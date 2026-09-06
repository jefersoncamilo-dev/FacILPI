"""Permanent tests for the deterministic Phase 2A RBAC catalog."""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import os
import pathlib
import sqlite3
import subprocess
import sys

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
OFFICIAL_DB = ROOT / "storage" / "app.db"
MIGRATION = BACKEND / "alembic" / "versions" / "004_catalogo_permissoes_rbac.py"

PERMISSION_COLUMNS = ("id", "modulo", "acao", "chave", "descricao")
PROFILE_COLUMNS = ("id", "ilpi_id", "nome", "chave", "descricao", "escopo", "situacao")
EXPECTED_PERMISSION_IDS = tuple(
    f"fac11000-0000-4000-8000-{number:012d}" for number in range(1, 27)
)

EXPECTED_PERMISSIONS = (
    (EXPECTED_PERMISSION_IDS[0], "ilpis", "ler", "ilpis:ler", "Consultar ILPIs conforme o contexto; contexto institucional enxerga somente a pr\u00f3pria ILPI.", "global/ilpi"),
    (EXPECTED_PERMISSION_IDS[1], "ilpis", "criar", "ilpis:criar", "Criar uma ILPI inicialmente em situa\u00e7\u00e3o de rascunho.", "global"),
    (EXPECTED_PERMISSION_IDS[2], "ilpis", "atualizar", "ilpis:atualizar", "Atualizar dados cadastrais permitidos sem alterar diretamente a situa\u00e7\u00e3o.", "global/ilpi"),
    (EXPECTED_PERMISSION_IDS[3], "ilpis", "ativar", "ilpis:ativar", "Ativar ILPI ap\u00f3s todas as valida\u00e7\u00f5es obrigat\u00f3rias.", "global"),
    (EXPECTED_PERMISSION_IDS[4], "ilpis", "suspender", "ilpis:suspender", "Suspender uma ILPI sem excluir seus registros.", "global"),
    (EXPECTED_PERMISSION_IDS[5], "ilpis", "inativar", "ilpis:inativar", "Inativar logicamente uma ILPI, preservando hist\u00f3rico e auditoria.", "global"),
    (EXPECTED_PERMISSION_IDS[6], "usuarios", "ler", "usuarios:ler", "Consultar usu\u00e1rios dentro do contexto autorizado.", "global/ilpi"),
    (EXPECTED_PERMISSION_IDS[7], "usuarios", "criar", "usuarios:criar", "Criar usu\u00e1rio no contexto atual, sem cadastro p\u00fablico.", "global/ilpi"),
    (EXPECTED_PERMISSION_IDS[8], "usuarios", "atualizar", "usuarios:atualizar", "Atualizar dados permitidos de um usu\u00e1rio do contexto atual.", "global/ilpi"),
    (EXPECTED_PERMISSION_IDS[9], "usuarios", "inativar", "usuarios:inativar", "Inativar usu\u00e1rio e futuramente revogar suas sess\u00f5es.", "global/ilpi"),
    (EXPECTED_PERMISSION_IDS[10], "usuarios", "redefinir_senha", "usuarios:redefinir_senha", "Realizar redefini\u00e7\u00e3o administrativa e auditada de senha.", "global/ilpi"),
    (EXPECTED_PERMISSION_IDS[11], "usuarios", "atribuir_perfil", "usuarios:atribuir_perfil", "Atribuir ou remover perfil compat\u00edvel com o mesmo escopo.", "global/ilpi"),
    (EXPECTED_PERMISSION_IDS[12], "funcionarios", "ler", "funcionarios:ler", "Consultar funcion\u00e1rios da ILPI atual.", "ilpi"),
    (EXPECTED_PERMISSION_IDS[13], "funcionarios", "criar", "funcionarios:criar", "Cadastrar funcion\u00e1rio na ILPI atual.", "ilpi"),
    (EXPECTED_PERMISSION_IDS[14], "funcionarios", "atualizar", "funcionarios:atualizar", "Atualizar dados funcionais permitidos.", "ilpi"),
    (EXPECTED_PERMISSION_IDS[15], "funcionarios", "inativar", "funcionarios:inativar", "Inativar funcion\u00e1rio preservando o hist\u00f3rico.", "ilpi"),
    (EXPECTED_PERMISSION_IDS[16], "funcionarios", "vincular_usuario", "funcionarios:vincular_usuario", "Vincular ou desvincular funcion\u00e1rio e usu\u00e1rio no mesmo tenant.", "ilpi"),
    (EXPECTED_PERMISSION_IDS[17], "perfis", "ler", "perfis:ler", "Consultar perfis dispon\u00edveis no contexto.", "global/ilpi"),
    (EXPECTED_PERMISSION_IDS[18], "perfis", "criar", "perfis:criar", "Criar perfil institucional personalizado.", "ilpi"),
    (EXPECTED_PERMISSION_IDS[19], "perfis", "atualizar", "perfis:atualizar", "Atualizar somente perfis institucionais n\u00e3o protegidos.", "ilpi"),
    (EXPECTED_PERMISSION_IDS[20], "perfis", "inativar", "perfis:inativar", "Inativar perfil institucional n\u00e3o protegido.", "ilpi"),
    (EXPECTED_PERMISSION_IDS[21], "perfis", "atribuir_permissao", "perfis:atribuir_permissao", "Atribuir ou remover permiss\u00f5es permitidas de perfil institucional.", "ilpi"),
    (EXPECTED_PERMISSION_IDS[22], "permissoes", "ler", "permissoes:ler", "Consultar o cat\u00e1logo de permiss\u00f5es mantido por release.", "global/ilpi"),
    (EXPECTED_PERMISSION_IDS[23], "configuracoes", "ler", "configuracoes:ler", "Consultar configura\u00e7\u00f5es institucionais permitidas.", "ilpi"),
    (EXPECTED_PERMISSION_IDS[24], "configuracoes", "atualizar", "configuracoes:atualizar", "Atualizar configura\u00e7\u00f5es institucionais permitidas e auditadas; n\u00e3o altera cat\u00e1logo regulat\u00f3rio do sistema.", "ilpi"),
    (EXPECTED_PERMISSION_IDS[25], "auditoria", "ler", "auditoria:ler", "Consultar auditoria conforme o escopo, com prote\u00e7\u00e3o de segredos e dados cl\u00ednicos sens\u00edveis.", "global/ilpi"),
)

EXPECTED_PROFILE_IDS = (
    "fac10000-0000-4000-8000-000000000001",
    "fac10000-0000-4000-8000-000000000002",
)
EXPECTED_PROFILES = (
    (EXPECTED_PROFILE_IDS[0], None, "Superusu\u00e1rio da Plataforma", "platform_superuser", "Perfil global gerenciado pelo sistema, sem permiss\u00f5es cl\u00ednicas.", "global", "ativo"),
    (EXPECTED_PROFILE_IDS[1], None, "Administrador da ILPI", "ilpi_admin", "Template institucional gerenciado pelo sistema; requer v\u00ednculo com uma ILPI.", "ilpi", "ativo"),
)

EXPECTED_PROFILE_PERMISSION_KEYS = {
    "platform_superuser": {
        "ilpis:ler",
        "ilpis:criar",
        "ilpis:atualizar",
        "ilpis:ativar",
        "ilpis:suspender",
        "ilpis:inativar",
        "usuarios:ler",
        "usuarios:criar",
        "usuarios:atualizar",
        "usuarios:inativar",
        "usuarios:redefinir_senha",
        "usuarios:atribuir_perfil",
        "perfis:ler",
        "permissoes:ler",
        "auditoria:ler",
    },
    "ilpi_admin": {
        "ilpis:ler",
        "ilpis:atualizar",
        "usuarios:ler",
        "usuarios:criar",
        "usuarios:atualizar",
        "usuarios:inativar",
        "usuarios:redefinir_senha",
        "usuarios:atribuir_perfil",
        "funcionarios:ler",
        "funcionarios:criar",
        "funcionarios:atualizar",
        "funcionarios:inativar",
        "funcionarios:vincular_usuario",
        "perfis:ler",
        "perfis:criar",
        "perfis:atualizar",
        "perfis:inativar",
        "perfis:atribuir_permissao",
        "permissoes:ler",
        "configuracoes:ler",
        "configuracoes:atualizar",
        "auditoria:ler",
    },
}

CLINICAL_MODULES = {
    "residentes",
    "familiares",
    "documentos",
    "quartos_leitos",
    "admissoes",
    "avaliacoes",
    "planos_cuidados",
    "tarefas",
    "cuidados_diarios",
    "medicamentos",
    "prescricoes",
    "sinais_vitais",
    "intercorrencias",
    "agenda",
    "passagem_plantao",
    "alertas",
    "estoque",
    "financeiro",
    "portal_familia",
    "relatorios",
    "supervisao",
    "compliance",
    "uploads",
}

FORBIDDEN_KEYS = {
    "plataforma:administrar",
    "bootstrap:administrar",
    "permissoes:administrar",
}


def _sqlite_url(path: pathlib.Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def _async_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def _assert_disposable_url(url: str) -> None:
    if "sqlite" in url:
        path = pathlib.Path(url.split("///", 1)[1].split("?", 1)[0]).resolve()
        assert path != OFFICIAL_DB.resolve(), "test must never write the official database"


def _run_alembic(url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    _assert_disposable_url(url)
    environment = os.environ.copy()
    environment["DATABASE_URL"] = url
    environment.pop("APP_DATABASE_URL", None)
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"database_url={url}", *arguments],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


async def _reset_postgres(url: str) -> None:
    engine = create_async_engine(_async_url(url), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
            await connection.commit()
    finally:
        await engine.dispose()


async def _snapshot(url: str) -> dict:
    engine = create_async_engine(_async_url(url), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            version = (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one()
            permission_rows = (
                await connection.execute(
                    text(
                        "SELECT id, modulo, acao, chave, descricao "
                        "FROM permissoes ORDER BY id"
                    )
                )
            ).mappings().all()
            profile_rows = (
                await connection.execute(
                    text(
                        "SELECT id, ilpi_id, nome, chave, descricao, escopo, situacao "
                        "FROM perfis ORDER BY id"
                    )
                )
            ).mappings().all()
            links = (
                await connection.execute(
                    text(
                        "SELECT perfil_id, permissao_id FROM perfil_permissoes "
                        "ORDER BY perfil_id, permissao_id"
                    )
                )
            ).all()
            counts = {}
            for table in (
                "users",
                "instituicoes",
                "funcionarios",
                "usuario_ilpi_perfis",
            ):
                counts[table] = (
                    await connection.execute(text(f"SELECT COUNT(*) FROM {table}"))
                ).scalar_one()
            if "sqlite" in url:
                template_index = (
                    await connection.execute(
                        text(
                            "SELECT COUNT(*) FROM sqlite_master "
                            "WHERE type='index' AND name='uq_perfis_chave_template_ilpi_null'"
                        )
                    )
                ).scalar_one()
            else:
                template_index = (
                    await connection.execute(
                        text(
                            "SELECT COUNT(*) FROM pg_indexes "
                            "WHERE schemaname = current_schema() AND tablename = 'perfis' "
                            "AND indexname = 'uq_perfis_chave_template_ilpi_null'"
                        )
                    )
                ).scalar_one()
            return {
                "version": str(version),
                "permissions": tuple(
                    tuple(row[column] for column in PERMISSION_COLUMNS)
                    for row in permission_rows
                ),
                "profiles": tuple(
                    tuple(row[column] for column in PROFILE_COLUMNS)
                    for row in profile_rows
                ),
                "links": tuple(tuple(row) for row in links),
                "counts": counts,
                "template_index": int(template_index),
            }
    finally:
        await engine.dispose()


def _get_snapshot(url: str) -> dict:
    return asyncio.run(_snapshot(url))


def _catalog_projection(snapshot: dict) -> tuple:
    permission_ids = set(EXPECTED_PERMISSION_IDS)
    profile_ids = set(EXPECTED_PROFILE_IDS)
    return (
        tuple(row for row in snapshot["permissions"] if row[0] in permission_ids),
        tuple(row for row in snapshot["profiles"] if row[0] in profile_ids),
        tuple(
            link
            for link in snapshot["links"]
            if link[0] in profile_ids and link[1] in permission_ids
        ),
    )


def _data_projection(snapshot: dict) -> tuple:
    return (
        snapshot["permissions"],
        snapshot["profiles"],
        snapshot["links"],
        tuple(sorted(snapshot["counts"].items())),
    )


def _assert_catalog(snapshot: dict) -> None:
    assert snapshot["version"] == "004_catalogo_permissoes_rbac"
    assert len(snapshot["permissions"]) == 26
    assert len(snapshot["profiles"]) == 2
    assert len(snapshot["links"]) == 37
    assert snapshot["template_index"] == 1

    expected_permission_rows = tuple(
        (permission_id, module, action, key, description)
        for permission_id, module, action, key, description, _scope in EXPECTED_PERMISSIONS
    )
    assert snapshot["permissions"] == expected_permission_rows

    expected_profile_rows = EXPECTED_PROFILES
    assert snapshot["profiles"] == expected_profile_rows

    permission_keys = {row[3]: row[0] for row in snapshot["permissions"]}
    profile_keys = {row[3]: row[0] for row in snapshot["profiles"]}
    links_by_profile = {
        profile_key: {
            next(key for key, permission_id in permission_keys.items() if permission_id == permission_id_value)
            for profile_id, permission_id_value in snapshot["links"]
            if profile_id == profile_keys[profile_key]
        }
        for profile_key in EXPECTED_PROFILE_PERMISSION_KEYS
    }
    assert links_by_profile == EXPECTED_PROFILE_PERMISSION_KEYS
    assert len(links_by_profile["platform_superuser"]) == 15
    assert len(links_by_profile["ilpi_admin"]) == 22

    assert all(module not in CLINICAL_MODULES for _id, module, *_rest in snapshot["permissions"])
    keys = {row[3] for row in snapshot["permissions"]}
    assert all("*" not in key and not key.endswith(":administrar") for key in keys)
    assert keys.isdisjoint(FORBIDDEN_KEYS)

    assert snapshot["counts"] == {
        "users": 0,
        "instituicoes": 0,
        "funcionarios": 0,
        "usuario_ilpi_perfis": 0,
    }


async def _insert_duplicate_template(url: str) -> None:
    engine = create_async_engine(_async_url(url), poolclass=NullPool)
    try:
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(
                        "INSERT INTO perfis "
                        "(id, ilpi_id, nome, chave, descricao, escopo, situacao) "
                        "VALUES (:id, NULL, :nome, :chave, :descricao, :escopo, :situacao)"
                    ),
                    {
                        "id": "fac10000-0000-4000-8000-999999999999",
                        "nome": "Duplicate template",
                        "chave": "ilpi_admin",
                        "descricao": "fixture",
                        "escopo": "ilpi",
                        "situacao": "ativo",
                    },
                )
        except IntegrityError:
            return
        raise AssertionError("duplicate NULL template key was accepted")
    finally:
        await engine.dispose()


async def _insert_custom_records(url: str) -> None:
    engine = create_async_engine(_async_url(url), poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "INSERT INTO permissoes (id, modulo, acao, chave, descricao) "
                    "VALUES (:id, :modulo, :acao, :chave, :descricao)"
                ),
                {
                    "id": "fac12000-0000-4000-8000-000000000001",
                    "modulo": "custom",
                    "acao": "ler",
                    "chave": "custom:ler",
                    "descricao": "Custom permission fixture",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO perfis "
                    "(id, ilpi_id, nome, chave, descricao, escopo, situacao) "
                    "VALUES (:id, NULL, :nome, :chave, :descricao, :escopo, :situacao)"
                ),
                {
                    "id": "fac13000-0000-4000-8000-000000000001",
                    "nome": "Custom profile",
                    "chave": "custom_profile",
                    "descricao": "Custom profile fixture",
                    "escopo": "global",
                    "situacao": "ativo",
                },
            )
            await connection.execute(
                text(
                    "INSERT INTO perfil_permissoes (perfil_id, permissao_id) "
                    "VALUES (:perfil_id, :permissao_id)"
                ),
                {
                    "perfil_id": "fac13000-0000-4000-8000-000000000001",
                    "permissao_id": "fac12000-0000-4000-8000-000000000001",
                },
            )
    finally:
        await engine.dispose()


def _assert_custom_records(snapshot: dict) -> None:
    assert (
        "fac12000-0000-4000-8000-000000000001",
        "custom",
        "ler",
        "custom:ler",
        "Custom permission fixture",
    ) in snapshot["permissions"]
    assert (
        "fac13000-0000-4000-8000-000000000001",
        None,
        "Custom profile",
        "custom_profile",
        "Custom profile fixture",
        "global",
        "ativo",
    ) in snapshot["profiles"]
    assert (
        "fac13000-0000-4000-8000-000000000001",
        "fac12000-0000-4000-8000-000000000001",
    ) in snapshot["links"]


async def _mutate_permission(url: str, mode: str) -> None:
    engine = create_async_engine(_async_url(url), poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            if mode == "id":
                await connection.execute(
                    text("DELETE FROM perfil_permissoes WHERE permissao_id = :expected"),
                    {"expected": EXPECTED_PERMISSION_IDS[0]},
                )
                await connection.execute(
                    text("UPDATE permissoes SET id = :replacement WHERE id = :expected"),
                    {
                        "replacement": "fac11000-0000-4000-8000-999999999999",
                        "expected": EXPECTED_PERMISSION_IDS[0],
                    },
                )
            else:
                await connection.execute(
                    text("UPDATE permissoes SET chave = :key WHERE id = :expected"),
                    {
                        "key": "adulterated:key",
                        "expected": EXPECTED_PERMISSION_IDS[0],
                    },
                )
    finally:
        await engine.dispose()


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def _assert_official_readable_only() -> None:
    connection = sqlite3.connect(
        f"file:{OFFICIAL_DB.resolve().as_posix()}?mode=ro", uri=True
    )
    try:
        assert connection.execute("SELECT 1").fetchone()[0] == 1
    finally:
        connection.close()


def _load_migration():
    spec = importlib.util.spec_from_file_location("phase2_catalog_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _assert_success(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stdout + result.stderr


def _run_catalog_scenario(url: str) -> None:
    upgrade = _run_alembic(url, "upgrade", "004_catalogo_permissoes_rbac")
    _assert_success(upgrade)
    initial = _get_snapshot(url)
    _assert_catalog(initial)

    asyncio.run(_insert_duplicate_template(url))

    _assert_success(_run_alembic(url, "stamp", "003_correcoes_fase1"))
    _assert_success(_run_alembic(url, "upgrade", "004_catalogo_permissoes_rbac"))
    rerun = _get_snapshot(url)
    assert rerun == initial

    asyncio.run(_insert_custom_records(url))
    before_downgrade = _get_snapshot(url)
    _assert_custom_records(before_downgrade)
    catalog_before_downgrade = _catalog_projection(before_downgrade)

    _assert_success(_run_alembic(url, "downgrade", "003_correcoes_fase1"))
    downgraded = _get_snapshot(url)
    assert downgraded["version"] == "003_correcoes_fase1"
    assert _catalog_projection(downgraded) == ((), (), ())
    assert downgraded["template_index"] == 0
    _assert_custom_records(downgraded)
    assert downgraded["counts"] == before_downgrade["counts"]

    _assert_success(_run_alembic(url, "upgrade", "004_catalogo_permissoes_rbac"))
    restored = _get_snapshot(url)
    _assert_custom_records(restored)
    assert _catalog_projection(restored) == catalog_before_downgrade
    assert _data_projection(restored) == _data_projection(before_downgrade)
    _assert_catalog(
        {
            **restored,
            "permissions": tuple(
                row for row in restored["permissions"] if row[0] in set(EXPECTED_PERMISSION_IDS)
            ),
            "profiles": tuple(
                row for row in restored["profiles"] if row[0] in set(EXPECTED_PROFILE_IDS)
            ),
            "links": tuple(
                link
                for link in restored["links"]
                if link[0] in set(EXPECTED_PROFILE_IDS)
                and link[1] in set(EXPECTED_PERMISSION_IDS)
            ),
        }
    )


def _run_adulteration_scenario(url: str, mode: str) -> None:
    _assert_success(_run_alembic(url, "upgrade", "004_catalogo_permissoes_rbac"))
    asyncio.run(_mutate_permission(url, mode))
    _assert_success(_run_alembic(url, "stamp", "003_correcoes_fase1"))
    failed = _run_alembic(url, "upgrade", "004_catalogo_permissoes_rbac")
    assert failed.returncode != 0
    output = failed.stdout + failed.stderr
    assert "004" in output
    assert "chave" in output
    if mode == "id":
        assert "conflito de permissao" in output
    else:
        assert "permissao adulterado" in output


def test_fase2_catalogo_rbac_em_bancos_descartaveis(tmp_path):
    """Validate the full 004 lifecycle without writing the official database."""
    migration = _load_migration()
    assert migration.revision == "004_catalogo_permissoes_rbac"
    assert migration.down_revision == "003_correcoes_fase1"

    official_before = _sha256(OFFICIAL_DB)
    _assert_official_readable_only()

    targets = [("sqlite", _sqlite_url(tmp_path / "fase2_catalogo.db"))]
    postgres_url = os.getenv("FASE2_TEST_POSTGRES_URL")
    if postgres_url:
        assert postgres_url.startswith(("postgresql://", "postgresql+asyncpg://", "postgres://"))
        targets.append(("postgresql", postgres_url))

    for backend, url in targets:
        _assert_disposable_url(url)
        if backend == "postgresql":
            asyncio.run(_reset_postgres(url))
        _run_catalog_scenario(url)

        for mode in ("id", "key"):
            if backend == "postgresql":
                asyncio.run(_reset_postgres(url))
                conflict_url = url
            else:
                conflict_url = _sqlite_url(tmp_path / f"fase2_adulteration_{mode}.db")
            _run_adulteration_scenario(conflict_url, mode)

    _assert_official_readable_only()
    assert _sha256(OFFICIAL_DB) == official_before
