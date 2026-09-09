"""Disposable-database tests for D.2: rotina assistencial.

Programacao -> Ocorrencia -> Execucao + Meu Plantao como PROJECAO.
Tarefa legada intocada. Sem escala/turno, sem tolerancia hardcoded.
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


PAIS6 = {
    "planos_cuidados:ler", "planos_cuidados:criar", "planos_cuidados:atualizar",
    "planos_cuidados:revisar", "planos_cuidados:aprovar", "planos_cuidados:encerrar",
}
D2_ALL = {
    "programacoes:ler", "programacoes:criar", "programacoes:atualizar", "programacoes:inativar",
    "ocorrencias:ler", "ocorrencias:cancelar",
    "execucoes:ler", "execucoes:criar", "execucoes:corrigir",
    "plantao:ler",
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
    assert parsed.port == 55485 and parsed.database == "facilpi_d2_test"


def _database_url(ref):
    return _sqlite_url(ref) if isinstance(ref, pathlib.Path) else _async_url(ref)


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


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D2_TEST_POSTGRES_URL") else []))
def rotina_db(request, tmp_path):
    if request.param == "sqlite":
        path = tmp_path / "d2-rotina.db"
        _run_migration(path)
        return path
    url = os.environ["D2_TEST_POSTGRES_URL"]
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
    return m.User(id=user_id, nome=kwargs.get("nome", "Usuario D.2"),
                  email=f"d2-{user_id}@example.com", password_hash="fixture-password-hash", ativo=True)


def _new_institution(name="ILPI D.2") -> m.Instituicao:
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


async def _create_ilpi_user(db, institution, *, permissions, profile_key="d2", **kwargs) -> m.User:
    user = _new_user(**kwargs)
    profile = m.Perfil(id=_new_id(), ilpi_id=institution.id, nome="Perfil D.2", chave=profile_key, escopo="ilpi", situacao="ativo")
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


async def _create_funcionario(db, institution, *, situacao="ativo", nome="Func D.2") -> m.Funcionario:
    func = m.Funcionario(id=_new_id(), ilpi_id=institution.id, nome=nome, situacao=situacao)
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


async def _create_residente(db, ilpi_id, nome="Residente D.2") -> m.Residente:
    res = m.Residente(id=_new_id(), instituicao_id=ilpi_id, nome=nome, data_nascimento=date(1940, 5, 1))
    db.add(res)
    await db.flush()
    return res


async def _setup_pais_vigente(client, headers, residente_id, revisor_id):
    """Sobe PAIS até vigente com 1 necessidade/meta/intervenção; retorna plano+intervencao."""
    r = await client.post("/api/planos-cuidados/",
                          json={"residente_id": residente_id, "data_inicial": "2026-09-01", "objetivos": "D2"}, headers=headers)
    assert r.status_code == 201, r.text
    pid = r.json()["id"]
    assert (await client.patch(f"/api/planos-cuidados/{pid}", json={"situacao": "em_elaboracao"}, headers=headers)).status_code == 200
    assert (await client.post(f"/api/planos-cuidados/{pid}/necessidades", json={"descricao": "N", "origem": "manual"}, headers=headers)).status_code == 201
    assert (await client.post(f"/api/planos-cuidados/{pid}/metas", json={"descricao": "M"}, headers=headers)).status_code == 201
    r = await client.post(f"/api/planos-cuidados/{pid}/intervencoes", json={"descricao": "Banho assistido", "frequencia": "texto livre nao interpretado"}, headers=headers)
    assert r.status_code == 201, r.text
    iid = r.json()["id"]
    assert (await client.post(f"/api/planos-cuidados/{pid}/revisar", json={"funcionario_id": revisor_id}, headers=headers)).status_code == 200
    assert (await client.post(f"/api/planos-cuidados/{pid}/aprovar", json={"funcionario_id": revisor_id}, headers=headers)).status_code == 200
    r = await client.post(f"/api/planos-cuidados/{pid}/ativar", headers=headers)
    assert r.status_code == 200, r.text
    return pid, iid


def _prog_payload(plano_id, intervencao_id, *, inicio_horas=-1):
    inicio = (datetime.now(timezone.utc) + timedelta(hours=inicio_horas)).isoformat()
    return {"plano_id": plano_id, "intervencao_id": intervencao_id, "horarios": ["08:00", "20:00"],
            "timezone": "America/Sao_Paulo", "vigencia_inicio": inicio, "prioridade": "alta"}


def test_01_anonymous_e_sem_permissao(rotina_db):
    async def op(client, db):
        assert (await client.get("/api/programacoes-cuidado/")).status_code in (401, 403)
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=set())
        await db.commit()
        r = await client.get("/api/programacoes-cuidado/", headers=_headers(user, ilpi_id=ilpi.id))
        assert r.status_code == 403 and _code(r) == PERMISSION_DENIED
    asyncio.run(_with_client(rotina_db, op))


def test_02_platform_bloqueado(rotina_db):
    async def op(client, db):
        ilpi = _new_institution()
        db.add(ilpi)
        await db.flush()
        platform = await _create_platform_user(db)
        await db.commit()
        r = await client.get("/api/plantao/", headers=_headers(platform, scope="global"))
        assert r.status_code == 403
    asyncio.run(_with_client(rotina_db, op))


def test_03_criar_programacao_autor_sessao(rotina_db):
    async def op(client, db):
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=PAIS6 | D2_ALL)
        rev = await _create_funcionario(db, ilpi)
        res = await _create_residente(db, ilpi.id)
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        pid, iid = await _setup_pais_vigente(client, h, res.id, rev.id)
        r = await client.post("/api/programacoes-cuidado/", json=_prog_payload(pid, iid), headers=h)
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["autor_id"] == user.id and body["ilpi_id"] == ilpi.id and body["situacao"] == "ativa"
        assert body["residente_id"] == res.id
        r = await client.get("/api/ocorrencias-cuidado/", params={"programacao_id": body["id"]}, headers=h)
        assert r.status_code == 200 and len(r.json()) >= 10, r.text
        assert all(o["pendente"] for o in r.json())
    asyncio.run(_with_client(rotina_db, op))


def test_04_payload_hostil_rejeitado(rotina_db):
    async def op(client, db):
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=PAIS6 | D2_ALL)
        rev = await _create_funcionario(db, ilpi)
        res = await _create_residente(db, ilpi.id)
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        pid, iid = await _setup_pais_vigente(client, h, res.id, rev.id)
        payload = _prog_payload(pid, iid) | {"ilpi_id": _new_id(), "autor_id": _new_id()}
        assert (await client.post("/api/programacoes-cuidado/", json=payload, headers=h)).status_code == 422
    asyncio.run(_with_client(rotina_db, op))


def test_05_pais_precisa_estar_vigente(rotina_db):
    async def op(client, db):
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=PAIS6 | D2_ALL)
        rev = await _create_funcionario(db, ilpi)
        res = await _create_residente(db, ilpi.id)
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        r = await client.post("/api/planos-cuidados/",
                              json={"residente_id": res.id, "data_inicial": "2026-09-01"}, headers=h)
        pid = r.json()["id"]
        await client.patch(f"/api/planos-cuidados/{pid}", json={"situacao": "em_elaboracao"}, headers=h)
        r = await client.post(f"/api/planos-cuidados/{pid}/intervencoes", json={"descricao": "I"}, headers=h)
        iid = r.json()["id"]
        r = await client.post("/api/programacoes-cuidado/", json=_prog_payload(pid, iid), headers=h)
        assert r.status_code == 422, r.text
    asyncio.run(_with_client(rotina_db, op))


def test_06_cross_tenant_404(rotina_db):
    async def op(client, db):
        a = _new_institution("ILPI A")
        b = _new_institution("ILPI B")
        ua = await _create_ilpi_user(db, a, permissions=PAIS6 | D2_ALL, profile_key="pa")
        ub = await _create_ilpi_user(db, b, permissions=PAIS6 | D2_ALL, profile_key="pb")
        ra = await _create_funcionario(db, a, nome="Rev A")
        res = await _create_residente(db, a.id)
        await db.commit()
        ha, hb = _headers(ua, ilpi_id=a.id), _headers(ub, ilpi_id=b.id)
        pid, iid = await _setup_pais_vigente(client, ha, res.id, ra.id)
        r = await client.post("/api/programacoes-cuidado/", json=_prog_payload(pid, iid), headers=ha)
        prog_id = r.json()["id"]
        assert (await client.get(f"/api/programacoes-cuidado/{prog_id}", headers=hb)).status_code == 404
        r = await client.post("/api/programacoes-cuidado/", json=_prog_payload(pid, iid), headers=hb)
        assert r.status_code == 404 and _code(r) == RESOURCE_NOT_FOUND
        assert (await client.get("/api/plantao/", headers=hb)).status_code == 200
    asyncio.run(_with_client(rotina_db, op))


def test_07_horarios_invalidos_422(rotina_db):
    async def op(client, db):
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=PAIS6 | D2_ALL)
        rev = await _create_funcionario(db, ilpi)
        res = await _create_residente(db, ilpi.id)
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        pid, iid = await _setup_pais_vigente(client, h, res.id, rev.id)
        base = _prog_payload(pid, iid)
        assert (await client.post("/api/programacoes-cuidado/", json=base | {"horarios": ["08:00", "08:00"]}, headers=h)).status_code == 422
        assert (await client.post("/api/programacoes-cuidado/", json=base | {"horarios": ["25:00"]}, headers=h)).status_code == 422
        assert (await client.post("/api/programacoes-cuidado/", json=base | {"timezone": "America/Inexistente"}, headers=h)).status_code == 422
    asyncio.run(_with_client(rotina_db, op))


def test_08_idempotencia_reconciliacao(rotina_db):
    async def op(client, db):
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=PAIS6 | D2_ALL)
        rev = await _create_funcionario(db, ilpi)
        res = await _create_residente(db, ilpi.id)
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        pid, iid = await _setup_pais_vigente(client, h, res.id, rev.id)
        r = await client.post("/api/programacoes-cuidado/", json=_prog_payload(pid, iid), headers=h)
        prog_id = r.json()["id"]
        n1 = len((await client.get("/api/ocorrencias-cuidado/", params={"programacao_id": prog_id}, headers=h)).json())
        r = await client.post(f"/api/programacoes-cuidado/{prog_id}/reconciliar", headers=h)
        assert r.status_code == 200, r.text
        n2 = len((await client.get("/api/ocorrencias-cuidado/", params={"programacao_id": prog_id}, headers=h)).json())
        assert n1 == n2 and n1 >= 10
    asyncio.run(_with_client(rotina_db, op))


def test_09_execucao_fluxo_basico(rotina_db):
    async def op(client, db):
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=PAIS6 | D2_ALL)
        rev = await _create_funcionario(db, ilpi)
        res = await _create_residente(db, ilpi.id)
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        pid, iid = await _setup_pais_vigente(client, h, res.id, rev.id)
        r = await client.post("/api/programacoes-cuidado/", json=_prog_payload(pid, iid), headers=h)
        prog_id = r.json()["id"]
        ocorrencias = (await client.get("/api/ocorrencias-cuidado/", params={"programacao_id": prog_id}, headers=h)).json()
        oid = ocorrencias[0]["id"]
        assert (await client.post("/api/execucoes-cuidado/", json={
            "ocorrencia_id": oid, "resultado": "recusada",
            "ocorrido_em": datetime.now(timezone.utc).isoformat()}, headers=h)).status_code == 422
        r = await client.post("/api/execucoes-cuidado/", json={
            "ocorrencia_id": oid, "resultado": "executada",
            "ocorrido_em": datetime.now(timezone.utc).isoformat(), "observacao": "ok"}, headers=h)
        assert r.status_code == 201, r.text
        assert r.json()["executor_id"] == user.id
        r = await client.get(f"/api/ocorrencias-cuidado/{oid}", headers=h)
        assert r.json()["pendente"] is False
        r = await client.post("/api/execucoes-cuidado/", json={
            "ocorrencia_id": oid, "resultado": "omitida", "justificativa": "x",
            "ocorrido_em": datetime.now(timezone.utc).isoformat()}, headers=h)
        assert r.status_code == 409, r.text
        assert (await client.post("/api/execucoes-cuidado/", json={
            "ocorrencia_id": oid, "resultado": "executada",
            "ocorrido_em": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()}, headers=h)).status_code == 422
    asyncio.run(_with_client(rotina_db, op))


def test_10_recusa_omisao_exigem_justificativa(rotina_db):
    async def op(client, db):
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=PAIS6 | D2_ALL)
        rev = await _create_funcionario(db, ilpi)
        res = await _create_residente(db, ilpi.id)
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        pid, iid = await _setup_pais_vigente(client, h, res.id, rev.id)
        r = await client.post("/api/programacoes-cuidado/", json=_prog_payload(pid, iid), headers=h)
        prog_id = r.json()["id"]
        ocorrencias = (await client.get("/api/ocorrencias-cuidado/", params={"programacao_id": prog_id}, headers=h)).json()
        r = await client.post("/api/execucoes-cuidado/", json={
            "ocorrencia_id": ocorrencias[0]["id"], "resultado": "recusada",
            "ocorrido_em": datetime.now(timezone.utc).isoformat(), "justificativa": "Recusou banho"}, headers=h)
        assert r.status_code == 201, r.text
        r = await client.post("/api/execucoes-cuidado/", json={
            "ocorrencia_id": ocorrencias[1]["id"], "resultado": "omitida",
            "ocorrido_em": datetime.now(timezone.utc).isoformat(), "justificativa": "Intercorrencia"}, headers=h)
        assert r.status_code == 201, r.text
    asyncio.run(_with_client(rotina_db, op))


def test_11_estorno_e_substituto(rotina_db):
    async def op(client, db):
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=PAIS6 | D2_ALL)
        rev = await _create_funcionario(db, ilpi)
        res = await _create_residente(db, ilpi.id)
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        pid, iid = await _setup_pais_vigente(client, h, res.id, rev.id)
        r = await client.post("/api/programacoes-cuidado/", json=_prog_payload(pid, iid), headers=h)
        prog_id = r.json()["id"]
        oid = (await client.get("/api/ocorrencias-cuidado/", params={"programacao_id": prog_id}, headers=h)).json()[0]["id"]
        r = await client.post("/api/execucoes-cuidado/", json={
            "ocorrencia_id": oid, "resultado": "executada",
            "ocorrido_em": datetime.now(timezone.utc).isoformat()}, headers=h)
        eid = r.json()["id"]
        agora = datetime.now(timezone.utc).isoformat()
        r = await client.post(f"/api/execucoes-cuidado/{eid}/estornar", json={
            "motivo": "Registro errado",
            "substituto": {"ocorrencia_id": oid, "resultado": "omitida",
                           "ocorrido_em": agora, "justificativa": "Queda de energia"}}, headers=h)
        assert r.status_code == 200, r.text
        assert r.json()["estornado_em"] is not None and r.json()["substituto"]["resultado"] == "omitida"
        assert (await client.post(f"/api/execucoes-cuidado/{eid}/estornar", json={"motivo": "x"}, headers=h)).status_code == 409
        r = await client.get(f"/api/ocorrencias-cuidado/{oid}", headers=h)
        assert r.json()["pendente"] is False
    asyncio.run(_with_client(rotina_db, op))


def test_12_cancelamentos(rotina_db):
    async def op(client, db):
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=PAIS6 | D2_ALL)
        rev = await _create_funcionario(db, ilpi)
        res = await _create_residente(db, ilpi.id)
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        pid, iid = await _setup_pais_vigente(client, h, res.id, rev.id)
        r = await client.post("/api/programacoes-cuidado/", json=_prog_payload(pid, iid), headers=h)
        prog_id = r.json()["id"]
        ocorrencias = (await client.get("/api/ocorrencias-cuidado/", params={"programacao_id": prog_id}, headers=h)).json()
        oid = ocorrencias[0]["id"]
        assert (await client.post(f"/api/ocorrencias-cuidado/{oid}/cancelar", json={}, headers=h)).status_code == 422
        r = await client.post("/api/execucoes-cuidado/", json={
            "ocorrencia_id": oid, "resultado": "executada",
            "ocorrido_em": datetime.now(timezone.utc).isoformat()}, headers=h)
        assert r.status_code == 201
        assert (await client.post(f"/api/ocorrencias-cuidado/{oid}/cancelar", json={"motivo": "x"}, headers=h)).status_code == 409
        oid2 = ocorrencias[1]["id"]
        r = await client.post(f"/api/ocorrencias-cuidado/{oid2}/cancelar", json={"motivo": "Familia levou"}, headers=h)
        assert r.status_code == 200 and r.json()["situacao"] == "cancelada"
        r = await client.post("/api/execucoes-cuidado/", json={
            "ocorrencia_id": oid2, "resultado": "executada",
            "ocorrido_em": datetime.now(timezone.utc).isoformat()}, headers=h)
        assert r.status_code == 409, r.text
        r = await client.post(f"/api/programacoes-cuidado/{prog_id}/cancelar", json={"motivo": "Alta"}, headers=h)
        assert r.status_code == 200 and r.json()["situacao"] == "cancelada"
        restantes = (await client.get("/api/ocorrencias-cuidado/",
                                      params={"programacao_id": prog_id, "pendentes": True}, headers=h)).json()
        agora = datetime.now(timezone.utc).isoformat()
        # Cancelamento da programação só atinge o futuro; passado pendente fica p/ trato manual.
        assert all(o["previsto_em"] <= agora for o in restantes)
    asyncio.run(_with_client(rotina_db, op))


def test_13_pais_nova_versao_trava_futuro(rotina_db):
    async def op(client, db):
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=PAIS6 | D2_ALL)
        rev = await _create_funcionario(db, ilpi)
        res = await _create_residente(db, ilpi.id)
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        pid, iid = await _setup_pais_vigente(client, h, res.id, rev.id)
        r = await client.post("/api/programacoes-cuidado/", json=_prog_payload(pid, iid), headers=h)
        prog_id = r.json()["id"]
        oid = (await client.get("/api/ocorrencias-cuidado/", params={"programacao_id": prog_id}, headers=h)).json()[0]["id"]
        await client.post("/api/execucoes-cuidado/", json={
            "ocorrencia_id": oid, "resultado": "executada",
            "ocorrido_em": datetime.now(timezone.utc).isoformat()}, headers=h)
        r = await client.post(f"/api/planos-cuidados/{pid}/nova-versao", json={"motivo": "Reavaliacao"}, headers=h)
        v2 = r.json()["id"]
        await client.patch(f"/api/planos-cuidados/{v2}", json={"situacao": "em_elaboracao"}, headers=h)
        await client.post(f"/api/planos-cuidados/{v2}/revisar", json={"funcionario_id": rev.id}, headers=h)
        await client.post(f"/api/planos-cuidados/{v2}/aprovar", json={"funcionario_id": rev.id}, headers=h)
        assert (await client.post(f"/api/planos-cuidados/{v2}/ativar", headers=h)).status_code == 409
        await client.post(f"/api/planos-cuidados/{pid}/encerrar", json={"motivo": "Substituido", "funcionario_id": rev.id}, headers=h)
        assert (await client.post(f"/api/planos-cuidados/{v2}/ativar", headers=h)).status_code == 200
        assert (await client.post(f"/api/programacoes-cuidado/{prog_id}/reconciliar", headers=h)).status_code == 409
        futuras = (await client.get("/api/ocorrencias-cuidado/", params={"programacao_id": prog_id, "pendentes": True}, headers=h)).json()
        if futuras:
            r = await client.post(f"/api/ocorrencias-cuidado/{futuras[0]['id']}/cancelar", json={"motivo": "PAIS substituido"}, headers=h)
            assert r.status_code == 200
        execs = (await client.get("/api/execucoes-cuidado/", params={"ocorrencia_id": oid}, headers=h)).json()
        assert len(execs) == 1 and execs[0]["estornado_em"] is None
    asyncio.run(_with_client(rotina_db, op))


def test_14_meu_plantao_projecao(rotina_db):
    async def op(client, db):
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=PAIS6 | D2_ALL | {"intercorrencias:criar"})
        rev = await _create_funcionario(db, ilpi)
        res = await _create_residente(db, ilpi.id)
        await db.flush()
        db.add(m.Intercorrencia(id=_new_id(), residente_id=res.id, ilpi_id=ilpi.id, tipo="Queda", situacao="aberta"))
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        pid, iid = await _setup_pais_vigente(client, h, res.id, rev.id)
        await client.post("/api/programacoes-cuidado/", json=_prog_payload(pid, iid), headers=h)
        antes = {
            "ocorr": (await db.execute(select(m.OcorrenciaCuidado.id))).scalars().all(),
            "exec": (await db.execute(select(m.ExecucaoCuidado.id))).scalars().all(),
        }
        r = await client.get("/api/plantao/", headers=h)
        assert r.status_code == 200, r.text
        itens = r.json()
        origens = {i["origem"] for i in itens}
        assert "cuidado" in origens and "intercorrencia" in origens
        assert all({"origem", "registro_id", "residente_id", "descricao"} <= set(i) for i in itens)
        depois = {
            "ocorr": (await db.execute(select(m.OcorrenciaCuidado.id))).scalars().all(),
            "exec": (await db.execute(select(m.ExecucaoCuidado.id))).scalars().all(),
        }
        assert antes == depois
        r = await client.get("/api/plantao/", params={"residente_id": _new_id()}, headers=h)
        assert r.status_code == 404
    asyncio.run(_with_client(rotina_db, op))


def test_15_delete_bloqueado_e_patch_controlado(rotina_db):
    async def op(client, db):
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=PAIS6 | D2_ALL)
        rev = await _create_funcionario(db, ilpi)
        res = await _create_residente(db, ilpi.id)
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        pid, iid = await _setup_pais_vigente(client, h, res.id, rev.id)
        r = await client.post("/api/programacoes-cuidado/", json=_prog_payload(pid, iid), headers=h)
        prog_id = r.json()["id"]
        assert (await client.delete(f"/api/programacoes-cuidado/{prog_id}", headers=h)).status_code == 405
        oid = (await client.get("/api/ocorrencias-cuidado/", params={"programacao_id": prog_id}, headers=h)).json()[0]["id"]
        assert (await client.delete(f"/api/ocorrencias-cuidado/{oid}", headers=h)).status_code == 405
        r = await client.patch(f"/api/programacoes-cuidado/{prog_id}", json={"horarios": ["09:00"]}, headers=h)
        assert r.status_code == 422, r.text
        passado = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        r = await client.patch(f"/api/programacoes-cuidado/{prog_id}", json={"vigencia_fim": passado}, headers=h)
        assert r.status_code == 422, r.text
        r = await client.patch(f"/api/programacoes-cuidado/{prog_id}", json={"prioridade": "baixa"}, headers=h)
        assert r.status_code == 200 and r.json()["prioridade"] == "baixa"
    asyncio.run(_with_client(rotina_db, op))


def test_16_rbac_granular(rotina_db):
    async def op(client, db):
        ilpi = _new_institution()
        full = await _create_ilpi_user(db, ilpi, permissions=PAIS6 | D2_ALL, profile_key="full")
        leitor = await _create_ilpi_user(db, ilpi, permissions={"programacoes:ler", "ocorrencias:ler", "execucoes:ler", "plantao:ler"},
                                         profile_key="ro", nome="Leitor")
        rev = await _create_funcionario(db, ilpi)
        res = await _create_residente(db, ilpi.id)
        await db.commit()
        hf, hr = _headers(full, ilpi_id=ilpi.id), _headers(leitor, ilpi_id=ilpi.id)
        pid, iid = await _setup_pais_vigente(client, hf, res.id, rev.id)
        r = await client.post("/api/programacoes-cuidado/", json=_prog_payload(pid, iid), headers=hf)
        prog_id = r.json()["id"]
        assert (await client.post("/api/programacoes-cuidado/", json=_prog_payload(pid, iid), headers=hr)).status_code == 403
        oid = (await client.get("/api/ocorrencias-cuidado/", params={"programacao_id": prog_id}, headers=hr)).json()[0]["id"]
        assert (await client.post(f"/api/ocorrencias-cuidado/{oid}/cancelar", json={"motivo": "x"}, headers=hr)).status_code == 403
        assert (await client.post("/api/execucoes-cuidado/", json={
            "ocorrencia_id": oid, "resultado": "executada",
            "ocorrido_em": datetime.now(timezone.utc).isoformat()}, headers=hr)).status_code == 403
    asyncio.run(_with_client(rotina_db, op))


def test_17_auditoria_rotina(rotina_db):
    async def op(client, db):
        ilpi = _new_institution()
        user = await _create_ilpi_user(db, ilpi, permissions=PAIS6 | D2_ALL)
        rev = await _create_funcionario(db, ilpi)
        res = await _create_residente(db, ilpi.id)
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        pid, iid = await _setup_pais_vigente(client, h, res.id, rev.id)
        r = await client.post("/api/programacoes-cuidado/", json=_prog_payload(pid, iid), headers=h)
        prog_id = r.json()["id"]
        oid = (await client.get("/api/ocorrencias-cuidado/", params={"programacao_id": prog_id}, headers=h)).json()[0]["id"]
        await client.post("/api/execucoes-cuidado/", json={
            "ocorrencia_id": oid, "resultado": "executada",
            "ocorrido_em": datetime.now(timezone.utc).isoformat()}, headers=h)
        await client.post(f"/api/programacoes-cuidado/{prog_id}/cancelar", json={"motivo": "Fim"}, headers=h)
        rows = (await db.execute(select(m.Auditoria.acao).where(m.Auditoria.ilpi_id == ilpi.id))).scalars().all()
        for expected in ("programacoes_cuidado.criar", "ocorrencias_cuidado.materializar",
                         "execucoes_cuidado.registrar", "programacoes_cuidado.cancelar"):
            assert expected in rows, f"auditoria sem {expected}"
    asyncio.run(_with_client(rotina_db, op))
