"""Disposable-database tests for D.1: PAIS/Plano de Cuidados.

Fonte única planos_cuidados + pais_necessidades/metas/intervencoes.
Lifecycle rascunho->em_elaboracao->em_revisao->aprovado->vigente,
versionamento sem sobrescrever histórico, encerramento explícito.
Sem automação clínica, sem frontend.
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
from src.application.auth import create_access_token  # noqa: E402
from src.application.security import PERMISSION_DENIED, RESOURCE_NOT_FOUND  # noqa: E402
from src.infrastructure import database  # noqa: E402
from src.infrastructure import models as m  # noqa: E402


ALL6 = {
    "planos_cuidados:ler", "planos_cuidados:criar", "planos_cuidados:atualizar",
    "planos_cuidados:revisar", "planos_cuidados:aprovar", "planos_cuidados:encerrar",
}


def _sqlite_url(path: pathlib.Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


def _async_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


def _assert_disposable_postgres(url: str) -> None:
    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    assert parsed.get_backend_name() == "postgresql"
    assert parsed.host in {"localhost", "127.0.0.1"}
    assert parsed.port == 55485 and parsed.database == "facilpi_d1_test"


def _database_url(ref):
    if isinstance(ref, pathlib.Path):
        return _sqlite_url(ref)
    return _async_url(ref)


async def _reset_postgres(url: str) -> None:
    engine = create_async_engine(_async_url(url), poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("DROP SCHEMA public CASCADE"))
            await connection.execute(text("CREATE SCHEMA public"))
            await connection.commit()
    finally:
        await engine.dispose()


def _run_migration(ref) -> None:
    if isinstance(ref, pathlib.Path):
        assert ref.resolve() != OFFICIAL_DB.resolve(), "must never write the official database"
    else:
        _assert_disposable_postgres(ref)
    url = _database_url(ref)
    env = os.environ.copy()
    env["DATABASE_URL"] = url
    env.pop("APP_DATABASE_URL", None)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-x", f"database_url={url}", "upgrade", "head"],
        cwd=BACKEND, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D1_TEST_POSTGRES_URL") else []))
def pais_db(request, tmp_path):
    if request.param == "sqlite":
        path = tmp_path / "d1-pais.db"
        _run_migration(path)
        return path
    url = os.environ["D1_TEST_POSTGRES_URL"]
    _assert_disposable_postgres(url)
    try:
        asyncio.run(_reset_postgres(url))
        _run_migration(url)
    except Exception as error:
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


def _new_id() -> str:
    return str(uuid.uuid4())


def _new_user(**kwargs) -> m.User:
    user_id = _new_id()
    return m.User(id=user_id, nome=kwargs.get("nome", "Usuario D.1"),
                  email=f"d1-{user_id}@example.com", password_hash="fixture-password-hash",
                  ativo=True, exige_troca_senha=kwargs.get("exige_troca_senha", False))


def _new_institution(name="ILPI D.1") -> m.Instituicao:
    return m.Instituicao(id=_new_id(), razao_social=name, situacao="ILPI_RASCUNHO")


def _new_link(user_id, perfil_id, ilpi_id) -> m.UsuarioIlpiPerfil:
    return m.UsuarioIlpiPerfil(id=_new_id(), usuario_id=user_id, perfil_id=perfil_id,
                               ilpi_id=ilpi_id, situacao="ativo",
                               data_inicial=datetime.now(timezone.utc) - timedelta(minutes=1))


async def _grant(db, perfil_id, keys) -> None:
    if not keys:
        return
    perms = (await db.execute(select(m.Permissao).where(m.Permissao.chave.in_(keys)))).scalars().all()
    assert {p.chave for p in perms} == keys
    for perm in perms:
        db.add(m.PerfilPermissao(perfil_id=perfil_id, permissao_id=perm.id))
    await db.flush()


async def _create_ilpi_user(db, institution, *, permissions, profile_key="pais_admin", **kwargs) -> m.User:
    user = _new_user(**kwargs)
    profile = m.Perfil(id=_new_id(), ilpi_id=institution.id, nome="Perfil D.1", chave=profile_key, escopo="ilpi", situacao="ativo")
    db.add_all([institution, user])
    await db.flush()
    db.add(profile)
    await db.flush()
    db.add_all([m.Funcionario(id=_new_id(), ilpi_id=institution.id, usuario_id=user.id,
                              nome=user.nome, email=user.email, situacao="ativo"),
                _new_link(user.id, profile.id, institution.id)])
    await db.flush()
    await _grant(db, profile.id, permissions)
    return user


async def _create_funcionario(db, institution, *, situacao="ativo", with_user=True, nome="Func D.1") -> m.Funcionario:
    user_id = None
    if with_user:
        u = _new_user(nome=nome)
        db.add(u)
        await db.flush()
        user_id = u.id
    func = m.Funcionario(id=_new_id(), ilpi_id=institution.id, usuario_id=user_id, nome=nome, situacao=situacao)
    db.add(func)
    await db.flush()
    return func


async def _create_platform_user(db) -> m.User:
    user = _new_user()
    profile = (await db.execute(select(m.Perfil).where(m.Perfil.chave == "platform_superuser", m.Perfil.ilpi_id.is_(None)))).scalar_one()
    db.add(user)
    await db.flush()
    db.add(_new_link(user.id, profile.id, None))
    await db.flush()
    return user


def _headers(user, *, scope="ilpi", ilpi_id=None):
    headers = {"Authorization": f"Bearer {create_access_token(user)}", "X-Scope": scope}
    if ilpi_id is not None:
        headers["X-ILPI-ID"] = ilpi_id
    return headers


def _code(response):
    detail = response.json().get("detail")
    return detail.get("code") if isinstance(detail, dict) else None


async def _create_residente(db, ilpi_id, nome="Residente D.1") -> m.Residente:
    res = m.Residente(id=_new_id(), instituicao_id=ilpi_id, nome=nome, data_nascimento=date(1940, 5, 1))
    db.add(res)
    await db.flush()
    return res


def _plano_payload(residente_id):
    return {"residente_id": residente_id, "data_inicial": "2026-09-01", "objetivos": "Manter autonomia"}


async def _lifecycle(client, headers, residente_id, *, revisor_id, aprovador_id):
    """Cria plano e avança até vigente; retorna plano completo."""
    r = await client.post("/api/planos-cuidados/", json=_plano_payload(residente_id), headers=headers)
    assert r.status_code == 201, r.text
    plano_id = r.json()["id"]
    r = await client.patch(f"/api/planos-cuidados/{plano_id}", json={"situacao": "em_elaboracao"}, headers=headers)
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/planos-cuidados/{plano_id}/necessidades", json={"descricao": "Risco de queda", "origem": "manual"}, headers=headers)
    assert r.status_code == 201, r.text
    necessidade_id = r.json()["id"]
    r = await client.post(f"/api/planos-cuidados/{plano_id}/metas", json={"descricao": "Zero quedas em 30 dias"}, headers=headers)
    assert r.status_code == 201, r.text
    r = await client.post(f"/api/planos-cuidados/{plano_id}/intervencoes",
                          json={"descricao": "Supervisionar deambulacao", "necessidade_id": necessidade_id, "frequencia": "diaria"}, headers=headers)
    assert r.status_code == 201, r.text
    r = await client.post(f"/api/planos-cuidados/{plano_id}/revisar", json={"funcionario_id": revisor_id}, headers=headers)
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/planos-cuidados/{plano_id}/aprovar", json={"funcionario_id": aprovador_id}, headers=headers)
    assert r.status_code == 200, r.text
    r = await client.post(f"/api/planos-cuidados/{plano_id}/ativar", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_01_anonymous_bloqueado(pais_db):
    async def op(client, db):
        assert (await client.get("/api/planos-cuidados/")).status_code in (401, 403)
        assert (await client.post("/api/planos-cuidados/", json={})).status_code in (401, 403)
    asyncio.run(_with_client(pais_db, op))


def test_02_sem_permissao_403(pais_db):
    async def op(client, db):
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=set())
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        r = await client.get("/api/planos-cuidados/", headers=h)
        assert r.status_code == 403 and _code(r) == PERMISSION_DENIED
    asyncio.run(_with_client(pais_db, op))


def test_03_platform_bloqueado(pais_db):
    async def op(client, db):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        res = await _create_residente(db, ilpi.id)
        platform = await _create_platform_user(db)
        await db.commit()
        h = _headers(platform, scope="global")
        r = await client.post("/api/planos-cuidados/", json=_plano_payload(res.id), headers=h)
        assert r.status_code == 403
    asyncio.run(_with_client(pais_db, op))


def test_04_criar_plano_autor_sessao(pais_db):
    async def op(client, db):
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=ALL6)
        res = await _create_residente(db, ilpi.id)
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        r = await client.post("/api/planos-cuidados/", json=_plano_payload(res.id), headers=h)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["situacao"] == "rascunho" and body["versao"] == 1
        assert body["autor_id"] == user.id and body["ilpi_id"] == ilpi.id
    asyncio.run(_with_client(pais_db, op))


def test_05_payload_hostil_rejeitado(pais_db):
    async def op(client, db):
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=ALL6)
        res = await _create_residente(db, ilpi.id)
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        payload = _plano_payload(res.id) | {"ilpi_id": _new_id(), "autor_id": _new_id()}
        r = await client.post("/api/planos-cuidados/", json=payload, headers=h)
        assert r.status_code == 422, r.text
    asyncio.run(_with_client(pais_db, op))


def test_06_tenant_list_e_cross_404(pais_db):
    async def op(client, db):
        a = _new_institution("ILPI A")
        b = _new_institution("ILPI B")
        ua = await _create_ilpi_user(db, a, permissions=ALL6, profile_key="pa")
        ub = await _create_ilpi_user(db, b, permissions=ALL6, profile_key="pb")
        ra = await _create_residente(db, a.id)
        await db.commit()
        r = await client.post("/api/planos-cuidados/", json=_plano_payload(ra.id),
                              headers=_headers(ua, ilpi_id=a.id))
        assert r.status_code == 201, r.text
        plano_id = r.json()["id"]
        await db.commit()
        hb = _headers(ub, ilpi_id=b.id)
        assert (await client.get("/api/planos-cuidados/", headers=hb)).json() == []
        r = await client.get(f"/api/planos-cuidados/{plano_id}", headers=hb)
        assert r.status_code == 404 and _code(r) == RESOURCE_NOT_FOUND
        r = await client.post("/api/planos-cuidados/", json=_plano_payload(ra.id), headers=hb)
        assert r.status_code == 404 and _code(r) == RESOURCE_NOT_FOUND
    asyncio.run(_with_client(pais_db, op))


def test_07_transicao_ilegal_409(pais_db):
    async def op(client, db):
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=ALL6)
        rev = await _create_funcionario(db, ilpi)
        res = await _create_residente(db, ilpi.id)
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        r = await client.post("/api/planos-cuidados/", json=_plano_payload(res.id), headers=h)
        pid = r.json()["id"]
        # rascunho não pode revisar direto
        r = await client.post(f"/api/planos-cuidados/{pid}/revisar", json={"funcionario_id": rev.id}, headers=h)
        assert r.status_code == 409, r.text
        # aprovar sem revisão
        r = await client.post(f"/api/planos-cuidados/{pid}/aprovar", json={"funcionario_id": rev.id}, headers=h)
        assert r.status_code == 409, r.text
        # ativar sem aprovação
        assert (await client.post(f"/api/planos-cuidados/{pid}/ativar", headers=h)).status_code == 409
        # encerrar sem vigência
        r = await client.post(f"/api/planos-cuidados/{pid}/encerrar", json={"motivo": "x", "funcionario_id": rev.id}, headers=h)
        assert r.status_code == 409, r.text
    asyncio.run(_with_client(pais_db, op))


def test_08_completude_422(pais_db):
    async def op(client, db):
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=ALL6)
        rev = await _create_funcionario(db, ilpi)
        res = await _create_residente(db, ilpi.id)
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        r = await client.post("/api/planos-cuidados/", json=_plano_payload(res.id), headers=h)
        pid = r.json()["id"]
        await client.patch(f"/api/planos-cuidados/{pid}", json={"situacao": "em_elaboracao"}, headers=h)
        await client.post(f"/api/planos-cuidados/{pid}/revisar", json={"funcionario_id": rev.id}, headers=h)
        r = await client.post(f"/api/planos-cuidados/{pid}/aprovar", json={"funcionario_id": rev.id}, headers=h)
        assert r.status_code == 422, r.text
    asyncio.run(_with_client(pais_db, op))


def test_09_lifecycle_vigente_e_unico_vigente(pais_db):
    async def op(client, db):
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=ALL6)
        rev = await _create_funcionario(db, ilpi, nome="Revisor")
        apr = await _create_funcionario(db, ilpi, nome="Aprovador")
        res = await _create_residente(db, ilpi.id)
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        plano = await _lifecycle(client, h, res.id, revisor_id=rev.id, aprovador_id=apr.id)
        assert plano["situacao"] == "vigente"
        assert plano["revisor_funcionario_id"] == rev.id and plano["aprovador_funcionario_id"] == apr.id
        assert len(plano["necessidades"]) == 1 and len(plano["metas"]) == 1 and len(plano["intervencoes"]) == 1
        # segundo plano não pode ativar com vigente existente
        r = await client.post("/api/planos-cuidados/", json=_plano_payload(res.id), headers=h)
        pid2 = r.json()["id"]
        await client.patch(f"/api/planos-cuidados/{pid2}", json={"situacao": "em_elaboracao"}, headers=h)
        await client.post(f"/api/planos-cuidados/{pid2}/necessidades", json={"descricao": "N", "origem": "manual"}, headers=h)
        await client.post(f"/api/planos-cuidados/{pid2}/metas", json={"descricao": "M"}, headers=h)
        await client.post(f"/api/planos-cuidados/{pid2}/intervencoes", json={"descricao": "I"}, headers=h)
        await client.post(f"/api/planos-cuidados/{pid2}/revisar", json={"funcionario_id": rev.id}, headers=h)
        await client.post(f"/api/planos-cuidados/{pid2}/aprovar", json={"funcionario_id": apr.id}, headers=h)
        r = await client.post(f"/api/planos-cuidados/{pid2}/ativar", headers=h)
        assert r.status_code == 409, r.text
    asyncio.run(_with_client(pais_db, op))


def test_10_bloqueio_edicao_pos_aprovacao(pais_db):
    async def op(client, db):
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=ALL6)
        rev = await _create_funcionario(db, ilpi)
        res = await _create_residente(db, ilpi.id)
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        r = await client.post("/api/planos-cuidados/", json=_plano_payload(res.id), headers=h)
        pid = r.json()["id"]
        await client.patch(f"/api/planos-cuidados/{pid}", json={"situacao": "em_elaboracao"}, headers=h)
        await client.post(f"/api/planos-cuidados/{pid}/necessidades", json={"descricao": "N", "origem": "manual"}, headers=h)
        await client.post(f"/api/planos-cuidados/{pid}/metas", json={"descricao": "M"}, headers=h)
        await client.post(f"/api/planos-cuidados/{pid}/intervencoes", json={"descricao": "I"}, headers=h)
        await client.post(f"/api/planos-cuidados/{pid}/revisar", json={"funcionario_id": rev.id}, headers=h)
        await client.post(f"/api/planos-cuidados/{pid}/aprovar", json={"funcionario_id": rev.id}, headers=h)
        assert (await client.patch(f"/api/planos-cuidados/{pid}", json={"objetivos": "novo"}, headers=h)).status_code == 409
        r = await client.post(f"/api/planos-cuidados/{pid}/necessidades", json={"descricao": "N2", "origem": "manual"}, headers=h)
        assert r.status_code == 409, r.text
    asyncio.run(_with_client(pais_db, op))


def test_11_nova_versao_e_substituicao(pais_db):
    async def op(client, db):
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=ALL6)
        rev = await _create_funcionario(db, ilpi)
        res = await _create_residente(db, ilpi.id)
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        v1 = await _lifecycle(client, h, res.id, revisor_id=rev.id, aprovador_id=rev.id)
        nid_v1 = v1["intervencoes"][0]["necessidade_id"]
        assert nid_v1 == v1["necessidades"][0]["id"]
        r = await client.post(f"/api/planos-cuidados/{v1['id']}/nova-versao", json={"motivo": "Reavaliacao trimestral"}, headers=h)
        assert r.status_code == 201, r.text
        v2 = r.json()
        assert v2["versao"] == 2 and v2["anterior_id"] == v1["id"] and v2["situacao"] == "rascunho"
        assert len(v2["necessidades"]) == 1 and len(v2["metas"]) == 1 and len(v2["intervencoes"]) == 1
        # link necessidade remapeado dentro da nova versão
        assert v2["intervencoes"][0]["necessidade_id"] == v2["necessidades"][0]["id"]
        # bifurcação bloqueada
        r = await client.post(f"/api/planos-cuidados/{v1['id']}/nova-versao", json={"motivo": "outra"}, headers=h)
        assert r.status_code == 409, r.text
        # anterior preservada até a nova versão assumir
        r = await client.get(f"/api/planos-cuidados/{v1['id']}", headers=h)
        assert r.json()["situacao"] == "vigente"
        # avança v2 até ativar: v1 passa a substituido
        await client.patch(f"/api/planos-cuidados/{v2['id']}", json={"situacao": "em_elaboracao"}, headers=h)
        await client.post(f"/api/planos-cuidados/{v2['id']}/revisar", json={"funcionario_id": rev.id}, headers=h)
        await client.post(f"/api/planos-cuidados/{v2['id']}/aprovar", json={"funcionario_id": rev.id}, headers=h)
        # vigente impede ativação da v2 antes de encerrar v1
        assert (await client.post(f"/api/planos-cuidados/{v2['id']}/ativar", headers=h)).status_code == 409
        r = await client.post(f"/api/planos-cuidados/{v1['id']}/encerrar", json={"motivo": "Substituido por v2", "funcionario_id": rev.id}, headers=h)
        assert r.status_code == 200, r.text
        r = await client.post(f"/api/planos-cuidados/{v2['id']}/ativar", headers=h)
        assert r.status_code == 200, r.text
        # encerrar v1 após v2 assumir marca... v1 já encerrado; fluxo alternativo: aprovar->ativar com anterior aprovado
    asyncio.run(_with_client(pais_db, op))


def test_12_substituicao_direta_aprovado(pais_db):
    async def op(client, db):
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=ALL6)
        rev = await _create_funcionario(db, ilpi)
        res = await _create_residente(db, ilpi.id)
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        # v1 até aprovado (sem ativar)
        r = await client.post("/api/planos-cuidados/", json=_plano_payload(res.id), headers=h)
        v1 = r.json()["id"]
        await client.patch(f"/api/planos-cuidados/{v1}", json={"situacao": "em_elaboracao"}, headers=h)
        await client.post(f"/api/planos-cuidados/{v1}/necessidades", json={"descricao": "N", "origem": "manual"}, headers=h)
        await client.post(f"/api/planos-cuidados/{v1}/metas", json={"descricao": "M"}, headers=h)
        await client.post(f"/api/planos-cuidados/{v1}/intervencoes", json={"descricao": "I"}, headers=h)
        await client.post(f"/api/planos-cuidados/{v1}/revisar", json={"funcionario_id": rev.id}, headers=h)
        await client.post(f"/api/planos-cuidados/{v1}/aprovar", json={"funcionario_id": rev.id}, headers=h)
        r = await client.post(f"/api/planos-cuidados/{v1}/nova-versao", json={"motivo": "Ajuste"}, headers=h)
        v2 = r.json()["id"]
        await client.patch(f"/api/planos-cuidados/{v2}", json={"situacao": "em_elaboracao"}, headers=h)
        await client.post(f"/api/planos-cuidados/{v2}/revisar", json={"funcionario_id": rev.id}, headers=h)
        await client.post(f"/api/planos-cuidados/{v2}/aprovar", json={"funcionario_id": rev.id}, headers=h)
        assert (await client.post(f"/api/planos-cuidados/{v2}/ativar", headers=h)).status_code == 200
        r = await client.get(f"/api/planos-cuidados/{v1}", headers=h)
        assert r.json()["situacao"] == "substituido" and r.json()["superseded_by"] == v2
    asyncio.run(_with_client(pais_db, op))


def test_13_encerramento_exige_motivo_e_historico_somente_leitura(pais_db):
    async def op(client, db):
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=ALL6)
        rev = await _create_funcionario(db, ilpi)
        res = await _create_residente(db, ilpi.id)
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        v = await _lifecycle(client, h, res.id, revisor_id=rev.id, aprovador_id=rev.id)
        assert (await client.post(f"/api/planos-cuidados/{v['id']}/encerrar", json={"funcionario_id": rev.id}, headers=h)).status_code == 422
        r = await client.post(f"/api/planos-cuidados/{v['id']}/encerrar", json={"motivo": "Obito", "funcionario_id": rev.id}, headers=h)
        assert r.status_code == 200 and r.json()["situacao"] == "encerrado"
        assert (await client.patch(f"/api/planos-cuidados/{v['id']}", json={"objetivos": "x"}, headers=h)).status_code == 409
        assert (await client.delete(f"/api/planos-cuidados/{v['id']}", headers=h)).status_code == 405
    asyncio.run(_with_client(pais_db, op))


def test_14_revisor_cross_tenant_404_e_inativo_422(pais_db):
    async def op(client, db):
        a = _new_institution("ILPI A")
        b = _new_institution("ILPI B")
        ua = await _create_ilpi_user(db, a, permissions=ALL6, profile_key="pa")
        await _create_ilpi_user(db, b, permissions=ALL6, profile_key="pb")
        outsider = await _create_funcionario(db, b, nome="Outsider")
        inativo = await _create_funcionario(db, a, situacao="inativo", nome="Inativo")
        res = await _create_residente(db, a.id)
        await db.commit()
        h = _headers(ua, ilpi_id=a.id)
        r = await client.post("/api/planos-cuidados/", json=_plano_payload(res.id), headers=h)
        pid = r.json()["id"]
        await client.patch(f"/api/planos-cuidados/{pid}", json={"situacao": "em_elaboracao"}, headers=h)
        r = await client.post(f"/api/planos-cuidados/{pid}/revisar", json={"funcionario_id": outsider.id}, headers=h)
        assert r.status_code == 404, r.text
        r = await client.post(f"/api/planos-cuidados/{pid}/revisar", json={"funcionario_id": inativo.id}, headers=h)
        assert r.status_code == 422, r.text
    asyncio.run(_with_client(pais_db, op))


def test_15_origem_grau_exige_tabela_ativa(pais_db):
    async def op(client, db):
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=ALL6 | {"grau_dependencia:criar", "avaliacoes:criar"})
        res = await _create_residente(db, ilpi.id, nome="Res Grau")
        db.add(m.GrauDependencia(id=_new_id(), ilpi_id=ilpi.id, residente_id=res.id, classificacao="Grau II",
                                 origem="manual", justificativa="j", confirmado_por=user.id, situacao="ativo"))
        # legado congelado NÃO conta como fonte
        res.grau_dependencia = "Grau III"
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        r = await client.post("/api/planos-cuidados/", json=_plano_payload(res.id), headers=h)
        pid = r.json()["id"]
        await client.patch(f"/api/planos-cuidados/{pid}", json={"situacao": "em_elaboracao"}, headers=h)
        grau = (await db.execute(select(m.GrauDependencia).where(m.GrauDependencia.residente_id == res.id))).scalar_one()
        r = await client.post(f"/api/planos-cuidados/{pid}/necessidades",
                              json={"descricao": "N grau", "origem": "grau_dependencia", "referencia_id": grau.id}, headers=h)
        assert r.status_code == 201, r.text
        r = await client.post(f"/api/planos-cuidados/{pid}/necessidades",
                              json={"descricao": "N fake", "origem": "grau_dependencia", "referencia_id": _new_id()}, headers=h)
        assert r.status_code == 422, r.text
        r = await client.post(f"/api/planos-cuidados/{pid}/necessidades",
                              json={"descricao": "N manual c/ ref", "origem": "manual", "referencia_id": grau.id}, headers=h)
        assert r.status_code == 422, r.text
    asyncio.run(_with_client(pais_db, op))


def test_16_intervencao_vinculo_e_responsaveis(pais_db):
    async def op(client, db):
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=ALL6)
        tec = await _create_funcionario(db, ilpi, nome="Tecnico")
        res = await _create_residente(db, ilpi.id)
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        r = await client.post("/api/planos-cuidados/", json=_plano_payload(res.id), headers=h)
        pid = r.json()["id"]
        await client.patch(f"/api/planos-cuidados/{pid}", json={"situacao": "em_elaboracao"}, headers=h)
        # necessidade de outro plano não vincula
        r = await client.post(f"/api/planos-cuidados/{pid}/intervencoes",
                              json={"descricao": "I orfa", "necessidade_id": _new_id()}, headers=h)
        assert r.status_code == 404, r.text
        r = await client.post(f"/api/planos-cuidados/{pid}/metas",
                              json={"descricao": "M", "responsavel_funcionario_id": _new_id()}, headers=h)
        assert r.status_code == 404, r.text
        r = await client.post(f"/api/planos-cuidados/{pid}/metas",
                              json={"descricao": "M", "responsavel_funcionario_id": tec.id}, headers=h)
        assert r.status_code == 201, r.text
    asyncio.run(_with_client(pais_db, op))


def test_17_auditoria_lifecycle(pais_db):
    async def op(client, db):
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=ALL6)
        rev = await _create_funcionario(db, ilpi)
        res = await _create_residente(db, ilpi.id)
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        v = await _lifecycle(client, h, res.id, revisor_id=rev.id, aprovador_id=rev.id)
        await client.post(f"/api/planos-cuidados/{v['id']}/encerrar",
                          json={"motivo": "Alta", "funcionario_id": rev.id}, headers=h)
        rows = (await db.execute(select(m.Auditoria.acao).where(m.Auditoria.ilpi_id == ilpi.id))).scalars().all()
        for expected in ("planos_cuidados.criar", "planos_cuidados.atualizar", "pais_necessidades.criar",
                         "pais_metas.criar", "pais_intervencoes.criar", "planos_cuidados.revisar",
                         "planos_cuidados.aprovar", "planos_cuidados.ativar", "planos_cuidados.encerrar"):
            assert expected in rows, f"auditoria sem {expected}: {sorted(set(rows))}"
        assert all((await db.execute(select(m.Auditoria.usuario_id).where(m.Auditoria.ilpi_id == ilpi.id))).scalars().all())
    asyncio.run(_with_client(pais_db, op))


def test_18_rbac_granular_por_acao(pais_db):
    async def op(client, db):
        ilpi = _new_institution()
        full = await _create_ilpi_user(db, ilpi, permissions=ALL6, profile_key="full")
        readonly = await _create_ilpi_user(db, ilpi, permissions={"planos_cuidados:ler"}, profile_key="ro", nome="Leitor")
        rev = await _create_funcionario(db, ilpi)
        res = await _create_residente(db, ilpi.id)
        await db.commit()
        hf, hr = _headers(full, ilpi_id=ilpi.id), _headers(readonly, ilpi_id=ilpi.id)
        r = await client.post("/api/planos-cuidados/", json=_plano_payload(res.id), headers=hf)
        pid = r.json()["id"]
        assert (await client.post("/api/planos-cuidados/", json=_plano_payload(res.id), headers=hr)).status_code == 403
        assert (await client.patch(f"/api/planos-cuidados/{pid}", json={"objetivos": "x"}, headers=hr)).status_code == 403
        r = await client.post(f"/api/planos-cuidados/{pid}/necessidades", json={"descricao": "N", "origem": "manual"}, headers=hr)
        assert r.status_code == 403, r.text
    asyncio.run(_with_client(pais_db, op))
