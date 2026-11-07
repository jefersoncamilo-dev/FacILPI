"""Complementares D5: tenant (404), RBAC, autoria e historico. Banco descartavel."""

import asyncio
from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from .banco_modelo import migrar_de_modelo
from .test_d3_admissao import _client
from .test_d3_admissao_migration import _ref, _url
from .test_operacao_escala import _ilpi_com_area, _template, _usuario
from src.application.security import GLOBAL_SCOPE, _permission_is_allowed
from src.infrastructure import models as m


@pytest.fixture
def banco(tmp_path):
    ref = _ref(SimpleNamespace(param="sqlite"), tmp_path)
    migrar_de_modelo(_url(ref), "head")
    return ref


async def _cenario(client, db):
    a, _, _, _ = await _ilpi_com_area(client, db)
    b, _, _, _ = await _ilpi_com_area(client, db, nome="Outra")
    ra = m.Residente(instituicao_id=a.id, nome="Res A", situacao="Ativo", data_nascimento=date(1940, 1, 1))
    rb = m.Residente(instituicao_id=b.id, nome="Res B", situacao="Ativo", data_nascimento=date(1940, 1, 1))
    db.add_all([ra, rb])
    await db.commit()
    return a, b, ra.id, rb.id


def _roda(banco, op):
    asyncio.run(_client(banco, op))


def test_agenda(banco):
    async def op(client, db):
        a, b, ra, rb = await _cenario(client, db)
        rt, h = await _usuario(db, a, await _template(db, "responsavel_tecnico"), "responsavel_tecnico", "RT Sint")
        _, hc = await _usuario(db, a, await _template(db, "cuidador"), "cuidador", "Cuid Sint")
        _, hb = await _usuario(db, b, await _template(db, "responsavel_tecnico"), "responsavel_tecnico", "RT B")
        corpo = {"residente_id": ra, "motivo": "Consulta", "inicio_em": "2030-01-10T12:00:00Z"}
        assert (await client.post("/api/agenda/", headers=hc, json=corpo)).status_code == 403
        assert (await client.post("/api/agenda/", headers=h, json={**corpo, "residente_id": rb})).status_code == 404
        r = await client.post("/api/agenda/", headers=h, json={**corpo, "autor_id": "x", "ilpi_id": b.id})
        assert r.status_code == 201, r.text
        ev = r.json()["id"]
        o = await db.scalar(select(m.AgendaEvento).where(m.AgendaEvento.id == ev))
        assert (o.autor_id, o.ilpi_id) == (rt.id, a.id)
        assert [e["id"] for e in (await client.get("/api/agenda/", headers=hc)).json()] == [ev]
        assert (await client.get("/api/agenda/", headers=hb)).json() == []
        assert (await client.post(f"/api/agenda/{ev}/concluir", headers=hb, json={"texto": "x"})).status_code == 404
        assert (await client.post(f"/api/agenda/{ev}/concluir", headers=h, json={"texto": "Ok"})).json()["situacao"] == "realizado"
        assert (await client.post(f"/api/agenda/{ev}/cancelar", headers=h, json={"texto": "x"})).status_code == 409
    _roda(banco, op)


def test_multidisciplinar_sem_acesso_cruzado_e_estorno(banco):
    async def op(client, db):
        a, b, ra, rb = await _cenario(client, db)
        enf, h = await _usuario(db, a, await _template(db, "enfermagem"), "enfermagem", "Enf Sint")
        _, hrt = await _usuario(db, a, await _template(db, "responsavel_tecnico"), "responsavel_tecnico", "RT Sint")
        corpo = {"residente_id": ra, "ocorrido_em": "2030-01-10T12:00:00Z", "evolucao": "Evolui bem", "autor_nome": "Forjado"}
        assert (await client.post("/api/multidisciplinar/fisioterapia", headers=h, json=corpo)).status_code == 403
        assert (await client.get("/api/multidisciplinar/nutricao", headers=h)).status_code == 403
        assert (await client.post("/api/multidisciplinar/enfermagem", headers=h, json={**corpo, "residente_id": rb})).status_code == 404
        assert (await client.post("/api/multidisciplinar/enfermagem", headers=hrt, json=corpo)).status_code == 403
        r = await client.post("/api/multidisciplinar/enfermagem", headers=h, json=corpo)
        assert r.status_code == 201, r.text
        assert (r.json()["autor_id"], r.json()["autor_nome"]) == (enf.id, "Enf Sint")
        assert len((await client.get("/api/multidisciplinar/enfermagem", headers=hrt)).json()) == 1
        i = r.json()["id"]
        assert (await client.post(f"/api/multidisciplinar/enfermagem/{i}/estornar", headers=h, json={"texto": "Erro"})).json()["estornado_em"]
        assert (await client.post(f"/api/multidisciplinar/enfermagem/{i}/estornar", headers=h, json={"texto": "Erro"})).status_code == 409
        assert len((await client.get("/api/multidisciplinar/enfermagem", headers=h)).json()) == 1
    _roda(banco, op)


def test_pia_versiona(banco):
    async def op(client, db):
        a, b, ra, rb = await _cenario(client, db)
        rt, h = await _usuario(db, a, await _template(db, "responsavel_tecnico"), "responsavel_tecnico", "RT Sint")
        _, hc = await _usuario(db, a, await _template(db, "cuidador"), "cuidador", "Cuid Sint")
        assert (await client.post(f"/api/pia/{ra}", headers=hc, json={})).status_code == 403
        assert (await client.post(f"/api/pia/{rb}", headers=h, json={})).status_code == 404
        assert (await client.get(f"/api/pia/{rb}", headers=h)).status_code == 404
        assert (await client.post(f"/api/pia/{ra}", headers=h, json={"apoio_social": "Filha"})).json()["versao"] == 1
        assert (await client.post(f"/api/pia/{ra}", headers=h, json={"apoio_social": "Neta"})).json()["versao"] == 2
        v = (await client.get(f"/api/pia/{ra}", headers=hc)).json()
        assert [(x["versao"], x["apoio_social"], x["autor_nome"]) for x in v] == [(2, "Neta", "RT Sint"), (1, "Filha", "RT Sint")]
    _roda(banco, op)


def test_estoque_saldo_por_lote(banco):
    async def op(client, db):
        a, b, ra, rb = await _cenario(client, db)
        _, h = await _usuario(db, a, await _template(db, "enfermagem"), "enfermagem", "Enf Sint")
        _, hc = await _usuario(db, a, await _template(db, "cuidador"), "cuidador", "Cuid Sint")
        _, hb = await _usuario(db, b, await _template(db, "enfermagem"), "enfermagem", "Enf B")
        assert (await client.get("/api/estoque/itens", headers=hc)).status_code == 403
        r = await client.post("/api/estoque/itens", headers=h, json={"nome": "Luva", "unidade": "cx", "estoque_minimo": 5})
        assert r.status_code == 201, r.text
        i = r.json()["id"]
        assert (await client.post("/api/estoque/itens", headers=h, json={"nome": "Luva", "unidade": "cx"})).status_code == 409
        url = f"/api/estoque/itens/{i}/movimentos"
        assert (await client.post(url, headers=hb, json={"tipo": "entrada", "quantidade": 1})).status_code == 404
        assert (await client.post(url, headers=h, json={"tipo": "entrada", "quantidade": 8, "lote": "L1", "validade": "2031-01-01"})).status_code == 201
        assert (await client.post(url, headers=h, json={"tipo": "saida", "quantidade": 1, "lote": "L1"})).status_code == 422
        assert (await client.post(url, headers=h, json={"tipo": "saida", "quantidade": 9, "lote": "L1", "motivo": "Uso"})).status_code == 409
        assert (await client.post(url, headers=h, json={"tipo": "saida", "quantidade": 1, "lote": "L1", "motivo": "Uso", "residente_id": rb})).status_code == 404
        assert (await client.post(url, headers=h, json={"tipo": "saida", "quantidade": 6, "lote": "L1", "motivo": "Uso", "residente_id": ra})).status_code == 201
        item = (await client.get("/api/estoque/itens", headers=h)).json()[0]
        assert (item["saldo"], item["abaixo_do_minimo"], item["lotes"][0]["saldo"]) == (2, True, 2)
        assert (await client.get("/api/estoque/itens", headers=hb)).json() == []
    _roda(banco, op)


def test_mensalidades(banco):
    async def op(client, db):
        a, b, ra, rb = await _cenario(client, db)
        adm, h = await _usuario(db, a, await _template(db, "ilpi_admin"), "ilpi_admin", "Adm Sint")
        _, he = await _usuario(db, a, await _template(db, "enfermagem"), "enfermagem", "Enf Sint")
        _, hb = await _usuario(db, b, await _template(db, "ilpi_admin"), "ilpi_admin", "Adm B")
        corpo = {"residente_id": ra, "competencia": "2030-01", "valor_centavos": 350000, "vencimento": "2030-01-10"}
        assert (await client.get("/api/financeiro/mensalidades", headers=he)).status_code == 403
        assert (await client.post("/api/financeiro/mensalidades", headers=h, json={**corpo, "residente_id": rb})).status_code == 404
        assert (await client.post("/api/financeiro/mensalidades", headers=h, json={**corpo, "competencia": "2030-13"})).status_code == 422
        r = await client.post("/api/financeiro/mensalidades", headers=h, json=corpo)
        assert r.status_code == 201, r.text
        i = r.json()["id"]
        assert (await db.scalar(select(m.Mensalidade.autor_id).where(m.Mensalidade.id == i))) == adm.id
        assert (await client.post("/api/financeiro/mensalidades", headers=h, json=corpo)).status_code == 409
        assert (await client.post(f"/api/financeiro/mensalidades/{i}/pagar", headers=hb, json={"pago_em": "2030-01-09"})).status_code == 404
        assert (await client.post(f"/api/financeiro/mensalidades/{i}/pagar", headers=h, json={"pago_em": "2030-01-09"})).json()["situacao"] == "paga"
        assert (await client.post(f"/api/financeiro/mensalidades/{i}/pagar", headers=h, json={"pago_em": "2030-01-09"})).status_code == 409
        assert (await client.post(f"/api/financeiro/mensalidades/{i}/cancelar", headers=h, json={"texto": "Erro"})).json()["situacao"] == "cancelada"
        assert (await client.post("/api/financeiro/mensalidades", headers=h, json=corpo)).status_code == 201
    _roda(banco, op)


@pytest.mark.parametrize("chave,modulo", [("agenda:ler", "agenda"), ("pia:ler", "pia"), ("estoque:ler", "estoque"),
                                          ("financeiro:ler", "financeiro"), ("multidisciplinar.nutricao:ler", "multidisciplinar")])
def test_plataforma_sem_acesso(chave, modulo):
    ctx = SimpleNamespace(perfil=SimpleNamespace(chave="platform_superuser"), scope=GLOBAL_SCOPE, ilpi_situacao=None)
    assert _permission_is_allowed(ctx, SimpleNamespace(chave=chave, modulo=modulo)) is False


def test_migration_035_ida_e_volta(tmp_path):
    from .test_n2_saida_residente import _alembic
    import sqlite3

    db = tmp_path / "m035.db"
    assert _alembic(db, ("upgrade", "head")).returncode == 0
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM perfis WHERE chave = 'nutricionista' AND ilpi_id IS NULL").fetchone()[0] == 1
        chaves = {r[0] for r in con.execute(
            "SELECT p.chave FROM perfil_permissoes pp JOIN permissoes p ON p.id = pp.permissao_id "
            "JOIN perfis f ON f.id = pp.perfil_id WHERE f.chave = 'nutricionista' AND f.ilpi_id IS NULL")}
        assert "multidisciplinar.nutricao:registrar" in chaves and "multidisciplinar.psicologia:ler" not in chaves
    r = _alembic(db, ("downgrade", "034_transicao_admin_clinico"))
    assert r.returncode == 0, r.stdout + r.stderr
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM permissoes WHERE chave LIKE 'financeiro:%'").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'mensalidades'").fetchone()[0] == 0
