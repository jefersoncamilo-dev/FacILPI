"""D.3 migration gates: only fenced disposable SQLite/PostgreSQL databases."""

import asyncio
import os
import pathlib
import subprocess
import sys
import uuid

import pytest
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

BACKEND = pathlib.Path(__file__).resolve().parents[1]
BEFORE = "015_s1_matriz_permissoes"
HEAD = "016_d3_admissao"
ACTIONS = {"ler", "criar", "atualizar", "avancar", "reabrir", "concluir", "cancelar"}


def _url(ref):
    if isinstance(ref, pathlib.Path):
        resolved = ref.resolve()
        assert resolved.name.startswith("d3-") and resolved.suffix == ".db"
        assert not resolved.is_relative_to(BACKEND.parent)
        assert resolved.parent.is_dir()
        return f"sqlite+aiosqlite:///{resolved.as_posix()}"
    url = make_url(ref)
    assert url.get_backend_name() == "postgresql"
    assert url.host == "127.0.0.1" and url.port == 55486 and url.database == "facilpi_d3_test"
    assert not url.query
    return url.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)


def _migrate(ref, target=HEAD, command="upgrade", success=True):
    url = _url(ref)
    env = os.environ.copy()
    env["DATABASE_URL"] = url
    env.pop("FASE3A_TEST_POSTGRES_URL", None)
    env.pop("APP_DATABASE_URL", None)
    script = ("import sys; from types import SimpleNamespace; from alembic.config import Config; "
              "from alembic import command; c=Config('alembic.ini'); "
              "c.cmd_opts=SimpleNamespace(x=['database_url='+sys.argv[1]]); "
              "getattr(command, sys.argv[2])(c, sys.argv[3])")
    result = subprocess.run([sys.executable, "-B", "-c", script, url, command, target], cwd=BACKEND,
                            env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
    assert (result.returncode == 0) == success, result.stdout + result.stderr
    return result


def _engine(ref):
    engine = create_async_engine(_url(ref), poolclass=NullPool)
    if isinstance(ref, pathlib.Path):
        @event.listens_for(engine.sync_engine, "connect")
        def pragma(connection, record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=10000")
            cursor.close()
    return engine


async def _connection(ref, operation):
    engine = _engine(ref)
    try:
        async with engine.begin() as connection:
            return await operation(connection)
    finally:
        await engine.dispose()


def _ref(request, tmp_path):
    if request.param == "sqlite":
        return tmp_path / "d3-test.db"
    ref = _url(os.environ["D3_TEST_POSTGRES_URL"])
    async def reset(connection):
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))
    asyncio.run(_connection(ref, reset))
    return ref


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D3_TEST_POSTGRES_URL") else []))
def d3_migration_db(request, tmp_path):
    return _ref(request, tmp_path)


async def _baseline(connection):
    return {
        "revision": (await connection.execute(text("SELECT version_num FROM alembic_version"))).scalar_one(),
        "permissions": (await connection.execute(text("SELECT count(*) FROM permissoes"))).scalar_one(),
        "grants": set((await connection.execute(text("SELECT perfil_id, permissao_id FROM perfil_permissoes"))).all()),
        "profiles": set((await connection.execute(text("SELECT id, chave, ilpi_id FROM perfis"))).all()),
    }


async def _seed(connection, process=False):
    ids = {k: str(uuid.uuid4()) for k in ("tenant", "other", "resident", "user", "func", "doc", "admission", "history")}
    for tenant in ("tenant", "other"):
        await connection.execute(text("INSERT INTO instituicoes (id, razao_social) VALUES (:id, 'D3')"), {"id": ids[tenant]})
    await connection.execute(text("INSERT INTO users (id, nome, email, password_hash, ativo) VALUES (:id, 'D3', :email, 'fixture', true)"),
                             {"id": ids["user"], "email": ids["user"] + "@example.com"})
    await connection.execute(text("INSERT INTO residentes (id, instituicao_id, nome, data_nascimento, situacao) VALUES (:resident, :tenant, 'Legado D3', '1940-01-01', 'Ativo')"), ids)
    await connection.execute(text("INSERT INTO funcionarios (id, ilpi_id, nome, situacao) VALUES (:func, :other, 'Other', 'ativo')"), ids)
    await connection.execute(text("INSERT INTO documentos (id, instituicao_id, residente_id, tipo, obrigatorio, situacao) VALUES (:doc, :tenant, :resident, 'Legado', true, 'situacao legada')"), ids)
    if process:
        await connection.execute(text("INSERT INTO admissoes (id, ilpi_id, residente_id, autor_id, situacao, iniciada_em, updated_at, avaliacoes_requeridas) VALUES (:admission, :tenant, :resident, :user, 'pre_cadastro', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, '[]')"), ids)
        await connection.execute(text("INSERT INTO admissao_historico (id, ilpi_id, admissao_id, etapa_destino, acao, autor_id, lock_version) VALUES (:history, :tenant, :admission, 'pre_cadastro', 'criar', :user, 0)"), ids)
    return ids


def test_upgrade_baseline_preserva_legado_e_grants(d3_migration_db):
    _migrate(d3_migration_db, BEFORE)
    before = asyncio.run(_connection(d3_migration_db, _baseline))
    assert before["permissions"] == 85 and len(before["grants"]) == 168 and len(before["profiles"]) == 7
    ids = asyncio.run(_connection(d3_migration_db, _seed))
    _migrate(d3_migration_db)
    after = asyncio.run(_connection(d3_migration_db, _baseline))
    assert after["revision"] == HEAD and after["permissions"] == 92
    assert after["grants"] == before["grants"] and after["profiles"] == before["profiles"]
    async def verify(connection):
        assert (await connection.execute(text("SELECT situacao FROM residentes WHERE id=:resident"), ids)).scalar_one() == "Ativo"
        assert (await connection.execute(text("SELECT situacao FROM documentos WHERE id=:doc"), ids)).scalar_one() == "situacao legada"
        assert (await connection.execute(text("SELECT count(*) FROM admissoes"))).scalar_one() == 0
        keys = set((await connection.execute(text("SELECT chave FROM permissoes WHERE modulo='admissoes'"))).scalars())
        assert keys == {f"admissoes:{action}" for action in ACTIONS}
        inspector = await connection.run_sync(lambda c: inspect(c).get_foreign_keys("admissoes"))
        assert {"fk_admissoes_residente", "fk_admissoes_responsavel", "fk_admissoes_contrato"} <= {fk["name"] for fk in inspector}
    asyncio.run(_connection(d3_migration_db, verify))


def test_downgrade_vazio_e_reupgrade(d3_migration_db):
    _migrate(d3_migration_db)
    _migrate(d3_migration_db, BEFORE, "downgrade")
    after = asyncio.run(_connection(d3_migration_db, _baseline))
    assert after["revision"] == BEFORE and after["permissions"] == 85
    _migrate(d3_migration_db)


def test_downgrade_recusa_historico(d3_migration_db):
    _migrate(d3_migration_db)
    async def seed(connection):
        return await _seed(connection, process=True)
    asyncio.run(_connection(d3_migration_db, seed))
    result = _migrate(d3_migration_db, BEFORE, "downgrade", success=False)
    assert "016 recusa downgrade" in result.stderr
    assert asyncio.run(_connection(d3_migration_db, _baseline))["revision"] == HEAD


def test_downgrade_recusa_grants(d3_migration_db):
    _migrate(d3_migration_db)
    async def grant(connection):
        await connection.execute(text("INSERT INTO perfil_permissoes (perfil_id, permissao_id) SELECT p.id, m.id FROM perfis p, permissoes m WHERE p.chave='administrativo' AND m.chave='admissoes:ler'"))
    asyncio.run(_connection(d3_migration_db, grant))
    assert "grants de admissoes" in _migrate(d3_migration_db, BEFORE, "downgrade", success=False).stderr


def test_constraints_same_tenant_e_append_only(d3_migration_db):
    _migrate(d3_migration_db)
    async def verify(connection):
        ids = await _seed(connection, process=True)
        mutations = [
            "UPDATE admissoes SET responsavel_funcionario_id=:func WHERE id=:admission",
            "UPDATE admissoes SET ilpi_id=:other WHERE id=:admission",
            "UPDATE admissoes SET situacao='inventada' WHERE id=:admission",
            "UPDATE admissoes SET situacao='concluida' WHERE id=:admission",
            "UPDATE admissoes SET situacao='cancelada' WHERE id=:admission",
            "UPDATE admissoes SET lock_version=-1 WHERE id=:admission",
            "UPDATE admissao_historico SET motivo='alterado' WHERE id=:history",
            "DELETE FROM admissao_historico WHERE id=:history",
            "DELETE FROM admissoes WHERE id=:admission",
        ]
        if connection.dialect.name == "sqlite":
            mutations.append("INSERT OR REPLACE INTO admissao_historico (id, ilpi_id, admissao_id, etapa_destino, acao, autor_id, lock_version) VALUES (:history, :tenant, :admission, 'concluida', 'inventado', :user, 0)")
        else:
            mutations.append("TRUNCATE admissao_historico")
        for sql in mutations:
            with pytest.raises(DBAPIError):
                async with connection.begin_nested():
                    await connection.execute(text(sql), ids)
        assert (await connection.execute(text("SELECT count(*) FROM admissao_historico"))).scalar_one() == 1
    asyncio.run(_connection(d3_migration_db, verify))
