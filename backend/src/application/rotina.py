"""D.2: rotina assistencial — Programação, Ocorrência, Execução, Meu Plantão.

Fluxo: Intervenção do PAIS vigente (ação humana explícita)
  -> ProgramacaoCuidado (horários fixos confirmados)
  -> OcorrenciaCuidado (previstas materializadas, idempotentes)
  -> ExecucaoCuidado (append-only; correção = estorno + substituto).

Meu Plantão é PROJEÇÃO (sem tabela): ocorrências pendentes + doses
previstas pendentes + intercorrências abertas. Sem escala/turno,
sem passagem persistida, sem prontuário novo, sem tolerância de atraso
hardcoded (pendente/atrasada nunca persistem). Tarefa legada intocada.
"""

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


programacoes_router = APIRouter(prefix="/programacoes-cuidado", tags=["programacoes-cuidado"], dependencies=[Depends(require_ilpi_context)])
ocorrencias_router = APIRouter(prefix="/ocorrencias-cuidado", tags=["ocorrencias-cuidado"], dependencies=[Depends(require_ilpi_context)])
execucoes_router = APIRouter(prefix="/execucoes-cuidado", tags=["execucoes-cuidado"], dependencies=[Depends(require_ilpi_context)])
plantao_router = APIRouter(prefix="/plantao", tags=["plantao"], dependencies=[Depends(require_ilpi_context)])

ROTINA_CONFLITO = "ROTINA_CONFLITO"
ROTINA_INVALIDA = "ROTINA_INVALIDA"
HORIZONTE_DIAS = 7


def _now():
    return datetime.now(timezone.utc)


def _utc(value):
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
    raise HTTPException(status_code=status, detail={"code": ROTINA_CONFLITO if status == 409 else ROTINA_INVALIDA, "message": message})


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
            "uq_ocorr_programacao_horario", "uq_exec_ocorrencia_vigente", "uq_exec_substitui",
            "unique constraint failed: ocorrencias_cuidado.programacao_id, ocorrencias_cuidado.previsto_em",
            "unique constraint failed: execucoes_cuidado.ocorrencia_id",
            "unique constraint failed: execucoes_cuidado.substitui_id",
        ))
        sqlite_code = getattr(original, "sqlite_errorcode", 0) or 0
        lock_conflict = code in {"40001", "40P01", "55P03"} or (sqlite_code & 255) in {5, 6}
        if unique_conflict or lock_conflict:
            _fail("Conflito concorrente; recarregue o recurso antes de tentar novamente")
        raise
    except Exception:
        await db.rollback()
        raise


async def _ensure_funcionario(db, funcionario_id, context):
    obj = (await db.execute(select(m.Funcionario).where(
        m.Funcionario.id == funcionario_id, m.Funcionario.ilpi_id == context.ilpi_id))).scalar_one_or_none()
    if obj is None:
        _missing()
    if obj.situacao != "ativo":
        _fail("Funcionario inativo nao pode ser designado", 422)
    if obj.usuario_id is not None:
        user = (await db.execute(select(m.User).where(m.User.id == obj.usuario_id))).scalar_one_or_none()
        if user is None or not user.ativo:
            _fail("Funcionario sem usuario/vinculo ativo", 422)
    return obj


async def _get_plano(db, plano_id, context):
    obj = (await db.execute(select(m.PlanoCuidados).where(
        m.PlanoCuidados.id == plano_id, m.PlanoCuidados.ilpi_id == context.ilpi_id))).scalar_one_or_none()
    if obj is None:
        _missing()
    return obj


async def _get_intervencao(db, intervencao_id, plano, context):
    obj = (await db.execute(select(m.PaisIntervencao).where(
        m.PaisIntervencao.id == intervencao_id, m.PaisIntervencao.plano_id == plano.id,
        m.PaisIntervencao.ilpi_id == context.ilpi_id))).scalar_one_or_none()
    if obj is None:
        _missing()
    return obj


async def _get_programacao(db, programacao_id, context):
    obj = (await db.execute(select(m.ProgramacaoCuidado).where(
        m.ProgramacaoCuidado.id == programacao_id,
        m.ProgramacaoCuidado.ilpi_id == context.ilpi_id,
    ).execution_options(populate_existing=True))).scalar_one_or_none()
    if obj is None:
        _missing()
    return obj


async def _lock_programacao(db, programacao_id, context):
    # Este UPDATE é o primeiro DML de toda transição, nos dois engines.
    with db.no_autoflush:
        result = await db.execute(
            update(m.ProgramacaoCuidado)
            .where(m.ProgramacaoCuidado.id == programacao_id, m.ProgramacaoCuidado.ilpi_id == context.ilpi_id)
            .values(lock_version=m.ProgramacaoCuidado.lock_version + 1)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            _missing()
        return await _get_programacao(db, programacao_id, context)


async def _audit(db, obj, context, request, action, before=None):
    await db.flush()
    add_audit(db, acao=f"{obj.__tablename__}.{action}", entidade=obj.__tablename__, registro_id=obj.id,
              usuario_id=context.user.id, ilpi_id=context.ilpi_id,
              valores_anteriores=before, valores_posteriores=_data(obj), request=request)


def _has_execucao_vigente():
    return exists().where(
        m.ExecucaoCuidado.ocorrencia_id == m.OcorrenciaCuidado.id,
        m.ExecucaoCuidado.ilpi_id == m.OcorrenciaCuidado.ilpi_id,
        m.ExecucaoCuidado.estornado_em.is_(None),
    )


async def _ocorrencia_response(db, ocorrencia):
    result = _data(ocorrencia)
    vigente = await db.scalar(select(m.ExecucaoCuidado.id).where(
        m.ExecucaoCuidado.ocorrencia_id == ocorrencia.id,
        m.ExecucaoCuidado.ilpi_id == ocorrencia.ilpi_id,
        m.ExecucaoCuidado.estornado_em.is_(None)))
    result["pendente"] = ocorrencia.situacao == "prevista" and vigente is None
    return result


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


async def _materialize(db, programacao, plano, context, request, now):
    # Programações da versão anterior do PAIS deixam de gerar futuro.
    if plano.situacao != "vigente":
        _fail("PAIS fora de vigencia nao gera ocorrencias")
    if programacao.situacao != "ativa":
        _fail("Somente programacao ativa gera ocorrencias")
    zone = ZoneInfo(programacao.timezone)
    start = _utc(programacao.cobertura_ate) or max(now, _utc(programacao.vigencia_inicio))
    end = now + timedelta(days=HORIZONTE_DIAS)
    if programacao.vigencia_fim is not None:
        end = min(end, _utc(programacao.vigencia_fim))
    if plano.data_final is not None:
        bound = _local_time(plano.data_final + timedelta(days=1), "00:00", zone)
        end = min(end, bound)
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
    # Valida a janela inteira antes de inserir qualquer ocorrência.
    existing = {_utc(value) for value in (await db.scalars(select(m.OcorrenciaCuidado.previsto_em).where(
        m.OcorrenciaCuidado.programacao_id == programacao.id, m.OcorrenciaCuidado.ilpi_id == context.ilpi_id,
        m.OcorrenciaCuidado.previsto_em >= start, m.OcorrenciaCuidado.previsto_em < end))).all()}
    for instant in sorted(occurrences):
        if instant not in existing:
            ocorrencia = m.OcorrenciaCuidado(
                ilpi_id=context.ilpi_id, residente_id=programacao.residente_id, plano_id=programacao.plano_id,
                intervencao_id=programacao.intervencao_id, programacao_id=programacao.id,
                previsto_em=instant, situacao="prevista")
            db.add(ocorrencia)
            await _audit(db, ocorrencia, context, request, "materializar")
    before = _data(programacao)
    programacao.cobertura_ate = end
    await _audit(db, programacao, context, request, "reconciliar", before)


async def _validate_programacao_base(db, payload, context):
    plano = await _get_plano(db, payload.plano_id, context)
    if plano.situacao != "vigente":
        _fail("Programacao exige PAIS vigente", 422)
    intervencao = await _get_intervencao(db, payload.intervencao_id, plano, context)
    if intervencao.situacao != "ativa":
        _fail("Intervencao inativa nao admite programacao", 422)
    inicio, fim = _utc(payload.vigencia_inicio), _utc(payload.vigencia_fim) if payload.vigencia_fim else None
    if inicio.date() < plano.data_inicial:
        _fail("Vigencia anterior ao inicio do PAIS", 422)
    if plano.data_final is not None:
        if inicio.date() > plano.data_final:
            _fail("Vigencia fora das datas do PAIS", 422)
        if fim is not None and fim.date() > plano.data_final:
            _fail("Vigencia fora das datas do PAIS", 422)
    if payload.funcionario_designado_id is not None:
        await _ensure_funcionario(db, payload.funcionario_designado_id, context)
    return plano, intervencao


@programacoes_router.post("/", response_model=s.ProgramacaoResponse, status_code=201)
async def criar_programacao(payload: s.ProgramacaoCreate, request: Request, db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("programacoes:criar"))):
    async with _write(db):
        plano, _ = await _validate_programacao_base(db, payload, context)
        values = payload.model_dump()
        values["vigencia_inicio"] = _utc(values["vigencia_inicio"])
        values["vigencia_fim"] = _utc(values["vigencia_fim"]) if values["vigencia_fim"] else None
        obj = m.ProgramacaoCuidado(**values, ilpi_id=context.ilpi_id,
                                   residente_id=plano.residente_id, autor_id=context.user.id, situacao="ativa")
        db.add(obj)
        await _audit(db, obj, context, request, "criar")
        await _materialize(db, obj, plano, context, request, _now())
        result = _data(obj)
    return result


@programacoes_router.get("/", response_model=list[s.ProgramacaoResponse])
async def listar_programacoes(residente_id: str | None = None, plano_id: str | None = None,
    skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("programacoes:ler"))):
    query = select(m.ProgramacaoCuidado).where(m.ProgramacaoCuidado.ilpi_id == context.ilpi_id)
    if residente_id is not None:
        query = query.where(m.ProgramacaoCuidado.residente_id == residente_id)
    if plano_id is not None:
        await _get_plano(db, plano_id, context)
        query = query.where(m.ProgramacaoCuidado.plano_id == plano_id)
    objects = (await db.scalars(query.order_by(m.ProgramacaoCuidado.created_at.desc(), m.ProgramacaoCuidado.id).offset(skip).limit(limit))).all()
    return [_data(obj) for obj in objects]


@programacoes_router.get("/{id}", response_model=s.ProgramacaoResponse)
async def obter_programacao(id: str, db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("programacoes:ler"))):
    return _data(await _get_programacao(db, id, context))


@programacoes_router.patch("/{id}", response_model=s.ProgramacaoResponse)
async def atualizar_programacao(id: str, payload: s.ProgramacaoPatch, request: Request,
    db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("programacoes:atualizar"))):
    async with _write(db):
        obj = await _lock_programacao(db, id, context)
        if obj.situacao != "ativa":
            _fail("Somente programacao ativa pode ser atualizada")
        changes = payload.model_dump(exclude_unset=True)
        if "vigencia_fim" in changes:
            novo_fim = _utc(changes["vigencia_fim"]) if changes["vigencia_fim"] else None
            atual = _utc(obj.vigencia_fim) if obj.vigencia_fim is not None else None
            if novo_fim is not None and novo_fim <= _utc(obj.vigencia_inicio):
                _fail("Fim deve ser posterior ao inicio", 422)
            if atual is not None and (novo_fim is None or novo_fim < atual):
                _fail("Reduzir vigencia exige cancelamento; use nova programacao", 422)
            changes["vigencia_fim"] = novo_fim
        if "funcionario_designado_id" in changes and changes["funcionario_designado_id"] is not None:
            await _ensure_funcionario(db, changes["funcionario_designado_id"], context)
        before = _data(obj)
        for key, value in changes.items():
            setattr(obj, key, value)
        await _audit(db, obj, context, request, "atualizar", before)
        result = _data(obj)
    return result


@programacoes_router.post("/{id}/reconciliar", response_model=s.ProgramacaoResponse)
async def reconciliar_programacao(id: str, request: Request, db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("programacoes:atualizar"))):
    async with _write(db):
        obj = await _lock_programacao(db, id, context)
        plano = await _get_plano(db, obj.plano_id, context)
        await _materialize(db, obj, plano, context, request, _now())
        result = _data(obj)
    return result


@programacoes_router.post("/{id}/cancelar", response_model=s.ProgramacaoResponse)
async def cancelar_programacao(id: str, payload: s.ProgramacaoCancel, request: Request,
    db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("programacoes:inativar"))):
    async with _write(db):
        obj = await _lock_programacao(db, id, context)
        if obj.situacao != "ativa":
            _fail("Somente programacao ativa pode ser cancelada")
        before, now = _data(obj), _now()
        obj.situacao = "cancelada"
        await _audit(db, obj, context, request, "cancelar", before)
        futuras = (await db.scalars(select(m.OcorrenciaCuidado).where(
            m.OcorrenciaCuidado.programacao_id == obj.id, m.OcorrenciaCuidado.ilpi_id == context.ilpi_id,
            m.OcorrenciaCuidado.situacao == "prevista", m.OcorrenciaCuidado.previsto_em > now,
            ~_has_execucao_vigente(),
        ).execution_options(populate_existing=True))).all()
        for ocorrencia in futuras:
            before_oc = _data(ocorrencia)
            ocorrencia.situacao, ocorrencia.cancelado_em, ocorrencia.cancelado_por = "cancelada", now, context.user.id
            ocorrencia.motivo_cancelamento = payload.motivo.strip()
            await _audit(db, ocorrencia, context, request, "cancelar", before_oc)
        result = _data(obj)
    return result


@ocorrencias_router.get("/", response_model=list[s.OcorrenciaResponse])
async def listar_ocorrencias(residente_id: str | None = None, programacao_id: str | None = None,
    pendentes: bool | None = None, desde: AwareDatetime | None = None, ate: AwareDatetime | None = None,
    skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500), db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("ocorrencias:ler"))):
    if programacao_id is not None:
        await _get_programacao(db, programacao_id, context)
    if desde is not None and ate is not None and desde > ate:
        _fail("Intervalo de consulta invalido", 422)
    pending = (m.OcorrenciaCuidado.situacao == "prevista") & ~_has_execucao_vigente()
    query = select(m.OcorrenciaCuidado, pending.label("pendente")).where(m.OcorrenciaCuidado.ilpi_id == context.ilpi_id)
    for key, value in (("residente_id", residente_id), ("programacao_id", programacao_id)):
        if value is not None:
            query = query.where(getattr(m.OcorrenciaCuidado, key) == value)
    if pendentes is not None:
        query = query.where(pending if pendentes else ~pending)
    if desde is not None:
        query = query.where(m.OcorrenciaCuidado.previsto_em >= _utc(desde))
    if ate is not None:
        query = query.where(m.OcorrenciaCuidado.previsto_em <= _utc(ate))
    rows = (await db.execute(query.order_by(m.OcorrenciaCuidado.previsto_em, m.OcorrenciaCuidado.id).offset(skip).limit(limit))).all()
    return [dict(_data(obj), pendente=bool(pending_value)) for obj, pending_value in rows]


@ocorrencias_router.get("/{id}", response_model=s.OcorrenciaResponse)
async def obter_ocorrencia(id: str, db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("ocorrencias:ler"))):
    obj = (await db.execute(select(m.OcorrenciaCuidado).where(
        m.OcorrenciaCuidado.id == id, m.OcorrenciaCuidado.ilpi_id == context.ilpi_id))).scalar_one_or_none()
    if obj is None:
        _missing()
    return await _ocorrencia_response(db, obj)


async def _get_ocorrencia(db, ocorrencia_id, context):
    obj = (await db.execute(select(m.OcorrenciaCuidado).where(
        m.OcorrenciaCuidado.id == ocorrencia_id, m.OcorrenciaCuidado.ilpi_id == context.ilpi_id,
    ).execution_options(populate_existing=True))).scalar_one_or_none()
    if obj is None:
        _missing()
    return obj


@ocorrencias_router.post("/{id}/cancelar", response_model=s.OcorrenciaResponse)
async def cancelar_ocorrencia(id: str, payload: s.OcorrenciaCancel, request: Request,
    db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("ocorrencias:cancelar"))):
    async with _write(db):
        obj = await _get_ocorrencia(db, id, context)
        programacao = await _lock_programacao(db, obj.programacao_id, context)
        obj = await _get_ocorrencia(db, id, context)
        if obj.situacao != "prevista":
            _fail("Somente ocorrencia prevista pode ser cancelada")
        if not (await _ocorrencia_response(db, obj))["pendente"]:
            _fail("Ocorrencia com execucao vigente nao pode ser cancelada")
        before, now = _data(obj), _now()
        obj.situacao, obj.cancelado_em, obj.cancelado_por = "cancelada", now, context.user.id
        obj.motivo_cancelamento = payload.motivo.strip()
        await _audit(db, obj, context, request, "cancelar", before)
        await _audit(db, programacao, context, request, "ocorrencia-cancelada", _data(programacao))
        result = await _ocorrencia_response(db, obj)
    return result


async def _validate_fato(db, programacao, ocorrencia, payload, context, now):
    plano = await _get_plano(db, programacao.plano_id, context)
    if programacao.situacao != "ativa" or plano.situacao != "vigente":
        _fail("Programacao fora de vigencia operacional")
    intervencao = await _get_intervencao(db, programacao.intervencao_id, plano, context)
    if intervencao.situacao != "ativa":
        _fail("Intervencao inativa nao admite execucao")
    if ocorrencia.situacao != "prevista":
        _fail("Ocorrencia cancelada nao admite execucao")
    ocorrido = _utc(payload.ocorrido_em)
    if ocorrido > now:
        _fail("Ocorrido em nao pode estar no futuro", 422)


async def _record(db, ocorrencia, programacao, payload, context, request, now, substitui_id=None):
    values = payload.model_dump(exclude={"ocorrencia_id"})
    values["ocorrido_em"] = _utc(values["ocorrido_em"])
    obj = m.ExecucaoCuidado(**values, ocorrencia_id=ocorrencia.id, ilpi_id=context.ilpi_id,
        residente_id=ocorrencia.residente_id, programacao_id=programacao.id,
        executor_id=context.user.id, registrado_em=now, substitui_id=substitui_id)
    db.add(obj)
    await _audit(db, obj, context, request, "registrar")
    return obj


@execucoes_router.post("/", response_model=s.ExecucaoResponse, status_code=201)
async def registrar_execucao(payload: s.ExecucaoCreate, request: Request, db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("execucoes:criar"))):
    async with _write(db):
        ocorrencia = await _get_ocorrencia(db, payload.ocorrencia_id, context)
        programacao = await _lock_programacao(db, ocorrencia.programacao_id, context)
        ocorrencia = await _get_ocorrencia(db, payload.ocorrencia_id, context)
        now = _now()
        await _validate_fato(db, programacao, ocorrencia, payload, context, now)
        if not (await _ocorrencia_response(db, ocorrencia))["pendente"]:
            _fail("Ocorrencia ja possui execucao vigente")
        result = _data(await _record(db, ocorrencia, programacao, payload, context, request, now))
    return result


@execucoes_router.get("/", response_model=list[s.ExecucaoResponse])
async def listar_execucoes(residente_id: str | None = None, programacao_id: str | None = None,
    ocorrencia_id: str | None = None, skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("execucoes:ler"))):
    query = select(m.ExecucaoCuidado).where(m.ExecucaoCuidado.ilpi_id == context.ilpi_id)
    for key, value in (("residente_id", residente_id), ("programacao_id", programacao_id), ("ocorrencia_id", ocorrencia_id)):
        if value is not None:
            query = query.where(getattr(m.ExecucaoCuidado, key) == value)
    return [_data(obj) for obj in (await db.scalars(query.order_by(
        m.ExecucaoCuidado.ocorrido_em.desc(), m.ExecucaoCuidado.id).offset(skip).limit(limit))).all()]


@execucoes_router.get("/{id}", response_model=s.ExecucaoResponse)
async def obter_execucao(id: str, db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("execucoes:ler"))):
    obj = (await db.execute(select(m.ExecucaoCuidado).where(
        m.ExecucaoCuidado.id == id, m.ExecucaoCuidado.ilpi_id == context.ilpi_id))).scalar_one_or_none()
    if obj is None:
        _missing()
    result = _data(obj)
    if obj.substitui_id is not None:
        substituto = (await db.execute(select(m.ExecucaoCuidado).where(
            m.ExecucaoCuidado.substitui_id == obj.id,
            m.ExecucaoCuidado.ilpi_id == context.ilpi_id))).scalar_one_or_none()
        result["substituto"] = _data(substituto) if substituto else None
    return result


@execucoes_router.post("/{id}/estornar", response_model=s.ExecucaoResponse)
async def estornar_execucao(id: str, payload: s.ExecucaoEstorno, request: Request,
    db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("execucoes:corrigir"))):
    async with _write(db):
        original = (await db.execute(select(m.ExecucaoCuidado).where(
            m.ExecucaoCuidado.id == id, m.ExecucaoCuidado.ilpi_id == context.ilpi_id,
        ).execution_options(populate_existing=True))).scalar_one_or_none()
        if original is None:
            _missing()
        programacao = await _lock_programacao(db, original.programacao_id, context)
        original = (await db.execute(select(m.ExecucaoCuidado).where(
            m.ExecucaoCuidado.id == id, m.ExecucaoCuidado.ilpi_id == context.ilpi_id,
        ).execution_options(populate_existing=True))).scalar_one_or_none()
        if original.estornado_em is not None:
            _fail("Execucao ja estornada")
        ocorrencia = await _get_ocorrencia(db, original.ocorrencia_id, context)
        now = _now()
        if payload.substituto is not None:
            if payload.substituto.ocorrencia_id != ocorrencia.id:
                _fail("Substituto deve pertencer a mesma ocorrencia", 422)
            await _validate_fato(db, programacao, ocorrencia, payload.substituto, context, now)
        before = _data(original)
        original.estornado_em, original.estornado_por, original.motivo_estorno = now, context.user.id, payload.motivo.strip()
        # Flush do estorno antes do substituto libera o unique parcial.
        await _audit(db, original, context, request, "estornar", before)
        result = _data(original)
        if payload.substituto is not None:
            result["substituto"] = _data(await _record(
                db, ocorrencia, programacao, payload.substituto, context, request, now, original.id))
    return result


def _has_admin_vigente():
    return exists().where(
        m.Administracao.dose_prevista_id == m.DosePrevista.id,
        m.Administracao.ilpi_id == m.DosePrevista.ilpi_id,
        m.Administracao.estornado_em.is_(None),
    )


@plantao_router.get("/", response_model=list[s.PlantaoItem])
async def meu_plantao(a_partir_de: AwareDatetime | None = None, ate: AwareDatetime | None = None,
    residente_id: str | None = None, limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("plantao:ler"))):
    # PROJEÇÃO: nenhuma linha é criada ou duplicada aqui.
    now = _now()
    inicio = _utc(a_partir_de) if a_partir_de is not None else now
    fim = _utc(ate) if ate is not None else now + timedelta(hours=24)
    if fim <= inicio:
        _fail("Intervalo de plantao invalido", 422)
    if residente_id is not None:
        residente = (await db.execute(select(m.Residente).where(
            m.Residente.id == residente_id, m.Residente.instituicao_id == context.ilpi_id))).scalar_one_or_none()
        if residente is None:
            _missing()
    items: list[dict] = []
    ocorrencias = (await db.scalars(select(m.OcorrenciaCuidado).where(
        m.OcorrenciaCuidado.ilpi_id == context.ilpi_id,
        m.OcorrenciaCuidado.situacao == "prevista",
        m.OcorrenciaCuidado.previsto_em >= inicio, m.OcorrenciaCuidado.previsto_em < fim,
        ~_has_execucao_vigente(),
        *([m.OcorrenciaCuidado.residente_id == residente_id] if residente_id is not None else []),
    ).order_by(m.OcorrenciaCuidado.previsto_em, m.OcorrenciaCuidado.id).limit(limit))).all()
    programacoes = {row.id: row for row in (await db.scalars(select(m.ProgramacaoCuidado).where(
        m.ProgramacaoCuidado.ilpi_id == context.ilpi_id))).all()}
    intervencoes = {row.id: row for row in (await db.scalars(select(m.PaisIntervencao).where(
        m.PaisIntervencao.ilpi_id == context.ilpi_id))).all()}
    for ocorrencia in ocorrencias:
        programacao = programacoes.get(ocorrencia.programacao_id)
        intervencao = intervencoes.get(ocorrencia.intervencao_id)
        items.append({
            "origem": "cuidado",
            "registro_id": ocorrencia.id,
            "residente_id": ocorrencia.residente_id,
            "descricao": (intervencao.descricao if intervencao else "Cuidado programado"),
            "previsto_em": _utc(ocorrencia.previsto_em),
            "prioridade": programacao.prioridade if programacao else None,
        })
    doses = (await db.execute(select(m.DosePrevista, True).where(
        m.DosePrevista.ilpi_id == context.ilpi_id,
        m.DosePrevista.situacao == "prevista",
        m.DosePrevista.previsto_em >= inicio, m.DosePrevista.previsto_em < fim,
        ~_has_admin_vigente(),
        *([m.DosePrevista.residente_id == residente_id] if residente_id is not None else []),
    ).order_by(m.DosePrevista.previsto_em, m.DosePrevista.id).limit(limit))).all()
    for dose, _ in doses:
        items.append({
            "origem": "medicacao",
            "registro_id": dose.id,
            "residente_id": dose.residente_id,
            "descricao": "Dose prevista de medicacao",
            "previsto_em": _utc(dose.previsto_em),
            "prioridade": None,
        })
    abertas = (await db.scalars(select(m.Intercorrencia).where(
        m.Intercorrencia.ilpi_id == context.ilpi_id,
        m.Intercorrencia.situacao == "aberta",
        *([m.Intercorrencia.residente_id == residente_id] if residente_id is not None else []),
    ).order_by(m.Intercorrencia.data.desc(), m.Intercorrencia.id).limit(limit))).all()
    for intercorrencia in abertas:
        items.append({
            "origem": "intercorrencia",
            "registro_id": intercorrencia.id,
            "residente_id": intercorrencia.residente_id,
            "descricao": f"Intercorrencia aberta: {intercorrencia.tipo}",
            "previsto_em": None,
            "prioridade": None,
        })
    items.sort(key=lambda item: (item["previsto_em"] is None, item["previsto_em"] or now, item["registro_id"]))
    return items[:limit]
