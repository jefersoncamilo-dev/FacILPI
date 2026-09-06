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
from src.application.fase3a import ADMIN_EMAIL, ILPI_DRAFT  # noqa: E402
from src.infrastructure import database  # noqa: E402
from src.infrastructure import models as m  # noqa: E402
from src.scripts import bootstrap as bootstrap_script  # noqa: E402


BOOTSTRAP_TOKEN = "fase3b-perfis-test-bootstrap-token"
FIRST_PASSWORD = "SenhaPrimeiro123A"
ADMIN_PASSWORD = "SenhaAdmin123A"


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
    if os.getenv("FASE3B_TEST_POSTGRES_URL") or os.getenv("FASE3A_TEST_POSTGRES_URL"):
        backends.append("postgresql")
    return backends


@pytest.fixture(params=_database_backends(), ids=lambda backend: backend)
def perfis_db(request: pytest.FixtureRequest, tmp_path: pathlib.Path) -> pathlib.Path | str:
    if request.param == "sqlite":
        path = tmp_path / "fase3b-perfis.db"
        _run_migration(path, "upgrade", "head")
        return path

    url = os.environ.get("FASE3B_TEST_POSTGRES_URL") or os.environ["FASE3A_TEST_POSTGRES_URL"]
    try:
        asyncio.run(_reset_postgres(url))
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


async def _login(client: httpx.AsyncClient, email: str, password: str, **context) -> httpx.Response:
    payload = {"email": email, "password": password}
    payload.update({key: value for key, value in context.items() if value is not None})
    return await client.post("/api/auth/token", json=payload)


async def _bootstrap_global_access(client: httpx.AsyncClient) -> str:
    bootstrap = await bootstrap_script.run_bootstrap(BOOTSTRAP_TOKEN)
    login = await _login(client, ADMIN_EMAIL, bootstrap.temporary_password)
    assert login.status_code == 200, login.text
    first_access = await client.put(
        "/api/auth/primeiro-acesso",
        headers=_auth_headers(login.json()["access_token"]),
        json={"nova_senha": FIRST_PASSWORD, "confirmar": FIRST_PASSWORD},
    )
    assert first_access.status_code == 200, first_access.text
    password = await client.put(
        "/api/auth/password",
        headers=_auth_headers(first_access.json()["access_token"]),
        json={"nova_senha": ADMIN_PASSWORD, "confirmar_senha": ADMIN_PASSWORD},
    )
    assert password.status_code == 200, password.text
    login = await _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


async def _create_ilpi_admin_context(client: httpx.AsyncClient, db: AsyncSession) -> dict[str, str]:
    global_access = await _bootstrap_global_access(client)
    draft = await client.post(
        "/api/instituicoes/",
        headers=_auth_headers(global_access),
        json={"razao_social": "ILPI Perfis", "capacidade": 10, "uf": "SP"},
    )
    assert draft.status_code == 201, draft.text
    ilpi_id = draft.json()["id"]
    onboarding = await client.post(
        f"/api/onboarding/{ilpi_id}/iniciar",
        headers=_auth_headers(global_access),
        json={"usar_usuario_atual_como_admin": True},
    )
    assert onboarding.status_code == 200, onboarding.text
    profile = (
        await db.execute(select(m.Perfil).where(m.Perfil.chave == "ilpi_admin", m.Perfil.ilpi_id == ilpi_id))
    ).scalar_one()
    context = await client.post(
        "/api/auth/contexto",
        headers=_auth_headers(global_access),
        json={"scope": "ilpi", "ilpi_id": ilpi_id, "perfil_id": profile.id},
    )
    assert context.status_code == 200, context.text
    return {"global_access": global_access, "local_access": context.json()["access_token"], "ilpi_id": ilpi_id, "perfil_id": profile.id}


async def _create_other_tenant(db: AsyncSession) -> dict[str, str]:
    ilpi = m.Instituicao(id=str(uuid.uuid4()), razao_social="ILPI Outro Tenant", situacao=ILPI_DRAFT, capacidade=5, uf="RJ")
    db.add(ilpi)
    # Flush incremental: os models não declaram relationship(), então o UoW
    # pode ordenar o flush fora da ordem de dependência em bancos que impõem
    # FK (PostgreSQL). SQLite mascara o problema (FK desligado por padrão).
    await db.flush()
    template = (await db.execute(select(m.Perfil).where(m.Perfil.chave == "ilpi_admin", m.Perfil.ilpi_id.is_(None)))).scalar_one()
    profile = m.Perfil(
        id=str(uuid.uuid4()),
        ilpi_id=ilpi.id,
        nome=template.nome,
        chave=template.chave,
        descricao=template.descricao,
        escopo="ilpi",
        situacao="ativo",
    )
    db.add(profile)
    await db.flush()
    permission_ids = (
        await db.execute(select(m.PerfilPermissao.permissao_id).where(m.PerfilPermissao.perfil_id == template.id))
    ).scalars().all()
    for permission_id in permission_ids:
        db.add(m.PerfilPermissao(perfil_id=profile.id, permissao_id=permission_id))
    await db.flush()
    user = m.User(
        id=str(uuid.uuid4()),
        nome="Usuario Outro Tenant",
        email="outro.tenant@example.com",
        password_hash=auth.hash_password("SenhaOutro123A"),
        ativo=True,
        is_superuser=False,
        exige_troca_senha=False,
    )
    db.add(user)
    await db.flush()
    employee = m.Funcionario(
        id=str(uuid.uuid4()),
        ilpi_id=ilpi.id,
        usuario_id=user.id,
        nome="Funcionario Outro Tenant",
        cpf="52998224725",
        email="func.outro@example.com",
        situacao="ativo",
    )
    db.add(employee)
    link = m.UsuarioIlpiPerfil(id=str(uuid.uuid4()), usuario_id=user.id, ilpi_id=ilpi.id, perfil_id=profile.id, situacao="ativo")
    db.add(link)
    await db.commit()
    return {"ilpi_id": ilpi.id, "perfil_id": profile.id, "user_id": user.id}


def test_fase3b_perfis_list_backend(perfis_db, monkeypatch):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        context = await _create_ilpi_admin_context(client, db)
        local_headers = _auth_headers(context["local_access"])
        other = await _create_other_tenant(db)

        # 1. Contexto global sem ILPI não lista perfis de tenant (regra de contexto ILPI).
        denied_global = await client.get("/api/perfis/", headers=_auth_headers(context["global_access"]))
        assert denied_global.status_code == 403, denied_global.text
        assert denied_global.json()["detail"]["code"] == "ILPI_CONTEXT_REQUIRED"

        # 2/3. Admin ILPI lista perfis do próprio tenant (ilpi_admin clonado no onboarding).
        listing = await client.get("/api/perfis/", headers=local_headers)
        assert listing.status_code == 200, listing.text
        own_ids = {item["id"] for item in listing.json()}
        assert context["perfil_id"] in own_ids

        # Cria um perfil local ativo adicional e confirma presença.
        created = await client.post(
            "/api/perfis/",
            headers=local_headers,
            json={"nome": "Enfermeiro Chefe", "chave": "enfermeiro_chefe", "descricao": "Responsável pela enfermagem"},
        )
        assert created.status_code == 201, created.text
        created_id = created.json()["id"]

        listing = await client.get("/api/perfis/", headers=local_headers)
        assert listing.status_code == 200, listing.text
        own_ids = {item["id"] for item in listing.json()}
        assert created_id in own_ids

        # 4. Perfil local inativo aparece na listagem administrativa.
        created_profile = (await db.execute(select(m.Perfil).where(m.Perfil.id == created_id))).scalar_one()
        created_profile.situacao = "inativo"
        await db.commit()

        listing = await client.get("/api/perfis/", headers=local_headers)
        assert listing.status_code == 200, listing.text
        by_id = {item["id"]: item for item in listing.json()}
        assert created_id in by_id
        assert by_id[created_id]["situacao"] == "inativo"

        # 5. platform_superuser nunca aparece na listagem local.
        chaves = {item["chave"] for item in listing.json()}
        assert "platform_superuser" not in chaves
        assert all(item["escopo"] == "ilpi" for item in listing.json())

        # 6. Perfil de outra ILPI não é exposto.
        assert other["perfil_id"] not in by_id

        # 7/E. Cross-tenant: usuário da outra ILPI lista apenas o próprio tenant.
        other_login = await _login(
            client,
            "outro.tenant@example.com",
            "SenhaOutro123A",
            scope="ilpi",
            ilpi_id=other["ilpi_id"],
            perfil_id=other["perfil_id"],
        )
        assert other_login.status_code == 200, other_login.text
        other_listing = await client.get("/api/perfis/", headers=_auth_headers(other_login.json()["access_token"]))
        assert other_listing.status_code == 200, other_listing.text
        other_ids = {item["id"] for item in other_listing.json()}
        assert other_ids == {other["perfil_id"]}
        assert created_id not in other_ids
        assert context["perfil_id"] not in other_ids

        # Catálogo e modelo preservados.
        counts = {
            key: (await db.execute(text(query))).scalar_one()
            for key, query in {
                "permissoes": "SELECT COUNT(*) FROM permissoes",
                "template_perfis": "SELECT COUNT(*) FROM perfis WHERE ilpi_id IS NULL",
                "template_permissoes": "SELECT COUNT(*) FROM perfil_permissoes pp JOIN perfis p ON p.id = pp.perfil_id WHERE p.ilpi_id IS NULL",
            }.items()
        }
        assert counts == {"permissoes": 44, "template_perfis": 2, "template_permissoes": 55}

    asyncio.run(_with_client(perfis_db, monkeypatch, scenario))
