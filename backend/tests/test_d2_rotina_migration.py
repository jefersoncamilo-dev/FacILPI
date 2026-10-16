"""D.2 migration gates. Only pytest tmp_path disposable databases."""

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

REV_013 = "013_d1_pais"
REV_014 = "014_d2_rotina_assistencial"
BACKEND = pathlib.Path(__file__).resolve().parents[1]
KEYS = {
    "programacoes:ler", "programacoes:criar", "programacoes:atualizar", "programacoes:inativar",
    "ocorrencias:ler", "ocorrencias:cancelar",
    "execucoes:ler", "execucoes:criar", "execucoes:corrigir",
    "plantao:ler",
}


def _url(ref):
    if isinstance(ref, pathlib.Path):
        resolved = ref.resolve()
        assert resolved.name.startswith("d2-") and resolved.suffix == ".db"
        assert not resolved.is_relative_to(BACKEND.parent / "storage")
        return f"sqlite+aiosqlite:///{resolved.as_posix()}"
    url = make_url(ref)
    assert url.get_backend_name() == "postgresql"
    assert url.host in {"localhost", "127.0.0.1"}
    assert url.port == 55485 and url.database == "facilpi_d2_test"
    assert not set(url.query) & {"host", "port", "database", "dbname", "service"}
    return url.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)


def _migrate(ref, command="upgrade", target=REV_014, success=True):
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


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D2_TEST_POSTGRES_URL") else []))
def d2_migration_db(request, tmp_path):
    if request.param == "sqlite":
        return tmp_path / "d2-migration.db"
    ref = _url(os.environ["D2_TEST_POSTGRES_URL"])

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


def test_01_baseline_013_counts(d2_migration_db):
    _migrate(d2_migration_db, target=REV_013)
    assert asyncio.run(_connection(d2_migration_db, _state))["counts"] == (75, 61, 15)


def test_02_upgrade_014_counts_grants(d2_migration_db):
    _migrate(d2_migration_db, target=REV_013)
    _migrate(d2_migration_db, target=REV_014)
    after = asyncio.run(_connection(d2_migration_db, _state))
    assert after["revision"] == REV_014
    assert after["counts"] == (85, 71, 15)
    assert {"programacoes_cuidado", "ocorrencias_cuidado", "execucoes_cuidado"} <= after["tables"]
    assert "meu_plantao" not in after["tables"]
    assert "passagens_plantao" not in after["tables"]

    async def keys(connection):
        return {row[0] for row in (await connection.execute(
            text("SELECT chave FROM permissoes WHERE modulo IN ('programacoes','ocorrencias','execucoes','plantao')"))).all()}

    assert asyncio.run(_connection(d2_migration_db, keys)) == KEYS


def test_03_tarefa_legada_preservada(d2_migration_db):
    _migrate(d2_migration_db, target=REV_013)

    async def seed(connection):
        tenant, resident = str(uuid.uuid4()), str(uuid.uuid4())
        await connection.execute(text(
            "INSERT INTO instituicoes (id, razao_social, situacao) VALUES (:id, 'ILPI D2', 'ILPI_RASCUNHO')"), {"id": tenant})
        await connection.execute(text(
            "INSERT INTO residentes (id, instituicao_id, nome, data_nascimento) "
            "VALUES (:id, :tenant, 'Residente legado', '1940-05-01')"), {"id": resident, "tenant": tenant})
        tarefa = str(uuid.uuid4())
        await connection.execute(text(
            "INSERT INTO tarefas (id, residente_id, descricao, responsavel, executor, situacao) "
            "VALUES (:id, :res, 'Banho legado', 'texto livre', 'texto livre', 'Pendente')"),
            {"id": tarefa, "res": resident})
        return tarefa

    tarefa_id = asyncio.run(_connection(d2_migration_db, seed))
    _migrate(d2_migration_db, target=REV_014)

    async def check(connection):
        row = (await connection.execute(text("SELECT * FROM tarefas WHERE id=:id"), {"id": tarefa_id})).mappings().first()
        return dict(row)

    row = asyncio.run(_connection(d2_migration_db, check))
    assert row["descricao"] == "Banho legado" and row["executor"] == "texto livre"


def test_04_downgrade_limpo(d2_migration_db):
    _migrate(d2_migration_db, target=REV_014)
    _migrate(d2_migration_db, command="downgrade", target=REV_013)
    before = asyncio.run(_connection(d2_migration_db, _state))
    assert before["revision"] == REV_013 and before["counts"] == (75, 61, 15)
    _migrate(d2_migration_db, target=REV_014)


def test_05_downgrade_recusa_historico(d2_migration_db):
    _migrate(d2_migration_db, target=REV_014)

    async def seed(connection):
        tenant, resident, plano, interv, prog, autor = [str(uuid.uuid4()) for _ in range(6)]
        await connection.execute(text(
            "INSERT INTO instituicoes (id, razao_social, situacao) VALUES (:id, 'ILPI D2', 'ILPI_RASCUNHO')"), {"id": tenant})
        await connection.execute(text(
            "INSERT INTO users (id, email, password_hash, nome, ativo) "
            "VALUES (:id, :email, 'fixture', 'Autor D2', true)"), {"id": autor, "email": f"{autor}@example.com"})
        await connection.execute(text(
            "INSERT INTO residentes (id, instituicao_id, nome, data_nascimento) "
            "VALUES (:id, :tenant, 'Residente D2', '1940-05-01')"), {"id": resident, "tenant": tenant})
        await connection.execute(text(
            "INSERT INTO planos_cuidados (id, residente_id, ilpi_id, versao, data_inicial, situacao) "
            "VALUES (:id, :res, :ilpi, 1, '2026-09-01', 'vigente')"), {"id": plano, "res": resident, "ilpi": tenant})
        await connection.execute(text(
            "INSERT INTO pais_intervencoes (id, ilpi_id, plano_id, descricao, situacao) "
            "VALUES (:id, :ilpi, :plano, 'I', 'ativa')"), {"id": interv, "ilpi": tenant, "plano": plano})
        await connection.execute(text(
            "INSERT INTO programacoes_cuidado (id, ilpi_id, residente_id, plano_id, intervencao_id, autor_id, "
            "horarios, timezone, vigencia_inicio, situacao) "
            "VALUES (:id, :ilpi, :res, :plano, :interv, :autor, '[\"08:00\"]', 'UTC', '2026-09-01 00:00:00+00:00', 'ativa')"),
            {"id": prog, "ilpi": tenant, "res": resident, "plano": plano, "interv": interv, "autor": autor})

    asyncio.run(_connection(d2_migration_db, seed))
    _migrate(d2_migration_db, command="downgrade", target=REV_013, success=False)
