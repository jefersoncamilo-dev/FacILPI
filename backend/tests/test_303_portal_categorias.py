"""#303 Portal da familia: liga/desliga por ILPI, categorias bloqueadas por padrao,
tenant, vinculo, auditoria de acesso e conteudo sem valor clinico.

Banco SQLite descartavel em tmp_path; PostgreSQL via D3_TEST_POSTGRES_URL no CI.
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select

from .banco_modelo import migrar_de_modelo
from .test_271_portal_familia import _cenario, _sessao_familiar
from .test_d2_rotina import _headers
from .test_d3_admissao import _client
from .test_d3_admissao_migration import _ref, _url
from .test_operacao_escala import _template, _usuario
from src.infrastructure import models as m

TODAS = ["medicacao", "alimentacao", "atividades", "bem_estar", "recados", "agenda", "mensalidades"]


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D3_TEST_POSTGRES_URL") else []))
def banco(request, tmp_path):
    ref = _ref(SimpleNamespace(param=request.param), tmp_path)
    migrar_de_modelo(_url(ref), "head")
    return ref


async def _familiar_liberado(client, db):
    c = await _cenario(client, db)
    assert (await client.post(f"/api/familiares/{c.fa}/portal", headers=c.ha, json={"ativo": True})).status_code == 200
    user, hf = await _sessao_familiar(db, c)
    user.exige_troca_senha = False
    await db.commit()
    return c, user, hf


def test_tudo_comeca_bloqueado_e_so_a_equipe_libera(banco):
    async def op(client, db):
        c, user, hf = await _familiar_liberado(client, db)
        assert (await client.get("/api/portal/config", headers=c.ha)).json() == {"ativo": False, "categorias": []}
        db.add(m.SinalVital(residente_id=c.ra, ilpi_id=c.a.id, peso=61.5, pressao_sistolica=150, pressao_diastolica=95,
                            data=datetime.now(timezone.utc) - timedelta(days=1)))
        await db.commit()
        corpo = (await client.get("/api/portal/resumo", headers=hf)).json()
        assert corpo["portal_liberado"] is False and corpo["categorias"] == []
        assert all(corpo[k] is None for k in ("medicacao", "alimentacao", "atividades", "peso", "agenda", "recados", "mensalidades"))

        # Categorias marcadas com o portal desligado continuam bloqueadas.
        assert (await client.put("/api/portal/config", headers=c.ha, json={"ativo": False, "categorias": TODAS})).status_code == 200
        assert (await client.get("/api/portal/resumo", headers=hf)).json()["categorias"] == []

        # Ligado, so a categoria liberada aparece.
        assert (await client.put("/api/portal/config", headers=c.ha, json={"ativo": True, "categorias": ["bem_estar"]})).status_code == 200
        corpo = (await client.get("/api/portal/resumo", headers=hf)).json()
        assert corpo["categorias"] == ["bem_estar"] and [p["peso"] for p in corpo["peso"]] == [61.5]
        assert corpo["medicacao"] is None and corpo["recados"] is None
        assert "pressao" not in str(corpo).lower() and "150" not in str(corpo), "nenhum valor de pressao vai ao familiar"

        assert (await client.put("/api/portal/config", headers=c.ha, json={"ativo": True, "categorias": ["pressao"]})).status_code == 422
        # So quem publica configura; cuidador nao.
        _, hcuid = await _usuario(db, c.a, await _template(db, "cuidador"), "cuidador", "Cuid Sint")
        assert (await client.put("/api/portal/config", headers=hcuid, json={"ativo": True, "categorias": TODAS})).status_code == 403
        assert (await client.get("/api/portal/config", headers=hcuid)).status_code == 403

        # Auditoria: a mudanca de configuracao e cada acesso do familiar.
        assert await db.scalar(select(func.count()).select_from(m.Auditoria).where(
            m.Auditoria.acao == "portal_familia.config", m.Auditoria.ilpi_id == c.a.id)) == 2
        assert await db.scalar(select(func.count()).select_from(m.Auditoria).where(
            m.Auditoria.acao == "portal_familia.acesso", m.Auditoria.usuario_id == user.id)) == 3
    asyncio.run(_client(banco, op))


def test_config_e_por_ilpi_e_familiar_so_ve_o_proprio_residente(banco):
    async def op(client, db):
        c, user, hf = await _familiar_liberado(client, db)
        # A ILPI B liga tudo; isso nao liga nada na ILPI A.
        adm_b, hb = await _usuario(db, c.b, await _template(db, "ilpi_admin"), "ilpi_admin", "Adm B Sint")
        assert (await client.put("/api/portal/config", headers=hb, json={"ativo": True, "categorias": TODAS})).status_code == 200
        assert (await client.get("/api/portal/config", headers=c.ha)).json()["ativo"] is False
        assert (await client.get("/api/portal/resumo", headers=hf)).json()["portal_liberado"] is False

        assert (await client.put("/api/portal/config", headers=c.ha, json={"ativo": True, "categorias": TODAS})).status_code == 200
        db.add(m.SinalVital(residente_id=c.ra2, ilpi_id=c.a.id, peso=99.9, data=datetime.now(timezone.utc)))
        await db.commit()
        corpo = (await client.get("/api/portal/resumo", headers=hf)).json()
        assert corpo["residente_nome"] == "Dona Sintetica" and corpo["peso"] == []
        assert corpo["medicacao"] == {"feitos": 0, "total": 0, "percentual": None}

        # Sessao do familiar apontando para a outra ILPI: sem vinculo, nada abre.
        r = await client.get("/api/portal/resumo", headers=_headers(user, ilpi_id=c.b.id))
        assert r.status_code in (401, 403, 404)
        assert "Residente B" not in r.text
    asyncio.run(_client(banco, op))
