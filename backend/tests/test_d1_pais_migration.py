"""D.1 migration gates. Only pytest tmp_path disposable databases."""

import asyncio
import os
import pathlib
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

REV_012 = "012_c5_medicacao"
REV_013 = "013_d1_pais"
BACKEND = pathlib.Path(__file__).resolve().parents[1]
KEYS = {
    "planos_cuidados:ler", "planos_cuidados:criar", "planos_cuidados:atualizar",
    "planos_cuidados:revisar", "planos_cuidados:aprovar", "planos_cuidados:encerrar",
}


def _url(ref):
    if isinstance(ref, pathlib.Path):
        resolved = ref.resolve()
        assert resolved.name.startswith("d1-") and resolved.suffix == ".db"
        assert not resolved.is_relative_to(BACKEND.parent / "storage")
        return f"sqlite+aiosqlite:///{resolved.as_posix()}"
    url = make_url(ref)
    assert url.get_backend_name() == "postgresql"
    assert url.host in {"localhost", "127.0.0.1"}
    assert url.port == 55485 and url.database == "facilpi_d1_test"
    assert not set(url.query) & {"host", "port", "database", "dbname", "service"}
    return url.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)


def _migrate(ref, command="upgrade", target=REV_013, success=True):
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


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D1_TEST_POSTGRES_URL") else []))
def d1_migration_db(request, tmp_path):
    if request.param == "sqlite":
        return tmp_path / "d1-migration.db"
    ref = _url(os.environ["D1_TEST_POSTGRES_URL"])

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
    ):
        counts.append((await connection.execute(text(sql))).scalar_one())
    return {
        "revision": (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalar_one(),
        "counts": tuple(counts), "tables": tables,
    }


def test_01_baseline_012_counts(d1_migration_db):
    _migrate(d1_migration_db, target=REV_012)
    assert asyncio.run(_connection(d1_migration_db, _state))["counts"] == (69, 55, 15)


def test_02_upgrade_013_counts_grants(d1_migration_db):
    _migrate(d1_migration_db, target=REV_012)
    _migrate(d1_migration_db, target=REV_013)
    after = asyncio.run(_connection(d1_migration_db, _state))
    assert after["revision"] == REV_013
    assert after["counts"] == (75, 61, 15)
    assert {"pais_necessidades", "pais_metas", "pais_intervencoes"} <= after["tables"]

    async def keys(connection):
        return {row[0] for row in (await connection.execute(
            text("SELECT chave FROM permissoes WHERE modulo='planos_cuidados'"))).all()}

    assert asyncio.run(_connection(d1_migration_db, keys)) == KEYS


async def _seed_legacy_plano(connection, *, situacao="Rascunho", ilpi_null=True, orphan=False, versao_null=True):
    tenant, other, resident = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    for identifier in (tenant, other):
        await connection.execute(text(
            "INSERT INTO instituicoes (id, razao_social, situacao) VALUES (:id, 'ILPI D1', 'ILPI_RASCUNHO')"), {"id": identifier})
    await connection.execute(text(
        "INSERT INTO residentes (id, instituicao_id, nome, data_nascimento) "
        "VALUES (:id, :tenant, 'Residente legado', '1940-05-01')"),
        {"id": resident, "tenant": None if orphan else tenant})
    plano = str(uuid.uuid4())
    await connection.execute(text(
        "INSERT INTO planos_cuidados (id, residente_id, ilpi_id, versao, data_inicial, situacao, responsaveis, revisor) "
        "VALUES (:id, :res, :ilpi, :versao, '2026-01-01', :sit, 'texto legado', 'nome livre legado')"),
        {"id": plano, "res": resident, "ilpi": None if ilpi_null else tenant,
         "versao": None if versao_null else 1, "sit": situacao})
    return {"plano": plano, "tenant": tenant, "other": other, "resident": resident}


def test_03_legado_mapeado_para_rascunho(d1_migration_db):
    _migrate(d1_migration_db, target=REV_012)

    async def seed(connection):
        return await _seed_legacy_plano(connection)

    ids = asyncio.run(_connection(d1_migration_db, seed))
    _migrate(d1_migration_db, target=REV_013)

    async def check(connection):
        return (await connection.execute(text(
            "SELECT ilpi_id, situacao, versao, lock_version, revisor, autor_id, "
            "revisor_funcionario_id, aprovador_funcionario_id FROM planos_cuidados WHERE id=:id"),
            {"id": ids["plano"]})).mappings().first()

    row = asyncio.run(_connection(d1_migration_db, check))
    assert row["ilpi_id"] == ids["tenant"] and row["situacao"] == "rascunho" and row["versao"] == 1
    assert row["lock_version"] == 0 and row["revisor"] == "nome livre legado"
    assert row["autor_id"] is None and row["revisor_funcionario_id"] is None and row["aprovador_funcionario_id"] is None


def test_04_tenant_ambiguo_recusa(d1_migration_db):
    _migrate(d1_migration_db, target=REV_012)

    async def seed(connection):
        ids = await _seed_legacy_plano(connection, ilpi_null=False)
        # Tenant ambiguo com FK valida: plano aponta outra ILPI existente.
        # Savepoint: no PG a FK composta recusa o DML divergente (camada DB);
        # no SQLite o estado persiste e o preflight da 013 deve recusar.
        try:
            async with connection.begin_nested():
                await connection.execute(text("UPDATE planos_cuidados SET ilpi_id=:other WHERE id=:id"),
                                         {"other": ids["other"], "id": ids["plano"]})
        except Exception:
            return {**ids, "diverged": False}
        return {**ids, "diverged": True}

    ids = asyncio.run(_connection(d1_migration_db, seed))
    if isinstance(d1_migration_db, pathlib.Path):
        assert ids["diverged"] is True
        _migrate(d1_migration_db, target=REV_013, success=False)
    else:
        assert ids["diverged"] is False
        _migrate(d1_migration_db, target=REV_013)


def test_05_downgrade_limpo(d1_migration_db):
    _migrate(d1_migration_db, target=REV_013)
    _migrate(d1_migration_db, command="downgrade", target=REV_012)
    before = asyncio.run(_connection(d1_migration_db, _state))
    assert before["revision"] == REV_012 and before["counts"] == (69, 55, 15)
    _migrate(d1_migration_db, target=REV_013)


def test_06_downgrade_recusa_historico(d1_migration_db):
    _migrate(d1_migration_db, target=REV_013)

    async def seed(connection):
        ids = await _seed_legacy_plano(connection, ilpi_null=False, versao_null=False, situacao="rascunho")
        plano = str(uuid.uuid4())
        await connection.execute(text(
            "INSERT INTO planos_cuidados (id, residente_id, ilpi_id, versao, data_inicial, situacao) "
            "VALUES (:id, :res, :ilpi, 1, '2026-09-01', 'rascunho')"),
            {"id": plano, "res": ids["resident"], "ilpi": ids["tenant"]})
        await connection.execute(text(
            "INSERT INTO pais_necessidades (id, ilpi_id, plano_id, descricao, origem, situacao) "
            "VALUES (:id, :ilpi, :plano, 'N', 'manual', 'ativa')"),
            {"id": str(uuid.uuid4()), "ilpi": ids["tenant"], "plano": plano})

    asyncio.run(_connection(d1_migration_db, seed))
    _migrate(d1_migration_db, command="downgrade", target=REV_012, success=False)
