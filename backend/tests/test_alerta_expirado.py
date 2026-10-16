"""#132: cuidado/dose que sai da janela de 24 h sem registro encerra o estado como
``expirado`` (encerramento ``janela``), nunca como "resolvido pela fonte".

Somente bancos descartaveis (SQLite em tmp_path; PostgreSQL via D3_TEST_POSTGRES_URL).
"""

import asyncio
import os
from datetime import timedelta

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from .test_alertas_gestor import GESTOR, _agora, _alertas, _gestor, _residente
from .test_d2_rotina import _create_funcionario, _new_id, _prog_payload, _setup_pais_vigente
from .test_d3_admissao import _client
from .test_d3_admissao_migration import _migrate, _ref
from src.infrastructure import models as m

HEAD = "028_alerta_expirado"
URL = "/api/central-alertas"


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D3_TEST_POSTGRES_URL") else []))
def expirado_db(request, tmp_path):
    ref = _ref(request, tmp_path)
    _migrate(ref, target=HEAD)
    return ref


def _run(ref, operation):
    asyncio.run(_client(ref, operation))


async def _cuidado_na_janela(client, db):
    """Um residente com exatamente UM cuidado atrasado dentro da janela (as demais ocorrencias no futuro)."""
    ilpi, _, h = await _gestor(db, "ILPI Expirado", permissions=GESTOR | {"alertas:assumir"})
    res = await _residente(db, ilpi.id, "Elza Sintetica")
    revisor = await _create_funcionario(db, ilpi)
    await db.commit()
    pais_id, intervencao_id = await _setup_pais_vigente(client, h, res.id, revisor.id)
    r = await client.post("/api/programacoes-cuidado/", headers=h, json=_prog_payload(pais_id, intervencao_id, inicio_horas=-3))
    assert r.status_code == 201, r.text
    ocorrencias = (await db.scalars(select(m.OcorrenciaCuidado).where(
        m.OcorrenciaCuidado.programacao_id == r.json()["id"]).order_by(m.OcorrenciaCuidado.previsto_em))).all()
    for n, ocorrencia in enumerate(ocorrencias[1:], start=1):
        await db.execute(update(m.OcorrenciaCuidado).where(m.OcorrenciaCuidado.id == ocorrencia.id)
                         .values(previsto_em=_agora() + timedelta(days=3, minutes=n)))
    alvo = ocorrencias[0]
    await db.execute(update(m.OcorrenciaCuidado).where(m.OcorrenciaCuidado.id == alvo.id)
                     .values(previsto_em=_agora() - timedelta(hours=2)))
    await db.commit()
    return h, res, alvo


async def _estado(db, alerta_id):
    return (await db.execute(select(m.AlertaEstado.situacao, m.AlertaEstado.encerramento).where(
        m.AlertaEstado.alerta_id == alerta_id).order_by(m.AlertaEstado.assumido_em.desc())
        .execution_options(populate_existing=True))).first()


def test_saiu_da_janela_sem_registro_expira_e_registro_resolve(expirado_db):
    async def op(client, db):
        h, res, alvo = await _cuidado_na_janela(client, db)
        alerta = f"cuidados_sem_registro:{res.id}"
        assert alerta in {a["id"] for a in (await _alertas(client, h))["alertas"]}
        assert (await client.post(f"{URL}/assumir", headers=h, json={"alerta_id": alerta})).status_code == 200

        # O tempo passa: o cuidado sai da janela de 24 h SEM execucao (assumido ha 3 h).
        await db.execute(update(m.AlertaEstado).where(m.AlertaEstado.alerta_id == alerta)
                         .values(assumido_em=_agora() - timedelta(hours=3)))
        await db.execute(update(m.OcorrenciaCuidado).where(m.OcorrenciaCuidado.id == alvo.id)
                         .values(previsto_em=_agora() - timedelta(hours=25)))
        await db.commit()
        assert alerta not in {a["id"] for a in (await _alertas(client, h))["alertas"]}
        assert tuple(await _estado(db, alerta)) == ("expirado", "janela"), "sumir da janela nao e resolver"
        auditoria = set((await db.scalars(select(m.Auditoria.acao).where(m.Auditoria.entidade == "alerta_estados"))).all())
        assert "alerta_estados.expirado_sem_registro" in auditoria
        hist = (await client.get(f"{URL}/historico", headers=h, params={"alerta_id": alerta})).json()
        assert [(e["situacao"], e["encerramento"]) for e in hist] == [("expirado", "janela")]

        # Novo episodio: o cuidado volta a estar atrasado na janela e desta vez e EXECUTADO -> resolvido.
        await db.execute(update(m.OcorrenciaCuidado).where(m.OcorrenciaCuidado.id == alvo.id)
                         .values(previsto_em=_agora() - timedelta(hours=2)))
        await db.commit()
        assert (await client.post(f"{URL}/assumir", headers=h, json={"alerta_id": alerta})).status_code == 200
        r = await client.post("/api/execucoes-cuidado/", headers=h, json={
            "ocorrencia_id": alvo.id, "resultado": "executada", "ocorrido_em": _agora().isoformat()})
        assert r.status_code == 201, r.text
        assert alerta not in {a["id"] for a in (await _alertas(client, h))["alertas"]}
        assert tuple(await _estado(db, alerta)) == ("resolvido", "fonte")
    _run(expirado_db, op)


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D3_TEST_POSTGRES_URL") else []))
def pre028_db(request, tmp_path):
    ref = _ref(request, tmp_path)
    _migrate(ref, target="027_passagem_plantao")
    return ref


def test_028_amplia_checks_mantem_indice_e_recusa_downgrade_com_expirado(pre028_db):
    _migrate(pre028_db, target=HEAD)

    async def depois(client, db):
        ilpi, gestor, _ = await _gestor(db, "ILPI 028")
        base = dict(ilpi_id=ilpi.id, regra="cuidados_sem_registro", assumido_por=gestor.id, assumido_em=_agora())
        db.add(m.AlertaEstado(id=_new_id(), alerta_id="cuidados_sem_registro:x", situacao="expirado",
                              encerramento="janela", encerrado_em=_agora(), **base))
        await db.commit()
        # expirado exige encerramento 'janela'
        db.add(m.AlertaEstado(id=_new_id(), alerta_id="cuidados_sem_registro:y", situacao="expirado",
                              encerramento="fonte", encerrado_em=_agora(), **base))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()
        # O indice unico parcial continua valendo depois da recriacao da tabela: um aberto por alerta.
        db.add(m.AlertaEstado(id=_new_id(), alerta_id="cuidados_sem_registro:z", situacao="assumido", **base))
        await db.commit()
        db.add(m.AlertaEstado(id=_new_id(), alerta_id="cuidados_sem_registro:z", situacao="assumido", **base))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()
    asyncio.run(_client(pre028_db, depois))
    falha = _migrate(pre028_db, target="027_passagem_plantao", command="downgrade", success=False)
    assert "ha estados 'expirado'" in falha.stdout + falha.stderr

    async def limpar(client, db):
        await db.execute(text("DELETE FROM alerta_estados WHERE situacao = 'expirado'"))
        await db.commit()
    asyncio.run(_client(pre028_db, limpar))
    _migrate(pre028_db, target="027_passagem_plantao", command="downgrade")

    async def voltou(client, db):
        ilpi, gestor, _ = await _gestor(db, "ILPI 027 de volta")
        db.add(m.AlertaEstado(id=_new_id(), ilpi_id=ilpi.id, alerta_id="cuidados_sem_registro:w", regra="cuidados_sem_registro",
                              assumido_por=gestor.id, assumido_em=_agora(), situacao="expirado",
                              encerramento="janela", encerrado_em=_agora()))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()
    asyncio.run(_client(pre028_db, voltou))


def test_item_anterior_a_janela_do_episodio_nao_expira_o_estado(expirado_db):
    async def op(client, db):
        h, res, alvo = await _cuidado_na_janela(client, db)
        alerta = f"cuidados_sem_registro:{res.id}"
        # Outra ocorrencia pendente muito antiga (fora da janela de quando o alerta foi assumido).
        antiga = (await db.scalars(select(m.OcorrenciaCuidado).where(
            m.OcorrenciaCuidado.programacao_id == alvo.programacao_id, m.OcorrenciaCuidado.id != alvo.id))).first()
        await db.execute(update(m.OcorrenciaCuidado).where(m.OcorrenciaCuidado.id == antiga.id)
                         .values(previsto_em=_agora() - timedelta(hours=30)))
        await db.commit()
        assert (await client.post(f"{URL}/assumir", headers=h, json={"alerta_id": alerta})).status_code == 200
        # O alvo e executado; a antiga ja estava fora da janela do episodio -> resolvido, nao expirado.
        r = await client.post("/api/execucoes-cuidado/", headers=h, json={
            "ocorrencia_id": alvo.id, "resultado": "executada", "ocorrido_em": _agora().isoformat()})
        assert r.status_code == 201, r.text
        await _alertas(client, h)
        await _alertas(client, h)
        assert tuple(await _estado(db, alerta)) == ("resolvido", "fonte")
        encerramentos = (await db.scalars(select(m.Auditoria.acao).where(
            m.Auditoria.acao.in_(("alerta_estados.resolvido_pela_fonte", "alerta_estados.expirado_sem_registro"))))).all()
        assert len(encerramentos) == 1, "duas consultas, uma auditoria"
    _run(expirado_db, op)
