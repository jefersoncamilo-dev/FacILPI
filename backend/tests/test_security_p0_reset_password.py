"""Disposable-database tests for Issue #22 (P0).

Administrative password reset is an institutional capability.  A global
profile (``platform_superuser``) must never be able to reset the credential of
a user that belongs to an ILPI, because that would hand it the institutional
and clinical identity of that user.

The legitimate ``ilpi_admin`` flow over users of its own ILPI stays untouched.
"""

from __future__ import annotations

import asyncio
import json
import os
import pathlib
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tests.db_safety import OFFICIAL_DB, reset_postgres, run_alembic, validate_pg_target, validate_target


ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from src import main  # noqa: E402
from src.application import auth  # noqa: E402
from src.application.auth import create_access_token, hash_password, verify_password  # noqa: E402
from src.application.security import PERMISSION_DENIED  # noqa: E402
from src.infrastructure import database  # noqa: E402
from src.infrastructure import models as m  # noqa: E402


RESET_KEY = "usuarios:redefinir_senha"
RESET_AUDIT = "usuario.senha_redefinida"
VICTIM_PASSWORD = "SenhaVitima1"
ADMIN_KEYS = {RESET_KEY, "usuarios:criar", "usuarios:atribuir_perfil"}


def _sqlite_url(path: pathlib.Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def _async_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _database_url(ref) -> str:
    return _sqlite_url(ref) if isinstance(ref, pathlib.Path) else _async_url(ref)


def _migrate(ref) -> None:
    if isinstance(ref, pathlib.Path):
        assert ref.resolve() != OFFICIAL_DB, "must never write the official database"
        url = _sqlite_url(ref)
    else:
        url = validate_pg_target(ref)
    validate_target(url)
    result = run_alembic(url, "upgrade", "head")
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("P0_TEST_POSTGRES_URL") else []))
def p0_db(request, tmp_path):
    if request.param == "sqlite":
        path = tmp_path / "p0-reset-password.db"
        _migrate(path)
        return path
    url = os.environ["P0_TEST_POSTGRES_URL"]
    validate_pg_target(url)
    try:
        asyncio.run(reset_postgres(url))
        _migrate(url)
    except Exception as error:  # pragma: no cover - infrastructure guard
        pytest.skip(f"PostgreSQL descartavel indisponivel: {error}")
    return url


async def _with_client(database_ref, operation):
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
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", follow_redirects=True) as client:
            async with factory() as session:
                return await operation(client, session)
    finally:
        main.app.dependency_overrides.clear()
        await engine.dispose()


async def _commit(db) -> None:
    """Commit and detach: seeded instances must survive a later rollback."""
    await db.commit()
    db.expunge_all()


def _new_id() -> str:
    return str(uuid.uuid4())


def _new_user(*, nome="Usuario P0", password=None) -> m.User:
    user_id = _new_id()
    return m.User(
        id=user_id,
        nome=nome,
        email=f"p0-{user_id}@example.com",
        password_hash=hash_password(password) if password else "fixture-password-hash",
        ativo=True,
        is_superuser=False,
    )


def _new_institution(name="ILPI P0") -> m.Instituicao:
    return m.Instituicao(id=_new_id(), razao_social=name, situacao="ILPI_RASCUNHO")


def _new_link(user_id, perfil_id, ilpi_id, *, situacao="ativo") -> m.UsuarioIlpiPerfil:
    return m.UsuarioIlpiPerfil(
        id=_new_id(), usuario_id=user_id, perfil_id=perfil_id, ilpi_id=ilpi_id,
        situacao=situacao, data_inicial=datetime.now(timezone.utc) - timedelta(minutes=1),
    )


async def _grant(db, perfil_id, keys) -> None:
    if not keys:
        return
    perms = (await db.execute(select(m.Permissao).where(m.Permissao.chave.in_(keys)))).scalars().all()
    assert {p.chave for p in perms} == set(keys)
    for perm in perms:
        db.add(m.PerfilPermissao(perfil_id=perfil_id, permissao_id=perm.id))
    await db.flush()


async def _create_ilpi_user(db, institution, *, permissions, profile_key="p0", nome="Usuario P0",
                            password=None, link_situacao="ativo") -> m.User:
    user = _new_user(nome=nome, password=password)
    profile = m.Perfil(id=_new_id(), ilpi_id=institution.id, nome=f"Perfil {profile_key}",
                       chave=profile_key, escopo="ilpi", situacao="ativo")
    db.add(user)
    await db.flush()
    db.add(profile)
    await db.flush()
    db.add_all([
        m.Funcionario(id=_new_id(), ilpi_id=institution.id, usuario_id=user.id,
                      nome=user.nome, email=user.email, situacao="ativo"),
        _new_link(user.id, profile.id, institution.id, situacao=link_situacao),
    ])
    await db.flush()
    await _grant(db, profile.id, permissions)
    return user


async def _create_platform_user(db) -> m.User:
    user = _new_user(nome="Superusuario da Plataforma")
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
    return user


async def _seed_refresh_tokens(db, user_id, *, quantity=2) -> list[str]:
    now = datetime.now(timezone.utc)
    ids = []
    for _ in range(quantity):
        row = m.RefreshToken(
            id=_new_id(), user_id=user_id, token_hash=_new_id(), jti=_new_id(),
            token_family=_new_id(), expires_at=now + timedelta(days=7),
        )
        db.add(row)
        ids.append(row.id)
    await db.flush()
    return ids


def _headers(user, *, scope="ilpi", ilpi_id=None):
    headers = {"Authorization": f"Bearer {create_access_token(user)}", "X-Scope": scope}
    if ilpi_id is not None:
        headers["X-ILPI-ID"] = ilpi_id
    return headers


def _code(response):
    detail = response.json().get("detail")
    return detail.get("code") if isinstance(detail, dict) else None


def _reset_url(user_id: str) -> str:
    return f"/api/usuarios/{user_id}/reset-password"


async def _snapshot(db, user_id):
    await db.rollback()
    user = (await db.execute(select(m.User).where(m.User.id == user_id))).scalar_one()
    await db.refresh(user)
    tokens = (await db.execute(select(m.RefreshToken).where(m.RefreshToken.user_id == user_id))).scalars().all()
    for token in tokens:
        await db.refresh(token)
    audits = (
        await db.execute(select(m.Auditoria).where(m.Auditoria.acao == RESET_AUDIT, m.Auditoria.registro_id == user_id))
    ).scalars().all()
    return {
        "password_hash": user.password_hash,
        "exige_troca_senha": user.exige_troca_senha,
        "revoked": [token.revoked_at for token in tokens],
        "audits": len(audits),
    }


async def _base_seed(db, *, victim_password=VICTIM_PASSWORD):
    """One ILPI with an administrator, an institutional victim and a platform user."""
    institution = _new_institution()
    db.add(institution)
    await db.flush()
    admin = await _create_ilpi_user(db, institution, permissions=ADMIN_KEYS,
                                    profile_key="p0_admin", nome="Admin da ILPI")
    victim = await _create_ilpi_user(db, institution, permissions={"residentes:ler"},
                                     profile_key="p0_clinico", nome="Enfermeira da ILPI",
                                     password=victim_password)
    platform = await _create_platform_user(db)
    await _commit(db)
    return institution, admin, victim, platform


# ===== 01 - Platform Superuser is blocked and leaves no trace =====

def test_01_platform_nao_redefine_usuario_institucional(p0_db):
    async def operation(client, db):
        institution, _admin, victim, platform = await _base_seed(db)
        await _seed_refresh_tokens(db, victim.id)
        await _commit(db)
        before = await _snapshot(db, victim.id)

        response = await client.patch(_reset_url(victim.id), headers=_headers(platform, scope="global"))

        assert response.status_code == 403, response.text
        assert _code(response) == PERMISSION_DENIED
        assert "senha_temporaria" not in response.text

        after = await _snapshot(db, victim.id)
        # Zero side effects: nothing about the victim may change.
        assert after["password_hash"] == before["password_hash"]
        assert after["exige_troca_senha"] == before["exige_troca_senha"] is False
        assert after["revoked"] == before["revoked"] == [None, None]
        assert after["audits"] == before["audits"] == 0
        # The original credential still authenticates the victim.
        assert verify_password(VICTIM_PASSWORD, after["password_hash"])

    asyncio.run(_with_client(p0_db, operation))


# ===== 02 - the full takeover chain is closed =====

def test_02_cadeia_de_takeover_bloqueada(p0_db):
    async def operation(client, db):
        institution, _admin, victim, platform = await _base_seed(db)

        blocked = await client.patch(_reset_url(victim.id), headers=_headers(platform, scope="global"))
        assert blocked.status_code == 403
        assert _code(blocked) == PERMISSION_DENIED

        # No temporary credential was ever produced, so no login is possible.
        auth._rate_store.clear()
        stolen = await client.post("/api/auth/token", json={"email": victim.email, "password": "Aa1!qualquer-coisa"})
        assert stolen.status_code == 401

        # The victim keeps its own institutional identity intact.
        auth._rate_store.clear()
        legitimate = await client.post(
            "/api/auth/token",
            json={"email": victim.email, "password": VICTIM_PASSWORD,
                  "scope": "ilpi", "ilpi_id": institution.id},
        )
        assert legitimate.status_code == 200, legitimate.text
        assert legitimate.json()["exige_troca_senha"] is False

    asyncio.run(_with_client(p0_db, operation))


# ===== 03 - global scope is denied before the target is read =====

def test_03_escopo_global_nao_enumera(p0_db):
    async def operation(client, db):
        _institution, _admin, victim, platform = await _base_seed(db)
        headers = _headers(platform, scope="global")

        existing = await client.patch(_reset_url(victim.id), headers=headers)
        missing = await client.patch(_reset_url(_new_id()), headers=headers)

        assert existing.status_code == missing.status_code == 403
        assert existing.json() == missing.json()

    asyncio.run(_with_client(p0_db, operation))


# ===== 04 - the legitimate ilpi_admin flow is preserved =====

def test_04_ilpi_admin_reset_legitimo(p0_db):
    async def operation(client, db):
        institution, admin, victim, _platform = await _base_seed(db)
        before = await _snapshot(db, victim.id)

        response = await client.patch(
            _reset_url(victim.id), headers=_headers(admin, ilpi_id=institution.id)
        )

        assert response.status_code == 200, response.text
        temporary = response.json()["senha_temporaria"]
        assert temporary

        after = await _snapshot(db, victim.id)
        assert after["password_hash"] != before["password_hash"]
        assert after["password_hash"] != temporary
        assert after["exige_troca_senha"] is True
        assert verify_password(temporary, after["password_hash"])

        # The delivered credential really works.
        auth._rate_store.clear()
        login = await client.post("/api/auth/token", json={"email": victim.email, "password": temporary})
        assert login.status_code == 200, login.text
        assert login.json()["exige_troca_senha"] is True

    asyncio.run(_with_client(p0_db, operation))


# ===== 05 - cross-tenant target is not reachable =====

def test_05_cross_tenant_404(p0_db):
    async def operation(client, db):
        institution_a, admin_a, _victim_a, _platform = await _base_seed(db)
        institution_b = _new_institution("ILPI P0 B")
        db.add(institution_b)
        await db.flush()
        victim_b = await _create_ilpi_user(db, institution_b, permissions={"residentes:ler"},
                                           profile_key="p0_b", nome="Enfermeira da ILPI B",
                                           password=VICTIM_PASSWORD)
        await _commit(db)
        before = await _snapshot(db, victim_b.id)

        response = await client.patch(
            _reset_url(victim_b.id), headers=_headers(admin_a, ilpi_id=institution_a.id)
        )

        assert response.status_code == 404
        assert _code(response) == "USER_NOT_FOUND"
        after = await _snapshot(db, victim_b.id)
        assert after["password_hash"] == before["password_hash"]
        assert after["audits"] == 0

    asyncio.run(_with_client(p0_db, operation))


# ===== 06 - missing target and cross-tenant target are indistinguishable =====

def test_06_inexistente_vs_cross_tenant(p0_db):
    async def operation(client, db):
        institution_a, admin_a, _victim_a, _platform = await _base_seed(db)
        institution_b = _new_institution("ILPI P0 B")
        db.add(institution_b)
        await db.flush()
        victim_b = await _create_ilpi_user(db, institution_b, permissions={"residentes:ler"},
                                           profile_key="p0_b", nome="Enfermeira da ILPI B")
        await _commit(db)
        headers = _headers(admin_a, ilpi_id=institution_a.id)

        cross = await client.patch(_reset_url(victim_b.id), headers=headers)
        missing = await client.patch(_reset_url(_new_id()), headers=headers)

        assert cross.status_code == missing.status_code == 404
        assert cross.json() == missing.json()

    asyncio.run(_with_client(p0_db, operation))


# ===== 07 - a legitimate reset revokes every refresh token =====

def test_07_refresh_tokens_revogados(p0_db):
    async def operation(client, db):
        institution, admin, victim, _platform = await _base_seed(db)
        await _seed_refresh_tokens(db, victim.id, quantity=3)
        await _commit(db)
        assert (await _snapshot(db, victim.id))["revoked"] == [None, None, None]

        response = await client.patch(
            _reset_url(victim.id), headers=_headers(admin, ilpi_id=institution.id)
        )
        assert response.status_code == 200, response.text

        revoked = (await _snapshot(db, victim.id))["revoked"]
        assert len(revoked) == 3
        assert all(value is not None for value in revoked)

    asyncio.run(_with_client(p0_db, operation))


# ===== 08 - audit records the act without storing any secret =====

def test_08_auditoria_sem_segredo(p0_db):
    async def operation(client, db):
        institution, admin, victim, _platform = await _base_seed(db)

        response = await client.patch(
            _reset_url(victim.id), headers=_headers(admin, ilpi_id=institution.id)
        )
        assert response.status_code == 200, response.text
        temporary = response.json()["senha_temporaria"]

        await db.rollback()
        rows = (
            await db.execute(
                select(m.Auditoria).where(m.Auditoria.acao == RESET_AUDIT, m.Auditoria.registro_id == victim.id)
            )
        ).scalars().all()
        assert len(rows) == 1
        row = rows[0]
        assert row.ilpi_id == institution.id
        assert row.usuario_id == admin.id
        assert row.entidade == "users"

        payload = json.dumps(
            {"anteriores": row.valores_anteriores, "posteriores": row.valores_posteriores},
            ensure_ascii=False,
        )
        assert temporary not in payload
        assert "senha" not in payload.lower().replace("exige_troca_senha", "")
        assert "$2b$" not in payload

        user = (await db.execute(select(m.User).where(m.User.id == victim.id))).scalar_one()
        assert user.password_hash not in payload

    asyncio.run(_with_client(p0_db, operation))


# ===== 09 - authentication and permission are still required =====

def test_09_sem_permissao_e_anonimo(p0_db):
    async def operation(client, db):
        institution, _admin, victim, _platform = await _base_seed(db)
        sem_permissao = await _create_ilpi_user(
            db, institution, permissions={"residentes:ler"}, profile_key="p0_sem", nome="Sem permissao"
        )
        await _commit(db)

        anonimo = await client.patch(_reset_url(victim.id))
        assert anonimo.status_code == 401

        negado = await client.patch(
            _reset_url(victim.id), headers=_headers(sem_permissao, ilpi_id=institution.id)
        )
        assert negado.status_code == 403
        assert _code(negado) == PERMISSION_DENIED
        assert (await _snapshot(db, victim.id))["audits"] == 0

    asyncio.run(_with_client(p0_db, operation))


# ===== 10 - the administrative lifecycle over the API stays intact =====

def test_10_ciclo_administrativo_preservado(p0_db):
    async def operation(client, db):
        institution, admin, _victim, _platform = await _base_seed(db)
        headers = _headers(admin, ilpi_id=institution.id)
        # The administrative reset requires an ACTIVE institutional link, so the
        # new user is created already bound to a profile of this ILPI.
        perfil = (
            await db.execute(
                select(m.Perfil).where(m.Perfil.ilpi_id == institution.id, m.Perfil.chave == "p0_clinico")
            )
        ).scalar_one()

        created = await client.post(
            "/api/usuarios/", headers=headers,
            json={"nome": "Usuario Novo", "email": "NOVO-P0@EXAMPLE.COM", "perfil_id": perfil.id},
        )
        assert created.status_code == 201, created.text
        payload = created.json()
        assert payload["exige_troca_senha"] is True
        primeira = payload["senha_temporaria"]

        reset = await client.patch(_reset_url(payload["id"]), headers=headers)
        assert reset.status_code == 200, reset.text
        segunda = reset.json()["senha_temporaria"]
        assert segunda != primeira

        auth._rate_store.clear()
        antiga = await client.post("/api/auth/token", json={"email": payload["email"], "password": primeira})
        assert antiga.status_code == 401
        auth._rate_store.clear()
        nova = await client.post("/api/auth/token", json={"email": payload["email"], "password": segunda})
        assert nova.status_code == 200, nova.text

    asyncio.run(_with_client(p0_db, operation))


# ===== 11 - the link check is unconditional, not scope dependent =====

def test_11_vinculo_inativo_nao_autoriza(p0_db):
    async def operation(client, db):
        institution, admin, _victim, _platform = await _base_seed(db)
        inativo = await _create_ilpi_user(
            db, institution, permissions={"residentes:ler"}, profile_key="p0_inativo",
            nome="Vinculo inativo", password=VICTIM_PASSWORD, link_situacao="inativo",
        )
        await _commit(db)
        before = await _snapshot(db, inativo.id)

        response = await client.patch(
            _reset_url(inativo.id), headers=_headers(admin, ilpi_id=institution.id)
        )

        assert response.status_code == 404
        assert _code(response) == "USER_NOT_FOUND"
        after = await _snapshot(db, inativo.id)
        assert after["password_hash"] == before["password_hash"]
        assert after["audits"] == 0

    asyncio.run(_with_client(p0_db, operation))
