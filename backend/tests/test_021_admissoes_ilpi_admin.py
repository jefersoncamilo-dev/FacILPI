"""#103 / migration 021: o Administrador da ILPI conduz admissões.

A 016 criou ``admissoes:*`` sem grants e nenhum perfil podia recebê-las pela
interface; em ambiente real ninguém conduzia admissão. Decisão do responsável
(26/09): o template ``ilpi_admin`` e seus clones locais recebem as 7
permissões; os perfis institucionais da 015 seguem sem elas.

Somente bancos descartáveis (SQLite em tmp_path; PostgreSQL via D3_TEST_POSTGRES_URL).
"""

import asyncio
import os

import pytest
from sqlalchemy import select

from .test_d3_admissao_migration import _migrate, _ref
from .test_d3_admissao import ALL, URL, _client
from .test_d2_rotina import _create_ilpi_user, _headers, _new_institution
from src.infrastructure import models as m

HEAD = "021_admissoes_ilpi_admin"
PRE_021 = "020_documentos_admin_anexar"
OUTROS_TEMPLATES = ("administrativo", "responsavel_tecnico", "cuidador", "enfermagem", "medico")


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D3_TEST_POSTGRES_URL") else []))
def pre021_db(request, tmp_path):
    # Parado exatamente antes da 021, para exercitar a própria transição.
    ref = _ref(request, tmp_path)
    _migrate(ref, target=PRE_021)
    return ref


async def _chaves(db, chave, ilpi_id):
    consulta = (select(m.Permissao.chave).join(m.PerfilPermissao, m.PerfilPermissao.permissao_id == m.Permissao.id)
                .join(m.Perfil, m.Perfil.id == m.PerfilPermissao.perfil_id).where(m.Perfil.chave == chave))
    consulta = consulta.where(m.Perfil.ilpi_id.is_(None)) if ilpi_id is None else consulta.where(m.Perfil.ilpi_id == ilpi_id)
    return set((await db.scalars(consulta)).all())


def test_021_concede_admissoes_ao_administrador_e_so_a_ele(pre021_db):
    semeado = {}

    async def antes(client, db):
        instituicao = _new_institution("T021")
        # Clone local do administrador criado ANTES da 021 (ILPI já provisionada).
        gestor = await _create_ilpi_user(db, instituicao, permissions=set(), profile_key="ilpi_admin")
        await db.commit()
        semeado.update(gestor=gestor, ilpi=instituicao.id)
        assert not (await _chaves(db, "ilpi_admin", None)) & ALL
        assert (await client.get(URL, headers=_headers(gestor, ilpi_id=instituicao.id))).status_code == 403
    asyncio.run(_client(pre021_db, antes))

    _migrate(pre021_db, target=HEAD)

    async def depois(client, db):
        assert ALL <= await _chaves(db, "ilpi_admin", None), "template ilpi_admin sem admissoes"
        assert ALL <= await _chaves(db, "ilpi_admin", semeado["ilpi"]), "clone existente sem admissoes"
        for chave in OUTROS_TEMPLATES:
            assert not (await _chaves(db, chave, None)) & ALL, f"{chave} nao deveria conduzir admissoes"
        assert (await client.get(URL, headers=_headers(semeado["gestor"], ilpi_id=semeado["ilpi"]))).status_code == 200
    asyncio.run(_client(pre021_db, depois))


def test_021_idempotente_e_downgrade_remove_so_os_seus_grants(pre021_db):
    semeado = {}

    async def semear(client, db):
        instituicao = _new_institution("T021b")
        gestor = await _create_ilpi_user(db, instituicao, permissions={"residentes:ler"}, profile_key="ilpi_admin")
        await db.commit()
        semeado.update(gestor=gestor, ilpi=instituicao.id)
    asyncio.run(_client(pre021_db, semear))

    _migrate(pre021_db, target=HEAD)
    _migrate(pre021_db, target=HEAD)  # reaplicar a ponta não duplica vínculo

    async def conferir_unicos(client, db):
        perfis = (await db.scalars(select(m.Perfil.id).where(m.Perfil.chave == "ilpi_admin"))).all()
        for perfil in perfis:
            vinculos = (await db.scalars(
                select(m.Permissao.chave).join(m.PerfilPermissao, m.PerfilPermissao.permissao_id == m.Permissao.id)
                .where(m.PerfilPermissao.perfil_id == perfil, m.Permissao.modulo == "admissoes"))).all()
            assert sorted(vinculos) == sorted(ALL)
    asyncio.run(_client(pre021_db, conferir_unicos))

    _migrate(pre021_db, target=PRE_021, command="downgrade")

    async def apos_downgrade(client, db):
        assert not (await _chaves(db, "ilpi_admin", None)) & ALL
        # Só os grants da 021 saem: o que o clone já tinha continua.
        assert await _chaves(db, "ilpi_admin", semeado["ilpi"]) == {"residentes:ler"}
        assert (await client.get(URL, headers=_headers(semeado["gestor"], ilpi_id=semeado["ilpi"]))).status_code == 403
    asyncio.run(_client(pre021_db, apos_downgrade))
