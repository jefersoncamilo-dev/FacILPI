"""Banco modelo por sessao de teste (Issue #184).

Cada fixture funcional precisava de um banco descartavel migrado ate uma revisao
e rodava `alembic upgrade` num subprocess para CADA teste. Aqui a migracao real
roda uma vez por processo de teste (e por revisao) num banco modelo, e cada
teste recebe uma copia:

- SQLite: o arquivo `.db` migrado e copiado para o caminho do teste;
- PostgreSQL: o database do teste e recriado com `CREATE DATABASE ... TEMPLATE`.

So serve para banco recem-criado/resetado. Testes que exercitam a propria
migration (upgrade em etapas, downgrade, dados preexistentes) continuam
chamando o Alembic de verdade e nao usam este modulo.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import pathlib
import re
import shutil
import tempfile
import uuid

from sqlalchemy.engine import make_url

from .db_safety import register_temp_root, run_alembic, validate_sqlite_path

_PG_HOSTS = {"127.0.0.1", "localhost"}
_PG_PORTS = {55484, 55485, 55486}
_PG_DATABASE = re.compile(r"^facilpi_[a-z0-9]+_test$")

_modelos_sqlite: dict[str, pathlib.Path] = {}
_modelos_pg: dict[tuple[str, int, str], str] = {}
_raiz: pathlib.Path | None = None


def _worker() -> str:
    return re.sub(r"[^a-z0-9]", "", os.getenv("PYTEST_XDIST_WORKER", "main").lower()) or "main"


def _raiz_modelos() -> pathlib.Path:
    global _raiz
    if _raiz is None:
        _raiz = register_temp_root(
            pathlib.Path(tempfile.gettempdir())
            / "facilpi-pytest"
            / f"modelo-{os.getpid()}-{uuid.uuid4().hex[:8]}"
        )
    return _raiz


def _sqlite_alvo(url: str) -> pathlib.Path:
    database = make_url(url).database
    assert database not in (None, "", ":memory:"), "banco modelo exige SQLite em arquivo"
    return validate_sqlite_path(database)


def _validar_pg(url: str) -> None:
    parsed = make_url(url)
    assert parsed.get_backend_name() == "postgresql"
    assert parsed.host in _PG_HOSTS, f"PG host nao descartavel: {parsed.host}"
    assert parsed.port in _PG_PORTS, f"PG porta nao descartavel: {parsed.port}"
    assert parsed.database and _PG_DATABASE.match(parsed.database), (
        f"PG database nao descartavel: {parsed.database}"
    )
    assert not parsed.query


def _alembic(url: str, revisao: str) -> None:
    resultado = run_alembic(url, "upgrade", revisao)
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr


def _copiar_sqlite(url: str, revisao: str) -> None:
    alvo = _sqlite_alvo(url)
    assert not alvo.exists(), f"banco modelo exige alvo novo: {alvo}"
    modelo = _modelos_sqlite.get(revisao)
    if modelo is None:
        modelo = _raiz_modelos() / f"modelo-{hashlib.sha1(revisao.encode()).hexdigest()[:10]}.db"
        validate_sqlite_path(modelo)
        _alembic(f"sqlite+aiosqlite:///{modelo.as_posix()}", revisao)
        for sufixo in ("-wal", "-shm", "-journal"):
            assert not pathlib.Path(f"{modelo}{sufixo}").exists(), "modelo SQLite com arquivo auxiliar"
        _modelos_sqlite[revisao] = modelo
    shutil.copyfile(modelo, alvo)


async def _executar_manutencao(url: str, *comandos: str) -> None:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    manutencao = make_url(url).set(drivername="postgresql+asyncpg", database="postgres")
    engine = create_async_engine(manutencao, poolclass=NullPool, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            for comando in comandos:
                await connection.execute(text(comando))
    finally:
        await engine.dispose()


def _clonar_pg(url: str, revisao: str) -> None:
    _validar_pg(url)
    parsed = make_url(url)
    chave = (parsed.host, parsed.port, revisao)
    modelo = _modelos_pg.get(chave)
    if modelo is None:
        modelo = (
            f"facilpi_modelo{parsed.port}"
            f"{hashlib.sha1(revisao.encode()).hexdigest()[:10]}{_worker()}_test"
        )
        _validar_pg(parsed.set(database=modelo).render_as_string(hide_password=False))
        asyncio.run(
            _executar_manutencao(
                url,
                f'DROP DATABASE IF EXISTS "{modelo}" WITH (FORCE)',
                f'CREATE DATABASE "{modelo}"',
            )
        )
        _alembic(parsed.set(database=modelo).render_as_string(hide_password=False), revisao)
        _modelos_pg[chave] = modelo
    asyncio.run(
        _executar_manutencao(
            url,
            f'DROP DATABASE IF EXISTS "{parsed.database}" WITH (FORCE)',
            f'CREATE DATABASE "{parsed.database}" TEMPLATE "{modelo}"',
        )
    )


def migrar_de_modelo(url: str, revisao: str = "head") -> None:
    """Deixa o banco descartavel de `url` (novo/resetado) na `revisao`, copiando o modelo."""
    backend = make_url(url).get_backend_name()
    if backend == "sqlite":
        _copiar_sqlite(url, revisao)
    elif backend == "postgresql":
        _clonar_pg(url, revisao)
    else:
        raise AssertionError(f"backend sem banco modelo: {backend}")
