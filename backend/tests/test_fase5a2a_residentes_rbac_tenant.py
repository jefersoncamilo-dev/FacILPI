"""Disposable-database tests for Phase F5A-2A: Residentes RBAC + tenant isolation.

Covers:
- GET /api/residentes/      -> residentes:ler   (tenant-filtered list)
- GET /api/residentes/{id}  -> residentes:ler   (404 cross-tenant, no leak)
- POST /api/residentes/     -> residentes:criar (tenant from session, hostile body ignored)
- PUT /api/residentes/{id}  -> residentes:atualizar (no tenant move)
- DELETE /api/residentes/.. -> BLOCKED_FOR_F5B_LOGICAL_DELETE (fail-closed, physical delete never runs)

All databases are disposable (tmp sqlite / disposable postgres). The official
database (storage/app.db) is never written.
"""

from __future__ import annotations

import asyncio
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
from src.application.auth import create_access_token  # noqa: E402
from src.application.security import (  # noqa: E402
    AUTHENTICATION_REQUIRED,
    FIRST_PASSWORD_CHANGE_REQUIRED,
    PERMISSION_CATALOG_PENDING,
    PERMISSION_DENIED,
    RESOURCE_NOT_FOUND,
)
from src.infrastructure import database  # noqa: E402
from src.infrastructure import models as m  # noqa: E402


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
        assert database_ref.resolve() != OFFICIAL_DB.resolve(), "must never write the official database"
    else:
        assert "storage/app.db" not in database_ref, "must never write the official database"


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
    if os.getenv("FASE3A_TEST_POSTGRES_URL"):
        backends.append("postgresql")
    return backends


@pytest.fixture(params=_database_backends(), ids=lambda backend: backend)
def residentes_db(request: pytest.FixtureRequest, tmp_path: pathlib.Path) -> pathlib.Path | str:
    if request.param == "sqlite":
        path = tmp_path / "fase5a2a-residentes.db"
        _run_migration(path)
        return path

    url = os.environ["FASE3A_TEST_POSTGRES_URL"]
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


def _new_user(*, exige_troca_senha: bool = False) -> m.User:
    user_id = _new_id()
    return m.User(
        id=user_id,
        nome="Usuario Fase 5A-2A",
        email=f"fase5a2a-{user_id}@example.com",
        password_hash="fixture-password-hash",
        ativo=True,
        exige_troca_senha=exige_troca_senha,
    )


def _new_institution(name: str = "ILPI Fase 5A-2A") -> m.Instituicao:
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


async def _create_ilpi_user(
    db: AsyncSession,
    institution: m.Instituicao,
    *,
    permissions: set[str],
    profile_key: str = "cuidador",
    exige_troca_senha: bool = False,
) -> m.User:
    """ILPI user with profile + link + active Funcionario (required for ILPI context)."""
    user = _new_user(exige_troca_senha=exige_troca_senha)
    profile = m.Perfil(
        id=_new_id(),
        ilpi_id=institution.id,
        nome="Perfil Fixture 5A-2A",
        chave=profile_key,
        escopo="ilpi",
        situacao="ativo",
    )
    employee = m.Funcionario(
        id=_new_id(),
        ilpi_id=institution.id,
        usuario_id=user.id,
        nome=user.nome,
        email=user.email,
        cargo="Cuidador",
        situacao="ativo",
    )
    db.add_all(
        [
            institution,
            user,
            profile,
            employee,
            _new_link(user.id, profile.id, institution.id),
        ]
    )
    await db.flush()
    await _grant_permissions(db, profile.id, permissions)
    return user


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
    return (await db.execute(select(func.count()).select_from(model))).scalar_one()


def _residente_payload(nome: str = "Residente Fixture") -> dict:
    return {"nome": nome, "data_nascimento": "1940-05-01"}


def test_residentes_rbac_tenant_endpoints(residentes_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi_a = _new_institution("ILPI A 5A-2A")
        ilpi_b = _new_institution("ILPI B 5A-2A")
        platform_user = await _create_platform_user(db)
        reader = await _create_ilpi_user(
            db, ilpi_a, permissions={"residentes:ler"}, profile_key="leitor"
        )
        writer = await _create_ilpi_user(
            db,
            ilpi_a,
            permissions={"residentes:ler", "residentes:criar", "residentes:atualizar"},
            profile_key="cuidador",
        )
        no_permission = await _create_ilpi_user(
            db, ilpi_a, permissions=set(), profile_key="sem_permissao"
        )
        other_tenant = await _create_ilpi_user(
            db,
            ilpi_b,
            permissions={"residentes:ler", "residentes:criar", "residentes:atualizar"},
            profile_key="cuidador_b",
        )
        pending_first_access = await _create_ilpi_user(
            db,
            ilpi_a,
            permissions={"residentes:ler", "residentes:criar", "residentes:atualizar"},
            profile_key="primeiro_acesso",
            exige_troca_senha=True,
        )
        db.add(ilpi_b)
        await db.commit()

        headers_reader = _auth_headers(reader, scope="ilpi", ilpi_id=ilpi_a.id)
        headers_writer = _auth_headers(writer, scope="ilpi", ilpi_id=ilpi_a.id)
        headers_none = _auth_headers(no_permission, scope="ilpi", ilpi_id=ilpi_a.id)
        headers_b = _auth_headers(other_tenant, scope="ilpi", ilpi_id=ilpi_b.id)
        headers_pending = _auth_headers(pending_first_access, scope="ilpi", ilpi_id=ilpi_a.id)
        headers_global = _auth_headers(platform_user, scope="global")

        # 19. Health continua pública.
        health = await client.get("/api/health")
        assert health.status_code == 200

        # 01. GET LIST sem token -> 401 AUTHENTICATION_REQUIRED.
        no_token = await client.get("/api/residentes/")
        assert no_token.status_code == 401
        assert _detail_code(no_token) == AUTHENTICATION_REQUIRED

        # 02. GET LIST contexto global -> 403 PERMISSION_DENIED.
        global_list = await client.get("/api/residentes/", headers=headers_global)
        assert global_list.status_code == 403
        assert _detail_code(global_list) == PERMISSION_DENIED

        # 03. GET LIST ILPI sem residentes:ler -> 403 PERMISSION_DENIED.
        denied = await client.get("/api/residentes/", headers=headers_none)
        assert denied.status_code == 403
        assert _detail_code(denied) == PERMISSION_DENIED

        # Seed: um residente em cada ILPI (viaSesion A e sessão B).
        created_a1 = await client.post(
            "/api/residentes/", headers=headers_writer, json=_residente_payload("Residente A1")
        )
        assert created_a1.status_code == 201, created_a1.text
        a1_id = created_a1.json()["id"]
        assert created_a1.json()["instituicao_id"] == ilpi_a.id

        created_b1 = await client.post(
            "/api/residentes/", headers=headers_b, json=_residente_payload("Residente B1")
        )
        assert created_b1.status_code == 201, created_b1.text
        b1_id = created_b1.json()["id"]
        assert created_b1.json()["instituicao_id"] == ilpi_b.id

        # 04. GET LIST ILPI com residentes:ler -> 200.
        listed = await client.get("/api/residentes/", headers=headers_reader)
        assert listed.status_code == 200

        # 05. Isolamento de listagem: A vê só A1+A2... (A1 + criado abaixo), nunca B1.
        ids_a = {item["id"] for item in listed.json()}
        assert a1_id in ids_a
        assert b1_id not in ids_a
        assert all(item["instituicao_id"] == ilpi_a.id for item in listed.json())

        listed_b = await client.get("/api/residentes/", headers=headers_b)
        assert listed_b.status_code == 200
        ids_b = {item["id"] for item in listed_b.json()}
        assert b1_id in ids_b
        assert a1_id not in ids_b

        # 06. GET ID mesmo tenant -> 200.
        got = await client.get(f"/api/residentes/{a1_id}", headers=headers_reader)
        assert got.status_code == 200
        assert got.json()["id"] == a1_id

        # 07. GET ID cross-tenant -> 404 RESOURCE_NOT_FOUND (sem vazar existência).
        cross = await client.get(f"/api/residentes/{b1_id}", headers=headers_reader)
        assert cross.status_code == 404
        assert _detail_code(cross) == RESOURCE_NOT_FOUND

        # 08. GET ID inexistente -> 404 RESOURCE_NOT_FOUND.
        missing = await client.get(f"/api/residentes/{_new_id()}", headers=headers_reader)
        assert missing.status_code == 404
        assert _detail_code(missing) == RESOURCE_NOT_FOUND

        # 09. CREATE com residentes:criar -> 201 no tenant da sessão.
        created_a2 = await client.post(
            "/api/residentes/", headers=headers_writer, json=_residente_payload("Residente A2")
        )
        assert created_a2.status_code == 201, created_a2.text
        assert created_a2.json()["instituicao_id"] == ilpi_a.id
        a2_id = created_a2.json()["id"]

        # 10. CREATE sem residentes:criar -> 403 PERMISSION_DENIED (nada persistido).
        before = await _count(db, m.Residente)
        forbidden_create = await client.post(
            "/api/residentes/", headers=headers_none, json=_residente_payload("Nao Criar")
        )
        assert forbidden_create.status_code == 403
        assert _detail_code(forbidden_create) == PERMISSION_DENIED
        assert await _count(db, m.Residente) == before

        # 11. CREATE com payload hostil (instituicao_id de outra ILPI) -> persiste na ILPI da sessão.
        hostile = await client.post(
            "/api/residentes/",
            headers=headers_writer,
            json={**_residente_payload("Residente Hostil"), "instituicao_id": ilpi_b.id},
        )
        assert hostile.status_code == 201, hostile.text
        assert hostile.json()["instituicao_id"] == ilpi_a.id
        hostile_id = hostile.json()["id"]
        hostile_b = await client.get(f"/api/residentes/{hostile_id}", headers=headers_b)
        assert hostile_b.status_code == 404
        assert _detail_code(hostile_b) == RESOURCE_NOT_FOUND

        # 12. UPDATE com residentes:atualizar no mesmo tenant -> 200.
        updated = await client.put(
            f"/api/residentes/{a2_id}",
            headers=headers_writer,
            json={"nome": "Residente A2 Atualizado"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["nome"] == "Residente A2 Atualizado"
        assert updated.json()["instituicao_id"] == ilpi_a.id

        # 13. UPDATE sem residentes:atualizar -> 403 PERMISSION_DENIED.
        forbidden_update = await client.put(
            f"/api/residentes/{a2_id}",
            headers=headers_none,
            json={"nome": "Nao Atualizar"},
        )
        assert forbidden_update.status_code == 403
        assert _detail_code(forbidden_update) == PERMISSION_DENIED

        # 14. UPDATE cross-tenant -> 404 RESOURCE_NOT_FOUND.
        cross_update = await client.put(
            f"/api/residentes/{b1_id}",
            headers=headers_writer,
            json={"nome": "Tentativa Cross Tenant"},
        )
        assert cross_update.status_code == 404
        assert _detail_code(cross_update) == RESOURCE_NOT_FOUND
        intact_b = await client.get(f"/api/residentes/{b1_id}", headers=headers_b)
        assert intact_b.json()["nome"] == "Residente B1"

        # 15. UPDATE tentando trocar instituicao_id -> tenant permanece inalterado.
        move_attempt = await client.put(
            f"/api/residentes/{a2_id}",
            headers=headers_writer,
            json={"nome": "Residente A2", "instituicao_id": ilpi_b.id},
        )
        assert move_attempt.status_code == 200, move_attempt.text
        assert move_attempt.json()["instituicao_id"] == ilpi_a.id
        confirm = await client.get(f"/api/residentes/{a2_id}", headers=headers_reader)
        assert confirm.json()["instituicao_id"] == ilpi_a.id

        # 16. Primeiro acesso pendente -> 403 FIRST_PASSWORD_CHANGE_REQUIRED.
        pending = await client.get("/api/residentes/", headers=headers_pending)
        assert pending.status_code == 403
        assert _detail_code(pending) == FIRST_PASSWORD_CHANGE_REQUIRED
        pending_create = await client.post(
            "/api/residentes/", headers=headers_pending, json=_residente_payload("Bloqueado")
        )
        assert pending_create.status_code == 403
        assert _detail_code(pending_create) == FIRST_PASSWORD_CHANGE_REQUIRED

        # 17. Platform superuser sem acesso clínico (global já coberto no item 02;
        # aqui também com tentativa de leitura por id e escrita).
        global_get = await client.get(f"/api/residentes/{a1_id}", headers=headers_global)
        assert global_get.status_code == 403
        assert _detail_code(global_get) == PERMISSION_DENIED
        global_create = await client.post(
            "/api/residentes/", headers=headers_global, json=_residente_payload("Superuser")
        )
        assert global_create.status_code == 403
        assert _detail_code(global_create) == PERMISSION_DENIED

        # 18. DELETE continua bloqueado (fail-closed): 403 e nenhuma deleção física.
        total_before_delete = await _count(db, m.Residente)
        for headers in (headers_writer, headers_b, headers_global):
            blocked = await client.delete(f"/api/residentes/{a1_id}", headers=headers)
            assert blocked.status_code == 403
            assert _detail_code(blocked) in {PERMISSION_CATALOG_PENDING, PERMISSION_DENIED}
        assert await _count(db, m.Residente) == total_before_delete
        still_there = await client.get(f"/api/residentes/{a1_id}", headers=headers_reader)
        assert still_there.status_code == 200

        # DELETE sem token -> 401.
        delete_no_token = await client.delete(f"/api/residentes/{a1_id}")
        assert delete_no_token.status_code == 401

    asyncio.run(_with_client(residentes_db, scenario))


def test_outros_modulos_clinicos_permanecem_fail_closed(residentes_db):
    """F5A-2A libera SOMENTE Residentes; demais módulos seguem fail-closed (20)."""

    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution("ILPI Fail-closed 5A-2A")
        user = await _create_ilpi_user(
            db,
            ilpi,
            permissions={"residentes:ler", "residentes:criar", "residentes:atualizar"},
            profile_key="cuidador_fc",
        )
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)

        still_blocked = (
            ("get", "/api/familiares/", None),
            ("post", "/api/familiares/", {"residente_id": _new_id(), "nome": "X"}),
            ("get", "/api/tarefas/", None),
            ("post", "/api/tarefas/", {"residente_id": _new_id(), "descricao": "X"}),
            ("get", "/api/sinais-vitais/", None),
            ("post", "/api/sinais-vitais/", {"residente_id": _new_id()}),
            ("get", "/api/medicamentos/", None),
            ("get", "/api/avaliacoes/", None),
            ("get", "/api/intercorrencias/", None),
            ("get", "/api/alertas/", None),
        )
        for method, route, payload in still_blocked:
            request = getattr(client, method)
            kwargs = {"headers": headers}
            if payload is not None:
                kwargs["json"] = payload
            response = await request(route, **kwargs)
            assert response.status_code == 403, (method, route, response.text)
            detail = response.json().get("detail")
            assert isinstance(detail, dict), (method, route, response.text)
            assert detail.get("code") == PERMISSION_CATALOG_PENDING, (method, route, response.text)

    asyncio.run(_with_client(residentes_db, scenario))
