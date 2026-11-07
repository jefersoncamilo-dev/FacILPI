"""Consulta de auditoria: tenant da sessao, RBAC e escopo global. Banco descartavel."""

import asyncio
from types import SimpleNamespace

import pytest

from .banco_modelo import migrar_de_modelo
from .test_d3_admissao import _client
from .test_d3_admissao_migration import _ref, _url
from .test_operacao_escala import _ilpi_com_area, _template, _usuario
from src.infrastructure import models as m


@pytest.fixture
def banco(tmp_path):
    ref = _ref(SimpleNamespace(param="sqlite"), tmp_path)
    migrar_de_modelo(_url(ref), "head")
    return ref


def test_so_a_ilpi_da_sessao_filtros_e_rbac(banco):
    async def op(client, db):
        ilpi, _, _, _ = await _ilpi_com_area(client, db)
        outra, _, _, _ = await _ilpi_com_area(client, db, nome="Outra")
        admin, ha = await _usuario(db, ilpi, await _template(db, "ilpi_admin"), "ilpi_admin", "Admin Sintetico")
        _, hc = await _usuario(db, ilpi, await _template(db, "cuidador"), "cuidador", "Ana Sintetica")
        db.add(m.Auditoria(acao="teste.minha", entidade="x", ilpi_id=ilpi.id, usuario_id=admin.id))
        db.add(m.Auditoria(acao="teste.minha2", entidade="y", ilpi_id=ilpi.id))
        db.add(m.Auditoria(acao="teste.outra", entidade="x", ilpi_id=outra.id))
        db.add(m.Auditoria(acao="teste.global", entidade="x"))
        await db.commit()

        assert (await client.get("/api/auditoria/", headers=hc)).status_code == 403
        r = await client.get("/api/auditoria/", headers=ha, params={"limit": 200, "ilpi_id": outra.id})
        assert r.status_code == 200, r.text
        acoes = {i["acao"] for i in r.json()}
        assert {"teste.minha", "teste.minha2"} <= acoes
        assert not {"teste.outra", "teste.global"} & acoes

        f = (await client.get("/api/auditoria/", headers=ha, params={"acao": "teste.minha"})).json()
        assert [(i["acao"], i["usuario_nome"]) for i in f] == [("teste.minha", "Admin Sintetico")]
        assert (await client.get("/api/auditoria/", headers=ha, params={"entidade": "y"})).json()[0]["acao"] == "teste.minha2"
        assert (await client.get("/api/auditoria/", headers=ha, params={"acao": "teste.outra"})).json() == []
        # So leitura: nao ha escrita na trilha.
        assert (await client.post("/api/auditoria/", headers=ha, json={})).status_code == 405
    asyncio.run(_client(banco, op))
