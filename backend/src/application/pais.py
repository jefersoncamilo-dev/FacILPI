"""D.1: PAIS/Plano de Cuidados — fonte única, itens, revisão e versionamento.

Contrato de permissões (agrupadas em planos_cuidados, sem micropermissões
por filha):
  ler -> leitura; criar -> criar plano; atualizar -> edição de rascunho,
  itens e nova-versao; revisar -> revisar; aprovar -> aprovar e ativar;
  encerrar -> encerrar.

Sem automação clínica: avaliações, grau de dependência e intercorrências
são apenas referência/evidência (origem) mediante decisão humana; PAIS
não controla prescrição/medicação e não gera programação/tarefa.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure import models as m
from ..infrastructure.database import get_db
from . import schemas as s
from .audit import add_audit
from .security import RESOURCE_NOT_FOUND, SecurityContext, require_ilpi_context, require_permission


planos_router = APIRouter(prefix="/planos-cuidados", tags=["planos-cuidados"], dependencies=[Depends(require_ilpi_context)])

DRAFT_STATES = ("rascunho", "em_elaboracao")
PAIS_CONFLITO = "PAIS_CONFLITO"
PAIS_INVALIDO = "PAIS_INVALIDO"


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
    raise HTTPException(status_code=status, detail={"code": PAIS_CONFLITO if status == 409 else PAIS_INVALIDO, "message": message})


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
            "uq_planos_vigente_por_residente",
            "unique constraint failed: planos_cuidados.residente_id",
        ))
        sqlite_code = getattr(original, "sqlite_errorcode", 0) or 0
        lock_conflict = code in {"40001", "40P01", "55P03"} or (sqlite_code & 255) in {5, 6}
        if unique_conflict or lock_conflict:
            _fail("Conflito concorrente; recarregue o recurso antes de tentar novamente")
        raise
    except Exception:
        await db.rollback()
        raise


async def _ensure_residente(db, residente_id, context):
    parent = (await db.execute(select(m.Residente).where(
        m.Residente.id == residente_id,
        m.Residente.instituicao_id == context.ilpi_id,
    ))).scalar_one_or_none()
    if parent is None:
        _missing()
    return parent


async def _ensure_funcionario(db, funcionario_id, context, papel="profissional"):
    obj = (await db.execute(select(m.Funcionario).where(
        m.Funcionario.id == funcionario_id,
        m.Funcionario.ilpi_id == context.ilpi_id,
    ))).scalar_one_or_none()
    if obj is None:
        _missing()
    if obj.situacao != "ativo":
        _fail(f"{papel} inativo nao pode atuar no PAIS", 422)
    if obj.usuario_id is not None:
        user = (await db.execute(select(m.User).where(m.User.id == obj.usuario_id))).scalar_one_or_none()
        if user is None or not user.ativo:
            _fail(f"{papel} sem usuario/vinculo ativo", 422)
    return obj


async def _get_plano(db, plano_id, context):
    obj = (await db.execute(select(m.PlanoCuidados).where(
        m.PlanoCuidados.id == plano_id,
        m.PlanoCuidados.ilpi_id == context.ilpi_id,
    ).execution_options(populate_existing=True))).scalar_one_or_none()
    if obj is None:
        _missing()
    return obj


async def _lock_plano(db, plano_id, context):
    # Este UPDATE é o primeiro DML de toda transição clínica, nos dois engines.
    with db.no_autoflush:
        result = await db.execute(
            update(m.PlanoCuidados)
            .where(m.PlanoCuidados.id == plano_id, m.PlanoCuidados.ilpi_id == context.ilpi_id)
            .values(lock_version=m.PlanoCuidados.lock_version + 1)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            _missing()
        return await _get_plano(db, plano_id, context)


async def _audit(db, obj, context, request, action, before=None):
    await db.flush()
    add_audit(db, acao=f"{obj.__tablename__}.{action}", entidade=obj.__tablename__, registro_id=obj.id,
              usuario_id=context.user.id, ilpi_id=context.ilpi_id,
              valores_anteriores=before, valores_posteriores=_data(obj), request=request)


async def _plano_response(db, obj):
    result = _data(obj)
    for table, key in ((m.PaisNecessidade, "necessidades"), (m.PaisMeta, "metas"), (m.PaisIntervencao, "intervencoes")):
        rows = (await db.scalars(select(table).where(
            table.plano_id == obj.id, table.ilpi_id == obj.ilpi_id,
        ).order_by(table.created_at, table.id))).all()
        result[key] = [_data(row) for row in rows]
    return result


async def _validate_origem(db, payload, plano, context):
    # origem é referência/evidência: valida existência same-tenant+residente,
    # sem copiar dados e sem efeitos colaterais clínicos.
    if payload.origem == "manual":
        return
    ref = payload.referencia_id
    found = False
    if payload.origem == "avaliacao":
        found = (await db.execute(select(m.Avaliacao.id).where(
            m.Avaliacao.id == ref, m.Avaliacao.ilpi_id == context.ilpi_id,
            m.Avaliacao.residente_id == plano.residente_id))).scalar_one_or_none() is not None
    elif payload.origem == "grau_dependencia":
        # Fonte oficial: graus_dependencia ativo (nunca Residente.grau_dependencia).
        found = (await db.execute(select(m.GrauDependencia.id).where(
            m.GrauDependencia.id == ref, m.GrauDependencia.ilpi_id == context.ilpi_id,
            m.GrauDependencia.residente_id == plano.residente_id,
            m.GrauDependencia.situacao == "ativo"))).scalar_one_or_none() is not None
    elif payload.origem == "intercorrencia":
        found = (await db.execute(select(m.Intercorrencia.id).where(
            m.Intercorrencia.id == ref, m.Intercorrencia.ilpi_id == context.ilpi_id,
            m.Intercorrencia.residente_id == plano.residente_id))).scalar_one_or_none() is not None
    if not found:
        _fail("Evidencia de origem nao encontrada no tenant/residente", 422)


async def _require_draft(obj):
    if obj.situacao not in DRAFT_STATES:
        _fail("Plano fora de rascunho: altere via nova versao")


async def _completude(db, obj, context):
    counts = []
    for table in (m.PaisNecessidade, m.PaisMeta, m.PaisIntervencao):
        counts.append(await db.scalar(select(table.id).where(
            table.plano_id == obj.id, table.ilpi_id == context.ilpi_id,
            table.situacao == "ativa").limit(1)))
    if any(value is None for value in counts):
        _fail("PAIS incompleto: exige >= 1 necessidade, >= 1 meta e >= 1 intervencao ativas", 422)


@planos_router.get("/", response_model=list[s.PlanoCuidadosResponse])
async def listar_planos(residente_id: str | None = None, skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("planos_cuidados:ler"))):
    if residente_id is not None:
        await _ensure_residente(db, residente_id, context)
    query = select(m.PlanoCuidados).where(m.PlanoCuidados.ilpi_id == context.ilpi_id)
    if residente_id is not None:
        query = query.where(m.PlanoCuidados.residente_id == residente_id)
    objects = (await db.scalars(query.order_by(m.PlanoCuidados.created_at.desc(), m.PlanoCuidados.id).offset(skip).limit(limit))).all()
    return [await _plano_response(db, obj) for obj in objects]


@planos_router.get("/{id}", response_model=s.PlanoCuidadosResponse)
async def obter_plano(id: str, db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("planos_cuidados:ler"))):
    return await _plano_response(db, await _get_plano(db, id, context))


@planos_router.post("/", response_model=s.PlanoCuidadosResponse, status_code=201)
async def criar_plano(payload: s.PlanoCuidadosCreate, request: Request, db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("planos_cuidados:criar"))):
    async with _write(db):
        await _ensure_residente(db, payload.residente_id, context)
        obj = m.PlanoCuidados(**payload.model_dump(), ilpi_id=context.ilpi_id,
                              autor_id=context.user.id, versao=1, situacao="rascunho")
        db.add(obj)
        await _audit(db, obj, context, request, "criar")
        result = await _plano_response(db, obj)
    return result


@planos_router.patch("/{id}", response_model=s.PlanoCuidadosResponse)
async def atualizar_plano(id: str, payload: s.PlanoCuidadosPatch, request: Request,
    db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("planos_cuidados:atualizar"))):
    async with _write(db):
        obj = await _lock_plano(db, id, context)
        await _require_draft(obj)
        changes = payload.model_dump(exclude_unset=True)
        if "situacao" in changes:
            if obj.situacao != "rascunho":
                _fail("Transicao de plano nao permitida")
            obj.situacao = "em_elaboracao"
            del changes["situacao"]
        if "data_final" in changes or "data_inicial" in changes:
            inicio = changes.get("data_inicial", obj.data_inicial)
            fim = changes.get("data_final", obj.data_final)
            if fim is not None and inicio is not None and fim < inicio:
                _fail("data_final anterior a data_inicial", 422)
        before = _data(obj)
        for key, value in changes.items():
            setattr(obj, key, value)
        await _audit(db, obj, context, request, "atualizar", before)
        result = await _plano_response(db, obj)
    return result


@planos_router.post("/{id}/revisar", response_model=s.PlanoCuidadosResponse)
async def revisar_plano(id: str, payload: s.FuncionarioRef, request: Request,
    db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("planos_cuidados:revisar"))):
    async with _write(db):
        obj = await _lock_plano(db, id, context)
        if obj.situacao != "em_elaboracao":
            _fail("Somente plano em elaboracao pode ser revisado")
        await _ensure_funcionario(db, payload.funcionario_id, context, "revisor")
        before = _data(obj)
        obj.situacao, obj.revisor_funcionario_id, obj.revisado_em = "em_revisao", payload.funcionario_id, _now()
        await _audit(db, obj, context, request, "revisar", before)
        result = await _plano_response(db, obj)
    return result


@planos_router.post("/{id}/aprovar", response_model=s.PlanoCuidadosResponse)
async def aprovar_plano(id: str, payload: s.FuncionarioRef, request: Request,
    db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("planos_cuidados:aprovar"))):
    async with _write(db):
        obj = await _lock_plano(db, id, context)
        if obj.situacao != "em_revisao":
            _fail("Somente plano em revisao pode ser aprovado")
        await _ensure_funcionario(db, payload.funcionario_id, context, "aprovador")
        await _completude(db, obj, context)
        before = _data(obj)
        obj.situacao, obj.aprovador_funcionario_id, obj.aprovado_em = "aprovado", payload.funcionario_id, _now()
        await _audit(db, obj, context, request, "aprovar", before)
        result = await _plano_response(db, obj)
    return result


@planos_router.post("/{id}/ativar", response_model=s.PlanoCuidadosResponse)
async def ativar_plano(id: str, request: Request,
    db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("planos_cuidados:aprovar"))):
    async with _write(db):
        obj = await _lock_plano(db, id, context)
        if obj.situacao != "aprovado":
            _fail("Somente plano aprovado pode entrar em vigencia")
        vigente = (await db.execute(select(m.PlanoCuidados.id).where(
            m.PlanoCuidados.ilpi_id == context.ilpi_id,
            m.PlanoCuidados.residente_id == obj.residente_id,
            m.PlanoCuidados.situacao == "vigente",
        ).execution_options(populate_existing=True))).scalar_one_or_none()
        if vigente is not None:
            _fail("Residente ja possui PAIS vigente")
        before = _data(obj)
        obj.situacao = "vigente"
        await _audit(db, obj, context, request, "ativar", before)
        if obj.anterior_id is not None:
            anterior = await _get_plano(db, obj.anterior_id, context)
            if anterior.situacao in ("aprovado", "vigente"):
                before_ant = _data(anterior)
                anterior.situacao, anterior.superseded_by = "substituido", obj.id
                await _audit(db, anterior, context, request, "substituir", before_ant)
        result = await _plano_response(db, obj)
    return result


@planos_router.post("/{id}/nova-versao", response_model=s.PlanoCuidadosResponse, status_code=201)
async def nova_versao_plano(id: str, payload: s.NovaVersao, request: Request,
    db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("planos_cuidados:atualizar"))):
    async with _write(db):
        obj = await _lock_plano(db, id, context)
        if obj.situacao not in ("aprovado", "vigente"):
            _fail("Nova versao exige plano aprovado ou vigente")
        successor = await db.scalar(select(m.PlanoCuidados.id).where(
            m.PlanoCuidados.anterior_id == obj.id, m.PlanoCuidados.ilpi_id == context.ilpi_id))
        if successor is not None:
            _fail("Versao ja possui sucessora; bifurcacao bloqueada")
        new = m.PlanoCuidados(
            residente_id=obj.residente_id, ilpi_id=context.ilpi_id, autor_id=context.user.id,
            versao=obj.versao + 1, situacao="rascunho", data_inicial=obj.data_inicial,
            data_final=obj.data_final, objetivos=obj.objetivos,
            anterior_id=obj.id, motivo_versao=payload.motivo.strip(),
        )
        db.add(new)
        await db.flush()
        remap = {}
        for table, extra in ((m.PaisNecessidade, ("categoria", "descricao", "gravidade", "evidencias", "origem")),
                             (m.PaisMeta, ("descricao", "indicador", "valor_esperado", "prazo", "responsavel_funcionario_id")),
                             (m.PaisIntervencao, ("descricao", "frequencia", "horario", "perfil_responsavel", "profissional_designado_id", "prioridade", "instrucoes", "necessidade_id"))):
            rows = (await db.scalars(select(table).where(
                table.plano_id == obj.id, table.ilpi_id == context.ilpi_id,
                table.situacao == "ativa"))).all()
            for row in rows:
                values = {key: getattr(row, key) for key in extra if key != "necessidade_id"}
                values.update(ilpi_id=context.ilpi_id, plano_id=new.id, situacao="ativa")
                if table is m.PaisIntervencao and row.necessidade_id is not None:
                    values["necessidade_id"] = remap.get(row.necessidade_id)
                clone = table(**values)
                db.add(clone)
                await db.flush()
                remap[row.id] = clone.id
                await _audit(db, clone, context, request, "copiar-versao")
        await _audit(db, new, context, request, "nova-versao", {"anterior_id": obj.id})
        result = await _plano_response(db, new)
    return result


@planos_router.post("/{id}/encerrar", response_model=s.PlanoCuidadosResponse)
async def encerrar_plano(id: str, payload: s.MotivoEncerramento, request: Request,
    db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("planos_cuidados:encerrar"))):
    async with _write(db):
        obj = await _lock_plano(db, id, context)
        if obj.situacao != "vigente":
            _fail("Somente plano vigente pode ser encerrado")
        await _ensure_funcionario(db, payload.funcionario_id, context, "responsavel")
        before = _data(obj)
        obj.situacao, obj.motivo_encerramento, obj.encerrado_em = "encerrado", payload.motivo.strip(), _now()
        await _audit(db, obj, context, request, "encerrar", before)
        result = await _plano_response(db, obj)
    return result


async def _get_item(db, table, item_id, plano, context):
    obj = (await db.execute(select(table).where(
        table.id == item_id, table.plano_id == plano.id,
        table.ilpi_id == context.ilpi_id,
    ).execution_options(populate_existing=True))).scalar_one_or_none()
    if obj is None:
        _missing()
    return obj


@planos_router.get("/{id}/necessidades", response_model=list[s.NecessidadeResponse])
async def listar_necessidades(id: str, db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("planos_cuidados:ler"))):
    plano = await _get_plano(db, id, context)
    return (await db.scalars(select(m.PaisNecessidade).where(
        m.PaisNecessidade.plano_id == plano.id,
        m.PaisNecessidade.ilpi_id == context.ilpi_id,
    ).order_by(m.PaisNecessidade.created_at, m.PaisNecessidade.id))).all()


@planos_router.post("/{id}/necessidades", response_model=s.NecessidadeResponse, status_code=201)
async def criar_necessidade(id: str, payload: s.NecessidadeCreate, request: Request,
    db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("planos_cuidados:atualizar"))):
    async with _write(db):
        plano = await _lock_plano(db, id, context)
        await _require_draft(plano)
        await _validate_origem(db, payload, plano, context)
        values = payload.model_dump()
        values.pop("referencia_id", None)
        obj = m.PaisNecessidade(**values, ilpi_id=context.ilpi_id, plano_id=plano.id, situacao="ativa")
        db.add(obj)
        await _audit(db, obj, context, request, "criar")
        result = _data(obj)
    return result


@planos_router.patch("/{id}/necessidades/{nid}", response_model=s.NecessidadeResponse)
async def atualizar_necessidade(id: str, nid: str, payload: s.NecessidadePatch, request: Request,
    db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("planos_cuidados:atualizar"))):
    async with _write(db):
        plano = await _lock_plano(db, id, context)
        await _require_draft(plano)
        obj = await _get_item(db, m.PaisNecessidade, nid, plano, context)
        before = _data(obj)
        for key, value in payload.model_dump(exclude_unset=True).items():
            setattr(obj, key, value)
        await _audit(db, obj, context, request, "atualizar", before)
        result = _data(obj)
    return result


@planos_router.get("/{id}/metas", response_model=list[s.MetaResponse])
async def listar_metas(id: str, db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("planos_cuidados:ler"))):
    plano = await _get_plano(db, id, context)
    return (await db.scalars(select(m.PaisMeta).where(
        m.PaisMeta.plano_id == plano.id, m.PaisMeta.ilpi_id == context.ilpi_id,
    ).order_by(m.PaisMeta.created_at, m.PaisMeta.id))).all()


@planos_router.post("/{id}/metas", response_model=s.MetaResponse, status_code=201)
async def criar_meta(id: str, payload: s.MetaCreate, request: Request,
    db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("planos_cuidados:atualizar"))):
    async with _write(db):
        plano = await _lock_plano(db, id, context)
        await _require_draft(plano)
        if payload.responsavel_funcionario_id is not None:
            await _ensure_funcionario(db, payload.responsavel_funcionario_id, context, "responsavel")
        obj = m.PaisMeta(**payload.model_dump(), ilpi_id=context.ilpi_id, plano_id=plano.id, situacao="ativa")
        db.add(obj)
        await _audit(db, obj, context, request, "criar")
        result = _data(obj)
    return result


@planos_router.patch("/{id}/metas/{mid}", response_model=s.MetaResponse)
async def atualizar_meta(id: str, mid: str, payload: s.MetaPatch, request: Request,
    db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("planos_cuidados:atualizar"))):
    async with _write(db):
        plano = await _lock_plano(db, id, context)
        await _require_draft(plano)
        obj = await _get_item(db, m.PaisMeta, mid, plano, context)
        changes = payload.model_dump(exclude_unset=True)
        if "responsavel_funcionario_id" in changes and changes["responsavel_funcionario_id"] is not None:
            await _ensure_funcionario(db, changes["responsavel_funcionario_id"], context, "responsavel")
        before = _data(obj)
        for key, value in changes.items():
            setattr(obj, key, value)
        await _audit(db, obj, context, request, "atualizar", before)
        result = _data(obj)
    return result


@planos_router.get("/{id}/intervencoes", response_model=list[s.IntervencaoResponse])
async def listar_intervencoes(id: str, db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("planos_cuidados:ler"))):
    plano = await _get_plano(db, id, context)
    return (await db.scalars(select(m.PaisIntervencao).where(
        m.PaisIntervencao.plano_id == plano.id, m.PaisIntervencao.ilpi_id == context.ilpi_id,
    ).order_by(m.PaisIntervencao.created_at, m.PaisIntervencao.id))).all()


@planos_router.post("/{id}/intervencoes", response_model=s.IntervencaoResponse, status_code=201)
async def criar_intervencao(id: str, payload: s.IntervencaoCreate, request: Request,
    db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("planos_cuidados:atualizar"))):
    async with _write(db):
        plano = await _lock_plano(db, id, context)
        await _require_draft(plano)
        if payload.necessidade_id is not None:
            await _get_item(db, m.PaisNecessidade, payload.necessidade_id, plano, context)
        if payload.profissional_designado_id is not None:
            await _ensure_funcionario(db, payload.profissional_designado_id, context, "profissional")
        obj = m.PaisIntervencao(**payload.model_dump(), ilpi_id=context.ilpi_id, plano_id=plano.id, situacao="ativa")
        db.add(obj)
        await _audit(db, obj, context, request, "criar")
        result = _data(obj)
    return result


@planos_router.patch("/{id}/intervencoes/{iid}", response_model=s.IntervencaoResponse)
async def atualizar_intervencao(id: str, iid: str, payload: s.IntervencaoPatch, request: Request,
    db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("planos_cuidados:atualizar"))):
    async with _write(db):
        plano = await _lock_plano(db, id, context)
        await _require_draft(plano)
        obj = await _get_item(db, m.PaisIntervencao, iid, plano, context)
        changes = payload.model_dump(exclude_unset=True)
        if "necessidade_id" in changes and changes["necessidade_id"] is not None:
            await _get_item(db, m.PaisNecessidade, changes["necessidade_id"], plano, context)
        if "profissional_designado_id" in changes and changes["profissional_designado_id"] is not None:
            await _ensure_funcionario(db, changes["profissional_designado_id"], context, "profissional")
        before = _data(obj)
        for key, value in changes.items():
            setattr(obj, key, value)
        await _audit(db, obj, context, request, "atualizar", before)
        result = _data(obj)
    return result
