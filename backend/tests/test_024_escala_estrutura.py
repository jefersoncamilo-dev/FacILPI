"""#120 / migration 024: estrutura operacional (areas, turnos, plantao real, responsabilidade).

Concede escala:ler / escala:gerenciar / plantao:registrar conforme a matriz da
024 (templates e clones locais, por chave), cria as tabelas e o downgrade
recusa apagar historico operacional ou vinculos externos.

Somente bancos descartaveis (SQLite em tmp_path; PostgreSQL via D3_TEST_POSTGRES_URL).
"""

import asyncio
import os

import pytest
from sqlalchemy import func, select, text

from .test_d3_admissao_migration import _migrate, _ref
from .test_d3_admissao import _client
from .test_d2_rotina import _create_ilpi_user, _new_id, _new_institution
from src.infrastructure import models as m

HEAD = "024_escala_estrutura"
PRE_024 = "023_alertas_operacionais"
NOVAS = ("escala:ler", "escala:gerenciar", "plantao:registrar")
ESPERADO = {
    "ilpi_admin": {"escala:ler", "escala:gerenciar", "plantao:registrar"},
    "cuidador": {"escala:ler", "plantao:registrar"},
    "enfermagem": {"escala:ler", "plantao:registrar"},
    "responsavel_tecnico": {"escala:ler", "plantao:registrar"},
    "medico": {"escala:ler"},
    "administrativo": set(),
    "platform_superuser": set(),
}
TABELAS = ("areas_operacionais", "area_leitos", "turnos", "plantoes", "responsabilidades")


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D3_TEST_POSTGRES_URL") else []))
def pre024_db(request, tmp_path):
    ref = _ref(request, tmp_path)
    _migrate(ref, target=PRE_024)
    return ref


async def _novas_do_perfil(db, chave, ilpi_id):
    consulta = (select(m.Permissao.chave).join(m.PerfilPermissao, m.PerfilPermissao.permissao_id == m.Permissao.id)
                .join(m.Perfil, m.Perfil.id == m.PerfilPermissao.perfil_id)
                .where(m.Perfil.chave == chave, m.Permissao.chave.in_(NOVAS)))
    consulta = consulta.where(m.Perfil.ilpi_id.is_(None)) if ilpi_id is None else consulta.where(m.Perfil.ilpi_id == ilpi_id)
    return set((await db.scalars(consulta)).all())


def test_024_concede_cria_tabelas_e_reverte(pre024_db):
    semeado = {}

    async def antes(client, db):
        ilpi = _new_institution("T024")
        for chave in ("cuidador", "medico", "administrativo"):
            await _create_ilpi_user(db, ilpi, permissions=set(), profile_key=chave, nome=f"{chave} T024")
        await db.commit()
        semeado["ilpi"] = ilpi.id
        assert await db.scalar(select(func.count()).select_from(m.Permissao).where(m.Permissao.chave.in_(NOVAS))) == 0
    asyncio.run(_client(pre024_db, antes))

    _migrate(pre024_db, target=HEAD)

    async def depois(client, db):
        assert await db.scalar(select(func.count()).select_from(m.Permissao).where(m.Permissao.chave.in_(NOVAS))) == 3
        for chave, esperado in ESPERADO.items():
            assert await _novas_do_perfil(db, chave, None) == esperado, chave
        # Clones preexistentes tambem sao alcancados, por chave.
        assert await _novas_do_perfil(db, "cuidador", semeado["ilpi"]) == ESPERADO["cuidador"]
        assert await _novas_do_perfil(db, "medico", semeado["ilpi"]) == ESPERADO["medico"]
        assert await _novas_do_perfil(db, "administrativo", semeado["ilpi"]) == set()
        for tabela in TABELAS:
            assert await db.scalar(text(f"SELECT COUNT(*) FROM {tabela}")) == 0
    asyncio.run(_client(pre024_db, depois))

    # Historico operacional nao some em silencio.
    async def com_area(client, db):
        db.add(m.AreaOperacional(id=_new_id(), ilpi_id=semeado["ilpi"], nome="Ala B", tipo="ala", situacao="ativa"))
        await db.commit()
    asyncio.run(_client(pre024_db, com_area))
    falha = _migrate(pre024_db, target=PRE_024, command="downgrade", success=False)
    assert "areas_operacionais tem historico" in falha.stdout + falha.stderr

    # Vinculo externo (perfil local que recebeu escala:ler do gestor) tambem barra o downgrade.
    async def externo(client, db):
        await db.execute(text("DELETE FROM areas_operacionais"))
        await _create_ilpi_user(db, _new_institution("T024 externo"), permissions={"escala:ler"}, profile_key="coordenacao")
        await db.commit()
    asyncio.run(_client(pre024_db, externo))
    falha = _migrate(pre024_db, target=PRE_024, command="downgrade", success=False)
    assert "vinculos externos" in falha.stdout + falha.stderr

    async def sem_externo(client, db):
        await db.execute(text("DELETE FROM perfil_permissoes WHERE perfil_id IN (SELECT id FROM perfis WHERE chave = 'coordenacao')"))
        await db.commit()
    asyncio.run(_client(pre024_db, sem_externo))
    _migrate(pre024_db, target=PRE_024, command="downgrade")

    async def apos(client, db):
        assert await db.scalar(select(func.count()).select_from(m.Permissao).where(m.Permissao.chave.in_(NOVAS))) == 0
        for chave in ESPERADO:
            assert await _novas_do_perfil(db, chave, None) == set()
    asyncio.run(_client(pre024_db, apos))
    # A cadeia continua reversivel ate a 022 (que recusa vinculos externos de alertas:ler).
    _migrate(pre024_db, target="022_alertas_gestor", command="downgrade")
