"""Disposable-database tests for Phase C.3: Sinais Vitais — registro mínimo seguro.

Covers:
- AUTH/RBAC (tests 01-07)
- TENANT isolation (tests 08-14)
- AUTORIA from session + audit (tests 15-18)
- REGISTRO mínimo + validações técnicas (tests 19-36)
- IMUTABILIDADE (tests 37-40)
- SEGURANÇA / sem integrações automáticas (tests 41-46)
- DATABASES descartáveis (tests 47-48)

Official decisions encoded (PLAN C.3A, congeladas):
- Modelo colunar mantido; sem tipo+valor+unidade; sem catálogo de unidades.
- Pressão arterial em duas colunas; sistolica<=diastolica NÃO bloqueada.
- Correção clínica = novo INSERT; sem PUT; sem DELETE (405).
- Autoria sempre da sessão (Funcionario ativo -> nome; fallback User.nome).
- Tenant sempre SecurityContext.ilpi_id; payload hostil ignorado.
- Pelo menos UM sinal vital por registro, senão 422.
- `data` = momento da medição (default agora UTC); sem created_at novo.
- Sem migration nova (head 010 já contém permissões + modelo suficiente).
- Sem alertas, intercorrências ou alterações de Grau automáticas.
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
    AUTH_CONTEXT_REQUIRED,
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
        capture_output=True, text=True, encoding="utf-8", errors="replace",
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
def sinais_db(request: pytest.FixtureRequest, tmp_path: pathlib.Path) -> pathlib.Path | str:
    if request.param == "sqlite":
        path = tmp_path / "c3-sinais-vitais.db"
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


def _new_user(*, exige_troca_senha: bool = False, nome: str = "Usuario C.3") -> m.User:
    user_id = _new_id()
    return m.User(
        id=user_id,
        nome=nome,
        email=f"c3-{user_id}@example.com",
        password_hash="fixture-password-hash",
        ativo=True,
        exige_troca_senha=exige_troca_senha,
    )


def _new_institution(name: str = "ILPI C.3") -> m.Instituicao:
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
    profile_key: str = "sinais_admin",
    exige_troca_senha: bool = False,
    nome: str = "Usuario C.3",
) -> m.User:
    user = _new_user(exige_troca_senha=exige_troca_senha, nome=nome)
    profile = m.Perfil(
        id=_new_id(),
        ilpi_id=institution.id,
        nome="Perfil Fixture C.3",
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
        cargo="Tecnico de Enfermagem",
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


async def _create_residente(db: AsyncSession, ilpi_id: str, nome: str = "Residente Sinais") -> m.Residente:
    res = m.Residente(
        id=_new_id(),
        instituicao_id=ilpi_id,
        nome=nome,
        data_nascimento=date(1940, 5, 1),
    )
    db.add(res)
    await db.flush()
    return res


async def _create_sinal_in_db(
    db: AsyncSession,
    residente_id: str,
    ilpi_id: str,
    *,
    temperatura: float | None = 36.5,
    data: datetime | None = None,
    profissional: str = "Profissional Teste",
) -> m.SinalVital:
    row = m.SinalVital(
        id=_new_id(),
        residente_id=residente_id,
        ilpi_id=ilpi_id,
        temperatura=temperatura,
        profissional=profissional,
        data=data or datetime.now(timezone.utc),
        observacao="semente",
    )
    db.add(row)
    await db.flush()
    return row


# =============================================================================
# AUTH/RBAC — 01 a 07
# =============================================================================

def test_01_sem_autenticacao_401(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        db.add(_new_institution())
        await db.flush()
        r = await client.get("/api/sinais-vitais/", headers={})
        assert r.status_code in (401, 403)
        r2 = await client.post("/api/sinais-vitais/", json={"residente_id": _new_id(), "temperatura": 36.5})
        assert r2.status_code in (401, 403)
    asyncio.run(_with_client(sinais_db, scenario))


def test_02_first_password_change_required(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:ler"}, exige_troca_senha=True)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.get("/api/sinais-vitais/", headers=headers)
        assert r.status_code == 403
        assert _detail_code(r) == FIRST_PASSWORD_CHANGE_REQUIRED
    asyncio.run(_with_client(sinais_db, scenario))


def test_03_ler_sem_permissao_403(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions=set())
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.get("/api/sinais-vitais/", headers=headers)
        assert r.status_code == 403
        assert _detail_code(r) == PERMISSION_DENIED
    asyncio.run(_with_client(sinais_db, scenario))


def test_04_criar_sem_permissao_403(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:ler"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente.id, "temperatura": 36.5},
            headers=headers,
        )
        assert r.status_code == 403
        assert _detail_code(r) == PERMISSION_DENIED
    asyncio.run(_with_client(sinais_db, scenario))


def test_05_ler_com_permissao(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:ler"})
        await db.commit()
        residente = await _create_residente(db, ilpi.id)
        row = await _create_sinal_in_db(db, residente.id, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.get("/api/sinais-vitais/", headers=headers)
        assert r.status_code == 200
        assert any(item["id"] == row.id for item in r.json())
        r2 = await client.get(f"/api/sinais-vitais/{row.id}", headers=headers)
        assert r2.status_code == 200
        assert r2.json()["id"] == row.id
    asyncio.run(_with_client(sinais_db, scenario))


def test_06_criar_com_permissao(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente.id, "temperatura": 36.8},
            headers=headers,
        )
        assert r.status_code == 201
        assert r.json()["residente_id"] == residente.id
        assert r.json()["temperatura"] == 36.8
    asyncio.run(_with_client(sinais_db, scenario))


def test_07_platform_superuser_bloqueado(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        platform_user = await _create_platform_user(db)
        await db.commit()
        residente = await _create_residente(db, ilpi.id)
        row = await _create_sinal_in_db(db, residente.id, ilpi.id)
        await db.commit()
        headers = _auth_headers(platform_user, scope="global")
        r = await client.get("/api/sinais-vitais/", headers=headers)
        assert r.status_code == 403
        assert _detail_code(r) == PERMISSION_DENIED
        r2 = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente.id, "temperatura": 36.5},
            headers=headers,
        )
        assert r2.status_code == 403
        assert _detail_code(r2) == PERMISSION_DENIED
        r3 = await client.get(f"/api/sinais-vitais/{row.id}", headers=headers)
        assert r3.status_code == 403
        assert _detail_code(r3) == PERMISSION_DENIED
    asyncio.run(_with_client(sinais_db, scenario))


# =============================================================================
# TENANT — 08 a 14
# =============================================================================

def test_08_lista_somente_tenant_proprio(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi_a = _new_institution(name="ILPI A")
        ilpi_b = _new_institution(name="ILPI B")
        db.add_all([ilpi_a, ilpi_b])
        await db.flush()
        user_a = await _create_ilpi_user(db, ilpi_a, permissions={"sinais_vitais:ler"})
        await db.commit()
        residente_b = await _create_residente(db, ilpi_b.id, nome="Residente B")
        row_b = await _create_sinal_in_db(db, residente_b.id, ilpi_b.id)
        await db.commit()
        headers = _auth_headers(user_a, scope="ilpi", ilpi_id=ilpi_a.id)
        r = await client.get("/api/sinais-vitais/", headers=headers)
        assert r.status_code == 200
        assert all(item["id"] != row_b.id for item in r.json())
    asyncio.run(_with_client(sinais_db, scenario))


def test_09_get_cross_tenant_404(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi_a = _new_institution(name="ILPI A")
        ilpi_b = _new_institution(name="ILPI B")
        db.add_all([ilpi_a, ilpi_b])
        await db.flush()
        user_a = await _create_ilpi_user(db, ilpi_a, permissions={"sinais_vitais:ler"})
        await db.commit()
        residente_b = await _create_residente(db, ilpi_b.id, nome="Residente B")
        row_b = await _create_sinal_in_db(db, residente_b.id, ilpi_b.id)
        await db.commit()
        headers = _auth_headers(user_a, scope="ilpi", ilpi_id=ilpi_a.id)
        r = await client.get(f"/api/sinais-vitais/{row_b.id}", headers=headers)
        assert r.status_code == 404
        assert _detail_code(r) == RESOURCE_NOT_FOUND
    asyncio.run(_with_client(sinais_db, scenario))


def test_10_post_residente_cross_tenant_404(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi_a = _new_institution(name="ILPI A")
        ilpi_b = _new_institution(name="ILPI B")
        db.add_all([ilpi_a, ilpi_b])
        await db.flush()
        residente_b = await _create_residente(db, ilpi_b.id, nome="Residente B")
        user_a = await _create_ilpi_user(db, ilpi_a, permissions={"sinais_vitais:criar"})
        await db.commit()
        headers = _auth_headers(user_a, scope="ilpi", ilpi_id=ilpi_a.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente_b.id, "temperatura": 37.0},
            headers=headers,
        )
        assert r.status_code == 404
        assert _detail_code(r) == RESOURCE_NOT_FOUND
    asyncio.run(_with_client(sinais_db, scenario))


def test_11_residente_inexistente_404(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:criar"})
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": _new_id(), "temperatura": 37.0},
            headers=headers,
        )
        assert r.status_code == 404
        assert _detail_code(r) == RESOURCE_NOT_FOUND
    asyncio.run(_with_client(sinais_db, scenario))


def test_12_payload_hostil_ilpi_id_ignorado(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi_a = _new_institution(name="ILPI A")
        ilpi_b = _new_institution(name="ILPI B")
        db.add_all([ilpi_a, ilpi_b])
        await db.flush()
        residente_a = await _create_residente(db, ilpi_a.id, nome="Residente A")
        user_a = await _create_ilpi_user(db, ilpi_a, permissions={"sinais_vitais:criar"})
        await db.commit()
        headers = _auth_headers(user_a, scope="ilpi", ilpi_id=ilpi_a.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente_a.id, "temperatura": 36.6, "ilpi_id": ilpi_b.id},
            headers=headers,
        )
        assert r.status_code == 201
        row_id = r.json()["id"]
        stored = (await db.execute(select(m.SinalVital).where(m.SinalVital.id == row_id))).scalar_one()
        assert stored.ilpi_id == ilpi_a.id
    asyncio.run(_with_client(sinais_db, scenario))


def test_13_payload_hostil_instituicao_id_ignorado(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi_a = _new_institution(name="ILPI A")
        ilpi_b = _new_institution(name="ILPI B")
        db.add_all([ilpi_a, ilpi_b])
        await db.flush()
        residente_a = await _create_residente(db, ilpi_a.id, nome="Residente A")
        user_a = await _create_ilpi_user(db, ilpi_a, permissions={"sinais_vitais:criar"})
        await db.commit()
        headers = _auth_headers(user_a, scope="ilpi", ilpi_id=ilpi_a.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente_a.id, "peso": 70.5, "instituicao_id": ilpi_b.id},
            headers=headers,
        )
        assert r.status_code == 201
        row_id = r.json()["id"]
        stored = (await db.execute(select(m.SinalVital).where(m.SinalVital.id == row_id))).scalar_one()
        assert stored.ilpi_id == ilpi_a.id
    asyncio.run(_with_client(sinais_db, scenario))


def test_14_contexto_invalido_403(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi_a = _new_institution(name="ILPI A")
        ilpi_b = _new_institution(name="ILPI B")
        db.add_all([ilpi_a, ilpi_b])
        await db.flush()
        user_a = await _create_ilpi_user(db, ilpi_a, permissions={"sinais_vitais:ler"})
        await db.commit()
        # Seletor de tenant sem vínculo válido na base: contexto indisponível.
        headers = _auth_headers(user_a, scope="ilpi", ilpi_id=ilpi_b.id)
        r = await client.get("/api/sinais-vitais/", headers=headers)
        assert r.status_code == 403
        assert _detail_code(r) == AUTH_CONTEXT_REQUIRED
    asyncio.run(_with_client(sinais_db, scenario))


# =============================================================================
# AUTORIA — 15 a 18
# =============================================================================

def test_15_profissional_vem_da_sessao(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:criar"}, nome="Enf. Plantao")
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente.id, "temperatura": 36.7},
            headers=headers,
        )
        assert r.status_code == 201
        assert r.json()["profissional"] == "Enf. Plantao"
    asyncio.run(_with_client(sinais_db, scenario))


def test_16_spoof_autoria_ignorado(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:criar"}, nome="Tec. Vera")
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={
                "residente_id": residente.id,
                "temperatura": 36.7,
                "profissional": "Pessoa Errada",
                "usuario_id": _new_id(),
                "autor": "Outro Autor",
                "executor": "Outro Executor",
            },
            headers=headers,
        )
        assert r.status_code == 201
        assert r.json()["profissional"] == "Tec. Vera"
    asyncio.run(_with_client(sinais_db, scenario))


def test_17_auditoria_usuario_id_correta(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente.id, "glicemia": 110},
            headers=headers,
        )
        assert r.status_code == 201
        row_id = r.json()["id"]
        audits = (
            await db.execute(
                select(m.Auditoria).where(
                    m.Auditoria.entidade == "sinais_vitais",
                    m.Auditoria.acao == "sinais_vitais.criar",
                    m.Auditoria.registro_id == row_id,
                )
            )
        ).scalars().all()
        assert len(audits) == 1
        assert audits[0].usuario_id == user.id
    asyncio.run(_with_client(sinais_db, scenario))


def test_18_auditoria_ilpi_id_correta(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente.id, "peso": 68.2},
            headers=headers,
        )
        assert r.status_code == 201
        row_id = r.json()["id"]
        audits = (
            await db.execute(
                select(m.Auditoria).where(
                    m.Auditoria.entidade == "sinais_vitais",
                    m.Auditoria.acao == "sinais_vitais.criar",
                    m.Auditoria.registro_id == row_id,
                )
            )
        ).scalars().all()
        assert len(audits) == 1
        assert audits[0].ilpi_id == ilpi.id
    asyncio.run(_with_client(sinais_db, scenario))


# =============================================================================
# REGISTRO — 19 a 36
# =============================================================================

def test_19_criar_temperatura(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente.id, "temperatura": 37.2},
            headers=headers,
        )
        assert r.status_code == 201
        assert r.json()["temperatura"] == 37.2
    asyncio.run(_with_client(sinais_db, scenario))


def test_20_criar_pressao_120_80(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente.id, "pressao_sistolica": 120, "pressao_diastolica": 80},
            headers=headers,
        )
        assert r.status_code == 201
        assert r.json()["pressao_sistolica"] == 120
        assert r.json()["pressao_diastolica"] == 80
    asyncio.run(_with_client(sinais_db, scenario))


def test_21_criar_saturacao(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente.id, "saturacao": 98},
            headers=headers,
        )
        assert r.status_code == 201
        assert r.json()["saturacao"] == 98
    asyncio.run(_with_client(sinais_db, scenario))


def test_22_criar_multiplos_sinais_mesma_coleta(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        payload = {
            "residente_id": residente.id,
            "temperatura": 36.9,
            "pressao_sistolica": 130,
            "pressao_diastolica": 85,
            "frequencia_cardiaca": 78,
            "frequencia_respiratoria": 16,
            "saturacao": 97,
            "glicemia": 105.5,
            "peso": 72.3,
            "observacao": "coleta completa do plantao",
        }
        r = await client.post("/api/sinais-vitais/", json=payload, headers=headers)
        assert r.status_code == 201
        data = r.json()
        assert data["temperatura"] == 36.9
        assert data["frequencia_cardiaca"] == 78
        assert data["frequencia_respiratoria"] == 16
        assert data["glicemia"] == 105.5
        assert data["peso"] == 72.3
    asyncio.run(_with_client(sinais_db, scenario))


def test_23_todos_vitais_null_422(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente.id},
            headers=headers,
        )
        assert r.status_code == 422
    asyncio.run(_with_client(sinais_db, scenario))


def test_24_saturacao_acima_100_422(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente.id, "saturacao": 101},
            headers=headers,
        )
        assert r.status_code == 422
    asyncio.run(_with_client(sinais_db, scenario))


def test_25_saturacao_negativa_422(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente.id, "saturacao": -1},
            headers=headers,
        )
        assert r.status_code == 422
    asyncio.run(_with_client(sinais_db, scenario))


def test_26_glicemia_negativa_422(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente.id, "glicemia": -0.1},
            headers=headers,
        )
        assert r.status_code == 422
    asyncio.run(_with_client(sinais_db, scenario))


def test_27_peso_negativo_422(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente.id, "peso": -70},
            headers=headers,
        )
        assert r.status_code == 422
    asyncio.run(_with_client(sinais_db, scenario))


def test_28_pressao_negativa_422(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente.id, "pressao_sistolica": -120, "pressao_diastolica": 80},
            headers=headers,
        )
        assert r.status_code == 422
        r2 = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente.id, "pressao_sistolica": 120, "pressao_diastolica": -80},
            headers=headers,
        )
        assert r2.status_code == 422
    asyncio.run(_with_client(sinais_db, scenario))


def test_29_frequencia_cardiaca_negativa_422(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente.id, "frequencia_cardiaca": -60},
            headers=headers,
        )
        assert r.status_code == 422
    asyncio.run(_with_client(sinais_db, scenario))


def test_30_frequencia_respiratoria_negativa_422(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente.id, "frequencia_respiratoria": -12},
            headers=headers,
        )
        assert r.status_code == 422
    asyncio.run(_with_client(sinais_db, scenario))


def test_31_sistolica_menor_que_diastolica_nao_bloqueada(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente.id, "pressao_sistolica": 80, "pressao_diastolica": 120},
            headers=headers,
        )
        assert r.status_code == 201
        assert r.json()["pressao_sistolica"] == 80
        assert r.json()["pressao_diastolica"] == 120
    asyncio.run(_with_client(sinais_db, scenario))


def test_32_data_default_agora(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        before = datetime.now(timezone.utc)
        r = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente.id, "temperatura": 36.5},
            headers=headers,
        )
        after = datetime.now(timezone.utc)
        assert r.status_code == 201
        stored = datetime.fromisoformat(r.json()["data"])
        if stored.tzinfo is None:
            stored = stored.replace(tzinfo=timezone.utc)
        assert before - timedelta(minutes=5) <= stored <= after + timedelta(minutes=5)
    asyncio.run(_with_client(sinais_db, scenario))


def test_33_data_enviada_preservada(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={
                "residente_id": residente.id,
                "temperatura": 38.1,
                "data": "2026-03-15T10:30:00+00:00",
            },
            headers=headers,
        )
        assert r.status_code == 201
        stored = datetime.fromisoformat(r.json()["data"])
        if stored.tzinfo is None:
            stored = stored.replace(tzinfo=timezone.utc)
        assert stored == datetime(2026, 3, 15, 10, 30, tzinfo=timezone.utc)
    asyncio.run(_with_client(sinais_db, scenario))


def test_34_observacao_preservada(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(
            db, ilpi, permissions={"sinais_vitais:criar", "sinais_vitais:ler"}
        )
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={
                "residente_id": residente.id,
                "saturacao": 95,
                "observacao": "  medida apos caminhada  ",
            },
            headers=headers,
        )
        assert r.status_code == 201
        row_id = r.json()["id"]
        assert r.json()["observacao"] == "medida apos caminhada"
        r2 = await client.get(f"/api/sinais-vitais/{row_id}", headers=headers)
        assert r2.json()["observacao"] == "medida apos caminhada"
    asyncio.run(_with_client(sinais_db, scenario))


def test_35_ordenacao_data_desc(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:criar", "sinais_vitais:ler"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        for day in ("2026-01-10T08:00:00+00:00", "2026-02-10T08:00:00+00:00", "2026-03-10T08:00:00+00:00"):
            r = await client.post(
                "/api/sinais-vitais/",
                json={"residente_id": residente.id, "temperatura": 36.5, "data": day},
                headers=headers,
            )
            assert r.status_code == 201
        r = await client.get("/api/sinais-vitais/", headers=headers)
        assert r.status_code == 200
        items = r.json()
        assert len(items) == 3
        dates = [datetime.fromisoformat(item["data"]) for item in items]
        assert dates == sorted(dates, reverse=True)
    asyncio.run(_with_client(sinais_db, scenario))


def test_36_filtro_por_residente_tenant_safe(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi_a = _new_institution(name="ILPI A")
        ilpi_b = _new_institution(name="ILPI B")
        db.add_all([ilpi_a, ilpi_b])
        await db.flush()
        user_a = await _create_ilpi_user(
            db, ilpi_a, permissions={"sinais_vitais:criar", "sinais_vitais:ler"}
        )
        await db.commit()
        residente_a1 = await _create_residente(db, ilpi_a.id, nome="Residente A1")
        residente_a2 = await _create_residente(db, ilpi_a.id, nome="Residente A2")
        residente_b = await _create_residente(db, ilpi_b.id, nome="Residente B")
        await _create_sinal_in_db(db, residente_a1.id, ilpi_a.id)
        await _create_sinal_in_db(db, residente_a2.id, ilpi_a.id)
        await _create_sinal_in_db(db, residente_b.id, ilpi_b.id)
        await db.commit()
        headers = _auth_headers(user_a, scope="ilpi", ilpi_id=ilpi_a.id)
        r = await client.get(
            "/api/sinais-vitais/", params={"residente_id": residente_a1.id}, headers=headers
        )
        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["residente_id"] == residente_a1.id
        # Filtro para residente de outra ILPI: 404 sem leak.
        r2 = await client.get(
            "/api/sinais-vitais/", params={"residente_id": residente_b.id}, headers=headers
        )
        assert r2.status_code == 404
        assert _detail_code(r2) == RESOURCE_NOT_FOUND
    asyncio.run(_with_client(sinais_db, scenario))


# =============================================================================
# IMUTABILIDADE — 37 a 40
# =============================================================================

def test_37_put_inexistente_bloqueado(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(
            db, ilpi, permissions={"sinais_vitais:criar", "sinais_vitais:ler"}
        )
        residente = await _create_residente(db, ilpi.id)
        row = await _create_sinal_in_db(db, residente.id, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.put(
            f"/api/sinais-vitais/{row.id}", json={"temperatura": 39.9}, headers=headers
        )
        assert r.status_code == 405
    asyncio.run(_with_client(sinais_db, scenario))


def test_38_delete_inexistente_bloqueado(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(
            db, ilpi, permissions={"sinais_vitais:criar", "sinais_vitais:ler"}
        )
        residente = await _create_residente(db, ilpi.id)
        row = await _create_sinal_in_db(db, residente.id, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.delete(f"/api/sinais-vitais/{row.id}", headers=headers)
        assert r.status_code == 405
    asyncio.run(_with_client(sinais_db, scenario))


def test_39_correcao_e_novo_insert(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(
            db, ilpi, permissions={"sinais_vitais:criar", "sinais_vitais:ler"}
        )
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r1 = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente.id, "temperatura": 39.9},
            headers=headers,
        )
        assert r1.status_code == 201
        r2 = await client.post(
            "/api/sinais-vitais/",
            json={
                "residente_id": residente.id,
                "temperatura": 36.9,
                "observacao": "correcao: leitura anterior com termometro descalibrado",
            },
            headers=headers,
        )
        assert r2.status_code == 201
        assert r1.json()["id"] != r2.json()["id"]
        r3 = await client.get("/api/sinais-vitais/", headers=headers)
        assert len(r3.json()) == 2
    asyncio.run(_with_client(sinais_db, scenario))


def test_40_registro_anterior_permanece(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(
            db, ilpi, permissions={"sinais_vitais:criar", "sinais_vitais:ler"}
        )
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r1 = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente.id, "temperatura": 39.9},
            headers=headers,
        )
        row_id = r1.json()["id"]
        r2 = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente.id, "temperatura": 36.9},
            headers=headers,
        )
        assert r2.status_code == 201
        r_get = await client.get(f"/api/sinais-vitais/{row_id}", headers=headers)
        assert r_get.status_code == 200
        assert r_get.json()["temperatura"] == 39.9
    asyncio.run(_with_client(sinais_db, scenario))


# =============================================================================
# SEGURANÇA / SEM INTEGRAÇÕES AUTOMÁTICAS — 41 a 46
# =============================================================================

def test_41_outros_modulos_clinicos_continuam_fail_closed(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(
            db, ilpi, permissions={"sinais_vitais:ler", "sinais_vitais:criar"}
        )
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        still_blocked = (
            ("get", "/api/tarefas/", None),
            ("post", "/api/tarefas/", {"residente_id": _new_id(), "descricao": "X"}),
            ("get", "/api/alertas/", None),
        )
        for method, route, payload in still_blocked:
            request = getattr(client, method)
            kwargs = {"headers": headers}
            if payload is not None:
                kwargs["json"] = payload
            response = await request(route, **kwargs)
            assert response.status_code == 403, (method, route, response.text)
            assert _detail_code(response) == PERMISSION_CATALOG_PENDING, (method, route, response.text)
    asyncio.run(_with_client(sinais_db, scenario))


def test_42_avaliacoes_continuam_funcionando(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(
            db,
            ilpi,
            permissions={"sinais_vitais:criar", "avaliacoes:ler", "avaliacoes:criar"},
        )
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post(
            "/api/avaliacoes/",
            json={"residente_id": residente.id, "tipo": "Katz"},
            headers=headers,
        )
        assert r.status_code == 201
        r2 = await client.get("/api/avaliacoes/", headers=headers)
        assert r2.status_code == 200
        assert len(r2.json()) == 1
    asyncio.run(_with_client(sinais_db, scenario))


def test_43_grau_dependencia_continua_funcionando(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(
            db,
            ilpi,
            permissions={"sinais_vitais:criar", "grau_dependencia:ler", "grau_dependencia:criar"},
        )
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post(
            "/api/graus-dependencia/",
            json={
                "residente_id": residente.id,
                "classificacao": "Grau II",
                "origem": "manual",
                "justificativa": "Confirmacao profissional C.3",
            },
            headers=headers,
        )
        assert r.status_code == 201
        assert r.json()["classificacao"] == "Grau II"
    asyncio.run(_with_client(sinais_db, scenario))


def test_44_nenhum_dado_alterado_automaticamente_em_grau(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente.id, "temperatura": 38.5},
            headers=headers,
        )
        assert r.status_code == 201
        graus = (
            await db.execute(
                select(m.GrauDependencia).where(m.GrauDependencia.residente_id == residente.id)
            )
        ).scalars().all()
        assert graus == []
        res = (await db.execute(select(m.Residente).where(m.Residente.id == residente.id))).scalar_one()
        assert res.grau_dependencia is None
    asyncio.run(_with_client(sinais_db, scenario))


def test_45_nenhum_alerta_automatico_criado(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente.id, "saturacao": 88},
            headers=headers,
        )
        assert r.status_code == 201
        total = (await db.execute(select(func.count(m.Alerta.id)))).scalar_one()
        assert total == 0
    asyncio.run(_with_client(sinais_db, scenario))


def test_46_nenhuma_intercorrencia_automatica_criada(sinais_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"sinais_vitais:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post(
            "/api/sinais-vitais/",
            json={"residente_id": residente.id, "temperatura": 39.8},
            headers=headers,
        )
        assert r.status_code == 201
        total = (await db.execute(select(func.count(m.Intercorrencia.id)))).scalar_one()
        assert total == 0
    asyncio.run(_with_client(sinais_db, scenario))


# =============================================================================
# DATABASES — 47 e 48 (cobertos pelo fixture sqlite/postgresql em cada teste)
# =============================================================================

def test_47_banco_oficial_intacto(sinais_db):
    _assert_disposable_database(sinais_db)


def test_48_catalogo_sem_novas_permissoes(sinais_db):
    """D.3 adiciona 7 permissoes de admissao; HEAD tem 92 pela migration 016."""

    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        total = (await db.execute(select(func.count(m.Permissao.id)))).scalar_one()
        assert total == 92
        novas = (
            await db.execute(
                select(m.Permissao).where(
                    m.Permissao.chave.in_(["sinais_vitais:atualizar", "sinais_vitais:inativar"])
                )
            )
        ).scalars().all()
        assert novas == []
        chaves = (
            await db.execute(
                select(m.Permissao.chave).where(
                    m.Permissao.chave.in_(["sinais_vitais:ler", "sinais_vitais:criar"])
                )
            )
        ).scalars().all()
        assert set(chaves) == {"sinais_vitais:ler", "sinais_vitais:criar"}

    asyncio.run(_with_client(sinais_db, scenario))
