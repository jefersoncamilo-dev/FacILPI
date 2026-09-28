"""Camada Operacional, Fase 2A (#120): areas, turnos, plantao real e responsabilidade.

O FacILPI passa a saber QUEM responde POR QUE area AGORA — e quem respondia
em qualquer instante do passado — sem misturar isso com permissao:

- RBAC responde "o que este usuario pode acessar"; nada aqui concede acesso.
- Responsabilidade responde "pelo que este profissional responde neste
  plantao"; e append-only (so ``fim_em`` e gravado, uma vez). Trocar o
  responsavel encerra uma vigencia e abre outra no mesmo instante.
- Residentes de uma area derivam da ocupacao atual dos leitos da area
  (``QuartoLeito.residente_atual_id``): fonte unica, sem copia.

Tenant sempre da sessao; recurso de outra ILPI responde 404. Toda mutacao e
auditada. Nao e RH: sem folha, ponto ou banco de horas.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure import models as m
from ..infrastructure.database import get_db
from .alertas import _fuso
from .audit import add_audit
from .rotina import _data, _utc
from .security import RESOURCE_NOT_FOUND, SecurityContext, allowed_permission_keys, require_ilpi_context, require_permission

escala_router = APIRouter(prefix="/escala", tags=["escala"], dependencies=[Depends(require_ilpi_context)])
plantoes_router = APIRouter(prefix="/plantoes", tags=["plantoes"], dependencies=[Depends(require_ilpi_context)])

OPERACAO_CONFLITO = "OPERACAO_CONFLITO"
OPERACAO_INVALIDA = "OPERACAO_INVALIDA"
_HORA = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
TipoArea = Literal["ala", "setor", "unidade", "grupo"]


# ---------------------------------------------------------------- schemas ----

def _hora(valor: str) -> str:
    if not _HORA.match(valor or ""):
        raise ValueError("Use o formato HH:MM (ex.: 07:00)")
    return valor


class AreaCriar(BaseModel):
    nome: str = Field(..., min_length=1, max_length=100)
    tipo: TipoArea = "ala"
    descricao: Optional[str] = Field(None, max_length=500)

    @field_validator("nome")
    @classmethod
    def _nome(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Informe o nome da área")
        return v


class AreaAtualizar(BaseModel):
    nome: Optional[str] = Field(None, min_length=1, max_length=100)
    tipo: Optional[TipoArea] = None
    descricao: Optional[str] = Field(None, max_length=500)
    situacao: Optional[Literal["ativa", "inativa"]] = None

    @field_validator("nome")
    @classmethod
    def _nome(cls, v):
        if v is not None and not v.strip():
            raise ValueError("Informe o nome da área")
        return v.strip() if v is not None else v

    @model_validator(mode="after")
    def _sem_nulo_obrigatorio(self):
        # null explicito so vale para descricao; nome/tipo/situacao sao obrigatorios na area.
        for campo in ("nome", "tipo", "situacao"):
            if campo in self.model_fields_set and getattr(self, campo) is None:
                raise ValueError(f"{campo} não pode ser vazio")
        return self


class LeitoDaArea(BaseModel):
    vinculo_id: str
    quarto_leito_id: str
    unidade: Optional[str] = None
    quarto: str
    leito: str
    # Ocupacao e dado de leitos/residentes: nula para quem so le a escala.
    ocupado: Optional[bool] = None
    desde: datetime


class AreaResposta(BaseModel):
    id: str
    nome: str
    tipo: str
    descricao: Optional[str] = None
    situacao: str
    leitos: list[LeitoDaArea] = []


class VincularLeito(BaseModel):
    quarto_leito_id: str


class TurnoCriar(BaseModel):
    nome: str = Field(..., min_length=1, max_length=60)
    hora_inicio: str
    hora_fim: str

    @field_validator("nome")
    @classmethod
    def _nome(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Informe o nome do turno")
        return v.strip()

    @field_validator("hora_inicio", "hora_fim")
    @classmethod
    def _horas(cls, v: str) -> str:
        return _hora(v)


class TurnoAtualizar(BaseModel):
    nome: Optional[str] = Field(None, min_length=1, max_length=60)
    hora_inicio: Optional[str] = None
    hora_fim: Optional[str] = None
    situacao: Optional[Literal["ativo", "inativo"]] = None

    @field_validator("nome")
    @classmethod
    def _nome(cls, v):
        if v is not None and not v.strip():
            raise ValueError("Informe o nome do turno")
        return v.strip() if v is not None else v

    @model_validator(mode="after")
    def _sem_nulo(self):
        for campo in self.model_fields_set:
            if getattr(self, campo) is None:
                raise ValueError(f"{campo} não pode ser vazio")
        return self

    @field_validator("hora_inicio", "hora_fim")
    @classmethod
    def _horas(cls, v):
        return None if v is None else _hora(v)


class TurnoResposta(BaseModel):
    id: str
    nome: str
    hora_inicio: str
    hora_fim: str
    situacao: str


class ResponsabilidadeResposta(BaseModel):
    id: str
    plantao_id: str
    funcionario_id: str
    funcionario_nome: str
    area_id: str
    area_nome: str
    inicio_em: datetime
    fim_em: Optional[datetime] = None
    motivo_fim: Optional[str] = None


class PlantaoResposta(BaseModel):
    id: str
    funcionario_id: str
    funcionario_nome: str
    turno_id: Optional[str] = None
    turno_nome: Optional[str] = None
    inicio_em: datetime
    fim_em: Optional[datetime] = None
    situacao: str
    # 2B (#122): escala planejada que este plantao cumpre (nulo = cobertura sem escala).
    escala_id: Optional[str] = None
    responsabilidades: list[ResponsabilidadeResposta] = []


EstadoEscala = Literal["prevista", "presente", "realizada", "nao_iniciada", "ausente", "substituida", "cancelada"]


class EscalaResposta(BaseModel):
    id: str
    funcionario_id: str
    funcionario_nome: str
    turno_id: Optional[str] = None
    turno_nome: Optional[str] = None
    area_id: Optional[str] = None
    area_nome: Optional[str] = None
    inicio_previsto: datetime
    fim_previsto: datetime
    tipo: Literal["regular", "substituicao", "cobertura"]
    situacao: Literal["prevista", "ausente", "cancelada"]
    motivo: Optional[str] = None
    substitui_escala_id: Optional[str] = None
    substituta_id: Optional[str] = None
    substituto_nome: Optional[str] = None
    plantao_id: Optional[str] = None
    # Previsto x efetivo, derivado agora (nao persistido).
    estado: EstadoEscala


class PlantaoAtual(BaseModel):
    """O plantao em andamento de quem esta logado (ou nenhum)."""

    pode_registrar: bool
    funcionario_id: Optional[str] = None
    plantao: Optional[PlantaoResposta] = None
    # 2B (#122): escalas previstas da pessoa ainda por cumprir (para iniciar a partir delas).
    escalas_pendentes: list[EscalaResposta] = []


class IniciarPlantao(BaseModel):
    area_ids: list[str] = Field(default_factory=list, max_length=20)
    turno_id: Optional[str] = None
    # 2B (#122): cumpre a propria escala; sem ela o plantao e cobertura sem escala.
    escala_id: Optional[str] = None


class EscalaCriar(BaseModel):
    funcionario_id: str
    area_id: Optional[str] = None
    turno_id: Optional[str] = None
    # Com turno + data, o horario sai do turno no fuso da ILPI; senao, inicio/fim explicitos.
    data: Optional[date] = None
    inicio_previsto: Optional[datetime] = None
    fim_previsto: Optional[datetime] = None
    tipo: Literal["regular", "cobertura"] = "regular"


class Motivo(BaseModel):
    motivo: str = Field(..., min_length=3, max_length=500)


class Substituir(Motivo):
    funcionario_id: str


class EscalaDia(BaseModel):
    dia: date
    fuso: str
    escalas: list[EscalaResposta]
    # Plantoes reais do dia sem escala (cobertura avulsa).
    coberturas_sem_escala: list[PlantaoResposta]


class Transferir(BaseModel):
    area_id: str
    para_plantao_id: str
    # Sem "de": o profissional passa a responder pela area junto com quem ja responde (cobertura).
    de_funcionario_id: Optional[str] = None


class AreaAgora(BaseModel):
    area: AreaResposta
    responsaveis: list[ResponsabilidadeResposta]
    residentes: Optional[int] = None


class EscalaAgora(BaseModel):
    gerado_em: datetime
    areas: list[AreaAgora]
    plantoes_sem_area: list[PlantaoResposta]


# ---------------------------------------------------------------- helpers ----

def _agora() -> datetime:
    return datetime.now(timezone.utc)


def _nao_encontrado():
    raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})


def _conflito(mensagem: str):
    raise HTTPException(status_code=409, detail={"code": OPERACAO_CONFLITO, "message": mensagem})


async def _auditar(db, obj, context, request, acao, antes=None):
    await db.flush()
    # updated_at vem do banco (onupdate): recarrega antes de ler, sem IO implicito no async.
    await db.refresh(obj)
    add_audit(db, acao=f"{obj.__tablename__}.{acao}", entidade=obj.__tablename__, registro_id=obj.id,
              usuario_id=context.user.id, ilpi_id=context.ilpi_id, valores_anteriores=antes,
              valores_posteriores=_data(obj), request=request)


async def _obter(db, modelo, ident, ilpi):
    """Mesmo contrato dos demais modulos: de outra ILPI = inexistente (404)."""
    obj = (await db.execute(select(modelo).where(modelo.id == ident, modelo.ilpi_id == ilpi))).scalar_one_or_none()
    if obj is None:
        _nao_encontrado()
    return obj


async def funcionario_da_sessao(db: AsyncSession, context: SecurityContext) -> Optional[m.Funcionario]:
    return (await db.execute(select(m.Funcionario).where(
        m.Funcionario.usuario_id == context.user.id, m.Funcionario.ilpi_id == context.ilpi_id,
        m.Funcionario.situacao == "ativo"))).scalar_one_or_none()


async def _leitos_das_areas(db, context, area_ids) -> dict[str, list[LeitoDaArea]]:
    if not area_ids:
        return {}
    ilpi = context.ilpi_id
    # escala:ler (repassavel a perfil local nao clinico) nao revela ocupacao de leito.
    mostrar_ocupacao = bool({"residentes:ler", "quartos_leitos:ler"} & set(await allowed_permission_keys(db, context)))
    linhas = (await db.execute(
        select(m.AreaLeito, m.QuartoLeito)
        .join(m.QuartoLeito, (m.QuartoLeito.id == m.AreaLeito.quarto_leito_id) & (m.QuartoLeito.instituicao_id == m.AreaLeito.ilpi_id))
        .where(m.AreaLeito.ilpi_id == ilpi, m.AreaLeito.area_id.in_(area_ids), m.AreaLeito.fim_em.is_(None))
        .order_by(m.QuartoLeito.unidade, m.QuartoLeito.quarto, m.QuartoLeito.leito)
    )).all()
    por_area: dict[str, list[LeitoDaArea]] = {a: [] for a in area_ids}
    for vinculo, leito in linhas:
        por_area[vinculo.area_id].append(LeitoDaArea(
            vinculo_id=vinculo.id, quarto_leito_id=leito.id, unidade=leito.unidade, quarto=leito.quarto,
            leito=leito.leito, ocupado=(leito.residente_atual_id is not None) if mostrar_ocupacao else None,
            desde=_utc(vinculo.inicio_em)))
    return por_area


def _area(area: m.AreaOperacional, leitos: list[LeitoDaArea] | None = None) -> AreaResposta:
    return AreaResposta(id=area.id, nome=area.nome, tipo=area.tipo, descricao=area.descricao,
                        situacao=area.situacao, leitos=leitos or [])


async def residentes_das_areas(db: AsyncSession, ilpi: str, area_ids: list[str]) -> dict[str, list[str]]:
    """Residentes que ocupam AGORA os leitos ativos de cada area (ocupacao e a fonte)."""
    if not area_ids:
        return {}
    linhas = (await db.execute(
        select(m.AreaLeito.area_id, m.QuartoLeito.residente_atual_id)
        .join(m.QuartoLeito, (m.QuartoLeito.id == m.AreaLeito.quarto_leito_id) & (m.QuartoLeito.instituicao_id == m.AreaLeito.ilpi_id))
        .where(m.AreaLeito.ilpi_id == ilpi, m.AreaLeito.area_id.in_(area_ids), m.AreaLeito.fim_em.is_(None),
               m.QuartoLeito.residente_atual_id.is_not(None))
    )).all()
    por_area: dict[str, list[str]] = {a: [] for a in area_ids}
    for area_id, residente_id in linhas:
        por_area[area_id].append(residente_id)
    return por_area


async def _responsabilidades(db, ilpi, *, plantao_ids=None, abertas_em=None, area_id=None, abertas=False):
    consulta = (select(m.Responsabilidade, m.Funcionario.nome, m.AreaOperacional.nome)
                .join(m.Funcionario, (m.Funcionario.id == m.Responsabilidade.funcionario_id) & (m.Funcionario.ilpi_id == m.Responsabilidade.ilpi_id))
                .join(m.AreaOperacional, (m.AreaOperacional.id == m.Responsabilidade.area_id) & (m.AreaOperacional.ilpi_id == m.Responsabilidade.ilpi_id))
                .where(m.Responsabilidade.ilpi_id == ilpi))
    if plantao_ids is not None:
        consulta = consulta.where(m.Responsabilidade.plantao_id.in_(plantao_ids))
    if area_id is not None:
        consulta = consulta.where(m.Responsabilidade.area_id == area_id)
    if abertas:
        consulta = consulta.where(m.Responsabilidade.fim_em.is_(None))
    if abertas_em is not None:
        # Vigencia semiaberta [inicio_em, fim_em): quem assumiu as 15:00 responde a partir das 15:00.
        consulta = consulta.where(m.Responsabilidade.inicio_em <= abertas_em,
                                  or_(m.Responsabilidade.fim_em.is_(None), m.Responsabilidade.fim_em > abertas_em))
    linhas = (await db.execute(consulta.order_by(m.Responsabilidade.inicio_em, m.Responsabilidade.id))).all()
    return [ResponsabilidadeResposta(
        id=r.id, plantao_id=r.plantao_id, funcionario_id=r.funcionario_id, funcionario_nome=nome_func,
        area_id=r.area_id, area_nome=nome_area, inicio_em=_utc(r.inicio_em), fim_em=_utc(r.fim_em),
        motivo_fim=r.motivo_fim) for r, nome_func, nome_area in linhas]


async def _plantoes_resposta(db, ilpi, plantoes: list[m.Plantao]) -> list[PlantaoResposta]:
    if not plantoes:
        return []
    ids = [p.id for p in plantoes]
    nomes = dict((await db.execute(select(m.Funcionario.id, m.Funcionario.nome).where(
        m.Funcionario.ilpi_id == ilpi, m.Funcionario.id.in_({p.funcionario_id for p in plantoes})))).all())
    turnos = dict((await db.execute(select(m.Turno.id, m.Turno.nome).where(
        m.Turno.ilpi_id == ilpi, m.Turno.id.in_({p.turno_id for p in plantoes if p.turno_id})))).all())
    resp = await _responsabilidades(db, ilpi, plantao_ids=ids)
    por_plantao: dict[str, list[ResponsabilidadeResposta]] = {i: [] for i in ids}
    for r in resp:
        por_plantao[r.plantao_id].append(r)
    escala_de = dict((await db.execute(select(m.Escala.plantao_id, m.Escala.id).where(
        m.Escala.ilpi_id == ilpi, m.Escala.plantao_id.in_(ids)))).all())
    return [PlantaoResposta(
        id=p.id, funcionario_id=p.funcionario_id, funcionario_nome=nomes.get(p.funcionario_id, ""),
        turno_id=p.turno_id, turno_nome=turnos.get(p.turno_id), inicio_em=_utc(p.inicio_em), fim_em=_utc(p.fim_em),
        situacao=p.situacao, escala_id=escala_de.get(p.id), responsabilidades=por_plantao[p.id]) for p in plantoes]


# ------------------------------------------------- escala planejada (2B) ----

def _estado_escala(e: m.Escala, plantao: Optional[m.Plantao], substituta: Optional[m.Escala], agora: datetime) -> str:
    """Previsto x efetivo, sem julgamento inventado (nao ha tolerancia de atraso)."""
    if e.situacao == "cancelada":
        return "cancelada"
    if e.situacao == "ausente":
        return "substituida" if substituta is not None else "ausente"
    if plantao is not None:
        return "presente" if plantao.situacao == "em_andamento" else "realizada"
    return "prevista" if agora < _utc(e.inicio_previsto) else "nao_iniciada"


async def _escalas_resposta(db, ilpi, escalas: list[m.Escala], *, mostrar_motivo: bool = True) -> list[EscalaResposta]:
    """``mostrar_motivo``: motivo de ausencia pode ser dado de saude do funcionario (LGPD) — so para quem gere."""
    if not escalas:
        return []
    agora = _agora()
    ids = [e.id for e in escalas]
    substitutas = {s.substitui_escala_id: s for s in (await db.scalars(select(m.Escala).where(
        m.Escala.ilpi_id == ilpi, m.Escala.substitui_escala_id.in_(ids), m.Escala.situacao != "cancelada"))).all()}
    func_ids = {e.funcionario_id for e in escalas} | {s.funcionario_id for s in substitutas.values()}
    nomes = dict((await db.execute(select(m.Funcionario.id, m.Funcionario.nome).where(
        m.Funcionario.ilpi_id == ilpi, m.Funcionario.id.in_(func_ids)))).all())
    turnos = dict((await db.execute(select(m.Turno.id, m.Turno.nome).where(
        m.Turno.ilpi_id == ilpi, m.Turno.id.in_({e.turno_id for e in escalas if e.turno_id})))).all())
    areas = dict((await db.execute(select(m.AreaOperacional.id, m.AreaOperacional.nome).where(
        m.AreaOperacional.ilpi_id == ilpi, m.AreaOperacional.id.in_({e.area_id for e in escalas if e.area_id})))).all())
    plantoes = {p.id: p for p in (await db.scalars(select(m.Plantao).where(
        m.Plantao.ilpi_id == ilpi, m.Plantao.id.in_({e.plantao_id for e in escalas if e.plantao_id})))).all()}
    saida = []
    for e in escalas:
        sub = substitutas.get(e.id)
        saida.append(EscalaResposta(
            id=e.id, funcionario_id=e.funcionario_id, funcionario_nome=nomes.get(e.funcionario_id, ""),
            turno_id=e.turno_id, turno_nome=turnos.get(e.turno_id), area_id=e.area_id, area_nome=areas.get(e.area_id),
            inicio_previsto=_utc(e.inicio_previsto), fim_previsto=_utc(e.fim_previsto), tipo=e.tipo, situacao=e.situacao,
            motivo=e.motivo if mostrar_motivo else None, substitui_escala_id=e.substitui_escala_id,
            substituta_id=sub.id if sub else None,
            substituto_nome=nomes.get(sub.funcionario_id) if sub else None, plantao_id=e.plantao_id,
            estado=_estado_escala(e, plantoes.get(e.plantao_id), sub, agora)))
    return saida


async def _funcionario_ativo(db, ilpi, funcionario_id) -> m.Funcionario:
    func = (await db.execute(select(m.Funcionario).where(
        m.Funcionario.id == funcionario_id, m.Funcionario.ilpi_id == ilpi))).scalar_one_or_none()
    if func is None:
        _nao_encontrado()
    if func.situacao != "ativo":
        _conflito("Este funcionário não está ativo")
    return func


async def _travar_funcionario(db, ilpi, funcionario_id) -> None:
    """Serializa o planejamento da mesma pessoa (checar sobreposicao e inserir sem corrida)."""
    resultado = await db.execute(
        update(m.Funcionario).where(m.Funcionario.id == funcionario_id, m.Funcionario.ilpi_id == ilpi)
        .values(situacao=m.Funcionario.situacao).execution_options(synchronize_session=False))
    if resultado.rowcount != 1:
        _nao_encontrado()


async def _travar_escala(db, ilpi, escala_id) -> m.Escala:
    """Primeiro DML da transicao da escala: ausencia, cancelamento, substituicao e inicio nao correm entre si."""
    resultado = await db.execute(
        update(m.Escala).where(m.Escala.id == escala_id, m.Escala.ilpi_id == ilpi)
        .values(situacao=m.Escala.situacao).execution_options(synchronize_session=False))
    if resultado.rowcount != 1:
        _nao_encontrado()
    return (await db.execute(select(m.Escala).where(m.Escala.id == escala_id, m.Escala.ilpi_id == ilpi)
                             .execution_options(populate_existing=True))).scalar_one()


async def _fim_de_hoje(db, ilpi, agora) -> datetime:
    fuso = await _fuso(db, ilpi)
    return datetime.combine(agora.astimezone(fuso).date() + timedelta(days=1), time.min, tzinfo=fuso).astimezone(timezone.utc)


async def _sem_sobreposicao(db, ilpi, funcionario_id, inicio, fim, ignorar_id=None):
    await _travar_funcionario(db, ilpi, funcionario_id)
    consulta = select(m.Escala.id).where(
        m.Escala.ilpi_id == ilpi, m.Escala.funcionario_id == funcionario_id, m.Escala.situacao == "prevista",
        m.Escala.inicio_previsto < fim, m.Escala.fim_previsto > inicio)
    if ignorar_id:
        consulta = consulta.where(m.Escala.id != ignorar_id)
    if (await db.execute(consulta.limit(1))).first() is not None:
        _conflito("Este profissional já tem escala prevista neste horário")


async def _escala_prevista_editavel(db, ilpi, escala_id) -> m.Escala:
    escala = await _travar_escala(db, ilpi, escala_id)
    if escala.situacao != "prevista":
        _conflito("Esta escala não está mais prevista")
    if escala.plantao_id is not None:
        _conflito("Esta escala já foi cumprida por um plantão; o histórico não é alterado")
    return escala


async def _abrir_responsabilidade(db, context, request, plantao: m.Plantao, area: m.AreaOperacional, instante):
    resp = m.Responsabilidade(ilpi_id=context.ilpi_id, plantao_id=plantao.id, funcionario_id=plantao.funcionario_id,
                              area_id=area.id, inicio_em=instante, criado_por=context.user.id)
    db.add(resp)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        _conflito("Este profissional já responde por esta área")
    await _auditar(db, resp, context, request, "abrir")
    return resp


async def _encerrar_responsabilidade(db, context, request, resp: m.Responsabilidade, instante, motivo):
    """Append-only: grava fim_em uma unica vez (UPDATE condicional; corrida perde com 409)."""
    antes = _data(resp)
    resultado = await db.execute(
        update(m.Responsabilidade)
        .where(m.Responsabilidade.id == resp.id, m.Responsabilidade.ilpi_id == context.ilpi_id,
               m.Responsabilidade.fim_em.is_(None))
        .values(fim_em=instante, motivo_fim=motivo, encerrado_por=context.user.id)
        .execution_options(synchronize_session=False))
    if resultado.rowcount != 1:
        await db.rollback()
        _conflito("Esta responsabilidade já foi encerrada")
    await db.refresh(resp)
    await _auditar(db, resp, context, request, "encerrar", antes)


async def _travar_plantao(db, ilpi, plantao_id) -> m.Plantao:
    """Primeiro DML da transicao: trava a linha do plantao (PostgreSQL) / a escrita (SQLite).

    Encerrar o plantao e transferir para ele passam por aqui, entao nao ha como
    abrir responsabilidade num plantao que acabou de ser encerrado.
    """
    resultado = await db.execute(
        update(m.Plantao).where(m.Plantao.id == plantao_id, m.Plantao.ilpi_id == ilpi)
        .values(situacao=m.Plantao.situacao).execution_options(synchronize_session=False))
    if resultado.rowcount != 1:
        _nao_encontrado()
    return (await db.execute(select(m.Plantao).where(m.Plantao.id == plantao_id, m.Plantao.ilpi_id == ilpi)
                             .execution_options(populate_existing=True))).scalar_one()


async def _encerrar_plantao(db, context, request, plantao: m.Plantao) -> None:
    """Encerra o plantao (ja travado) e as responsabilidades abertas dele, no mesmo instante. Sem commit."""
    instante = _agora()
    abertas = (await db.scalars(select(m.Responsabilidade).where(
        m.Responsabilidade.ilpi_id == context.ilpi_id, m.Responsabilidade.plantao_id == plantao.id,
        m.Responsabilidade.fim_em.is_(None)).execution_options(populate_existing=True))).all()
    for resp in abertas:
        await _encerrar_responsabilidade(db, context, request, resp, instante, "fim_plantao")
    antes = _data(plantao)
    plantao.fim_em, plantao.situacao, plantao.encerrado_por = instante, "encerrado", context.user.id
    await _auditar(db, plantao, context, request, "encerrar", antes)


async def _area_ativa(db, ilpi, area_id) -> m.AreaOperacional:
    area = await _obter(db, m.AreaOperacional, area_id, ilpi)
    if area.situacao != "ativa":
        _conflito(f"A área {area.nome} está inativa")
    return area


# ------------------------------------------------------------------ areas ----

@escala_router.get("/areas", response_model=list[AreaResposta])
async def listar_areas(db: AsyncSession = Depends(get_db),
                       context: SecurityContext = Depends(require_permission("escala:ler"))):
    areas = (await db.scalars(select(m.AreaOperacional).where(m.AreaOperacional.ilpi_id == context.ilpi_id)
                              .order_by(m.AreaOperacional.situacao, m.AreaOperacional.nome))).all()
    leitos = await _leitos_das_areas(db, context, [a.id for a in areas])
    return [_area(a, leitos.get(a.id)) for a in areas]


@escala_router.post("/areas", response_model=AreaResposta, status_code=201)
async def criar_area(payload: AreaCriar, request: Request, db: AsyncSession = Depends(get_db),
                     context: SecurityContext = Depends(require_permission("escala:gerenciar"))):
    area = m.AreaOperacional(ilpi_id=context.ilpi_id, nome=payload.nome, tipo=payload.tipo,
                             descricao=payload.descricao, situacao="ativa")
    db.add(area)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        _conflito("Já existe uma área com este nome")
    await _auditar(db, area, context, request, "criar")
    await db.commit()
    return _area(area)


@escala_router.patch("/areas/{area_id}", response_model=AreaResposta)
async def atualizar_area(area_id: str, payload: AreaAtualizar, request: Request, db: AsyncSession = Depends(get_db),
                         context: SecurityContext = Depends(require_permission("escala:gerenciar"))):
    area = await _obter(db, m.AreaOperacional, area_id, context.ilpi_id)
    antes = _data(area)
    dados = payload.model_dump(exclude_unset=True)
    if dados.get("situacao") == "inativa" and area.situacao == "ativa":
        abertas = await _responsabilidades(db, context.ilpi_id, area_id=area.id, abertas=True)
        if abertas:
            _conflito("Há profissionais respondendo por esta área agora; transfira antes de inativar")
    for campo, valor in dados.items():
        setattr(area, campo, valor.strip() if isinstance(valor, str) and campo == "nome" else valor)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        _conflito("Já existe uma área com este nome")
    await _auditar(db, area, context, request, "atualizar", antes)
    await db.commit()
    leitos = await _leitos_das_areas(db, context, [area.id])
    return _area(area, leitos.get(area.id))


@escala_router.post("/areas/{area_id}/leitos", response_model=AreaResposta, status_code=201)
async def vincular_leito(area_id: str, payload: VincularLeito, request: Request, db: AsyncSession = Depends(get_db),
                         context: SecurityContext = Depends(require_permission("escala:gerenciar"))):
    area = await _area_ativa(db, context.ilpi_id, area_id)
    leito = (await db.execute(select(m.QuartoLeito).where(
        m.QuartoLeito.id == payload.quarto_leito_id, m.QuartoLeito.instituicao_id == context.ilpi_id))).scalar_one_or_none()
    if leito is None:
        _nao_encontrado()
    vinculo = m.AreaLeito(ilpi_id=context.ilpi_id, area_id=area.id, quarto_leito_id=leito.id,
                          inicio_em=_agora(), criado_por=context.user.id)
    db.add(vinculo)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        _conflito("Este leito já pertence a uma área ativa; remova-o de lá antes")
    await _auditar(db, vinculo, context, request, "vincular")
    await db.commit()
    leitos = await _leitos_das_areas(db, context, [area.id])
    return _area(area, leitos.get(area.id))


@escala_router.post("/areas/{area_id}/leitos/{quarto_leito_id}/remover", response_model=AreaResposta)
async def remover_leito(area_id: str, quarto_leito_id: str, request: Request, db: AsyncSession = Depends(get_db),
                        context: SecurityContext = Depends(require_permission("escala:gerenciar"))):
    area = await _obter(db, m.AreaOperacional, area_id, context.ilpi_id)
    vinculo = (await db.execute(select(m.AreaLeito).where(
        m.AreaLeito.ilpi_id == context.ilpi_id, m.AreaLeito.area_id == area.id,
        m.AreaLeito.quarto_leito_id == quarto_leito_id, m.AreaLeito.fim_em.is_(None)))).scalar_one_or_none()
    if vinculo is None:
        _nao_encontrado()
    antes = _data(vinculo)
    # Encerra a vigencia; o historico de qual area o leito integrava permanece.
    vinculo.fim_em, vinculo.encerrado_por = _agora(), context.user.id
    await _auditar(db, vinculo, context, request, "desvincular", antes)
    await db.commit()
    leitos = await _leitos_das_areas(db, context, [area.id])
    return _area(area, leitos.get(area.id))


# ----------------------------------------------------------------- turnos ----

def _turno(t: m.Turno) -> TurnoResposta:
    return TurnoResposta(id=t.id, nome=t.nome, hora_inicio=t.hora_inicio, hora_fim=t.hora_fim, situacao=t.situacao)


@escala_router.get("/turnos", response_model=list[TurnoResposta])
async def listar_turnos(db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_ilpi_context)):
    # Turnos sao rotulos operacionais: quem inicia o proprio plantao tambem precisa escolher um.
    chaves = set(await allowed_permission_keys(db, context))
    if not ({"escala:ler", "plantao:registrar"} & chaves):
        raise HTTPException(status_code=403, detail={"code": "PERMISSION_DENIED", "message": "Permissão negada"})
    turnos = (await db.scalars(select(m.Turno).where(m.Turno.ilpi_id == context.ilpi_id)
                               .order_by(m.Turno.situacao, m.Turno.hora_inicio, m.Turno.nome))).all()
    return [_turno(t) for t in turnos]


@escala_router.post("/turnos", response_model=TurnoResposta, status_code=201)
async def criar_turno(payload: TurnoCriar, request: Request, db: AsyncSession = Depends(get_db),
                      context: SecurityContext = Depends(require_permission("escala:gerenciar"))):
    if payload.hora_inicio == payload.hora_fim:
        raise HTTPException(status_code=422, detail={"code": OPERACAO_INVALIDA, "message": "Início e fim do turno não podem ser iguais"})
    turno = m.Turno(ilpi_id=context.ilpi_id, nome=payload.nome.strip(), hora_inicio=payload.hora_inicio,
                    hora_fim=payload.hora_fim, situacao="ativo")
    db.add(turno)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        _conflito("Já existe um turno com este nome")
    await _auditar(db, turno, context, request, "criar")
    await db.commit()
    return _turno(turno)


@escala_router.patch("/turnos/{turno_id}", response_model=TurnoResposta)
async def atualizar_turno(turno_id: str, payload: TurnoAtualizar, request: Request, db: AsyncSession = Depends(get_db),
                          context: SecurityContext = Depends(require_permission("escala:gerenciar"))):
    turno = await _obter(db, m.Turno, turno_id, context.ilpi_id)
    antes = _data(turno)
    for campo, valor in payload.model_dump(exclude_unset=True).items():
        setattr(turno, campo, valor)
    if turno.hora_inicio == turno.hora_fim:
        raise HTTPException(status_code=422, detail={"code": OPERACAO_INVALIDA, "message": "Início e fim do turno não podem ser iguais"})
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        _conflito("Já existe um turno com este nome")
    await _auditar(db, turno, context, request, "atualizar", antes)
    await db.commit()
    return _turno(turno)


# ------------------------------------------------------ quem responde agora ----

@escala_router.get("/agora", response_model=EscalaAgora)
async def escala_agora(db: AsyncSession = Depends(get_db),
                       context: SecurityContext = Depends(require_permission("escala:ler"))):
    ilpi = context.ilpi_id
    chaves = set(await allowed_permission_keys(db, context))
    areas = (await db.scalars(select(m.AreaOperacional).where(
        m.AreaOperacional.ilpi_id == ilpi, m.AreaOperacional.situacao == "ativa").order_by(m.AreaOperacional.nome))).all()
    ids = [a.id for a in areas]
    leitos = await _leitos_das_areas(db, context, ids)
    abertas = await _responsabilidades(db, ilpi, abertas=True)
    por_area: dict[str, list[ResponsabilidadeResposta]] = {a: [] for a in ids}
    for r in abertas:
        por_area.setdefault(r.area_id, []).append(r)
    # Contagem de residentes so para quem le residentes (RBAC continua valendo).
    ocupacao = await residentes_das_areas(db, ilpi, ids) if "residentes:ler" in chaves else None
    em_andamento = (await db.scalars(select(m.Plantao).where(
        m.Plantao.ilpi_id == ilpi, m.Plantao.situacao == "em_andamento").order_by(m.Plantao.inicio_em))).all()
    com_area = {r.plantao_id for r in abertas}
    sem_area = await _plantoes_resposta(db, ilpi, [p for p in em_andamento if p.id not in com_area])
    return EscalaAgora(
        gerado_em=_agora(),
        areas=[AreaAgora(area=_area(a, leitos.get(a.id)), responsaveis=por_area.get(a.id, []),
                         residentes=len(ocupacao.get(a.id, [])) if ocupacao is not None else None) for a in areas],
        plantoes_sem_area=sem_area,
    )


@escala_router.get("/responsaveis", response_model=list[ResponsabilidadeResposta])
async def responsaveis_no_instante(area_id: str, em: datetime = Query(..., description="Instante (ISO 8601 com fuso)"),
                                   db: AsyncSession = Depends(get_db),
                                   context: SecurityContext = Depends(require_permission("escala:ler"))):
    """Quem respondia pela area no instante ``em`` — consulta historica honesta."""
    await _obter(db, m.AreaOperacional, area_id, context.ilpi_id)
    return await _responsabilidades(db, context.ilpi_id, area_id=area_id, abertas_em=_utc(em))


@escala_router.post("/responsabilidades/transferir", response_model=list[ResponsabilidadeResposta])
async def transferir(payload: Transferir, request: Request, db: AsyncSession = Depends(get_db),
                     context: SecurityContext = Depends(require_permission("escala:gerenciar"))):
    ilpi = context.ilpi_id
    area = await _area_ativa(db, ilpi, payload.area_id)
    para = await _travar_plantao(db, ilpi, payload.para_plantao_id)
    if para.situacao != "em_andamento":
        _conflito("O plantão de destino já foi encerrado")
    instante = _agora()
    if payload.de_funcionario_id:
        anterior = (await db.execute(select(m.Responsabilidade).where(
            m.Responsabilidade.ilpi_id == ilpi, m.Responsabilidade.area_id == area.id,
            m.Responsabilidade.funcionario_id == payload.de_funcionario_id,
            m.Responsabilidade.fim_em.is_(None)))).scalar_one_or_none()
        if anterior is None:
            _nao_encontrado()
        if anterior.funcionario_id == para.funcionario_id:
            _conflito("Origem e destino são o mesmo profissional")
        # Mesmo instante: nunca fica buraco nem sobreposicao do mesmo par.
        await _encerrar_responsabilidade(db, context, request, anterior, instante, "transferencia")
    await _abrir_responsabilidade(db, context, request, para, area, instante)
    await db.commit()
    return await _responsabilidades(db, ilpi, area_id=area.id, abertas=True)


@escala_router.post("/responsabilidades/{responsabilidade_id}/encerrar", response_model=ResponsabilidadeResposta)
async def encerrar_responsabilidade(responsabilidade_id: str, request: Request, db: AsyncSession = Depends(get_db),
                                    context: SecurityContext = Depends(require_permission("escala:gerenciar"))):
    resp = await _obter(db, m.Responsabilidade, responsabilidade_id, context.ilpi_id)
    await _travar_plantao(db, context.ilpi_id, resp.plantao_id)
    await _encerrar_responsabilidade(db, context, request, resp, _agora(), "ajuste")
    await db.commit()
    return next(r for r in await _responsabilidades(db, context.ilpi_id, plantao_ids=[resp.plantao_id]) if r.id == resp.id)


# ---------------------------------------------- previsto x efetivo (2B) ----

@escala_router.get("/previsto", response_model=EscalaDia)
async def escala_do_dia(dia: Optional[date] = None, db: AsyncSession = Depends(get_db),
                        context: SecurityContext = Depends(require_permission("escala:ler"))):
    """Escalas que tocam o dia (no fuso da ILPI) e coberturas reais sem escala."""
    ilpi = context.ilpi_id
    fuso = await _fuso(db, ilpi)
    dia = dia or _agora().astimezone(fuso).date()
    inicio = datetime.combine(dia, time.min, tzinfo=fuso).astimezone(timezone.utc)
    fim = datetime.combine(dia + timedelta(days=1), time.min, tzinfo=fuso).astimezone(timezone.utc)
    escalas = (await db.scalars(select(m.Escala).where(
        m.Escala.ilpi_id == ilpi, m.Escala.inicio_previsto < fim, m.Escala.fim_previsto > inicio)
        .order_by(m.Escala.inicio_previsto, m.Escala.created_at, m.Escala.id))).all()
    cumpridos = select(m.Escala.plantao_id).where(m.Escala.ilpi_id == ilpi, m.Escala.plantao_id.is_not(None))
    avulsos = (await db.scalars(select(m.Plantao).where(
        m.Plantao.ilpi_id == ilpi, m.Plantao.inicio_em < fim, or_(m.Plantao.fim_em.is_(None), m.Plantao.fim_em > inicio),
        m.Plantao.id.not_in(cumpridos)).order_by(m.Plantao.inicio_em, m.Plantao.id))).all()
    gere = "escala:gerenciar" in set(await allowed_permission_keys(db, context))
    return EscalaDia(dia=dia, fuso=fuso.key, escalas=await _escalas_resposta(db, ilpi, list(escalas), mostrar_motivo=gere),
                     coberturas_sem_escala=await _plantoes_resposta(db, ilpi, list(avulsos)))


@escala_router.post("/previsto", response_model=EscalaResposta, status_code=201)
async def criar_escala(payload: EscalaCriar, request: Request, db: AsyncSession = Depends(get_db),
                       context: SecurityContext = Depends(require_permission("escala:gerenciar"))):
    ilpi = context.ilpi_id
    func = await _funcionario_ativo(db, ilpi, payload.funcionario_id)
    area = await _area_ativa(db, ilpi, payload.area_id) if payload.area_id else None
    turno = await _obter(db, m.Turno, payload.turno_id, ilpi) if payload.turno_id else None
    if turno is not None and turno.situacao != "ativo":
        _conflito("Este turno está inativo")
    if turno is not None and payload.data is not None:
        # Horario do turno no fuso da ILPI; fim <= inicio cruza a meia-noite.
        fuso = await _fuso(db, ilpi)
        h_ini, h_fim = (time.fromisoformat(turno.hora_inicio), time.fromisoformat(turno.hora_fim))
        inicio = datetime.combine(payload.data, h_ini, tzinfo=fuso)
        fim = datetime.combine(payload.data + (timedelta(days=1) if h_fim <= h_ini else timedelta()), h_fim, tzinfo=fuso)
        inicio, fim = inicio.astimezone(timezone.utc), fim.astimezone(timezone.utc)
    elif payload.inicio_previsto is not None and payload.fim_previsto is not None:
        inicio, fim = _utc(payload.inicio_previsto), _utc(payload.fim_previsto)
    else:
        raise HTTPException(status_code=422, detail={"code": OPERACAO_INVALIDA,
                                                     "message": "Informe turno e data, ou início e fim previstos"})
    if fim <= inicio:
        raise HTTPException(status_code=422, detail={"code": OPERACAO_INVALIDA, "message": "O fim precisa ser depois do início"})
    await _sem_sobreposicao(db, ilpi, func.id, inicio, fim)
    escala = m.Escala(ilpi_id=ilpi, funcionario_id=func.id, turno_id=turno.id if turno else None,
                      area_id=area.id if area else None, inicio_previsto=inicio, fim_previsto=fim,
                      tipo=payload.tipo, situacao="prevista", criado_por=context.user.id)
    db.add(escala)
    await _auditar(db, escala, context, request, "criar")
    await db.commit()
    return (await _escalas_resposta(db, ilpi, [escala]))[0]


@escala_router.post("/previsto/{escala_id}/ausencia", response_model=EscalaResposta)
async def registrar_ausencia(escala_id: str, payload: Motivo, request: Request, db: AsyncSession = Depends(get_db),
                             context: SecurityContext = Depends(require_permission("escala:gerenciar"))):
    escala = await _escala_prevista_editavel(db, context.ilpi_id, escala_id)
    antes = _data(escala)
    escala.situacao, escala.motivo, escala.atualizado_por = "ausente", payload.motivo.strip(), context.user.id
    await _auditar(db, escala, context, request, "ausencia", antes)
    await db.commit()
    return (await _escalas_resposta(db, context.ilpi_id, [escala]))[0]


@escala_router.post("/previsto/{escala_id}/substituir", response_model=list[EscalaResposta], status_code=201)
async def substituir(escala_id: str, payload: Substituir, request: Request, db: AsyncSession = Depends(get_db),
                     context: SecurityContext = Depends(require_permission("escala:gerenciar"))):
    """Substituicao simples: a original fica ausente e nasce uma escala de substituicao no mesmo periodo."""
    ilpi = context.ilpi_id
    original = await _travar_escala(db, ilpi, escala_id)
    if original.situacao == "cancelada" or original.plantao_id is not None:
        _conflito("Só uma escala prevista ou ausente, ainda não cumprida, pode ser substituída")
    ja = (await db.execute(select(m.Escala.id).where(m.Escala.ilpi_id == ilpi, m.Escala.substitui_escala_id == original.id,
                                                    m.Escala.situacao != "cancelada"))).first()
    if ja is not None:
        _conflito("Esta escala já tem substituto")
    func = await _funcionario_ativo(db, ilpi, payload.funcionario_id)
    if func.id == original.funcionario_id:
        _conflito("O substituto precisa ser outro profissional")
    await _sem_sobreposicao(db, ilpi, func.id, _utc(original.inicio_previsto), _utc(original.fim_previsto))
    if original.situacao == "prevista":
        antes = _data(original)
        original.situacao, original.motivo, original.atualizado_por = "ausente", payload.motivo.strip(), context.user.id
        await _auditar(db, original, context, request, "ausencia", antes)
    nova = m.Escala(ilpi_id=ilpi, funcionario_id=func.id, turno_id=original.turno_id, area_id=original.area_id,
                    inicio_previsto=original.inicio_previsto, fim_previsto=original.fim_previsto, tipo="substituicao",
                    situacao="prevista", substitui_escala_id=original.id, motivo=None, criado_por=context.user.id)
    db.add(nova)
    try:
        await _auditar(db, nova, context, request, "substituir")
    except IntegrityError:
        await db.rollback()
        _conflito("Esta escala já tem substituto")
    await db.commit()
    return await _escalas_resposta(db, ilpi, [original, nova])


@escala_router.post("/previsto/{escala_id}/cancelar", response_model=EscalaResposta)
async def cancelar_escala(escala_id: str, payload: Motivo, request: Request, db: AsyncSession = Depends(get_db),
                          context: SecurityContext = Depends(require_permission("escala:gerenciar"))):
    escala = await _escala_prevista_editavel(db, context.ilpi_id, escala_id)
    antes = _data(escala)
    escala.situacao, escala.motivo, escala.atualizado_por = "cancelada", payload.motivo.strip(), context.user.id
    await _auditar(db, escala, context, request, "cancelar", antes)
    await db.commit()
    return (await _escalas_resposta(db, context.ilpi_id, [escala]))[0]


# --------------------------------------------------------------- plantoes ----

@plantoes_router.get("/atual", response_model=PlantaoAtual)
async def plantao_atual(db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_ilpi_context)):
    """So o proprio plantao: nao expoe dado de outra pessoa, por isso basta o contexto da ILPI."""
    chaves = set(await allowed_permission_keys(db, context))
    funcionario = await funcionario_da_sessao(db, context)
    if funcionario is None:
        return PlantaoAtual(pode_registrar=False)
    plantao = (await db.execute(select(m.Plantao).where(
        m.Plantao.ilpi_id == context.ilpi_id, m.Plantao.funcionario_id == funcionario.id,
        m.Plantao.situacao == "em_andamento"))).scalar_one_or_none()
    resposta = (await _plantoes_resposta(db, context.ilpi_id, [plantao]))[0] if plantao else None
    if resposta is not None:
        resposta.responsabilidades = [r for r in resposta.responsabilidades if r.fim_em is None]
    # Escalas previstas da propria pessoa ainda por cumprir (as proximas primeiro).
    pendentes = (await db.scalars(select(m.Escala).where(
        m.Escala.ilpi_id == context.ilpi_id, m.Escala.funcionario_id == funcionario.id, m.Escala.situacao == "prevista",
        m.Escala.plantao_id.is_(None), m.Escala.fim_previsto > _agora(),
        m.Escala.inicio_previsto < await _fim_de_hoje(db, context.ilpi_id, _agora()))
        .order_by(m.Escala.inicio_previsto, m.Escala.id).limit(3))).all()
    return PlantaoAtual(pode_registrar="plantao:registrar" in chaves, funcionario_id=funcionario.id, plantao=resposta,
                        escalas_pendentes=await _escalas_resposta(db, context.ilpi_id, list(pendentes)))


@plantoes_router.post("/iniciar", response_model=PlantaoResposta, status_code=201)
async def iniciar_plantao(payload: IniciarPlantao, request: Request, db: AsyncSession = Depends(get_db),
                          context: SecurityContext = Depends(require_permission("plantao:registrar"))):
    ilpi = context.ilpi_id
    funcionario = await funcionario_da_sessao(db, context)
    if funcionario is None:
        _conflito("Seu usuário não está vinculado a um funcionário ativo desta ILPI")
    instante = _agora()
    escala = None
    if payload.escala_id:
        # Posse primeiro: escala de outra pessoa (ou ILPI) e inexistente para quem pede.
        propria = await _obter(db, m.Escala, payload.escala_id, ilpi)
        if propria.funcionario_id != funcionario.id:
            _nao_encontrado()
        escala = await _escala_prevista_editavel(db, ilpi, propria.id)
        if _utc(escala.fim_previsto) <= instante:
            _conflito("O período desta escala já terminou")
        # So escala que toca o dia de hoje (no fuso da ILPI): nao se cumpre hoje a escala de amanha.
        if _utc(escala.inicio_previsto) >= await _fim_de_hoje(db, ilpi, instante):
            _conflito("Esta escala é de outro dia")
    turno_id = payload.turno_id or (escala.turno_id if escala else None)
    turno = None
    if turno_id:
        turno = await _obter(db, m.Turno, turno_id, ilpi)
        if turno.situacao != "ativo" and payload.turno_id:
            _conflito("Este turno está inativo")
    if payload.area_ids:
        areas = [await _area_ativa(db, ilpi, area_id) for area_id in dict.fromkeys(payload.area_ids)]
    else:
        # Area da escala inativada depois do planejamento: o plantao comeca sem area (a coordenacao atribui).
        da_escala = await _obter(db, m.AreaOperacional, escala.area_id, ilpi) if escala is not None and escala.area_id else None
        areas = [da_escala] if da_escala is not None and da_escala.situacao == "ativa" else []
    plantao = m.Plantao(ilpi_id=ilpi, funcionario_id=funcionario.id, turno_id=turno.id if turno else None,
                        inicio_em=instante, situacao="em_andamento", iniciado_por=context.user.id)
    db.add(plantao)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        _conflito("Você já tem um plantão em andamento")
    await _auditar(db, plantao, context, request, "iniciar")
    if escala is not None:
        antes = _data(escala)
        escala.plantao_id, escala.atualizado_por = plantao.id, context.user.id
        try:
            await _auditar(db, escala, context, request, "cumprir", antes)
        except IntegrityError:
            await db.rollback()
            _conflito("A escala mudou enquanto o plantão era iniciado; atualize e tente de novo")
    for area in areas:
        await _abrir_responsabilidade(db, context, request, plantao, area, instante)
    await db.commit()
    return (await _plantoes_resposta(db, ilpi, [plantao]))[0]


@plantoes_router.post("/{plantao_id}/encerrar", response_model=PlantaoResposta)
async def encerrar_plantao(plantao_id: str, request: Request, db: AsyncSession = Depends(get_db),
                           context: SecurityContext = Depends(require_ilpi_context)):
    ilpi = context.ilpi_id
    chaves = set(await allowed_permission_keys(db, context))
    plantao = await _obter(db, m.Plantao, plantao_id, ilpi)
    funcionario = await funcionario_da_sessao(db, context)
    proprio = funcionario is not None and plantao.funcionario_id == funcionario.id
    # O proprio profissional encerra o seu; o gestor da escala encerra o de outro (esquecido aberto).
    if not ((proprio and "plantao:registrar" in chaves) or "escala:gerenciar" in chaves):
        raise HTTPException(status_code=403, detail={"code": "PERMISSION_DENIED", "message": "Permissão negada"})
    plantao = await _travar_plantao(db, ilpi, plantao.id)
    if plantao.situacao != "em_andamento":
        _conflito("Este plantão já foi encerrado")
    await _encerrar_plantao(db, context, request, plantao)
    await db.commit()
    return (await _plantoes_resposta(db, ilpi, [plantao]))[0]


@plantoes_router.get("/", response_model=list[PlantaoResposta])
async def listar_plantoes(desde: Optional[datetime] = None, ate: Optional[datetime] = None, limit: int = Query(200, ge=1, le=1000),
                          db: AsyncSession = Depends(get_db),
                          context: SecurityContext = Depends(require_permission("escala:ler"))):
    consulta = select(m.Plantao).where(m.Plantao.ilpi_id == context.ilpi_id)
    if desde is not None:
        consulta = consulta.where(or_(m.Plantao.fim_em.is_(None), m.Plantao.fim_em >= _utc(desde)))
    if ate is not None:
        consulta = consulta.where(m.Plantao.inicio_em < _utc(ate))
    plantoes = (await db.scalars(consulta.order_by(m.Plantao.inicio_em.desc(), m.Plantao.id).limit(limit))).all()
    return await _plantoes_resposta(db, context.ilpi_id, list(plantoes))
