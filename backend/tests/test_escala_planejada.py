"""#122: escala planejada x plantao real — previsto, presente, ausencia, substituicao e cobertura.

Somente bancos descartaveis (SQLite em tmp_path; PostgreSQL via D3_TEST_POSTGRES_URL).
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, text

from .test_d3_admissao_migration import _migrate, _ref
from .test_d3_admissao import _client
from .test_d2_rotina import _headers, _new_id
from .test_operacao_escala import GESTOR, _ilpi_com_area, _ok, _template, _usuario
from src.infrastructure import models as m

HEAD = "025_escala_planejada"


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D3_TEST_POSTGRES_URL") else []))
def planejada_db(request, tmp_path):
    ref = _ref(request, tmp_path)
    _migrate(ref, target=HEAD)
    return ref


def _run(ref, operation):
    asyncio.run(_client(ref, operation))


def _agora():
    return datetime.now(timezone.utc)


async def _funcionario_id(db, user):
    return await db.scalar(select(m.Funcionario.id).where(m.Funcionario.usuario_id == user.id))


async def _escala_agora(client, hg, funcionario_id, area_id=None, tipo="regular"):
    """Escala que ja comecou e ainda nao terminou (inicio -1 h, fim +11 h)."""
    corpo = {"funcionario_id": funcionario_id, "inicio_previsto": (_agora() - timedelta(hours=1)).isoformat(),
             "fim_previsto": (_agora() + timedelta(hours=11)).isoformat(), "tipo": tipo}
    if area_id:
        corpo["area_id"] = area_id
    return await _ok(await client.post("/api/escala/previsto", headers=hg, json=corpo), 201)


def test_turno_e_data_no_fuso_da_ilpi_e_sobreposicao(planejada_db):
    async def op(client, db):
        ilpi, _, hg, ala_b = await _ilpi_com_area(client, db)
        ana, _ = await _usuario(db, ilpi, await _template(db, "cuidador"), "cuidador", "Ana Sintetica")
        f_ana = await _funcionario_id(db, ana)
        diurno = await _ok(await client.post("/api/escala/turnos", headers=hg, json={"nome": "Diurno", "hora_inicio": "07:00", "hora_fim": "19:00"}), 201)
        noturno = await _ok(await client.post("/api/escala/turnos", headers=hg, json={"nome": "Noturno", "hora_inicio": "19:00", "hora_fim": "07:00"}), 201)

        dia = await _ok(await client.post("/api/escala/previsto", headers=hg, json={
            "funcionario_id": f_ana, "turno_id": diurno["id"], "area_id": ala_b["id"], "data": "2030-01-15"}), 201)
        # 07:00-19:00 em Sao Paulo (UTC-3) = 10:00Z-22:00Z.
        assert (dia["inicio_previsto"][:16], dia["fim_previsto"][:16]) == ("2030-01-15T10:00", "2030-01-15T22:00")
        assert (dia["turno_nome"], dia["area_nome"], dia["estado"], dia["tipo"]) == ("Diurno", "Ala B", "prevista", "regular")
        noite = await _ok(await client.post("/api/escala/previsto", headers=hg, json={
            "funcionario_id": f_ana, "turno_id": noturno["id"], "data": "2030-01-16"}), 201)
        assert (noite["inicio_previsto"][:16], noite["fim_previsto"][:16]) == ("2030-01-16T22:00", "2030-01-17T10:00")
        # Mesma pessoa, horario sobreposto: recusado.
        r = await client.post("/api/escala/previsto", headers=hg, json={
            "funcionario_id": f_ana, "inicio_previsto": "2030-01-15T20:00:00+00:00", "fim_previsto": "2030-01-15T23:00:00+00:00"})
        assert r.status_code == 409, r.text
        assert (await client.post("/api/escala/previsto", headers=hg, json={"funcionario_id": f_ana})).status_code == 422

        visao = await _ok(await client.get("/api/escala/previsto", headers=hg, params={"dia": "2030-01-15"}))
        assert visao["fuso"] == "America/Sao_Paulo"
        assert [e["id"] for e in visao["escalas"]] == [dia["id"]]
        # O noturno do dia 16 toca o dia 17, nao o 15.
        assert [e["id"] for e in (await _ok(await client.get("/api/escala/previsto", headers=hg, params={"dia": "2030-01-17"})))["escalas"]] == [noite["id"]]
    _run(planejada_db, op)


def test_previsto_x_efetivo_presente_realizada_e_cobertura(planejada_db):
    async def op(client, db):
        ilpi, _, hg, ala_b = await _ilpi_com_area(client, db)
        cuidador = await _template(db, "cuidador")
        ana, h_ana = await _usuario(db, ilpi, cuidador, "cuidador", "Ana Sintetica")
        bruno, h_bruno = await _usuario(db, ilpi, cuidador, "cuidador_b", "Bruno Sintetico")
        escala = await _escala_agora(client, hg, await _funcionario_id(db, ana), ala_b["id"])
        assert escala["estado"] == "nao_iniciada"

        atual = await _ok(await client.get("/api/plantoes/atual", headers=h_ana))
        assert [e["id"] for e in atual["escalas_pendentes"]] == [escala["id"]]
        # Escala de outra pessoa nao pode ser cumprida por Bruno (inexistente para ele).
        assert (await client.post("/api/plantoes/iniciar", headers=h_bruno, json={"escala_id": escala["id"]})).status_code == 404

        plantao = await _ok(await client.post("/api/plantoes/iniciar", headers=h_ana, json={"escala_id": escala["id"]}), 201)
        assert plantao["escala_id"] == escala["id"]
        assert [r["area_nome"] for r in plantao["responsabilidades"]] == ["Ala B"], "a responsabilidade nasce na area da escala"
        assert (await _ok(await client.get("/api/plantoes/atual", headers=h_ana)))["escalas_pendentes"] == []

        # Cobertura: Bruno trabalha sem escala.
        avulso = await _ok(await client.post("/api/plantoes/iniciar", headers=h_bruno, json={}), 201)
        visao = await _ok(await client.get("/api/escala/previsto", headers=hg))
        assert [(e["funcionario_nome"], e["estado"]) for e in visao["escalas"]] == [("Ana Sintetica", "presente")]
        assert [p["id"] for p in visao["coberturas_sem_escala"]] == [avulso["id"]]

        await _ok(await client.post(f"/api/plantoes/{plantao['id']}/encerrar", headers=h_ana))
        visao = await _ok(await client.get("/api/escala/previsto", headers=hg))
        assert visao["escalas"][0]["estado"] == "realizada"
        # Cumprida nao se cancela nem se marca ausencia (historico preservado).
        assert (await client.post(f"/api/escala/previsto/{escala['id']}/cancelar", headers=hg, json={"motivo": "Erro"})).status_code == 409
        assert (await client.post(f"/api/escala/previsto/{escala['id']}/ausencia", headers=hg, json={"motivo": "Falta"})).status_code == 409
        # Escala extra de cobertura tambem e prevista.
        cobertura = await _escala_agora(client, hg, await _funcionario_id(db, bruno), tipo="cobertura")
        assert cobertura["tipo"] == "cobertura"
    _run(planejada_db, op)


def test_ausencia_e_substituicao_simples(planejada_db):
    async def op(client, db):
        ilpi, _, hg, ala_b = await _ilpi_com_area(client, db)
        cuidador = await _template(db, "cuidador")
        ana, h_ana = await _usuario(db, ilpi, cuidador, "cuidador", "Ana Sintetica")
        ju, h_ju = await _usuario(db, ilpi, cuidador, "cuidador_j", "Juliana Sintetica")
        bruno, _ = await _usuario(db, ilpi, cuidador, "cuidador_b", "Bruno Sintetico")
        f_ana, f_ju, f_bruno = [await _funcionario_id(db, u) for u in (ana, ju, bruno)]

        falta = await _escala_agora(client, hg, f_bruno, ala_b["id"])
        assert (await client.post(f"/api/escala/previsto/{falta['id']}/ausencia", headers=hg, json={"motivo": "x"})).status_code == 422
        ausente = await _ok(await client.post(f"/api/escala/previsto/{falta['id']}/ausencia", headers=hg, json={"motivo": "Atestado"}))
        assert (ausente["estado"], ausente["motivo"]) == ("ausente", "Atestado")

        original = await _escala_agora(client, hg, f_ana, ala_b["id"])
        assert (await client.post(f"/api/escala/previsto/{original['id']}/substituir", headers=hg,
                                  json={"funcionario_id": f_ana, "motivo": "Troca"})).status_code == 409
        par = await _ok(await client.post(f"/api/escala/previsto/{original['id']}/substituir", headers=hg,
                                          json={"funcionario_id": f_ju, "motivo": "Ana chamou em cima da hora"}), 201)
        antiga, nova = par
        assert (antiga["estado"], antiga["substituto_nome"], antiga["motivo"]) == ("substituida", "Juliana Sintetica", "Ana chamou em cima da hora")
        assert (nova["tipo"], nova["substitui_escala_id"], nova["area_nome"]) == ("substituicao", original["id"], "Ala B")
        assert (nova["inicio_previsto"], nova["fim_previsto"]) == (original["inicio_previsto"], original["fim_previsto"])
        assert (await client.post(f"/api/escala/previsto/{original['id']}/substituir", headers=hg,
                                  json={"funcionario_id": f_bruno, "motivo": "De novo"})).status_code == 409
        # A ausente nao pode ser cumprida; a substituta sim.
        assert (await client.post("/api/plantoes/iniciar", headers=h_ana, json={"escala_id": original["id"]})).status_code == 409
        plantao = await _ok(await client.post("/api/plantoes/iniciar", headers=h_ju, json={"escala_id": nova["id"]}), 201)
        assert plantao["escala_id"] == nova["id"]

        cancelada = await _escala_agora(client, hg, f_bruno)
        cancelada = await _ok(await client.post(f"/api/escala/previsto/{cancelada['id']}/cancelar", headers=hg, json={"motivo": "Escala duplicada"}))
        assert cancelada["estado"] == "cancelada"

        # Nada foi apagado e tudo foi auditado.
        assert await db.scalar(select(func.count()).select_from(m.Escala).where(m.Escala.ilpi_id == ilpi.id)) == 4
        acoes = set((await db.scalars(select(m.Auditoria.acao).where(m.Auditoria.ilpi_id == ilpi.id, m.Auditoria.entidade == "escalas"))).all())
        assert {"escalas.criar", "escalas.ausencia", "escalas.substituir", "escalas.cumprir", "escalas.cancelar"} <= acoes
    _run(planejada_db, op)


def test_rbac_e_isolamento_da_escala(planejada_db):
    async def op(client, db):
        ilpi_a, _, h_a, ala_a = await _ilpi_com_area(client, db, "ILPI A")
        ilpi_b, _, h_b, _ = await _ilpi_com_area(client, db, "ILPI B")
        ana, h_ana = await _usuario(db, ilpi_a, await _template(db, "cuidador"), "cuidador", "Ana Sintetica")
        bia, _ = await _usuario(db, ilpi_b, await _template(db, "cuidador"), "cuidador", "Bia Sintetica")
        escala_a = await _escala_agora(client, h_a, await _funcionario_id(db, ana), ala_a["id"])
        escala_b = await _escala_agora(client, h_b, await _funcionario_id(db, bia))

        # Cuidador le a escala, nao a gere.
        assert (await _ok(await client.get("/api/escala/previsto", headers=h_ana)))["escalas"][0]["id"] == escala_a["id"]
        assert (await client.post("/api/escala/previsto", headers=h_ana, json={"funcionario_id": escala_a["funcionario_id"]})).status_code == 403
        assert (await client.post(f"/api/escala/previsto/{escala_a['id']}/ausencia", headers=h_ana, json={"motivo": "Nao vou"})).status_code == 403
        # Outra ILPI: escala e funcionario inexistentes (404), e a visao do dia nao os mostra.
        assert (await client.post(f"/api/escala/previsto/{escala_b['id']}/ausencia", headers=h_a, json={"motivo": "Teste"})).status_code == 404
        assert (await client.post(f"/api/escala/previsto/{escala_a['id']}/substituir", headers=h_a,
                                  json={"funcionario_id": escala_b["funcionario_id"], "motivo": "Teste"})).status_code == 404
        assert (await client.post("/api/escala/previsto", headers=h_a, json={
            "funcionario_id": escala_b["funcionario_id"], "inicio_previsto": _agora().isoformat(),
            "fim_previsto": (_agora() + timedelta(hours=2)).isoformat()})).status_code == 404
        ids_a = {e["id"] for e in (await _ok(await client.get("/api/escala/previsto", headers=h_a)))["escalas"]}
        assert escala_b["id"] not in ids_a
    _run(planejada_db, op)


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D3_TEST_POSTGRES_URL") else []))
def pre025_db(request, tmp_path):
    ref = _ref(request, tmp_path)
    _migrate(ref, target="024_escala_estrutura")
    return ref


def test_025_cria_e_reverte_sem_apagar_planejamento(pre025_db):
    _migrate(pre025_db, target=HEAD)

    async def com_escala(client, db):
        ilpi, gestor, hg, _ = await _ilpi_com_area(client, db)
        await _escala_agora(client, hg, await _funcionario_id(db, gestor))
        assert await db.scalar(text("SELECT COUNT(*) FROM escalas")) == 1
    _run(pre025_db, com_escala)
    falha = _migrate(pre025_db, target="024_escala_estrutura", command="downgrade", success=False)
    assert "escalas tem historico" in falha.stdout + falha.stderr

    async def limpar(client, db):
        await db.execute(text("DELETE FROM escalas"))
        await db.commit()
    _run(pre025_db, limpar)
    _migrate(pre025_db, target="024_escala_estrutura", command="downgrade")
    _migrate(pre025_db, target=HEAD)


def test_revisao_motivo_dia_outro_ilpi_e_substituicao_de_novo(planejada_db):
    async def op(client, db):
        ilpi, _, hg, ala_b = await _ilpi_com_area(client, db)
        ilpi_b, _, h_b, ala_outra = await _ilpi_com_area(client, db, "ILPI B")
        cuidador = await _template(db, "cuidador")
        ana, h_ana = await _usuario(db, ilpi, cuidador, "cuidador", "Ana Sintetica")
        ju, _ = await _usuario(db, ilpi, cuidador, "cuidador_j", "Juliana Sintetica")
        bia, _ = await _usuario(db, ilpi, cuidador, "cuidador_b", "Bia Sintetica")
        f_ana, f_ju, f_bia = [await _funcionario_id(db, u) for u in (ana, ju, bia)]
        turno_b = await _ok(await client.post("/api/escala/turnos", headers=h_b, json={"nome": "Diurno", "hora_inicio": "07:00", "hora_fim": "19:00"}), 201)

        # Turno e area de outra ILPI: inexistentes (404).
        assert (await client.post("/api/escala/previsto", headers=hg, json={
            "funcionario_id": f_ana, "turno_id": turno_b["id"], "data": "2030-01-15"})).status_code == 404
        assert (await client.post("/api/escala/previsto", headers=hg, json={
            "funcionario_id": f_ana, "area_id": ala_outra["id"], "inicio_previsto": _agora().isoformat(),
            "fim_previsto": (_agora() + timedelta(hours=2)).isoformat()})).status_code == 404

        # Motivo de ausencia (pode ser dado de saude) so para quem gere a escala.
        falta = await _escala_agora(client, hg, f_bia)
        await _ok(await client.post(f"/api/escala/previsto/{falta['id']}/ausencia", headers=hg, json={"motivo": "Atestado medico"}))
        de_gestor = {e["id"]: e for e in (await _ok(await client.get("/api/escala/previsto", headers=hg)))["escalas"]}
        de_cuidadora = {e["id"]: e for e in (await _ok(await client.get("/api/escala/previsto", headers=h_ana)))["escalas"]}
        assert de_gestor[falta["id"]]["motivo"] == "Atestado medico"
        assert de_cuidadora[falta["id"]]["motivo"] is None and de_cuidadora[falta["id"]]["estado"] == "ausente"

        # Escala de amanha nao aparece como pendente nem se cumpre hoje; escala encerrada tambem nao.
        amanha = await _ok(await client.post("/api/escala/previsto", headers=hg, json={
            "funcionario_id": f_ana, "inicio_previsto": (_agora() + timedelta(days=2)).isoformat(),
            "fim_previsto": (_agora() + timedelta(days=2, hours=12)).isoformat()}), 201)
        assert amanha["id"] not in {e["id"] for e in (await _ok(await client.get("/api/plantoes/atual", headers=h_ana)))["escalas_pendentes"]}
        r = await client.post("/api/plantoes/iniciar", headers=h_ana, json={"escala_id": amanha["id"]})
        assert r.status_code == 409 and "outro dia" in r.text
        passada = await _ok(await client.post("/api/escala/previsto", headers=hg, json={
            "funcionario_id": f_ana, "inicio_previsto": (_agora() - timedelta(hours=10)).isoformat(),
            "fim_previsto": (_agora() - timedelta(hours=2)).isoformat()}), 201)
        r = await client.post("/api/plantoes/iniciar", headers=h_ana, json={"escala_id": passada["id"]})
        assert r.status_code == 409 and "terminou" in r.text
        # Escala de outra ILPI ao iniciar: inexistente.
        bia_b, _ = await _usuario(db, ilpi_b, cuidador, "cuidador", "Bia B")
        de_b = await _escala_agora(client, h_b, await _funcionario_id(db, bia_b))
        assert (await client.post("/api/plantoes/iniciar", headers=h_ana, json={"escala_id": de_b["id"]})).status_code == 404

        # Substituta cancelada libera nova substituicao.
        original = await _escala_agora(client, hg, f_ana, ala_b["id"])
        _, sub = await _ok(await client.post(f"/api/escala/previsto/{original['id']}/substituir", headers=hg,
                                             json={"funcionario_id": f_ju, "motivo": "Troca combinada"}), 201)
        await _ok(await client.post(f"/api/escala/previsto/{sub['id']}/cancelar", headers=hg, json={"motivo": "Juliana nao pode"}))
        _, sub2 = await _ok(await client.post(f"/api/escala/previsto/{original['id']}/substituir", headers=hg,
                                              json={"funcionario_id": f_bia, "motivo": "Bia cobre"}), 201)
        assert sub2["funcionario_nome"] == "Bia Sintetica"

        # Area da escala inativada depois: o plantao comeca sem area (nao bloqueia).
        ala_c = await _ok(await client.post("/api/escala/areas", headers=hg, json={"nome": "Ala C"}), 201)
        ju_hoje = await _ok(await client.post("/api/escala/previsto", headers=hg, json={
            "funcionario_id": f_ju, "area_id": ala_c["id"], "inicio_previsto": (_agora() - timedelta(minutes=30)).isoformat(),
            "fim_previsto": (_agora() + timedelta(hours=6)).isoformat()}), 201)
        await _ok(await client.patch(f"/api/escala/areas/{ala_c['id']}", headers=hg, json={"situacao": "inativa"}))
        h_ju = _headers(ju, ilpi_id=ilpi.id)
        plantao = await _ok(await client.post("/api/plantoes/iniciar", headers=h_ju, json={"escala_id": ju_hoje["id"]}), 201)
        assert plantao["escala_id"] == ju_hoje["id"] and plantao["responsabilidades"] == []
    _run(planejada_db, op)


def test_revisao_concorrencia_posse_e_motivo_em_branco(planejada_db):
    async def op(client, db):
        ilpi, _, hg, ala_b = await _ilpi_com_area(client, db)
        cuidador = await _template(db, "cuidador")
        ana, h_ana = await _usuario(db, ilpi, cuidador, "cuidador", "Ana Sintetica")
        ju, _ = await _usuario(db, ilpi, cuidador, "cuidador_j", "Juliana Sintetica")
        bruno, _ = await _usuario(db, ilpi, cuidador, "cuidador_b", "Bruno Sintetico")
        f_ana, f_ju, f_bruno = [await _funcionario_id(db, u) for u in (ana, ju, bruno)]

        # So espacos: 422 (antes virava 500 ao violar ck_escalas_motivo depois do strip).
        escala = await _escala_agora(client, hg, f_bruno, ala_b["id"])
        for rota, corpo in (("ausencia", {}), ("cancelar", {}), ("substituir", {"funcionario_id": f_ju})):
            r = await client.post(f"/api/escala/previsto/{escala['id']}/{rota}", headers=hg, json={**corpo, "motivo": "     "})
            assert r.status_code == 422, (rota, r.text)

        # Duas transicoes ao mesmo tempo na mesma escala: uma vence, a outra recebe 409 (nunca 500).
        respostas = await asyncio.gather(
            client.post(f"/api/escala/previsto/{escala['id']}/substituir", headers=hg, json={"funcionario_id": f_ju, "motivo": "Troca A"}),
            client.post(f"/api/escala/previsto/{escala['id']}/cancelar", headers=hg, json={"motivo": "Cancelamento B"}))
        codigos = sorted(r.status_code for r in respostas)
        assert codigos in ([200, 409], [201, 409]), [r.text for r in respostas]
        # Dois planejamentos sobrepostos da mesma pessoa ao mesmo tempo: um so entra.
        inicio = _agora() + timedelta(hours=30)
        corpo = {"funcionario_id": f_ana, "inicio_previsto": inicio.isoformat(),
                 "fim_previsto": (inicio + timedelta(hours=6)).isoformat(), "area_id": ala_b["id"]}
        duplas = await asyncio.gather(client.post("/api/escala/previsto", headers=hg, json=corpo),
                                      client.post("/api/escala/previsto", headers=hg, json=corpo))
        assert sorted(r.status_code for r in duplas) == [201, 409], [r.text for r in duplas]

        # Escala de outra pessoa, mesmo ja encerrada (nao prevista): 404 antes de qualquer 409 de estado.
        assert (await client.post("/api/plantoes/iniciar", headers=h_ana, json={"escala_id": escala["id"]})).status_code == 404
    _run(planejada_db, op)
