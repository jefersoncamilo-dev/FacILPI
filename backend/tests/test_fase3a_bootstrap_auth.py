from __future__ import annotations

import asyncio
import os
import pathlib
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
OFFICIAL_DB = ROOT / "storage" / "app.db"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from src import main  # noqa: E402
from src.application import auth  # noqa: E402
from src.application.bootstrap_state import (  # noqa: E402
    FIRST_PASSWORD_CHANGED,
    ILPI_CREATED,
    ONBOARDING_COMPLETED,
    ONBOARDING_IN_PROGRESS,
    PLATFORM_BOOTSTRAPPED,
    transition_state,
)
from src.application.fase3a import ADMIN_EMAIL, ILPI_ACTIVE, ILPI_DRAFT, ILPI_INACTIVE  # noqa: E402
from src.infrastructure import database  # noqa: E402
from src.infrastructure import models as m  # noqa: E402
from src.scripts import bootstrap as bootstrap_script  # noqa: E402


BOOTSTRAP_TOKEN = "fase3a-test-bootstrap-token"
FIRST_PASSWORD = "SenhaPrimeiro123A"
NORMAL_PASSWORD = "SenhaNormal123A"
VALID_CNPJ = "11222333000181"


def _sqlite_url(path: pathlib.Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def _async_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def _database_url(database_ref: pathlib.Path | str) -> str:
    if isinstance(database_ref, pathlib.Path):
        return _sqlite_url(database_ref)
    return _async_url(database_ref)


def _assert_disposable_database(database_ref: pathlib.Path | str) -> None:
    if isinstance(database_ref, pathlib.Path):
        assert database_ref.resolve() != OFFICIAL_DB.resolve()


def _run_migration(database_ref: pathlib.Path | str, *arguments: str) -> None:
    _assert_disposable_database(database_ref)
    url = _database_url(database_ref)
    environment = os.environ.copy()
    environment["DATABASE_URL"] = url
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"database_url={url}", *arguments],
        cwd=BACKEND,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stdout + result.stderr


async def _reset_postgres(url: str) -> None:
    engine = create_async_engine(_async_url(url), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
            await connection.commit()
    finally:
        await engine.dispose()


def _database_backends() -> list[str]:
    backends = ["sqlite"]
    if os.getenv("FASE3A_TEST_POSTGRES_URL"):
        backends.append("postgresql")
    return backends


async def _insert_legacy_users(database_ref: pathlib.Path | str) -> None:
    engine = create_async_engine(_database_url(database_ref), poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            for index in range(2):
                await connection.execute(
                    text(
                        "INSERT INTO users (id, nome, email, password_hash, ativo) "
                        "VALUES (:id, :nome, :email, :password_hash, :ativo)"
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "nome": f"Legado {index}",
                        "email": f"legado{index}@example.test",
                        "password_hash": "hash-legado",
                        "ativo": True,
                    },
                )
    finally:
        await engine.dispose()


@pytest.fixture(params=_database_backends(), ids=lambda backend: backend)
def fase3a_db(request: pytest.FixtureRequest, tmp_path: pathlib.Path) -> pathlib.Path | str:
    if request.param == "sqlite":
        path = tmp_path / "fase3a.db"
        _run_migration(path, "upgrade", "004_catalogo_permissoes_rbac")
        asyncio.run(_insert_legacy_users(path))
        _run_migration(path, "upgrade", "head")
        return path

    url = os.environ["FASE3A_TEST_POSTGRES_URL"]
    try:
        asyncio.run(_reset_postgres(url))
        _run_migration(url, "upgrade", "004_catalogo_permissoes_rbac")
        asyncio.run(_insert_legacy_users(url))
        _run_migration(url, "upgrade", "head")
    except Exception as error:
        pytest.skip(f"PostgreSQL descartável indisponível: {error}")
    return url


async def _with_client(database_ref: pathlib.Path | str, monkeypatch: pytest.MonkeyPatch, operation):
    engine = create_async_engine(_database_url(database_ref), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    main.app.dependency_overrides[main.get_db] = override_get_db
    main.app.dependency_overrides[database.get_db] = override_get_db
    monkeypatch.setattr(bootstrap_script, "SessionLocal", factory)
    monkeypatch.setenv("BOOTSTRAP_TOKEN", BOOTSTRAP_TOKEN)
    auth._rate_store.clear()
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            async with factory() as session:
                return await operation(client, session)
    finally:
        main.app.dependency_overrides.clear()
        await engine.dispose()


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _detail_message(response: httpx.Response) -> str:
    detail = response.json().get("detail")
    if isinstance(detail, dict):
        return str(detail.get("message"))
    return str(detail)


async def _login(client: httpx.AsyncClient, password: str, **context) -> httpx.Response:
    payload = {"email": ADMIN_EMAIL, "password": password}
    payload.update({key: value for key, value in context.items() if value is not None})
    return await client.post("/api/auth/token", json=payload)


def test_migration_004_to_005_preserves_legacy_users(fase3a_db, monkeypatch):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        version = (await db.execute(text("SELECT version_num FROM alembic_version"))).scalar_one()
        assert version == "005_fase3a_bootstrap_auth"
        users = (await db.execute(select(m.User).order_by(m.User.email))).scalars().all()
        assert len(users) == 2
        assert all(not user.is_superuser and not user.exige_troca_senha for user in users)
        assert (await db.execute(text("SELECT COUNT(*) FROM instituicoes"))).scalar_one() == 0
        assert (await db.execute(text("SELECT COUNT(*) FROM funcionarios"))).scalar_one() == 0
        assert (await db.execute(text("SELECT COUNT(*) FROM usuario_ilpi_perfis"))).scalar_one() == 0
        assert (await db.execute(text("SELECT COUNT(*) FROM permissoes"))).scalar_one() == 26
        assert (await db.execute(text("SELECT COUNT(*) FROM perfis"))).scalar_one() == 2
        assert (await db.execute(text("SELECT COUNT(*) FROM perfil_permissoes"))).scalar_one() == 37

    asyncio.run(_with_client(fase3a_db, monkeypatch, scenario))


def test_bootstrap_wrong_repeat_and_concurrent_guards(fase3a_db, monkeypatch):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        with pytest.raises(bootstrap_script.BootstrapFailure) as wrong:
            await bootstrap_script.run_bootstrap("token-incorreto")
        assert wrong.value.code == "BOOTSTRAP_TOKEN_INVALID"

        first, second = await asyncio.gather(
            bootstrap_script.run_bootstrap(BOOTSTRAP_TOKEN),
            bootstrap_script.run_bootstrap(BOOTSTRAP_TOKEN),
            return_exceptions=True,
        )
        successes = [item for item in (first, second) if isinstance(item, bootstrap_script.BootstrapResult)]
        failures = [item for item in (first, second) if isinstance(item, Exception)]
        assert len(successes) == 1
        assert len(failures) == 1
        assert (await db.execute(select(m.User).where(m.User.email == ADMIN_EMAIL))).scalar_one().is_superuser
        assert (await db.execute(text("SELECT COUNT(*) FROM users WHERE lower(email)=:email"), {"email": ADMIN_EMAIL})).scalar_one() == 1
        assert (await db.execute(select(m.BootstrapState.estado))).scalar_one() == PLATFORM_BOOTSTRAPPED

        with pytest.raises(bootstrap_script.BootstrapFailure) as repeated:
            await bootstrap_script.run_bootstrap(BOOTSTRAP_TOKEN)
        assert repeated.value.code in {"INVALID_BOOTSTRAP_STATE", "BOOTSTRAP_ADMIN_EXISTS", "BOOTSTRAP_CONFLICT"}

    asyncio.run(_with_client(fase3a_db, monkeypatch, scenario))


def test_fase3a_full_auth_onboarding_and_admin_flow(fase3a_db, monkeypatch):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        bootstrap = await bootstrap_script.run_bootstrap(BOOTSTRAP_TOKEN)
        assert bootstrap.email == ADMIN_EMAIL
        assert (await db.execute(text("SELECT COUNT(*) FROM instituicoes"))).scalar_one() == 0

        register = await client.post("/api/auth/register", json={"nome": "X", "email": "x@example.test", "password": "Senha123A"})
        assert register.status_code == 410

        login = await _login(client, bootstrap.temporary_password)
        assert login.status_code == 200, login.text
        login_cookie = login.cookies.get("refresh_token")
        assert login_cookie
        set_cookie = login.headers["set-cookie"]
        assert "HttpOnly" in set_cookie
        assert "samesite=strict" in set_cookie.lower()
        assert "Path=/api/auth" in set_cookie
        first_token = login.json()["access_token"]
        denied_before_change = await client.get("/api/instituicoes/", headers=_auth_headers(first_token))
        assert denied_before_change.status_code == 403

        first_access = await client.put(
            "/api/auth/primeiro-acesso",
            headers=_auth_headers(first_token),
            json={"nova_senha": FIRST_PASSWORD, "confirmar": FIRST_PASSWORD},
        )
        assert first_access.status_code == 200, first_access.text
        assert first_access.json()["exige_troca_senha"] is False

        client.cookies.clear()
        old_refresh = await client.post("/api/auth/refresh", headers={"Cookie": f"refresh_token={login_cookie}"})
        assert old_refresh.status_code == 401

        login = await _login(client, FIRST_PASSWORD)
        assert login.status_code == 200, login.text
        access = login.json()["access_token"]
        normal_password = await client.put(
            "/api/auth/password",
            headers=_auth_headers(access),
            json={"nova_senha": NORMAL_PASSWORD, "confirmar_senha": NORMAL_PASSWORD},
        )
        assert normal_password.status_code == 200, normal_password.text

        login = await _login(client, NORMAL_PASSWORD)
        assert login.status_code == 200, login.text
        access = login.json()["access_token"]
        refresh_one = client.cookies.get("refresh_token")
        refreshed = await client.post("/api/auth/refresh")
        assert refreshed.status_code == 200, refreshed.text
        refresh_two = client.cookies.get("refresh_token")
        assert refresh_two and refresh_two != refresh_one
        client.cookies.clear()
        reused = await client.post("/api/auth/refresh", headers={"Cookie": f"refresh_token={refresh_one}"})
        assert reused.status_code == 401

        login = await _login(client, NORMAL_PASSWORD)
        assert login.status_code == 200, login.text
        access = login.json()["access_token"]
        logout = await client.post("/api/auth/logout")
        assert logout.status_code == 200
        after_logout_refresh = await client.post("/api/auth/refresh")
        assert after_logout_refresh.status_code == 401

        login = await _login(client, NORMAL_PASSWORD)
        assert login.status_code == 200, login.text
        global_access = login.json()["access_token"]
        local_route_with_global = await client.post(
            "/api/funcionarios/",
            headers=_auth_headers(global_access),
            json={"nome": "Bloqueado Global"},
        )
        assert local_route_with_global.status_code == 403

        draft = await client.post(
            "/api/instituicoes/",
            headers=_auth_headers(global_access),
            json={
                "razao_social": "ILPI Modelo FacILPI",
                "finalidade": "Desenvolvimento e homologação",
                "capacidade": 10,
                "uf": "SP",
            },
        )
        assert draft.status_code == 201, draft.text
        ilpi = draft.json()
        assert ilpi["cnpj"] is None
        assert ilpi["situacao"] == ILPI_DRAFT
        assert (await db.execute(select(m.BootstrapState.estado))).scalar_one() == ILPI_CREATED

        invalid_cnpj = await client.put(
            f"/api/instituicoes/{ilpi['id']}",
            headers=_auth_headers(global_access),
            json={"cnpj": "123"},
        )
        assert invalid_cnpj.status_code == 422

        onboarding = await client.post(
            f"/api/onboarding/{ilpi['id']}/iniciar",
            headers=_auth_headers(global_access),
            json={"usar_usuario_atual_como_admin": True},
        )
        assert onboarding.status_code == 200, onboarding.text
        assert (await db.execute(select(m.BootstrapState.estado))).scalar_one() == ONBOARDING_IN_PROGRESS

        admin = (await db.execute(select(m.User).where(m.User.email == ADMIN_EMAIL))).scalar_one()
        global_links = (
            await db.execute(select(m.UsuarioIlpiPerfil).where(m.UsuarioIlpiPerfil.usuario_id == admin.id))
        ).scalars().all()
        assert len(global_links) == 2
        assert {link.ilpi_id for link in global_links} == {None, ilpi["id"]}
        local_profile = (
            await db.execute(select(m.Perfil).where(m.Perfil.chave == "ilpi_admin", m.Perfil.ilpi_id == ilpi["id"]))
        ).scalar_one()
        assert local_profile.escopo == "ilpi"
        assert (await db.execute(text("SELECT COUNT(*) FROM funcionarios WHERE ilpi_id=:ilpi"), {"ilpi": ilpi["id"]})).scalar_one() == 1

        activate_without_cnpj = await client.post(f"/api/instituicoes/{ilpi['id']}/ativar", headers=_auth_headers(global_access))
        assert activate_without_cnpj.status_code == 422
        assert _detail_message(activate_without_cnpj) == "CNPJ obrigatório para ativar ILPI"

        local_context = await client.post(
            "/api/auth/contexto",
            headers=_auth_headers(global_access),
            json={"scope": "ilpi", "ilpi_id": ilpi["id"], "perfil_id": local_profile.id},
        )
        assert local_context.status_code == 200, local_context.text
        local_access = local_context.json()["access_token"]
        local_token_global_route = await client.post(
            "/api/instituicoes/",
            headers=_auth_headers(local_access),
            json={"razao_social": "Nao criar", "capacidade": 1},
        )
        assert local_token_global_route.status_code == 403

        second_ilpi = m.Instituicao(id=str(uuid.uuid4()), razao_social="Outra ILPI", situacao=ILPI_DRAFT, capacidade=5)
        db.add(second_ilpi)
        await db.commit()
        cross_tenant = await client.get(f"/api/instituicoes/{second_ilpi.id}", headers=_auth_headers(local_access))
        assert cross_tenant.status_code == 404

        created_user = await client.post(
            "/api/usuarios/",
            headers=_auth_headers(local_access),
            json={"nome": "Usuario Local", "email": "LOCAL@EXAMPLE.COM", "perfil_id": local_profile.id},
        )
        assert created_user.status_code == 201, created_user.text
        created_payload = created_user.json()
        assert created_payload["email"] == "local@example.com"
        assert created_payload["exige_troca_senha"] is True
        target = (await db.execute(select(m.User).where(m.User.id == created_payload["id"]))).scalar_one()
        assert target.password_hash != created_payload["senha_temporaria"]

        employee = await client.post(
            "/api/funcionarios/",
            headers=_auth_headers(local_access),
            json={"nome": "Funcionario Local", "cpf": "52998224725", "email": "func@example.com"},
        )
        assert employee.status_code == 201, employee.text
        linked = await client.post(
            f"/api/funcionarios/{employee.json()['id']}/vincular-usuario",
            headers=_auth_headers(local_access),
            json={"usuario_id": created_payload["id"]},
        )
        assert linked.status_code == 200, linked.text

        reset = await client.patch(f"/api/usuarios/{created_payload['id']}/reset-password", headers=_auth_headers(local_access))
        assert reset.status_code == 200, reset.text
        assert reset.json()["senha_temporaria"]

        updated = await client.put(
            f"/api/instituicoes/{ilpi['id']}",
            headers=_auth_headers(global_access),
            json={"cnpj": VALID_CNPJ, "uf": "SP", "capacidade": 10},
        )
        assert updated.status_code == 200, updated.text
        activated = await client.post(f"/api/instituicoes/{ilpi['id']}/ativar", headers=_auth_headers(global_access))
        assert activated.status_code == 200, activated.text
        assert activated.json()["situacao"] == ILPI_ACTIVE
        assert (await db.execute(select(m.BootstrapState.estado))).scalar_one() == ONBOARDING_COMPLETED

        before_delete_count = (await db.execute(text("SELECT COUNT(*) FROM instituicoes WHERE id=:id"), {"id": ilpi["id"]})).scalar_one()
        deleted = await client.delete(f"/api/instituicoes/{ilpi['id']}", headers=_auth_headers(global_access))
        assert deleted.status_code == 204
        after_delete_count = (await db.execute(text("SELECT COUNT(*) FROM instituicoes WHERE id=:id"), {"id": ilpi["id"]})).scalar_one()
        inactive = (await db.execute(select(m.Instituicao.situacao).where(m.Instituicao.id == ilpi["id"]))).scalar_one()
        assert before_delete_count == after_delete_count == 1
        assert inactive == ILPI_INACTIVE

        audits = (await db.execute(select(m.Auditoria))).scalars().all()
        audit_text = "\n".join(
            item for audit in audits for item in (audit.valores_anteriores or "", audit.valores_posteriores or "")
        )
        forbidden = [
            BOOTSTRAP_TOKEN,
            bootstrap.temporary_password,
            FIRST_PASSWORD,
            NORMAL_PASSWORD,
            login_cookie,
            refresh_one,
            refresh_two,
            created_payload["senha_temporaria"],
            reset.json()["senha_temporaria"],
            "password_hash",
        ]
        assert all(secret not in audit_text for secret in forbidden if secret)

    asyncio.run(_with_client(fase3a_db, monkeypatch, scenario))


def test_onboarding_false_keeps_pending_without_admin(fase3a_db, monkeypatch):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        bootstrap = await bootstrap_script.run_bootstrap(BOOTSTRAP_TOKEN)
        login = await _login(client, bootstrap.temporary_password)
        first_token = login.json()["access_token"]
        first_access = await client.put(
            "/api/auth/primeiro-acesso",
            headers=_auth_headers(first_token),
            json={"nova_senha": FIRST_PASSWORD, "confirmar": FIRST_PASSWORD},
        )
        global_access = first_access.json()["access_token"]
        draft = await client.post(
            "/api/instituicoes/",
            headers=_auth_headers(global_access),
            json={"razao_social": "ILPI Sem Admin", "capacidade": 3, "uf": "SP"},
        )
        ilpi_id = draft.json()["id"]
        onboarding = await client.post(
            f"/api/onboarding/{ilpi_id}/iniciar",
            headers=_auth_headers(global_access),
            json={"usar_usuario_atual_como_admin": False},
        )
        assert onboarding.status_code == 200, onboarding.text
        assert (await db.execute(select(m.BootstrapState.estado))).scalar_one() == ONBOARDING_IN_PROGRESS
        assert (await db.execute(text("SELECT COUNT(*) FROM funcionarios"))).scalar_one() == 0
        assert (await db.execute(text("SELECT COUNT(*) FROM usuario_ilpi_perfis WHERE ilpi_id IS NOT NULL"))).scalar_one() == 0

    asyncio.run(_with_client(fase3a_db, monkeypatch, scenario))


def test_transition_state_is_forward_only(fase3a_db, monkeypatch):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        state = (await db.execute(select(m.BootstrapState))).scalar_one()
        with pytest.raises(HTTPException):
            transition_state(db, state, FIRST_PASSWORD_CHANGED, usuario_id=None)

    asyncio.run(_with_client(fase3a_db, monkeypatch, scenario))


async def _create_test_ilpi(db: AsyncSession, nome: str, cnpj: str | None = None) -> m.Instituicao:
    """Helper to create an instituicao test."""
    obj = m.Instituicao(
        razao_social=f"ILPI Teste {nome}",
        cnpj=cnpj,
        situacao=ILPI_DRAFT,
    )
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return obj


async def _bootstrap_global_access(client: httpx.AsyncClient) -> str:
    bootstrap = await bootstrap_script.run_bootstrap(BOOTSTRAP_TOKEN)
    login = await _login(client, bootstrap.temporary_password)
    assert login.status_code == 200, login.text
    first_access = await client.put(
        "/api/auth/primeiro-acesso",
        headers=_auth_headers(login.json()["access_token"]),
        json={"nova_senha": FIRST_PASSWORD, "confirmar": FIRST_PASSWORD},
    )
    assert first_access.status_code == 200, first_access.text
    return first_access.json()["access_token"]


def test_cross_tenant_isolamento_http_404(fase3a_db, monkeypatch):
    """Test that accessing ILPI A's resource with ILPI B's context returns 404.
    
    This test verifies true cross-tenant isolation at the HTTP level,
    not just FK constraint rejection.
    """
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        global_access = await _bootstrap_global_access(client)
        draft = await client.post(
            "/api/instituicoes/",
            headers=_auth_headers(global_access),
            json={"razao_social": "ILPI Contexto A", "capacidade": 10, "uf": "SP"},
        )
        assert draft.status_code == 201, draft.text
        ilpi_a_id = draft.json()["id"]

        onboarding = await client.post(
            f"/api/onboarding/{ilpi_a_id}/iniciar",
            headers=_auth_headers(global_access),
            json={"usar_usuario_atual_como_admin": True},
        )
        assert onboarding.status_code == 200, onboarding.text
        local_profile = (
            await db.execute(select(m.Perfil).where(m.Perfil.chave == "ilpi_admin", m.Perfil.ilpi_id == ilpi_a_id))
        ).scalar_one()
        local_context = await client.post(
            "/api/auth/contexto",
            headers=_auth_headers(global_access),
            json={"scope": "ilpi", "ilpi_id": ilpi_a_id, "perfil_id": local_profile.id},
        )
        assert local_context.status_code == 200, local_context.text

        ilpi_b = m.Instituicao(id=str(uuid.uuid4()), razao_social="ILPI Contexto B", situacao=ILPI_DRAFT, capacidade=5)
        db.add(ilpi_b)
        await db.commit()

        response = await client.get(f"/api/instituicoes/{ilpi_b.id}", headers=_auth_headers(local_context.json()["access_token"]))
        assert response.status_code == 404, f"Expected 404, got {response.status_code}: {response.text}"
    
    asyncio.run(_with_client(fase3a_db, monkeypatch, scenario))


def test_ilpi_creation_platform_superuser(fase3a_db, monkeypatch):
    """Gate: ILPI creation as platform_superuser via API."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        global_access = await _bootstrap_global_access(client)
        response = await client.post(
            "/api/instituicoes/",
            headers=_auth_headers(global_access),
            json={"razao_social": "ILPI Teste Gate", "capacidade": 5, "uf": "SP"},
        )
        assert response.status_code == 201, f"Expected 201, got {response.status_code}: {response.text}"
        ilpi = response.json()
        assert ilpi["razao_social"] == "ILPI Teste Gate"
        assert ilpi["cnpj"] is None
        assert ilpi["situacao"] == ILPI_DRAFT
        persisted = (await db.execute(select(m.Instituicao).where(m.Instituicao.id == ilpi["id"]))).scalar_one()
        assert persisted.cnpj is None
        assert persisted.situacao == ILPI_DRAFT
    
    asyncio.run(_with_client(fase3a_db, monkeypatch, scenario))


def test_ilpi_ativacao_sem_cnpj_422(fase3a_db, monkeypatch):
    """Gate: Ativação de ILPI sem CNPJ deve retornar HTTP 422."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        global_access = await _bootstrap_global_access(client)
        draft = await client.post(
            "/api/instituicoes/",
            headers=_auth_headers(global_access),
            json={"razao_social": "ILPI Sem CNPJ Gate", "capacidade": 5, "uf": "SP"},
        )
        assert draft.status_code == 201, draft.text
        ilpi_id = draft.json()["id"]
        onboarding = await client.post(
            f"/api/onboarding/{ilpi_id}/iniciar",
            headers=_auth_headers(global_access),
            json={"usar_usuario_atual_como_admin": True},
        )
        assert onboarding.status_code == 200, onboarding.text

        response = await client.post(f"/api/instituicoes/{ilpi_id}/ativar", headers=_auth_headers(global_access))
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        assert _detail_message(response) == "CNPJ obrigatório para ativar ILPI"
        situacao = (await db.execute(select(m.Instituicao.situacao).where(m.Instituicao.id == ilpi_id))).scalar_one()
        assert situacao != ILPI_ACTIVE
    
    asyncio.run(_with_client(fase3a_db, monkeypatch, scenario))


def test_audit_transacional_sucesso_e_rollback(fase3a_db, monkeypatch):
    """Gate: Auditoria transacional - sucesso e rollback."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        from src.application.audit import add_audit

        success_id = str(uuid.uuid4())
        success = m.Instituicao(id=success_id, razao_social="ILPI Audit Commit", situacao=ILPI_DRAFT, capacidade=5)
        db.add(success)
        await db.flush()
        add_audit(db, acao="test.audit.commit", entidade="instituicoes", registro_id=success_id, ilpi_id=success_id)
        await db.commit()

        success_operation_count = (await db.execute(text("SELECT COUNT(*) FROM instituicoes WHERE id=:id"), {"id": success_id})).scalar_one()
        success_audit_count = (await db.execute(text("SELECT COUNT(*) FROM auditoria WHERE registro_id=:id"), {"id": success_id})).scalar_one()
        assert success_operation_count == 1
        assert success_audit_count == 1

        rollback_id = str(uuid.uuid4())
        try:
            rollback = m.Instituicao(id=rollback_id, razao_social="ILPI Audit Rollback", situacao=ILPI_DRAFT, capacidade=5)
            db.add(rollback)
            await db.flush()
            add_audit(db, acao="test.audit.rollback", entidade="instituicoes", registro_id=rollback_id, ilpi_id=rollback_id)
            await db.flush()
            raise RuntimeError("forced rollback before commit")
        except RuntimeError:
            await db.rollback()

        rollback_operation_count = (await db.execute(text("SELECT COUNT(*) FROM instituicoes WHERE id=:id"), {"id": rollback_id})).scalar_one()
        rollback_audit_count = (await db.execute(text("SELECT COUNT(*) FROM auditoria WHERE registro_id=:id"), {"id": rollback_id})).scalar_one()
        assert rollback_operation_count == 0
        assert rollback_audit_count == 0
    
    asyncio.run(_with_client(fase3a_db, monkeypatch, scenario))
