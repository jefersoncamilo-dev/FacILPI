"""C5: catalogo, versoes clinicas e registro documental de doses."""

from contextlib import asynccontextmanager
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import AwareDatetime
from sqlalchemy import exists, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure import models as m
from ..infrastructure.database import get_db
from . import schemas as s
from .audit import add_audit
from .security import RESOURCE_NOT_FOUND, SecurityContext, require_ilpi_context, require_permission


medicamentos_router = APIRouter(prefix="/medicamentos", tags=["medicamentos"], dependencies=[Depends(require_ilpi_context)])
prescricoes_router = APIRouter(prefix="/prescricoes", tags=["prescricoes"], dependencies=[Depends(require_ilpi_context)])
doses_previstas_router = APIRouter(prefix="/doses-previstas", tags=["doses_previstas"], dependencies=[Depends(require_ilpi_context)])
administracoes_router = APIRouter(prefix="/administracoes", tags=["administracoes"], dependencies=[Depends(require_ilpi_context)])


def utcnow():
    return datetime.now(timezone.utc)


def _now_utc():
    return utcnow()


def _utc(value):
    # SQLite drops timezone metadata; all C5 timestamps are persisted in UTC.
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _data(obj):
    return {
        column.key: _utc(value) if isinstance(value, datetime) else value
        for column in obj.__table__.columns
        for value in [getattr(obj, column.key)]
    }


def _fail(message, status=409):
    raise HTTPException(status_code=status, detail={"code": "MEDICACAO_CONFLICT" if status == 409 else "MEDICACAO_INVALID", "message": message})


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
        constraint = getattr(getattr(original, "diag", None), "constraint_name", "") or ""
        unique_conflict = any(name in text or name == constraint for name in (
            "uq_prescricoes_anterior", "uq_programacoes_prescricao", "uq_doses_programacao_horario",
            "uq_administracoes_dose_vigente", "uq_administracoes_substitui",
            "unique constraint failed: prescricoes.anterior_id",
            "unique constraint failed: programacoes_medicacao.prescricao_id",
            "unique constraint failed: doses_previstas.programacao_id, doses_previstas.previsto_em",
            "unique constraint failed: administracoes.dose_prevista_id",
            "unique constraint failed: administracoes.substitui_id",
        ))
        sqlite_code = getattr(original, "sqlite_errorcode", 0) or 0
        lock_conflict = code in {"40001", "40P01", "55P03"} or (sqlite_code & 255) in {5, 6}
        if unique_conflict or lock_conflict:
            _fail("Conflito concorrente; recarregue o recurso antes de tentar novamente")
        raise
    except Exception:
        await db.rollback()
        raise


async def _get(db, model, resource_id, context):
    tenant = model.instituicao_id if model is m.Residente else model.ilpi_id
    obj = (await db.execute(select(model).where(model.id == resource_id, tenant == context.ilpi_id).execution_options(populate_existing=True))).scalar_one_or_none()
    if obj is None:
        _missing()
    return obj


async def _lock_prescricao(db, resource_id, context):
    # This UPDATE is the first DML of every clinical transition, on both engines.
    with db.no_autoflush:
        result = await db.execute(
            update(m.Prescricao)
            .where(m.Prescricao.id == resource_id, m.Prescricao.ilpi_id == context.ilpi_id)
            .values(lock_version=m.Prescricao.lock_version + 1)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            _missing()
        return await _get(db, m.Prescricao, resource_id, context)


async def _audit(db, obj, context, request, action, before=None):
    await db.flush()
    add_audit(db, acao=f"{obj.__tablename__}.{action}", entidade=obj.__tablename__, registro_id=obj.id,
              usuario_id=context.user.id, ilpi_id=context.ilpi_id,
              valores_anteriores=before, valores_posteriores=_data(obj), request=request)


async def _programacao(db, prescricao, context):
    return (await db.execute(select(m.ProgramacaoMedicacao).where(
        m.ProgramacaoMedicacao.prescricao_id == prescricao.id,
        m.ProgramacaoMedicacao.ilpi_id == context.ilpi_id,
    ).execution_options(populate_existing=True))).scalar_one_or_none()


async def _prescricao_response(db, obj, context):
    result = _data(obj)
    programacao = await _programacao(db, obj, context)
    result["programacao"] = _data(programacao) if programacao else None
    return result


def _has_administracao():
    return exists().where(
        m.Administracao.dose_prevista_id == m.DosePrevista.id,
        m.Administracao.ilpi_id == m.DosePrevista.ilpi_id,
        m.Administracao.estornado_em.is_(None),
    )


async def _dose_response(db, dose):
    result = _data(dose)
    completed = await db.scalar(select(_has_administracao()).select_from(m.DosePrevista).where(
        m.DosePrevista.id == dose.id, m.DosePrevista.ilpi_id == dose.ilpi_id))
    result["pendente"] = dose.situacao == "prevista" and not completed
    return result


async def _parents(db, context, residente_id=None, prescricao_id=None, dose_prevista_id=None):
    if residente_id is not None:
        await _get(db, m.Residente, residente_id, context)
    if prescricao_id is not None:
        await _get(db, m.Prescricao, prescricao_id, context)
    if dose_prevista_id is not None:
        await _get(db, m.DosePrevista, dose_prevista_id, context)


async def _new_prescricao(db, payload, context, request, anterior=None, motivo=None):
    await _get(db, m.Residente, payload.residente_id, context)
    medicamento = await _get(db, m.Medicamento, payload.medicamento_id, context)
    if medicamento.situacao != "ativo":
        _fail("Medicamento inativo nao permite nova prescricao")
    obj = m.Prescricao(**payload.model_dump(), ilpi_id=context.ilpi_id, autor_id=context.user.id,
                       prescritor=payload.prescritor_nome, situacao="rascunho",
                       anterior_id=anterior, motivo_versao=motivo,
                       medicamento_snapshot={key: getattr(medicamento, key) for key in (
                           "id", "nome", "principio_ativo", "apresentacao", "concentracao", "unidade", "fabricante")})
    db.add(obj)
    await _audit(db, obj, context, request, "criar")
    return obj


def _local_time(day, clock, zone):
    naive = datetime.combine(day, time.fromisoformat(clock))
    candidates = set()
    for fold in (0, 1):
        candidate = naive.replace(tzinfo=zone, fold=fold).astimezone(timezone.utc)
        if candidate.astimezone(zone).replace(tzinfo=None) == naive:
            candidates.add(candidate)
    if len(candidates) != 1:
        _fail("Horario local ambiguo ou inexistente na programacao", 422)
    return candidates.pop()


async def _materialize(db, prescricao, programacao, context, request, now):
    zone = ZoneInfo(programacao.timezone)
    start = _utc(programacao.cobertura_ate) or max(now, _utc(programacao.vigencia_inicio))
    end = now + timedelta(days=7)
    if programacao.vigencia_fim is not None:
        end = min(end, _utc(programacao.vigencia_fim))
    if end <= start:
        return
    occurrences = []
    day = start.astimezone(zone).date()
    last = end.astimezone(zone).date()
    while day <= last:
        for clock in programacao.horarios:
            instant = _local_time(day, clock, zone)
            if start <= instant < end:
                occurrences.append(instant)
        day += timedelta(days=1)
    # Validate the entire window before inserting any occurrence.
    existing = {_utc(value) for value in (await db.scalars(select(m.DosePrevista.previsto_em).where(
        m.DosePrevista.programacao_id == programacao.id, m.DosePrevista.ilpi_id == context.ilpi_id,
        m.DosePrevista.previsto_em >= start, m.DosePrevista.previsto_em < end))).all()}
    for instant in sorted(occurrences):
        if instant not in existing:
            dose = m.DosePrevista(ilpi_id=context.ilpi_id, residente_id=prescricao.residente_id,
                                  prescricao_id=prescricao.id, programacao_id=programacao.id,
                                  previsto_em=instant, situacao="prevista")
            db.add(dose)
            await _audit(db, dose, context, request, "prever")
    before = _data(programacao)
    programacao.cobertura_ate = end
    await _audit(db, programacao, context, request, "reconciliar", before)


async def _activate(db, obj, payload, context, request, now):
    if obj.situacao != "rascunho" or await _programacao(db, obj, context) is not None:
        _fail("Somente rascunho sem programacao pode ser ativado")
    medicamento = await _get(db, m.Medicamento, obj.medicamento_id, context)
    if medicamento.situacao != "ativo":
        _fail("Medicamento inativo nao permite ativar prescricao")
    zone = ZoneInfo(payload.timezone)
    start, end = _utc(payload.vigencia_inicio), _utc(payload.vigencia_fim)
    if start.astimezone(zone).date() < obj.inicio:
        _fail("Vigencia anterior ao inicio da prescricao", 422)
    if obj.termino is not None:
        bound = _local_time(obj.termino + timedelta(days=1), "00:00", zone)
        if start >= bound or (end is not None and end > bound):
            _fail("Vigencia fora das datas da prescricao", 422)
        end = end or bound
    if end is not None and end <= now:
        _fail("Vigencia ja encerrada", 422)
    before = _data(obj)
    obj.situacao, obj.ativado_em, obj.ativado_por = "ativa", now, context.user.id
    programacao = m.ProgramacaoMedicacao(ilpi_id=context.ilpi_id, residente_id=obj.residente_id,
        prescricao_id=obj.id, horarios=sorted(payload.horarios), timezone=payload.timezone,
        vigencia_inicio=start, vigencia_fim=end, situacao="ativa", autor_id=context.user.id)
    db.add(programacao)
    await _audit(db, programacao, context, request, "criar")
    await _materialize(db, obj, programacao, context, request, now)
    await _audit(db, obj, context, request, "ativar", before)


async def _cancel(db, obj, motivo, context, request, now):
    programacao = await _programacao(db, obj, context)
    if programacao is not None:
        before = _data(programacao)
        programacao.situacao = "cancelada"
        await _audit(db, programacao, context, request, "cancelar", before)
    doses = (await db.scalars(select(m.DosePrevista).where(
        m.DosePrevista.prescricao_id == obj.id, m.DosePrevista.ilpi_id == context.ilpi_id,
        m.DosePrevista.situacao == "prevista", ~_has_administracao(),
    ).execution_options(populate_existing=True))).all()
    for dose in doses:
        before = _data(dose)
        dose.situacao, dose.cancelado_em, dose.cancelado_por = "cancelada", now, context.user.id
        dose.motivo_cancelamento = motivo
        await _audit(db, dose, context, request, "cancelar", before)


async def _validate_fact(db, obj, dose, payload, context, now, historical=False):
    programacao = await _programacao(db, obj, context)
    if programacao is None or obj.ativado_em is None:
        _fail("Prescricao sem ativacao")
    occurred = _utc(payload.ocorrido_em)
    start, end = _utc(programacao.vigencia_inicio), _utc(programacao.vigencia_fim)
    scheduled = _utc(dose.previsto_em)
    if dose.situacao != "prevista":
        _fail("Dose cancelada nao pode receber registro")
    if occurred > now:
        _fail("Ocorrido em nao pode estar no futuro", 422)
    if occurred < _utc(obj.ativado_em):
        _fail("Registro anterior a ativacao", 422)
    if scheduled < start or occurred < start or (end is not None and (scheduled >= end or occurred >= end)):
        _fail("Dose ou fato fora da vigencia", 422)
    zone = ZoneInfo(programacao.timezone)
    for instant in (scheduled, occurred):
        local_day = instant.astimezone(zone).date()
        if local_day < obj.inicio or (obj.termino is not None and local_day > obj.termino):
            _fail("Dose ou fato fora das datas da prescricao", 422)
    if historical:
        boundaries = [_utc(value) for value in (obj.suspenso_em, obj.substituido_em, obj.encerrado_em) if value is not None]
        if boundaries and occurred >= min(boundaries):
            _fail("Fato fora do periodo historico elegivel", 422)
    elif obj.situacao != "ativa" or programacao.situacao != "ativa" or (end is not None and now >= end):
        _fail("Prescricao nao esta ativa e vigente")


async def _record(db, dose, payload, context, request, now, substitui_id=None):
    values = payload.model_dump(exclude={"dose_prevista_id"})
    values["ocorrido_em"] = _utc(values["ocorrido_em"])
    obj = m.Administracao(**values, dose_prevista_id=dose.id, ilpi_id=context.ilpi_id,
        residente_id=dose.residente_id, prescricao_id=dose.prescricao_id,
        executor_id=context.user.id, registrado_em=now, substitui_id=substitui_id)
    db.add(obj)
    await _audit(db, obj, context, request, "registrar")
    return obj


@medicamentos_router.get("/", response_model=list[s.C5MedicamentoResponse])
async def listar_medicamentos(skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("medicamentos:ler"))):
    return [_data(obj) for obj in (await db.scalars(select(m.Medicamento).where(
        m.Medicamento.ilpi_id == context.ilpi_id).order_by(m.Medicamento.nome, m.Medicamento.id).offset(skip).limit(limit))).all()]


@medicamentos_router.get("/{id}", response_model=s.C5MedicamentoResponse)
async def obter_medicamento(id: str, db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("medicamentos:ler"))):
    return _data(await _get(db, m.Medicamento, id, context))


@medicamentos_router.post("/", response_model=s.C5MedicamentoResponse, status_code=201)
async def criar_medicamento(payload: s.C5MedicamentoCreate, request: Request, db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("medicamentos:criar"))):
    async with _write(db):
        obj = m.Medicamento(**payload.model_dump(), ilpi_id=context.ilpi_id, autor_id=context.user.id)
        db.add(obj)
        await _audit(db, obj, context, request, "criar")
        result = _data(obj)
    return result


@medicamentos_router.patch("/{id}", response_model=s.C5MedicamentoResponse)
async def atualizar_medicamento(id: str, payload: s.C5MedicamentoPatch, request: Request,
    db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("medicamentos:atualizar"))):
    async with _write(db):
        obj = await _get(db, m.Medicamento, id, context)
        before = _data(obj)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(obj, key, value)
        await _audit(db, obj, context, request, "atualizar", before)
        result = _data(obj)
    return result


@prescricoes_router.get("/", response_model=list[s.C5PrescricaoResponse])
async def listar_prescricoes(residente_id: str | None = None, skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("prescricoes:ler"))):
    await _parents(db, context, residente_id=residente_id)
    query = select(m.Prescricao).where(m.Prescricao.ilpi_id == context.ilpi_id)
    if residente_id is not None:
        query = query.where(m.Prescricao.residente_id == residente_id)
    objects = (await db.scalars(query.order_by(m.Prescricao.created_at.desc(), m.Prescricao.id).offset(skip).limit(limit))).all()
    return [await _prescricao_response(db, obj, context) for obj in objects]


@prescricoes_router.get("/{id}", response_model=s.C5PrescricaoResponse)
async def obter_prescricao(id: str, db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("prescricoes:ler"))):
    return await _prescricao_response(db, await _get(db, m.Prescricao, id, context), context)


@prescricoes_router.post("/", response_model=s.C5PrescricaoResponse, status_code=201)
async def criar_prescricao(payload: s.C5PrescricaoCreate, request: Request, db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("prescricoes:criar"))):
    async with _write(db):
        obj = await _new_prescricao(db, payload, context, request)
        result = await _prescricao_response(db, obj, context)
    return result


@prescricoes_router.post("/{id}/ativar", response_model=s.C5PrescricaoResponse)
async def ativar_prescricao(id: str, payload: s.C5Ativacao, request: Request, db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("prescricoes:atualizar"))):
    async with _write(db):
        obj = await _lock_prescricao(db, id, context)
        await _activate(db, obj, payload, context, request, _now_utc())
        result = await _prescricao_response(db, obj, context)
    return result


@prescricoes_router.post("/{id}/reconciliar", response_model=s.C5PrescricaoResponse)
async def reconciliar_prescricao(id: str, request: Request, payload: s.C5Input | None = None, db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("prescricoes:atualizar"))):
    async with _write(db):
        obj = await _lock_prescricao(db, id, context)
        programacao = await _programacao(db, obj, context)
        if obj.situacao != "ativa" or programacao is None or programacao.situacao != "ativa":
            _fail("Somente prescricao ativa pode ser reconciliada")
        before = _data(obj)
        await _materialize(db, obj, programacao, context, request, _now_utc())
        await _audit(db, obj, context, request, "reconciliar", before)
        result = await _prescricao_response(db, obj, context)
    return result


async def _stop(db, id, payload, context, request, encerramento):
    async with _write(db):
        obj = await _lock_prescricao(db, id, context)
        allowed = {"rascunho", "ativa", "suspensa"} if encerramento else {"ativa"}
        if obj.situacao not in allowed:
            _fail("Transicao de prescricao nao permitida")
        before, now = _data(obj), _now_utc()
        if encerramento:
            obj.situacao, obj.encerrado_em, obj.encerrado_por = "encerrada", now, context.user.id
            obj.motivo_encerramento = payload.motivo
        else:
            obj.situacao, obj.suspenso_em, obj.suspenso_por = "suspensa", now, context.user.id
            obj.motivo_suspensao = payload.motivo
        await _cancel(db, obj, payload.motivo, context, request, now)
        await _audit(db, obj, context, request, "encerrar" if encerramento else "suspender", before)
        result = await _prescricao_response(db, obj, context)
    return result


@prescricoes_router.post("/{id}/suspender", response_model=s.C5PrescricaoResponse)
async def suspender_prescricao(id: str, payload: s.C5Motivo, request: Request, db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("prescricoes:atualizar"))):
    return await _stop(db, id, payload, context, request, False)


@prescricoes_router.post("/{id}/encerrar", response_model=s.C5PrescricaoResponse)
async def encerrar_prescricao(id: str, payload: s.C5Motivo, request: Request, db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("prescricoes:atualizar"))):
    return await _stop(db, id, payload, context, request, True)


@prescricoes_router.post("/{id}/substituir", response_model=s.C5PrescricaoResponse, status_code=201)
async def substituir_prescricao(id: str, payload: s.C5Substituicao, request: Request, db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("prescricoes:atualizar"))):
    async with _write(db):
        obj = await _lock_prescricao(db, id, context)
        await _parents(db, context, residente_id=payload.prescricao.residente_id)
        if payload.prescricao.residente_id != obj.residente_id:
            _fail("Nova versao deve pertencer ao mesmo residente", 422)
        successor = await db.scalar(select(m.Prescricao.id).where(
            m.Prescricao.anterior_id == obj.id, m.Prescricao.ilpi_id == context.ilpi_id))
        if obj.situacao not in {"ativa", "suspensa"} or successor is not None:
            _fail("Prescricao nao elegivel para substituicao")
        before, now = _data(obj), _now_utc()
        new = await _new_prescricao(db, payload.prescricao, context, request, obj.id, payload.motivo)
        await _activate(db, new, payload.programacao, context, request, now)
        obj.situacao, obj.substituido_em = "substituida", now
        await _cancel(db, obj, payload.motivo, context, request, now)
        await _audit(db, obj, context, request, "substituir", before)
        result = await _prescricao_response(db, new, context)
    return result


@doses_previstas_router.get("/", response_model=list[s.C5DoseResponse])
async def listar_doses(residente_id: str | None = None, prescricao_id: str | None = None, pendentes: bool | None = None,
    desde: AwareDatetime | None = None, ate: AwareDatetime | None = None,
    skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500), db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("doses_previstas:ler"))):
    await _parents(db, context, residente_id, prescricao_id)
    if desde is not None and ate is not None and desde > ate:
        _fail("Intervalo de consulta invalido", 422)
    pending = (m.DosePrevista.situacao == "prevista") & ~_has_administracao()
    query = select(m.DosePrevista, pending.label("pendente")).where(m.DosePrevista.ilpi_id == context.ilpi_id)
    for key, value in (("residente_id", residente_id), ("prescricao_id", prescricao_id)):
        if value is not None:
            query = query.where(getattr(m.DosePrevista, key) == value)
    if pendentes is not None:
        query = query.where(pending if pendentes else ~pending)
    if desde is not None:
        query = query.where(m.DosePrevista.previsto_em >= _utc(desde))
    if ate is not None:
        query = query.where(m.DosePrevista.previsto_em <= _utc(ate))
    rows = (await db.execute(query.order_by(m.DosePrevista.previsto_em, m.DosePrevista.id).offset(skip).limit(limit))).all()
    return [dict(_data(obj), pendente=bool(pending_value)) for obj, pending_value in rows]


@doses_previstas_router.get("/{id}", response_model=s.C5DoseResponse)
async def obter_dose(id: str, db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("doses_previstas:ler"))):
    return await _dose_response(db, await _get(db, m.DosePrevista, id, context))


@administracoes_router.get("/", response_model=list[s.C5AdministracaoResponse])
async def listar_administracoes(residente_id: str | None = None, prescricao_id: str | None = None, dose_prevista_id: str | None = None,
    skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500), db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("administracoes:ler"))):
    await _parents(db, context, residente_id, prescricao_id, dose_prevista_id)
    query = select(m.Administracao).where(m.Administracao.ilpi_id == context.ilpi_id)
    for key, value in (("residente_id", residente_id), ("prescricao_id", prescricao_id), ("dose_prevista_id", dose_prevista_id)):
        if value is not None:
            query = query.where(getattr(m.Administracao, key) == value)
    return [_data(obj) for obj in (await db.scalars(query.order_by(
        m.Administracao.ocorrido_em.desc(), m.Administracao.id).offset(skip).limit(limit))).all()]


@administracoes_router.get("/{id}", response_model=s.C5AdministracaoResponse)
async def obter_administracao(id: str, db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("administracoes:ler"))):
    return _data(await _get(db, m.Administracao, id, context))


@administracoes_router.post("/", response_model=s.C5AdministracaoResponse, status_code=201)
async def registrar_administracao(payload: s.C5AdministracaoCreate, request: Request, db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("administracoes:criar"))):
    async with _write(db):
        dose = await _get(db, m.DosePrevista, payload.dose_prevista_id, context)
        obj = await _lock_prescricao(db, dose.prescricao_id, context)
        dose = await _get(db, m.DosePrevista, payload.dose_prevista_id, context)
        now = _now_utc()
        await _validate_fact(db, obj, dose, payload, context, now)
        if not (await _dose_response(db, dose))["pendente"]:
            _fail("Dose ja possui administracao nao estornada")
        result = _data(await _record(db, dose, payload, context, request, now))
    return result


@administracoes_router.post("/{id}/estornar", response_model=s.C5AdministracaoResponse)
async def estornar_administracao(id: str, payload: s.C5Estorno, request: Request, db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("administracoes:corrigir"))):
    async with _write(db):
        original = await _get(db, m.Administracao, id, context)
        obj = await _lock_prescricao(db, original.prescricao_id, context)
        original = await _get(db, m.Administracao, id, context)
        if original.estornado_em is not None:
            _fail("Administracao ja estornada")
        dose = await _get(db, m.DosePrevista, original.dose_prevista_id, context)
        now = _now_utc()
        if payload.substituto is not None:
            await _validate_fact(db, obj, dose, payload.substituto, context, now, historical=True)
        before = _data(original)
        original.estornado_em, original.estornado_por, original.motivo_estorno = now, context.user.id, payload.motivo
        # Flush the reversal before the replacement to release the partial unique index.
        await _audit(db, original, context, request, "estornar", before)
        result = _data(original)
        if payload.substituto is not None:
            result["substituto"] = _data(await _record(db, dose, payload.substituto, context, request, now, original.id))
        elif obj.situacao != "ativa":
            # An isolated reversal must not resurrect an unexecutable dose.
            before = _data(dose)
            dose.situacao, dose.cancelado_em, dose.cancelado_por = "cancelada", now, context.user.id
            dose.motivo_cancelamento = payload.motivo
            await _audit(db, dose, context, request, "cancelar", before)
    return result
