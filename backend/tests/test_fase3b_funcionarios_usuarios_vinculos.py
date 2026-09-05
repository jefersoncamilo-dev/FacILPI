from __future__ import annotations

import asyncio
import os
import pathlib
import subprocess
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timezone

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


BOOTSTRAP_TOKEN = "fase3b-test-bootstrap-token"
FIRST_PASSWORD = "SenhaPrimeiro123A"
ADMIN_PASSWORD = "SenhaAdmin123A"
LOCAL_PASSWORD = "SenhaLocal123A"


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
def fase3b_db(request: pytest.FixtureRequest, tmp_path: pathlib.Path) -> pathlib.Path | str:
    if request.param == "sqlite":
        path = tmp_path / "fase3b.db"
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
        json={"razao_social": "ILPI Fase 3B", "capacidade": 10, "uf": "SP"},
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
    return {"ilpi_id": ilpi.id, "perfil_id": profile.id, "user_id": user.id, "funcionario_id": employee.id}


def test_fase3b_funcionarios_usuarios_vinculos_backend(fase3b_db, monkeypatch):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        context = await _create_ilpi_admin_context(client, db)
        local_headers = _auth_headers(context["local_access"])
        other = await _create_other_tenant(db)

        sem_login = await client.post(
            "/api/funcionarios/",
            headers=local_headers,
            json={"nome": "Funcionario Sem Login", "cpf": "11144477735", "email": "sem.login@example.com", "cargo": "Cuidador"},
        )
        assert sem_login.status_code == 201, sem_login.text
        sem_login_id = sem_login.json()["id"]
        assert sem_login.json()["usuario_id"] is None

        com_login = await client.post(
            "/api/funcionarios/",
            headers=local_headers,
            json={
                "nome": "Funcionario Com Login",
                "cpf": "93541134780",
                "email": "com.login@example.com",
                "cargo": "Administrador",
                "criar_usuario": True,
                "perfil_id": context["perfil_id"],
            },
        )
        assert com_login.status_code == 201, com_login.text
        com_login_payload = com_login.json()
        assert com_login_payload["usuario_id"]
        assert com_login_payload["senha_temporaria"]

        user = await client.post(
            "/api/usuarios/",
            headers=local_headers,
            json={"nome": "Usuario Local", "email": "usuario.local@example.com", "perfil_id": context["perfil_id"]},
        )
        assert user.status_code == 201, user.text
        user_payload = user.json()

        link = await client.post(
            f"/api/funcionarios/{sem_login_id}/vincular-usuario",
            headers=local_headers,
            json={"usuario_id": user_payload["id"]},
        )
        assert link.status_code == 200, link.text
        assert link.json()["usuario_id"] == user_payload["id"]

        cross_link = await client.post(
            f"/api/funcionarios/{sem_login_id}/vincular-usuario",
            headers=local_headers,
            json={"usuario_id": other["user_id"]},
        )
        assert cross_link.status_code == 403

        duplicate_cpf = await client.post(
            "/api/funcionarios/",
            headers=local_headers,
            json={"nome": "CPF Duplicado", "cpf": "11144477735"},
        )
        assert duplicate_cpf.status_code == 409
        duplicate_email = await client.post(
            "/api/usuarios/",
            headers=local_headers,
            json={"nome": "Email Duplicado", "email": "usuario.local@example.com", "perfil_id": context["perfil_id"]},
        )
        assert duplicate_email.status_code == 409

        employees = await client.get("/api/funcionarios/", headers=local_headers)
        assert employees.status_code == 200, employees.text
        employee_ids = {item["id"] for item in employees.json()}
        assert {sem_login_id, com_login_payload["id"]}.issubset(employee_ids)
        assert other["funcionario_id"] not in employee_ids

        other_employee = await client.get(f"/api/funcionarios/{other['funcionario_id']}", headers=local_headers)
        assert other_employee.status_code == 404

        updated_employee = await client.put(
            f"/api/funcionarios/{sem_login_id}",
            headers=local_headers,
            json={"cargo": "Enfermeiro", "telefone": "11999999999"},
        )
        assert updated_employee.status_code == 200, updated_employee.text
        assert updated_employee.json()["cargo"] == "Enfermeiro"

        users = await client.get("/api/usuarios/", headers=local_headers)
        assert users.status_code == 200, users.text
        user_ids = {item["id"] for item in users.json()}
        assert user_payload["id"] in user_ids
        assert other["user_id"] not in user_ids

        get_user = await client.get(f"/api/usuarios/{user_payload['id']}", headers=local_headers)
        assert get_user.status_code == 200, get_user.text
        other_user = await client.get(f"/api/usuarios/{other['user_id']}", headers=local_headers)
        assert other_user.status_code == 404

        updated_user = await client.put(
            f"/api/usuarios/{user_payload['id']}",
            headers=local_headers,
            json={"nome": "Usuario Local Atualizado"},
        )
        assert updated_user.status_code == 200, updated_user.text
        assert updated_user.json()["nome"] == "Usuario Local Atualizado"

        assign_ilpi_admin = await client.post(
            f"/api/usuarios/{user_payload['id']}/perfis",
            headers=local_headers,
            json={"perfil_id": context["perfil_id"]},
        )
        assert assign_ilpi_admin.status_code in {201, 409}
        platform_profile_id = (await db.execute(select(m.Perfil.id).where(m.Perfil.chave == "platform_superuser"))).scalar_one()
        assign_platform = await client.post(
            f"/api/usuarios/{user_payload['id']}/perfis",
            headers=local_headers,
            json={"perfil_id": platform_profile_id},
        )
        assert assign_platform.status_code == 403

        login_local = await _login(client, user_payload["email"], user_payload["senha_temporaria"])
        assert login_local.status_code == 200, login_local.text
        password_local = await client.put(
            "/api/auth/password",
            headers=_auth_headers(login_local.json()["access_token"]),
            json={"nova_senha": LOCAL_PASSWORD, "confirmar_senha": LOCAL_PASSWORD},
        )
        assert password_local.status_code == 200, password_local.text
        login_context = await _login(
            client,
            user_payload["email"],
            LOCAL_PASSWORD,
            scope="ilpi",
            ilpi_id=context["ilpi_id"],
            perfil_id=context["perfil_id"],
        )
        assert login_context.status_code == 200, login_context.text
        local_user_headers = _auth_headers(login_context.json()["access_token"])
        token_rows_before = (
            await db.execute(
                select(m.RefreshToken).where(
                    m.RefreshToken.user_id == user_payload["id"],
                    m.RefreshToken.ilpi_id == context["ilpi_id"],
                    m.RefreshToken.revoked_at.is_(None),
                )
            )
        ).scalars().all()
        assert token_rows_before

        unlink_employee = await client.delete(f"/api/funcionarios/{sem_login_id}/vincular-usuario", headers=local_headers)
        assert unlink_employee.status_code == 200, unlink_employee.text
        assert unlink_employee.json()["usuario_id"] is None

        relink = await client.post(
            f"/api/funcionarios/{sem_login_id}/vincular-usuario",
            headers=local_headers,
            json={"usuario_id": user_payload["id"]},
        )
        assert relink.status_code == 200, relink.text

        inactivate = await client.delete(f"/api/funcionarios/{sem_login_id}", headers=local_headers)
        assert inactivate.status_code == 204
        persisted = (await db.execute(select(m.Funcionario).where(m.Funcionario.id == sem_login_id))).scalar_one()
        assert persisted.situacao == "inativo"

        denied_inactive_employee = await client.get("/api/funcionarios/", headers=local_user_headers)
        assert denied_inactive_employee.status_code == 403

        revoke_access = await client.delete(f"/api/usuarios/{user_payload['id']}/acesso", headers=local_headers)
        assert revoke_access.status_code == 200, revoke_access.text
        active_links = (
            await db.execute(
                select(m.UsuarioIlpiPerfil).where(
                    m.UsuarioIlpiPerfil.usuario_id == user_payload["id"],
                    m.UsuarioIlpiPerfil.ilpi_id == context["ilpi_id"],
                    m.UsuarioIlpiPerfil.situacao == "ativo",
                )
            )
        ).scalars().all()
        assert active_links == []
        active_tokens_after = (
            await db.execute(
                select(m.RefreshToken).where(
                    m.RefreshToken.user_id == user_payload["id"],
                    m.RefreshToken.ilpi_id == context["ilpi_id"],
                    m.RefreshToken.revoked_at.is_(None),
                )
            )
        ).scalars().all()
        assert active_tokens_after == []

        rollback_count_before = (await db.execute(text("SELECT COUNT(*) FROM auditoria"))).scalar_one()
        rollback_attempt = await client.post(
            "/api/funcionarios/",
            headers=local_headers,
            json={"nome": "Rollback CPF", "cpf": "93541134780"},
        )
        assert rollback_attempt.status_code == 409
        rollback_count_after = (await db.execute(text("SELECT COUNT(*) FROM auditoria"))).scalar_one()
        assert rollback_count_after == rollback_count_before

        audit_actions = set((await db.execute(select(m.Auditoria.acao))).scalars().all())
        assert {
            "funcionario.criado",
            "funcionario.atualizado",
            "funcionario.inativado",
            "funcionario.usuario_vinculado",
            "funcionario.usuario_desvinculado",
            "usuario.criado",
            "usuario.atualizado",
            "usuario_ilpi_perfil.criado",
            "usuario.acesso_revogado",
        }.issubset(audit_actions)

        user_columns = [row[1] for row in (await db.execute(text("PRAGMA table_info(users)"))).all()] if isinstance(fase3b_db, pathlib.Path) else [row.column_name for row in (await db.execute(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'users'"))).all()]
        assert "ilpi_id" not in user_columns
        counts = {
            key: (await db.execute(text(query))).scalar_one()
            for key, query in {
                "permissoes": "SELECT COUNT(*) FROM permissoes",
                "template_perfis": "SELECT COUNT(*) FROM perfis WHERE ilpi_id IS NULL",
                "template_permissoes": "SELECT COUNT(*) FROM perfil_permissoes pp JOIN perfis p ON p.id = pp.perfil_id WHERE p.ilpi_id IS NULL",
            }.items()
        }
        assert counts == {"permissoes": 40, "template_perfis": 2, "template_permissoes": 51}

        platform_still_works = await client.get("/api/instituicoes/", headers=_auth_headers(context["global_access"]))
        assert platform_still_works.status_code == 200, platform_still_works.text

    asyncio.run(_with_client(fase3b_db, monkeypatch, scenario))
