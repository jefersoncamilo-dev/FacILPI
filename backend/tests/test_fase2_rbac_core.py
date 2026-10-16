"""Disposable-database tests for the Phase 2B RBAC core."""

from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool


ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
OFFICIAL_DB = ROOT / "storage" / "app.db"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from src.application.auth import (  # noqa: E402
    AUTHENTICATION_REQUIRED,
    JWT_ALGORITHM,
    JWT_SECRET,
    get_current_user,
)
from src.application.security import (  # noqa: E402
    AUTH_CONTEXT_REQUIRED,
    GLOBAL_SCOPE_REQUIRED,
    ILPI_CONTEXT_REQUIRED,
    PERMISSION_DENIED,
    PROFILE_SELECTION_REQUIRED,
    RESOURCE_NOT_FOUND,
    SecurityContext,
    build_security_context,
    ensure_same_tenant,
    get_security_context,
    load_security_context,
    require_global_scope,
    require_ilpi_context,
    require_permission,
)
from src.infrastructure.models import (  # noqa: E402
    Funcionario,
    Instituicao,
    Perfil,
    PerfilPermissao,
    Permissao,
    User,
    UsuarioIlpiPerfil,
)


def _sqlite_url(path: pathlib.Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def _async_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


def _database_url(database: pathlib.Path | str) -> str:
    if isinstance(database, pathlib.Path):
        return _sqlite_url(database)
    return _async_url(database)


def _run_migration(database: pathlib.Path | str) -> None:
    url = _database_url(database)
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
def rbac_db(
    request: pytest.FixtureRequest,
    tmp_path: pathlib.Path,
) -> pathlib.Path | str:
    if request.param == "sqlite":
        path = tmp_path / "fase2b-rbac.db"
        assert path.resolve() != OFFICIAL_DB.resolve()
        _run_migration(path)
        return path

    url = os.environ["FASE2_TEST_POSTGRES_URL"]
    try:
        asyncio.run(_reset_postgres(url))
        _run_migration(url)
    except Exception as error:
        pytest.skip(f"PostgreSQL descartável indisponível: {error}")
    return url


async def _with_session(database: pathlib.Path | str, operation):
    engine = create_async_engine(_database_url(database), poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as session:
            return await operation(session)
    finally:
        await engine.dispose()


def _new_id() -> str:
    return str(uuid.uuid4())


def _new_user(*, active: bool = True) -> User:
    user_id = _new_id()
    return User(
        id=user_id,
        nome="RBAC User",
        email=f"rbac-{user_id}@example.test",
        password_hash="fixture-password-hash",
        ativo=active,
    )


def _new_institution(ilpi_id: str | None = None) -> Instituicao:
    return Instituicao(
        id=ilpi_id or _new_id(),
        razao_social="ILPI Fixture",
        situacao="ILPI_RASCUNHO",
    )


def _new_profile(ilpi_id: str, *, active: bool = True, key: str | None = None) -> Perfil:
    profile_id = _new_id()
    return Perfil(
        id=profile_id,
        ilpi_id=ilpi_id,
        nome="Fixture profile",
        chave=key or f"fixture_profile_{profile_id[:8]}",
        escopo="ilpi",
        situacao="ativo" if active else "inativo",
    )


def _new_link(
    user_id: str,
    profile_id: str,
    ilpi_id: str | None,
    *,
    active: bool = True,
) -> UsuarioIlpiPerfil:
    return UsuarioIlpiPerfil(
        id=_new_id(),
        usuario_id=user_id,
        ilpi_id=ilpi_id,
        perfil_id=profile_id,
        situacao="ativo" if active else "inativo",
        data_inicial=datetime.now(timezone.utc) - timedelta(minutes=1),
    )


async def _institution_context_fixture(
    db: AsyncSession,
    *,
    active_user: bool = True,
    active_profile: bool = True,
    active_link: bool = True,
    user: User | None = None,
    ilpi_id: str | None = None,
    profile_key: str | None = None,
) -> tuple[User, Instituicao, Perfil, UsuarioIlpiPerfil]:
    """Institutional fixture with an active Funcionario (Fase 3B requirement).

    A valid ILPI security context requires an active operational link
    (Funcionario) between the user and the tenant; without it
    load_security_context denies with AUTH_CONTEXT_REQUIRED before any
    permission guard is reached.

    Rows are flushed in FK dependency order (roots, then profile, then
    link/employee) because PostgreSQL enforces FK constraints immediately
    while the models declare no ORM relationships for the unit of work to
    sort by.
    """
    user = user or _new_user(active=active_user)
    institution = _new_institution(ilpi_id)
    profile = _new_profile(
        institution.id,
        active=active_profile,
        key=profile_key,
    )
    db.add_all([user, institution])
    await db.flush()
    db.add(profile)
    await db.flush()
    link = _new_link(
        user.id,
        profile.id,
        institution.id,
        active=active_link,
    )
    employee = Funcionario(
        id=_new_id(),
        ilpi_id=institution.id,
        usuario_id=user.id,
        nome=user.nome,
        email=user.email,
        situacao="ativo",
    )
    db.add_all([link, employee])
    await db.flush()
    return user, institution, profile, link


async def _platform_context_fixture(
    db: AsyncSession,
    *,
    active_user: bool = True,
) -> tuple[User, Perfil, UsuarioIlpiPerfil]:
    user = _new_user(active=active_user)
    profile = (
        await db.execute(
            select(Perfil).where(
                Perfil.chave == "platform_superuser",
                Perfil.ilpi_id.is_(None),
            )
        )
    ).scalar_one()
    link = _new_link(user.id, profile.id, None)
    db.add_all([user, link])
    await db.flush()
    return user, profile, link


async def _grant_existing_permission(
    db: AsyncSession,
    profile_id: str,
    key: str,
) -> None:
    permission = (
        await db.execute(select(Permissao).where(Permissao.chave == key))
    ).scalar_one()
    db.add(PerfilPermissao(perfil_id=profile_id, permissao_id=permission.id))
    await db.flush()


def _assert_http_error(error: pytest.ExceptionInfo[HTTPException], status_code: int, code: str):
    assert error.value.status_code == status_code
    assert error.value.detail["code"] == code


def test_missing_token_returns_401(rbac_db: pathlib.Path):
    async def scenario(db: AsyncSession):
        with pytest.raises(HTTPException) as error:
            await get_current_user(None, db)
        _assert_http_error(error, 401, AUTHENTICATION_REQUIRED)

    asyncio.run(_with_session(rbac_db, scenario))


def test_invalid_and_expired_tokens_return_401(rbac_db: pathlib.Path):
    async def scenario(db: AsyncSession):
        invalid = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials="not-a-valid-token",
        )
        with pytest.raises(HTTPException) as invalid_error:
            await get_current_user(invalid, db)
        _assert_http_error(invalid_error, 401, AUTHENTICATION_REQUIRED)

        expired_token = jwt.encode(
            {
                "sub": _new_id(),
                "iat": 1,
                "exp": 2,
            },
            JWT_SECRET,
            algorithm=JWT_ALGORITHM,
        )
        expired = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=expired_token,
        )
        with pytest.raises(HTTPException) as expired_error:
            await get_current_user(expired, db)
        _assert_http_error(expired_error, 401, AUTHENTICATION_REQUIRED)

    asyncio.run(_with_session(rbac_db, scenario))


def test_user_without_link_returns_403(rbac_db: pathlib.Path):
    async def scenario(db: AsyncSession):
        user = _new_user()
        db.add(user)
        await db.commit()
        with pytest.raises(HTTPException) as error:
            await load_security_context(db, user)
        _assert_http_error(error, 403, AUTH_CONTEXT_REQUIRED)

    asyncio.run(_with_session(rbac_db, scenario))


def test_inactive_user_returns_403(rbac_db: pathlib.Path):
    async def scenario(db: AsyncSession):
        user = _new_user(active=False)
        db.add(user)
        await db.commit()
        with pytest.raises(HTTPException) as error:
            await load_security_context(db, user)
        _assert_http_error(error, 403, AUTH_CONTEXT_REQUIRED)

    asyncio.run(_with_session(rbac_db, scenario))


def test_inactive_profile_returns_403(rbac_db: pathlib.Path):
    async def scenario(db: AsyncSession):
        user, _institution, _profile, _link = await _institution_context_fixture(
            db,
            active_profile=False,
        )
        await db.commit()
        with pytest.raises(HTTPException) as error:
            await load_security_context(db, user)
        _assert_http_error(error, 403, AUTH_CONTEXT_REQUIRED)

    asyncio.run(_with_session(rbac_db, scenario))


def test_inactive_link_returns_403(rbac_db: pathlib.Path):
    async def scenario(db: AsyncSession):
        user, _institution, _profile, _link = await _institution_context_fixture(
            db,
            active_link=False,
        )
        await db.commit()
        with pytest.raises(HTTPException) as error:
            await load_security_context(db, user)
        _assert_http_error(error, 403, AUTH_CONTEXT_REQUIRED)

    asyncio.run(_with_session(rbac_db, scenario))


def test_global_scope_accepts_platform_superuser_context(rbac_db: pathlib.Path):
    async def scenario(db: AsyncSession):
        user, _profile, _link = await _platform_context_fixture(db)
        await db.commit()
        context = await load_security_context(db, user, scope="global")
        assert context.scope == "global"
        assert await require_global_scope(context) is context

    asyncio.run(_with_session(rbac_db, scenario))


def test_global_scope_rejects_ilpi_context_guard(rbac_db: pathlib.Path):
    async def scenario(db: AsyncSession):
        user, _profile, _link = await _platform_context_fixture(db)
        await db.commit()
        context = await load_security_context(db, user, scope="global")
        with pytest.raises(HTTPException) as error:
            await require_ilpi_context(context)
        _assert_http_error(error, 403, ILPI_CONTEXT_REQUIRED)

    asyncio.run(_with_session(rbac_db, scenario))


def test_institutional_context_accepts_valid_link(rbac_db: pathlib.Path):
    async def scenario(db: AsyncSession):
        user, institution, _profile, _link = await _institution_context_fixture(db)
        await db.commit()
        context = await build_security_context(
            user,
            db,
            scope="ilpi",
            ilpi_id=institution.id,
        )
        assert context.ilpi_id == institution.id
        assert await require_ilpi_context(context) is context

    asyncio.run(_with_session(rbac_db, scenario))


def test_institutional_context_rejects_global_scope_guard(rbac_db: pathlib.Path):
    async def scenario(db: AsyncSession):
        user, institution, _profile, _link = await _institution_context_fixture(db)
        await db.commit()
        context = await load_security_context(db, user, scope="ilpi", ilpi_id=institution.id)
        with pytest.raises(HTTPException) as error:
            await require_global_scope(context)
        _assert_http_error(error, 403, GLOBAL_SCOPE_REQUIRED)

    asyncio.run(_with_session(rbac_db, scenario))


def test_exact_permission_authorizes(rbac_db: pathlib.Path):
    async def scenario(db: AsyncSession):
        user, institution, profile, _link = await _institution_context_fixture(db)
        await _grant_existing_permission(db, profile.id, "usuarios:ler")
        await db.commit()
        context = await load_security_context(
            db,
            user,
            scope="ilpi",
            ilpi_id=institution.id,
        )
        authorized = await require_permission("usuarios:ler")(context, db)
        assert authorized.ilpi_id == institution.id

    asyncio.run(_with_session(rbac_db, scenario))


def test_missing_permission_denies_by_default(rbac_db: pathlib.Path):
    async def scenario(db: AsyncSession):
        user, institution, profile, _link = await _institution_context_fixture(db)
        await db.commit()
        context = await load_security_context(
            db,
            user,
            scope="ilpi",
            ilpi_id=institution.id,
        )
        with pytest.raises(HTTPException) as error:
            await require_permission("usuarios:ler")(context, db)
        _assert_http_error(error, 403, PERMISSION_DENIED)

    asyncio.run(_with_session(rbac_db, scenario))


def test_wildcard_never_authorizes(rbac_db: pathlib.Path):
    async def scenario(db: AsyncSession):
        user, institution, profile, _link = await _institution_context_fixture(db)
        # A literal "*" key on a catalog-free (modulo, acao) pair: linking it
        # must never grant anything, and must not collide with migration 006,
        # which owns ("residentes", "ler").
        wildcard = Permissao(
            id=_new_id(),
            modulo="wildcard_modulo",
            acao="sondar",
            chave="*",
            descricao="Wildcard fixture",
        )
        db.add(wildcard)
        await db.flush()
        db.add(PerfilPermissao(perfil_id=profile.id, permissao_id=wildcard.id))
        await db.commit()
        context = await load_security_context(
            db,
            user,
            scope="ilpi",
            ilpi_id=institution.id,
        )
        with pytest.raises(HTTPException) as error:
            await require_permission("residentes:ler")(context, db)
        _assert_http_error(error, 403, PERMISSION_DENIED)

        with pytest.raises(HTTPException) as wildcard_error:
            await require_permission("*")(context, db)
        _assert_http_error(wildcard_error, 403, PERMISSION_DENIED)

    asyncio.run(_with_session(rbac_db, scenario))


def test_template_ilpi_admin_without_tenant_cannot_be_linked(rbac_db: pathlib.Path):
    async def scenario(db: AsyncSession):
        user = _new_user()
        template = (
            await db.execute(
                select(Perfil).where(
                    Perfil.chave == "ilpi_admin",
                    Perfil.ilpi_id.is_(None),
                )
            )
        ).scalar_one()
        db.add(_new_link(user.id, template.id, None))
        db.add(user)
        await db.commit()
        with pytest.raises(HTTPException) as error:
            await load_security_context(db, user, scope="ilpi")
        _assert_http_error(error, 403, AUTH_CONTEXT_REQUIRED)

    asyncio.run(_with_session(rbac_db, scenario))


def test_profile_of_tenant_a_cannot_authorize_tenant_b(rbac_db: pathlib.Path):
    async def scenario(db: AsyncSession):
        user = _new_user()
        _user, institution_a, profile_a, _link_a = await _institution_context_fixture(
            db,
            user=user,
        )
        _user, institution_b, _profile_b, _link_b = await _institution_context_fixture(
            db,
            user=user,
        )
        await db.commit()
        with pytest.raises(HTTPException) as error:
            await load_security_context(
                db,
                user,
                scope="ilpi",
                ilpi_id=institution_b.id,
                perfil_id=profile_a.id,
            )
        _assert_http_error(error, 403, AUTH_CONTEXT_REQUIRED)

    asyncio.run(_with_session(rbac_db, scenario))


def test_other_tenant_resource_returns_404_without_existence_leak(rbac_db: pathlib.Path):
    async def scenario(db: AsyncSession):
        user, institution_a, _profile, _link = await _institution_context_fixture(db)
        institution_b = _new_institution()
        db.add(institution_b)
        await db.commit()
        context = await load_security_context(db, user, ilpi_id=institution_a.id)
        with pytest.raises(HTTPException) as error:
            ensure_same_tenant(context, institution_b.id)
        _assert_http_error(error, 404, RESOURCE_NOT_FOUND)

    asyncio.run(_with_session(rbac_db, scenario))


def test_payload_tenant_cannot_change_session_tenant(rbac_db: pathlib.Path):
    async def scenario(db: AsyncSession):
        user, institution_a, _profile, _link = await _institution_context_fixture(db)
        institution_b = _new_institution()
        db.add(institution_b)
        await db.commit()
        context = await load_security_context(db, user, ilpi_id=institution_a.id)
        payload = {"ilpi_id": institution_b.id}
        with pytest.raises(HTTPException) as error:
            ensure_same_tenant(context, payload["ilpi_id"])
        _assert_http_error(error, 404, RESOURCE_NOT_FOUND)
        assert context.ilpi_id == institution_a.id

    asyncio.run(_with_session(rbac_db, scenario))


def test_platform_superuser_does_not_get_clinical_permission(rbac_db: pathlib.Path):
    async def scenario(db: AsyncSession):
        user, profile, _link = await _platform_context_fixture(db)
        # Use the official catalog permission owned by migration 006 instead
        # of inserting a duplicate (modulo, acao) pair: even with an explicit
        # clinical grant on the disposable database, the architectural
        # global/clinical rule must deny.
        clinical = (
            await db.execute(select(Permissao).where(Permissao.chave == "residentes:ler"))
        ).scalar_one()
        db.add(PerfilPermissao(perfil_id=profile.id, permissao_id=clinical.id))
        await db.commit()
        context = await load_security_context(db, user, scope="global")
        with pytest.raises(HTTPException) as error:
            await require_permission("residentes:ler")(context, db)
        _assert_http_error(error, 403, PERMISSION_DENIED)

    asyncio.run(_with_session(rbac_db, scenario))


def test_selected_profile_from_other_tenant_is_rejected(rbac_db: pathlib.Path):
    async def scenario(db: AsyncSession):
        user = _new_user()
        _user, institution_a, _profile_a, _link_a = await _institution_context_fixture(
            db,
            user=user,
        )
        _user, _institution_b, profile_b, _link_b = await _institution_context_fixture(
            db,
            user=user,
        )
        await db.commit()
        with pytest.raises(HTTPException) as error:
            await load_security_context(
                db,
                user,
                scope="ilpi",
                ilpi_id=institution_a.id,
                perfil_id=profile_b.id,
            )
        _assert_http_error(error, 403, AUTH_CONTEXT_REQUIRED)

    asyncio.run(_with_session(rbac_db, scenario))


def test_ambiguous_context_requires_profile_selection(rbac_db: pathlib.Path):
    async def scenario(db: AsyncSession):
        user = _new_user()
        await _institution_context_fixture(db, user=user)
        await _institution_context_fixture(db, user=user)
        await db.commit()
        with pytest.raises(HTTPException) as error:
            await load_security_context(db, user)
        _assert_http_error(error, 403, PROFILE_SELECTION_REQUIRED)

    asyncio.run(_with_session(rbac_db, scenario))


def test_context_dependency_uses_only_database_validated_selectors(rbac_db: pathlib.Path):
    async def scenario(db: AsyncSession):
        user, institution_a, _profile, _link = await _institution_context_fixture(db)
        institution_b = _new_institution()
        db.add(institution_b)
        await db.commit()
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/fixture",
                "headers": [(b"x-ilpi-id", institution_b.id.encode())],
            }
        )
        with pytest.raises(HTTPException) as error:
            await get_security_context(request, user, db)
        _assert_http_error(error, 403, AUTH_CONTEXT_REQUIRED)
        assert institution_a.id != institution_b.id

    asyncio.run(_with_session(rbac_db, scenario))


def test_denial_logs_never_contain_sensitive_values(rbac_db: pathlib.Path, caplog):
    secret_token = "Bearer token-that-must-not-be-logged"
    secret_cookie = "cookie-that-must-not-be-logged"
    secret_password = "SenhaSuperSecreta123"
    secret_hash = "bcrypt-hash-that-must-not-be-logged"
    clinical_data = "alergia: informação clínica privada"

    caplog.set_level(logging.WARNING, logger="facilpi.security")

    async def scenario(db: AsyncSession):
        invalid = HTTPAuthorizationCredentials(
            scheme="Bearer",
            credentials=secret_token.removeprefix("Bearer "),
        )
        with pytest.raises(HTTPException):
            await get_current_user(invalid, db)

        user, institution, _profile, _link = await _institution_context_fixture(db)
        user.password_hash = secret_hash
        await db.commit()
        context = await load_security_context(db, user, ilpi_id=institution.id)
        with pytest.raises(HTTPException):
            ensure_same_tenant(context, _new_id())

    asyncio.run(_with_session(rbac_db, scenario))
    output = caplog.text
    for sensitive in (
        secret_token,
        secret_cookie,
        secret_password,
        secret_hash,
        clinical_data,
    ):
        assert sensitive not in output
    assert "authorization_denied" in output
    assert "authentication_denied" in output
