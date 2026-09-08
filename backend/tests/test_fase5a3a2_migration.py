"""Migration tests for Phase F5A-3A2: Grau de Dependência — source + RBAC.

- Baseline at 009: 54 permissions / ilpi_admin 50 / platform 15
- After 010: 56 permissions / ilpi_admin 52 / platform 15 (zero clinical)
- Table, constraints, partial unique index on both dialects
- Backfill: exact legacy matches migrate as origem=migracao; junk skipped
- Downgrade removes table + grants; round-trip upgrade works
- RBAC upgrade is idempotent

Never touches storage/app.db.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import subprocess
import sys
import uuid
from datetime import date

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
OFFICIAL_DB = ROOT / "storage" / "app.db"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

REV_009 = "009_f5a3a1_avaliacoes_rbac"
REV_010 = "010_f5a3a2_grau_dependencia"

GRAU_LER_ID = "fac11000-0000-4000-8000-000000000055"
GRAU_CRIAR_ID = "fac11000-0000-4000-8000-000000000056"


def _async_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def _database_url(ref: pathlib.Path | str) -> str:
    if isinstance(ref, pathlib.Path):
        return f"sqlite+aiosqlite:///{ref.resolve().as_posix()}"
    return _async_url(ref)


def _assert_disposable(ref: pathlib.Path | str) -> None:
    if isinstance(ref, pathlib.Path):
        assert ref.resolve() != OFFICIAL_DB.resolve()
    else:
        assert "storage/app.db" not in ref


def _alembic(ref: pathlib.Path | str, *args: str) -> None:
    _assert_disposable(ref)
    url = _database_url(ref)
    environment = os.environ.copy()
    environment["DATABASE_URL"] = url
    environment.pop("APP_DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"database_url={url}", *args],
        cwd=BACKEND,
        env=environment,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
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


def _backends() -> list[str]:
    backends = ["sqlite"]
    if os.getenv("FASE3A_TEST_POSTGRES_URL"):
        backends.append("postgresql")
    return backends


@pytest.fixture(params=_backends(), ids=lambda backend: backend)
def migration_db(request: pytest.FixtureRequest, tmp_path: pathlib.Path) -> pathlib.Path | str:
    if request.param == "sqlite":
        return tmp_path / "f5a3a2-migration.db"
    url = os.environ["FASE3A_TEST_POSTGRES_URL"]
    try:
        asyncio.run(_reset_postgres(url))
    except Exception as error:
        pytest.skip(f"PostgreSQL descartavel indisponivel: {error}")
    return url


def _session_factory(ref: pathlib.Path | str):
    engine = create_async_engine(_database_url(ref), poolclass=NullPool)
    return engine, async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def _counts(db: AsyncSession) -> tuple[int, int, int]:
    total = (await db.execute(text("SELECT COUNT(*) FROM permissoes"))).scalar()
    ilpi = (await db.execute(text(
        "SELECT COUNT(*) FROM perfil_permissoes pp JOIN perfis p ON p.id = pp.perfil_id "
        "WHERE p.chave = 'ilpi_admin' AND p.ilpi_id IS NULL"
    ))).scalar()
    plat = (await db.execute(text(
        "SELECT COUNT(*) FROM perfil_permissoes pp JOIN perfis p ON p.id = pp.perfil_id "
        "WHERE p.chave = 'platform_superuser' AND p.ilpi_id IS NULL"
    ))).scalar()
    return total, ilpi, plat


def test_01_baseline_009_counts(migration_db):
    """At 009: catalog 54, ilpi_admin 50, platform 15, no grau table."""
    _alembic(migration_db, "upgrade", REV_009)
    engine, factory = _session_factory(migration_db)
    try:
        async def check():
            async with factory() as db:
                assert await _counts(db) == (54, 50, 15)
                grau = (await db.execute(text("SELECT COUNT(*) FROM permissoes WHERE modulo = 'grau_dependencia'"))).scalar()
                assert grau == 0
        asyncio.run(check())
    finally:
        asyncio.run(engine.dispose())


def test_02_upgrade_010_counts(migration_db):
    """After 010: catalog 56, ilpi_admin 52, platform 15."""
    _alembic(migration_db, "upgrade", "head")
    engine, factory = _session_factory(migration_db)
    try:
        async def check():
            async with factory() as db:
                assert await _counts(db) == (56, 52, 15)
                rows = (await db.execute(text("SELECT id, chave FROM permissoes WHERE modulo = 'grau_dependencia' ORDER BY chave"))).mappings().all()
                assert [(r["id"], r["chave"]) for r in rows] == [
                    (GRAU_CRIAR_ID, "grau_dependencia:criar"),
                    (GRAU_LER_ID, "grau_dependencia:ler"),
                ]
                plat_clinical = (await db.execute(text(
                    "SELECT COUNT(*) FROM perfil_permissoes pp "
                    "JOIN perfis p ON p.id = pp.perfil_id "
                    "JOIN permissoes m ON m.id = pp.permissao_id "
                    "WHERE p.chave = 'platform_superuser' AND m.modulo = 'grau_dependencia'"
                ))).scalar()
                assert plat_clinical == 0
        asyncio.run(check())
    finally:
        asyncio.run(engine.dispose())


def test_03_table_constraints_indexes(migration_db):
    """graus_dependencia exists with checks + partial unique active index."""
    _alembic(migration_db, "upgrade", "head")
    engine, factory = _session_factory(migration_db)
    try:
        async def check():
            async with factory() as db:
                if isinstance(migration_db, pathlib.Path):
                    idx = (await db.execute(text(
                        "SELECT name, sql FROM sqlite_master WHERE type = 'index' AND tbl_name = 'graus_dependencia'"
                    ))).all()
                    by_name = {name: sql for name, sql in idx}
                    assert "uq_graus_ativo_por_residente" in by_name
                    assert "WHERE situacao = 'ativo'" in by_name["uq_graus_ativo_por_residente"]
                    assert "ix_graus_ilpi_residente" in by_name
                    assert "ix_graus_avaliacao" in by_name
                    tbl = (await db.execute(text(
                        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'graus_dependencia'"
                    ))).scalar()
                    for token in ("ck_graus_classificacao", "ck_graus_origem", "ck_graus_situacao",
                                  "ck_graus_origem_avaliacao", "ck_graus_confirmado_por", "fk_graus_residente_ilpi"):
                        assert token in tbl, f"missing {token}"
                else:
                    idx = (await db.execute(text(
                        "SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'graus_dependencia'"
                    ))).all()
                    by_name = {name: definition for name, definition in idx}
                    assert "uq_graus_ativo_por_residente" in by_name
                    parcial = by_name["uq_graus_ativo_por_residente"]
                    assert "WHERE" in parcial and "situacao" in parcial and "'ativo'" in parcial
                    assert "UNIQUE" in parcial
                    cons = (await db.execute(text(
                        "SELECT conname FROM pg_constraint WHERE conrelid = 'graus_dependencia'::regclass"
                    ))).scalars().all()
                    for token in ("ck_graus_classificacao", "ck_graus_origem", "ck_graus_situacao",
                                  "ck_graus_origem_avaliacao", "ck_graus_confirmado_por", "fk_graus_residente_ilpi"):
                        assert token in cons, f"missing {token}"
        asyncio.run(check())
    finally:
        asyncio.run(engine.dispose())


def test_04_backfill_exact_matches_only(migration_db):
    """Legacy exact labels migrate as migracao; junk/NULL skipped, no author invented."""
    _alembic(migration_db, "upgrade", REV_009)
    engine, factory = _session_factory(migration_db)
    ilpi_id = str(uuid.uuid4())
    try:
        async def seed():
            async with factory() as db:
                await db.execute(text("INSERT INTO instituicoes (id, razao_social, situacao) VALUES (:id, 'ILPI Backfill', 'ATIVA')"), {"id": ilpi_id})
                residentes = [
                    ("Grau I", str(uuid.uuid4())),
                    ("  Grau III  ", str(uuid.uuid4())),
                    ("Dependente total", str(uuid.uuid4())),
                    (None, str(uuid.uuid4())),
                ]
                for grau, res_id in residentes:
                    await db.execute(
                        text("INSERT INTO residentes (id, instituicao_id, nome, data_nascimento, grau_dependencia) VALUES (:id, :ilpi, :nome, '1940-05-01', :grau)"),
                        {"id": res_id, "ilpi": ilpi_id, "nome": f"Res {res_id[:8]}", "grau": grau},
                    )
                await db.commit()
                return residentes
        residentes = asyncio.run(seed())
        _alembic(migration_db, "upgrade", "head")

        async def check():
            async with factory() as db:
                rows = (await db.execute(text(
                    "SELECT residente_id, classificacao, origem, avaliacao_id, confirmado_por, situacao, justificativa "
                    "FROM graus_dependencia ORDER BY classificacao"
                ))).mappings().all()
                assert len(rows) == 2
                assert {(r["classificacao"], r["origem"], r["situacao"]) for r in rows} == {
                    ("Grau I", "migracao", "ativo"), ("Grau III", "migracao", "ativo"),
                }
                for r in rows:
                    assert r["avaliacao_id"] is None
                    assert r["confirmado_por"] is None  # no invented author
                    assert r["justificativa"]
                # legacy column untouched
                legado = (await db.execute(text("SELECT grau_dependencia FROM residentes WHERE grau_dependencia = 'Grau I'"))).scalar()
                assert legado == "Grau I"
        asyncio.run(check())
    finally:
        asyncio.run(engine.dispose())


def test_05_downgrade_roundtrip(migration_db):
    """Downgrade 010->009 removes table + grants; re-upgrade restores."""
    _alembic(migration_db, "upgrade", "head")
    _alembic(migration_db, "downgrade", REV_009)
    engine, factory = _session_factory(migration_db)
    try:
        async def check_down():
            async with factory() as db:
                assert await _counts(db) == (54, 50, 15)
                if isinstance(migration_db, pathlib.Path):
                    tbl = (await db.execute(text("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'graus_dependencia'"))).scalar()
                    assert tbl is None
                else:
                    exists = (await db.execute(text("SELECT to_regclass('public.graus_dependencia')"))).scalar()
                    assert exists is None
        asyncio.run(check_down())
    finally:
        asyncio.run(engine.dispose())
    _alembic(migration_db, "upgrade", "head")
    engine, factory = _session_factory(migration_db)
    try:
        async def check_up():
            async with factory() as db:
                assert await _counts(db) == (56, 52, 15)
        asyncio.run(check_up())
    finally:
        asyncio.run(engine.dispose())


def test_06_upgrade_idempotent(migration_db):
    """Running upgrade head twice is a no-op with stable counts."""
    _alembic(migration_db, "upgrade", "head")
    _alembic(migration_db, "upgrade", "head")
    engine, factory = _session_factory(migration_db)
    try:
        async def check():
            async with factory() as db:
                assert await _counts(db) == (56, 52, 15)
        asyncio.run(check())
    finally:
        asyncio.run(engine.dispose())


def test_07_security_module_registers_grau():
    """security.py lists grau permissions as ILPI-only and clinical."""
    from src.application.security import _CLINICAL_MODULES, _ILPI_ONLY_PERMISSIONS
    assert "grau_dependencia:ler" in _ILPI_ONLY_PERMISSIONS
    assert "grau_dependencia:criar" in _ILPI_ONLY_PERMISSIONS
    assert "grau_dependencia" in _CLINICAL_MODULES


def test_08_official_database_intact(migration_db):
    if isinstance(migration_db, pathlib.Path):
        assert migration_db.resolve() != OFFICIAL_DB.resolve()
