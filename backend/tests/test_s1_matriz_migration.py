"""S.1 migration gates. Only pytest tmp_path disposable databases."""

import asyncio
import os
import pathlib
import subprocess
import sys

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

REV_014 = "014_d2_rotina_assistencial"
REV_015 = "015_s1_matriz_permissoes"
BACKEND = pathlib.Path(__file__).resolve().parents[1]
CHAVES = ["cuidador", "enfermagem", "medico", "responsavel_tecnico", "administrativo"]


def _url(ref):
    if isinstance(ref, pathlib.Path):
        resolved = ref.resolve()
        assert resolved.name.startswith("s1-") and resolved.suffix == ".db"
        assert not resolved.is_relative_to(BACKEND.parent / "storage")
        return f"sqlite+aiosqlite:///{resolved.as_posix()}"
    url = make_url(ref)
    assert url.get_backend_name() == "postgresql"
    assert url.host in {"localhost", "127.0.0.1"}
    assert url.port == 55485 and url.database == "facilpi_s1_test"
    assert not set(url.query) & {"host", "port", "database", "dbname", "service"}
    return url.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)


def _migrate(ref, command="upgrade", target=REV_015, success=True):
    url = _url(ref)
    env = os.environ.copy()
    env["DATABASE_URL"] = url
    env.pop("APP_DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"database_url={url}", command, target],
        cwd=BACKEND, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=180,
    )
    assert (result.returncode == 0) == success, result.stdout + result.stderr
    return result


async def _connection(ref, operation):
    engine = create_async_engine(_url(ref), poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            return await operation(connection)
    finally:
        await engine.dispose()


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("S1_TEST_POSTGRES_URL") else []))
def s1_migration_db(request, tmp_path):
    if request.param == "sqlite":
        return tmp_path / "s1-migration.db"
    ref = _url(os.environ["S1_TEST_POSTGRES_URL"])

    async def reset(connection):
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))

    asyncio.run(_connection(ref, reset))
    return ref


async def _state(connection):
    tables = await connection.run_sync(lambda c: set(inspect(c).get_table_names()))
    counts = []
    for sql in (
        "SELECT COUNT(*) FROM permissoes",
        "SELECT COUNT(*) FROM perfil_permissoes pp JOIN perfis p ON p.id=pp.perfil_id "
        "WHERE p.chave='ilpi_admin' AND p.ilpi_id IS NULL",
        "SELECT COUNT(*) FROM perfil_permissoes pp JOIN perfis p ON p.id=pp.perfil_id "
        "WHERE p.chave='platform_superuser' AND p.ilpi_id IS NULL",
        "SELECT COUNT(*) FROM perfis WHERE ilpi_id IS NULL",
    ):
        counts.append((await connection.execute(text(sql))).scalar_one())
    return {
        "revision": (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalar_one(),
        "counts": tuple(counts), "tables": tables,
    }


def test_01_baseline_014(s1_migration_db):
    _migrate(s1_migration_db, target=REV_014)
    assert asyncio.run(_connection(s1_migration_db, _state))["counts"] == (85, 71, 15, 2)


def test_02_upgrade_015_templates(s1_migration_db):
    _migrate(s1_migration_db, target=REV_014)
    _migrate(s1_migration_db, target=REV_015)
    after = asyncio.run(_connection(s1_migration_db, _state))
    assert after["revision"] == REV_015
    # Nenhuma permissão nova; 5 templates; ilpi_admin e platform intactos.
    assert after["counts"] == (85, 71, 15, 7)

    async def templates(connection):
        return {row[0]: row[1] for row in (await connection.execute(text(
            "SELECT chave, COUNT(pp.permissao_id) FROM perfis p LEFT JOIN perfil_permissoes pp "
            "ON pp.perfil_id = p.id WHERE p.ilpi_id IS NULL AND p.chave IN "
            "('cuidador','enfermagem','medico','responsavel_tecnico','administrativo') "
            "GROUP BY chave"))).all()}

    assert asyncio.run(_connection(s1_migration_db, templates)) == {
        "cuidador": 8, "enfermagem": 21, "medico": 14,
        "responsavel_tecnico": 30, "administrativo": 9}


def test_03_downgrade_limpo(s1_migration_db):
    _migrate(s1_migration_db, target=REV_015)
    _migrate(s1_migration_db, command="downgrade", target=REV_014)
    before = asyncio.run(_connection(s1_migration_db, _state))
    assert before["revision"] == REV_014 and before["counts"] == (85, 71, 15, 2)
    _migrate(s1_migration_db, target=REV_015)


def test_04_downgrade_recusa_vinculo(s1_migration_db):
    _migrate(s1_migration_db, target=REV_015)

    async def seed(connection):
        import uuid as _uuid
        tenant, user, template = str(_uuid.uuid4()), str(_uuid.uuid4()), None
        await connection.execute(text(
            "INSERT INTO instituicoes (id, razao_social, situacao) VALUES (:id, 'ILPI S1', 'ILPI_RASCUNHO')"), {"id": tenant})
        await connection.execute(text(
            "INSERT INTO users (id, email, password_hash, nome, ativo) "
            "VALUES (:id, :email, 'fixture', 'U', true)"), {"id": user, "email": f"{user}@example.com"})
        template = (await connection.execute(text(
            "SELECT id FROM perfis WHERE chave='cuidador' AND ilpi_id IS NULL"))).scalar_one()
        clone = str(_uuid.uuid4())
        await connection.execute(text(
            "INSERT INTO perfis (id, ilpi_id, nome, chave, descricao, escopo, situacao) "
            "VALUES (:id, :ilpi, 'Cuidador', 'cuidador', 'd', 'ilpi', 'ativo')"),
            {"id": clone, "ilpi": tenant})
        await connection.execute(text(
            "INSERT INTO usuario_ilpi_perfis (id, usuario_id, ilpi_id, perfil_id, situacao) "
            "VALUES (:id, :user, :ilpi, :perfil, 'ativo')"),
            {"id": str(_uuid.uuid4()), "user": user, "ilpi": tenant, "perfil": clone})

    asyncio.run(_connection(s1_migration_db, seed))
    _migrate(s1_migration_db, command="downgrade", target=REV_014, success=False)
