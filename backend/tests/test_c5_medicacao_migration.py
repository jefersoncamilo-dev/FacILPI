"""C5 migration gates. Only pytest tmp_path or the explicitly fenced local PG."""

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

REV_011 = "011_f5a4a_intercorrencias_rbac"
REV_012 = "012_c5_medicacao"
BACKEND = pathlib.Path(__file__).resolve().parents[1]
KEYS = {
    "medicamentos:ler", "medicamentos:criar", "medicamentos:atualizar",
    "prescricoes:ler", "prescricoes:criar", "prescricoes:atualizar",
    "doses_previstas:ler", "administracoes:ler", "administracoes:criar",
    "administracoes:corrigir",
}


def _url(ref):
    if isinstance(ref, pathlib.Path):
        resolved = ref.resolve()
        assert resolved.name.startswith("c5-") and resolved.suffix == ".db"
        assert not resolved.is_relative_to(BACKEND.parent / "storage")
        return f"sqlite+aiosqlite:///{resolved.as_posix()}"
    url = make_url(ref)
    assert url.get_backend_name() == "postgresql"
    assert url.host in {"localhost", "127.0.0.1"}
    assert url.port == 55485 and url.database == "facilpi_c5_test"
    # Do not allow query parameters to override the validated connection target.
    assert not set(url.query) & {"host", "port", "database", "dbname", "service"}
    return url.set(drivername="postgresql+asyncpg").render_as_string(hide_password=False)


def _migrate(ref, command="upgrade", target=REV_012, success=True):
    url = _url(ref)
    env = os.environ.copy()
    env["DATABASE_URL"] = url
    env.pop("APP_DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"database_url={url}", command, target],
        cwd=BACKEND, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120,
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


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("C5_TEST_POSTGRES_URL") else []))
def c5_migration_db(request, tmp_path):
    if request.param == "sqlite":
        return tmp_path / "c5-migration.db"
    ref = _url(os.environ["C5_TEST_POSTGRES_URL"])

    async def reset(connection):
        await connection.execute(text("DROP SCHEMA public CASCADE"))
        await connection.execute(text("CREATE SCHEMA public"))

    asyncio.run(_connection(ref, reset))
    return ref


async def _state(connection):
    tables = await connection.run_sync(lambda c: set(inspect(c).get_table_names()))
    columns = await connection.run_sync(
        lambda c: {t: tuple(col["name"] for col in inspect(c).get_columns(t))
                   for t in ("medicamentos", "prescricoes")}
    )
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
        "counts": tuple(counts), "tables": tables, "columns": columns,
        "medicamentos": [dict(r) for r in (await connection.execute(text("SELECT * FROM medicamentos ORDER BY id"))).mappings()],
        "prescricoes": [dict(r) for r in (await connection.execute(text("SELECT * FROM prescricoes ORDER BY id"))).mappings()],
        "grants": sorted((await connection.execute(text("SELECT perfil_id, permissao_id FROM perfil_permissoes"))).all()),
    }


async def _seed_legacy(connection, kind="complete"):
    identifiers = [str(uuid.uuid4()) for _ in range(5)]
    tenant, resident, medicine, prescription, other_tenant = identifiers
    for identifier in (tenant, other_tenant):
        await connection.execute(text(
            "INSERT INTO instituicoes (id, razao_social, situacao) VALUES (:id, 'ILPI C5', 'ILPI_RASCUNHO')"
        ), {"id": identifier})
    await connection.execute(text(
        "INSERT INTO residentes (id, instituicao_id, nome, data_nascimento) "
        "VALUES (:id, :tenant, 'Residente legado', '1940-05-01')"
    ), {"id": resident, "tenant": tenant})
    await connection.execute(text(
        "INSERT INTO medicamentos (id, nome, principio_ativo, situacao) "
        "VALUES (:id, 'Medicamento legado', 'Principio original', 'ativo')"
    ), {"id": medicine})
    if kind == "orphan":
        return identifiers
    await connection.execute(text(
        "INSERT INTO prescricoes (id, residente_id, ilpi_id, medicamento_id, prescritor, "
        "dose, via, frequencia, horarios, inicio, situacao) "
        "VALUES (:id, :resident, :tenant, :medicine, 'Dra Legada CRM livre', "
        "'1 comprimido', 'oral', '8/8h', :horarios, '2026-09-08', :state)"
    ), {"id": prescription, "resident": resident, "tenant": tenant, "medicine": medicine,
        "horarios": None if kind == "incomplete" else "08h, 16h, 24h",
        "state": "desconhecida" if kind == "unknown" else "ativa"})
    if kind == "multi_tenant":
        other_resident = str(uuid.uuid4())
        await connection.execute(text(
            "INSERT INTO residentes (id, instituicao_id, nome, data_nascimento) "
            "VALUES (:id, :tenant, 'Outro residente', '1940-05-01')"
        ), {"id": other_resident, "tenant": other_tenant})
        await connection.execute(text(
            "INSERT INTO prescricoes (id, residente_id, ilpi_id, medicamento_id, prescritor, dose, inicio, situacao) "
            "VALUES (:id, :resident, :tenant, :medicine, 'Outro prescritor', '2', '2026-09-08', 'rascunho')"
        ), {"id": str(uuid.uuid4()), "resident": other_resident, "tenant": other_tenant, "medicine": medicine})
    return identifiers


def test_empty_roundtrip_catalog_no_automatic_grants(c5_migration_db):
    ref = c5_migration_db
    _migrate(ref, target=REV_011)
    before = asyncio.run(_connection(ref, _state))
    assert before["counts"] == (59, 55, 15)
    _migrate(ref, target="head")
    after = asyncio.run(_connection(ref, _state))
    assert after["revision"] == REV_012
    assert after["counts"] == (69, 55, 15)
    assert after["grants"] == before["grants"]
    assert {"programacoes_medicacao", "doses_previstas", "administracoes"} <= after["tables"]

    async def catalog(connection):
        keys = set((await connection.execute(text(
            "SELECT chave FROM permissoes WHERE modulo IN "
            "('medicamentos','prescricoes','doses_previstas','administracoes')"
        ))).scalars())
        assert keys == KEYS

    asyncio.run(_connection(ref, catalog))
    _migrate(ref)
    assert asyncio.run(_connection(ref, _state)) == after
    _migrate(ref, "downgrade", REV_011)
    assert asyncio.run(_connection(ref, _state)) == before
    _migrate(ref)
    assert asyncio.run(_connection(ref, _state)) == after


@pytest.mark.parametrize("kind", ["complete", "incomplete"])
def test_legacy_preserved_without_inventing_authors_or_schedules(c5_migration_db, kind):
    ref = c5_migration_db
    _migrate(ref, target=REV_011)
    ids = asyncio.run(_connection(ref, lambda c: _seed_legacy(c, kind)))
    before = asyncio.run(_connection(ref, _state))
    _migrate(ref)
    after = asyncio.run(_connection(ref, _state))
    med, row = after["medicamentos"][0], after["prescricoes"][0]
    assert med["ilpi_id"] == row["ilpi_id"] == ids[0]
    assert med["autor_id"] is None
    for key, value in before["medicamentos"][0].items():
        assert med[key] == value
    for key, value in before["prescricoes"][0].items():
        assert row[key] == ("rascunho" if key == "situacao" and kind == "incomplete" else value)
    for key in ("autor_id", "prescritor_nome", "prescritor_categoria", "prescritor_conselho",
                "prescritor_numero", "prescritor_uf", "medicamento_snapshot", "ativado_em", "ativado_por"):
        assert row[key] is None

    async def empty_clinical(connection):
        for table in ("programacoes_medicacao", "doses_previstas", "administracoes"):
            assert (await connection.execute(text(f"SELECT COUNT(*) FROM {table}"))).scalar_one() == 0

    asyncio.run(_connection(ref, empty_clinical))
    _migrate(ref, "downgrade", REV_011)
    _migrate(ref)
    assert asyncio.run(_connection(ref, _state)) == after


@pytest.mark.parametrize("kind", ["multi_tenant", "orphan", "unknown"])
def test_legacy_preflight_fails_before_any_change(c5_migration_db, kind):
    ref = c5_migration_db
    _migrate(ref, target=REV_011)
    asyncio.run(_connection(ref, lambda c: _seed_legacy(c, kind)))
    before = asyncio.run(_connection(ref, _state))
    result = _migrate(ref, success=False)
    assert "012" in result.stderr
    assert asyncio.run(_connection(ref, _state)) == before


@pytest.mark.parametrize("protected", ["grant", "medication_author", "prescription", "schedule", "dose", "administration"])
def test_downgrade_refuses_new_data_without_partial_changes(c5_migration_db, protected):
    ref = c5_migration_db
    _migrate(ref, target=REV_011)
    tenant, resident, med, presc, _ = asyncio.run(_connection(ref, _seed_legacy))
    _migrate(ref)

    async def seed(connection):
        user, program, dose, admin = [str(uuid.uuid4()) for _ in range(4)]
        await connection.execute(text(
            "INSERT INTO users (id, email, password_hash, nome, ativo) "
            "VALUES (:id, :email, 'fixture', 'Autor C5', true)"
        ), {"id": user, "email": f"{user}@example.com"})
        if protected == "grant":
            await connection.execute(text(
                "INSERT INTO perfil_permissoes (perfil_id, permissao_id) "
                "SELECT p.id, m.id FROM perfis p CROSS JOIN permissoes m "
                "WHERE p.chave='ilpi_admin' AND p.ilpi_id IS NULL AND m.chave='medicamentos:ler'"
            ))
        elif protected == "medication_author":
            await connection.execute(text("UPDATE medicamentos SET autor_id=:user WHERE id=:id"), {"user": user, "id": med})
        elif protected == "prescription":
            await connection.execute(text("UPDATE prescricoes SET autor_id=:user WHERE id=:id"), {"user": user, "id": presc})
        else:
            await connection.execute(text(
                "INSERT INTO programacoes_medicacao "
                "(id, ilpi_id, residente_id, prescricao_id, horarios, timezone, vigencia_inicio, autor_id) "
                "VALUES (:id, :tenant, :resident, :presc, '[\"12:01\"]', 'UTC', '2026-09-08 12:00:00+00:00', :user)"
            ), {"id": program, "tenant": tenant, "resident": resident, "presc": presc, "user": user})
            if protected in {"dose", "administration"}:
                await connection.execute(text(
                    "INSERT INTO doses_previstas (id, ilpi_id, residente_id, prescricao_id, programacao_id, previsto_em) "
                    "VALUES (:id, :tenant, :resident, :presc, :program, '2026-09-08 12:01:00+00:00')"
                ), {"id": dose, "tenant": tenant, "resident": resident, "presc": presc, "program": program})
            if protected == "administration":
                await connection.execute(text(
                    "INSERT INTO administracoes (id, ilpi_id, residente_id, prescricao_id, dose_prevista_id, "
                    "resultado, ocorrido_em, executor_id, quantidade_realizada) "
                    "VALUES (:id, :tenant, :resident, :presc, :dose, 'administrada', '2026-09-08 12:02:00+00:00', :user, 1)"
                ), {"id": admin, "tenant": tenant, "resident": resident, "presc": presc, "dose": dose, "user": user})

    asyncio.run(_connection(ref, seed))
    before = asyncio.run(_connection(ref, _state))
    _migrate(ref, "downgrade", REV_011, success=False)
    assert asyncio.run(_connection(ref, _state)) == before
