"""Complementares D5: agenda, multidisciplinar, PIA, estoque e mensalidades.

Tenant e autoria vem sempre da sessao; id de outra ILPI devolve o mesmo 404 de id
inexistente. Nada aqui decide algo clinico nem dispara automacao entre modulos:
estoque nao baixa com dose, e mensalidade nao cobra nem envia mensagem.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure import models as m
from ..infrastructure.database import get_db
from .audit import add_audit
from .security import RESOURCE_NOT_FOUND, SecurityContext, allowed_permission_keys, require_ilpi_context, require_permission

agenda_router = APIRouter(prefix="/agenda", tags=["agenda"])
multidisciplinar_router = APIRouter(prefix="/multidisciplinar", tags=["multidisciplinar"])
pia_router = APIRouter(prefix="/pia", tags=["pia"])
estoque_router = APIRouter(prefix="/estoque", tags=["estoque"])
financeiro_router = APIRouter(prefix="/financeiro", tags=["financeiro"])

Area = Literal["fisioterapia", "nutricao", "psicologia", "servico_social", "enfermagem"]
Texto = Field(min_length=1)


def _404():
    return HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})


def _409(mensagem: str):
    return HTTPException(status_code=409, detail={"code": "CONFLITO", "message": mensagem})


async def _residente(db: AsyncSession, context: SecurityContext, residente_id: str) -> None:
    achou = await db.scalar(select(m.Residente.id).where(
        m.Residente.id == residente_id, m.Residente.instituicao_id == context.ilpi_id))
    if achou is None:
        raise _404()


async def _do_tenant(db: AsyncSession, modelo, item_id: str, context: SecurityContext):
    obj = await db.scalar(select(modelo).where(modelo.id == item_id, modelo.ilpi_id == context.ilpi_id))
    if obj is None:
        raise _404()
    return obj


def _audit(db, request, context, acao, entidade, registro_id, depois=None):
    add_audit(db, acao=acao, entidade=entidade, registro_id=registro_id, usuario_id=context.user.id,
              ilpi_id=context.ilpi_id, valores_posteriores=depois, request=request)


class _Saida(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Agenda ----------
class EventoNovo(BaseModel):
    residente_id: str
    motivo: str = Field(min_length=1, max_length=255)
    especialidade: Optional[str] = Field(None, max_length=100)
    profissional: Optional[str] = Field(None, max_length=255)
    local: Optional[str] = Field(None, max_length=255)
    inicio_em: datetime


class EventoSaida(_Saida):
    id: str
    residente_id: str
    motivo: str
    especialidade: Optional[str] = None
    profissional: Optional[str] = None
    local: Optional[str] = None
    inicio_em: datetime
    situacao: str
    resultado: Optional[str] = None
    motivo_cancelamento: Optional[str] = None


class TextoObrigatorio(BaseModel):
    texto: str = Texto


@agenda_router.get("/", response_model=list[EventoSaida])
async def listar_agenda(
    residente_id: Optional[str] = None, de: Optional[datetime] = None, ate: Optional[datetime] = None,
    db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("agenda:ler")),
):
    q = select(m.AgendaEvento).where(m.AgendaEvento.ilpi_id == context.ilpi_id)
    if residente_id:
        q = q.where(m.AgendaEvento.residente_id == residente_id)
    if de:
        q = q.where(m.AgendaEvento.inicio_em >= de)
    if ate:
        q = q.where(m.AgendaEvento.inicio_em <= ate)
    return (await db.scalars(q.order_by(m.AgendaEvento.inicio_em, m.AgendaEvento.id).limit(500))).all()


@agenda_router.post("/", response_model=EventoSaida, status_code=201)
async def criar_evento(payload: EventoNovo, request: Request, db: AsyncSession = Depends(get_db),
                       context: SecurityContext = Depends(require_permission("agenda:gerenciar"))):
    await _residente(db, context, payload.residente_id)
    obj = m.AgendaEvento(**payload.model_dump(), ilpi_id=context.ilpi_id, autor_id=context.user.id)
    db.add(obj)
    await db.flush()
    _audit(db, request, context, "agenda.criado", "agenda_eventos", obj.id)
    await db.commit()
    return obj


async def _fechar_evento(db, request, context, item_id, situacao, campo, texto):
    obj = await _do_tenant(db, m.AgendaEvento, item_id, context)
    if obj.situacao != "agendado":
        raise _409("Este agendamento já foi encerrado.")
    obj.situacao = situacao
    setattr(obj, campo, texto)
    _audit(db, request, context, f"agenda.{situacao}", "agenda_eventos", obj.id)
    await db.commit()
    return obj


@agenda_router.post("/{item_id}/concluir", response_model=EventoSaida)
async def concluir_evento(item_id: str, payload: TextoObrigatorio, request: Request, db: AsyncSession = Depends(get_db),
                          context: SecurityContext = Depends(require_permission("agenda:gerenciar"))):
    return await _fechar_evento(db, request, context, item_id, "realizado", "resultado", payload.texto)


@agenda_router.post("/{item_id}/cancelar", response_model=EventoSaida)
async def cancelar_evento(item_id: str, payload: TextoObrigatorio, request: Request, db: AsyncSession = Depends(get_db),
                          context: SecurityContext = Depends(require_permission("agenda:gerenciar"))):
    return await _fechar_evento(db, request, context, item_id, "cancelado", "motivo_cancelamento", payload.texto)


# ---------- Multidisciplinar ----------
class AtendimentoNovo(BaseModel):
    residente_id: str
    ocorrido_em: datetime
    evolucao: str = Texto


class AtendimentoSaida(_Saida):
    id: str
    residente_id: str
    area: str
    ocorrido_em: datetime
    evolucao: str
    autor_id: str
    autor_nome: str
    estornado_em: Optional[datetime] = None
    motivo_estorno: Optional[str] = None


async def _exigir_area(db, context, area: str, acao: str) -> None:
    if f"multidisciplinar.{area}:{acao}" not in await allowed_permission_keys(db, context):
        raise HTTPException(status_code=403, detail={"code": "PERMISSION_DENIED", "message": "Sem acesso a esta área."})


@multidisciplinar_router.get("/{area}", response_model=list[AtendimentoSaida])
async def listar_atendimentos(area: Area, residente_id: Optional[str] = None, db: AsyncSession = Depends(get_db),
                              context: SecurityContext = Depends(require_ilpi_context)):
    await _exigir_area(db, context, area, "ler")
    q = select(m.AtendimentoMultidisciplinar).where(
        m.AtendimentoMultidisciplinar.ilpi_id == context.ilpi_id, m.AtendimentoMultidisciplinar.area == area)
    if residente_id:
        q = q.where(m.AtendimentoMultidisciplinar.residente_id == residente_id)
    return (await db.scalars(q.order_by(m.AtendimentoMultidisciplinar.ocorrido_em.desc(), m.AtendimentoMultidisciplinar.id).limit(500))).all()


@multidisciplinar_router.post("/{area}", response_model=AtendimentoSaida, status_code=201)
async def registrar_atendimento(area: Area, payload: AtendimentoNovo, request: Request, db: AsyncSession = Depends(get_db),
                                context: SecurityContext = Depends(require_ilpi_context)):
    await _exigir_area(db, context, area, "registrar")
    await _residente(db, context, payload.residente_id)
    obj = m.AtendimentoMultidisciplinar(**payload.model_dump(), area=area, ilpi_id=context.ilpi_id,
                                        autor_id=context.user.id, autor_nome=context.user.nome)
    db.add(obj)
    await db.flush()
    _audit(db, request, context, "atendimento.registrado", "atendimentos_multidisciplinares", obj.id, {"area": area})
    await db.commit()
    return obj


@multidisciplinar_router.post("/{area}/{item_id}/estornar", response_model=AtendimentoSaida)
async def estornar_atendimento(area: Area, item_id: str, payload: TextoObrigatorio, request: Request,
                               db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_ilpi_context)):
    await _exigir_area(db, context, area, "registrar")
    obj = await _do_tenant(db, m.AtendimentoMultidisciplinar, item_id, context)
    if obj.area != area:
        raise _404()
    if obj.estornado_em is not None:
        raise _409("Este atendimento já foi estornado.")
    obj.estornado_em, obj.estornado_por, obj.motivo_estorno = datetime.now(timezone.utc), context.user.id, payload.texto
    _audit(db, request, context, "atendimento.estornado", "atendimentos_multidisciplinares", obj.id)
    await db.commit()
    return obj


# ---------- PIA ----------
class PiaNovo(BaseModel):
    informacoes_gerais: Optional[str] = None
    institucionalizacao: Optional[str] = None
    habitos_interesses: Optional[str] = None
    apoio_social: Optional[str] = None
    financas: Optional[str] = None
    historico_saude: Optional[str] = None
    planejamento_individual: Optional[str] = None


class PiaSaida(PiaNovo, _Saida):
    id: str
    residente_id: str
    versao: int
    autor_nome: str
    created_at: datetime


@pia_router.get("/{residente_id}", response_model=list[PiaSaida])
async def versoes_pia(residente_id: str, db: AsyncSession = Depends(get_db),
                      context: SecurityContext = Depends(require_permission("pia:ler"))):
    """Versoes do PIA, da vigente para a mais antiga."""
    await _residente(db, context, residente_id)
    return (await db.scalars(select(m.PiaVersao).where(
        m.PiaVersao.ilpi_id == context.ilpi_id, m.PiaVersao.residente_id == residente_id
    ).order_by(m.PiaVersao.versao.desc()))).all()


@pia_router.post("/{residente_id}", response_model=PiaSaida, status_code=201)
async def nova_versao_pia(residente_id: str, payload: PiaNovo, request: Request, db: AsyncSession = Depends(get_db),
                          context: SecurityContext = Depends(require_permission("pia:registrar"))):
    await _residente(db, context, residente_id)
    atual = await db.scalar(select(func.max(m.PiaVersao.versao)).where(
        m.PiaVersao.ilpi_id == context.ilpi_id, m.PiaVersao.residente_id == residente_id))
    obj = m.PiaVersao(**payload.model_dump(), residente_id=residente_id, ilpi_id=context.ilpi_id, versao=(atual or 0) + 1,
                      autor_id=context.user.id, autor_nome=context.user.nome)
    db.add(obj)
    await db.flush()
    _audit(db, request, context, "pia.versao_criada", "pia_versoes", obj.id, {"versao": obj.versao})
    await db.commit()
    await db.refresh(obj)
    return obj


# ---------- Farmacia e estoque ----------
class ItemNovo(BaseModel):
    nome: str = Field(min_length=1, max_length=255)
    categoria: Optional[str] = Field(None, max_length=100)
    unidade: str = Field(min_length=1, max_length=50)
    estoque_minimo: int = Field(0, ge=0)
    localizacao: Optional[str] = Field(None, max_length=255)


class LoteSaldo(BaseModel):
    lote: Optional[str] = None
    validade: Optional[date] = None
    saldo: int


class ItemSaida(ItemNovo):
    id: str
    saldo: int
    abaixo_do_minimo: bool
    lotes: list[LoteSaldo]


class MovimentoNovo(BaseModel):
    tipo: Literal["entrada", "saida"]
    quantidade: int = Field(gt=0)
    lote: Optional[str] = Field(None, max_length=50)
    validade: Optional[date] = None
    residente_id: Optional[str] = None
    motivo: Optional[str] = None


class MovimentoSaida(_Saida):
    id: str
    item_id: str
    tipo: str
    quantidade: int
    lote: Optional[str] = None
    validade: Optional[date] = None
    residente_id: Optional[str] = None
    motivo: Optional[str] = None
    autor_id: str
    created_at: datetime


_SINAL = case((m.EstoqueMovimento.tipo == "entrada", m.EstoqueMovimento.quantidade), else_=-m.EstoqueMovimento.quantidade)


async def _lotes(db, context, item_ids=None):
    q = select(m.EstoqueMovimento.item_id, m.EstoqueMovimento.lote, func.max(m.EstoqueMovimento.validade), func.sum(_SINAL)).where(
        m.EstoqueMovimento.ilpi_id == context.ilpi_id)
    if item_ids is not None:
        q = q.where(m.EstoqueMovimento.item_id.in_(item_ids))
    por_item: dict[str, list[LoteSaldo]] = {}
    for item, lote, validade, saldo in (await db.execute(q.group_by(m.EstoqueMovimento.item_id, m.EstoqueMovimento.lote))).all():
        por_item.setdefault(item, []).append(LoteSaldo(lote=lote, validade=validade, saldo=saldo))
    return por_item


def _item_saida(item, lotes) -> ItemSaida:
    saldo = sum(x.saldo for x in lotes)
    return ItemSaida(id=item.id, nome=item.nome, categoria=item.categoria, unidade=item.unidade, estoque_minimo=item.estoque_minimo,
                     localizacao=item.localizacao, saldo=saldo, abaixo_do_minimo=saldo < item.estoque_minimo,
                     lotes=[x for x in lotes if x.saldo > 0])


@estoque_router.get("/itens", response_model=list[ItemSaida])
async def listar_itens(db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("estoque:ler"))):
    itens = (await db.scalars(select(m.EstoqueItem).where(m.EstoqueItem.ilpi_id == context.ilpi_id).order_by(m.EstoqueItem.nome))).all()
    lotes = await _lotes(db, context)
    return [_item_saida(i, lotes.get(i.id, [])) for i in itens]


@estoque_router.post("/itens", response_model=ItemSaida, status_code=201)
async def criar_item(payload: ItemNovo, request: Request, db: AsyncSession = Depends(get_db),
                     context: SecurityContext = Depends(require_permission("estoque:movimentar"))):
    if await db.scalar(select(m.EstoqueItem.id).where(m.EstoqueItem.ilpi_id == context.ilpi_id, m.EstoqueItem.nome == payload.nome)):
        raise _409("Já existe um item com este nome.")
    obj = m.EstoqueItem(**payload.model_dump(), ilpi_id=context.ilpi_id, autor_id=context.user.id)
    db.add(obj)
    await db.flush()
    _audit(db, request, context, "estoque.item_criado", "estoque_itens", obj.id)
    await db.commit()
    return _item_saida(obj, [])


@estoque_router.get("/itens/{item_id}/movimentos", response_model=list[MovimentoSaida])
async def listar_movimentos(item_id: str, db: AsyncSession = Depends(get_db),
                            context: SecurityContext = Depends(require_permission("estoque:ler"))):
    await _do_tenant(db, m.EstoqueItem, item_id, context)
    return (await db.scalars(select(m.EstoqueMovimento).where(
        m.EstoqueMovimento.ilpi_id == context.ilpi_id, m.EstoqueMovimento.item_id == item_id
    ).order_by(m.EstoqueMovimento.created_at.desc(), m.EstoqueMovimento.id).limit(500))).all()


@estoque_router.post("/itens/{item_id}/movimentos", response_model=MovimentoSaida, status_code=201)
async def movimentar(item_id: str, payload: MovimentoNovo, request: Request, db: AsyncSession = Depends(get_db),
                     context: SecurityContext = Depends(require_permission("estoque:movimentar"))):
    await _do_tenant(db, m.EstoqueItem, item_id, context)
    if payload.residente_id:
        await _residente(db, context, payload.residente_id)
    if payload.tipo == "saida":
        if not (payload.motivo or "").strip():
            raise HTTPException(status_code=422, detail="Informe o motivo da saída.")
        lotes = (await _lotes(db, context, [item_id])).get(item_id, [])
        disponivel = sum(x.saldo for x in lotes if x.lote == payload.lote)
        if payload.quantidade > disponivel:
            raise _409(f"Saldo insuficiente neste lote: {disponivel}.")
    obj = m.EstoqueMovimento(**payload.model_dump(), item_id=item_id, ilpi_id=context.ilpi_id, autor_id=context.user.id)
    db.add(obj)
    await db.flush()
    _audit(db, request, context, f"estoque.{payload.tipo}", "estoque_movimentos", obj.id, {"quantidade": payload.quantidade})
    await db.commit()
    await db.refresh(obj)
    return obj


# ---------- Financeiro: controle manual de mensalidades ----------
class MensalidadeNova(BaseModel):
    residente_id: str
    competencia: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    valor_centavos: int = Field(gt=0)
    vencimento: date
    observacao: Optional[str] = None


class PagamentoNovo(BaseModel):
    pago_em: date


class MensalidadeSaida(_Saida):
    id: str
    residente_id: str
    competencia: str
    valor_centavos: int
    vencimento: date
    situacao: str
    pago_em: Optional[date] = None
    observacao: Optional[str] = None


@financeiro_router.get("/mensalidades", response_model=list[MensalidadeSaida])
async def listar_mensalidades(competencia: Optional[str] = Query(None, max_length=7), residente_id: Optional[str] = None,
                              db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_permission("financeiro:ler"))):
    q = select(m.Mensalidade).where(m.Mensalidade.ilpi_id == context.ilpi_id)
    if competencia:
        q = q.where(m.Mensalidade.competencia == competencia)
    if residente_id:
        q = q.where(m.Mensalidade.residente_id == residente_id)
    return (await db.scalars(q.order_by(m.Mensalidade.vencimento.desc(), m.Mensalidade.id).limit(500))).all()


@financeiro_router.post("/mensalidades", response_model=MensalidadeSaida, status_code=201)
async def lancar_mensalidade(payload: MensalidadeNova, request: Request, db: AsyncSession = Depends(get_db),
                             context: SecurityContext = Depends(require_permission("financeiro:gerenciar"))):
    await _residente(db, context, payload.residente_id)
    if await db.scalar(select(m.Mensalidade.id).where(
            m.Mensalidade.residente_id == payload.residente_id, m.Mensalidade.competencia == payload.competencia,
            m.Mensalidade.situacao != "cancelada")):
        raise _409("Este residente já tem mensalidade nesta competência.")
    obj = m.Mensalidade(**payload.model_dump(), ilpi_id=context.ilpi_id, autor_id=context.user.id)
    db.add(obj)
    await db.flush()
    _audit(db, request, context, "mensalidade.lancada", "mensalidades", obj.id, {"competencia": payload.competencia})
    await db.commit()
    await db.refresh(obj)
    return obj


@financeiro_router.post("/mensalidades/{item_id}/pagar", response_model=MensalidadeSaida)
async def pagar_mensalidade(item_id: str, payload: PagamentoNovo, request: Request, db: AsyncSession = Depends(get_db),
                            context: SecurityContext = Depends(require_permission("financeiro:gerenciar"))):
    obj = await _do_tenant(db, m.Mensalidade, item_id, context)
    if obj.situacao != "aberta":
        raise _409("Só mensalidade em aberto pode ser paga.")
    obj.situacao, obj.pago_em = "paga", payload.pago_em
    _audit(db, request, context, "mensalidade.paga", "mensalidades", obj.id)
    await db.commit()
    return obj


@financeiro_router.post("/mensalidades/{item_id}/cancelar", response_model=MensalidadeSaida)
async def cancelar_mensalidade(item_id: str, payload: TextoObrigatorio, request: Request, db: AsyncSession = Depends(get_db),
                               context: SecurityContext = Depends(require_permission("financeiro:gerenciar"))):
    obj = await _do_tenant(db, m.Mensalidade, item_id, context)
    if obj.situacao == "cancelada":
        raise _409("Esta mensalidade já foi cancelada.")
    obj.situacao, obj.observacao = "cancelada", payload.texto
    _audit(db, request, context, "mensalidade.cancelada", "mensalidades", obj.id)
    await db.commit()
    return obj
