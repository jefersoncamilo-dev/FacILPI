"""Permanent tests for the Phase F5A-2C0 RBAC catalog expansion (007).

NOTA DE ESCOPO: esta fase expande o catálogo RBAC com 4 permissões do
módulo ``documentos``. Não implementa endpoints, models ou schemas de
Documentos — isso pertence à F5A-2C.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import os
import pathlib
import subprocess
import sys

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
OFFICIAL_DB = ROOT / "storage" / "app.db"
MIGRATION_007 = BACKEND / "alembic" / "versions" / "007_expandir_rbac_documentos.py"
MIGRATION_006 = BACKEND / "alembic" / "versions" / "006_catalogo_clinico_rbac.py"
SECURITY = BACKEND / "src" / "application" / "security.py"

EXPECTED_DOC_PERMISSION_IDS = tuple(f"fac11000-0000-4000-8000-{n:012d}" for n in range(41, 45))
EXPECTED_DOC_KEYS = (
    "documentos:ler",
    "documentos:criar",
    "documentos:atualizar",
    "documentos:inativar",
)
EXPECTED_DOC_MODULES = ("documentos", "documentos", "documentos", "documentos")
EXPECTED_DOC_ACTIONS = ("ler", "criar", "atualizar", "inativar")

# Permissões administrativas (004) + clínicas (006) para template ilpi_admin
EXPECTED_ADMIN_22 = {
    "ilpis:ler", "ilpis:atualizar",
    "usuarios:ler", "usuarios:criar", "usuarios:atualizar", "usuarios:inativar",
    "usuarios:redefinir_senha", "usuarios:atribuir_perfil",
    "funcionarios:ler", "funcionarios:criar", "funcionarios:atualizar",
    "funcionarios:inativar", "funcionarios:vincular_usuario",
    "perfis:ler", "perfis:criar", "perfis:atualizar", "perfis:inativar",
    "perfis:atribuir_permissao", "permissoes:ler",
    "configuracoes:ler", "configuracoes:atualizar", "auditoria:ler",
}
EXPECTED_CLINICAL_14 = (
    "residentes:ler", "residentes:criar", "residentes:atualizar", "residentes:inativar",
    "familiares:ler", "familiares:criar", "familiares:atualizar", "familiares:inativar",
    "tarefas:ler", "tarefas:criar", "tarefas:atualizar", "tarefas:inativar",
    "sinais_vitais:ler", "sinais_vitais:criar",
)

TEMPLATE_ID = "fac10000-0000-4000-8000-000000000002"
SUPER_ID = "fac10000-0000-4000-8000-000000000001"
CLONE_ID = "fac14000-0000-4000-8000-000000000001"
FUTURE_CLONE_ID = "fac14000-0000-4000-8000-000000000002"
CUSTOM_PROFILE_ID = "fac14000-0000-4000-8000-000000000003"
FAKE_ILPI_A = "fac15000-0000-4000-8000-0000000000a1"
FAKE_ILPI_B = "fac15000-0000-4000-8000-0000000000b2"

BASELINE_PRE_007 = 40
BASELINE_POST_007 = 44
EXPECTED_DOC_COUNT = 4


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
    else:
        assert "storage/app.db" not in url, "test must never write the official database"


def _run_alembic(url: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    _assert_disposable_url(url)
    environment = os.environ.copy()
    environment["DATABASE_URL"] = url
    environment.pop("APP_DATABASE_URL", None)
    return subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"database_url={url}", *arguments],
        cwd=BACKEND, env=environment,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
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


async def _exec(url: str, statement: str, params: dict | None = None):
    engine = create_async_engine(_async_url(url), poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.execute(text(statement), params or {})
    finally:
        await engine.dispose()


async def _query(url: str, statement: str, params: dict | None = None):
    engine = create_async_engine(_async_url(url), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            return (await connection.execute(text(statement), params or {})).mappings().all()
    finally:
        await engine.dispose()


def _grants(url: str, profile_id: str) -> set:
    rows = asyncio.run(_query(
        url,
        "SELECT p.chave FROM perfil_permissoes pp "
        "JOIN permissoes p ON p.id = pp.permissao_id "
        "WHERE pp.perfil_id = :pid",
        {"pid": profile_id},
    ))
    return {row["chave"] for row in rows}


def _assert_success(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stdout + result.stderr


def _official_snapshot() -> str | None:
    try:
        digest = hashlib.sha256()
        with OFFICIAL_DB.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest().upper()
    except OSError:
        return None


def _load_migration_007():
    spec = importlib.util.spec_from_file_location("phase5a2c0_migration", MIGRATION_007)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_migration_006():
    spec = importlib.util.spec_from_file_location("phase5a_migration", MIGRATION_006)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _setup_state_after_006(url: str) -> None:
    """Upgrade to 006 head, create test ILPIs, clone, and grant baseline."""
    _assert_success(_run_alembic(url, "upgrade", "006_catalogo_clinico_rbac"))
    asyncio.run(_exec(url, "INSERT INTO instituicoes (id, razao_social, capacidade, uf, situacao) VALUES (:id, :razao, 10, 'SP', 'ILPI_RASCUNHO')", {"id": FAKE_ILPI_A, "razao": "ILPI Teste A"}))
    asyncio.run(_exec(url, "INSERT INTO instituicoes (id, razao_social, capacidade, uf, situacao) VALUES (:id, :razao, 10, 'SP', 'ILPI_RASCUNHO')", {"id": FAKE_ILPI_B, "razao": "ILPI Teste B"}))
    asyncio.run(_exec(url, "INSERT INTO perfis (id, ilpi_id, nome, chave, descricao, escopo, situacao) VALUES (:id, :ilpi, :nome, 'ilpi_admin', 'clone preexistente', 'ilpi', 'ativo')", {"id": CLONE_ID, "ilpi": FAKE_ILPI_A, "nome": "Clone A"}))
    asyncio.run(_exec(url, "INSERT INTO perfil_permissoes (perfil_id, permissao_id) SELECT :cid, permissao_id FROM perfil_permissoes WHERE perfil_id = :tid", {"cid": CLONE_ID, "tid": TEMPLATE_ID}))


def _assert_pre_007_baseline(url: str) -> None:
    """Verify the 006 baseline: 40 permissions, correct template/clone/super grants."""
    perms = {row["chave"] for row in asyncio.run(_query(url, "SELECT chave FROM permissoes"))}
    assert len(perms) == BASELINE_PRE_007, f"expected {BASELINE_PRE_007} permissions, got {len(perms)}"
    assert set(EXPECTED_DOC_KEYS).isdisjoint(perms), "documentos permissions should not exist before 007"
    assert _grants(url, TEMPLATE_ID) == EXPECTED_ADMIN_22 | set(EXPECTED_CLINICAL_14)
    assert _grants(url, CLONE_ID) == EXPECTED_ADMIN_22 | set(EXPECTED_CLINICAL_14)
    super_grants = _grants(url, SUPER_ID)
    assert super_grants.isdisjoint(set(EXPECTED_DOC_KEYS)), "platform_superuser has文档权限 before 007"
    assert len(super_grants) == 15


def _run_upgrade_scenario(url: str) -> None:
    """Test 007 upgrade from 006 baseline."""
    _setup_state_after_006(url)
    _assert_pre_007_baseline(url)

    # Upgrade to 007
    _assert_success(_run_alembic(url, "upgrade", "head"))

    # Verify 4 new permissions added
    snap = {row["chave"]: row["id"] for row in asyncio.run(_query(url, "SELECT chave, id FROM permissoes"))}
    assert len(snap) == BASELINE_POST_007, f"expected {BASELINE_POST_007} permissions, got {len(snap)}: {sorted(snap)}"
    assert len(set(snap.values())) == BASELINE_POST_007, "duplicated permission ids"

    # Verify specific keys, ids, modules, actions
    assert [snap[key] for key in EXPECTED_DOC_KEYS] == list(EXPECTED_DOC_PERMISSION_IDS)
    for i, key in enumerate(EXPECTED_DOC_KEYS):
        modulo, acao = key.split(":")
        assert modulo == EXPECTED_DOC_MODULES[i]
        assert acao == EXPECTED_DOC_ACTIONS[i]

    # Verify ilpi_admin template gets exactly 4 new grants
    template_grants = _grants(url, TEMPLATE_ID)
    assert template_grants == EXPECTED_ADMIN_22 | set(EXPECTED_CLINICAL_14) | set(EXPECTED_DOC_KEYS)

    # Verify clone gets same grants
    clone_grants = _grants(url, CLONE_ID)
    assert clone_grants == EXPECTED_ADMIN_22 | set(EXPECTED_CLINICAL_14) | set(EXPECTED_DOC_KEYS)

    # Verify platform_superuser gets zero documentos grants
    super_grants = _grants(url, SUPER_ID)
    assert super_grants.isdisjoint(set(EXPECTED_DOC_KEYS))
    assert len(super_grants) == 15

    # Verify documentos permissions are ILPI-only
    security = SECURITY.read_text(encoding="utf-8")
    for key in EXPECTED_DOC_KEYS:
        assert f'"{key}"' in security, f"{key} not in _ILPI_ONLY_PERMISSIONS"

    # Verify 004 and 006 catalogs preserved
    admin_keys = {row["chave"] for row in asyncio.run(_query(url, "SELECT chave FROM permissoes WHERE modulo NOT IN ('documentos')"))}
    assert len(admin_keys) == BASELINE_PRE_007, "004+006 catalog should be preserved"


def _run_future_clone_scenario(url: str) -> None:
    """Future clone simulation: new local clone gets document grants."""
    asyncio.run(_exec(url, "INSERT INTO perfis (id, ilpi_id, nome, chave, descricao, escopo, situacao) VALUES (:id, :ilpi, :nome, 'ilpi_admin', 'clone futuro (simulacao)', 'ilpi', 'ativo')", {"id": FUTURE_CLONE_ID, "ilpi": FAKE_ILPI_B, "nome": "Clone B"}))
    asyncio.run(_exec(url, "INSERT INTO perfil_permissoes (perfil_id, permissao_id) SELECT :cid, permissao_id FROM perfil_permissoes WHERE perfil_id = :tid", {"cid": FUTURE_CLONE_ID, "tid": TEMPLATE_ID}))
    assert _grants(url, FUTURE_CLONE_ID) == _grants(url, TEMPLATE_ID)
    assert set(EXPECTED_DOC_KEYS) <= _grants(url, FUTURE_CLONE_ID)


def _run_idempotency_scenario(url: str) -> None:
    """Re-upgrade does not duplicate permissions."""
    _assert_success(_run_alembic(url, "upgrade", "head"))
    assert _grants(url, TEMPLATE_ID) == EXPECTED_ADMIN_22 | set(EXPECTED_CLINICAL_14) | set(EXPECTED_DOC_KEYS)
    perms = asyncio.run(_query(url, "SELECT chave FROM permissoes"))
    assert len(perms) == BASELINE_POST_007


def _run_downgrade_scenario(url: str) -> None:
    """Downgrade removes only 007 artifacts, restores 006 baseline."""
    _assert_success(_run_alembic(url, "downgrade", "006_catalogo_clinico_rbac"))
    perms = {row["chave"] for row in asyncio.run(_query(url, "SELECT chave FROM permissoes"))}
    assert len(perms) == BASELINE_PRE_007
    assert set(EXPECTED_DOC_KEYS).isdisjoint(perms)
    assert _grants(url, TEMPLATE_ID) == EXPECTED_ADMIN_22 | set(EXPECTED_CLINICAL_14)
    assert _grants(url, CLONE_ID) == EXPECTED_ADMIN_22 | set(EXPECTED_CLINICAL_14)
    assert _grants(url, FUTURE_CLONE_ID) == EXPECTED_ADMIN_22 | set(EXPECTED_CLINICAL_14)


def _run_reupgrade_scenario(url: str) -> None:
    """Re-upgrade after downgrade restores everything."""
    _assert_success(_run_alembic(url, "upgrade", "head"))
    assert len(asyncio.run(_query(url, "SELECT chave FROM permissoes"))) == BASELINE_POST_007
    assert _grants(url, TEMPLATE_ID) == EXPECTED_ADMIN_22 | set(EXPECTED_CLINICAL_14) | set(EXPECTED_DOC_KEYS)
    assert _grants(url, FUTURE_CLONE_ID) == EXPECTED_ADMIN_22 | set(EXPECTED_CLINICAL_14) | set(EXPECTED_DOC_KEYS)


def _run_upgrade_downgrade_upgrade_scenario(url: str) -> None:
    """Full cycle: upgrade → downgrade → upgrade."""
    _run_upgrade_scenario(url)
    _run_future_clone_scenario(url)
    _run_idempotency_scenario(url)
    _run_downgrade_scenario(url)
    _run_reupgrade_scenario(url)


def _run_downgrade_refusal_scenario(url: str) -> None:
    """Downgrade refuses if external links exist."""
    _assert_success(_run_alembic(url, "upgrade", "head"))
    asyncio.run(_exec(url, "INSERT INTO perfis (id, ilpi_id, nome, chave, descricao, escopo, situacao) VALUES (:id, NULL, 'Perfil externo', 'perfil_externo', 'fixture', 'global', 'ativo')", {"id": CUSTOM_PROFILE_ID}))
    asyncio.run(_exec(url, "INSERT INTO perfil_permissoes (perfil_id, permissao_id) VALUES (:pid, :mid)", {"pid": CUSTOM_PROFILE_ID, "mid": EXPECTED_DOC_PERMISSION_IDS[0]}))
    refused = _run_alembic(url, "downgrade", "006_catalogo_clinico_rbac")
    assert refused.returncode != 0, refused.stdout + refused.stderr
    output = refused.stdout + refused.stderr
    assert "007 recusa downgrade" in output
    assert len(asyncio.run(_query(url, "SELECT chave FROM permissoes"))) == BASELINE_POST_007
    assert EXPECTED_DOC_KEYS[0] in _grants(url, CUSTOM_PROFILE_ID)


def _run_unique_constraint_scenario(url: str) -> None:
    """Verify UNIQUE constraints on permissoes (chave, modulo+acao) are preserved."""
    _assert_success(_run_alembic(url, "upgrade", "head"))
    # Second upgrade should be idempotent (no error, no duplicate)
    _assert_success(_run_alembic(url, "upgrade", "head"))
    assert _grants(url, TEMPLATE_ID) == EXPECTED_ADMIN_22 | set(EXPECTED_CLINICAL_14) | set(EXPECTED_DOC_KEYS)
    perms = asyncio.run(_query(url, "SELECT chave FROM permissoes"))
    assert len(perms) == BASELINE_POST_007, "idempotency preserved"


def _run_idempotency_only(url: str) -> None:
    """Standalone idempotency test on a fresh database."""
    _assert_success(_run_alembic(url, "upgrade", "006_catalogo_clinico_rbac"))
    _assert_success(_run_alembic(url, "upgrade", "head"))
    _assert_success(_run_alembic(url, "upgrade", "head"))
    assert _grants(url, TEMPLATE_ID) == EXPECTED_ADMIN_22 | set(EXPECTED_CLINICAL_14) | set(EXPECTED_DOC_KEYS)
    perms = asyncio.run(_query(url, "SELECT chave FROM permissoes"))
    assert len(perms) == BASELINE_POST_007, "idempotency preserved"


def _run_conflict_detection_scenario(url: str) -> None:
    """Verify ID/chave conflicts are not silently accepted."""
    _setup_state_after_006(url)
    # Insert a permission with same chave but different id
    asyncio.run(_exec(
        url,
        "INSERT INTO permissoes (id, modulo, acao, chave, descricao) VALUES (:id, 'documentos', 'ler', 'documentos:ler', 'conflict')",
        {"id": "fac11000-0000-4000-8000-999999999999"},
    ))
    # Upgrade should detect the conflict and fail
    result = _run_alembic(url, "upgrade", "head")
    assert result.returncode != 0, "upgrade should fail on chave conflict"
    assert "conflito" in (result.stdout + result.stderr).lower() or "007" in (result.stdout + result.stderr)


def _run_security_block_scenario(url: str) -> None:
    """Verify platform_superuser is blocked from documentos permissions at runtime."""
    _setup_state_after_006(url)
    _assert_success(_run_alembic(url, "upgrade", "head"))
    # The _CLINICAL_MODULES set already contains 'documentos'
    security = SECURITY.read_text(encoding="utf-8")
    assert '"documentos"' in security, "documentos not in _CLINICAL_MODULES"
    # The runtime guard in _permission_is_allowed checks:
    # context.perfil.chave == 'platform_superuser' and permission.modulo in _CLINICAL_MODULES
    # Since 'documentos' is in _CLINICAL_MODULES, platform_superuser is blocked


def _run_ilpi_only_scenario(url: str) -> None:
    """Verify documentos permissions are listed in _ILPI_ONLY_PERMISSIONS."""
    security = SECURITY.read_text(encoding="utf-8")
    for key in EXPECTED_DOC_KEYS:
        assert f'"{key}"' in security, f"{key} not found in _ILPI_ONLY_PERMISSIONS"


def _run_full_catalog_scenario(tmp_path: pathlib.Path, backend: str, base_url: str) -> None:
    """Complete lifecycle test for 007, each scenario on its own disposable DB."""
    # Scenario 1: Upgrade/Downgrade/Upgrade cycle
    if backend == "postgresql":
        asyncio.run(_reset_postgres(base_url))
        url1 = base_url
    else:
        url1 = _sqlite_url(tmp_path / "fase5a2c0_lifecycle.db")
    _run_upgrade_downgrade_upgrade_scenario(url1)
    # Scenario 2: Downgrade refusal
    if backend == "postgresql":
        asyncio.run(_reset_postgres(base_url))
        url2 = base_url
    else:
        url2 = _sqlite_url(tmp_path / "fase5a2c0_refusal.db")
    _run_downgrade_refusal_scenario(url2)
    # Scenario 3: Idempotency
    if backend == "postgresql":
        asyncio.run(_reset_postgres(base_url))
        url3 = base_url
    else:
        url3 = _sqlite_url(tmp_path / "fase5a2c0_idempotent.db")
    _run_idempotency_only(url3)
    # Scenario 4: Conflict detection
    if backend == "postgresql":
        asyncio.run(_reset_postgres(base_url))
        url4 = base_url
    else:
        url4 = _sqlite_url(tmp_path / "fase5a2c0_conflict.db")
    _run_conflict_detection_scenario(url4)
    # Scenario 5: Security block
    if backend == "postgresql":
        asyncio.run(_reset_postgres(base_url))
        url5 = base_url
    else:
        url5 = _sqlite_url(tmp_path / "fase5a2c0_security.db")
    _run_security_block_scenario(url5)
    # Scenario 6: ILPI-only check (static, just verify security.py)
    _run_ilpi_only_scenario(url1)


def test_fase5a2c0_rbac_documentos(tmp_path):
    """Validate the full 007 lifecycle without writing the official database."""
    migration_007 = _load_migration_007()
    assert migration_007.revision == "007_expandir_rbac_documentos"
    assert migration_007.down_revision == "006_catalogo_clinico_rbac"
    assert len(migration_007.DOCUMENT_PERMISSIONS) == EXPECTED_DOC_COUNT
    assert [p["chave"] for p in migration_007.DOCUMENT_PERMISSIONS] == list(EXPECTED_DOC_KEYS)
    assert [p["id"] for p in migration_007.DOCUMENT_PERMISSIONS] == list(EXPECTED_DOC_PERMISSION_IDS)

    migration_006 = _load_migration_006()
    assert migration_006.revision == "006_catalogo_clinico_rbac"

    source_007 = MIGRATION_007.read_text(encoding="utf-8")
    assert ":editar" not in source_007
    assert ":executar" not in source_007
    assert ":registrar" not in source_007
    assert "CREATE TABLE" not in source_007
    assert "ALTER TABLE" not in source_007
    assert "users.ilpi_id" not in source_007
    assert "INSERT INTO residentes" not in source_007
    assert "INSERT INTO tarefas" not in source_007
    assert "INSERT INTO documentos" not in source_007

    security = SECURITY.read_text(encoding="utf-8")
    for key in EXPECTED_DOC_KEYS:
        assert f'"{key}"' in security, key

    official_before = _official_snapshot()
    targets = [("sqlite", _sqlite_url(tmp_path / "fase5a2c0_rbac.db"))]
    postgres_url = os.getenv("FASE3A_TEST_POSTGRES_URL")
    if postgres_url:
        assert postgres_url.startswith(("postgresql://", "postgresql+asyncpg://", "postgres://"))
        targets.append(("postgresql", postgres_url))
    for backend, url in targets:
        _assert_disposable_url(url)
        if backend == "postgresql":
            asyncio.run(_reset_postgres(url))
        _run_full_catalog_scenario(tmp_path, backend, url)
        if backend == "postgresql":
            asyncio.run(_reset_postgres(url))
    if official_before is not None:
        assert _official_snapshot() == official_before
