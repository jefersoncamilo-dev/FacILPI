"""Disposable-database tests for S.1: matriz institucional de permissões.

Templates explícitos, atribuição com anti-escalation, profissão≠permissão.
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
from src.application import fase3a  # noqa: E402
from src.application.auth import create_access_token  # noqa: E402
from src.application.security import PERMISSION_DENIED  # noqa: E402
from src.infrastructure import database  # noqa: E402
from src.infrastructure import models as m  # noqa: E402


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
    assert parsed.port == 55485 and parsed.database == "facilpi_s1_test"


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


@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("S1_TEST_POSTGRES_URL") else []))
def s1_db(request, tmp_path):
    if request.param == "sqlite":
        path = tmp_path / "s1-matriz.db"
        _run_migration(path)
        return path
    url = os.environ["S1_TEST_POSTGRES_URL"]
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


def _new_user(nome="Usuario S.1") -> m.User:
    user_id = _new_id()
    return m.User(id=user_id, nome=nome, email=f"s1-{user_id}@example.com",
                  password_hash="fixture-password-hash", ativo=True)


def _new_institution(name="ILPI S.1") -> m.Instituicao:
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
    existing = set((await db.execute(select(m.PerfilPermissao.permissao_id).where(
        m.PerfilPermissao.perfil_id == perfil_id))).scalars().all())
    for perm in perms:
        if perm.id not in existing:
            db.add(m.PerfilPermissao(perfil_id=perfil_id, permissao_id=perm.id))
    await db.flush()


async def _clone(db, chave, ilpi_id) -> m.Perfil:
    return (await db.execute(select(m.Perfil).where(
        m.Perfil.chave == chave, m.Perfil.ilpi_id == ilpi_id))).scalar_one()


async def _create_admin(db, institution) -> m.User:
    """ilpi_admin clone + vínculo + funcionário ativo (administração institucional)."""
    user = _new_user("Admin S.1")
    db.add_all([institution, user])
    await db.flush()
    await fase3a._clone_ilpi_admin_profile(db, institution.id, None, user.id)
    clone = (await db.execute(select(m.Perfil).where(
        m.Perfil.chave == "ilpi_admin", m.Perfil.ilpi_id == institution.id))).scalar_one()
    db.add_all([m.Funcionario(id=_new_id(), ilpi_id=institution.id, usuario_id=user.id,
                              nome=user.nome, email=user.email, situacao="ativo"),
                _new_link(user.id, clone.id, institution.id)])
    await db.flush()
    return user


async def _create_plain_user(db, institution, *, profile_keys=("x",), nome="Alvo S.1") -> m.User:
    """Usuário com vínculo ativo no tenant e perfil customizado mínimo."""
    user = _new_user(nome)
    profile = m.Perfil(id=_new_id(), ilpi_id=institution.id, nome="Custom", chave=f"custom-{_new_id()[:8]}",
                       escopo="ilpi", situacao="ativo")
    db.add_all([institution, user])
    await db.flush()
    db.add(profile)
    await db.flush()
    db.add_all([m.Funcionario(id=_new_id(), ilpi_id=institution.id, usuario_id=user.id,
                              nome=user.nome, email=user.email, situacao="ativo"),
                _new_link(user.id, profile.id, institution.id)])
    await db.flush()
    return user


def _headers(user, *, scope="ilpi", ilpi_id=None, perfil_id=None):
    headers = {"Authorization": f"Bearer {create_access_token(user)}", "X-Scope": scope}
    if ilpi_id is not None:
        headers["X-ILPI-ID"] = ilpi_id
    if perfil_id is not None:
        headers["X-Perfil-ID"] = perfil_id
    return headers


def _code(response):
    detail = response.json().get("detail")
    return detail.get("code") if isinstance(detail, dict) else None


async def _user_keys(db, user_id):
    return {row[0] for row in (await db.execute(select(m.Permissao.chave).join(
        m.PerfilPermissao, m.PerfilPermissao.permissao_id == m.Permissao.id).join(
        m.Perfil, m.Perfil.id == m.PerfilPermissao.perfil_id).join(
        m.UsuarioIlpiPerfil, m.UsuarioIlpiPerfil.perfil_id == m.Perfil.id).where(
        m.UsuarioIlpiPerfil.usuario_id == user_id,
        m.UsuarioIlpiPerfil.situacao == "ativo"))).all()}


def test_01_templates_e_baseline(s1_db):
    async def op(client, db):
        assert (await db.execute(select(m.Permissao.id))).scalars().all().__len__() == 93
        templates = (await db.execute(select(m.Perfil).where(
            m.Perfil.ilpi_id.is_(None), m.Perfil.chave.in_(
                ["cuidador", "enfermagem", "medico", "responsavel_tecnico", "administrativo"])))).scalars().all()
        assert {t.chave for t in templates} == {"cuidador", "enfermagem", "medico", "responsavel_tecnico", "administrativo"}
        assert all(t.escopo == "ilpi" and t.situacao == "ativo" for t in templates)
        rt = next(t for t in templates if t.chave == "responsavel_tecnico")
        keys = {row[0] for row in (await db.execute(select(m.Permissao.chave).join(
            m.PerfilPermissao, m.PerfilPermissao.permissao_id == m.Permissao.id).where(
            m.PerfilPermissao.perfil_id == rt.id))).all()}
        assert {"planos_cuidados:aprovar", "planos_cuidados:revisar", "execucoes:corrigir"} <= keys
        cu = next(t for t in templates if t.chave == "cuidador")
        cuk = {row[0] for row in (await db.execute(select(m.Permissao.chave).join(
            m.PerfilPermissao, m.PerfilPermissao.permissao_id == m.Permissao.id).where(
            m.PerfilPermissao.perfil_id == cu.id))).all()}
        assert "administracoes:criar" not in cuk and "planos_cuidados:aprovar" not in cuk
        platform = (await db.execute(select(m.Permissao.chave).join(
            m.PerfilPermissao, m.PerfilPermissao.permissao_id == m.Permissao.id).join(
            m.Perfil, m.Perfil.id == m.PerfilPermissao.perfil_id).where(
            m.Perfil.chave == "platform_superuser"))).scalars().all()
        assert len(platform) == 15
    asyncio.run(_with_client(s1_db, op))


def test_02_listar_e_atribuir(s1_db):
    async def op(client, db):
        ilpi = _new_institution()
        admin = await _create_admin(db, ilpi)
        alvo = await _create_plain_user(db, ilpi)
        await db.commit()
        ha = _headers(admin, ilpi_id=ilpi.id)
        r = await client.get("/api/matriz/perfis", headers=ha)
        assert r.status_code == 200 and {p["chave"] for p in r.json()} == {
            "cuidador", "enfermagem", "medico", "responsavel_tecnico", "administrativo"}
        r = await client.post("/api/matriz/atribuicoes",
                              json={"usuario_id": alvo.id, "perfil_chave": "cuidador"}, headers=ha)
        assert r.status_code == 201, r.text
        assert r.json()["reativado"] is False
        clone = (await db.execute(select(m.Perfil).where(
            m.Perfil.chave == "cuidador", m.Perfil.ilpi_id == ilpi.id))).scalar_one()
        assert (await _user_keys(db, alvo.id)) >= {"execucoes:criar", "plantao:ler"}
        assert (await client.post("/api/matriz/atribuicoes",
                                  json={"usuario_id": alvo.id, "perfil_chave": "cuidador"}, headers=ha)).status_code == 409
        assert clone.id is not None
    asyncio.run(_with_client(s1_db, op))


def test_03_revogar_e_reativar(s1_db):
    async def op(client, db):
        ilpi = _new_institution()
        admin = await _create_admin(db, ilpi)
        alvo = await _create_plain_user(db, ilpi)
        await db.commit()
        ha = _headers(admin, ilpi_id=ilpi.id)
        await client.post("/api/matriz/atribuicoes",
                          json={"usuario_id": alvo.id, "perfil_chave": "enfermagem"}, headers=ha)
        assert await _user_keys(db, alvo.id) >= {"administracoes:criar"}
        r = await client.post("/api/matriz/revogacoes",
                              json={"usuario_id": alvo.id, "perfil_chave": "enfermagem"}, headers=ha)
        assert r.status_code == 200, r.text
        assert "administracoes:criar" not in await _user_keys(db, alvo.id)
        assert (await client.post("/api/matriz/revogacoes",
                                  json={"usuario_id": alvo.id, "perfil_chave": "enfermagem"}, headers=ha)).status_code == 404
        r = await client.post("/api/matriz/atribuicoes",
                              json={"usuario_id": alvo.id, "perfil_chave": "enfermagem"}, headers=ha)
        assert r.status_code == 201 and r.json()["reativado"] is True
        rows = (await db.execute(select(m.Auditoria.acao).where(m.Auditoria.ilpi_id == ilpi.id))).scalars().all()
        assert "usuario_ilpi_perfil.revogado" in rows and "usuario_ilpi_perfil.reativado" in rows
    asyncio.run(_with_client(s1_db, op))


def test_04_escalation_bloqueada(s1_db):
    async def op(client, db):
        ilpi = _new_institution()
        admin = await _create_admin(db, ilpi)
        limitado = await _create_plain_user(db, ilpi, nome="Limitado")
        profile = (await db.execute(select(m.Perfil).join(
            m.UsuarioIlpiPerfil, m.UsuarioIlpiPerfil.perfil_id == m.Perfil.id).where(
            m.UsuarioIlpiPerfil.usuario_id == limitado.id))).scalar_one()
        await _grant(db, profile.id, {"usuarios:atribuir_perfil"})
        alvo = await _create_plain_user(db, ilpi, nome="Alvo")
        await db.commit()
        hl = _headers(limitado, ilpi_id=ilpi.id)
        r = await client.post("/api/matriz/atribuicoes",
                              json={"usuario_id": alvo.id, "perfil_chave": "enfermagem"}, headers=hl)
        assert r.status_code == 403 and _code(r) == "PERMISSAO_ESCALATION", r.text
        # Subconjunto legítimo: atribuidor com superset explícito pode atribuir.
        ha = _headers(admin, ilpi_id=ilpi.id)
        chefe = await _create_plain_user(db, ilpi, nome="Chefe")
        profile_chefe = (await db.execute(select(m.Perfil).join(
            m.UsuarioIlpiPerfil, m.UsuarioIlpiPerfil.perfil_id == m.Perfil.id).where(
            m.UsuarioIlpiPerfil.usuario_id == chefe.id))).scalar_one()
        await _grant(db, profile_chefe.id, {"usuarios:atribuir_perfil", "residentes:ler",
                     "planos_cuidados:ler", "programacoes:ler", "ocorrencias:ler",
                     "execucoes:ler", "execucoes:criar", "plantao:ler", "sinais_vitais:ler"})
        await db.commit()
        hc = _headers(chefe, ilpi_id=ilpi.id)
        r = await client.post("/api/matriz/atribuicoes",
                              json={"usuario_id": alvo.id, "perfil_chave": "cuidador"}, headers=hc)
        assert r.status_code == 201, r.text
    asyncio.run(_with_client(s1_db, op))


def test_05_cross_tenant_e_chaves_invalidas(s1_db):
    async def op(client, db):
        a = _new_institution("ILPI A")
        b = _new_institution("ILPI B")
        admin_a = await _create_admin(db, a)
        await _create_admin(db, b)
        alvo_b = await _create_plain_user(db, b, nome="Alvo B")
        await db.commit()
        ha = _headers(admin_a, ilpi_id=a.id)
        r = await client.post("/api/matriz/atribuicoes",
                              json={"usuario_id": alvo_b.id, "perfil_chave": "cuidador"}, headers=ha)
        assert r.status_code == 404, r.text
        assert (await client.post("/api/matriz/atribuicoes",
                                  json={"usuario_id": alvo_b.id, "perfil_chave": "platform_superuser"},
                                  headers=ha)).status_code == 422
    asyncio.run(_with_client(s1_db, op))


def test_06_cuidador_executa_sem_aprovar_nem_medicar(s1_db):
    async def op(client, db):
        ilpi = _new_institution()
        admin = await _create_admin(db, ilpi)
        await _grant(db, (await db.execute(select(m.Perfil).where(
            m.Perfil.chave == "ilpi_admin", m.Perfil.ilpi_id == ilpi.id))).scalar_one().id,
            {"planos_cuidados:ler", "planos_cuidados:criar", "planos_cuidados:atualizar",
             "planos_cuidados:revisar", "planos_cuidados:aprovar",
             "programacoes:ler", "programacoes:criar", "ocorrencias:ler", "execucoes:ler"})
        alvo = await _create_plain_user(db, ilpi, nome="Cuidador")
        res = m.Residente(id=_new_id(), instituicao_id=ilpi.id, nome="Res S.1", data_nascimento=date(1940, 5, 1))
        db.add(res)
        await db.flush()
        rev = m.Funcionario(id=_new_id(), ilpi_id=ilpi.id, nome="Rev", situacao="ativo")
        db.add(rev)
        await db.commit()
        ha = _headers(admin, ilpi_id=ilpi.id)
        await client.post("/api/matriz/atribuicoes",
                          json={"usuario_id": alvo.id, "perfil_chave": "cuidador"}, headers=ha)
        ht = _headers(alvo, ilpi_id=ilpi.id, perfil_id=(await _clone(db, "cuidador", ilpi.id)).id)
        # setup pelo admin até ocorrência pendente
        # setup pelo admin até ocorrência pendente
        r = await client.post("/api/planos-cuidados/",
                              json={"residente_id": res.id, "data_inicial": "2026-09-01"}, headers=ha)
        pid = r.json()["id"]
        await client.patch(f"/api/planos-cuidados/{pid}", json={"situacao": "em_elaboracao"}, headers=ha)
        await client.post(f"/api/planos-cuidados/{pid}/necessidades", json={"descricao": "N", "origem": "manual"}, headers=ha)
        await client.post(f"/api/planos-cuidados/{pid}/metas", json={"descricao": "M"}, headers=ha)
        r = await client.post(f"/api/planos-cuidados/{pid}/intervencoes", json={"descricao": "I"}, headers=ha)
        iid = r.json()["id"]
        await client.post(f"/api/planos-cuidados/{pid}/revisar", json={"funcionario_id": rev.id}, headers=ha)
        await client.post(f"/api/planos-cuidados/{pid}/aprovar", json={"funcionario_id": rev.id}, headers=ha)
        await client.post(f"/api/planos-cuidados/{pid}/ativar", headers=ha)
        inicio = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        r = await client.post("/api/programacoes-cuidado/",
                              json={"plano_id": pid, "intervencao_id": iid, "horarios": ["08:00"],
                                    "timezone": "America/Sao_Paulo", "vigencia_inicio": inicio}, headers=ha)
        prog_id = r.json()["id"]
        oid = (await client.get("/api/ocorrencias-cuidado/", params={"programacao_id": prog_id}, headers=ha)).json()[0]["id"]
        r = await client.post("/api/execucoes-cuidado/", json={
            "ocorrencia_id": oid, "resultado": "executada",
            "ocorrido_em": datetime.now(timezone.utc).isoformat()}, headers=ht)
        assert r.status_code == 201, r.text
        assert (await client.post(f"/api/planos-cuidados/{pid}/aprovar",
                                  json={"funcionario_id": rev.id}, headers=ht)).status_code == 403
        assert (await client.post("/api/administracoes/", json={}, headers=ht)).status_code == 403
    asyncio.run(_with_client(s1_db, op))


def test_07_enfermagem_medica_medico(s1_db):
    async def op(client, db):
        ilpi = _new_institution()
        admin = await _create_admin(db, ilpi)
        await _grant(db, (await db.execute(select(m.Perfil).where(
            m.Perfil.chave == "ilpi_admin", m.Perfil.ilpi_id == ilpi.id))).scalar_one().id,
            {"medicamentos:ler", "medicamentos:criar", "prescricoes:ler", "prescricoes:criar",
             "prescricoes:atualizar", "doses_previstas:ler"})
        enf = await _create_plain_user(db, ilpi, nome="Enf")
        med = await _create_plain_user(db, ilpi, nome="Med")
        res = m.Residente(id=_new_id(), instituicao_id=ilpi.id, nome="Res Med", data_nascimento=date(1940, 5, 1))
        db.add(res)
        await db.commit()
        ha = _headers(admin, ilpi_id=ilpi.id)
        await client.post("/api/matriz/atribuicoes", json={"usuario_id": enf.id, "perfil_chave": "enfermagem"}, headers=ha)
        await client.post("/api/matriz/atribuicoes", json={"usuario_id": med.id, "perfil_chave": "medico"}, headers=ha)
        he = _headers(enf, ilpi_id=ilpi.id, perfil_id=(await _clone(db, "enfermagem", ilpi.id)).id)
        hm = _headers(med, ilpi_id=ilpi.id, perfil_id=(await _clone(db, "medico", ilpi.id)).id)
        r = await client.post("/api/medicamentos/",
                              json={"nome": "Dipirona", "principio_ativo": "Dipirona"}, headers=ha)
        med_id = r.json()["id"]
        r = await client.post("/api/prescricoes/", json={
            "residente_id": res.id, "medicamento_id": med_id, "prescritor_nome": "Dr S1",
            "prescritor_categoria": "Medico", "dose": "1", "unidade": "cp", "via": "oral",
            "inicio": "2026-09-01"}, headers=hm)
        assert r.status_code == 201, r.text
        presc_id = r.json()["id"]
        assert (await client.post("/api/prescricoes/", json={
            "residente_id": res.id, "medicamento_id": med_id, "prescritor_nome": "Enf",
            "prescritor_categoria": "Enfermeiro", "dose": "1", "unidade": "cp", "via": "oral",
            "inicio": "2026-09-01"}, headers=he)).status_code == 403
        inicio = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        r = await client.post(f"/api/prescricoes/{presc_id}/ativar", json={
            "horarios": ["08:00"], "timezone": "America/Sao_Paulo", "vigencia_inicio": inicio}, headers=ha)
        assert r.status_code == 200, r.text
        dose_id = (await client.get("/api/doses-previstas/", params={"prescricao_id": presc_id}, headers=ha)).json()[0]["id"]
        agora = datetime.now(timezone.utc).isoformat()
        r = await client.post("/api/administracoes/", json={
            "dose_prevista_id": dose_id, "resultado": "administrada",
            "ocorrido_em": agora, "quantidade_realizada": "1"}, headers=he)
        assert r.status_code == 201, r.text
        assert (await client.post("/api/administracoes/", json={
            "dose_prevista_id": dose_id, "resultado": "administrada",
            "ocorrido_em": agora, "quantidade_realizada": "1"}, headers=hm)).status_code == 403
    asyncio.run(_with_client(s1_db, op))


def test_08_rt_aprova_e_adm_nao_clinica(s1_db):
    async def op(client, db):
        ilpi = _new_institution()
        admin = await _create_admin(db, ilpi)
        await _grant(db, (await db.execute(select(m.Perfil).where(
            m.Perfil.chave == "ilpi_admin", m.Perfil.ilpi_id == ilpi.id))).scalar_one().id,
            {"planos_cuidados:ler", "planos_cuidados:criar", "planos_cuidados:atualizar",
             "planos_cuidados:revisar"})
        rt = await _create_plain_user(db, ilpi, nome="RT")
        adm = await _create_plain_user(db, ilpi, nome="Adm")
        res = m.Residente(id=_new_id(), instituicao_id=ilpi.id, nome="Res RT", data_nascimento=date(1940, 5, 1))
        db.add(res)
        await db.flush()
        rev = m.Funcionario(id=_new_id(), ilpi_id=ilpi.id, nome="Rev", situacao="ativo")
        db.add(rev)
        await db.commit()
        ha = _headers(admin, ilpi_id=ilpi.id)
        await client.post("/api/matriz/atribuicoes", json={"usuario_id": rt.id, "perfil_chave": "responsavel_tecnico"}, headers=ha)
        await client.post("/api/matriz/atribuicoes", json={"usuario_id": adm.id, "perfil_chave": "administrativo"}, headers=ha)
        ht = _headers(rt, ilpi_id=ilpi.id, perfil_id=(await _clone(db, "responsavel_tecnico", ilpi.id)).id)
        hd = _headers(adm, ilpi_id=ilpi.id, perfil_id=(await _clone(db, "administrativo", ilpi.id)).id)
        r = await client.post("/api/planos-cuidados/",
                              json={"residente_id": res.id, "data_inicial": "2026-09-01"}, headers=ha)
        pid = r.json()["id"]
        await client.patch(f"/api/planos-cuidados/{pid}", json={"situacao": "em_elaboracao"}, headers=ha)
        await client.post(f"/api/planos-cuidados/{pid}/necessidades", json={"descricao": "N", "origem": "manual"}, headers=ha)
        await client.post(f"/api/planos-cuidados/{pid}/metas", json={"descricao": "M"}, headers=ha)
        await client.post(f"/api/planos-cuidados/{pid}/intervencoes", json={"descricao": "I"}, headers=ha)
        await client.post(f"/api/planos-cuidados/{pid}/revisar", json={"funcionario_id": rev.id}, headers=ha)
        r = await client.post(f"/api/planos-cuidados/{pid}/aprovar", json={"funcionario_id": rev.id}, headers=ht)
        assert r.status_code == 200, r.text
        r = await client.post("/api/residentes/",
                              json={"nome": "Novo Res", "data_nascimento": "1940-01-01"}, headers=hd)
        assert r.status_code == 201, r.text
        assert (await client.post("/api/execucoes-cuidado/", json={
            "ocorrencia_id": _new_id(), "resultado": "executada",
            "ocorrido_em": datetime.now(timezone.utc).isoformat()}, headers=hd)).status_code == 403
    asyncio.run(_with_client(s1_db, op))


def test_09_profissao_nao_concede(s1_db):
    async def op(client, db):
        ilpi = _new_institution()
        admin = await _create_admin(db, ilpi)
        alvo = await _create_plain_user(db, ilpi, nome="Prof")
        await db.commit()
        ha = _headers(admin, ilpi_id=ilpi.id)
        await client.post("/api/matriz/atribuicoes",
                          json={"usuario_id": alvo.id, "perfil_chave": "cuidador"}, headers=ha)
        antes = await _user_keys(db, alvo.id)
        func = (await db.execute(select(m.Funcionario).where(
            m.Funcionario.usuario_id == alvo.id, m.Funcionario.ilpi_id == ilpi.id))).scalar_one()
        r = await client.put(f"/api/funcionarios/{func.id}", json={
            "profissao": "Médico", "cargo": "Responsável Técnico",
            "conselho_profissional": "CRM", "numero_conselho": "123", "uf_conselho": "SP"}, headers=ha)
        assert r.status_code == 200, r.text
        assert await _user_keys(db, alvo.id) == antes
        ht = _headers(alvo, ilpi_id=ilpi.id, perfil_id=(await _clone(db, "cuidador", ilpi.id)).id)
        assert (await client.post("/api/prescricoes/", json={}, headers=ht)).status_code == 403
    asyncio.run(_with_client(s1_db, op))


def test_10_sem_permissao_atribuir(s1_db):
    async def op(client, db):
        ilpi = _new_institution()
        admin = await _create_admin(db, ilpi)
        sem = await _create_plain_user(db, ilpi, nome="Sem")
        alvo = await _create_plain_user(db, ilpi, nome="Alvo2")
        await db.commit()
        hs = _headers(sem, ilpi_id=ilpi.id)
        r = await client.post("/api/matriz/atribuicoes",
                              json={"usuario_id": alvo.id, "perfil_chave": "cuidador"}, headers=hs)
        assert r.status_code == 403
        assert (await client.get("/api/matriz/perfis", headers=hs)).status_code == 403
        assert _code(r) == PERMISSION_DENIED
    asyncio.run(_with_client(s1_db, op))
