"""Collection-time safety boundary for backend database tests."""

from __future__ import annotations

import os
import pathlib
import sqlite3
import tempfile
import uuid

from .db_safety import register_temp_root, validate_sqlite_path, validate_target

_ORIGINAL_CONNECT = sqlite3.connect


def _guarded_connect(database, *args, **kwargs):
    if isinstance(database, (str, os.PathLike)) and os.fspath(database) not in (":memory:", ""):
        validate_sqlite_path(database)
    return _ORIGINAL_CONNECT(database, *args, **kwargs)


def pytest_configure(config):
    run_id = f"{os.getpid()}-{uuid.uuid4().hex[:8]}"
    run_root = register_temp_root(pathlib.Path(tempfile.gettempdir()) / "facilpi-pytest" / run_id)
    config.option.basetemp = str(run_root)
    default_db = run_root / "collection-default.db"
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{default_db.as_posix()}"
    validate_target(os.environ["DATABASE_URL"])
    sqlite3.connect = _guarded_connect


def pytest_unconfigure(config):
    sqlite3.connect = _ORIGINAL_CONNECT
