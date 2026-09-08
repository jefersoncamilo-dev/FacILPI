"""Disposable-database tests for Phase F5A-3A2: Grau de Dependência.

Covers:
- AUTH/RBAC (ler/criar only; no atualizar/inativar/confirmar)
- TENANT isolation + cross-tenant 404 without leak
- Parent residente validation
- Linked avaliacao validation (same tenant + same residente)
- Authorship from session + hostile payload ignored
- Human confirmation (no auto-creation from avaliacao)
- origem manual vs avaliacao + justificativa required
- History + substitution + single active + concurrency
- Revocation + re-confirmation after revocation
- PUT/DELETE blocked (405)
- Platform Superuser blocked (zero clinical grants)
- FIRST_PASSWORD_CHANGE_REQUIRED
- Legacy Residente.grau_dependencia frozen (no new writes)
- Avaliacao flow unchanged (no automation)

Official decisions encoded:
- graus_dependencia is the SOLE official source for new records
- Residente.grau_dependencia is frozen legacy: no writes, no sync
- At most ONE ativo per residente (partial unique index)
- New confirmation = new INSERT; history never overwritten
- Revocation is explicit; no physical DELETE
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
from sqlalchemy.exc import IntegrityError
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
def graus_db(request: pytest.FixtureRequest, tmp_path: pathlib.Path) -> pathlib.Path | str:
    if request.param == "sqlite":
        path = tmp_path / "f5a3a2-graus.db"
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


def _new_user(*, exige_troca_senha: bool = False, nome: str = "Usuario F5A-3A2") -> m.User:
    user_id = _new_id()
    return m.User(
        id=user_id,
        nome=nome,
        email=f"f5a3a2-{user_id}@example.com",
        password_hash="fixture-password-hash",
        ativo=True,
        exige_troca_senha=exige_troca_senha,
    )


def _new_institution(name: str = "ILPI F5A-3A2") -> m.Instituicao:
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
    profile_key: str = "graus_admin",
    exige_troca_senha: bool = False,
    nome: str = "Usuario F5A-3A2",
) -> m.User:
    user = _new_user(exige_troca_senha=exige_troca_senha, nome=nome)
    profile = m.Perfil(
        id=_new_id(),
        ilpi_id=institution.id,
        nome="Perfil Fixture F5A-3A2",
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


async def _create_residente(db: AsyncSession, ilpi_id: str, nome: str = "Residente Grau") -> m.Residente:
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
    classificacao: str = "Dependência Moderada",
) -> m.Avaliacao:
    av = m.Avaliacao(
        id=_new_id(),
        residente_id=residente_id,
        ilpi_id=ilpi_id,
        tipo=tipo,
        instrumento=tipo,
        profissional="Profissional Fixture",
        respostas='{"q1": "dependente"}',
        pontuacao=3.0,
        classificacao=classificacao,
        data=datetime.now(timezone.utc),
    )
    db.add(av)
    await db.flush()
    return av


def _confirm_payload(residente_id: str, **overrides):
    payload = {
        "residente_id": residente_id,
        "classificacao": "Grau II",
        "origem": "manual",
        "justificativa": "Justificativa clínica mínima",
    }
    payload.update(overrides)
    return payload


# ---------- 1. AUTH/RBAC ----------

def test_01_unauthenticated_blocked(graus_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        r = await client.get("/api/graus-dependencia/")
        assert r.status_code in (401, 403)
        r = await client.post("/api/graus-dependencia/", json=_confirm_payload(_new_id()))
        assert r.status_code in (401, 403)
    asyncio.run(_with_client(graus_db, scenario))


def test_02_ler_only_cannot_confirm(graus_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"grau_dependencia:ler"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post("/api/graus-dependencia/", json=_confirm_payload(residente.id), headers=headers)
        assert r.status_code == 403
        assert _detail_code(r) == PERMISSION_DENIED
        r = await client.get("/api/graus-dependencia/", headers=headers)
        assert r.status_code == 200
    asyncio.run(_with_client(graus_db, scenario))


def test_03_criar_only_cannot_list(graus_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"grau_dependencia:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.get("/api/graus-dependencia/", headers=headers)
        assert r.status_code == 403
        r = await client.post("/api/graus-dependencia/", json=_confirm_payload(residente.id), headers=headers)
        assert r.status_code == 201
    asyncio.run(_with_client(graus_db, scenario))


def test_04_no_speculative_permissions_in_catalog(graus_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        for chave in ("grau_dependencia:atualizar", "grau_dependencia:inativar", "grau_dependencia:confirmar"):
            row = (await db.execute(select(m.Permissao).where(m.Permissao.chave == chave))).scalar_one_or_none()
            assert row is None, f"permissao especulativa presente: {chave}"
    asyncio.run(_with_client(graus_db, scenario))


# ---------- 2. TENANT ----------

def test_05_list_tenant_filtered(graus_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi_a = _new_institution("ILPI A")
        ilpi_b = _new_institution("ILPI B")
        db.add_all([ilpi_a, ilpi_b])
        await db.flush()
        user_a = await _create_ilpi_user(db, ilpi_a, permissions={"grau_dependencia:ler", "grau_dependencia:criar"})
        user_b = await _create_ilpi_user(db, ilpi_b, permissions={"grau_dependencia:ler", "grau_dependencia:criar"})
        res_a = await _create_residente(db, ilpi_a.id, nome="Res A")
        res_b = await _create_residente(db, ilpi_b.id, nome="Res B")
        await db.commit()
        headers_a = _auth_headers(user_a, scope="ilpi", ilpi_id=ilpi_a.id)
        headers_b = _auth_headers(user_b, scope="ilpi", ilpi_id=ilpi_b.id)
        assert (await client.post("/api/graus-dependencia/", json=_confirm_payload(res_a.id), headers=headers_a)).status_code == 201
        assert (await client.post("/api/graus-dependencia/", json=_confirm_payload(res_b.id), headers=headers_b)).status_code == 201
        r = await client.get("/api/graus-dependencia/", headers=headers_a)
        assert r.status_code == 200
        assert {g["residente_id"] for g in r.json()} == {res_a.id}
    asyncio.run(_with_client(graus_db, scenario))


def test_06_cross_tenant_residente_404(graus_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi_a = _new_institution("ILPI A")
        ilpi_b = _new_institution("ILPI B")
        db.add_all([ilpi_a, ilpi_b])
        await db.flush()
        user_a = await _create_ilpi_user(db, ilpi_a, permissions={"grau_dependencia:ler", "grau_dependencia:criar"})
        res_b = await _create_residente(db, ilpi_b.id, nome="Res B")
        await db.commit()
        headers_a = _auth_headers(user_a, scope="ilpi", ilpi_id=ilpi_a.id)
        r = await client.post("/api/graus-dependencia/", json=_confirm_payload(res_b.id), headers=headers_a)
        assert r.status_code == 404
        assert _detail_code(r) == RESOURCE_NOT_FOUND
        r = await client.get(f"/api/graus-dependencia/?residente_id={res_b.id}", headers=headers_a)
        assert r.status_code == 404
        r = await client.get(f"/api/graus-dependencia/ativo?residente_id={res_b.id}", headers=headers_a)
        assert r.status_code == 404
    asyncio.run(_with_client(graus_db, scenario))


def test_07_residente_inexistente_404(graus_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"grau_dependencia:criar"})
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post("/api/graus-dependencia/", json=_confirm_payload(_new_id()), headers=headers)
        assert r.status_code == 404
        assert _detail_code(r) == RESOURCE_NOT_FOUND
    asyncio.run(_with_client(graus_db, scenario))


# ---------- 3. AVALIACAO VINCULADA ----------

def test_08_origem_avaliacao_happy_path(graus_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"grau_dependencia:criar", "grau_dependencia:ler"})
        residente = await _create_residente(db, ilpi.id)
        av = await _create_avaliacao_in_db(db, residente.id, ilpi.id, classificacao="Dependência Moderada")
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        payload = _confirm_payload(residente.id, origem="avaliacao", avaliacao_id=av.id, classificacao="Grau II")
        r = await client.post("/api/graus-dependencia/", json=payload, headers=headers)
        assert r.status_code == 201
        body = r.json()
        assert body["origem"] == "avaliacao"
        assert body["avaliacao_id"] == av.id
        assert body["sugestao_classificacao"] == "Dependência Moderada"
        assert body["classificacao"] == "Grau II"
        assert body["confirmado_por"] == user.id
    asyncio.run(_with_client(graus_db, scenario))


def test_09_avaliacao_outro_residente_404(graus_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"grau_dependencia:criar"})
        res_a = await _create_residente(db, ilpi.id, nome="Res A")
        res_b = await _create_residente(db, ilpi.id, nome="Res B")
        av_b = await _create_avaliacao_in_db(db, res_b.id, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        payload = _confirm_payload(res_a.id, origem="avaliacao", avaliacao_id=av_b.id)
        r = await client.post("/api/graus-dependencia/", json=payload, headers=headers)
        assert r.status_code == 404
        assert _detail_code(r) == RESOURCE_NOT_FOUND
    asyncio.run(_with_client(graus_db, scenario))


def test_10_avaliacao_cross_tenant_404(graus_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi_a = _new_institution("ILPI A")
        ilpi_b = _new_institution("ILPI B")
        db.add_all([ilpi_a, ilpi_b])
        await db.flush()
        user_a = await _create_ilpi_user(db, ilpi_a, permissions={"grau_dependencia:criar", "avaliacoes:criar"})
        res_a = await _create_residente(db, ilpi_a.id, nome="Res A")
        res_b = await _create_residente(db, ilpi_b.id, nome="Res B")
        av_b = await _create_avaliacao_in_db(db, res_b.id, ilpi_b.id)
        await db.commit()
        headers_a = _auth_headers(user_a, scope="ilpi", ilpi_id=ilpi_a.id)
        payload = _confirm_payload(res_a.id, origem="avaliacao", avaliacao_id=av_b.id)
        r = await client.post("/api/graus-dependencia/", json=payload, headers=headers_a)
        assert r.status_code == 404
        assert _detail_code(r) == RESOURCE_NOT_FOUND
    asyncio.run(_with_client(graus_db, scenario))


def test_11_coerencia_origem_avaliacao_422(graus_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"grau_dependencia:criar"})
        residente = await _create_residente(db, ilpi.id)
        av = await _create_avaliacao_in_db(db, residente.id, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        # avaliacao sem avaliacao_id
        r = await client.post("/api/graus-dependencia/", json=_confirm_payload(residente.id, origem="avaliacao"), headers=headers)
        assert r.status_code == 422
        # manual com avaliacao_id
        r = await client.post("/api/graus-dependencia/", json=_confirm_payload(residente.id, origem="manual", avaliacao_id=av.id), headers=headers)
        assert r.status_code == 422
        # origem migracao rejeitada na API
        payload = _confirm_payload(residente.id, origem="migracao")
        r = await client.post("/api/graus-dependencia/", json=payload, headers=headers)
        assert r.status_code == 422
        # classificacao fora do enum
        r = await client.post("/api/graus-dependencia/", json=_confirm_payload(residente.id, classificacao="Dependente total"), headers=headers)
        assert r.status_code == 422
    asyncio.run(_with_client(graus_db, scenario))


def test_12_justificativa_obrigatoria(graus_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"grau_dependencia:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        payload = _confirm_payload(residente.id)
        del payload["justificativa"]
        assert (await client.post("/api/graus-dependencia/", json=payload, headers=headers)).status_code == 422
        payload = _confirm_payload(residente.id, justificativa="   ")
        assert (await client.post("/api/graus-dependencia/", json=payload, headers=headers)).status_code == 422
    asyncio.run(_with_client(graus_db, scenario))


# ---------- 4. AUTORIA / PAYLOAD HOSTIL ----------

def test_13_payload_hostil_ignorado(graus_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi_a = _new_institution("ILPI A")
        ilpi_b = _new_institution("ILPI B")
        db.add_all([ilpi_a, ilpi_b])
        await db.flush()
        user_a = await _create_ilpi_user(db, ilpi_a, permissions={"grau_dependencia:criar"})
        residente = await _create_residente(db, ilpi_a.id)
        await db.commit()
        headers = _auth_headers(user_a, scope="ilpi", ilpi_id=ilpi_a.id)
        payload = _confirm_payload(residente.id)
        payload.update({
            "confirmado_por": _new_id(),
            "usuario_id": _new_id(),
            "profissional": "Falso Profissional",
            "ilpi_id": ilpi_b.id,
            "instituicao_id": ilpi_b.id,
        })
        r = await client.post("/api/graus-dependencia/", json=payload, headers=headers)
        assert r.status_code == 201
        body = r.json()
        assert body["confirmado_por"] == user_a.id
        assert body["ilpi_id"] == ilpi_a.id
    asyncio.run(_with_client(graus_db, scenario))


# ---------- 5. CONFIRMACAO HUMANA / HISTORICO ----------

def test_14_avaliacao_nao_cria_grau_sozinha(graus_db):
    """Invariante F5A-3A1 preservado: avaliação não altera grau automaticamente."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"avaliacoes:criar", "grau_dependencia:ler"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post("/api/avaliacoes/", json={"residente_id": residente.id, "tipo": "Katz", "pontuacao": 2.0}, headers=headers)
        assert r.status_code == 201
        total = (await db.execute(select(func.count()).select_from(m.GrauDependencia).where(m.GrauDependencia.residente_id == residente.id))).scalar()
        assert total == 0
        r = await client.get(f"/api/graus-dependencia/ativo?residente_id={residente.id}", headers=headers)
        assert r.status_code == 404
    asyncio.run(_with_client(graus_db, scenario))


def test_15_substituicao_preserva_historico(graus_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"grau_dependencia:criar", "grau_dependencia:ler"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r1 = await client.post("/api/graus-dependencia/", json=_confirm_payload(residente.id, classificacao="Grau I"), headers=headers)
        assert r1.status_code == 201
        r2 = await client.post("/api/graus-dependencia/", json=_confirm_payload(residente.id, classificacao="Grau II"), headers=headers)
        assert r2.status_code == 201
        r = await client.get(f"/api/graus-dependencia/?residente_id={residente.id}", headers=headers)
        assert r.status_code == 200
        rows = {g["id"]: g for g in r.json()}
        assert len(rows) == 2
        primeiro = rows[r1.json()["id"]]
        segundo = rows[r2.json()["id"]]
        assert primeiro["situacao"] == "substituido"
        assert primeiro["superseded_by"] == segundo["id"]
        assert primeiro["classificacao"] == "Grau I"  # histórico intacto
        assert segundo["situacao"] == "ativo"
        r = await client.get(f"/api/graus-dependencia/ativo?residente_id={residente.id}", headers=headers)
        assert r.json()["id"] == segundo["id"]
    asyncio.run(_with_client(graus_db, scenario))


def test_16_ativo_unico_constraint_nivel_banco(graus_db):
    """Dois ativos para o mesmo residente violam a constraint (prova do índice)."""
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions=set())
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        db.add(m.GrauDependencia(
            id=_new_id(), ilpi_id=ilpi.id, residente_id=residente.id,
            classificacao="Grau I", origem="manual", justificativa="a",
            confirmado_por=user.id, situacao="ativo",
        ))
        db.add(m.GrauDependencia(
            id=_new_id(), ilpi_id=ilpi.id, residente_id=residente.id,
            classificacao="Grau II", origem="manual", justificativa="b",
            confirmado_por=user.id, situacao="ativo",
        ))
        with pytest.raises(IntegrityError):
            await db.flush()
        await db.rollback()
    asyncio.run(_with_client(graus_db, scenario))


def test_17_confirmacoes_concorrentes_um_ativo(graus_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"grau_dependencia:criar", "grau_dependencia:ler"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        payload_a = _confirm_payload(residente.id, classificacao="Grau I")
        payload_b = _confirm_payload(residente.id, classificacao="Grau III")

        async def confirmar(payload):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://testserver") as cli:
                return await cli.post("/api/graus-dependencia/", json=payload, headers=headers)

        first, second = await asyncio.gather(confirmar(payload_a), confirmar(payload_b))
        assert {first.status_code, second.status_code} <= {201, 409}
        assert 201 in (first.status_code, second.status_code)
        ativos = (await db.execute(
            select(func.count()).select_from(m.GrauDependencia).where(
                m.GrauDependencia.residente_id == residente.id,
                m.GrauDependencia.situacao == "ativo",
            )
        )).scalar()
        assert ativos == 1
    asyncio.run(_with_client(graus_db, scenario))


# ---------- 6. REVOGACAO ----------

def test_18_revogacao_happy_path(graus_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"grau_dependencia:criar", "grau_dependencia:ler"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post("/api/graus-dependencia/", json=_confirm_payload(residente.id), headers=headers)
        grau_id = r.json()["id"]
        r = await client.post(f"/api/graus-dependencia/{grau_id}/revogar", json={"motivo": "Óbito — aguardando baixa"}, headers=headers)
        assert r.status_code == 200
        body = r.json()
        assert body["situacao"] == "revogado"
        assert body["motivo_revogacao"] == "Óbito — aguardando baixa"
        assert body["classificacao"] == "Grau II"  # histórico preservado
        r = await client.get(f"/api/graus-dependencia/ativo?residente_id={residente.id}", headers=headers)
        assert r.status_code == 404
    asyncio.run(_with_client(graus_db, scenario))


def test_19_revogacao_regras(graus_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"grau_dependencia:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        # inexistente
        r = await client.post(f"/api/graus-dependencia/{_new_id()}/revogar", json={"motivo": "x"}, headers=headers)
        assert r.status_code == 404
        r = await client.post("/api/graus-dependencia/", json=_confirm_payload(residente.id), headers=headers)
        grau_id = r.json()["id"]
        # motivo obrigatório
        assert (await client.post(f"/api/graus-dependencia/{grau_id}/revogar", json={"motivo": "  "}, headers=headers)).status_code == 422
        # revogar duas vezes
        assert (await client.post(f"/api/graus-dependencia/{grau_id}/revogar", json={"motivo": "ok"}, headers=headers)).status_code == 200
        r = await client.post(f"/api/graus-dependencia/{grau_id}/revogar", json={"motivo": "de novo"}, headers=headers)
        assert r.status_code == 409
    asyncio.run(_with_client(graus_db, scenario))


def test_20_nova_confirmacao_apos_revogacao(graus_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"grau_dependencia:criar", "grau_dependencia:ler"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        velho = (await client.post("/api/graus-dependencia/", json=_confirm_payload(residente.id, classificacao="Grau I"), headers=headers)).json()
        assert (await client.post(f"/api/graus-dependencia/{velho['id']}/revogar", json={"motivo": "revisão"}, headers=headers)).status_code == 200
        novo = (await client.post("/api/graus-dependencia/", json=_confirm_payload(residente.id, classificacao="Grau III"), headers=headers)).json()
        assert novo["situacao"] == "ativo"
        assert novo["id"] != velho["id"]
        r = await client.get(f"/api/graus-dependencia/?residente_id={residente.id}", headers=headers)
        situacoes = sorted(g["situacao"] for g in r.json())
        assert situacoes == ["ativo", "revogado"]
    asyncio.run(_with_client(graus_db, scenario))


# ---------- 7. VERBOS BLOQUEADOS / PLATAFORMA / SENHA ----------

def test_21_put_delete_bloqueados(graus_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"grau_dependencia:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post("/api/graus-dependencia/", json=_confirm_payload(residente.id), headers=headers)
        grau_id = r.json()["id"]
        # Sem rota PUT/DELETE: FastAPI responde 404 (path inexistente) ou
        # 405 — ambos provam que update/delete destrutivo não existe.
        assert (await client.put(f"/api/graus-dependencia/{grau_id}", json={}, headers=headers)).status_code in (404, 405)
        assert (await client.delete(f"/api/graus-dependencia/{grau_id}", headers=headers)).status_code in (404, 405)
    asyncio.run(_with_client(graus_db, scenario))


def test_22_platform_superuser_blocked(graus_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        platform_user = await _create_platform_user(db)
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(platform_user, scope="global")
        r = await client.get("/api/graus-dependencia/", headers=headers)
        assert r.status_code == 403
        assert _detail_code(r) == PERMISSION_DENIED
        r = await client.post("/api/graus-dependencia/", json=_confirm_payload(residente.id), headers=headers)
        assert r.status_code == 403
    asyncio.run(_with_client(graus_db, scenario))


def test_23_first_password_change_required(graus_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"grau_dependencia:ler"}, exige_troca_senha=True)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.get("/api/graus-dependencia/", headers=headers)
        assert r.status_code == 403
        assert _detail_code(r) == FIRST_PASSWORD_CHANGE_REQUIRED
    asyncio.run(_with_client(graus_db, scenario))


# ---------- 8. LEGADO CONGELADO ----------

def test_24_legado_nao_recebe_novas_escritas(graus_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"residentes:criar", "residentes:atualizar", "residentes:ler"})
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        # POST com grau legado é ignorado
        r = await client.post("/api/residentes/", json={
            "nome": "Residente Legado", "data_nascimento": "1940-05-01", "grau_dependencia": "Grau III",
        }, headers=headers)
        assert r.status_code == 201
        assert r.json().get("grau_dependencia") is None
        residente_id = r.json()["id"]
        # valor legado pré-existente não muda via PUT
        await db.execute(text("UPDATE residentes SET grau_dependencia = 'Grau I' WHERE id = :id"), {"id": residente_id})
        await db.commit()
        r = await client.put(f"/api/residentes/{residente_id}", json={"nome": "Residente Legado 2", "grau_dependencia": "Grau III"}, headers=headers)
        assert r.status_code == 200
        assert r.json()["grau_dependencia"] == "Grau I"
        atual = (await db.execute(select(m.Residente).where(m.Residente.id == residente_id))).scalar_one()
        assert atual.grau_dependencia == "Grau I"
    asyncio.run(_with_client(graus_db, scenario))


# ---------- 9. AUDITORIA / VALIDADE / DIVERSOS ----------

def test_25_auditoria_confirmacao_e_revogacao(graus_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"grau_dependencia:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        grau_id = (await client.post("/api/graus-dependencia/", json=_confirm_payload(residente.id), headers=headers)).json()["id"]
        await client.post(f"/api/graus-dependencia/{grau_id}/revogar", json={"motivo": "auditoria"}, headers=headers)
        logs = (await db.execute(
            select(m.Auditoria).where(m.Auditoria.entidade == "graus_dependencia", m.Auditoria.registro_id == grau_id).order_by(m.Auditoria.created_at)
        )).scalars().all()
        acoes = [log.acao for log in logs]
        assert "graus_dependencia.criar" in acoes
        assert "graus_dependencia.revogar" in acoes
        for log in logs:
            assert log.usuario_id == user.id
            assert log.ilpi_id == ilpi.id
    asyncio.run(_with_client(graus_db, scenario))


def test_26_validade_preservada(graus_db):
    async def scenario(client: httpx.AsyncClient, db: AsyncSession):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        user = await _create_ilpi_user(db, ilpi, permissions={"grau_dependencia:criar"})
        residente = await _create_residente(db, ilpi.id)
        await db.commit()
        headers = _auth_headers(user, scope="ilpi", ilpi_id=ilpi.id)
        r = await client.post("/api/graus-dependencia/", json=_confirm_payload(residente.id, validade="2027-06-30"), headers=headers)
        assert r.status_code == 201
        assert r.json()["validade"] == "2027-06-30"
    asyncio.run(_with_client(graus_db, scenario))


def test_27_official_database_intact(graus_db):
    _assert_disposable_database(graus_db)
