"""Permanent tests for the deterministic Phase F5A-1 clinical RBAC catalog (006).

NOTA DE ESCOPO: o cenÃƒÆ’Ã‚Â¡rio de "clone futuro" abaixo ÃƒÆ’Ã‚Â© uma SIMULAÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O da
semÃƒÆ’Ã‚Â¢ntica de clonagem (copiar para um novo perfil local o conjunto exato de
grants do template). Ele NÃƒÆ’Ã†â€™O executa ``_clone_ilpi_admin_profile`` do
onboarding; o caminho real de clonagem ÃƒÆ’Ã‚Â© coberto pelos testes da Fase 3B.
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
MIGRATION = BACKEND / "alembic" / "versions" / "006_catalogo_clinico_rbac.py"
SECURITY = BACKEND / "src" / "application" / "security.py"

EXPECTED_PERMISSION_IDS = tuple(f"fac11000-0000-4000-8000-{n:012d}" for n in range(27, 41))
EXPECTED_KEYS = (
    "residentes:ler", "residentes:criar", "residentes:atualizar", "residentes:inativar",
    "familiares:ler", "familiares:criar", "familiares:atualizar", "familiares:inativar",
    "tarefas:ler", "tarefas:criar", "tarefas:atualizar", "tarefas:inativar",
    "sinais_vitais:ler", "sinais_vitais:criar",
)
# Baseline administrativo da 004 para o ilpi_admin (template e clones).
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
TEMPLATE_ID = "fac10000-0000-4000-8000-000000000002"
SUPER_ID = "fac10000-0000-4000-8000-000000000001"
CLONE_ID = "fac14000-0000-4000-8000-000000000001"
FUTURE_CLONE_ID = "fac14000-0000-4000-8000-000000000002"
CUSTOM_PROFILE_ID = "fac14000-0000-4000-8000-000000000003"
FAKE_ILPI_A = "fac15000-0000-4000-8000-0000000000a1"
FAKE_ILPI_B = "fac15000-0000-4000-8000-0000000000b2"


def _sqlite_url(path: pathlib.Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def _async_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def _assert_disposable_url(url: str) -> None:
    """Isolamento primÃƒÆ’Ã‚Â¡rio: a URL do teste nunca pode ser a do banco oficial."""
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
    return subprocess.run([sys.executable, "-m", "alembic", "-x", f"database_url={url}", *arguments], cwd=BACKEND, env=environment, capture_output=True, text=True, encoding="utf-8", errors="replace")


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
    rows = asyncio.run(_query(url, "SELECT p.chave FROM perfil_permissoes pp JOIN permissoes p ON p.id = pp.permissao_id WHERE pp.perfil_id = :pid", {"pid": profile_id}))
    return {row["chave"] for row in rows}


def _assert_success(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 0, result.stdout + result.stderr


def _official_snapshot() -> str | None:
    """EvidÃƒÆ’Ã‚Âªncia adicional (nÃƒÆ’Ã‚Â£o-gate): hash do banco oficial, se legÃƒÆ’Ã‚Â­vel.

    O isolamento real ÃƒÆ’Ã‚Â© garantido por ``_assert_disposable_url``. Nenhuma
    conexÃƒÆ’Ã‚Â£o ÃƒÆ’Ã‚Â© aberta no banco oficial; apenas leitura de bytes para hash
    quando o arquivo existe e estÃƒÆ’Ã‚Â¡ acessÃƒÆ’Ã‚Â­vel. Retorna None quando
    indisponÃƒÆ’Ã‚Â­vel, sem falhar o teste.
    """
    try:
        digest = hashlib.sha256()
        with OFFICIAL_DB.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest().upper()
    except OSError:
        return None


def _load_migration():
    spec = importlib.util.spec_from_file_location("phase5a_clinical_migration", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_catalog_scenario(url: str) -> None:
    _assert_success(_run_alembic(url, "upgrade", "005_fase3a_bootstrap_auth"))

    # ILPIs descart?veis necess?rias para satisfazer a FK perfis.ilpi_id.
    asyncio.run(_exec(
        url,
        "INSERT INTO instituicoes "
        "(id, razao_social, capacidade, uf, situacao) "
        "VALUES (:id, :razao, 10, 'SP', 'ILPI_RASCUNHO')",
        {"id": FAKE_ILPI_A, "razao": "ILPI Teste A"},
    ))
    asyncio.run(_exec(
        url,
        "INSERT INTO instituicoes "
        "(id, razao_social, capacidade, uf, situacao) "
        "VALUES (:id, :razao, 10, 'SP', 'ILPI_RASCUNHO')",
        {"id": FAKE_ILPI_B, "razao": "ILPI Teste B"},
    ))
    # clone local preexistente (simula ILPI com onboarding anterior ÃƒÆ’Ã‚Â  006)
    asyncio.run(_exec(url, "INSERT INTO perfis (id, ilpi_id, nome, chave, descricao, escopo, situacao) VALUES (:id, :ilpi, :nome, 'ilpi_admin', 'clone preexistente', 'ilpi', 'ativo')", {"id": CLONE_ID, "ilpi": FAKE_ILPI_A, "nome": "Clone A"}))
    asyncio.run(_exec(url, "INSERT INTO perfil_permissoes (perfil_id, permissao_id) SELECT :cid, permissao_id FROM perfil_permissoes WHERE perfil_id = :tid", {"cid": CLONE_ID, "tid": TEMPLATE_ID}))
    assert _grants(url, CLONE_ID) == EXPECTED_ADMIN_22
    before = {row["chave"] for row in asyncio.run(_query(url, "SELECT chave FROM permissoes"))}
    assert len(before) == 26
    _assert_success(_run_alembic(url, "upgrade", "006_catalogo_clinico_rbac"))
    snap = {row["chave"]: row["id"] for row in asyncio.run(_query(url, "SELECT chave, id FROM permissoes"))}
    assert len(snap) == 40, sorted(snap)
    assert len(set(snap.values())) == 40, "duplicated permission ids"
    assert [snap[key] for key in EXPECTED_KEYS] == list(EXPECTED_PERMISSION_IDS)
    assert _grants(url, TEMPLATE_ID) == EXPECTED_ADMIN_22 | set(EXPECTED_KEYS)
    assert _grants(url, CLONE_ID) == EXPECTED_ADMIN_22 | set(EXPECTED_KEYS)
    assert _grants(url, SUPER_ID).isdisjoint(set(EXPECTED_KEYS)) and len(_grants(url, SUPER_ID)) == 15
    assert len(asyncio.run(_query(url, "SELECT perfil_id FROM perfil_permissoes"))) == 59 + 28
    # SIMULAÃƒÆ’Ã¢â‚¬Â¡ÃƒÆ’Ã†â€™O da semÃƒÆ’Ã‚Â¢ntica de clonagem futura: novo perfil local recebe
    # cÃƒÆ’Ã‚Â³pia exata dos grants do template (o onboarding real ÃƒÆ’Ã‚Â© coberto na Fase 3B)
    asyncio.run(_exec(url, "INSERT INTO perfis (id, ilpi_id, nome, chave, descricao, escopo, situacao) VALUES (:id, :ilpi, :nome, 'ilpi_admin', 'clone futuro (simulacao)', 'ilpi', 'ativo')", {"id": FUTURE_CLONE_ID, "ilpi": FAKE_ILPI_B, "nome": "Clone B"}))
    asyncio.run(_exec(url, "INSERT INTO perfil_permissoes (perfil_id, permissao_id) SELECT :cid, permissao_id FROM perfil_permissoes WHERE perfil_id = :tid", {"cid": FUTURE_CLONE_ID, "tid": TEMPLATE_ID}))
    assert _grants(url, FUTURE_CLONE_ID) == _grants(url, TEMPLATE_ID)
    assert set(EXPECTED_KEYS) <= _grants(url, FUTURE_CLONE_ID)
    # idempotência: upgrade novamente não duplica nem altera
    _assert_success(_run_alembic(url, "upgrade", "006_catalogo_clinico_rbac"))
    assert _grants(url, TEMPLATE_ID) == EXPECTED_ADMIN_22 | set(EXPECTED_KEYS)
    assert len(asyncio.run(_query(url, "SELECT perfil_id FROM perfil_permissoes"))) == 59 + 28 + 36
    # downgrade remove exatamente os artefatos da 006 e restaura o baseline
    _assert_success(_run_alembic(url, "downgrade", "005_fase3a_bootstrap_auth"))
    after = {row["chave"] for row in asyncio.run(_query(url, "SELECT chave FROM permissoes"))}
    assert after == before and len(after) == 26
    assert set(EXPECTED_KEYS).isdisjoint({row["chave"] for row in asyncio.run(_query(url, "SELECT chave FROM permissoes"))})
    assert _grants(url, TEMPLATE_ID) == EXPECTED_ADMIN_22
    assert _grants(url, CLONE_ID) == EXPECTED_ADMIN_22
    assert _grants(url, FUTURE_CLONE_ID) == EXPECTED_ADMIN_22
    # re-upgrade restaura integralmente
    _assert_success(_run_alembic(url, "upgrade", "006_catalogo_clinico_rbac"))
    assert len(asyncio.run(_query(url, "SELECT chave FROM permissoes"))) == 40
    assert _grants(url, TEMPLATE_ID) == EXPECTED_ADMIN_22 | set(EXPECTED_KEYS)
    assert _grants(url, FUTURE_CLONE_ID) == EXPECTED_ADMIN_22 | set(EXPECTED_KEYS)
    cols = [row["name"] for row in asyncio.run(_query(url, "PRAGMA table_info(users)" if "sqlite" in url else "SELECT column_name AS name FROM information_schema.columns WHERE table_name = 'users'"))]
    assert "ilpi_id" not in cols, cols


def _run_downgrade_refusal_scenario(url: str) -> None:
    _assert_success(_run_alembic(url, "upgrade", "006_catalogo_clinico_rbac"))
    asyncio.run(_exec(url, "INSERT INTO perfis (id, ilpi_id, nome, chave, descricao, escopo, situacao) VALUES (:id, NULL, 'Perfil externo', 'perfil_externo', 'fixture', 'global', 'ativo')", {"id": CUSTOM_PROFILE_ID}))
    asyncio.run(_exec(url, "INSERT INTO perfil_permissoes (perfil_id, permissao_id) VALUES (:pid, :mid)", {"pid": CUSTOM_PROFILE_ID, "mid": EXPECTED_PERMISSION_IDS[0]}))
    refused = _run_alembic(url, "downgrade", "005_fase3a_bootstrap_auth")
    assert refused.returncode != 0, refused.stdout + refused.stderr
    output = refused.stdout + refused.stderr
    assert "006 recusa downgrade" in output
    # dados permanecem ÃƒÆ’Ã‚Â­ntegros apÃƒÆ’Ã‚Â³s a recusa
    assert len(asyncio.run(_query(url, "SELECT chave FROM permissoes"))) == 40
    assert _grants(url, TEMPLATE_ID) == EXPECTED_ADMIN_22 | set(EXPECTED_KEYS)
    assert EXPECTED_KEYS[0] in _grants(url, CUSTOM_PROFILE_ID)


def test_fase5a_catalogo_clinico_em_bancos_descartaveis(tmp_path):
    """Validate the full 006 lifecycle without writing the official database."""
    migration = _load_migration()
    assert migration.revision == "006_catalogo_clinico_rbac"
    assert migration.down_revision == "005_fase3a_bootstrap_auth"
    assert len(migration.CLINICAL_PERMISSIONS) == 14
    assert [p["chave"] for p in migration.CLINICAL_PERMISSIONS] == list(EXPECTED_KEYS)
    assert [p["id"] for p in migration.CLINICAL_PERMISSIONS] == list(EXPECTED_PERMISSION_IDS)
    source = open(MIGRATION, encoding="utf-8").read()
    assert ":editar" not in source
    assert ":executar" not in source
    assert ":registrar" not in source
    assert "CREATE TABLE" not in source
    assert "ALTER TABLE" not in source
    assert "users.ilpi_id" not in source
    assert "INSERT INTO residentes" not in source
    assert "INSERT INTO tarefas" not in source
    assert "INSERT INTO sinais_vitais" not in source
    assert "INSERT INTO familiares" not in source
    assert "86c21d63" not in source
    assert "11222333" not in source
    assert "ILPI Modelo" not in source
    security = SECURITY.read_text(encoding="utf-8")
    for key in EXPECTED_KEYS:
        assert f'"{key}"' in security, key
    official_before = _official_snapshot()
    targets = [("sqlite", _sqlite_url(tmp_path / "fase5a_catalogo.db"))]
    postgres_url = os.getenv("FASE3A_TEST_POSTGRES_URL")
    if postgres_url:
        assert postgres_url.startswith(("postgresql://", "postgresql+asyncpg://", "postgres://"))
        targets.append(("postgresql", postgres_url))
    for backend, url in targets:
        _assert_disposable_url(url)
        if backend == "postgresql":
            asyncio.run(_reset_postgres(url))
        _run_catalog_scenario(url)
        # recusa de downgrade em banco descartÃƒÆ’Ã‚Â¡vel prÃƒÆ’Ã‚Â³prio por backend:
        # SQLite usa arquivo independente; PostgreSQL ÃƒÆ’Ã‚Â© resetado antes do reuso
        if backend == "postgresql":
            asyncio.run(_reset_postgres(url))
            refusal_url = url
        else:
            refusal_url = _sqlite_url(tmp_path / "fase5a_recusa.db")
        _run_downgrade_refusal_scenario(refusal_url)
    if official_before is not None:
        assert _official_snapshot() == official_before