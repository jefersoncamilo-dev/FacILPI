"""N2 (#171, migration 030): saida do residente.

Banco descartavel (SQLite por padrao; PostgreSQL com D4_TEST_POSTGRES_URL),
mesmo harness e guards do prontuario (tests/test_d4_prontuario.py).
"""
import asyncio
import os
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from src.infrastructure import models as m
from tests.test_d4_prontuario import (  # noqa: F401 - prontuario_db e fixture
    ALL_CLINICAL, BACKEND, OFFICIAL_DB, _create_ilpi_user, _create_platform_user, _create_residente,
    _headers, _new_id, _new_inst, _seed_medicacao_prescricao, _seed_pais, _sqlite_url, _with_client,
    prontuario_db,
)

SAIDA = {"residentes:ler", "residentes:registrar_saida"}
OBITO = {"tipo": "obito", "local_obito": "ilpi"}


async def _ler(db, modelo, registro_id):
    # Le de novo do banco: o endpoint gravou em outra sessao.
    return (await db.execute(select(modelo).where(modelo.id == registro_id)
                             .execution_options(populate_existing=True))).scalar_one_or_none()


def _url(res_id, sufixo=""):
    return f"/api/residentes/{res_id}/saida{sufixo}"


def _quando(**delta):
    return (datetime.now(timezone.utc) - timedelta(minutes=5, **delta)).isoformat()


async def _ativo(db, ilpi_id, nome="Res N2"):
    res = await _create_residente(db, ilpi_id, nome=nome)
    res.situacao = "Ativo"
    await db.flush()
    return res


async def _leito(db, ilpi_id, res_id, user_id, numero="1"):
    leito = m.QuartoLeito(id=_new_id(), instituicao_id=ilpi_id, unidade="A", quarto="1", leito=numero,
                          situacao="livre", residente_atual_id=res_id, data_ocupacao=datetime.now(timezone.utc))
    db.add(leito)
    await db.flush()
    db.add(m.OcupacaoHistorico(id=_new_id(), instituicao_id=ilpi_id, residente_id=res_id, quarto_leito_id=leito.id,
                               data_entrada=datetime.now(timezone.utc) - timedelta(days=1),
                               tipo_movimentacao="alocacao", usuario_id=user_id))
    await db.flush()
    return leito


@pytest.mark.parametrize("payload,situacao", [
    ({"tipo": "obito", "local_obito": "hospital"}, "Falecido"),
    ({"tipo": "transferencia", "destino_tipo": "instituicao", "destino_descricao": "ILPI Vizinha"}, "Transferido"),
    ({"tipo": "desligamento", "motivo_desligamento": "pedido_familia"}, "Desligado"),
    ({"tipo": "retorno_familia"}, "Retornou a familia"),
])
def test_n2_cada_tipo_registra_saida_audita_e_muda_situacao(prontuario_db, payload, situacao):
    async def op(client, db):
        ilpi = _new_inst()
        user = await _create_ilpi_user(db, ilpi, permissions=SAIDA)
        res = await _ativo(db, ilpi.id)
        await db.commit()
        r = await client.post(_url(res.id), json={**payload, "ocorrido_em": _quando()}, headers=_headers(user, ilpi_id=ilpi.id))
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["tipo"] == payload["tipo"] and body["situacao_residente"] == situacao
        assert body["registrado_por"] == user.id and body["leito_liberado"] is False
        assert (await _ler(db, m.Residente, res.id)).situacao == situacao
        audit = (await db.execute(select(m.Auditoria).where(
            m.Auditoria.acao == "residentes.registrar_saida", m.Auditoria.registro_id == body["id"]))).scalar_one()
        assert audit.usuario_id == user.id and audit.ilpi_id == ilpi.id
    asyncio.run(_with_client(prontuario_db, op))


@pytest.mark.parametrize("payload", [
    {"tipo": "obito"},
    {"tipo": "transferencia", "destino_tipo": "hospital"},
    {"tipo": "transferencia", "destino_descricao": "Hospital X"},
    {"tipo": "desligamento"},
    {"tipo": "outro"},
])
def test_n2_campos_obrigatorios_por_tipo(prontuario_db, payload):
    async def op(client, db):
        ilpi = _new_inst()
        user = await _create_ilpi_user(db, ilpi, permissions=SAIDA)
        res = await _ativo(db, ilpi.id)
        await db.commit()
        r = await client.post(_url(res.id), json={**payload, "ocorrido_em": _quando()}, headers=_headers(user, ilpi_id=ilpi.id))
        assert r.status_code == 422, r.text
        assert (await _ler(db, m.Residente, res.id)).situacao == "Ativo"
    asyncio.run(_with_client(prontuario_db, op))


def test_n2_data_futura_recusada_e_autor_nao_vem_do_payload(prontuario_db):
    async def op(client, db):
        ilpi = _new_inst()
        user = await _create_ilpi_user(db, ilpi, permissions=SAIDA)
        res = await _ativo(db, ilpi.id)
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        futuro = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        assert (await client.post(_url(res.id), json={**OBITO, "ocorrido_em": futuro}, headers=h)).status_code == 422
        r = await client.post(_url(res.id), json={**OBITO, "ocorrido_em": _quando(), "registrado_por": _new_id(),
                                                  "ilpi_id": _new_id()}, headers=h)
        assert r.status_code == 201, r.text
        assert r.json()["registrado_por"] == user.id
    asyncio.run(_with_client(prontuario_db, op))


def test_n2_rbac_sem_permissao_e_platform_recebem_403(prontuario_db):
    async def op(client, db):
        ilpi = _new_inst()
        sem = await _create_ilpi_user(db, ilpi, permissions=ALL_CLINICAL)
        res = await _ativo(db, ilpi.id)
        platform = await _create_platform_user(db)
        await db.commit()
        body = {**OBITO, "ocorrido_em": _quando()}
        assert (await client.post(_url(res.id), json=body, headers=_headers(sem, ilpi_id=ilpi.id))).status_code == 403
        assert (await client.get(_url(res.id, "/pendencias"), headers=_headers(sem, ilpi_id=ilpi.id))).status_code == 403
        r = await client.post(_url(res.id), json=body, headers=_headers(platform, scope="platform"))
        assert r.status_code in (401, 403), r.text
        assert (await _ler(db, m.Residente, res.id)).situacao == "Ativo"
    asyncio.run(_with_client(prontuario_db, op))


def test_n2_cross_tenant_404_igual_a_inexistente(prontuario_db):
    async def op(client, db):
        ilpi_a, ilpi_b = _new_inst("A"), _new_inst("B")
        user_a = await _create_ilpi_user(db, ilpi_a, permissions=SAIDA | {"residentes:estornar_saida"})
        await _create_ilpi_user(db, ilpi_b, permissions=SAIDA)
        res_b = await _ativo(db, ilpi_b.id)
        await db.commit()
        h = _headers(user_a, ilpi_id=ilpi_a.id)
        body = {**OBITO, "ocorrido_em": _quando()}
        outro = await client.post(_url(res_b.id), json=body, headers=h)
        inexistente = await client.post(_url(_new_id()), json=body, headers=h)
        assert outro.status_code == inexistente.status_code == 404
        assert outro.json() == inexistente.json()
        assert (await client.get(_url(res_b.id, "/pendencias"), headers=h)).status_code == 404
        assert (await client.post(_url(res_b.id, "/estornar"), json={"motivo": "engano"}, headers=h)).status_code == 404
        assert (await _ler(db, m.Residente, res_b.id)).situacao == "Ativo"
    asyncio.run(_with_client(prontuario_db, op))


def test_n2_so_ativo_sai_e_segunda_saida_409(prontuario_db):
    async def op(client, db):
        ilpi = _new_inst()
        user = await _create_ilpi_user(db, ilpi, permissions=SAIDA)
        res = await _ativo(db, ilpi.id)
        em_admissao = await _create_residente(db, ilpi.id, nome="Em admissao")
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        body = {**OBITO, "ocorrido_em": _quando()}
        assert (await client.post(_url(em_admissao.id), json=body, headers=h)).status_code == 409
        assert (await client.post(_url(res.id), json=body, headers=h)).status_code == 201
        assert (await client.post(_url(res.id), json=body, headers=h)).status_code == 409
        assert len((await db.execute(select(m.ResidenteSaida).where(m.ResidenteSaida.residente_id == res.id))).all()) == 1
    asyncio.run(_with_client(prontuario_db, op))


def test_n2_leito_so_liberado_por_escolha_explicita(prontuario_db):
    async def op(client, db):
        ilpi = _new_inst()
        user = await _create_ilpi_user(db, ilpi, permissions=SAIDA | {"quartos_leitos:ler", "quartos_leitos:atualizar"})
        sem_leito_perm = await _create_ilpi_user(db, ilpi, permissions=SAIDA, profile_key="d4b")
        res1, res2, res3 = await _ativo(db, ilpi.id, "R1"), await _ativo(db, ilpi.id, "R2"), await _ativo(db, ilpi.id, "R3")
        l1 = await _leito(db, ilpi.id, res1.id, user.id)
        l2 = await _leito(db, ilpi.id, res2.id, user.id, numero="2")
        l3 = await _leito(db, ilpi.id, res3.id, user.id, numero="3")
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        body = {**OBITO, "ocorrido_em": _quando()}
        # Sem a escolha: leito continua ocupado.
        assert (await client.post(_url(res1.id), json=body, headers=h)).status_code == 201
        # Com a escolha: leito liberado e historico fechado.
        r = await client.post(_url(res2.id), json={**body, "liberar_leito": True}, headers=h)
        assert r.status_code == 201, r.text
        assert r.json()["leito_liberado"] is True
        # Sem quartos_leitos:atualizar: recusado, nada muda.
        r3 = await client.post(_url(res3.id), json={**body, "liberar_leito": True}, headers=_headers(sem_leito_perm, ilpi_id=ilpi.id))
        assert r3.status_code == 403
        assert (await _ler(db, m.QuartoLeito, l1.id)).residente_atual_id == res1.id
        assert (await _ler(db, m.QuartoLeito, l2.id)).residente_atual_id is None
        hist = (await db.execute(select(m.OcupacaoHistorico).where(m.OcupacaoHistorico.quarto_leito_id == l2.id))).scalar_one()
        assert hist.data_saida is not None
        assert (await _ler(db, m.QuartoLeito, l3.id)).residente_atual_id == res3.id
        assert (await _ler(db, m.Residente, res3.id)).situacao == "Ativo"
    asyncio.run(_with_client(prontuario_db, op))


def test_n2_pendencias_respeitam_leitura_de_cada_origem_e_nada_e_encerrado(prontuario_db):
    async def op(client, db):
        ilpi = _new_inst()
        todos = await _create_ilpi_user(db, ilpi, permissions=ALL_CLINICAL | SAIDA)
        so_saida = await _create_ilpi_user(db, ilpi, permissions=SAIDA, profile_key="d4b")
        res = await _ativo(db, ilpi.id)
        now = datetime.now(timezone.utc)
        pais = await _seed_pais(db, ilpi.id, res.id, todos.id, situacao="vigente")
        _, presc = await _seed_medicacao_prescricao(db, ilpi.id, res.id, todos.id, situacao="ativa", now=now)
        await _leito(db, ilpi.id, res.id, todos.id)
        await db.commit()
        r = await client.get(_url(res.id, "/pendencias"), headers=_headers(todos, ilpi_id=ilpi.id))
        assert r.status_code == 200, r.text
        origens = {(p["origem"], p["registro_id"]) for p in r.json()["pendencias"]}
        assert ("pais", pais.id) in origens and ("prescricao", presc.id) in origens
        assert any(o == "leito" for o, _ in origens)
        assert r.json()["origens_sem_leitura"] == []
        r2 = await client.get(_url(res.id, "/pendencias"), headers=_headers(so_saida, ilpi_id=ilpi.id))
        assert r2.status_code == 200
        assert r2.json()["pendencias"] == []
        assert set(r2.json()["origens_sem_leitura"]) == {"pais", "prescricao", "programacao_cuidado", "leito", "ausencia"}
        # Registrar a saida nao encerra PAIS nem prescricao.
        assert (await client.post(_url(res.id), json={**OBITO, "ocorrido_em": _quando()},
                                  headers=_headers(todos, ilpi_id=ilpi.id))).status_code == 201
        assert (await _ler(db, m.PlanoCuidados, pais.id)).situacao == "vigente"
        assert (await _ler(db, m.Prescricao, presc.id)).situacao == "ativa"
    asyncio.run(_with_client(prontuario_db, op))


def test_n2_estorno_preserva_original_e_so_quem_tem_permissao(prontuario_db):
    async def op(client, db):
        ilpi = _new_inst()
        rt = await _create_ilpi_user(db, ilpi, permissions=SAIDA | {"residentes:estornar_saida"})
        enf = await _create_ilpi_user(db, ilpi, permissions=SAIDA, profile_key="d4b")
        res = await _ativo(db, ilpi.id)
        await db.commit()
        r = await client.post(_url(res.id), json={**OBITO, "ocorrido_em": _quando()}, headers=_headers(enf, ilpi_id=ilpi.id))
        saida_id = r.json()["id"]
        assert (await client.post(_url(res.id, "/estornar"), json={"motivo": "Registrado por engano"},
                                  headers=_headers(enf, ilpi_id=ilpi.id))).status_code == 403
        assert (await client.post(_url(res.id, "/estornar"), json={"motivo": ""},
                                  headers=_headers(rt, ilpi_id=ilpi.id))).status_code == 422
        e = await client.post(_url(res.id, "/estornar"), json={"motivo": "Registrado por engano"},
                              headers=_headers(rt, ilpi_id=ilpi.id))
        assert e.status_code == 200, e.text
        assert e.json()["id"] == saida_id and e.json()["situacao_residente"] == "Ativo"
        assert e.json()["estornado_por"] == rt.id and e.json()["motivo_estorno"] == "Registrado por engano"
        original = await _ler(db, m.ResidenteSaida, saida_id)
        assert original is not None and original.tipo == "obito" and original.registrado_por == enf.id
        assert (await _ler(db, m.Residente, res.id)).situacao == "Ativo"
        # Sem saida vigente: novo estorno 409; nova saida volta a ser possivel.
        assert (await client.post(_url(res.id, "/estornar"), json={"motivo": "de novo"},
                                  headers=_headers(rt, ilpi_id=ilpi.id))).status_code == 409
        assert (await client.post(_url(res.id), json={"tipo": "retorno_familia", "ocorrido_em": _quando()},
                                  headers=_headers(enf, ilpi_id=ilpi.id))).status_code == 201
    asyncio.run(_with_client(prontuario_db, op))


def test_n2_residente_que_saiu_some_dos_alertas_e_do_plantao(prontuario_db):
    async def op(client, db):
        ilpi = _new_inst()
        user = await _create_ilpi_user(db, ilpi, permissions=ALL_CLINICAL | SAIDA | {"alertas:ler", "plantao:ler"})
        fica, sai = await _ativo(db, ilpi.id, "Fica"), await _ativo(db, ilpi.id, "Sai")
        for r in (fica, sai):
            db.add(m.Intercorrencia(id=_new_id(), residente_id=r.id, ilpi_id=ilpi.id, tipo="Queda", gravidade="grave",
                                    situacao="aberta", ocorrido_em=datetime.now(timezone.utc) - timedelta(days=2),
                                    data=datetime.now(timezone.utc) - timedelta(days=2), responsavel="Enf"))
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)

        async def residentes_em(path):
            resp = await client.get(path, headers=h)
            assert resp.status_code == 200, resp.text
            body = resp.json()
            itens = body if isinstance(body, list) else body["alertas"]
            return {i.get("residente_id") for i in itens}

        antes_alertas = await residentes_em("/api/central-alertas/")
        antes_plantao = await residentes_em("/api/plantao/")
        assert sai.id in antes_alertas and sai.id in antes_plantao
        assert (await client.post(_url(sai.id), json={**OBITO, "ocorrido_em": _quando()}, headers=h)).status_code == 201
        depois_alertas = await residentes_em("/api/central-alertas/")
        depois_plantao = await residentes_em("/api/plantao/")
        assert sai.id not in depois_alertas and sai.id not in depois_plantao
        assert fica.id in depois_alertas and fica.id in depois_plantao
    asyncio.run(_with_client(prontuario_db, op))


def test_n2_saida_e_estorno_visiveis_no_prontuario(prontuario_db):
    async def op(client, db):
        ilpi = _new_inst()
        user = await _create_ilpi_user(db, ilpi, permissions=SAIDA | {"residentes:estornar_saida"})
        res = await _ativo(db, ilpi.id)
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        saida_id = (await client.post(_url(res.id), json={**OBITO, "ocorrido_em": _quando()}, headers=h)).json()["id"]
        await client.post(_url(res.id, "/estornar"), json={"motivo": "engano"}, headers=h)
        r = await client.get(f"/api/residentes/{res.id}/prontuario", headers=h)
        assert r.status_code == 200, r.text
        evento, = [e for e in r.json()["items"] if e["origem"] == "saida"]
        assert evento["registro_id"] == saida_id and evento["situacao"] == "obito"
        assert evento["estornado"] is True and evento["motivo_estorno"] == "engano"
        assert evento["autor_id"] == user.id and evento["autor_nome"] == user.nome and evento["link"] is None
    asyncio.run(_with_client(prontuario_db, op))


def test_n2_grants_nos_templates(prontuario_db):
    async def op(client, db):
        rows = (await db.execute(select(m.Perfil.chave, m.Permissao.chave).join(
            m.PerfilPermissao, m.PerfilPermissao.perfil_id == m.Perfil.id).join(
            m.Permissao, m.Permissao.id == m.PerfilPermissao.permissao_id).where(
            m.Perfil.ilpi_id.is_(None), m.Permissao.chave.in_(["residentes:registrar_saida", "residentes:estornar_saida"])))).all()
        concedido = {}
        for perfil, perm in rows:
            concedido.setdefault(perm, set()).add(perfil)
        assert concedido["residentes:registrar_saida"] == {"ilpi_admin", "responsavel_tecnico", "enfermagem", "administrativo"}
        assert concedido["residentes:estornar_saida"] == {"ilpi_admin", "responsavel_tecnico"}
    asyncio.run(_with_client(prontuario_db, op))


def _alembic(db_path, alvo):
    assert db_path.resolve() != OFFICIAL_DB.resolve()
    url = _sqlite_url(db_path)
    env = os.environ.copy()
    env["DATABASE_URL"] = url
    env.pop("APP_DATABASE_URL", None)
    result = subprocess.run([sys.executable, "-m", "alembic", "-x", f"database_url={url}", alvo[0], alvo[1]], cwd=BACKEND,
                            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return result


def test_n2_migration_concede_aos_clones_e_downgrade_reversivel(tmp_path):
    db_path = tmp_path / "n2-clones.db"
    r = _alembic(db_path, ("upgrade", "029_autoria_autor_id"))
    assert r.returncode == 0, r.stdout + r.stderr
    clone_enf, clone_cuid, inst = _new_id(), _new_id(), _new_id()
    with sqlite3.connect(db_path) as con:
        con.execute("INSERT INTO instituicoes (id, razao_social, situacao) VALUES (?, 'Clone', 'ATIVA')", (inst,))
        for pid, chave in ((clone_enf, "enfermagem"), (clone_cuid, "cuidador")):
            con.execute("INSERT INTO perfis (id, ilpi_id, nome, chave, escopo, situacao) VALUES (?, ?, ?, ?, 'ilpi', 'ativo')",
                        (pid, inst, f"Clone {chave}", chave))
    r = _alembic(db_path, ("upgrade", "head"))
    assert r.returncode == 0, r.stdout + r.stderr
    with sqlite3.connect(db_path) as con:
        def chaves(pid):
            return {row[0] for row in con.execute(
                "SELECT p.chave FROM perfil_permissoes pp JOIN permissoes p ON p.id = pp.permissao_id WHERE pp.perfil_id = ?", (pid,))}
        assert "residentes:registrar_saida" in chaves(clone_enf)
        assert "residentes:estornar_saida" not in chaves(clone_enf)
        assert not {"residentes:registrar_saida", "residentes:estornar_saida"} & chaves(clone_cuid)
    r = _alembic(db_path, ("downgrade", "029_autoria_autor_id"))
    assert r.returncode == 0, r.stdout + r.stderr
    with sqlite3.connect(db_path) as con:
        assert con.execute("SELECT COUNT(*) FROM permissoes WHERE chave LIKE 'residentes:%_saida'").fetchone()[0] == 0
        assert con.execute("SELECT name FROM sqlite_master WHERE name = 'residente_saidas'").fetchone() is None
