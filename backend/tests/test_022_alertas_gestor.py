"""#107 / migration 022: ``alertas:ler`` so para o Administrador da ILPI.

Antes da 022 nao existe a permissao e a central responde 403; depois, template
``ilpi_admin`` e clones locais ja existentes a recebem, os perfis
institucionais da 015 seguem sem ela, e o downgrade remove exatamente o que a
022 criou.

Somente bancos descartaveis (SQLite em tmp_path; PostgreSQL via D3_TEST_POSTGRES_URL).
"""

import asyncio
import os

import pytest
from sqlalchemy import func, select

from .test_d3_admissao_migration import _migrate, _ref
from .test_d3_admissao import _client
from .test_d2_rotina import _create_ilpi_user, _headers, _new_institution
from src.infrastructure import models as m

HEAD = "022_alertas_gestor"
PRE_022 = "021_admissoes_ilpi_admin"
URL = "/api/central-alertas/"
CHAVE = "alertas:ler"
OUTROS_TEMPLATES = ("administrativo", "responsavel_tecnico", "cuidador", "enfermagem", "medico")


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D3_TEST_POSTGRES_URL") else []))
def pre022_db(request, tmp_path):
    ref = _ref(request, tmp_path)
    _migrate(ref, target=PRE_022)
    return ref


async def _tem(db, chave_perfil, ilpi_id):
    consulta = (select(func.count()).select_from(m.PerfilPermissao)
                .join(m.Permissao, m.Permissao.id == m.PerfilPermissao.permissao_id)
                .join(m.Perfil, m.Perfil.id == m.PerfilPermissao.perfil_id)
                .where(m.Permissao.chave == CHAVE, m.Perfil.chave == chave_perfil))
    consulta = consulta.where(m.Perfil.ilpi_id.is_(None)) if ilpi_id is None else consulta.where(m.Perfil.ilpi_id == ilpi_id)
    return await db.scalar(consulta)


def test_022_concede_ao_administrador_e_so_a_ele(pre022_db):
    semeado = {}

    async def antes(client, db):
        instituicao = _new_institution("T022")
        gestor = await _create_ilpi_user(db, instituicao, permissions={"residentes:ler"}, profile_key="ilpi_admin")
        await db.commit()
        semeado.update(gestor=gestor, ilpi=instituicao.id)
        assert await db.scalar(select(func.count()).select_from(m.Permissao).where(m.Permissao.chave == CHAVE)) == 0
        assert (await client.get(URL, headers=_headers(gestor, ilpi_id=instituicao.id))).status_code == 403
    asyncio.run(_client(pre022_db, antes))

    _migrate(pre022_db, target=HEAD)
    _migrate(pre022_db, target=HEAD)  # reaplicar a ponta nao duplica vinculo

    async def depois(client, db):
        assert await _tem(db, "ilpi_admin", None) == 1, "template ilpi_admin sem alertas:ler"
        assert await _tem(db, "ilpi_admin", semeado["ilpi"]) == 1, "clone existente sem alertas:ler"
        for chave in OUTROS_TEMPLATES:
            assert await _tem(db, chave, None) == 0, f"{chave} nao deveria receber alertas"
        r = await client.get(URL, headers=_headers(semeado["gestor"], ilpi_id=semeado["ilpi"]))
        assert r.status_code == 200, r.text
    asyncio.run(_client(pre022_db, depois))

    _migrate(pre022_db, target=PRE_022, command="downgrade")

    async def apos_downgrade(client, db):
        assert await db.scalar(select(func.count()).select_from(m.Permissao).where(m.Permissao.chave == CHAVE)) == 0
        # So o que a 022 criou sai: o clone mantem o que ja tinha.
        restantes = set((await db.scalars(
            select(m.Permissao.chave).join(m.PerfilPermissao, m.PerfilPermissao.permissao_id == m.Permissao.id)
            .join(m.Perfil, m.Perfil.id == m.PerfilPermissao.perfil_id)
            .where(m.Perfil.chave == "ilpi_admin", m.Perfil.ilpi_id == semeado["ilpi"]))).all())
        assert restantes == {"residentes:ler"}
        assert (await client.get(URL, headers=_headers(semeado["gestor"], ilpi_id=semeado["ilpi"]))).status_code == 403
    asyncio.run(_client(pre022_db, apos_downgrade))
