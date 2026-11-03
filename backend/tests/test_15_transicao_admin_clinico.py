"""#15 (migration 034, D3 = opcao B): escritas clinicas saem do ilpi_admin com
transicao de 30 dias por ILPI. Banco descartavel (harness da C5, revisao head)."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from src.application.security import ESCRITAS_CLINICAS_ADMIN
from src.infrastructure import models as m

from . import test_fase5a3b_sinais_vitais_rbac_tenant as h
from .banco_modelo import migrar_de_modelo
from .test_c5_medicacao_migration import _url, c5_migration_db  # noqa: F401 (fixture)

SV = "/api/sinais-vitais/"
LEITURAS = {"residentes:ler", "sinais_vitais:ler", "alertas:ler", "avaliacoes:ler", "planos_cuidados:ler"}


@pytest.fixture
def head_db(c5_migration_db):
    migrar_de_modelo(_url(c5_migration_db), "head")
    return c5_migration_db


async def _grants_template(db, chave):
    return set((await db.execute(text(
        "SELECT p.chave FROM perfil_permissoes pp JOIN permissoes p ON p.id = pp.permissao_id "
        "JOIN perfis pe ON pe.id = pp.perfil_id WHERE pe.chave = :c AND pe.ilpi_id IS NULL"), {"c": chave})).scalars())


async def _usuario(db, ilpi, chave):
    """Clone por chave com os grants do template, como o clone-on-assign faz."""
    user = await h._create_ilpi_user(db, ilpi, permissions=await _grants_template(db, chave), profile_key=chave,
                                     nome=f"Pessoa {chave}")
    return user, h._auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)


async def _ilpi(db, prazo):
    ilpi = h._new_institution("ILPI transicao")
    db.add(ilpi)
    await db.flush()
    if prazo is not None:
        db.add(m.TransicaoAdminClinico(ilpi_id=ilpi.id, prazo=prazo))
    residente = await h._create_residente(db, ilpi.id)
    return ilpi, residente


def test_15_template_sem_escritas_clinicas(head_db):
    async def scenario(client, db):
        admin = await _grants_template(db, "ilpi_admin")
        assert not admin & ESCRITAS_CLINICAS_ADMIN
        # Leituras, Alertas e gestao institucional ficam.
        assert LEITURAS <= admin
        assert {"usuarios:atribuir_perfil", "residentes:criar", "alertas:assumir"} <= admin
        # Os perfis clinicos nao mudam.
        assert {"execucoes:criar", "sinais_vitais:criar"} <= await _grants_template(db, "enfermagem")
    asyncio.run(h._with_client(head_db, scenario))


def test_15_carencia_ate_o_prazo_e_corte_depois(head_db):
    async def scenario(client, db):
        agora = datetime.now(timezone.utc)
        em_prazo, r1 = await _ilpi(db, agora + timedelta(days=10))
        vencida, r2 = await _ilpi(db, agora - timedelta(minutes=1))
        nova, r3 = await _ilpi(db, None)
        _, h1 = await _usuario(db, em_prazo, "ilpi_admin")
        _, h2 = await _usuario(db, vencida, "ilpi_admin")
        _, h3 = await _usuario(db, nova, "ilpi_admin")
        await db.commit()
        # Dentro do prazo: a escrita clinica ainda vale e aparece nas permissoes da sessao.
        r = await client.post(SV, headers=h1, json={"residente_id": r1.id, "temperatura": 36.5})
        assert r.status_code == 201, r.text
        assert ESCRITAS_CLINICAS_ADMIN <= set((await client.get("/api/auth/permissoes", headers=h1)).json()["permissoes"])
        # Prazo vencido ou ILPI sem transicao: perde so a escrita clinica.
        for hdr, res in ((h2, r2), (h3, r3)):
            r = await client.post(SV, headers=hdr, json={"residente_id": res.id, "temperatura": 36.5})
            assert r.status_code == 403, r.text
            assert (await client.get(SV, headers=hdr)).status_code == 200
            assert (await client.get("/api/central-alertas/", headers=hdr)).status_code == 200
            chaves = set((await client.get("/api/auth/permissoes", headers=hdr)).json()["permissoes"])
            assert not chaves & ESCRITAS_CLINICAS_ADMIN and LEITURAS <= chaves
        # Historico clinico registrado na carencia continua la.
        assert (await client.get(SV, headers=h1)).json()
    asyncio.run(h._with_client(head_db, scenario))


def test_15_carencia_nao_vaza_para_outros_perfis_nem_platform(head_db):
    async def scenario(client, db):
        ilpi, res = await _ilpi(db, datetime.now(timezone.utc) + timedelta(days=10))
        _, adm = await _usuario(db, ilpi, "administrativo")
        _, cuid = await _usuario(db, ilpi, "cuidador")
        platform = await h._create_platform_user(db)
        await db.commit()
        assert (await client.post(SV, headers=adm, json={"residente_id": res.id, "temperatura": 36.5})).status_code == 403
        chaves = set((await client.get("/api/auth/permissoes", headers=cuid)).json()["permissoes"])
        assert "sinais_vitais:criar" not in chaves and "planos_cuidados:aprovar" not in chaves
        ph = h._auth_headers(platform, scope="global")
        assert (await client.get("/api/transicao-clinica/", headers=ph)).status_code == 403
    asyncio.run(h._with_client(head_db, scenario))


def test_15_aviso_da_ilpi_e_relatorio_do_platform(head_db):
    async def scenario(client, db):
        prazo = datetime.now(timezone.utc) + timedelta(days=20)
        sem, _ = await _ilpi(db, prazo)
        com, _ = await _ilpi(db, prazo)
        _, h_sem = await _usuario(db, sem, "ilpi_admin")
        _, h_com = await _usuario(db, com, "ilpi_admin")
        await _usuario(db, com, "enfermagem")
        platform = await h._create_platform_user(db)
        await db.commit()
        r = (await client.get("/api/transicao-clinica/", headers=h_sem)).json()
        assert r["afeta_esta_sessao"] and r["em_carencia"] and not r["perfil_clinico_atribuido"]
        assert set(r["escritas_retiradas"]) == ESCRITAS_CLINICAS_ADMIN
        assert (await client.get("/api/transicao-clinica/", headers=h_com)).json()["perfil_clinico_atribuido"]
        # Relatorio so do Platform (escopo global); a ILPI nao o le.
        assert (await client.get("/api/platform/transicao-clinica", headers=h_sem)).status_code == 403
        rel = {x["ilpi_id"]: x for x in (await client.get(
            "/api/platform/transicao-clinica", headers=h._auth_headers(platform, scope="global"))).json()}
        assert rel[sem.id]["perfil_clinico_atribuido"] is False and rel[com.id]["perfil_clinico_atribuido"] is True
        assert rel[sem.id]["em_carencia"] and set(rel[sem.id]["escritas_que_o_administrador_perde"]) == ESCRITAS_CLINICAS_ADMIN
    asyncio.run(h._with_client(head_db, scenario))
