"""#123: estado persistente do alerta — assumir, em atendimento, liberar e resolucao pela fonte.

Fonte -> projecao (id estavel) -> estado. O estado nunca cria nem mantem alerta:
quando a fonte resolve, a projecao deixa de gerar o id e o estado aberto vira
``resolvido`` (encerramento ``fonte``), auditado, sem clique manual.

Somente bancos descartaveis (SQLite em tmp_path; PostgreSQL via D3_TEST_POSTGRES_URL).
"""

import asyncio
import os
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError

from .test_alertas_gestor import _agora, _alertas, _gestor, _residente, _run, _um, alertas_db  # noqa: F401
from .test_alertas_operacionais import _institucional
from .test_d2_rotina import _create_ilpi_user, _headers, _new_id, _new_institution
from .test_d3_admissao import _client
from .test_d3_admissao_migration import _migrate, _ref
from src.infrastructure import models as m

URL = "/api/central-alertas"


async def _cenario(db, nome="ILPI Estado"):
    ilpi, gestor, h_gestor = await _gestor(db, nome)
    res = await _residente(db, ilpi.id, "Hilda Sintetica", situacao="Em admissao")
    queda = m.Intercorrencia(id=_new_id(), residente_id=res.id, ilpi_id=ilpi.id, tipo="Queda", gravidade="grave",
                             situacao="aberta", ocorrido_em=_agora() - timedelta(minutes=30))
    rg = m.Documento(id=_new_id(), residente_id=res.id, instituicao_id=ilpi.id, tipo="RG", obrigatorio=True, situacao="pendente")
    db.add_all([queda, rg])
    await db.commit()
    return ilpi, h_gestor, queda, rg


async def _acao(client, h, acao, alerta_id, status=200):
    r = await client.post(f"{URL}/{acao}", headers=h, json={"alerta_id": alerta_id})
    assert r.status_code == status, r.text
    return r.json()


def _estado_de(payload, alerta_id):
    return next(a for a in payload["alertas"] if a["id"] == alerta_id)["estado"]


def test_assumir_atender_liberar_e_equipe_ve_quem_assumiu(alertas_db):
    async def op(client, db):
        ilpi, _, queda, _ = await _cenario(db)
        _, h_ana, ana = await _institucional(db, ilpi, "cuidador")
        _, h_bruno, _ = await _institucional(db, ilpi, "enfermagem")
        alerta = f"intercorrencia_grave_aberta:{queda.id}"
        assert _estado_de(await _alertas(client, h_ana), alerta) is None, "novo = ninguem assumiu"

        assumido = await _acao(client, h_ana, "assumir", alerta)
        assert (assumido["estado"]["situacao"], assumido["estado"]["por_nome"], assumido["estado"]["por_mim"]) == (
            "assumido", "cuidador sintetico", True)
        # A equipe ve quem assumiu; so para quem assumiu e "por mim".
        visto = _estado_de(await _alertas(client, h_bruno), alerta)
        assert (visto["situacao"], visto["por_nome"], visto["por_mim"]) == ("assumido", "cuidador sintetico", False)
        conflito = await _acao(client, h_bruno, "assumir", alerta, status=409)
        assert "cuidador sintetico" in conflito["detail"]["message"]
        # Liberar e so do titular (ou de quem gere a escala).
        await _acao(client, h_bruno, "liberar", alerta, status=403)

        atendendo = await _acao(client, h_ana, "atender", alerta)
        assert atendendo["estado"]["situacao"] == "em_atendimento" and atendendo["estado"]["em_atendimento_em"]
        assert _estado_de(await _alertas(client, h_bruno), alerta)["situacao"] == "em_atendimento"
        # Idempotente para o titular.
        assert (await _acao(client, h_ana, "assumir", alerta))["estado"]["situacao"] == "em_atendimento"

        liberado = await _acao(client, h_ana, "liberar", alerta)
        assert liberado["estado"] is None
        assert _estado_de(await _alertas(client, h_bruno), alerta) is None, "volta a ser novo para a equipe"
        # Bruno assume de uma vez ja em atendimento.
        assert (await _acao(client, h_bruno, "atender", alerta))["estado"]["situacao"] == "em_atendimento"

        # Coordenacao da escala libera o de outra pessoa.
        coord = await _create_ilpi_user(db, ilpi, profile_key="coordenacao", nome="Coordenadora Sintetica", permissions={
            "alertas:ler", "alertas:assumir", "intercorrencias:ler", "residentes:ler", "escala:gerenciar"})
        await db.commit()
        assert (await _acao(client, _headers(coord, ilpi_id=ilpi.id), "liberar", alerta))["estado"] is None

        historico = (await client.get(f"{URL}/historico", headers=h_ana, params={"alerta_id": alerta})).json()
        assert [(e["situacao"], e["encerramento"]) for e in historico] == [("liberado", "liberado"), ("liberado", "liberado")]
        acoes = sorted((await db.scalars(select(m.Auditoria.acao).where(
            m.Auditoria.ilpi_id == ilpi.id, m.Auditoria.entidade == "alerta_estados"))).all())
        assert acoes == sorted(["alerta_estados.assumir", "alerta_estados.atender", "alerta_estados.liberar",
                                "alerta_estados.atender", "alerta_estados.liberar"])
    _run(alertas_db, op)


def test_resolucao_pela_fonte_encerra_o_estado_e_novo_episodio(alertas_db):
    async def op(client, db):
        ilpi, _, queda, _ = await _cenario(db)
        _, h_ana, _ = await _institucional(db, ilpi, "cuidador")
        alerta = f"intercorrencia_grave_aberta:{queda.id}"
        await _acao(client, h_ana, "atender", alerta)

        # A fonte resolve (intercorrencia encerrada no modulo de origem).
        await db.execute(update(m.Intercorrencia).where(m.Intercorrencia.id == queda.id)
                         .values(situacao="encerrada", desfecho="Resolvido em teste"))
        await db.commit()
        depois = await _alertas(client, h_ana)
        assert alerta not in {a["id"] for a in depois["alertas"]}
        [estado] = (await db.scalars(select(m.AlertaEstado).where(m.AlertaEstado.alerta_id == alerta)
                                     .execution_options(populate_existing=True))).all()
        assert (estado.situacao, estado.encerramento) == ("resolvido", "fonte") and estado.encerrado_em is not None
        auditoria = (await db.scalars(select(m.Auditoria).where(
            m.Auditoria.registro_id == estado.id, m.Auditoria.acao == "alerta_estados.resolvido_pela_fonte"))).all()
        assert len(auditoria) == 1 and auditoria[0].usuario_id is None, "quem encerrou foi a fonte"
        # Idempotente: outra consulta nao audita de novo.
        await _alertas(client, h_ana)
        assert await db.scalar(select(func.count()).select_from(m.Auditoria).where(
            m.Auditoria.acao == "alerta_estados.resolvido_pela_fonte")) == 1

        # A situacao volta a existir (mesmo id): novo episodio, sem herdar "em atendimento".
        await db.execute(update(m.Intercorrencia).where(m.Intercorrencia.id == queda.id).values(situacao="aberta"))
        await db.commit()
        assert _estado_de(await _alertas(client, h_ana), alerta) is None
        await _acao(client, h_ana, "assumir", alerta)
        historico = (await client.get(f"{URL}/historico", headers=h_ana, params={"alerta_id": alerta})).json()
        assert [e["situacao"] for e in historico] == ["resolvido", "assumido"]
    _run(alertas_db, op)


def test_so_regras_avaliadas_encerram_estado(alertas_db):
    async def op(client, db):
        ilpi, _, _, rg = await _cenario(db)
        _, h_adm, _ = await _institucional(db, ilpi, "administrativo")
        _, h_ana, _ = await _institucional(db, ilpi, "cuidador")
        alerta = f"documento_aguardando_validacao:{rg.id}"
        await _acao(client, h_adm, "assumir", alerta)
        # A cuidadora nao le documentos: a ausencia do alerta na projecao dela nao prova nada.
        assert alerta not in {a["id"] for a in (await _alertas(client, h_ana))["alertas"]}
        assert _estado_de(await _alertas(client, h_adm), alerta)["situacao"] == "assumido"
        # Nem pode agir sobre ele (RBAC por origem) — nem ver o historico.
        await _acao(client, h_ana, "assumir", alerta, status=404)
        assert (await client.get(f"{URL}/historico", headers=h_ana, params={"alerta_id": alerta})).status_code == 404
        await _acao(client, h_ana, "assumir", "intercorrencia_grave_aberta:nao-existe", status=404)
        so_ler = await _create_ilpi_user(db, ilpi, profile_key="so_ler", permissions={"alertas:ler", "documentos:ler"})
        await db.commit()
        await _acao(client, _headers(so_ler, ilpi_id=ilpi.id), "assumir", alerta, status=403)
    _run(alertas_db, op)


def test_um_estado_aberto_por_alerta_e_isolamento(alertas_db):
    async def op(client, db):
        ilpi_a, _, queda_a, _ = await _cenario(db, "ILPI A")
        ilpi_b, _, queda_b, _ = await _cenario(db, "ILPI B")
        _, h_a, ana = await _institucional(db, ilpi_a, "cuidador")
        _, h_b, _ = await _institucional(db, ilpi_b, "cuidador")
        alerta_a = f"intercorrencia_grave_aberta:{queda_a.id}"
        await _acao(client, h_a, "assumir", alerta_a)
        # Outra ILPI: o alerta nao existe para ela e o estado da A nao aparece.
        await _acao(client, h_b, "assumir", alerta_a, status=404)
        assert all(a["estado"] is None for a in (await _alertas(client, h_b))["alertas"])
        assert (await client.post(f"{URL}/assumir", headers=_headers(ana, ilpi_id=ilpi_b.id),
                                  json={"alerta_id": f"intercorrencia_grave_aberta:{queda_b.id}"})).status_code == 403
        # O banco garante um so estado aberto por alerta (duas pessoas ao mesmo tempo).
        dono = await db.scalar(select(m.AlertaEstado.assumido_por).where(m.AlertaEstado.alerta_id == alerta_a))
        db.add(m.AlertaEstado(ilpi_id=ilpi_a.id, alerta_id=alerta_a, regra="intercorrencia_grave_aberta",
                              situacao="assumido", assumido_por=dono, assumido_em=_agora()))
        with pytest.raises(IntegrityError):
            await db.commit()
        await db.rollback()
    _run(alertas_db, op)


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D3_TEST_POSTGRES_URL") else []))
def pre026_db(request, tmp_path):
    ref = _ref(request, tmp_path)
    _migrate(ref, target="025_escala_planejada")
    return ref


def test_026_concede_cria_e_reverte(pre026_db):
    _migrate(pre026_db, target="026_alerta_estados")

    async def depois(client, db):
        chaves = set((await db.scalars(
            select(m.Perfil.chave).join(m.PerfilPermissao, m.PerfilPermissao.perfil_id == m.Perfil.id)
            .join(m.Permissao, m.Permissao.id == m.PerfilPermissao.permissao_id)
            .where(m.Permissao.chave == "alertas:assumir", m.Perfil.ilpi_id.is_(None)))).all())
        assert chaves == {"ilpi_admin", "cuidador", "enfermagem", "medico", "responsavel_tecnico", "administrativo"}
        ilpi, _, queda, _ = await _cenario(db)
        _, h, _ = await _institucional(db, ilpi, "cuidador")
        await _acao(client, h, "assumir", f"intercorrencia_grave_aberta:{queda.id}")
    asyncio.run(_client(pre026_db, depois))
    falha = _migrate(pre026_db, target="025_escala_planejada", command="downgrade", success=False)
    assert "alerta_estados tem historico" in falha.stdout + falha.stderr
