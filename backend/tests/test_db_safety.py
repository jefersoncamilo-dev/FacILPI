from __future__ import annotations

import os
import pathlib
import sqlite3
import tempfile

import pytest

from tests.db_safety import (
    BACKEND_OFFICIAL_DB,
    OFFICIAL_DB,
    PG_MANIFEST,
    _TEMP_ROOTS,
    validate_pg_target,
    validate_sqlite_path,
    validate_target,
)


# ── SQLite allowlist: rejects official paths ──────────────────────────

@pytest.mark.parametrize(
    "url",
    [
        f"sqlite+aiosqlite:///{OFFICIAL_DB.as_posix()}",
        f"sqlite+aiosqlite:///{BACKEND_OFFICIAL_DB.as_posix()}",
        "sqlite+aiosqlite:///../storage/app.db",
    ],
)
def test_validate_target_rejects_official_equivalents(url):
    with pytest.raises(AssertionError):
        validate_target(url)


def test_validate_target_accepts_registered_temp_database(tmp_path):
    from tests.db_safety import register_temp_root
    register_temp_root(tmp_path)
    validate_target(f"sqlite+aiosqlite:///{(tmp_path / 'test.db').resolve().as_posix()}")


@pytest.mark.parametrize(
    "url",
    [
        "sqlite+aiosqlite:///C:/tmp/test.db?mode=ro",
        "sqlite+aiosqlite:///C:/tmp/test.db?cache=shared",
    ],
)
def test_validate_target_rejects_unauthorized_sqlite_queries(url):
    with pytest.raises(AssertionError):
        validate_target(url)


def test_official_paths_are_resolved_not_string_compared():
    assert pathlib.Path(OFFICIAL_DB).resolve() == OFFICIAL_DB
    assert pathlib.Path(BACKEND_OFFICIAL_DB).resolve() == BACKEND_OFFICIAL_DB


# ── SQLite allowlist: rejects unregistered temp paths ─────────────────

def test_validate_sqlite_path_rejects_unregistered_temp():
    import uuid
    sentinel = (
        pathlib.Path(tempfile.gettempdir())
        / f"facilpi-never-registered-{uuid.uuid4().hex}"
        / "unregistered.db"
    )
    with pytest.raises(AssertionError, match="not disposable"):
        validate_sqlite_path(str(sentinel))


def test_validate_sqlite_path_accepts_registered_root(tmp_path):
    from tests.db_safety import register_temp_root
    root = register_temp_root(tmp_path / "my-suite")
    target = root / "test.db"
    validate_sqlite_path(str(target))


def test_validate_sqlite_path_rejects_official_via_string():
    with pytest.raises(AssertionError, match="official"):
        validate_sqlite_path(str(OFFICIAL_DB))


def test_validate_sqlite_path_rejects_official_resolved(tmp_path):
    link = tmp_path / "alias.db"
    link.symlink_to(OFFICIAL_DB)
    with pytest.raises(AssertionError):
        validate_sqlite_path(str(link))


def test_validate_sqlite_path_rejects_dotdot_escape(tmp_path):
    from tests.db_safety import register_temp_root
    root = register_temp_root(tmp_path / "safe-zone")
    escaping = root
    for _ in range(6):
        escaping = escaping / ".."
    escaping = escaping / "dotdot-escape-proof.db"
    assert escaping.resolve() != (root / "dotdot-escape-proof.db").resolve()
    with pytest.raises(AssertionError, match="not disposable"):
        validate_sqlite_path(str(escaping))


def test_validate_sqlite_path_allows_dotdot_within_root(tmp_path):
    from tests.db_safety import register_temp_root
    root = register_temp_root(tmp_path / "safe-zone")
    inside = root / "sub" / ".." / "valid.db"
    assert inside.resolve() == (root / "valid.db").resolve()
    validate_sqlite_path(str(inside))


def test_validate_sqlite_path_accepts_memory_alias():
    result = validate_target("sqlite+aiosqlite:///:memory:", allow_memory=True)
    assert result == "sqlite+aiosqlite:///:memory:"


# ── PostgreSQL manifest ───────────────────────────────────────────────

def test_pg_manifest_fields_present():
    assert "host" in PG_MANIFEST
    assert "port" in PG_MANIFEST
    assert "database" in PG_MANIFEST
    assert "user" in PG_MANIFEST
    assert "runner_id" in PG_MANIFEST
    assert PG_MANIFEST["disposable"] is True


def test_validate_pg_target_rejects_wrong_host():
    url = f"postgresql://postgres@wrong-host:{PG_MANIFEST['port']}/{PG_MANIFEST['database']}"
    with pytest.raises(AssertionError, match="host"):
        validate_pg_target(url)


def test_validate_pg_target_rejects_wrong_port():
    url = f"postgresql://postgres@{PG_MANIFEST['host']}:99999/{PG_MANIFEST['database']}"
    with pytest.raises(AssertionError, match="port"):
        validate_pg_target(url)


def test_validate_pg_target_rejects_wrong_database():
    url = f"postgresql://postgres@{PG_MANIFEST['host']}:{PG_MANIFEST['port']}/production_db"
    with pytest.raises(AssertionError, match="database"):
        validate_pg_target(url)


def test_validate_pg_target_rejects_wrong_user():
    url = f"postgresql://admin@{PG_MANIFEST['host']}:{PG_MANIFEST['port']}/{PG_MANIFEST['database']}"
    with pytest.raises(AssertionError, match="user"):
        validate_pg_target(url)


def test_validate_target_pg_uses_manifest():
    url = f"postgresql://{PG_MANIFEST['user']}@{PG_MANIFEST['host']}:{PG_MANIFEST['port']}/{PG_MANIFEST['database']}"
    result = validate_target(url)
    assert result == url


# ── sqlite3.connect guard (monkeypatch) ───────────────────────────────

def test_guard_rejects_official_connect():
    with pytest.raises(AssertionError, match="official"):
        sqlite3.connect(str(OFFICIAL_DB))


def test_guard_rejects_official_connect_resolved(tmp_path):
    link = tmp_path / "alias.db"
    link.symlink_to(OFFICIAL_DB)
    with pytest.raises(AssertionError):
        sqlite3.connect(str(link))


def test_guard_allows_registered_temp(tmp_path):
    from tests.db_safety import register_temp_root
    root = register_temp_root(tmp_path / "guard-test")
    target = root / "ok.db"
    con = sqlite3.connect(str(target))
    con.close()


def test_guard_allows_memory():
    con = sqlite3.connect(":memory:")
    con.close()


def test_validate_sqlite_path_accepts_pathlike(tmp_path):
    from tests.db_safety import register_temp_root
    root = register_temp_root(tmp_path / "pathlike-suite")
    validate_sqlite_path(root / "test.db")


def test_validate_sqlite_path_rejects_pathlike_official():
    with pytest.raises(AssertionError, match="official"):
        validate_sqlite_path(pathlib.Path(OFFICIAL_DB))


def test_guard_rejects_pathlike_official_connect():
    with pytest.raises(AssertionError, match="official"):
        sqlite3.connect(pathlib.Path(OFFICIAL_DB))


def test_guard_allows_pathlike_registered_temp(tmp_path):
    from tests.db_safety import register_temp_root
    root = register_temp_root(tmp_path / "guard-pathlike")
    con = sqlite3.connect(root / "ok.db")
    con.close()


def test_guard_active_during_collection_import():
    """Prove the guard is installed before test-module import (collection phase).

    Uses a nonexistent sentinel under ROOT/storage: the guard must reject it
    by path policy BEFORE any file open, so the official DB is never touched.
    """
    import subprocess
    import sys

    tests_dir = pathlib.Path(__file__).resolve().parent
    probe = tests_dir / "test_zz_import_proof_tmp.py"
    sentinel = (tests_dir.parent.parent / "storage" / "sentinel-import-proof.db").as_posix()
    probe.write_text(
        "import sqlite3\n"
        f"sqlite3.connect({sentinel!r})\n",
        encoding="utf-8",
    )
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-p", "no:cacheprovider", str(probe)],
            cwd=str(tests_dir.parent),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    finally:
        probe.unlink(missing_ok=True)
    assert result.returncode != 0
    assert "repository storage is forbidden" in (result.stdout + result.stderr)
