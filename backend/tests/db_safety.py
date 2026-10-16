"""Fail-closed helpers for disposable backend test databases."""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
from urllib.parse import unquote

from sqlalchemy.engine import make_url


ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
OFFICIAL_DB = (ROOT / "storage" / "app.db").resolve()
BACKEND_OFFICIAL_DB = (ROOT / "backend" / "storage" / "app.db").resolve()
_TEMP_ROOTS: set[pathlib.Path] = set()

PG_MANIFEST = {
    "host": "127.0.0.1",
    "port": int(os.getenv("FASE_TEST_PG_PORT", "55486")),
    "database": os.getenv("FASE_TEST_PG_DATABASE", "facilpi_qa_test"),
    "user": os.getenv("FASE_TEST_PG_USER", "postgres"),
    "runner_id": os.getenv("GITHUB_RUN_ID", "local"),
    "disposable": True,
}


def register_temp_root(path: pathlib.Path) -> pathlib.Path:
    root = path.resolve()
    root.mkdir(parents=True, exist_ok=True)
    _TEMP_ROOTS.add(root)
    return root


def _is_under(path: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _sqlite_path(url: str) -> pathlib.Path | None:
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        return None
    database = parsed.database
    if database in (None, ":memory:"):
        return None
    if parsed.query:
        raise AssertionError("SQLite test URLs must not contain query parameters")
    return pathlib.Path(unquote(database)).resolve()


def validate_sqlite_path(path: str | bytes | os.PathLike) -> pathlib.Path:
    """Validate a raw SQLite path (str, bytes or PathLike, not a URL). Rejects official DB and non-disposable targets."""
    raw = os.fspath(path)
    if isinstance(raw, bytes):
        try:
            raw = os.fsdecode(raw)
        except Exception:
            raise AssertionError("SQLite target is not disposable")
    resolved = pathlib.Path(raw).resolve()
    assert resolved not in {OFFICIAL_DB, BACKEND_OFFICIAL_DB}, "official SQLite database is forbidden"
    assert not _is_under(resolved, ROOT / "storage"), "repository storage is forbidden"
    assert not _is_under(resolved, ROOT / "backend" / "storage"), "backend storage is forbidden"
    assert any(_is_under(resolved, root) for root in _TEMP_ROOTS), "SQLite target is not disposable"
    return resolved


def validate_pg_target(url: str) -> str:
    """Validate a PostgreSQL URL against the explicit manifest. No heuristics."""
    parsed = make_url(url)
    assert parsed.host == PG_MANIFEST["host"], (
        f"PG host diverge: {parsed.host} != {PG_MANIFEST['host']}"
    )
    assert parsed.port == PG_MANIFEST["port"], (
        f"PG port diverge: {parsed.port} != {PG_MANIFEST['port']}"
    )
    assert parsed.database == PG_MANIFEST["database"], (
        f"PG database diverge: {parsed.database} != {PG_MANIFEST['database']}"
    )
    assert parsed.username == PG_MANIFEST["user"], (
        f"PG user diverge: {parsed.username} != {PG_MANIFEST['user']}"
    )
    assert PG_MANIFEST["disposable"] is True, "PG manifest does not indicate disposable"
    return url


def validate_target(url: str, *, allow_memory: bool = True) -> str:
    """Validate a test target before any connection or destructive command."""
    parsed = make_url(url)
    backend = parsed.get_backend_name()
    if backend == "sqlite":
        if parsed.database in (None, ":memory:"):
            if allow_memory:
                return url
            raise AssertionError("in-memory SQLite is not allowed for this test")
        path = _sqlite_path(url)
        assert path is not None
        assert path not in {OFFICIAL_DB, BACKEND_OFFICIAL_DB}, "official SQLite database is forbidden"
        assert not _is_under(path, ROOT / "storage"), "repository storage is forbidden"
        assert not _is_under(path, ROOT / "backend" / "storage"), "backend storage is forbidden"
        assert any(_is_under(path, root) for root in _TEMP_ROOTS), "SQLite target is not disposable"
        return url

    if backend == "postgresql":
        return validate_pg_target(url)

    raise AssertionError(f"unsupported test database backend: {backend}")


def run_alembic(url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    validate_target(url)
    environment = os.environ.copy()
    environment["DATABASE_URL"] = url
    environment.pop("APP_DATABASE_URL", None)
    if make_url(url).get_backend_name() == "sqlite":
        environment.pop("FASE3A_TEST_POSTGRES_URL", None)
        environment.pop("FASE2_TEST_POSTGRES_URL", None)
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            str(BACKEND / "alembic.ini"),
            "-x",
            f"database_url={url}",
            *arguments,
        ],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


async def reset_postgres(url: str) -> None:
    """Reset only an already validated disposable PostgreSQL target."""
    validate_pg_target(url)
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    engine = create_async_engine(url.replace("postgresql://", "postgresql+asyncpg://", 1), poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
    finally:
        await engine.dispose()
