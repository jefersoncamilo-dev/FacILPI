"""Configuracoes da instituicao: tenant da sessao, RBAC e autoria. Banco descartavel."""

import asyncio
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


def test_tenant_rbac_e_autoria(banco):
    async def op(client, db):
        ilpi, _, _, _ = await _ilpi_com_area(client, db)
        outra, _, _, _ = await _ilpi_com_area(client, db)
        ilpi_id, outra_id = getattr(ilpi, "id", ilpi), getattr(outra, "id", outra)
        admin, ha = await _usuario(db, ilpi, await _template(db, "ilpi_admin"), "ilpi_admin", "Admin Sintetico")
        _, hc = await _usuario(db, ilpi, await _template(db, "cuidador"), "cuidador", "Ana Sintetica")
        assert (await client.get("/api/configuracoes/", headers=hc)).status_code == 403
        assert (await client.put("/api/configuracoes/", headers=hc, json={"telefone": "1"})).status_code == 403

        r = await client.put("/api/configuracoes/", headers=ha, json={
            "telefone": "1133334444", "uf": "sp", "capacidade": 30, "fuso_horario": "America/Manaus",
            "situacao": "INATIVA", "cnpj": "x", "ilpi_id": outra_id, "razao_social": "Trocada"})
        assert r.status_code == 200, r.text
        corpo = r.json()
        assert (corpo["id"], corpo["uf"], corpo["fuso_horario"]) == (ilpi_id, "SP", "America/Manaus")
        assert corpo["razao_social"] != "Trocada" and corpo["situacao"] != "INATIVA" and corpo["cnpj"] != "x"
        o = await db.scalar(select(m.Instituicao).where(m.Instituicao.id == outra_id))
        assert o.telefone != "1133334444"
        a = await db.scalar(select(m.Auditoria).where(m.Auditoria.acao == "configuracoes.atualizadas"))
        assert (a.usuario_id, a.ilpi_id) == (admin.id, ilpi_id)

        for ruim in ({"uf": "S1"}, {"capacidade": 0}, {"fuso_horario": "Lua/Base"}):
            assert (await client.put("/api/configuracoes/", headers=ha, json=ruim)).status_code == 422
    asyncio.run(_client(banco, op))


def test_escopo_global_nao_alcanca():
    ctx = SimpleNamespace(perfil=SimpleNamespace(chave="platform_superuser"), scope=GLOBAL_SCOPE, ilpi_situacao=None)
    assert _permission_is_allowed(ctx, SimpleNamespace(chave="configuracoes:ler", modulo="configuracoes")) is False
