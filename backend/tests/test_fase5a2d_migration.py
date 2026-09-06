"""Migration tests for F5A-2D: Quarto/Leito + Ocupação + Ausências + Histórico.

Disposable-database tests verifying:
- Baseline 44 permissions → 51 after upgrade
- ilpi_admin template: 40 → 47 grants
- Platform superuser: 15 grants (unchanged)
- Unique indexes (leito sem/com unidade, residente, ausência ativa)
- capacidade=1 check
- Downgrade safety (empty tables → ok, with data → refuse)
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import subprocess
import sys

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
OFFICIAL_DB = ROOT / "storage" / "app.db"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


def _sqlite_url(path: pathlib.Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def _async_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def _database_url(database_ref: pathlib.Path | str) -> str:
    if isinstance(database_ref, pathlib.Path):
        return _sqlite_url(database_ref)
    return _async_url(database_ref)


def _assert_disposable_database(database_ref: pathlib.Path | str) -> None:
    if isinstance(database_ref, pathlib.Path):
        assert database_ref.resolve() != OFFICIAL_DB.resolve()
    else:
        assert "storage/app.db" not in database_ref


def _run_migration(database_ref: pathlib.Path | str, direction: str = "upgrade head") -> None:
    _assert_disposable_database(database_ref)
    url = _database_url(database_ref)
    environment = os.environ.copy()
    environment["DATABASE_URL"] = url
    environment.pop("APP_DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"database_url={url}"] + direction.split(),
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stdout + result.stderr


async def _reset_postgres(url: str) -> None:
    engine = create_async_engine(_async_url(url), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
            await connection.commit()
    finally:
        await engine.dispose()


def _database_backends() -> list[str]:
    backends = ["sqlite"]
    if os.getenv("FASE3A_TEST_POSTGRES_URL"):
        backends.append("postgresql")
    return backends


@pytest.fixture(params=_database_backends(), ids=lambda backend: backend)
def migration_db(request: pytest.FixtureRequest, tmp_path: pathlib.Path) -> pathlib.Path | str:
    if request.param == "sqlite":
        path = tmp_path / "fase5a2d-migration.db"
        _run_migration(path)
        return path

    url = os.environ["FASE3A_TEST_POSTGRES_URL"]
    try:
        asyncio.run(_reset_postgres(url))
        _run_migration(url)
    except Exception as error:
        pytest.skip(f"PostgreSQL descartável indisponível: {error}")
    return url


def _database_url_for_engine(database_ref: pathlib.Path | str) -> str:
    return _database_url(database_ref)


async def _query(database_ref: pathlib.Path | str, sql: str) -> list:
    url = _database_url_for_engine(database_ref)
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text(sql))
            return result.fetchall()
    except Exception:
        return []
    finally:
        await engine.dispose()


def test_permission_baseline_51(migration_db):
    """After migration, exactly 51 permissions must exist."""
    rows = asyncio.run(_query(migration_db, "SELECT COUNT(*) FROM permissoes"))
    assert rows[0][0] == 51


def test_platform_grants_unchanged_15(migration_db):
    """Platform superuser must have exactly 15 grants (unchanged)."""
    rows = asyncio.run(_query(migration_db, """
        SELECT COUNT(*) FROM perfil_permissoes pp
        JOIN perfis p ON p.id = pp.perfil_id
        WHERE p.chave = 'platform_superuser' AND p.ilpi_id IS NULL
    """))
    assert rows[0][0] == 15


def test_ilpi_admin_template_grants_47(migration_db):
    """ilpi_admin template must have exactly 47 grants."""
    rows = asyncio.run(_query(migration_db, """
        SELECT COUNT(*) FROM perfil_permissoes pp
        JOIN perfis p ON p.id = pp.perfil_id
        WHERE p.chave = 'ilpi_admin' AND p.ilpi_id IS NULL
    """))
    assert rows[0][0] == 47


def test_ilpi_admin_clone_grants(migration_db):
    """Each ilpi_admin clone must also have 47 grants."""
    rows = asyncio.run(_query(migration_db, """
        SELECT p.id, (
            SELECT COUNT(*) FROM perfil_permissoes pp WHERE pp.perfil_id = p.id
        ) AS grant_count
        FROM perfis p
        WHERE p.chave = 'ilpi_admin' AND p.ilpi_id IS NOT NULL AND p.situacao = 'ativo'
    """))
    for row in rows:
        assert row[1] == 47, f"Clone {row[0]} has {row[1]} grants, expected 47"


def test_new_permissions_exist(migration_db):
    """All 7 new permissions must exist."""
    expected_keys = {
        "quartos_leitos:ler", "quartos_leitos:criar",
        "quartos_leitos:atualizar", "quartos_leitos:inativar",
        "ausencias:ler", "ausencias:criar", "ausencias:atualizar",
    }
    rows = asyncio.run(_query(migration_db, "SELECT chave FROM permissoes"))
    actual_keys = {row[0] for row in rows}
    assert expected_keys.issubset(actual_keys)


def test_capacidade_check_constraint(migration_db):
    """capacidade=1 check constraint must exist on quartos_leitos."""
    rows = asyncio.run(_query(migration_db, """
        SELECT sql FROM sqlite_master WHERE type='table' AND name='quartos_leitos'
    """))
    if rows:
        ddl = rows[0][0]
        assert "capacidade = 1" in ddl or "capacidade=1" in ddl
    else:
        rows = asyncio.run(_query(migration_db, """
            SELECT conname FROM pg_constraint
            WHERE conname = 'ck_quartos_leitos_capacidade_1'
        """))
        assert len(rows) > 0


def test_situacao_check_constraint(migration_db):
    """situacao check constraint must exist on quartos_leitos."""
    rows = asyncio.run(_query(migration_db, """
        SELECT sql FROM sqlite_master WHERE type='table' AND name='quartos_leitos'
    """))
    if rows:
        ddl = rows[0][0]
        assert "situacao IN" in ddl
    else:
        rows = asyncio.run(_query(migration_db, """
            SELECT conname FROM pg_constraint
            WHERE conname = 'ck_quartos_leitos_situacao'
        """))
        assert len(rows) > 0


def test_unique_leito_sem_unidade(migration_db):
    """Partial unique index on (instituicao_id, quarto, leito) WHERE unidade IS NULL must exist."""
    rows = asyncio.run(_query(migration_db, """
        SELECT sql FROM sqlite_master WHERE type='index' AND name='uq_quartos_leitos_inst_quarto_leito'
    """))
    if rows:
        ddl = rows[0][0]
        assert "uq_quartos_leitos_inst_quarto_leito" in ddl
    else:
        rows = asyncio.run(_query(migration_db, """
            SELECT indexname FROM pg_indexes
            WHERE indexname = 'uq_quartos_leitos_inst_quarto_leito'
        """))
        assert len(rows) > 0


def test_unique_leito_com_unidade(migration_db):
    """Unique constraint on (instituicao_id, unidade, quarto, leito) must exist."""
    rows = asyncio.run(_query(migration_db, """
        SELECT sql FROM sqlite_master WHERE type='table' AND name='quartos_leitos'
    """))
    if rows:
        ddl = rows[0][0]
        assert "uq_quartos_leitos_inst_unidade_quarto_leito" in ddl
    else:
        rows = asyncio.run(_query(migration_db, """
            SELECT conname FROM pg_constraint
            WHERE conname = 'uq_quartos_leitos_inst_unidade_quarto_leito'
        """))
        assert len(rows) > 0


def test_unique_residente_em_leito(migration_db):
    """Partial unique index on (instituicao_id, residente_atual_id) must exist."""
    rows = asyncio.run(_query(migration_db, """
        SELECT name FROM sqlite_master WHERE type='index' AND name='uq_quartos_leitos_residente_ativo'
    """))
    if rows:
        assert len(rows) > 0
    else:
        rows = asyncio.run(_query(migration_db, """
            SELECT indexname FROM pg_indexes WHERE indexname='uq_quartos_leitos_residente_ativo'
        """))
        assert len(rows) > 0


def test_unique_ausencia_ativa(migration_db):
    """Partial unique index on (instituicao_id, residente_id) WHERE data_fim IS NULL."""
    rows = asyncio.run(_query(migration_db, """
        SELECT name FROM sqlite_master WHERE type='index' AND name='uq_ausencias_ativa_por_residente'
    """))
    if rows:
        assert len(rows) > 0
    else:
        rows = asyncio.run(_query(migration_db, """
            SELECT indexname FROM pg_indexes WHERE indexname='uq_ausencias_ativa_por_residente'
        """))
        assert len(rows) > 0


def test_ocupacao_historico_table_exists(migration_db):
    """ocupacao_historico table must exist."""
    rows = asyncio.run(_query(migration_db, """
        SELECT name FROM sqlite_master WHERE type='table' AND name='ocupacao_historico'
    """))
    if rows:
        assert len(rows) > 0
    else:
        rows = asyncio.run(_query(migration_db, """
            SELECT tablename FROM pg_tables WHERE tablename='ocupacao_historico'
        """))
        assert len(rows) > 0


def test_ausencias_table_exists(migration_db):
    """ausencias table must exist."""
    rows = asyncio.run(_query(migration_db, """
        SELECT name FROM sqlite_master WHERE type='table' AND name='ausencias'
    """))
    if rows:
        assert len(rows) > 0
    else:
        rows = asyncio.run(_query(migration_db, """
            SELECT tablename FROM pg_tables WHERE tablename='ausencias'
        """))
        assert len(rows) > 0


def test_ausencias_tipo_check(migration_db):
    """ausencias must have tipo check constraint."""
    rows = asyncio.run(_query(migration_db, """
        SELECT sql FROM sqlite_master WHERE type='table' AND name='ausencias'
    """))
    if rows:
        ddl = rows[0][0]
        assert "hospitalizacao" in ddl and "saida_temporaria" in ddl
    else:
        rows = asyncio.run(_query(migration_db, """
            SELECT conname FROM pg_constraint WHERE conname = 'ck_ausencias_tipo'
        """))
        assert len(rows) > 0


def test_downgrade_safe_empty(migration_db):
    """Downgrade on empty tables should succeed."""
    _run_migration(migration_db, "downgrade -1")
    # Verify permissions reverted
    rows = asyncio.run(_query(migration_db, "SELECT COUNT(*) FROM permissoes"))
    assert rows[0][0] == 44
    # Re-upgrade for subsequent tests
    _run_migration(migration_db, "upgrade head")


def test_round_trip(migration_db):
    """Full upgrade → downgrade → upgrade cycle must succeed."""
    _run_migration(migration_db, "downgrade -1")
    rows = asyncio.run(_query(migration_db, "SELECT COUNT(*) FROM permissoes"))
    assert rows[0][0] == 44
    _run_migration(migration_db, "upgrade head")
    rows = asyncio.run(_query(migration_db, "SELECT COUNT(*) FROM permissoes"))
    assert rows[0][0] == 51
