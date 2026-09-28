"""#120: estrutura operacional — areas, leitos da area, turnos, plantao real e responsabilidade.

Cobre: RBAC (escala:ler/gerenciar, plantao:registrar) independente da
responsabilidade, tenant (404 cross-tenant), vinculo area<->leito com vigencia
(um leito em uma area ativa por vez), plantao real (um em andamento por
funcionario), responsabilidade append-only e consulta historica "quem
respondia pela area no instante T" (Ana 07-15, Juliana a partir das 15).

Somente bancos descartaveis (SQLite em tmp_path; PostgreSQL via D3_TEST_POSTGRES_URL).
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, update

from .test_d3_admissao_migration import _migrate, _ref
from .test_d3_admissao import _client
from .test_d2_rotina import _create_ilpi_user, _headers, _new_id, _new_institution
from src.infrastructure import models as m

HEAD = "025_escala_planejada"
GESTOR = {"escala:ler", "escala:gerenciar", "plantao:registrar", "residentes:ler",
          "quartos_leitos:ler", "quartos_leitos:criar", "quartos_leitos:atualizar"}


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D3_TEST_POSTGRES_URL") else []))
def escala_db(request, tmp_path):
    ref = _ref(request, tmp_path)
    _migrate(ref, target=HEAD)
    return ref


def _run(ref, operation):
    asyncio.run(_client(ref, operation))


def _agora():
    return datetime.now(timezone.utc)


async def _usuario(db, ilpi, permissoes, chave, nome):
    user = await _create_ilpi_user(db, ilpi, permissions=permissoes, profile_key=chave, nome=nome)
    await db.commit()
    return user, _headers(user, ilpi_id=ilpi.id)


async def _template(db, chave):
    return set((await db.scalars(
        select(m.Permissao.chave).join(m.PerfilPermissao, m.PerfilPermissao.permissao_id == m.Permissao.id)
        .join(m.Perfil, m.Perfil.id == m.PerfilPermissao.perfil_id)
        .where(m.Perfil.chave == chave, m.Perfil.ilpi_id.is_(None)))).all())


async def _ok(resposta, status=200):
    assert resposta.status_code == status, resposta.text
    return resposta.json()


async def _ilpi_com_area(client, db, nome="ILPI Escala"):
    ilpi = _new_institution(nome)
    gestor, hg = await _usuario(db, ilpi, GESTOR, "gestor_escala", "Gestora Sintetica")
    area = await _ok(await client.post("/api/escala/areas", headers=hg, json={"nome": "Ala B", "tipo": "ala"}), 201)
    return ilpi, gestor, hg, area


def test_areas_leitos_e_turnos(escala_db):
    async def op(client, db):
        ilpi, _, hg, ala_b = await _ilpi_com_area(client, db)
        assert ala_b["situacao"] == "ativa" and ala_b["leitos"] == []
        assert (await client.post("/api/escala/areas", headers=hg, json={"nome": "Ala B"})).status_code == 409
        setor = await _ok(await client.post("/api/escala/areas", headers=hg, json={"nome": "Enfermaria", "tipo": "setor"}), 201)

        leito = await _ok(await client.post("/api/quartos_leitos/", headers=hg, json={"unidade": "Bloco 1", "quarto": "12", "leito": "A"}), 201)
        com_leito = await _ok(await client.post(f"/api/escala/areas/{ala_b['id']}/leitos", headers=hg,
                                                json={"quarto_leito_id": leito["id"]}), 201)
        assert [(l["quarto"], l["leito"], l["unidade"]) for l in com_leito["leitos"]] == [("12", "A", "Bloco 1")]
        # Um leito so pertence a uma area ativa por vez.
        r = await client.post(f"/api/escala/areas/{setor['id']}/leitos", headers=hg, json={"quarto_leito_id": leito["id"]})
        assert r.status_code == 409, r.text
        # Remover encerra a vigencia; o historico continua.
        sem = await _ok(await client.post(f"/api/escala/areas/{ala_b['id']}/leitos/{leito['id']}/remover", headers=hg))
        assert sem["leitos"] == []
        movido = await _ok(await client.post(f"/api/escala/areas/{setor['id']}/leitos", headers=hg,
                                             json={"quarto_leito_id": leito["id"]}), 201)
        assert len(movido["leitos"]) == 1
        vinculos = (await db.scalars(select(m.AreaLeito).where(m.AreaLeito.quarto_leito_id == leito["id"])
                                     .order_by(m.AreaLeito.inicio_em))).all()
        assert [(v.area_id, v.fim_em is None) for v in vinculos] == [(ala_b["id"], False), (setor["id"], True)]

        diurno = await _ok(await client.post("/api/escala/turnos", headers=hg,
                                             json={"nome": "Diurno", "hora_inicio": "07:00", "hora_fim": "19:00"}), 201)
        noturno = await _ok(await client.post("/api/escala/turnos", headers=hg,
                                              json={"nome": "Noturno", "hora_inicio": "19:00", "hora_fim": "07:00"}), 201)
        assert noturno["hora_fim"] == "07:00"  # cruza a meia-noite
        assert (await client.post("/api/escala/turnos", headers=hg, json={"nome": "X", "hora_inicio": "25:00", "hora_fim": "07:00"})).status_code == 422
        assert (await client.post("/api/escala/turnos", headers=hg, json={"nome": "Y", "hora_inicio": "07:00", "hora_fim": "07:00"})).status_code == 422
        assert (await client.post("/api/escala/turnos", headers=hg, json={"nome": "Diurno", "hora_inicio": "06:00", "hora_fim": "18:00"})).status_code == 409
        inativo = await _ok(await client.patch(f"/api/escala/turnos/{diurno['id']}", headers=hg, json={"situacao": "inativo"}))
        assert inativo["situacao"] == "inativo"

        auditadas = set((await db.scalars(select(m.Auditoria.acao).where(m.Auditoria.ilpi_id == ilpi.id))).all())
        assert {"areas_operacionais.criar", "area_leitos.vincular", "area_leitos.desvincular",
                "turnos.criar", "turnos.atualizar"} <= auditadas
    _run(escala_db, op)


def test_plantao_real_e_responsabilidade(escala_db):
    async def op(client, db):
        ilpi, _, hg, ala_b = await _ilpi_com_area(client, db)
        turno = await _ok(await client.post("/api/escala/turnos", headers=hg,
                                            json={"nome": "Diurno", "hora_inicio": "07:00", "hora_fim": "19:00"}), 201)
        _, hc = await _usuario(db, ilpi, await _template(db, "cuidador"), "cuidador", "Ana Sintetica")

        assert (await _ok(await client.get("/api/plantoes/atual", headers=hc)))["plantao"] is None
        # Quem so registra o proprio plantao ve os turnos para escolher.
        assert [t["nome"] for t in await _ok(await client.get("/api/escala/turnos", headers=hc))] == ["Diurno"]
        plantao = await _ok(await client.post("/api/plantoes/iniciar", headers=hc,
                                              json={"area_ids": [ala_b["id"]], "turno_id": turno["id"]}), 201)
        assert plantao["situacao"] == "em_andamento" and plantao["turno_nome"] == "Diurno"
        assert [(r["area_nome"], r["funcionario_nome"]) for r in plantao["responsabilidades"]] == [("Ala B", "Ana Sintetica")]
        assert (await client.post("/api/plantoes/iniciar", headers=hc, json={})).status_code == 409

        atual = await _ok(await client.get("/api/plantoes/atual", headers=hc))
        assert atual["pode_registrar"] is True and atual["plantao"]["id"] == plantao["id"]
        agora = await _ok(await client.get("/api/escala/agora", headers=hc))
        assert [(a["area"]["nome"], [r["funcionario_nome"] for r in a["responsaveis"]]) for a in agora["areas"]] == [("Ala B", ["Ana Sintetica"])]

        # Cuidador nao gere a escala nem encerra plantao alheio.
        assert (await client.post("/api/escala/areas", headers=hc, json={"nome": "Ala C"})).status_code == 403
        encerrado = await _ok(await client.post(f"/api/plantoes/{plantao['id']}/encerrar", headers=hc))
        assert encerrado["situacao"] == "encerrado" and encerrado["fim_em"]
        [resp] = encerrado["responsabilidades"]
        assert resp["motivo_fim"] == "fim_plantao" and resp["fim_em"] == encerrado["fim_em"]
        assert (await client.post(f"/api/plantoes/{plantao['id']}/encerrar", headers=hc)).status_code == 409
        assert (await _ok(await client.get("/api/plantoes/atual", headers=hc)))["plantao"] is None

        auditadas = [a for a in (await db.scalars(select(m.Auditoria.acao).where(m.Auditoria.ilpi_id == ilpi.id))).all()]
        assert {"plantoes.iniciar", "plantoes.encerrar", "responsabilidades.abrir", "responsabilidades.encerrar"} <= set(auditadas)
    _run(escala_db, op)


def test_troca_de_responsavel_nao_reescreve_o_passado(escala_db):
    async def op(client, db):
        ilpi, _, hg, ala_b = await _ilpi_com_area(client, db)
        cuidador = await _template(db, "cuidador")
        _, h_ana = await _usuario(db, ilpi, cuidador, "cuidador", "Ana Sintetica")
        _, h_ju = await _usuario(db, ilpi, cuidador | set(), "cuidador_2", "Juliana Sintetica")
        ana = await _ok(await client.post("/api/plantoes/iniciar", headers=h_ana, json={"area_ids": [ala_b["id"]]}), 201)
        ju = await _ok(await client.post("/api/plantoes/iniciar", headers=h_ju, json={}), 201)
        # Ana responde desde as 07:00 (instante sintetico no passado).
        sete = _agora() - timedelta(hours=8)
        await db.execute(update(m.Plantao).where(m.Plantao.id == ana["id"]).values(inicio_em=sete))
        await db.execute(update(m.Responsabilidade).where(m.Responsabilidade.plantao_id == ana["id"]).values(inicio_em=sete))
        await db.commit()
        evento = sete + timedelta(hours=7, minutes=10)  # "14:10"

        ana_func = ana["funcionario_id"]
        depois = await _ok(await client.post("/api/escala/responsabilidades/transferir", headers=hg, json={
            "area_id": ala_b["id"], "para_plantao_id": ju["id"], "de_funcionario_id": ana_func}))
        assert [r["funcionario_nome"] for r in depois] == ["Juliana Sintetica"]
        troca = datetime.fromisoformat(depois[0]["inicio_em"])

        async def quem(instante):
            r = await client.get("/api/escala/responsaveis", headers=hg,
                                 params={"area_id": ala_b["id"], "em": instante.isoformat()})
            return [x["funcionario_nome"] for x in await _ok(r)]

        assert await quem(evento) == ["Ana Sintetica"], "o historico das 14:10 continua mostrando Ana"
        assert await quem(troca - timedelta(seconds=1)) == ["Ana Sintetica"]
        assert await quem(troca) == ["Juliana Sintetica"]  # vigencia semiaberta: sem sobreposicao
        assert await quem(sete - timedelta(minutes=1)) == []

        linha_ana = (await db.scalars(select(m.Responsabilidade).where(m.Responsabilidade.plantao_id == ana["id"]))).one()
        assert linha_ana.motivo_fim == "transferencia" and linha_ana.inicio_em.replace(tzinfo=timezone.utc) == sete
        # Append-only: vigencia encerrada nao se reabre nem se reencerra.
        assert (await client.post(f"/api/escala/responsabilidades/{linha_ana.id}/encerrar", headers=hg)).status_code == 409
        # Area com responsavel nao inativa sem transferir antes.
        assert (await client.patch(f"/api/escala/areas/{ala_b['id']}", headers=hg, json={"situacao": "inativa"})).status_code == 409
        # Cobertura: um segundo profissional passa a responder junto.
        ana_ainda = await _ok(await client.post("/api/escala/responsabilidades/transferir", headers=hg, json={
            "area_id": ala_b["id"], "para_plantao_id": ana["id"]}))
        assert sorted(r["funcionario_nome"] for r in ana_ainda) == ["Ana Sintetica", "Juliana Sintetica"]
        assert (await client.post("/api/escala/responsabilidades/transferir", headers=hg, json={
            "area_id": ala_b["id"], "para_plantao_id": ana["id"]})).status_code == 409
    _run(escala_db, op)


def test_responsabilidade_nao_concede_acesso_e_rbac(escala_db):
    async def op(client, db):
        ilpi, _, hg, ala_b = await _ilpi_com_area(client, db)
        # So escala:ler + plantao:registrar: responde pela area, mas nao le residentes nem leitos.
        _, h = await _usuario(db, ilpi, {"escala:ler", "plantao:registrar"}, "so_plantao", "Paulo Sintetico")
        await _ok(await client.post("/api/plantoes/iniciar", headers=h, json={"area_ids": [ala_b["id"]]}), 201)
        assert (await client.get("/api/residentes/", headers=h)).status_code == 403
        assert (await client.get("/api/quartos_leitos/", headers=h)).status_code == 403
        agora = await _ok(await client.get("/api/escala/agora", headers=h))
        assert agora["areas"][0]["residentes"] is None, "contagem de residentes exige residentes:ler"
        assert (await _ok(await client.get("/api/escala/agora", headers=hg)))["areas"][0]["residentes"] == 0

        _, sem = await _usuario(db, ilpi, {"residentes:ler"}, "sem_escala", "Sem Escala")
        assert (await client.get("/api/escala/areas", headers=sem)).status_code == 403
        assert (await client.get("/api/escala/turnos", headers=sem)).status_code == 403
        assert (await client.post("/api/plantoes/iniciar", headers=sem, json={})).status_code == 403
        assert (await _ok(await client.get("/api/plantoes/atual", headers=sem)))["pode_registrar"] is False
        _, so_ler = await _usuario(db, ilpi, {"escala:ler"}, "so_ler", "So Ler")
        assert (await client.post("/api/escala/turnos", headers=so_ler, json={"nome": "T", "hora_inicio": "07:00", "hora_fim": "19:00"})).status_code == 403
    _run(escala_db, op)


def test_isolamento_entre_ilpis(escala_db):
    async def op(client, db):
        ilpi_a, gestor_a, h_a, ala_a = await _ilpi_com_area(client, db, "ILPI A")
        ilpi_b, _, h_b, ala_b = await _ilpi_com_area(client, db, "ILPI B")
        leito_b = await _ok(await client.post("/api/quartos_leitos/", headers=h_b, json={"quarto": "1", "leito": "A"}), 201)
        plantao_b = await _ok(await client.post("/api/plantoes/iniciar", headers=h_b, json={"area_ids": [ala_b["id"]]}), 201)

        assert [a["nome"] for a in await _ok(await client.get("/api/escala/areas", headers=h_a))] == ["Ala B"]
        assert (await _ok(await client.get("/api/escala/areas", headers=h_a)))[0]["id"] == ala_a["id"]
        # Recurso da ILPI B e inexistente para a ILPI A (404, sem vazar existencia).
        assert (await client.patch(f"/api/escala/areas/{ala_b['id']}", headers=h_a, json={"nome": "X"})).status_code == 404
        assert (await client.post(f"/api/escala/areas/{ala_a['id']}/leitos", headers=h_a, json={"quarto_leito_id": leito_b["id"]})).status_code == 404
        assert (await client.get("/api/escala/responsaveis", headers=h_a, params={"area_id": ala_b["id"], "em": _agora().isoformat()})).status_code == 404
        assert (await client.post(f"/api/plantoes/{plantao_b['id']}/encerrar", headers=h_a)).status_code == 404
        assert (await client.post("/api/escala/responsabilidades/transferir", headers=h_a, json={
            "area_id": ala_a["id"], "para_plantao_id": plantao_b["id"]})).status_code == 404
        assert (await client.post("/api/plantoes/iniciar", headers=h_a, json={"area_ids": [ala_b["id"]]})).status_code == 404
        agora_a = await _ok(await client.get("/api/escala/agora", headers=h_a))
        assert all(r["plantao_id"] != plantao_b["id"] for a in agora_a["areas"] for r in a["responsaveis"])
        assert agora_a["plantoes_sem_area"] == []
        # Header de outra ILPI nao abre a ILPI B.
        assert (await client.get("/api/escala/areas", headers=_headers(gestor_a, ilpi_id=ilpi_b.id))).status_code == 403
        assert (await client.get("/api/escala/areas", headers=_headers(gestor_a, scope="global"))).status_code == 403
    _run(escala_db, op)
