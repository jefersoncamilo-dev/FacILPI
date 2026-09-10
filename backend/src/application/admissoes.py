"""D.3: orquestracao humana; fontes de dominio consultadas, nunca copiadas.

situacao e a unica maquina de estados. Pre-cadastro vincula cadastro existente
em 'Em admissao' (default oficial) ou 'Pre-admissao' do consumidor legado.
Reabertura terminal retorna a pre_cadastro, preservando evidencias e historico.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure import models as m
from ..infrastructure.database import get_db
from . import schemas as s
from .audit import add_audit
from .security import RESOURCE_NOT_FOUND, SecurityContext, require_ilpi_context, require_permission


admissoes_router = APIRouter(prefix="/admissoes", tags=["admissoes"], dependencies=[Depends(require_ilpi_context)])
ETAPAS = ("pre_cadastro", "triagem", "documentacao", "avaliacoes", "contrato", "quarto_leito", "pais")
TERMINAIS = ("concluida", "cancelada", "desistencia")


def _now():
    return datetime.now(timezone.utc)


def _data(obj):
    return {c.key: (v.replace(tzinfo=timezone.utc) if isinstance(v, datetime) and v.tzinfo is None else v)
            for c in obj.__table__.columns for v in [getattr(obj, c.key)]}


def _fail(message, status=409, **extra):
    raise HTTPException(status_code=status, detail={"code": "ADMISSAO_CONFLITO" if status == 409 else "ADMISSAO_INVALIDA", "message": message, **extra})


def _missing():
    raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso nao encontrado"})


@asynccontextmanager
async def _write(db):
    try:
        yield
        await db.commit()
    except (IntegrityError, OperationalError) as exc:
        await db.rollback()
        original = exc.orig
        code = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
        text = str(original).lower()
        sqlite_code = getattr(original, "sqlite_errorcode", 0) or 0
        if (code in {"40001", "40P01", "55P03"} or (sqlite_code & 255) in {5, 6}
                or "uq_admissoes_residente_processo" in text
                or "unique constraint failed: admissoes.ilpi_id, admissoes.residente_id" in text):
            _fail("Processo duplicado ou conflito concorrente; recarregue antes de tentar novamente")
        raise
    except Exception:
        await db.rollback()
        raise


async def _get(db, id, context):
    obj = await db.scalar(select(m.Admissao).where(m.Admissao.id == id, m.Admissao.ilpi_id == context.ilpi_id)
                          .execution_options(populate_existing=True))
    if obj is None:
        _missing()
    return obj


async def _lock(db, id, version, context):
    # CAS e o primeiro DML, inclusive no SQLite: serializa todas as acoes
    # antes de ler estado/evidencias. Uma versao obsoleta nunca e reaplicada.
    with db.no_autoflush:
        result = await db.execute(update(m.Admissao).where(
            m.Admissao.id == id, m.Admissao.ilpi_id == context.ilpi_id,
            m.Admissao.lock_version == version,
        ).values(lock_version=version + 1).execution_options(synchronize_session=False))
    obj = await _get(db, id, context)
    if result.rowcount != 1:
        _fail("Versao obsoleta; recarregue a admissao")
    before = _data(obj)
    before["lock_version"] = version
    return obj, before


async def _residente(db, id, context, lock=False):
    query = select(m.Residente).where(m.Residente.id == id, m.Residente.instituicao_id == context.ilpi_id)
    obj = await db.scalar(query.with_for_update() if lock else query)
    if obj is None:
        _missing()
    return obj


async def _responsavel(db, id, context):
    if id is None:
        return
    obj = await db.scalar(select(m.Funcionario).where(m.Funcionario.id == id, m.Funcionario.ilpi_id == context.ilpi_id))
    if obj is None:
        _missing()
    if obj.situacao != "ativo":
        _fail("Responsavel operacional deve ser funcionario ativo", 422)


async def _record(db, obj, context, request, acao, before=None, motivo=None, verificacao=None):
    obj.updated_at = _now()
    await db.flush()
    db.add(m.AdmissaoHistorico(ilpi_id=context.ilpi_id, admissao_id=obj.id,
                              etapa_origem=before["situacao"] if before else None, etapa_destino=obj.situacao,
                              acao=acao, motivo=motivo, autor_id=context.user.id, lock_version=obj.lock_version))
    after = _data(obj)
    add_audit(db, acao=f"admissao.{acao}", entidade="admissoes", registro_id=obj.id,
              usuario_id=context.user.id, ilpi_id=context.ilpi_id, valores_anteriores=before,
              valores_posteriores={**after, "motivo": motivo, "verificacao": verificacao}, request=request)
    return after


async def _pendencias(db, obj, context, lock=False):
    # Na transicao, trava o pai (tambem impede novos filhos via FK no PG)
    # e as evidencias ate o commit. SQLite ja tem a trava de escrita do CAS.
    residente = await _residente(db, obj.residente_id, context, lock=lock)
    institution = await db.get(m.Instituicao, context.ilpi_id)
    try:
        today = _now().astimezone(ZoneInfo(institution.fuso_horario or "America/Sao_Paulo")).date()
    except ZoneInfoNotFoundError:
        _fail("Fuso horario institucional invalido", 422)
    pendencias = []
    try:
        s.ResidenteResponse.model_validate(residente)
    except ValidationError:
        pendencias.append({"codigo": "residente_pendente", "origem": "residentes", "referencia_id": residente.id})
    query = select(m.Documento).where(
        m.Documento.residente_id == obj.residente_id, m.Documento.instituicao_id == context.ilpi_id,
    ).order_by(m.Documento.id)
    docs = (await db.scalars(query.with_for_update() if lock else query)).all()
    documentos = []
    for doc in docs:
        # Contrato oficial D.3: so a validacao humana cumpre. obrigatorio +
        # validado cumpre independente de validade/arquivo; validade e arquivo
        # nunca bloqueiam e "vencido" nao e derivado como motivo nesta fase.
        cumprido = doc.situacao == "validado"
        documentos.append({"id": doc.id, "tipo": doc.tipo, "obrigatorio": doc.obrigatorio,
                           "situacao": doc.situacao, "validade": doc.validade,
                           "cumprido": cumprido, "origem": "documentos.obrigatorio"})
        if doc.obrigatorio and not cumprido:
            pendencias.append({"codigo": "documentacao_pendente", "origem": "documentos.obrigatorio",
                               "referencia_id": doc.id, "motivo": "documento_nao_validado"})
    query = select(m.Avaliacao).where(
        m.Avaliacao.residente_id == obj.residente_id, m.Avaliacao.ilpi_id == context.ilpi_id,
    ).order_by(m.Avaliacao.id)
    avaliacoes = (await db.scalars(query.with_for_update() if lock else query)).all()
    requisitos = []
    for requisito in obj.avaliacoes_requeridas:
        ids = [a.id for a in avaliacoes if a.tipo == requisito["tipo"]
               and (requisito.get("instrumento") is None or a.instrumento == requisito["instrumento"])
               and (a.validade is None or a.validade >= today)]
        requisitos.append({**requisito, "avaliacao_ids": ids, "cumprido": bool(ids)})
        if not ids:
            pendencias.append({"codigo": "avaliacao_requerida_pendente", "origem": requisito["origem"], "tipo": requisito["tipo"], "instrumento": requisito.get("instrumento")})
    if obj.contrato_registrado_em is None:
        pendencias.append({"codigo": "contrato_pendente", "origem": "admissoes.contrato_registrado_em"})
    if obj.contrato_documento_id is not None and not any(d.id == obj.contrato_documento_id for d in docs):
        _missing()
    query = select(m.QuartoLeito).where(
        m.QuartoLeito.instituicao_id == context.ilpi_id, m.QuartoLeito.residente_atual_id == obj.residente_id,
    ).order_by(m.QuartoLeito.id)
    rows = (await db.scalars(query.with_for_update() if lock else query)).all()
    leitos = [row.id for row in rows if row.situacao == "livre" and row.capacidade == 1]
    if len(leitos) != 1:
        pendencias.append({"codigo": "quarto_leito_pendente", "origem": "quartos_leitos.residente_atual_id"})
    query = select(m.PlanoCuidados).where(
        m.PlanoCuidados.ilpi_id == context.ilpi_id, m.PlanoCuidados.residente_id == obj.residente_id,
    ).order_by(m.PlanoCuidados.id)
    rows = (await db.scalars(query.with_for_update() if lock else query)).all()
    planos = [row.id for row in rows if row.situacao == "vigente"]
    if len(planos) != 1:
        pendencias.append({"codigo": "pais_pendente", "origem": "planos_cuidados.situacao=vigente"})
    return {"admissao_id": obj.id, "lock_version": obj.lock_version, "data_verificacao": today,
            "documentos": documentos, "avaliacoes_requeridas": requisitos,
            "avaliacoes": [{"id": a.id, "tipo": a.tipo, "instrumento": a.instrumento, "validade": a.validade} for a in avaliacoes],
            "quarto_leito_ids": list(leitos), "pais_ids": list(planos),
            "pendencias": pendencias, "requisitos_cumpridos": not pendencias}


@admissoes_router.get("/", response_model=list[s.AdmissaoResponse])
async def listar(residente_id: str | None = None, skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
                 db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("admissoes:ler"))):
    query = select(m.Admissao).where(m.Admissao.ilpi_id == context.ilpi_id)
    if residente_id is not None:
        await _residente(db, residente_id, context)
        query = query.where(m.Admissao.residente_id == residente_id)
    return [_data(a) for a in (await db.scalars(query.order_by(m.Admissao.created_at.desc(), m.Admissao.id).offset(skip).limit(limit))).all()]


@admissoes_router.get("/{id}", response_model=s.AdmissaoResponse)
async def obter(id: str, db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("admissoes:ler"))):
    return _data(await _get(db, id, context))


@admissoes_router.get("/{id}/pendencias")
async def pendencias(id: str, db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("admissoes:ler"))):
    return await _pendencias(db, await _get(db, id, context), context)


@admissoes_router.get("/{id}/historico")
async def historico(id: str, db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("admissoes:ler"))):
    await _get(db, id, context)
    return [_data(h) for h in (await db.scalars(select(m.AdmissaoHistorico).where(
        m.AdmissaoHistorico.admissao_id == id, m.AdmissaoHistorico.ilpi_id == context.ilpi_id,
    ).order_by(m.AdmissaoHistorico.lock_version))).all()]


@admissoes_router.post("/", response_model=s.AdmissaoResponse, status_code=201)
async def criar(payload: s.AdmissaoCreate, request: Request, db: AsyncSession = Depends(get_db),
                context: SecurityContext = Depends(require_permission("admissoes:criar"))):
    async with _write(db):
        residente = await _residente(db, payload.residente_id, context)
        # Grafias ja usadas pelo cadastro e pelo frontend legado; sem normalizar dados.
        if residente.situacao not in ("Em admissao", "Pr\u00e9-admiss\u00e3o"):
            _fail("Residente fora de estado compativel com pre-admissao")
        if await db.scalar(select(m.Admissao.id).where(m.Admissao.ilpi_id == context.ilpi_id,
                m.Admissao.residente_id == residente.id, m.Admissao.situacao.not_in(("cancelada", "desistencia")))):
            _fail("Residente ja possui processo de admissao")
        await _responsavel(db, payload.responsavel_funcionario_id, context)
        obj = m.Admissao(**payload.model_dump(), ilpi_id=context.ilpi_id, autor_id=context.user.id,
                         situacao="pre_cadastro", iniciada_em=_now(), lock_version=0, avaliacoes_requeridas=[])
        db.add(obj)
        result = await _record(db, obj, context, request, "criar")
    return result


async def _transicao(id, payload, request, db, context, acao):
    async with _write(db):
        obj, before = await _lock(db, id, payload.lock_version, context)
        verificacao = None
        if acao == "reabrir":
            if obj.situacao not in TERMINAIS:
                _fail("Reabertura exige processo terminal")
            obj.situacao = "pre_cadastro"
        else:
            if obj.situacao in TERMINAIS:
                _fail("Processo terminal exige reabertura explicita")
            if acao == "avancar":
                index = ETAPAS.index(obj.situacao)
                if index == len(ETAPAS) - 1 or payload.etapa_destino != ETAPAS[index + 1]:
                    _fail("Transicao ilegal; siga a proxima etapa e conclua em acao propria")
                verificacao = await _pendencias(db, obj, context, lock=True)
                blocking = {"documentacao": "documentacao_pendente", "avaliacoes": "avaliacao_requerida_pendente",
                            "contrato": "contrato_pendente", "quarto_leito": "quarto_leito_pendente"}.get(obj.situacao)
                pending = [p for p in verificacao["pendencias"] if p["codigo"] == blocking]
                if pending:
                    _fail("Etapa possui pendencias", 422, pendencias=pending)
                obj.situacao = payload.etapa_destino
            elif acao == "concluir":
                if obj.situacao != "pais":
                    _fail("Conclusao exige etapa pais")
                verificacao = await _pendencias(db, obj, context, lock=True)
                if verificacao["pendencias"]:
                    _fail("Admissao possui pendencias", 422, pendencias=verificacao["pendencias"])
                obj.situacao, obj.concluida_em = "concluida", _now()
            elif acao == "cancelar":
                obj.situacao, obj.cancelada_em, obj.motivo_cancelamento = "cancelada", _now(), payload.motivo
            elif acao == "desistir":
                obj.situacao, obj.desistencia_em, obj.motivo_desistencia = "desistencia", _now(), payload.motivo
        result = await _record(db, obj, context, request, acao, before, getattr(payload, "motivo", None), verificacao)
    return result


@admissoes_router.post("/{id}/avancar", response_model=s.AdmissaoResponse)
async def avancar(id: str, payload: s.AdmissaoAvancar, request: Request, db: AsyncSession = Depends(get_db),
                  context: SecurityContext = Depends(require_permission("admissoes:avancar"))):
    return await _transicao(id, payload, request, db, context, "avancar")


@admissoes_router.post("/{id}/concluir", response_model=s.AdmissaoResponse)
async def concluir(id: str, payload: s.AdmissaoAcao, request: Request, db: AsyncSession = Depends(get_db),
                   context: SecurityContext = Depends(require_permission("admissoes:concluir"))):
    return await _transicao(id, payload, request, db, context, "concluir")


@admissoes_router.post("/{id}/reabrir", response_model=s.AdmissaoResponse)
async def reabrir(id: str, payload: s.AdmissaoMotivo, request: Request, db: AsyncSession = Depends(get_db),
                  context: SecurityContext = Depends(require_permission("admissoes:reabrir"))):
    return await _transicao(id, payload, request, db, context, "reabrir")


@admissoes_router.post("/{id}/cancelar", response_model=s.AdmissaoResponse)
async def cancelar(id: str, payload: s.AdmissaoMotivo, request: Request, db: AsyncSession = Depends(get_db),
                   context: SecurityContext = Depends(require_permission("admissoes:cancelar"))):
    return await _transicao(id, payload, request, db, context, "cancelar")


@admissoes_router.post("/{id}/desistir", response_model=s.AdmissaoResponse)
async def desistir(id: str, payload: s.AdmissaoMotivo, request: Request, db: AsyncSession = Depends(get_db),
                   context: SecurityContext = Depends(require_permission("admissoes:cancelar"))):
    return await _transicao(id, payload, request, db, context, "desistir")


async def _editar(id, payload, request, db, context, acao):
    async with _write(db):
        obj, before = await _lock(db, id, payload.lock_version, context)
        if obj.situacao in TERMINAIS:
            _fail("Processo terminal nao pode ser editado")
        if acao == "responsavel_alterar":
            await _responsavel(db, payload.responsavel_funcionario_id, context)
            obj.responsavel_funcionario_id = payload.responsavel_funcionario_id
        elif acao == "requisitos_alterar":
            obj.avaliacoes_requeridas = [r.model_dump() for r in payload.avaliacoes_requeridas]
        elif acao == "contrato_registrar":
            if obj.situacao != "contrato":
                _fail("Marco de contrato exige etapa contrato")
            if payload.documento_id is not None:
                doc = await db.scalar(select(m.Documento.id).where(m.Documento.id == payload.documento_id,
                    m.Documento.instituicao_id == context.ilpi_id, m.Documento.residente_id == obj.residente_id))
                if doc is None:
                    _missing()
            obj.contrato_documento_id, obj.contrato_registrado_em = payload.documento_id, _now()
        result = await _record(db, obj, context, request, acao, before, payload.motivo)
    return result


@admissoes_router.post("/{id}/responsavel", response_model=s.AdmissaoResponse)
async def responsavel(id: str, payload: s.AdmissaoResponsavel, request: Request, db: AsyncSession = Depends(get_db),
                      context: SecurityContext = Depends(require_permission("admissoes:atualizar"))):
    return await _editar(id, payload, request, db, context, "responsavel_alterar")


@admissoes_router.post("/{id}/requisitos-avaliacoes", response_model=s.AdmissaoResponse)
async def requisitos(id: str, payload: s.AdmissaoRequisitos, request: Request, db: AsyncSession = Depends(get_db),
                     context: SecurityContext = Depends(require_permission("admissoes:atualizar"))):
    return await _editar(id, payload, request, db, context, "requisitos_alterar")


@admissoes_router.post("/{id}/contrato", response_model=s.AdmissaoResponse)
async def contrato(id: str, payload: s.AdmissaoContrato, request: Request, db: AsyncSession = Depends(get_db),
                   context: SecurityContext = Depends(require_permission("admissoes:atualizar"))):
    return await _editar(id, payload, request, db, context, "contrato_registrar")
