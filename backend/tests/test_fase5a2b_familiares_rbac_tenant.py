"""Disposable-database tests for Phase F5A-2B: Familiares RBAC + tenant isolation.

Covers:
- GET /api/familiares/      -> familiares:ler   (tenant-filtered list)
- GET /api/familiares/{id}  -> familiares:ler   (404 cross-tenant, no leak)
- POST /api/familiares/     -> familiares:criar (tenant from session, hostile
  body ignored, parent Residente validated in the session ILPI before INSERT)
- PUT /api/familiares/{id}  -> familiares:atualizar (no tenant move,
  residente_id immutable by official decision)
- DELETE /api/familiares/.. -> BLOCKED_FOR_F5B_LOGICAL_DELETE (fail-closed,
  physical delete never runs; familiares:inativar does NOT authorize it)

Official decisions encoded here:
- residente_id is IMMUTABLE on PUT (silently ignored, link preserved).
- FamiliarResponse intentionally exposes no ilpi_id; tenant assertions for
  hostile payloads (09/14) read the disposable database directly.

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
from datetime import date, datetime, timedelta, timezone

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
def familiares_db(request: pytest.FixtureRequest, tmp_path: pathlib.Path) -> pathlib.Path | str:
    if request.param == "sqlite":
        path = tmp_path / "fase5a2b-familiares.db"
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
        nome="Usuario Fase 5A-2B",
        email=f"fase5a2b-{user_id}@example.com",
        password_hash="fixture-password-hash",
        ativo=True,
        exige_troca_senha=exige_troca_senha,
    )


def _new_institution(name: str = "ILPI Fase 5A-2B") -> m.Instituicao:
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
    """ILPI user with profile + link + active Funcionario (required for ILPI context).

    Rows are flushed in FK dependency order (roots, then profile, then
    link/employee) because PostgreSQL enforces FK constraints immediately
    while the models declare no ORM relationships for the unit of work to
    sort by.
    """
    user = _new_user(exige_troca_senha=exige_troca_senha)
    profile = m.Perfil(
        id=_new_id(),
        ilpi_id=institution.id,
        nome="Perfil Fixture 5A-2B",
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
        cargo="Cuidador",
        situacao="ativo",
    )
    db.add_all([employee, _new_link(user.id, profile.id, institution.id)])
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
    db.add(user)
    await db.flush()
    db.add(_new_link(user.id, profile.id, None))
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


async def _familiar_row(db: AsyncSession, familiar_id: str) -> m.Familiar | None:
    # Fresh read: populate_existing refreshes the identity-mapped row that
    # the API mutated via another session (expire_all would expire unrelated
    # fixtures and break async lazy-load).
    result = await db.execute(
        select(m.Familiar)
        .where(m.Familiar.id == familiar_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()


def _familiar_payload(residente_id: str, nome: str = "Familiar Fixture") -> dict:
    return {"residente_id": residente_id, "nome": nome}


def test_familiares_rbac_tenant_endpoints(familiares_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi_a = _new_institution("ILPI A 5A-2B")
        ilpi_b = _new_institution("ILPI B 5A-2B")
        db.add_all([ilpi_a, ilpi_b])
        await db.flush()
        # Parent residentes, one per tenant (FK roots for the composite
        # (residente_id, ilpi_id) constraint; flushed before children).
        res_a = m.Residente(
            id=_new_id(),
            instituicao_id=ilpi_a.id,
            nome="Residente A 5A-2B",
            data_nascimento=date(1940, 5, 1),
        )
        res_b = m.Residente(
            id=_new_id(),
            instituicao_id=ilpi_b.id,
            nome="Residente B 5A-2B",
            data_nascimento=date(1938, 3, 2),
        )
        db.add_all([res_a, res_b])
        await db.flush()

        platform_user = await _create_platform_user(db)
        reader = await _create_ilpi_user(
            db, ilpi_a, permissions={"familiares:ler"}, profile_key="leitor_fam"
        )
        writer = await _create_ilpi_user(
            db,
            ilpi_a,
            permissions={"familiares:ler", "familiares:criar", "familiares:atualizar"},
            profile_key="cuidador_fam",
        )
        no_permission = await _create_ilpi_user(
            db, ilpi_a, permissions=set(), profile_key="sem_permissao_fam"
        )
        inativar_only = await _create_ilpi_user(
            db,
            ilpi_a,
            permissions={"familiares:ler", "familiares:inativar"},
            profile_key="inativador_fam",
        )
        other_tenant = await _create_ilpi_user(
            db,
            ilpi_b,
            permissions={"familiares:ler", "familiares:criar", "familiares:atualizar"},
            profile_key="cuidador_fam_b",
        )
        pending_first_access = await _create_ilpi_user(
            db,
            ilpi_a,
            permissions={"familiares:ler", "familiares:criar", "familiares:atualizar"},
            profile_key="primeiro_acesso_fam",
            exige_troca_senha=True,
        )
        await db.commit()

        headers_reader = _auth_headers(reader, scope="ilpi", ilpi_id=ilpi_a.id)
        headers_writer = _auth_headers(writer, scope="ilpi", ilpi_id=ilpi_a.id)
        headers_none = _auth_headers(no_permission, scope="ilpi", ilpi_id=ilpi_a.id)
        headers_inativar = _auth_headers(inativar_only, scope="ilpi", ilpi_id=ilpi_a.id)
        headers_b = _auth_headers(other_tenant, scope="ilpi", ilpi_id=ilpi_b.id)
        headers_pending = _auth_headers(pending_first_access, scope="ilpi", ilpi_id=ilpi_a.id)
        headers_global = _auth_headers(platform_user, scope="global")

        # Seed: um familiar em cada ILPI.
        created_a1 = await client.post(
            "/api/familiares/", headers=headers_writer, json=_familiar_payload(res_a.id, "Familiar A1")
        )
        assert created_a1.status_code == 201, created_a1.text
        a1_id = created_a1.json()["id"]
        assert created_a1.json()["residente_id"] == res_a.id

        created_b1 = await client.post(
            "/api/familiares/", headers=headers_b, json=_familiar_payload(res_b.id, "Familiar B1")
        )
        assert created_b1.status_code == 201, created_b1.text
        b1_id = created_b1.json()["id"]

        # 01. sem token -> 401.
        no_token = await client.get("/api/familiares/")
        assert no_token.status_code == 401
        assert _detail_code(no_token) == AUTHENTICATION_REQUIRED

        # 02. usuário com familiares:ler lista a própria ILPI -> 200.
        listed = await client.get("/api/familiares/", headers=headers_reader)
        assert listed.status_code == 200, listed.text

        # 03. sem familiares:ler -> 403 PERMISSION_DENIED.
        denied = await client.get("/api/familiares/", headers=headers_none)
        assert denied.status_code == 403
        assert _detail_code(denied) == PERMISSION_DENIED

        # 04. listagem A não contém B (isolamento).
        ids_a = {item["id"] for item in listed.json()}
        assert a1_id in ids_a
        assert b1_id not in ids_a
        listed_b = await client.get("/api/familiares/", headers=headers_b)
        assert listed_b.status_code == 200
        ids_b = {item["id"] for item in listed_b.json()}
        assert b1_id in ids_b
        assert a1_id not in ids_b

        # 05. GET próprio -> 200.
        got = await client.get(f"/api/familiares/{a1_id}", headers=headers_reader)
        assert got.status_code == 200
        assert got.json()["id"] == a1_id

        # 06. GET cross-tenant -> 404 RESOURCE_NOT_FOUND (sem leak).
        cross = await client.get(f"/api/familiares/{b1_id}", headers=headers_reader)
        assert cross.status_code == 404
        assert _detail_code(cross) == RESOURCE_NOT_FOUND

        # 07. POST com familiares:criar -> 201.
        created_a2 = await client.post(
            "/api/familiares/", headers=headers_writer, json=_familiar_payload(res_a.id, "Familiar A2")
        )
        assert created_a2.status_code == 201, created_a2.text
        a2_id = created_a2.json()["id"]
        row_a2 = await _familiar_row(db, a2_id)
        assert row_a2 is not None and row_a2.ilpi_id == ilpi_a.id

        # 08. POST sem permissão -> 403 PERMISSION_DENIED (nada persistido).
        before = await _count(db, m.Familiar)
        forbidden_create = await client.post(
            "/api/familiares/", headers=headers_none, json=_familiar_payload(res_a.id, "Nao Criar")
        )
        assert forbidden_create.status_code == 403
        assert _detail_code(forbidden_create) == PERMISSION_DENIED
        assert await _count(db, m.Familiar) == before

        # 09. POST com ilpi_id/instituicao_id hostil -> tenant final continua A.
        hostile = await client.post(
            "/api/familiares/",
            headers=headers_writer,
            json={**_familiar_payload(res_a.id, "Familiar Hostil"), "ilpi_id": ilpi_b.id, "instituicao_id": ilpi_b.id},
        )
        assert hostile.status_code == 201, hostile.text
        hostile_id = hostile.json()["id"]
        hostile_row = await _familiar_row(db, hostile_id)
        assert hostile_row is not None
        assert hostile_row.ilpi_id == ilpi_a.id
        hostile_cross = await client.get(f"/api/familiares/{hostile_id}", headers=headers_b)
        assert hostile_cross.status_code == 404
        assert _detail_code(hostile_cross) == RESOURCE_NOT_FOUND

        # 10. POST com residente da outra ILPI -> 404 fail-closed (nada persistido).
        before_parent = await _count(db, m.Familiar)
        cross_parent = await client.post(
            "/api/familiares/", headers=headers_writer, json=_familiar_payload(res_b.id, "Vinculo Cross")
        )
        assert cross_parent.status_code == 404
        assert _detail_code(cross_parent) == RESOURCE_NOT_FOUND
        assert await _count(db, m.Familiar) == before_parent

        # 11. PUT com familiares:atualizar -> 200.
        updated = await client.put(
            f"/api/familiares/{a2_id}",
            headers=headers_writer,
            json={"nome": "Familiar A2 Atualizado"},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["nome"] == "Familiar A2 Atualizado"

        # 12. PUT sem permissão -> 403 PERMISSION_DENIED.
        forbidden_update = await client.put(
            f"/api/familiares/{a2_id}",
            headers=headers_none,
            json={"nome": "Nao Atualizar"},
        )
        assert forbidden_update.status_code == 403
        assert _detail_code(forbidden_update) == PERMISSION_DENIED

        # 13. PUT cross-tenant -> 404 RESOURCE_NOT_FOUND (alvo intacto).
        cross_update = await client.put(
            f"/api/familiares/{b1_id}",
            headers=headers_writer,
            json={"nome": "Tentativa Cross Tenant"},
        )
        assert cross_update.status_code == 404
        assert _detail_code(cross_update) == RESOURCE_NOT_FOUND
        intact_b = await client.get(f"/api/familiares/{b1_id}", headers=headers_b)
        assert intact_b.json()["nome"] == "Familiar B1"

        # 14. PUT tentando trocar tenant -> tenant preservado (leitura direta no banco).
        move_attempt = await client.put(
            f"/api/familiares/{a2_id}",
            headers=headers_writer,
            json={"nome": "Familiar A2", "ilpi_id": ilpi_b.id, "instituicao_id": ilpi_b.id},
        )
        assert move_attempt.status_code == 200, move_attempt.text
        moved_row = await _familiar_row(db, a2_id)
        assert moved_row is not None and moved_row.ilpi_id == ilpi_a.id
        assert moved_row.residente_id == res_a.id

        # 15. PUT com residente_id de outra ILPI -> vínculo imutável (200, original preservado).
        transfer_attempt = await client.put(
            f"/api/familiares/{a2_id}",
            headers=headers_writer,
            json={"residente_id": res_b.id},
        )
        assert transfer_attempt.status_code == 200, transfer_attempt.text
        transfer_row = await _familiar_row(db, a2_id)
        assert transfer_row is not None and transfer_row.residente_id == res_a.id
        assert transfer_row.ilpi_id == ilpi_a.id

        # 16. Primeiro acesso pendente -> 403 FIRST_PASSWORD_CHANGE_REQUIRED.
        pending = await client.get("/api/familiares/", headers=headers_pending)
        assert pending.status_code == 403
        assert _detail_code(pending) == FIRST_PASSWORD_CHANGE_REQUIRED
        pending_create = await client.post(
            "/api/familiares/", headers=headers_pending, json=_familiar_payload(res_a.id, "Bloqueado")
        )
        assert pending_create.status_code == 403
        assert _detail_code(pending_create) == FIRST_PASSWORD_CHANGE_REQUIRED

        # 17. platform_superuser global -> sem acesso clínico.
        global_list = await client.get("/api/familiares/", headers=headers_global)
        assert global_list.status_code == 403
        assert _detail_code(global_list) == PERMISSION_DENIED
        global_get = await client.get(f"/api/familiares/{a1_id}", headers=headers_global)
        assert global_get.status_code == 403
        assert _detail_code(global_get) == PERMISSION_DENIED
        global_create = await client.post(
            "/api/familiares/", headers=headers_global, json=_familiar_payload(res_a.id, "Superuser")
        )
        assert global_create.status_code == 403
        assert _detail_code(global_create) == PERMISSION_DENIED

        # 18. DELETE com familiares:inativar continua bloqueado (físico nunca liberado).
        total_before_delete = await _count(db, m.Familiar)
        for headers in (headers_writer, headers_inativar, headers_b, headers_global):
            blocked = await client.delete(f"/api/familiares/{a1_id}", headers=headers)
            assert blocked.status_code == 403, blocked.text
            assert _detail_code(blocked) in {PERMISSION_CATALOG_PENDING, PERMISSION_DENIED}
        # familiares:inativar também não concede escrita.
        inativar_create = await client.post(
            "/api/familiares/", headers=headers_inativar, json=_familiar_payload(res_a.id, "Sem Criar")
        )
        assert inativar_create.status_code == 403
        assert _detail_code(inativar_create) == PERMISSION_DENIED

        # 19. Registro permanece após DELETE bloqueado.
        assert await _count(db, m.Familiar) == total_before_delete
        still_there = await client.get(f"/api/familiares/{a1_id}", headers=headers_reader)
        assert still_there.status_code == 200

        # DELETE sem token -> 401.
        delete_no_token = await client.delete(f"/api/familiares/{a1_id}")
        assert delete_no_token.status_code == 401

    asyncio.run(_with_client(familiares_db, scenario))


def test_outros_modulos_clinicos_permanecem_fail_closed(familiares_db):
    """F5A-2B libera SOMENTE Familiares (+Residentes da 2A); demais seguem fail-closed (20)."""

    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution("ILPI Fail-closed 5A-2B")
        user = await _create_ilpi_user(
            db,
            ilpi,
            permissions={"familiares:ler", "familiares:criar", "familiares:atualizar"},
            profile_key="cuidador_fc_fam",
        )
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)

        still_blocked = (
            ("get", "/api/medicamentos/", None),
            ("get", "/api/tarefas/", None),
            ("post", "/api/tarefas/", {"residente_id": _new_id(), "descricao": "X"}),
            ("post", "/api/prescricoes/", {"residente_id": _new_id(), "medicamento_id": _new_id(), "prescritor": "X", "dose": "1", "inicio": "2026-01-01"}),
            ("get", "/api/sinais-vitais/", None),
            ("post", "/api/sinais-vitais/", {"residente_id": _new_id()}),
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

        # Residentes segue protegido por RBAC próprio (sem wildcard via familiares).
        residentes_denied = await client.get("/api/residentes/", headers=headers)
        assert residentes_denied.status_code == 403
        assert _detail_code(residentes_denied) == PERMISSION_DENIED

    asyncio.run(_with_client(familiares_db, scenario))
