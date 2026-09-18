"""Collection-time safety boundary for backend database tests."""

from __future__ import annotations

import os
import pathlib
import sqlite3
import tempfile
import uuid

from .db_safety import register_temp_root, validate_sqlite_path, validate_target

_ORIGINAL_CONNECT = sqlite3.connect
_ORIGINAL_DBAPI2_CONNECT = sqlite3.dbapi2.connect


def _guarded_connect(database, *args, **kwargs):
    if isinstance(database, (str, bytes, os.PathLike)):
        raw = os.fspath(database)
        if isinstance(raw, bytes):
            try:
                raw = os.fsdecode(raw)
            except Exception:
                raise AssertionError("SQLite target is not disposable")
        if raw not in (":memory:", ""):
            validate_sqlite_path(raw)
    return _ORIGINAL_CONNECT(database, *args, **kwargs)


def pytest_configure(config):
    # SAFE2-A/B01: `auth.py` resolve JWT_SECRET no import e falha fechado sem ela.
    # A suite precisa de um segredo explicito e controlado — fora do conjunto de
    # valores conhecidos e com pelo menos 32 bytes. `setdefault` preserva um
    # segredo ja definido pelo ambiente.
    os.environ.setdefault(
        "JWT_SECRET", "facilpi-suite-de-testes-segredo-local-nao-operacional"
    )
    run_id = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
    run_root = register_temp_root(pathlib.Path(tempfile.gettempdir()) / "facilpi-pytest" / run_id)
    config.option.basetemp = str(run_root)
    default_db = run_root / "collection-default.db"
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{default_db.as_posix()}"
    validate_target(os.environ["DATABASE_URL"])
    sqlite3.connect = _guarded_connect
    sqlite3.dbapi2.connect = _guarded_connect


def pytest_unconfigure(config):
    sqlite3.connect = _ORIGINAL_CONNECT
    sqlite3.dbapi2.connect = _ORIGINAL_DBAPI2_CONNECT
