"""D.4: Prontuario Longitudinal como PROJECAO read-only."""
import asyncio
import base64
import json
import pathlib
import re
import subprocess
import sys
import uuid
import os
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import event, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
OFFICIAL_DB = ROOT / "storage" / "app.db"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from src import main
from src.application import auth
from src.application.auth import create_access_token
from src.application.security import PERMISSION_DENIED, RESOURCE_NOT_FOUND
from src.infrastructure import database
from src.infrastructure import models as m

ALL_CLINICAL = {
    "residentes:ler", "avaliacoes:ler", "avaliacoes:criar",
    "grau_dependencia:ler", "grau_dependencia:criar",
    "sinais_vitais:ler", "sinais_vitais:criar",
    "intercorrencias:ler", "intercorrencias:criar", "intercorrencias:atualizar",
    "prescricoes:ler", "prescricoes:criar", "prescricoes:atualizar",
    "medicamentos:ler", "medicamentos:criar", "medicamentos:atualizar",
    "doses_previstas:ler", "administracoes:ler", "administracoes:criar", "administracoes:corrigir",
    "planos_cuidados:ler", "planos_cuidados:criar", "planos_cuidados:atualizar", "planos_cuidados:revisar", "planos_cuidados:aprovar", "planos_cuidados:encerrar",
    "programacoes:ler", "programacoes:criar", "programacoes:atualizar", "programacoes:inativar",
    "ocorrencias:ler", "ocorrencias:cancelar",
    "execucoes:ler", "execucoes:criar", "execucoes:corrigir",
    "quartos_leitos:ler", "quartos_leitos:criar", "quartos_leitos:atualizar",
    "ausencias:ler", "ausencias:criar", "ausencias:atualizar",
}

def _sqlite_url(path: pathlib.Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"
def _async_url(url: str) -> str:
    return url.replace("postgresql://", "postgresql+asyncpg://", 1) if url.startswith("postgresql://") else url
def _assert_disposable_postgres(url: str) -> None:
    from sqlalchemy.engine import make_url
    parsed = make_url(url)
    assert parsed.get_backend_name()=="postgresql"
    assert parsed.host in {"localhost","127.0.0.1"}
    assert parsed.port==55486 and parsed.database=="facilpi_d4_test"
def _database_url(ref):
    return _sqlite_url(ref) if isinstance(ref, pathlib.Path) else _async_url(ref)
async def _reset_postgres(url:str):
    engine=create_async_engine(_async_url(url), poolclass=NullPool)
    try:
        async with engine.connect() as c:
            await c.execute(text("DROP SCHEMA public CASCADE"))
            await c.execute(text("CREATE SCHEMA public"))
            await c.commit()
    finally:
        await engine.dispose()
def _run_migration(ref):
    if isinstance(ref, pathlib.Path):
        assert ref.resolve()!=OFFICIAL_DB.resolve(), "must never write official"
    else:
        _assert_disposable_postgres(ref)
    url=_database_url(ref)
    env=os.environ.copy()
    env["DATABASE_URL"]=url
    env.pop("APP_DATABASE_URL",None)
    result=subprocess.run([sys.executable,"-m","alembic","-x",f"database_url={url}","upgrade","head"], cwd=BACKEND, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    assert result.returncode==0, result.stdout+result.stderr

@pytest.fixture(params=["sqlite"] + (["postgresql"] if os.getenv("D4_TEST_POSTGRES_URL") else []))
def prontuario_db(request, tmp_path):
    if request.param=="sqlite":
        path=tmp_path/"d4-prontuario.db"
        _run_migration(path)
        return path
    url=os.environ["D4_TEST_POSTGRES_URL"]
    _assert_disposable_postgres(url)
    try:
        asyncio.run(_reset_postgres(url))
        _run_migration(url)
    except Exception as e:
        pytest.skip(f"PG descartavel indisponivel: {e}")
    return url

async def _with_client(ref, op):
    engine=create_async_engine(_database_url(ref), poolclass=NullPool)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine.sync_engine, "connect")
        def enable_foreign_keys(connection, _record):
            cursor = connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
            finally:
                cursor.close()
    factory=async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async def override_get_db():
        async with factory() as s:
            yield s
    main.app.dependency_overrides[main.get_db]=override_get_db
    main.app.dependency_overrides[database.get_db]=override_get_db
    auth._rate_store.clear()
    transport=httpx.ASGITransport(app=main.app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver", follow_redirects=True) as client:
            async with factory() as session:
                return await op(client, session)
    finally:
        main.app.dependency_overrides.clear()
        await engine.dispose()

def _new_id(): return str(uuid.uuid4())
def _new_user(**kwargs):
    uid=_new_id()
    return m.User(id=uid, nome=kwargs.get("nome","Usuario D4"), email=f"d4-{uid}@example.com", password_hash="fixture", ativo=True)
def _new_inst(name="ILPI D4"):
    return m.Instituicao(id=_new_id(), razao_social=name, situacao="ILPI_RASCUNHO")
def _new_link(uid,pid,iid):
    return m.UsuarioIlpiPerfil(id=_new_id(), usuario_id=uid, perfil_id=pid, ilpi_id=iid, situacao="ativo", data_inicial=datetime.now(timezone.utc)-timedelta(minutes=1))
async def _grant(db,pid,keys):
    if not keys: return
    perms=(await db.execute(select(m.Permissao).where(m.Permissao.chave.in_(keys)))).scalars().all()
    assert {p.chave for p in perms}==keys
    for p in perms:
        db.add(m.PerfilPermissao(perfil_id=pid, permissao_id=p.id))
    await db.flush()
async def _create_ilpi_user(db, inst, *, permissions, profile_key="d4"):
    user=_new_user()
    perfil=m.Perfil(id=_new_id(), ilpi_id=inst.id, nome="Perfil D4", chave=profile_key, escopo="ilpi", situacao="ativo")
    db.add_all([inst,user])
    await db.flush()
    db.add(perfil)
    await db.flush()
    db.add_all([m.Funcionario(id=_new_id(), ilpi_id=inst.id, usuario_id=user.id, nome=user.nome, email=user.email, situacao="ativo"), _new_link(user.id, perfil.id, inst.id)])
    await db.flush()
    await _grant(db, perfil.id, permissions)
    return user
async def _create_platform_user(db):
    user=_new_user()
    perfil=(await db.execute(select(m.Perfil).where(m.Perfil.chave=="platform_superuser", m.Perfil.ilpi_id.is_(None)))).scalar_one()
    db.add(user)
    await db.flush()
    db.add(_new_link(user.id, perfil.id, None))
    await db.flush()
    return user
def _headers(user, *, scope="ilpi", ilpi_id=None):
    h={"Authorization": f"Bearer {create_access_token(user)}", "X-Scope": scope}
    if ilpi_id is not None:
        h["X-ILPI-ID"]=ilpi_id
    return h
async def _create_residente(db, ilpi_id, nome="Res D4"):
    r=m.Residente(id=_new_id(), instituicao_id=ilpi_id, nome=nome, data_nascimento=date(1940,5,1))
    db.add(r)
    await db.flush()
    return r
def _code(r):
    d=r.json().get("detail")
    return d.get("code") if isinstance(d, dict) else None

def _pront_url(res_id): return f"/api/residentes/{res_id}/prontuario"
# helpers to seed data via direct insert (faster)
async def _seed_avaliacao(db, ilpi_id, res_id, when=None):
    obj=m.Avaliacao(id=_new_id(), residente_id=res_id, ilpi_id=ilpi_id, tipo="Katz", instrumento="Katz", pontuacao=5, classificacao="Grau I", data=when or datetime.now(timezone.utc), profissional="Prof D4")
    db.add(obj)
    await db.flush()
    return obj
async def _seed_grau(db, ilpi_id, res_id, classificacao="Grau I", situacao="ativo", confirmado_em=None, confirmado_por=None):
    # confirmado_por must be valid user id in PG (FK). Fallback to any existing user in ilpi if not provided.
    if confirmado_por is None:
        # reuse any user from DB or generate valid one
        existing = (await db.execute(select(m.User.id).limit(1))).scalar_one_or_none()
        confirmado_por = existing or _new_id()
    obj=m.GrauDependencia(id=_new_id(), ilpi_id=ilpi_id, residente_id=res_id, classificacao=classificacao, origem="manual", justificativa="j", confirmado_por=confirmado_por, confirmado_em=confirmado_em or datetime.now(timezone.utc), situacao=situacao)
    db.add(obj)
    await db.flush()
    return obj
async def _seed_sinal(db, ilpi_id, res_id, when=None):
    obj=m.SinalVital(id=_new_id(), residente_id=res_id, ilpi_id=ilpi_id, temperatura=36.5, data=when or datetime.now(timezone.utc), profissional="Enf D4")
    db.add(obj)
    await db.flush()
    return obj
async def _seed_intercorrencia(db, ilpi_id, res_id, when=None):
    obj=m.Intercorrencia(id=_new_id(), residente_id=res_id, ilpi_id=ilpi_id, tipo="Queda", gravidade="leve", situacao="aberta", data=when or datetime.now(timezone.utc), responsavel="Enf D4")
    db.add(obj)
    await db.flush()
    return obj
async def _seed_medicacao_prescricao(db, ilpi_id, res_id, user_id, situacao="ativa", now=None):
    now=now or datetime.now(timezone.utc)
    med=m.Medicamento(id=_new_id(), ilpi_id=ilpi_id, autor_id=user_id, nome="Dipirona", situacao="ativo")
    db.add(med)
    await db.flush()
    presc=m.Prescricao(id=_new_id(), residente_id=res_id, ilpi_id=ilpi_id, medicamento_id=med.id, prescritor="Dr X", dose="1", via="oral", inicio=date.today(), situacao=situacao, autor_id=user_id, ativado_em=now if situacao!="rascunho" else None, ativado_por=user_id if situacao!="rascunho" else None, encerrado_em=now if situacao=="encerrada" else None, suspenso_em=now if situacao=="suspensa" else None, substituido_em=now if situacao=="substituida" else None, created_at=now)
    db.add(presc)
    await db.flush()
    return med, presc
async def _seed_administracao(db, ilpi_id, res_id, presc_id, dose_id, user_id, when=None, estornado=False):
    when=when or datetime.now(timezone.utc)
    prog_id=_new_id()
    prog=m.ProgramacaoMedicacao(id=prog_id, ilpi_id=ilpi_id, residente_id=res_id, prescricao_id=presc_id, horarios=["08:00"], timezone="America/Sao_Paulo", vigencia_inicio=when, situacao="ativa", autor_id=user_id)
    db.add(prog)
    await db.flush()
    dose=m.DosePrevista(id=dose_id, ilpi_id=ilpi_id, residente_id=res_id, prescricao_id=presc_id, programacao_id=prog_id, previsto_em=when, situacao="prevista")
    db.add(dose)
    await db.flush()
    adm=m.Administracao(id=_new_id(), ilpi_id=ilpi_id, residente_id=res_id, prescricao_id=presc_id, dose_prevista_id=dose.id, resultado="administrada", ocorrido_em=when, registrado_em=when, executor_id=user_id, quantidade_realizada=1, estornado_em=when if estornado else None, estornado_por=user_id if estornado else None, motivo_estorno="erro" if estornado else None)
    db.add(adm)
    await db.flush()
    return adm
async def _seed_pais(db, ilpi_id, res_id, user_id, situacao="vigente", versao=1):
    now=datetime.now(timezone.utc)
    plano=m.PlanoCuidados(id=_new_id(), residente_id=res_id, ilpi_id=ilpi_id, versao=versao, objetivos="obj", data_inicial=date(2026,1,1), situacao=situacao, autor_id=user_id, aprovado_em=now if situacao in ("aprovado","vigente","encerrado","substituido") else None, encerrado_em=now if situacao=="encerrado" else None, created_at=now)
    db.add(plano)
    await db.flush()
    return plano
async def _seed_execucao(db, ilpi_id, res_id, user_id, when=None, estornado=False):
    when=when or datetime.now(timezone.utc)
    # cria PAIS aprovado (evita colisao unica vigente) + intervencao para FK valida em PG
    pais = await _seed_pais(db, ilpi_id, res_id, user_id, situacao="aprovado")
    interv_id = _new_id()
    interv = m.PaisIntervencao(id=interv_id, ilpi_id=ilpi_id, plano_id=pais.id, descricao="Interv exec dummy", situacao="ativa")
    db.add(interv)
    await db.flush()
    prog=m.ProgramacaoCuidado(id=_new_id(), ilpi_id=ilpi_id, residente_id=res_id, plano_id=pais.id, intervencao_id=interv_id, autor_id=user_id, horarios=["08:00"], timezone="America/Sao_Paulo", vigencia_inicio=when, situacao="ativa")
    db.add(prog)
    await db.flush()
    ocorr=m.OcorrenciaCuidado(id=_new_id(), ilpi_id=ilpi_id, residente_id=res_id, plano_id=pais.id, intervencao_id=interv_id, programacao_id=prog.id, previsto_em=when, situacao="prevista")
    db.add(ocorr)
    await db.flush()
    execu=m.ExecucaoCuidado(id=_new_id(), ilpi_id=ilpi_id, residente_id=res_id, programacao_id=prog.id, ocorrencia_id=ocorr.id, resultado="executada", ocorrido_em=when, registrado_em=when, executor_id=user_id, estornado_em=when if estornado else None, estornado_por=user_id if estornado else None, motivo_estorno="erro" if estornado else None)
    db.add(execu)
    await db.flush()
    return execu
async def _seed_ocupacao(db, ilpi_id, res_id, user_id, when=None, tipo="alocacao"):
    when=when or datetime.now(timezone.utc)
    leito=m.QuartoLeito(id=_new_id(), instituicao_id=ilpi_id, quarto="Q1", leito="L1", capacidade=1, situacao="livre")
    db.add(leito)
    await db.flush()
    hist=m.OcupacaoHistorico(id=_new_id(), instituicao_id=ilpi_id, residente_id=res_id, quarto_leito_id=leito.id, data_entrada=when, tipo_movimentacao=tipo, usuario_id=user_id, created_at=when)
    db.add(hist)
    await db.flush()
    return hist
async def _seed_ausencia(db, ilpi_id, res_id, user_id, when=None, tipo="hospitalizacao", encerrada=False):
    when=when or datetime.now(timezone.utc)
    au=m.Ausencia(id=_new_id(), instituicao_id=ilpi_id, residente_id=res_id, tipo=tipo, data_inicio=when, data_fim=when+timedelta(days=1) if encerrada else None, motivo="motivo", usuario_id=user_id, created_at=when)
    db.add(au)
    await db.flush()
    return au

def test_auth_401(prontuario_db):
    async def op(client, db):
        ilpi=_new_inst()
        user=await _create_ilpi_user(db, ilpi, permissions=ALL_CLINICAL)
        res=await _create_residente(db, ilpi.id)
        await db.commit()
        r=await client.get(_pront_url(res.id))
        assert r.status_code==401
        # 403 sem permissao
        none=await _create_ilpi_user(db, ilpi, permissions=set(), profile_key="none")
        await db.commit()
        r=await client.get(_pront_url(res.id), headers=_headers(none, ilpi_id=ilpi.id))
        assert r.status_code==403 and _code(r)==PERMISSION_DENIED
    asyncio.run(_with_client(prontuario_db, op))

def test_platform_bloqueado(prontuario_db):
    async def op(client, db):
        ilpi=_new_inst()
        db.add(ilpi)
        await db.flush()
        plat=await _create_platform_user(db)
        res=await _create_residente(db, ilpi.id)
        await db.commit()
        r=await client.get(_pront_url(res.id), headers=_headers(plat, scope="global"))
        assert r.status_code==403
    asyncio.run(_with_client(prontuario_db, op))

def test_tenant_cross_404(prontuario_db):
    async def op(client, db):
        a=_new_inst("A")
        b=_new_inst("B")
        ua=await _create_ilpi_user(db, a, permissions=ALL_CLINICAL, profile_key="pa")
        ub=await _create_ilpi_user(db, b, permissions=ALL_CLINICAL, profile_key="pb")
        ra=await _create_residente(db, a.id)
        rb=await _create_residente(db, b.id)
        await db.commit()
        # cross-tenant 404
        r=await client.get(_pront_url(rb.id), headers=_headers(ua, ilpi_id=a.id))
        assert r.status_code==404 and _code(r)==RESOURCE_NOT_FOUND
        # own tenant ok
        r=await client.get(_pront_url(ra.id), headers=_headers(ua, ilpi_id=a.id))
        assert r.status_code==200
        # enumeration: listar prontuario de outro residente via filtro deve 404, nao leak
        r=await client.get(_pront_url(_new_id()), headers=_headers(ua, ilpi_id=a.id))
        assert r.status_code==404
    asyncio.run(_with_client(prontuario_db, op))

def test_rbac_por_origem(prontuario_db):
    async def op(client, db):
        ilpi=_new_inst()
        full=await _create_ilpi_user(db, ilpi, permissions=ALL_CLINICAL, profile_key="full")
        only_av=await _create_ilpi_user(db, ilpi, permissions={"avaliacoes:ler"}, profile_key="only_av")
        res=await _create_residente(db, ilpi.id)
        await _seed_avaliacao(db, ilpi.id, res.id)
        await _seed_sinal(db, ilpi.id, res.id)
        await db.commit()
        h_full=_headers(full, ilpi_id=ilpi.id)
        h_av=_headers(only_av, ilpi_id=ilpi.id)
        r=await client.get(_pront_url(res.id), headers=h_av)
        assert r.status_code==200
        origens={e["origem"] for e in r.json()["items"]}
        assert origens=={"avaliacao"}, origens
        # filtro origem sem permissao -> 403
        r=await client.get(_pront_url(res.id)+"?origem=sinal_vital", headers=h_av)
        assert r.status_code==403
        # full vê ambos
        r=await client.get(_pront_url(res.id), headers=h_full)
        assert {e["origem"] for e in r.json()["items"]} >= {"avaliacao","sinal_vital"}
        # sem nenhuma permissao aplicavel -> 403
        none=await _create_ilpi_user(db, ilpi, permissions={"residentes:ler"}, profile_key="none2")
        await db.commit()
        r=await client.get(_pront_url(res.id), headers=_headers(none, ilpi_id=ilpi.id))
        assert r.status_code==403
    asyncio.run(_with_client(prontuario_db, op))

def test_fontes_incluidas(prontuario_db):
    async def op(client, db):
        ilpi=_new_inst()
        user=await _create_ilpi_user(db, ilpi, permissions=ALL_CLINICAL)
        res=await _create_residente(db, ilpi.id)
        now=datetime.now(timezone.utc)
        await _seed_avaliacao(db, ilpi.id, res.id, when=now)
        await _seed_grau(db, ilpi.id, res.id, confirmado_em=now-timedelta(hours=1), confirmado_por=user.id)
        await _seed_sinal(db, ilpi.id, res.id, when=now-timedelta(hours=2))
        await _seed_intercorrencia(db, ilpi.id, res.id, when=now-timedelta(hours=3))
        await _seed_medicacao_prescricao(db, ilpi.id, res.id, user.id, situacao="ativa", now=now-timedelta(hours=4))
        # administracao: need prescricao+dose
        med, presc = await _seed_medicacao_prescricao(db, ilpi.id, res.id, user.id, situacao="ativa", now=now-timedelta(hours=5))
        # create dose+admin via helper
        dose_id=_new_id()
        await _seed_administracao(db, ilpi.id, res.id, presc.id, dose_id, user.id, when=now-timedelta(hours=6))
        await _seed_pais(db, ilpi.id, res.id, user.id, situacao="vigente")
        await _seed_execucao(db, ilpi.id, res.id, user.id, when=now-timedelta(hours=7))
        await _seed_ocupacao(db, ilpi.id, res.id, user.id, when=now-timedelta(hours=8))
        await _seed_ausencia(db, ilpi.id, res.id, user.id, when=now-timedelta(hours=9))
        await db.commit()
        r=await client.get(_pront_url(res.id), headers=_headers(user, ilpi_id=ilpi.id))
        assert r.status_code==200, r.text
        got={e["origem"] for e in r.json()["items"]}
        for expected in ["avaliacao","grau_dependencia","sinal_vital","intercorrencia","prescricao","administracao","pais","execucao_cuidado","ocupacao","ausencia"]:
            assert expected in got, f"faltou {expected} em {got}"
    asyncio.run(_with_client(prontuario_db, op))

def test_fontes_excluidas(prontuario_db):
    async def op(client, db):
        ilpi=_new_inst()
        user=await _create_ilpi_user(db, ilpi, permissions=ALL_CLINICAL)
        res=await _create_residente(db, ilpi.id)
        # rascunho prescricao nao entra
        await _seed_medicacao_prescricao(db, ilpi.id, res.id, user.id, situacao="rascunho")
        # pais rascunho nao entra
        await _seed_pais(db, ilpi.id, res.id, user.id, situacao="rascunho")
        # dose prevista, programacao, ocorrencia prevista nao entram - ensure not counted
        # cria cadeia valida para dose prevista (deve continuar excluida do prontuario)
        _med_tmp, _presc_tmp = await _seed_medicacao_prescricao(db, ilpi.id, res.id, user.id, situacao="ativa")
        # programacao valida para dose
        prog=m.ProgramacaoMedicacao(id=_new_id(), ilpi_id=ilpi.id, residente_id=res.id, prescricao_id=_presc_tmp.id, horarios=["08:00"], timezone="America/Sao_Paulo", vigencia_inicio=datetime.now(timezone.utc), situacao="ativa", autor_id=user.id)
        db.add(prog)
        await db.flush()
        dose=m.DosePrevista(id=_new_id(), ilpi_id=ilpi.id, residente_id=res.id, prescricao_id=_presc_tmp.id, programacao_id=prog.id, previsto_em=datetime.now(timezone.utc), situacao="prevista")
        db.add(dose)
        # ocorrencia prevista - precisa plano vigente valido
        _pais_tmp = await _seed_pais(db, ilpi.id, res.id, user.id, situacao="vigente")
        # cria necessidade/intervencao para prog valida
        prog2=m.ProgramacaoCuidado(id=_new_id(), ilpi_id=ilpi.id, residente_id=res.id, plano_id=_pais_tmp.id, intervencao_id=_new_id(), autor_id=user.id, horarios=["08:00"], timezone="America/Sao_Paulo", vigencia_inicio=datetime.now(timezone.utc), situacao="ativa")
        # para PG, intervencao precisa existir; cria dummy diretamente
        interv=m.PaisIntervencao(id=prog2.intervencao_id, ilpi_id=ilpi.id, plano_id=_pais_tmp.id, descricao="Interv dummy", situacao="ativa")
        db.add(interv)
        await db.flush()
        db.add(prog2)
        await db.flush()
        ocorr=m.OcorrenciaCuidado(id=_new_id(), ilpi_id=ilpi.id, residente_id=res.id, plano_id=_pais_tmp.id, intervencao_id=prog2.intervencao_id, programacao_id=prog2.id, previsto_em=datetime.now(timezone.utc), situacao="prevista")
        db.add(ocorr)
        # tarefa legado
        tar=m.Tarefa(id=_new_id(), residente_id=res.id, ilpi_id=ilpi.id, descricao="tarefa legado", situacao="Pendente")
        db.add(tar)
        # documento
        doc=m.Documento(id=_new_id(), residente_id=res.id, instituicao_id=ilpi.id, tipo="RG", situacao="pendente")
        db.add(doc)
        # auditoria
        aud=m.Auditoria(id=_new_id(), ilpi_id=ilpi.id, usuario_id=user.id, acao="test.auditoria", entidade="residentes", registro_id=res.id)
        db.add(aud)
        await db.commit()
        r=await client.get(_pront_url(res.id), headers=_headers(user, ilpi_id=ilpi.id))
        assert r.status_code==200
        origens={e["origem"] for e in r.json()["items"]}
        assert "prescricao" not in origens or all(e["situacao"]!="rascunho" for e in r.json()["items"] if e["origem"]=="prescricao")
        assert "pais" not in origens or all(e["situacao"] not in ("rascunho","em_elaboracao","em_revisao") for e in r.json()["items"] if e["origem"]=="pais")
        # dose prevista, programacao, ocorrencia, tarefa, documento, auditoria nao tem origem propria, devem estar ausentes
        for forbidden in ["dose_prevista","programacao","ocorrencia","tarefa","documento","auditoria"]:
            assert forbidden not in origens, f"{forbidden} nao deveria aparecer"
        # check no raw inclusion via categoria errada? total items should be 0-2 (maybe 0 if only excluded)
        # ensure at least rascunho not counted
        assert not any(e["origem"]=="prescricao" and e["situacao"]=="rascunho" for e in r.json()["items"])
        assert not any(e["origem"]=="pais" and e["situacao"]=="rascunho" for e in r.json()["items"])
    asyncio.run(_with_client(prontuario_db, op))

def test_estornos_visiveis(prontuario_db):
    async def op(client, db):
        ilpi=_new_inst()
        user=await _create_ilpi_user(db, ilpi, permissions=ALL_CLINICAL)
        res=await _create_residente(db, ilpi.id)
        # grau substituido
        g1=await _seed_grau(db, ilpi.id, res.id, classificacao="Grau I", situacao="substituido", confirmado_por=user.id)
        g2=await _seed_grau(db, ilpi.id, res.id, classificacao="Grau II", situacao="ativo", confirmado_por=user.id)
        g1.superseded_by=g2.id
        await db.flush()
        # administracao estornada
        med, presc = await _seed_medicacao_prescricao(db, ilpi.id, res.id, user.id, situacao="ativa")
        dose_id=_new_id()
        adm=await _seed_administracao(db, ilpi.id, res.id, presc.id, dose_id, user.id, estornado=True)
        # execucao estornada
        await _seed_execucao(db, ilpi.id, res.id, user.id, estornado=True)
        await db.commit()
        r=await client.get(_pront_url(res.id), headers=_headers(user, ilpi_id=ilpi.id))
        items=r.json()["items"]
        # grau history includes both
        graus=[e for e in items if e["origem"]=="grau_dependencia"]
        assert any(g["estornado"] or g["substituido"] for g in graus) or len(graus)>=2
        admins=[e for e in items if e["origem"]=="administracao"]
        assert any(a["estornado"] for a in admins)
        execs=[e for e in items if e["origem"]=="execucao_cuidado"]
        assert any(e["estornado"] for e in execs)
    asyncio.run(_with_client(prontuario_db, op))

def test_ordenacao_e_timestamps(prontuario_db):
    async def op(client, db):
        ilpi=_new_inst()
        user=await _create_ilpi_user(db, ilpi, permissions=ALL_CLINICAL)
        res=await _create_residente(db, ilpi.id)
        t1=datetime(2026,1,1,10,0, tzinfo=timezone.utc)
        t2=datetime(2026,1,2,10,0, tzinfo=timezone.utc)
        t3=datetime(2026,1,3,10,0, tzinfo=timezone.utc)
        await _seed_sinal(db, ilpi.id, res.id, when=t1)
        await _seed_sinal(db, ilpi.id, res.id, when=t3)
        await _seed_sinal(db, ilpi.id, res.id, when=t2)
        await db.commit()
        r=await client.get(_pront_url(res.id), headers=_headers(user, ilpi_id=ilpi.id))
        times=[e["ocorrido_em"] for e in r.json()["items"]]
        assert times==sorted(times, reverse=True), times
        # registrado_em exists and not classified as delay
        for e in r.json()["items"]:
            assert "ocorrido_em" in e and "registrado_em" in e
            assert e["ocorrido_em"] is not None
    asyncio.run(_with_client(prontuario_db, op))

def test_paginacao_cursor(prontuario_db):
    async def op(client, db):
        ilpi=_new_inst()
        user=await _create_ilpi_user(db, ilpi, permissions=ALL_CLINICAL)
        res=await _create_residente(db, ilpi.id)
        base=datetime(2026,1,1,10,0, tzinfo=timezone.utc)
        for i in range(5):
            await _seed_sinal(db, ilpi.id, res.id, when=base+timedelta(hours=i))
        await db.commit()
        h=_headers(user, ilpi_id=ilpi.id)
        r1=await client.get(_pront_url(res.id)+"?limit=2", headers=h)
        assert r1.status_code==200
        j1=r1.json()
        assert len(j1["items"])==2 and j1["has_more"] is True and j1["next_cursor"] is not None
        r2=await client.get(_pront_url(res.id)+f"?limit=2&cursor={j1['next_cursor']}", headers=h)
        j2=r2.json()
        assert len(j2["items"])==2
        r3=await client.get(_pront_url(res.id)+f"?limit=2&cursor={j2['next_cursor']}", headers=h)
        j3=r3.json()
        assert len(j3["items"])==1 and j3["has_more"] is False
        # sem duplicata across pages
        ids=set(e["registro_id"] for e in j1["items"]) | set(e["registro_id"] for e in j2["items"]) | set(e["registro_id"] for e in j3["items"])
        assert len(ids)==5
        # cursor invalido 400
        r=await client.get(_pront_url(res.id)+"?cursor=invalid", headers=h)
        assert r.status_code==400
        # limit abusivo 422
        r=await client.get(_pront_url(res.id)+"?limit=999", headers=h)
        assert r.status_code==422
    asyncio.run(_with_client(prontuario_db, op))

def test_filtros(prontuario_db):
    async def op(client, db):
        ilpi=_new_inst()
        user=await _create_ilpi_user(db, ilpi, permissions=ALL_CLINICAL)
        res=await _create_residente(db, ilpi.id)
        t=datetime(2026,1,10,10,0, tzinfo=timezone.utc)
        avaliacao=await _seed_avaliacao(db, ilpi.id, res.id, when=t)
        await _seed_sinal(db, ilpi.id, res.id, when=t+timedelta(days=1))
        ocupacao=await _seed_ocupacao(db, ilpi.id, res.id, user.id, when=t)
        await db.commit()
        h=_headers(user, ilpi_id=ilpi.id)
        # origem filtro
        r=await client.get(_pront_url(res.id)+"?origem=avaliacao", headers=h)
        assert all(e["origem"]=="avaliacao" for e in r.json()["items"])
        # categoria
        r=await client.get(_pront_url(res.id)+"?categoria=administrativo", headers=h)
        assert all(e["categoria"]=="administrativo" for e in r.json()["items"])
        # desde/ate
        r=await client.get(_pront_url(res.id), params={"desde": t.isoformat(), "ate": t.isoformat()}, headers=h)
        assert r.status_code==200, r.text
        assert {(e["origem"], e["registro_id"]) for e in r.json()["items"]} == {
            ("avaliacao", avaliacao.id), ("ocupacao", ocupacao.id),
        }
        assert all(datetime.fromisoformat(e["ocorrido_em"].replace("Z", "+00:00")) == t for e in r.json()["items"])
        # incluir_movimentacoes false
        r=await client.get(_pront_url(res.id)+"?incluir_movimentacoes=false", headers=h)
        assert all(e["origem"] not in ("ocupacao","ausencia") for e in r.json()["items"])
        # situacao
        await _seed_intercorrencia(db, ilpi.id, res.id, when=t)
        await db.commit()
        r=await client.get(_pront_url(res.id)+"?origem=intercorrencia&situacao=aberta", headers=h)
        assert all(e["situacao"]=="aberta" for e in r.json()["items"])
    asyncio.run(_with_client(prontuario_db, op))

def test_sem_insert_update_delete(prontuario_db):
    async def op(client, db):
        ilpi=_new_inst()
        user=await _create_ilpi_user(db, ilpi, permissions=ALL_CLINICAL)
        res=await _create_residente(db, ilpi.id)
        await db.commit()
        h=_headers(user, ilpi_id=ilpi.id)
        url=_pront_url(res.id)
        for method in ("post","put","patch","delete"):
            r=await client.request(method, url, headers=h, json={})
            assert r.status_code==405, f"{method} should be 405, got {r.status_code}"
        # get with hostile tenant in query should be ignored (tenant from context)
        r=await client.get(url+"?ilpi_id=evil", headers=h)
        assert r.status_code==200
    asyncio.run(_with_client(prontuario_db, op))

def test_historico_longitudinal_sem_janela(prontuario_db):
    async def op(client, db):
        ilpi=_new_inst()
        user=await _create_ilpi_user(db, ilpi, permissions=ALL_CLINICAL)
        res=await _create_residente(db, ilpi.id)
        old=datetime(2020,1,1,10,0, tzinfo=timezone.utc)
        await _seed_sinal(db, ilpi.id, res.id, when=old)
        await _seed_sinal(db, ilpi.id, res.id, when=datetime.now(timezone.utc))
        await db.commit()
        r=await client.get(_pront_url(res.id), headers=_headers(user, ilpi_id=ilpi.id))
        # without desde/ate, both appear via cursor
        ids={e["ocorrido_em"] for e in r.json()["items"]}
        assert len(ids)>=2
        # ensure old not hidden
        assert any("2020" in e["ocorrido_em"] for e in r.json()["items"])
    asyncio.run(_with_client(prontuario_db, op))


def _event_key(item):
    return (
        datetime.fromisoformat(item["ocorrido_em"].replace("Z", "+00:00")),
        datetime.fromisoformat(item["registrado_em"].replace("Z", "+00:00")),
        item["origem"], item["registro_id"], item["tipo"],
    )


async def _assert_pages(client, res_id, headers, expected, limit=1):
    expected = sorted(expected, reverse=True)
    received = []
    params = {"limit": limit}
    # A bounded walk fails on repeated cursors instead of hanging the suite.
    for offset in range(0, len(expected), limit):
        response = await client.get(_pront_url(res_id), headers=headers, params=params)
        assert response.status_code == 200, response.text
        page = response.json()
        keys = [_event_key(item) for item in page["items"]]
        assert keys == expected[offset:offset + limit]
        received.extend(keys)
        more = offset + limit < len(expected)
        assert page["has_more"] is more
        if more:
            assert page["next_cursor"]
            assert page["next_cursor"] != params.get("cursor")
            params["cursor"] = page["next_cursor"]
        else:
            assert page["next_cursor"] is None
    assert received == expected
    assert len(received) == len(set(received))


def test_prescricao_progressao_preserva_transicoes(prontuario_db):
    async def op(client, db):
        ilpi = _new_inst()
        user = await _create_ilpi_user(db, ilpi, permissions=ALL_CLINICAL)
        res = await _create_residente(db, ilpi.id)
        base = datetime(2026, 1, 1, 10, tzinfo=timezone.utc)
        _, presc = await _seed_medicacao_prescricao(db, ilpi.id, res.id, user.id, situacao="rascunho", now=base)
        expected = []
        transitions = (
            ("ativado_em", "ativada", "ativa"),
            ("suspenso_em", "suspensa", "suspensa"),
            ("substituido_em", "substituida", "substituida"),
            ("encerrado_em", "encerrada", "encerrada"),
        )
        for index, (field, tipo, situacao) in enumerate(transitions, 1):
            stamp = base + timedelta(days=index)
            setattr(presc, field, stamp)
            presc.situacao = situacao
            await db.commit()
            expected.insert(0, (tipo, situacao, stamp))
            response = await client.get(_pront_url(res.id), headers=_headers(user, ilpi_id=ilpi.id), params={"origem": "prescricao"})
            assert response.status_code == 200, response.text
            items = response.json()["items"]
            assert [(item["tipo"], item["situacao"], _event_key(item)[0]) for item in items] == expected
            assert all(item["registro_id"] == presc.id and _event_key(item)[1] == _event_key(item)[0] for item in items)
        # Filtering is by historical transition, not the row's current status.
        response = await client.get(_pront_url(res.id), headers=_headers(user, ilpi_id=ilpi.id), params={"origem": "prescricao", "situacao": "ativa"})
        assert response.status_code == 200, response.text
        assert [item["tipo"] for item in response.json()["items"]] == ["ativada"]
    asyncio.run(_with_client(prontuario_db, op))


def test_prescricao_timestamp_efetivo_nao_created_at(prontuario_db):
    async def op(client, db):
        ilpi = _new_inst()
        user = await _create_ilpi_user(db, ilpi, permissions=ALL_CLINICAL)
        res = await _create_residente(db, ilpi.id)
        created = datetime(2020, 1, 1, tzinfo=timezone.utc)
        stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
        _, presc = await _seed_medicacao_prescricao(db, ilpi.id, res.id, user.id, situacao="encerrada", now=created)
        presc.ativado_em = None
        presc.encerrado_em = stamp
        await db.commit()
        response = await client.get(_pront_url(res.id), headers=_headers(user, ilpi_id=ilpi.id), params={"origem": "prescricao"})
        assert response.status_code == 200, response.text
        # Rx has no separate technical timestamp: both stamps use the transition.
        assert [_event_key(item) for item in response.json()["items"]] == [(stamp, stamp, "prescricao", presc.id, "encerrada")]
    asyncio.run(_with_client(prontuario_db, op))


def test_prescricao_sem_timestamp_nao_emite_evento(prontuario_db):
    async def op(client, db):
        ilpi = _new_inst()
        user = await _create_ilpi_user(db, ilpi, permissions=ALL_CLINICAL)
        res = await _create_residente(db, ilpi.id)
        for status in ("ativa", "suspensa", "substituida", "encerrada"):
            _, presc = await _seed_medicacao_prescricao(db, ilpi.id, res.id, user.id, situacao=status)
            presc.ativado_em = presc.suspenso_em = presc.substituido_em = presc.encerrado_em = None
        await db.commit()
        response = await client.get(_pront_url(res.id), headers=_headers(user, ilpi_id=ilpi.id))
        assert response.status_code == 200, response.text
        assert response.json() == {"items": [], "has_more": False, "next_cursor": None}
    asyncio.run(_with_client(prontuario_db, op))


def test_prescricao_rascunho_excluido_com_timestamps_hostis(prontuario_db):
    async def op(client, db):
        ilpi = _new_inst()
        user = await _create_ilpi_user(db, ilpi, permissions=ALL_CLINICAL)
        res = await _create_residente(db, ilpi.id)
        _, presc = await _seed_medicacao_prescricao(db, ilpi.id, res.id, user.id, situacao="rascunho")
        presc.ativado_em = presc.suspenso_em = presc.substituido_em = presc.encerrado_em = datetime(2026, 1, 1, tzinfo=timezone.utc)
        await db.commit()
        response = await client.get(_pront_url(res.id), headers=_headers(user, ilpi_id=ilpi.id))
        assert response.status_code == 200, response.text
        assert response.json() == {"items": [], "has_more": False, "next_cursor": None}
    asyncio.run(_with_client(prontuario_db, op))


def test_cursor_colisao_timestamp_uuid_entre_origens(prontuario_db):
    async def op(client, db):
        ilpi = _new_inst()
        user = await _create_ilpi_user(db, ilpi, permissions=ALL_CLINICAL)
        res = await _create_residente(db, ilpi.id)
        stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
        avaliacao = await _seed_avaliacao(db, ilpi.id, res.id, when=stamp)
        sinal = await _seed_sinal(db, ilpi.id, res.id, when=stamp)
        sinal.id = avaliacao.id
        await db.commit()
        expected = [(stamp, stamp, origin, avaliacao.id, origin) for origin in ("avaliacao", "sinal_vital")]
        await _assert_pages(client, res.id, _headers(user, ilpi_id=ilpi.id), expected)
    asyncio.run(_with_client(prontuario_db, op))


def test_cursor_colisao_timestamp_uuid_entre_transicoes_rx(prontuario_db):
    async def op(client, db):
        ilpi = _new_inst()
        user = await _create_ilpi_user(db, ilpi, permissions=ALL_CLINICAL)
        res = await _create_residente(db, ilpi.id)
        stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
        _, presc = await _seed_medicacao_prescricao(db, ilpi.id, res.id, user.id, situacao="encerrada", now=stamp)
        presc.suspenso_em = presc.substituido_em = stamp
        await db.commit()
        expected = [(stamp, stamp, "prescricao", presc.id, tipo) for tipo in ("ativada", "suspensa", "substituida", "encerrada")]
        await _assert_pages(client, res.id, _headers(user, ilpi_id=ilpi.id), expected)
    asyncio.run(_with_client(prontuario_db, op))


def test_paginacao_uniao_completa_chaves_unicas(prontuario_db):
    async def op(client, db):
        ilpi = _new_inst()
        user = await _create_ilpi_user(db, ilpi, permissions=ALL_CLINICAL)
        res = await _create_residente(db, ilpi.id)
        stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
        avaliacao = await _seed_avaliacao(db, ilpi.id, res.id, when=stamp)
        grau = await _seed_grau(db, ilpi.id, res.id, confirmado_em=stamp, confirmado_por=user.id)
        grau.created_at = stamp
        sinal = await _seed_sinal(db, ilpi.id, res.id, when=stamp)
        intercorrencia = await _seed_intercorrencia(db, ilpi.id, res.id, when=stamp)
        _, presc = await _seed_medicacao_prescricao(db, ilpi.id, res.id, user.id, situacao="encerrada", now=stamp)
        presc.suspenso_em = presc.substituido_em = stamp
        adm = await _seed_administracao(db, ilpi.id, res.id, presc.id, _new_id(), user.id, when=stamp)
        execucao = await _seed_execucao(db, ilpi.id, res.id, user.id, when=stamp)
        plano = (await db.execute(select(m.PlanoCuidados).where(m.PlanoCuidados.residente_id == res.id))).scalar_one()
        plano.aprovado_em = plano.created_at = stamp
        ocupacao = await _seed_ocupacao(db, ilpi.id, res.id, user.id, when=stamp)
        ausencia = await _seed_ausencia(db, ilpi.id, res.id, user.id, when=stamp)
        # Include the registrado_em and registro_id tie-breakers, not just origins.
        adm.registrado_em = stamp + timedelta(hours=1)
        extra_sinal = await _seed_sinal(db, ilpi.id, res.id, when=stamp)
        old_sinal = await _seed_sinal(db, ilpi.id, res.id, when=stamp - timedelta(days=1))
        await db.commit()
        expected = [(stamp, stamp, origin, row.id, origin) for origin, row in (
            ("avaliacao", avaliacao), ("grau_dependencia", grau), ("sinal_vital", sinal),
            ("sinal_vital", extra_sinal), ("intercorrencia", intercorrencia), ("pais", plano),
            ("execucao_cuidado", execucao), ("ocupacao", ocupacao), ("ausencia", ausencia),
        )]
        expected.extend((stamp, stamp, "prescricao", presc.id, tipo) for tipo in ("ativada", "suspensa", "substituida", "encerrada"))
        expected.append((stamp, adm.registrado_em, "administracao", adm.id, "administracao"))
        expected.append((old_sinal.data, old_sinal.data, "sinal_vital", old_sinal.id, "sinal_vital"))
        await _assert_pages(client, res.id, _headers(user, ilpi_id=ilpi.id), expected, limit=2)
    asyncio.run(_with_client(prontuario_db, op))


def test_segunda_pagina_aplica_keyset_e_limit_no_sql(prontuario_db):
    async def op(client, db):
        ilpi = _new_inst()
        user = await _create_ilpi_user(db, ilpi, permissions=ALL_CLINICAL)
        res = await _create_residente(db, ilpi.id)
        stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for index in range(5):
            await _seed_sinal(db, ilpi.id, res.id, when=stamp + timedelta(hours=index))
        await db.commit()
        headers = _headers(user, ilpi_id=ilpi.id)
        response = await client.get(_pront_url(res.id), headers=headers, params={"limit": 2})
        assert response.status_code == 200, response.text
        assert response.json()["has_more"] is True
        queries = []
        engine = db.bind.sync_engine

        def capture(connection, cursor, statement, parameters, context, executemany):
            if context.compiled is not None and statement.lstrip().upper().startswith("SELECT"):
                queries.append(" ".join(str(context.compiled.statement.compile(
                    dialect=connection.dialect, compile_kwargs={"literal_binds": True},
                )).lower().split()))

        event.listen(engine, "before_cursor_execute", capture)
        try:
            response = await client.get(_pront_url(res.id), headers=headers, params={"limit": 2, "cursor": response.json()["next_cursor"]})
        finally:
            event.remove(engine, "before_cursor_execute", capture)
        assert response.status_code == 200, response.text
        assert len(response.json()["items"]) == 2
        tables = {"avaliacoes", "graus_dependencia", "sinais_vitais", "intercorrencias", "prescricoes", "administracoes", "planos_cuidados", "execucoes_cuidado", "ocupacao_historico", "ausencias"}
        seen = set()
        rx_queries = []
        for sql in queries:
            match = re.search(r"\bfrom (\w+)\b", sql)
            if match is None or match.group(1) not in tables:
                continue
            table = match.group(1)
            seen.add(table)
            assert re.search(r"\blimit 3(?: offset 0)?$", sql), sql
            assert " order by " in sql, sql
            assert " where " in sql, sql
            where = sql.split(" where ", 1)[1].split(" order by ", 1)[0]
            assert " < " in where, sql
            assert "2026-01-01" in where, sql
            if table == "prescricoes":
                rx_queries.append(sql)
        assert seen == tables, queries
        assert len(rx_queries) == 4, rx_queries
        for field in ("ativado_em", "suspenso_em", "substituido_em", "encerrado_em"):
            assert any(field in sql.split(" where ", 1)[1].split(" order by ", 1)[0] for sql in rx_queries)
    asyncio.run(_with_client(prontuario_db, op))


def test_cursor_tipos_maliciosos_retorna_400(prontuario_db):
    async def op(client, db):
        ilpi = _new_inst()
        user = await _create_ilpi_user(db, ilpi, permissions=ALL_CLINICAL)
        res = await _create_residente(db, ilpi.id)
        await _seed_sinal(db, ilpi.id, res.id)
        await _seed_sinal(db, ilpi.id, res.id)
        await db.commit()
        headers = _headers(user, ilpi_id=ilpi.id)
        response = await client.get(_pront_url(res.id), headers=headers, params={"limit": 1})
        assert response.status_code == 200, response.text
        cursor = response.json()["next_cursor"]
        valid = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        assert set(valid) >= {"ocorrido_em", "registrado_em", "origem", "registro_id", "tipo"}
        payloads = [[], None, 1, "cursor"]
        for field in ("ocorrido_em", "registrado_em", "origem", "registro_id", "tipo"):
            for invalid in (None, [], {}, 1, True):
                payloads.append({**valid, field: invalid})
        for payload in payloads:
            hostile = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
            response = await client.get(_pront_url(res.id), headers=headers, params={"cursor": hostile})
            assert response.status_code == 400, (payload, response.text)
            assert _code(response) == "CURSOR_INVALIDO"
    asyncio.run(_with_client(prontuario_db, op))


@pytest.mark.parametrize("origin", ["administracao", "execucao_cuidado"])
def test_estorno_e_substituicao_flags_original_e_sucessor(prontuario_db, origin):
    async def op(client, db):
        ilpi = _new_inst()
        user = await _create_ilpi_user(db, ilpi, permissions=ALL_CLINICAL)
        res = await _create_residente(db, ilpi.id)
        stamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
        other_ilpi = _new_inst("Outra ILPI D4")
        db.add(other_ilpi)
        await db.flush()
        other_tenant_res = await _create_residente(db, other_ilpi.id)
        other_res = await _create_residente(db, ilpi.id)
        # Unrelated replacement chains must neither leak nor mark this original.
        for tenant_id, resident_id in ((other_ilpi.id, other_tenant_res.id), (ilpi.id, other_res.id), (ilpi.id, res.id)):
            if origin == "administracao":
                _, presc = await _seed_medicacao_prescricao(db, tenant_id, resident_id, user.id, now=stamp)
                original = await _seed_administracao(db, tenant_id, resident_id, presc.id, _new_id(), user.id, when=stamp, estornado=True)
                chain = {"prescricao_id": original.prescricao_id, "dose_prevista_id": original.dose_prevista_id, "quantidade_realizada": 1}
            else:
                original = await _seed_execucao(db, tenant_id, resident_id, user.id, when=stamp, estornado=True)
                chain = {"programacao_id": original.programacao_id, "ocorrencia_id": original.ocorrencia_id}
            if resident_id != res.id:
                db.add(type(original)(id=_new_id(), ilpi_id=tenant_id, residente_id=resident_id, executor_id=user.id, resultado=original.resultado, ocorrido_em=stamp, registrado_em=stamp, substitui_id=original.id, **chain))
                await db.flush()
        await db.commit()
        headers = _headers(user, ilpi_id=ilpi.id)
        response = await client.get(_pront_url(res.id), headers=headers, params={"origem": origin})
        assert response.status_code == 200, response.text
        item, = response.json()["items"]
        assert item["estornado"] is True and item["substituido"] is False
        assert item["substituido_por"] is None and item["substituto"] is False and item["substitui_id"] is None
        successor = type(original)(id=_new_id(), ilpi_id=ilpi.id, residente_id=res.id, executor_id=user.id, resultado=original.resultado, ocorrido_em=stamp, registrado_em=stamp + timedelta(hours=1), substitui_id=original.id, **chain)
        db.add(successor)
        await db.commit()
        # Reversing the successor must not erase the original's replacement link.
        for reversed_successor in (False, True):
            if reversed_successor:
                successor.estornado_em = stamp + timedelta(hours=2)
                successor.estornado_por = user.id
                successor.motivo_estorno = "correcao do substituto"
                await db.commit()
            response = await client.get(_pront_url(res.id), headers=headers, params={"origem": origin})
            assert response.status_code == 200, response.text
            items = {item["registro_id"]: item for item in response.json()["items"]}
            assert set(items) == {original.id, successor.id}
            first, second = items[original.id], items[successor.id]
            assert first["tipo"] == second["tipo"] == origin
            assert first["estornado"] is True and first["motivo_estorno"] == "erro"
            assert first["substituido"] is True and first["substituido_por"] == successor.id
            assert first["substituto"] is False and first["substitui_id"] is None
            assert second["estornado"] is reversed_successor
            assert second["motivo_estorno"] == ("correcao do substituto" if reversed_successor else None)
            assert second["substituto"] is True and second["substitui_id"] == original.id
            assert second["substituido"] is False and second["substituido_por"] is None
    asyncio.run(_with_client(prontuario_db, op))


def test_grau_dependencia_link_nulo(prontuario_db):
    async def op(client, db):
        ilpi = _new_inst()
        user = await _create_ilpi_user(db, ilpi, permissions=ALL_CLINICAL)
        res = await _create_residente(db, ilpi.id)
        grau = await _seed_grau(db, ilpi.id, res.id, confirmado_por=user.id)
        await db.commit()
        response = await client.get(_pront_url(res.id), headers=_headers(user, ilpi_id=ilpi.id), params={"origem": "grau_dependencia"})
        assert response.status_code == 200, response.text
        item, = response.json()["items"]
        assert item["registro_id"] == grau.id
        assert item["tipo"] == "grau_dependencia"
        assert item["link"] is None
        assert item["substituto"] is False and item["substitui_id"] is None
    asyncio.run(_with_client(prontuario_db, op))


@pytest.mark.parametrize("origin", ["administracao", "execucao_cuidado"])
def test_substituicao_original_marcado_quando_sucessor_em_pagina_diferente(prontuario_db, origin):
    """Gate 2: verifica que o original é marcado como substituído mesmo quando o
    sucessor está em uma página diferente do cursor (segunda query sem filtro keyset)."""
    async def op(client, db):
        ilpi = _new_inst()
        user = await _create_ilpi_user(db, ilpi, permissions=ALL_CLINICAL)
        res = await _create_residente(db, ilpi.id)

        # original = mais antigo (última página em ordem desc)
        # 4 padding = timestamps intermediários (páginas do meio)
        # successor = mais recente (primeira página em ordem desc)
        t_orig = datetime(2025, 1, 1, tzinfo=timezone.utc)
        t_succ = datetime(2027, 1, 1, tzinfo=timezone.utc)

        if origin == "administracao":
            # original estornado: FK composta exige mesmo prescricao_id/dose_prevista_id
            # no sucessor; partial unique index impede dois não-estornados na mesma dose.
            _, presc_orig = await _seed_medicacao_prescricao(db, ilpi.id, res.id, user.id, now=t_orig)
            original = await _seed_administracao(db, ilpi.id, res.id, presc_orig.id, _new_id(), user.id, when=t_orig, estornado=True)
            for i in range(4):
                t_pad = datetime(2026, 1, i + 1, tzinfo=timezone.utc)
                _, p = await _seed_medicacao_prescricao(db, ilpi.id, res.id, user.id, now=t_pad)
                await _seed_administracao(db, ilpi.id, res.id, p.id, _new_id(), user.id, when=t_pad)
            successor = m.Administracao(
                id=_new_id(), ilpi_id=ilpi.id, residente_id=res.id,
                prescricao_id=original.prescricao_id,
                dose_prevista_id=original.dose_prevista_id,
                resultado="administrada", ocorrido_em=t_succ, registrado_em=t_succ,
                executor_id=user.id, quantidade_realizada=1,
                substitui_id=original.id,
            )
            db.add(successor)
        else:
            # Mesma lógica: FK composta exige mesmo programacao_id/ocorrencia_id.
            original = await _seed_execucao(db, ilpi.id, res.id, user.id, when=t_orig, estornado=True)
            for i in range(4):
                t_pad = datetime(2026, 1, i + 1, tzinfo=timezone.utc)
                await _seed_execucao(db, ilpi.id, res.id, user.id, when=t_pad)
            successor = m.ExecucaoCuidado(
                id=_new_id(), ilpi_id=ilpi.id, residente_id=res.id,
                programacao_id=original.programacao_id,
                ocorrencia_id=original.ocorrencia_id,
                resultado="executada", ocorrido_em=t_succ, registrado_em=t_succ,
                executor_id=user.id,
                substitui_id=original.id,
            )
            db.add(successor)

        await db.commit()

        headers = _headers(user, ilpi_id=ilpi.id)
        params = {"origem": origin, "limit": 2}
        all_pages = []

        for _ in range(20):
            response = await client.get(_pront_url(res.id), headers=headers, params=params)
            assert response.status_code == 200, response.text
            page = response.json()
            all_pages.append(list(page["items"]))
            if not page["has_more"]:
                break
            params = {"origem": origin, "limit": 2, "cursor": page["next_cursor"]}

        all_items = {item["registro_id"]: item for page in all_pages for item in page}
        assert original.id in all_items, "original not found in any page"
        assert successor.id in all_items, "successor not found in any page"

        orig_page_idx = next(
            i for i, page in enumerate(all_pages)
            if any(item["registro_id"] == original.id for item in page)
        )
        succ_page_idx = next(
            i for i, page in enumerate(all_pages)
            if any(item["registro_id"] == successor.id for item in page)
        )
        assert orig_page_idx != succ_page_idx, (
            f"original (pág {orig_page_idx}) e sucessor (pág {succ_page_idx}) "
            "devem estar em páginas diferentes para comprovar resolução cross-page"
        )

        orig_item = all_items[original.id]
        assert orig_item["substituido"] is True, orig_item
        assert orig_item["substituido_por"] == successor.id, orig_item
        assert orig_item["substituto"] is False, orig_item
        assert orig_item["substitui_id"] is None, orig_item

        succ_item = all_items[successor.id]
        assert succ_item["substituto"] is True, succ_item
        assert succ_item["substitui_id"] == original.id, succ_item
        assert succ_item["substituido"] is False, succ_item
        assert succ_item["substituido_por"] is None, succ_item

    asyncio.run(_with_client(prontuario_db, op))


def test_pais_keyset_consistente_com_ocorrido_em(prontuario_db):
    """MEDIUM: keyset SQL do PAIS deve usar o mesmo timestamp que ocorrido_em do evento.
    Quando aprovado_em != created_at, o cursor carrega ocorrido_em=aprovado_em; se o
    SQL comparar created_at contra esse valor o próximo fetch produz lacunas ou
    recebe registros já vistos — paginação incorreta."""
    async def op(client, db):
        ilpi = _new_inst()
        user = await _create_ilpi_user(db, ilpi, permissions=ALL_CLINICAL)
        res = await _create_residente(db, ilpi.id)

        # T1 < T2 < T3 < T4
        T1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
        T2 = datetime(2025, 1, 1, tzinfo=timezone.utc)
        T3 = datetime(2026, 1, 1, tzinfo=timezone.utc)
        T4 = datetime(2027, 1, 1, tzinfo=timezone.utc)

        # P1: created_at muito antigo, aprovado_em recente → ocorrido_em=T4 (1º em DESC)
        p1 = m.PlanoCuidados(
            id=_new_id(), residente_id=res.id, ilpi_id=ilpi.id,
            versao=1, objetivos="obj", data_inicial=date(2024, 1, 1),
            situacao="aprovado", autor_id=user.id,
            aprovado_em=T4, created_at=T1,
        )
        # P2: timestamps iguais → ocorrido_em=T3 (2º)
        p2 = m.PlanoCuidados(
            id=_new_id(), residente_id=res.id, ilpi_id=ilpi.id,
            versao=2, objetivos="obj", data_inicial=date(2025, 1, 1),
            situacao="aprovado", autor_id=user.id,
            aprovado_em=T3, created_at=T3,
        )
        # P3: timestamps iguais → ocorrido_em=T2 (3º)
        p3 = m.PlanoCuidados(
            id=_new_id(), residente_id=res.id, ilpi_id=ilpi.id,
            versao=3, objetivos="obj", data_inicial=date(2026, 1, 1),
            situacao="aprovado", autor_id=user.id,
            aprovado_em=T2, created_at=T2,
        )
        db.add_all([p1, p2, p3])
        await db.commit()

        # Navega com limit=1 e origem=pais — deve retornar P1, P2, P3 exatamente
        # uma vez, em ordem ocorrido_em DESC, sem lacunas nem duplicatas.
        expected = [
            (T4, T1, "pais", p1.id, "pais"),
            (T3, T3, "pais", p2.id, "pais"),
            (T2, T2, "pais", p3.id, "pais"),
        ]
        headers = _headers(user, ilpi_id=ilpi.id)
        received = []
        params = {"limit": 1, "origem": "pais"}
        for _ in range(10):
            response = await client.get(_pront_url(res.id), headers=headers, params=params)
            assert response.status_code == 200, response.text
            page = response.json()
            for item in page["items"]:
                received.append(_event_key(item))
            if not page["has_more"]:
                break
            params = {"limit": 1, "origem": "pais", "cursor": page["next_cursor"]}
        else:
            raise AssertionError("loop não terminou — provável loop infinito de cursor")

        assert received == sorted(expected, reverse=True), \
            f"ordem ou conteúdo incorreto:\n  recebido: {received}\n  esperado: {sorted(expected, reverse=True)}"
        assert len(received) == len(set(received)), \
            f"duplicatas detectadas: {received}"
    asyncio.run(_with_client(prontuario_db, op))
