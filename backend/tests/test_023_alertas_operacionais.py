"""#117 / migration 023: ``alertas:ler`` para os perfis operacionais da 015.

Antes da 023 so ``ilpi_admin`` le a central; depois, os templates cuidador,
enfermagem, medico, responsavel_tecnico e administrativo e seus clones locais
ja existentes a recebem. ``platform_superuser`` segue sem ela. O downgrade
remove exatamente esses vinculos, e a cadeia 023 -> 022 -> 021 continua
reversivel (a 022 recusa vinculos externos, entao a 023 precisa limpar os seus).

Somente bancos descartaveis (SQLite em tmp_path; PostgreSQL via D3_TEST_POSTGRES_URL).
"""

import asyncio
import os

import pytest
from sqlalchemy import func, select

from .test_022_alertas_gestor import _tem
from .test_d3_admissao_migration import _migrate, _ref
from .test_d3_admissao import _client
from .test_d2_rotina import _create_ilpi_user, _headers, _new_institution
from src.infrastructure import models as m

HEAD = "023_alertas_operacionais"
PRE_023 = "022_alertas_gestor"
PRE_022 = "021_admissoes_ilpi_admin"
URL = "/api/central-alertas/"
CHAVE = "alertas:ler"
OPERACIONAIS = ("cuidador", "enfermagem", "medico", "responsavel_tecnico", "administrativo")


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D3_TEST_POSTGRES_URL") else []))
def pre023_db(request, tmp_path):
    ref = _ref(request, tmp_path)
    _migrate(ref, target=PRE_023)
    return ref


async def _chaves_template(db, chave_perfil):
    return set((await db.scalars(
        select(m.Permissao.chave).join(m.PerfilPermissao, m.PerfilPermissao.permissao_id == m.Permissao.id)
        .join(m.Perfil, m.Perfil.id == m.PerfilPermissao.perfil_id)
        .where(m.Perfil.chave == chave_perfil, m.Perfil.ilpi_id.is_(None)))).all())


async def _chaves_perfil(db, perfil_id):
    return set((await db.scalars(
        select(m.Permissao.chave).join(m.PerfilPermissao, m.PerfilPermissao.permissao_id == m.Permissao.id)
        .where(m.PerfilPermissao.perfil_id == perfil_id))).all())


def test_023_concede_aos_perfis_operacionais_e_clones(pre023_db):
    semeado = {}

    async def antes(client, db):
        instituicao = _new_institution("T023")
        # Clones locais preexistentes: copiam o template no momento da criacao (S.1).
        usuarios = {}
        for chave in OPERACIONAIS:
            chaves = await _chaves_template(db, chave)
            assert CHAVE not in chaves
            usuarios[chave] = await _create_ilpi_user(db, instituicao, permissions=chaves, profile_key=chave,
                                                      nome=f"Usuario {chave} sintetico")
        await db.commit()
        perfis = {p.chave: p.id for p in (await db.scalars(select(m.Perfil).where(
            m.Perfil.ilpi_id == instituicao.id))).all()}
        semeado.update(ilpi=instituicao.id, usuarios=usuarios, perfis=perfis,
                       antes={chave: await _chaves_perfil(db, perfis[chave]) for chave in OPERACIONAIS})
        for chave in OPERACIONAIS:
            r = await client.get(URL, headers=_headers(usuarios[chave], ilpi_id=instituicao.id))
            assert r.status_code == 403, (chave, r.text)
    asyncio.run(_client(pre023_db, antes))

    _migrate(pre023_db, target=HEAD)
    _migrate(pre023_db, target=HEAD)  # reaplicar a ponta nao duplica vinculo

    async def depois(client, db):
        assert await db.scalar(select(func.count()).select_from(m.Permissao).where(m.Permissao.chave == CHAVE)) == 1
        for chave in OPERACIONAIS:
            assert await _tem(db, chave, None) == 1, f"template {chave} sem alertas:ler"
            assert await _tem(db, chave, semeado["ilpi"]) == 1, f"clone {chave} sem alertas:ler"
            assert await _chaves_perfil(db, semeado["perfis"][chave]) == semeado["antes"][chave] | {CHAVE}
            r = await client.get(URL, headers=_headers(semeado["usuarios"][chave], ilpi_id=semeado["ilpi"]))
            assert r.status_code == 200, (chave, r.text)
        assert await _tem(db, "ilpi_admin", None) == 1
        assert await _tem(db, "platform_superuser", None) == 0, "superusuario nao recebe alertas"
    asyncio.run(_client(pre023_db, depois))

    _migrate(pre023_db, target=PRE_023, command="downgrade")

    async def apos_downgrade(client, db):
        for chave in OPERACIONAIS:
            assert await _tem(db, chave, None) == 0
            # So o que a 023 criou sai: o clone mantem exatamente o que ja tinha.
            assert await _chaves_perfil(db, semeado["perfis"][chave]) == semeado["antes"][chave]
            r = await client.get(URL, headers=_headers(semeado["usuarios"][chave], ilpi_id=semeado["ilpi"]))
            assert r.status_code == 403, (chave, r.text)
        assert await _tem(db, "ilpi_admin", None) == 1, "a 022 continua valendo para o ilpi_admin"
    asyncio.run(_client(pre023_db, apos_downgrade))

    # A 022 recusa vinculos externos: sem a limpeza exata da 023, este passo falharia.
    _migrate(pre023_db, target=PRE_022, command="downgrade")

    async def apos_022(client, db):
        assert await db.scalar(select(func.count()).select_from(m.Permissao).where(m.Permissao.chave == CHAVE)) == 0
    asyncio.run(_client(pre023_db, apos_022))
