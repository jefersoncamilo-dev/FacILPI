"""UX-01 (#83): GET /api/auth/permissoes — permissoes efetivas da sessao.

A navegacao usa esta lista para nao oferecer o que o backend recusaria. O
contrato que importa e a paridade: uma chave esta na lista se, e somente se, o
`require_permission` dela aceitaria o mesmo contexto. Tudo em banco descartavel.
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
from src.application.security import (  # noqa: E402
    AUTH_CONTEXT_REQUIRED,
    FIRST_PASSWORD_CHANGE_REQUIRED,
    allowed_permission_keys,
    load_security_context,
    require_permission,
)
from src.infrastructure import database  # noqa: E402
from src.infrastructure import models as m  # noqa: E402
from tests.sessao_teste import abrir_sessao, token_de  # noqa: E402


ATIVA = "ATIVA"
RASCUNHO = "ILPI_RASCUNHO"
# Mistura chave clinica, administrativa e uma so-global, para exercitar os
# filtros de escopo e do GATE-2 alem da simples concessao.
PERMISSOES = {
    "residentes:ler",
    "sinais_vitais:criar",
    "sinais_vitais:ler",
    "planos_cuidados:ler",
    "funcionarios:ler",
    "ilpis:criar",
}


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


def _run_migration(database_ref: pathlib.Path | str) -> None:
    if isinstance(database_ref, pathlib.Path):
        assert database_ref.resolve() != OFFICIAL_DB.resolve()
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
def ux01_db(request: pytest.FixtureRequest, tmp_path: pathlib.Path) -> pathlib.Path | str:
    if request.param == "sqlite":
        path = tmp_path / "ux01-permissoes.db"
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
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            async with factory() as session:
                return await operation(client, session)
    finally:
        main.app.dependency_overrides.clear()
        await engine.dispose()


def _new_id() -> str:
    return str(uuid.uuid4())


def _new_user() -> m.User:
    user_id = _new_id()
    return m.User(
        id=user_id,
        nome="Usuario UX-01",
        email=f"ux01-{user_id}@example.com",
        password_hash="fixture-password-hash",
        ativo=True,
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


async def _new_ilpi(db: AsyncSession, nome: str, situacao: str) -> m.Instituicao:
    institution = m.Instituicao(id=_new_id(), razao_social=nome, situacao=situacao)
    db.add(institution)
    await db.flush()
    return institution


async def _link_to_ilpi(
    db: AsyncSession,
    user: m.User,
    institution: m.Instituicao,
    permissions: set[str],
) -> m.Perfil:
    """Perfil + vinculo + funcionario ativo, em ordem de FK (PostgreSQL)."""
    profile = m.Perfil(
        id=_new_id(),
        ilpi_id=institution.id,
        nome="Perfil UX-01",
        chave=f"ux01_{_new_id()[:8]}",
        escopo="ilpi",
        situacao="ativo",
    )
    db.add(profile)
    await db.flush()
    db.add_all([
        m.Funcionario(
            id=_new_id(),
            ilpi_id=institution.id,
            usuario_id=user.id,
            nome=user.nome,
            email=user.email,
            cargo="Equipe",
            situacao="ativo",
        ),
        _new_link(user.id, profile.id, institution.id),
    ])
    await db.flush()
    rows = (
        await db.execute(select(m.Permissao).where(m.Permissao.chave.in_(permissions)))
    ).scalars().all()
    assert {row.chave for row in rows} == permissions
    for row in rows:
        db.add(m.PerfilPermissao(perfil_id=profile.id, permissao_id=row.id))
    await db.flush()
    return profile


async def _ilpi_user(db: AsyncSession, situacao: str = ATIVA, permissions=PERMISSOES):
    user = _new_user()
    db.add(user)
    await db.flush()
    institution = await _new_ilpi(db, "ILPI UX-01", situacao)
    profile = await _link_to_ilpi(db, user, institution, set(permissions))
    await abrir_sessao(db, user)
    await db.commit()
    return user, institution, profile


async def _platform_user(db: AsyncSession) -> m.User:
    user = _new_user()
    user.is_superuser = True
    profile = (
        await db.execute(
            select(m.Perfil).where(m.Perfil.chave == "platform_superuser", m.Perfil.ilpi_id.is_(None))
        )
    ).scalar_one()
    db.add(user)
    await db.flush()
    db.add(_new_link(user.id, profile.id, None))
    await db.flush()
    await abrir_sessao(db, user)
    await db.commit()
    return user


def _headers(user: m.User, *, scope: str, ilpi_id: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token_de(user)}", "X-Scope": scope}
    if ilpi_id is not None:
        headers["X-ILPI-ID"] = ilpi_id
    return headers


def _code(response: httpx.Response) -> str | None:
    detail = response.json().get("detail")
    return detail.get("code") if isinstance(detail, dict) else None


async def _assert_parity(db: AsyncSession, user: m.User, *, scope: str, ilpi_id: str | None) -> set[str]:
    """Para cada chave do catalogo: listada <=> o guard real aceita."""
    context = await load_security_context(db, user, scope=scope, ilpi_id=ilpi_id)
    listed = set(await allowed_permission_keys(db, context))
    catalog = (await db.execute(select(m.Permissao.chave))).scalars().all()
    assert catalog, "catalogo de permissoes vazio: a paridade nao provaria nada"
    for key in catalog:
        try:
            await require_permission(key)(context=context, db=db)
            accepted = True
        except HTTPException as error:
            assert error.status_code == 403, key
            accepted = False
        assert accepted == (key in listed), key
    return listed


def test_lista_as_permissoes_do_contexto_ativo(ux01_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        user, institution, _ = await _ilpi_user(db)

        response = await client.get(
            "/api/auth/permissoes",
            headers=_headers(user, scope="ilpi", ilpi_id=institution.id),
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["scope"] == "ilpi"
        assert body["ilpi_id"] == institution.id
        # O perfil nao tem `ilpis:ler`, e mesmo assim sabe onde esta operando.
        assert "ilpis:ler" not in PERMISSOES
        assert body["ilpi_nome"] == "ILPI UX-01"
        assert body["perfil_nome"] == "Perfil UX-01"
        # `ilpis:criar` e so-global: concedida ao perfil, recusada em escopo ILPI.
        assert body["permissoes"] == sorted(PERMISSOES - {"ilpis:criar"})

    asyncio.run(_with_client(ux01_db, scenario))


def test_contexto_vem_das_claims_do_token(ux01_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        user, institution, profile = await _ilpi_user(db)
        token = token_de(user, scope="ilpi", ilpi_id=institution.id, perfil_id=profile.id)

        response = await client.get(
            "/api/auth/permissoes",
            headers={"Authorization": f"Bearer {token}"},
        )

        assert response.status_code == 200, response.text
        assert response.json()["permissoes"] == sorted(PERMISSOES - {"ilpis:criar"})

    asyncio.run(_with_client(ux01_db, scenario))


def test_cada_ilpi_ve_so_o_proprio_perfil(ux01_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        user, ilpi_a, _ = await _ilpi_user(db, permissions={"residentes:ler"})
        ilpi_b = await _new_ilpi(db, "ILPI UX-01 B", ATIVA)
        await _link_to_ilpi(db, user, ilpi_b, {"sinais_vitais:ler"})
        ilpi_sem_vinculo = await _new_ilpi(db, "ILPI UX-01 C", ATIVA)
        await db.commit()

        resposta_a = await client.get(
            "/api/auth/permissoes", headers=_headers(user, scope="ilpi", ilpi_id=ilpi_a.id)
        )
        resposta_b = await client.get(
            "/api/auth/permissoes", headers=_headers(user, scope="ilpi", ilpi_id=ilpi_b.id)
        )
        sem_vinculo = await client.get(
            "/api/auth/permissoes",
            headers=_headers(user, scope="ilpi", ilpi_id=ilpi_sem_vinculo.id),
        )

        assert resposta_a.json()["permissoes"] == ["residentes:ler"]
        assert resposta_b.json()["permissoes"] == ["sinais_vitais:ler"]
        assert resposta_a.json()["ilpi_nome"] == "ILPI UX-01"
        assert resposta_b.json()["ilpi_nome"] == "ILPI UX-01 B"
        assert sem_vinculo.status_code == 403, sem_vinculo.text
        assert _code(sem_vinculo) == AUTH_CONTEXT_REQUIRED

    asyncio.run(_with_client(ux01_db, scenario))


@pytest.mark.parametrize("situacao", [ATIVA, RASCUNHO])
def test_paridade_com_require_permission_em_ilpi(ux01_db, situacao):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        user, institution, _ = await _ilpi_user(db, situacao=situacao)
        listed = await _assert_parity(db, user, scope="ilpi", ilpi_id=institution.id)
        if situacao == RASCUNHO:
            # GATE-2: rascunho nao libera modulo clinico.
            assert "residentes:ler" not in listed
            assert "sinais_vitais:criar" not in listed

    asyncio.run(_with_client(ux01_db, scenario))


def test_paridade_no_contexto_global_sem_modulo_clinico(ux01_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        user = await _platform_user(db)
        listed = await _assert_parity(db, user, scope="global", ilpi_id=None)
        assert listed, "superusuario sem nenhuma permissao global"
        assert not any(key.startswith(("residentes:", "sinais_vitais:", "planos_cuidados:")) for key in listed)

        response = await client.get("/api/auth/permissoes", headers=_headers(user, scope="global"))
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["scope"] == "global"
        assert body["ilpi_id"] is None and body["ilpi_nome"] is None
        assert body["perfil_nome"]
        assert body["permissoes"] == sorted(listed)

    asyncio.run(_with_client(ux01_db, scenario))


def test_sem_sessao_valida_responde_401(ux01_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        user, institution, _ = await _ilpi_user(db)
        sem_token = await client.get("/api/auth/permissoes")
        sem_sid = await client.get(
            "/api/auth/permissoes",
            headers={
                "Authorization": f"Bearer {auth.create_access_token(user)}",
                "X-Scope": "ilpi",
                "X-ILPI-ID": institution.id,
            },
        )
        assert sem_token.status_code == 401, sem_token.text
        assert sem_sid.status_code == 401, sem_sid.text

    asyncio.run(_with_client(ux01_db, scenario))


def test_troca_de_senha_pendente_nao_expoe_permissoes(ux01_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        user, institution, _ = await _ilpi_user(db)
        user.exige_troca_senha = True
        await db.commit()

        response = await client.get(
            "/api/auth/permissoes",
            headers=_headers(user, scope="ilpi", ilpi_id=institution.id),
        )

        assert response.status_code == 403, response.text
        assert _code(response) == FIRST_PASSWORD_CHANGE_REQUIRED

    asyncio.run(_with_client(ux01_db, scenario))
