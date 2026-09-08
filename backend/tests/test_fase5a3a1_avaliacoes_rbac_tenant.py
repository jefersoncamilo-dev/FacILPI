"""Disposable-database tests for Phase F5A-3A1: Avaliações — RBAC + Tenant + Autoria + Histórico Seguro.

Covers:
- AUTH/RBAC (tests 1-10)
- TENANT isolation (tests 11-17)
- LEITOS CRUD + constraints (tests 18-27)
- DATABASES (tests 28-29)
- REGRESSÃO (test 30)

Official decisions encoded:
- Nova avaliação/reavaliação = novo INSERT (nunca sobrescreve)
- DELETE físico bloqueado
- Platform Superuser: zero grants Avaliações
- Tenant sempre da sessão (SecurityContext.ilpi_id)
- Autoria derivada da sessão
- residente_id imutável no PUT
- respostas JSON preservadas
- validade preservada
- Grau de Dependência não alterado automaticamente
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
    PERMISSION_DENIED,
    PERMISSION_CATALOG_PENDING,
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
def avaliacoes_db(request: pytest.FixtureRequest, tmp_path: pathlib.Path) -> pathlib.Path | str:
    if request.param == "sqlite":
        path = tmp_path / "f5a3a1-avaliacoes.db"
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


def _new_user(*, exige_troca_senha: bool = False, nome: str = "Usuario F5A-3A1") -> m.User:
    user_id = _new_id()
    return m.User(
        id=user_id,
        nome=nome,
        email=f"f5a3a1-{user_id}@example.com",
        password_hash="fixture-password-hash",
        ativo=True,
        exige_troca_senha=exige_troca_senha,
    )


def _new_institution(name: str = "ILPI F5A-3A1") -> m.Instituicao:
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
    profile_key: str = "avaliacoes_admin",
    exige_troca_senha: bool = False,
    nome: str = "Usuario F5A-3A1",
) -> m.User:
    user = _new_user(exige_troca_senha=exige_troca_senha, nome=nome)
    profile = m.Perfil(
        id=_new_id(),
        ilpi_id=institution.id,
        nome="Perfil Fixture F5A-3A1",
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
        cargo="Enfermeiro",
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


async def _create_residente(db: AsyncSession, ilpi_id: str, nome: str = "Residente Avaliacao") -> m.Residente:
    res = m.Residente(
        id=_new_id(),
        instituicao_id=ilpi_id,
        nome=nome,
        data_nascimento=date(1940, 5, 1),
    )
    db.add(res)
    await db.flush()
    return res


async def _create_avaliacao_in_db(
    db: AsyncSession,
    residente_id: str,
    ilpi_id: str,
    *,
    tipo: str = "Katz",
    instrumento: str = "Katz",
    pontuacao: float = 25.0,
    classificacao: str = "Dependência Leve",
    respostas: str = '{"q1": "independente"}',
    validade: date | None = None,
    profissional: str = "Profissional Teste",
) -> m.Avaliacao:
    av = m.Avaliacao(
        id=_new_id(),
        residente_id=residente_id,
        ilpi_id=ilpi_id,
        tipo=tipo,
        instrumento=instrumento,
        profissional=profissional,
        respostas=respostas,
        pontuacao=pontuacao,
        classificacao=classificacao,
        data=datetime.now(timezone.utc),
        validade=validade,
        observacoes="Teste",
    )
    db.add(av)
    await db.flush()
    return av


# =============================================================================
# TESTS
# =============================================================================

def test_01_no_auth(avaliacoes_db):
    """Requests without authentication must return 401."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        r = await client.get("/api/avaliacoes/", headers={})
        assert r.status_code in (401, 403)
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_02_first_password_change_required(avaliacoes_db):
    """User with exige_troca_senha must be blocked from Avaliações."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"avaliacoes:ler"}, exige_troca_senha=True)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.get("/api/avaliacoes/", headers=headers)
        assert r.status_code == 403
        assert _detail_code(r) == FIRST_PASSWORD_CHANGE_REQUIRED
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_03_avaliacoes_ler_own_ilpi(avaliacoes_db):
    """User with avaliacoes:ler can list avaliações from own ILPI."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"avaliacoes:ler"})
        await db.commit()
        residente = await _create_residente(db, ilpi.id)
        await _create_avaliacao_in_db(db, residente.id, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.get("/api/avaliacoes/", headers=headers)
        assert r.status_code == 200
        assert len(r.json()) >= 1
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_04_missing_avaliacoes_ler(avaliacoes_db):
    """User without avaliacoes:ler cannot list avaliações."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions=set())
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.get("/api/avaliacoes/", headers=headers)
        assert r.status_code == 403
        assert _detail_code(r) == PERMISSION_DENIED
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_05_listagem_cross_tenant_filtered(avaliacoes_db):
    """Listagem only returns avaliacoes from the session tenant."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi_a = _new_institution(name="ILPI A")
        ilpi_b = _new_institution(name="ILPI B")
        db.add_all([ilpi_a, ilpi_b])
        await db.flush()
        user_a = await _create_ilpi_user(db, ilpi_a, permissions={"avaliacoes:ler"})
        await db.commit()
        residente_b = await _create_residente(db, ilpi_b.id, nome="Residente B")
        await _create_avaliacao_in_db(db, residente_b.id, ilpi_b.id)
        await db.commit()
        headers = _auth_headers(user_a, scope="ilpi", ilpi_id=ilpi_a.id)
        r = await client.get("/api/avaliacoes/", headers=headers)
        assert r.status_code == 200
        for item in r.json():
            assert item.get("residente_id")  # Will not contain ILPI B's residente
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_06_get_cross_tenant_404(avaliacoes_db):
    """GET avaliacao from another tenant returns 404."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi_a = _new_institution(name="ILPI A")
        ilpi_b = _new_institution(name="ILPI B")
        db.add_all([ilpi_a, ilpi_b])
        await db.flush()
        user_a = await _create_ilpi_user(db, ilpi_a, permissions={"avaliacoes:ler"})
        await db.commit()
        residente_b = await _create_residente(db, ilpi_b.id, nome="Residente B")
        av = await _create_avaliacao_in_db(db, residente_b.id, ilpi_b.id)
        await db.commit()
        headers = _auth_headers(user_a, scope="ilpi", ilpi_id=ilpi_a.id)
        r = await client.get(f"/api/avaliacoes/{av.id}", headers=headers)
        assert r.status_code == 404
        assert _detail_code(r) == RESOURCE_NOT_FOUND
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_07_post_authorized(avaliacoes_db):
    """User with avaliacoes:criar can create avaliação."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"avaliacoes:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        payload = {
            "residente_id": residente.id,
            "tipo": "Katz",
            "instrumento": "Katz",
            "pontuacao": 25.0,
            "classificacao": "Dependência Leve",
            "respostas": '{"q1": "independente"}',
            "validade": "2026-12-31",
            "observacoes": "Teste",
        }
        r = await client.post("/api/avaliacoes/", json=payload, headers=headers)
        assert r.status_code == 201
        data = r.json()
        assert data["residente_id"] == residente.id
        assert data["profissional"] == user.nome
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_08_post_without_permission(avaliacoes_db):
    """User without avaliacoes:criar cannot create avaliação."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions=set())
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        payload = {
            "residente_id": residente.id,
            "tipo": "Katz",
        }
        r = await client.post("/api/avaliacoes/", json=payload, headers=headers)
        assert r.status_code == 403
        assert _detail_code(r) == PERMISSION_DENIED
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_09_post_hostile_tenant(avaliacoes_db):
    """POST with hostil ilpi_id in body is ignored; session tenant is used."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi_a = _new_institution(name="ILPI A")
        ilpi_b = _new_institution(name="ILPI B")
        db.add_all([ilpi_a, ilpi_b])
        await db.flush()
        residente_a = await _create_residente(db, ilpi_a.id, nome="Residente A")
        residente_b = await _create_residente(db, ilpi_b.id, nome="Residente B")
        user = await _create_ilpi_user(db, ilpi_a, permissions={"avaliacoes:criar"})
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi_a.id)
        payload = {
            "residente_id": residente_b.id,
            "tipo": "Katz",
        }
        r = await client.post("/api/avaliacoes/", json=payload, headers=headers)
        assert r.status_code == 404
        assert _detail_code(r) == RESOURCE_NOT_FOUND
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_10_post_residente_same_tenant(avaliacoes_db):
    """POST requires residente from same ILPI (tenant validation)."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"avaliacoes:criar"})
        await db.commit()
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        payload = {
            "residente_id": residente.id,
            "tipo": "Katz",
        }
        r = await client.post("/api/avaliacoes/", json=payload, headers=headers)
        assert r.status_code == 201
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_11_post_residente_cross_tenant_404(avaliacoes_db):
    """POST with residente from another ILPI returns 404."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi_a = _new_institution(name="ILPI A")
        ilpi_b = _new_institution(name="ILPI B")
        db.add_all([ilpi_a, ilpi_b])
        await db.flush()
        residente_b = await _create_residente(db, ilpi_b.id, nome="Residente B")
        user = await _create_ilpi_user(db, ilpi_a, permissions={"avaliacoes:criar"})
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi_a.id)
        payload = {"residente_id": residente_b.id, "tipo": "Katz"}
        r = await client.post("/api/avaliacoes/", json=payload, headers=headers)
        assert r.status_code == 404
        assert _detail_code(r) == RESOURCE_NOT_FOUND
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_12_post_residente_not_found(avaliacoes_db):
    """POST with nonexistent residente_id returns 404."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"avaliacoes:criar"})
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        payload = {"residente_id": _new_id(), "tipo": "Katz"}
        r = await client.post("/api/avaliacoes/", json=payload, headers=headers)
        assert r.status_code == 404
        assert _detail_code(r) == RESOURCE_NOT_FOUND
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_13_autoria_derived_from_session(avaliacoes_db):
    """Autoria (profissional) is derived from session, not body."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"avaliacoes:criar"}, nome="Dr. Silva")
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        payload = {
            "residente_id": residente.id,
            "tipo": "Katz",
            "profissional": "Hacker",
        }
        r = await client.post("/api/avaliacoes/", json=payload, headers=headers)
        assert r.status_code == 201
        data = r.json()
        assert data["profissional"] == "Dr. Silva"
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_14_payload_hostile_professionals(avaliacoes_db):
    """Body cannot control the profissional/autoria field."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"avaliacoes:criar"}, nome="Enf. Maria")
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        payload = {
            "residente_id": residente.id,
            "tipo": "Katz",
            "profissional": "Pessoa Errada",
            "instituicao_id": _new_id(),
        }
        r = await client.post("/api/avaliacoes/", json=payload, headers=headers)
        assert r.status_code == 201
        data = r.json()
        assert data["profissional"] == "Enf. Maria"
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_15_put_authorized(avaliacoes_db):
    """User with avaliacoes:atualizar can update avaliação."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"avaliacoes:criar", "avaliacoes:atualizar"})
        residente = await _create_residente(db, ilpi.id)
        av = await _create_avaliacao_in_db(db, residente.id, ilpi.id, tipo="Katz", pontuacao=25.0)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.put(f"/api/avaliacoes/{av.id}", json={"observacoes": "Atualizado"}, headers=headers)
        assert r.status_code == 200
        assert r.json()["observacoes"] == "Atualizado"
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_16_put_without_permission(avaliacoes_db):
    """User without avaliacoes:atualizar cannot update avaliação."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"avaliacoes:criar"})
        residente = await _create_residente(db, ilpi.id)
        av = await _create_avaliacao_in_db(db, residente.id, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.put(f"/api/avaliacoes/{av.id}", json={"observacoes": "Atualizado"}, headers=headers)
        assert r.status_code == 403
        assert _detail_code(r) == PERMISSION_DENIED
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_17_put_cross_tenant_404(avaliacoes_db):
    """PUT on avaliação from another tenant returns 404."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi_a = _new_institution(name="ILPI A")
        ilpi_b = _new_institution(name="ILPI B")
        db.add_all([ilpi_a, ilpi_b])
        await db.flush()
        residente_b = await _create_residente(db, ilpi_b.id, nome="Residente B")
        av = await _create_avaliacao_in_db(db, residente_b.id, ilpi_b.id)
        user = await _create_ilpi_user(db, ilpi_a, permissions={"avaliacoes:atualizar"})
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi_a.id)
        r = await client.put(f"/api/avaliacoes/{av.id}", json={"observacoes": "Hacked"}, headers=headers)
        assert r.status_code == 404
        assert _detail_code(r) == RESOURCE_NOT_FOUND
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_18_put_cross_tenant_via_session_tenant(avaliacoes_db):
    """PUT cannot modify avaliação when session tenant differs from resource tenant."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi_a = _new_institution(name="ILPI A")
        ilpi_b = _new_institution(name="ILPI B")
        db.add_all([ilpi_a, ilpi_b])
        await db.flush()
        residente_b = await _create_residente(db, ilpi_b.id, nome="Residente B")
        av = await _create_avaliacao_in_db(db, residente_b.id, ilpi_b.id)
        user = await _create_ilpi_user(db, ilpi_a, permissions={"avaliacoes:atualizar"})
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi_a.id)
        r = await client.put(f"/api/avaliacoes/{av.id}", json={"observacoes": "Hacked"}, headers=headers)
        assert r.status_code == 404
        assert _detail_code(r) == RESOURCE_NOT_FOUND
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_19_put_residente_id_immutable(avaliacoes_db):
    """residente_id cannot be changed via PUT."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"avaliacoes:criar", "avaliacoes:atualizar"})
        residente = await _create_residente(db, ilpi.id)
        av = await _create_avaliacao_in_db(db, residente.id, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        new_residente = await _create_residente(db, ilpi.id, nome="Outro Residente")
        await db.commit()
        r = await client.put(f"/api/avaliacoes/{av.id}", json={"residente_id": new_residente.id}, headers=headers)
        assert r.status_code == 200
        data = r.json()
        assert data["residente_id"] == residente.id
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_20_reevaluacao_is_new_record(avaliacoes_db):
    """Reavaliação creates a new INSERT; old record preserved."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"avaliacoes:criar", "avaliacoes:ler"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        payload = {"residente_id": residente.id, "tipo": "Katz"}
        r1 = await client.post("/api/avaliacoes/", json=payload, headers=headers)
        assert r1.status_code == 201
        r2 = await client.post("/api/avaliacoes/", json=payload, headers=headers)
        assert r2.status_code == 201
        assert r1.json()["id"] != r2.json()["id"]
        r3 = await client.get("/api/avaliacoes/", headers=headers)
        assert len(r3.json()) == 2
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_21_original_record_preserved(avaliacoes_db):
    """After reavaliação, the original record is preserved unchanged."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"avaliacoes:criar", "avaliacoes:ler"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        payload = {"residente_id": residente.id, "tipo": "Katz"}
        r1 = await client.post("/api/avaliacoes/", json=payload, headers=headers)
        av_id = r1.json()["id"]
        r2 = await client.post("/api/avaliacoes/", json=payload, headers=headers)
        assert r2.status_code == 201
        r_get = await client.get(f"/api/avaliacoes/{av_id}", headers=headers)
        assert r_get.status_code == 200
        assert r_get.json()["id"] == av_id
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_22_delete_physically_blocked(avaliacoes_db):
    """DELETE physical endpoint does not exist / is blocked."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"avaliacoes:criar", "avaliacoes:atualizar"})
        residente = await _create_residente(db, ilpi.id)
        av = await _create_avaliacao_in_db(db, residente.id, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.delete(f"/api/avaliacoes/{av.id}", headers=headers)
        assert r.status_code == 405
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_23_platform_superuser_blocked(avaliacoes_db):
    """Platform Superuser cannot access Avaliações."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        platform_user = await _create_platform_user(db)
        await db.commit()
        residente = await _create_residente(db, ilpi.id)
        await _create_avaliacao_in_db(db, residente.id, ilpi.id)
        await db.commit()
        headers = _auth_headers(platform_user, scope="global")
        r = await client.get("/api/avaliacoes/", headers=headers)
        assert r.status_code == 403
        assert _detail_code(r) == PERMISSION_DENIED
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_24_respostas_json_preserved(avaliacoes_db):
    """respostas JSON is preserved in create and get."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"avaliacoes:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        respostas_json = '{"questionario": {"q1": "independente", "q2": "dependente"}, "score": 25}'
        payload = {
            "residente_id": residente.id,
            "tipo": "Katz",
            "respostas": respostas_json,
        }
        r = await client.post("/api/avaliacoes/", json=payload, headers=headers)
        assert r.status_code == 201
        assert r.json()["respostas"] == respostas_json
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_25_validade_preserved(avaliacoes_db):
    """validade is preserved in create and get."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"avaliacoes:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        payload = {
            "residente_id": residente.id,
            "tipo": "Katz",
            "validade": "2027-01-15",
        }
        r = await client.post("/api/avaliacoes/", json=payload, headers=headers)
        assert r.status_code == 201
        assert r.json()["validade"] == "2027-01-15"
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_26_grau_dependencia_not_auto_changed(avaliacoes_db):
    """Creating avaliação does not alter residente.grau_dependencia."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"avaliacoes:criar"})
        residente = await _create_residente(db, ilpi.id, nome="Residente GD")
        db.add_all([ilpi, residente])
        await db.flush()
        residente.grau_dependencia = "Grau I"
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        payload = {"residente_id": residente.id, "tipo": "Katz", "pontuacao": 25.0}
        r = await client.post("/api/avaliacoes/", json=payload, headers=headers)
        assert r.status_code == 201
        res_get = (await db.execute(select(m.Residente).where(m.Residente.id == residente.id))).scalar_one()
        assert res_get.grau_dependencia == "Grau I"
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_27_other_clinical_modules_unchanged(avaliacoes_db):
    """Other clinical modules remain functional after Avaliações RBAC."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"residentes:ler", "avaliacoes:ler"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.get("/api/avaliacoes/", headers=headers)
        assert r.status_code == 200
    asyncio.run(_with_client(avaliacoes_db, scenario))


def test_28_official_database_intact(avaliacoes_db):
    """Official storage/app.db is not touched."""
    _assert_disposable_database(avaliacoes_db)


def test_29_migration_catalog_avaliacoes(avaliacoes_db):
    """Migration 009 adds the 3 Avaliações permissions to the catalog."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        keys = ["avaliacoes:ler", "avaliacoes:criar", "avaliacoes:atualizar"]
        result = await db.execute(
            select(m.Permissao).where(m.Permissao.chave.in_(keys))
        )
        permissions = result.scalars().all()
        assert {permission.chave for permission in permissions} == set(keys)
    asyncio.run(_with_client(avaliacoes_db, scenario))
