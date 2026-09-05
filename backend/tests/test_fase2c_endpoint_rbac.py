"""Disposable-database tests for Phase 2C endpoint RBAC binding."""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
OFFICIAL_DB = ROOT / "storage" / "app.db"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from src import main  # noqa: E402
from src.application import auth  # noqa: E402
from src.application.auth import create_access_token, hash_password  # noqa: E402
from src.application.security import (  # noqa: E402
    AUTH_CONTEXT_REQUIRED,
    ILPI_CONTEXT_REQUIRED,
    PERMISSION_CATALOG_PENDING,
    PERMISSION_DENIED,
    RESOURCE_NOT_FOUND,
)
from src.infrastructure import database  # noqa: E402
from src.infrastructure import models as m  # noqa: E402


PASSWORD = "SenhaForte123!"


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


def _run_migration(database_ref: pathlib.Path | str) -> None:
    _assert_disposable_database(database_ref)
    url = _database_url(database_ref)
    environment = os.environ.copy()
    environment["DATABASE_URL"] = url
    environment.pop("APP_DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"database_url={url}", "upgrade", "head"],
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
    if os.getenv("FASE2_TEST_POSTGRES_URL"):
        backends.append("postgresql")
    return backends


@pytest.fixture(params=_database_backends(), ids=lambda backend: backend)
def endpoint_db(
    request: pytest.FixtureRequest,
    tmp_path: pathlib.Path,
) -> pathlib.Path | str:
    if request.param == "sqlite":
        path = tmp_path / "fase2c-endpoint-rbac.db"
        _run_migration(path)
        return path

    url = os.environ["FASE2_TEST_POSTGRES_URL"]
    try:
        asyncio.run(_reset_postgres(url))
        _run_migration(url)
    except Exception as error:
        pytest.skip(f"PostgreSQL descartavel indisponivel: {error}")
    return url


async def _with_client(database_ref: pathlib.Path | str, operation):
    engine = create_async_engine(_database_url(database_ref), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    main.app.dependency_overrides[main.get_db] = override_get_db
    main.app.dependency_overrides[database.get_db] = override_get_db
    auth._rate_store.clear()
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            follow_redirects=True,
        ) as client:
            async with factory() as session:
                return await operation(client, session)
    finally:
        main.app.dependency_overrides.clear()
        await engine.dispose()


def _new_id() -> str:
    return str(uuid.uuid4())


def _new_user(*, password_hash: str = "fixture-password-hash") -> m.User:
    user_id = _new_id()
    return m.User(
        id=user_id,
        nome="Usuario Fase 2C",
        email=f"fase2c-{user_id}@example.com",
        password_hash=password_hash,
        ativo=True,
    )


def _new_institution(name: str = "ILPI Fase 2C") -> m.Instituicao:
    return m.Instituicao(
        id=_new_id(),
        razao_social=name,
        situacao="ILPI_RASCUNHO",
    )


def _new_link(user_id: str, perfil_id: str, ilpi_id: str | None) -> m.UsuarioIlpiPerfil:
    return m.UsuarioIlpiPerfil(
        id=_new_id(),
        usuario_id=user_id,
        perfil_id=perfil_id,
        ilpi_id=ilpi_id,
        situacao="ativo",
        data_inicial=datetime.now(timezone.utc) - timedelta(minutes=1),
    )


async def _grant_permissions(db: AsyncSession, perfil_id: str, keys: set[str]) -> None:
    if not keys:
        return
    permissions = (
        await db.execute(select(m.Permissao).where(m.Permissao.chave.in_(keys)))
    ).scalars().all()
    assert {permission.chave for permission in permissions} == keys
    for permission in permissions:
        db.add(m.PerfilPermissao(perfil_id=perfil_id, permissao_id=permission.id))
    await db.flush()


async def _create_platform_user(db: AsyncSession) -> m.User:
    user = _new_user()
    profile = (
        await db.execute(
            select(m.Perfil).where(
                m.Perfil.chave == "platform_superuser",
                m.Perfil.ilpi_id.is_(None),
            )
        )
    ).scalar_one()
    db.add_all([user, _new_link(user.id, profile.id, None)])
    await db.flush()
    return user


async def _create_ilpi_user(
    db: AsyncSession,
    institution: m.Instituicao,
    *,
    permissions: set[str],
    profile_key: str = "ilpi_admin",
) -> m.User:
    """ILPI user with profile + link + active Funcionario (Fase 3B requirement).

    Rows are flushed in FK dependency order because PostgreSQL enforces FK
    constraints immediately while the models declare no ORM relationships
    for the unit of work to sort by.
    """
    user = _new_user()
    profile = m.Perfil(
        id=_new_id(),
        ilpi_id=institution.id,
        nome="Administrador da ILPI",
        chave=profile_key,
        escopo="ilpi",
        situacao="ativo",
    )
    db.add_all([institution, user])
    await db.flush()
    db.add(profile)
    await db.flush()
    employee = m.Funcionario(
        id=_new_id(),
        ilpi_id=institution.id,
        usuario_id=user.id,
        nome=user.nome,
        email=user.email,
        cargo="Administrador da ILPI",
        situacao="ativo",
    )
    db.add_all([employee, _new_link(user.id, profile.id, institution.id)])
    await db.flush()
    await _grant_permissions(db, profile.id, permissions)
    return user


async def _create_user_with_template_ilpi_admin(db: AsyncSession) -> m.User:
    user = _new_user()
    template = (
        await db.execute(
            select(m.Perfil).where(
                m.Perfil.chave == "ilpi_admin",
                m.Perfil.ilpi_id.is_(None),
            )
        )
    ).scalar_one()
    db.add_all([user, _new_link(user.id, template.id, None)])
    await db.flush()
    return user


def _auth_headers(user: m.User, *, scope: str, ilpi_id: str | None = None) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {create_access_token(user)}",
        "X-Scope": scope,
    }
    if ilpi_id is not None:
        headers["X-ILPI-ID"] = ilpi_id
    return headers


def _detail_code(response: httpx.Response) -> str | None:
    detail = response.json().get("detail")
    if isinstance(detail, dict):
        return detail.get("code")
    return None


async def _count(db: AsyncSession, model) -> int:
    return (
        await db.execute(select(func.count()).select_from(model))
    ).scalar_one()


def test_public_register_is_disabled_and_login_still_works(endpoint_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        # Login user must be a valid institutional user under the current
        # model: User + local Perfil + UsuarioIlpiPerfil + active Funcionario.
        # The login itself uses the default flow (no explicit scope), which
        # resolves the single database-validated context.
        institution = _new_institution("ILPI Login")
        user = _new_user(password_hash=hash_password(PASSWORD))
        profile = m.Perfil(
            id=_new_id(),
            ilpi_id=institution.id,
            nome="Perfil Login",
            chave="perfil_login",
            escopo="ilpi",
            situacao="ativo",
        )
        db.add_all([institution, user])
        await db.flush()
        db.add(profile)
        await db.flush()
        employee = m.Funcionario(
            id=_new_id(),
            ilpi_id=institution.id,
            usuario_id=user.id,
            nome=user.nome,
            email=user.email,
            cargo="Cuidador",
            situacao="ativo",
        )
        db.add_all([employee, _new_link(user.id, profile.id, institution.id)])
        await db.flush()
        await db.commit()
        users_before = await _count(db, m.User)

        register_response = await client.post(
            "/api/auth/register",
            json={
                "nome": "Nao Criar",
                "email": "nao-criar@example.com",
                "password": "fraca",
            },
        )
        assert register_response.status_code == 410
        assert _detail_code(register_response) == "PUBLIC_REGISTER_DISABLED"
        assert await _count(db, m.User) == users_before

        login_response = await client.post(
            "/api/auth/token",
            json={"email": user.email, "password": PASSWORD},
        )
        assert login_response.status_code == 200, login_response.text
        assert login_response.json()["token_type"] == "bearer"
        assert login_response.json()["access_token"]

    asyncio.run(_with_client(endpoint_db, scenario))


def test_instituicoes_endpoint_rbac_and_tenant_isolation(endpoint_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi_a = _new_institution("ILPI A")
        ilpi_b = _new_institution("ILPI B")
        user_without_link = _new_user()
        platform_user = await _create_platform_user(db)
        ilpi_admin = await _create_ilpi_user(
            db,
            ilpi_a,
            permissions={"ilpis:ler", "ilpis:atualizar"},
        )
        missing_permission_user = await _create_ilpi_user(
            db,
            ilpi_a,
            permissions=set(),
            profile_key="sem_permissao",
        )
        template_user = await _create_user_with_template_ilpi_admin(db)
        db.add_all([ilpi_a, ilpi_b, user_without_link])
        await db.commit()

        no_token = await client.get("/api/instituicoes/")
        assert no_token.status_code == 401

        no_link = await client.get(
            "/api/instituicoes/",
            headers=_auth_headers(user_without_link, scope="ilpi", ilpi_id=ilpi_a.id),
        )
        assert no_link.status_code == 403
        assert _detail_code(no_link) == AUTH_CONTEXT_REQUIRED

        missing_permission = await client.get(
            "/api/instituicoes/",
            headers=_auth_headers(missing_permission_user, scope="ilpi", ilpi_id=ilpi_a.id),
        )
        assert missing_permission.status_code == 403
        assert _detail_code(missing_permission) == PERMISSION_DENIED

        template_direct = await client.get(
            "/api/instituicoes/",
            headers=_auth_headers(template_user, scope="ilpi"),
        )
        assert template_direct.status_code == 403
        assert _detail_code(template_direct) == AUTH_CONTEXT_REQUIRED

        platform_global = await client.get(
            "/api/instituicoes/",
            headers=_auth_headers(platform_user, scope="global"),
        )
        assert platform_global.status_code == 200
        assert {item["id"] for item in platform_global.json()} == {ilpi_a.id, ilpi_b.id}

        platform_as_ilpi = await client.get(
            "/api/instituicoes/",
            headers=_auth_headers(platform_user, scope="ilpi", ilpi_id=ilpi_a.id),
        )
        assert platform_as_ilpi.status_code == 403
        assert _detail_code(platform_as_ilpi) == AUTH_CONTEXT_REQUIRED

        own_ilpi = await client.get(
            f"/api/instituicoes/{ilpi_a.id}",
            headers=_auth_headers(ilpi_admin, scope="ilpi", ilpi_id=ilpi_a.id),
        )
        assert own_ilpi.status_code == 200
        assert own_ilpi.json()["id"] == ilpi_a.id

        listed = await client.get(
            "/api/instituicoes/",
            headers=_auth_headers(ilpi_admin, scope="ilpi", ilpi_id=ilpi_a.id),
        )
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [ilpi_a.id]

        cross_tenant = await client.get(
            f"/api/instituicoes/{ilpi_b.id}",
            headers=_auth_headers(ilpi_admin, scope="ilpi", ilpi_id=ilpi_a.id),
        )
        assert cross_tenant.status_code == 404
        assert _detail_code(cross_tenant) == RESOURCE_NOT_FOUND

        query_switch = await client.get(
            f"/api/instituicoes/{ilpi_b.id}?ilpi_id={ilpi_a.id}",
            headers=_auth_headers(ilpi_admin, scope="ilpi", ilpi_id=ilpi_a.id),
        )
        assert query_switch.status_code == 404
        assert _detail_code(query_switch) == RESOURCE_NOT_FOUND

        payload_switch = await client.put(
            f"/api/instituicoes/{ilpi_b.id}",
            headers=_auth_headers(ilpi_admin, scope="ilpi", ilpi_id=ilpi_a.id),
            json={"razao_social": "Tentativa cross-tenant", "ilpi_id": ilpi_a.id},
        )
        assert payload_switch.status_code == 404
        assert _detail_code(payload_switch) == RESOURCE_NOT_FOUND

        institutional_global_route = await client.post(
            "/api/instituicoes/",
            headers=_auth_headers(ilpi_admin, scope="ilpi", ilpi_id=ilpi_a.id),
            json={"razao_social": "ILPI Nao Criada"},
        )
        assert institutional_global_route.status_code == 403
        assert _detail_code(institutional_global_route) == PERMISSION_DENIED

    asyncio.run(_with_client(endpoint_db, scenario))


def test_clinical_routes_fail_closed_and_health_remains_public(endpoint_db):
    # F5A-2A: Residentes (GET/POST/PUT) usa RBAC real com isolamento de tenant
    # (cobertura em test_fase5a2a_residentes_rbac_tenant.py); aqui permanece
    # apenas o DELETE de residentes, ainda fail-closed (BLOCKED_FOR_F5B).
    # F5A-2B: Familiares (GET/POST/PUT) usa RBAC real com isolamento de tenant
    # + vínculo seguro com Residente (cobertura em
    # test_fase5a2b_familiares_rbac_tenant.py); aqui permanece apenas o
    # DELETE de familiares, ainda fail-closed (BLOCKED_FOR_F5B).
    clinical_list_routes = (
        "/api/medicamentos/",
        "/api/prescricoes/",
        "/api/tarefas/",
        "/api/avaliacoes/",
        "/api/sinais-vitais/",
        "/api/intercorrencias/",
        "/api/alertas/",
    )
    resident_id = _new_id()
    medication_id = _new_id()
    clinical_mutations = (
        # F5A-2A: POST/PUT de residentes liberados via RBAC; DELETE segue fail-closed.
        ("delete", f"/api/residentes/{resident_id}", None),
        # F5A-2B: GET/POST/PUT de familiares liberados via RBAC; DELETE segue fail-closed.
        ("delete", f"/api/familiares/{_new_id()}", None),
        ("post", "/api/medicamentos/", {"nome": "Medicamento"}),
        ("put", f"/api/medicamentos/{medication_id}", {"nome": "Medicamento"}),
        ("delete", f"/api/medicamentos/{medication_id}", None),
        (
            "post",
            "/api/prescricoes/",
            {
                "residente_id": resident_id,
                "medicamento_id": medication_id,
                "prescritor": "Profissional",
                "dose": "1 comprimido",
                "inicio": "2026-01-01",
            },
        ),
        (
            "put",
            f"/api/prescricoes/{_new_id()}",
            {
                "residente_id": resident_id,
                "medicamento_id": medication_id,
                "prescritor": "Profissional",
                "dose": "1 comprimido",
                "inicio": "2026-01-01",
            },
        ),
        ("delete", f"/api/prescricoes/{_new_id()}", None),
        ("post", "/api/tarefas/", {"residente_id": resident_id, "descricao": "Tarefa"}),
        ("put", f"/api/tarefas/{_new_id()}", {"descricao": "Tarefa"}),
        ("delete", f"/api/tarefas/{_new_id()}", None),
        ("post", "/api/avaliacoes/", {"residente_id": resident_id, "tipo": "Katz"}),
        ("post", "/api/sinais-vitais/", {"residente_id": resident_id}),
        ("put", f"/api/sinais-vitais/{_new_id()}", {"residente_id": resident_id}),
        ("delete", f"/api/sinais-vitais/{_new_id()}", None),
        ("post", "/api/intercorrencias/", {"residente_id": resident_id, "tipo": "queda"}),
        ("put", f"/api/intercorrencias/{_new_id()}", {"residente_id": resident_id, "tipo": "queda"}),
        ("delete", f"/api/intercorrencias/{_new_id()}", None),
    )

    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        institution = _new_institution()
        user = await _create_ilpi_user(
            db,
            institution,
            permissions={"ilpis:ler"},
        )
        db.add(institution)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=institution.id)

        health_response = await client.get("/api/health")
        assert health_response.status_code == 200

        for route in clinical_list_routes:
            missing_token = await client.get(route)
            assert missing_token.status_code == 401

            blocked = await client.get(route, headers=headers)
            assert blocked.status_code == 403
            assert _detail_code(blocked) == PERMISSION_CATALOG_PENDING

        for method, route, payload in clinical_mutations:
            request = getattr(client, method)
            kwargs = {"headers": headers}
            if payload is not None:
                kwargs["json"] = payload
            blocked = await request(route, **kwargs)
            assert blocked.status_code == 403
            assert _detail_code(blocked) == PERMISSION_CATALOG_PENDING

        upload_blocked = await client.post(
            f"/api/uploads/{institution.id}",
            headers=headers,
            files={"file": ("segredo.txt", b"nao gravar", "text/plain")},
        )
        assert upload_blocked.status_code == 403
        assert _detail_code(upload_blocked) == PERMISSION_CATALOG_PENDING

        alert_payload_blocked = await client.post(
            "/api/alertas/",
            headers=headers,
            json={
                "instituicao_id": _new_id(),
                "tipo": "payload-tenant-switch",
                "mensagem": "nao criar",
            },
        )
        assert alert_payload_blocked.status_code == 403
        assert _detail_code(alert_payload_blocked) == PERMISSION_CATALOG_PENDING
        assert await _count(db, m.Alerta) == 0

    asyncio.run(_with_client(endpoint_db, scenario))


def test_catalog_admin_routes_were_not_invented_or_mutated(endpoint_db):
    """Administrative routes exist (Fase 3A) but stay protected and immutable.

    The historical contract expected 404 for these routes. The current
    contract is: implemented and guarded. This test proves the current
    property instead of the obsolete absence: unauthenticated reads are 401,
    out-of-scope or ungranted attempts are 403 with the guard's code,
    never-invented routes stay 404, and no attempt mutates the catalog.
    """
    still_absent_routes = (
        "/api/configuracoes/",
        "/api/auditoria/",
    )

    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        platform_user = await _create_platform_user(db)
        await db.commit()
        headers = _auth_headers(platform_user, scope="global")
        catalog_before = {
            "permissoes": await _count(db, m.Permissao),
            "perfis": await _count(db, m.Perfil),
            "perfil_permissoes": await _count(db, m.PerfilPermissao),
            "users": await _count(db, m.User),
            "funcionarios": await _count(db, m.Funcionario),
        }

        no_token_usuarios = await client.get("/api/usuarios/")
        assert no_token_usuarios.status_code == 401
        no_token_funcionarios = await client.get("/api/funcionarios/")
        assert no_token_funcionarios.status_code == 401

        usuarios = await client.get("/api/usuarios/", headers=headers)
        assert usuarios.status_code == 403
        assert _detail_code(usuarios) == ILPI_CONTEXT_REQUIRED

        funcionarios = await client.get("/api/funcionarios/", headers=headers)
        assert funcionarios.status_code == 403
        assert _detail_code(funcionarios) == PERMISSION_DENIED

        perfis = await client.get("/api/perfis/", headers=headers)
        assert perfis.status_code == 403
        assert _detail_code(perfis) == ILPI_CONTEXT_REQUIRED

        permissoes = await client.get("/api/permissoes/", headers=headers)
        assert permissoes.status_code == 200
        assert any(item["chave"] == "residentes:ler" for item in permissoes.json())

        create_user = await client.post(
            "/api/usuarios/",
            headers=headers,
            json={"nome": "Nao Criar", "email": "nao-criar-admin@example.com"},
        )
        assert create_user.status_code == 403
        assert _detail_code(create_user) == ILPI_CONTEXT_REQUIRED

        create_employee = await client.post(
            "/api/funcionarios/",
            headers=headers,
            json={"nome": "Nao Criar"},
        )
        assert create_employee.status_code == 403
        assert _detail_code(create_employee) == PERMISSION_DENIED

        for route in still_absent_routes:
            read_response = await client.get(route, headers=headers)
            assert read_response.status_code == 404

            mutate_response = await client.post(route, headers=headers, json={"nome": "mutacao"})
            assert mutate_response.status_code == 404

        update_permission = await client.put(
            "/api/permissoes/fac11000-0000-4000-8000-000000000001",
            headers=headers,
            json={"chave": "mutada"},
        )
        assert update_permission.status_code == 404
        delete_profile = await client.delete(
            "/api/perfis/fac10000-0000-4000-8000-000000000001",
            headers=headers,
        )
        assert delete_profile.status_code == 404

        assert catalog_before == {
            "permissoes": await _count(db, m.Permissao),
            "perfis": await _count(db, m.Perfil),
            "perfil_permissoes": await _count(db, m.PerfilPermissao),
            "users": await _count(db, m.User),
            "funcionarios": await _count(db, m.Funcionario),
        }

    asyncio.run(_with_client(endpoint_db, scenario))


def test_denial_logs_do_not_include_secrets(endpoint_db, caplog):
    caplog.set_level(logging.WARNING, logger="facilpi.security")
    secret_password = "SenhaSuperSecreta123"
    secret_token = "token-secreto-que-nao-pode-vazar"
    secret_payload = "dado-clinico-sensivel"

    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        institution = _new_institution()
        user = await _create_ilpi_user(db, institution, permissions=set())
        db.add(institution)
        await db.commit()

        await client.get(
            "/api/instituicoes/",
            headers={"Authorization": f"Bearer {secret_token}", "X-Scope": "global"},
        )
        await client.get(
            "/api/instituicoes/",
            headers=_auth_headers(user, scope="ilpi", ilpi_id=institution.id),
        )
        await client.post(
            "/api/auth/register",
            json={
                "nome": secret_payload,
                "email": "segredo@example.com",
                "password": secret_password,
            },
        )

    asyncio.run(_with_client(endpoint_db, scenario))
    output = caplog.text
    for sensitive_value in (secret_password, secret_token, secret_payload):
        assert sensitive_value not in output
    assert "authentication_denied" in output
    assert "authorization_denied" in output
