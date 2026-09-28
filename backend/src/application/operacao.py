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
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure import models as m
from ..infrastructure.database import get_db
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
    responsabilidades: list[ResponsabilidadeResposta] = []


class PlantaoAtual(BaseModel):
    """O plantao em andamento de quem esta logado (ou nenhum)."""

    pode_registrar: bool
    funcionario_id: Optional[str] = None
    plantao: Optional[PlantaoResposta] = None


class IniciarPlantao(BaseModel):
    area_ids: list[str] = Field(default_factory=list, max_length=20)
    turno_id: Optional[str] = None


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
    return [PlantaoResposta(
        id=p.id, funcionario_id=p.funcionario_id, funcionario_nome=nomes.get(p.funcionario_id, ""),
        turno_id=p.turno_id, turno_nome=turnos.get(p.turno_id), inicio_em=_utc(p.inicio_em), fim_em=_utc(p.fim_em),
        situacao=p.situacao, responsabilidades=por_plantao[p.id]) for p in plantoes]


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
    return PlantaoAtual(pode_registrar="plantao:registrar" in chaves, funcionario_id=funcionario.id, plantao=resposta)


@plantoes_router.post("/iniciar", response_model=PlantaoResposta, status_code=201)
async def iniciar_plantao(payload: IniciarPlantao, request: Request, db: AsyncSession = Depends(get_db),
                          context: SecurityContext = Depends(require_permission("plantao:registrar"))):
    ilpi = context.ilpi_id
    funcionario = await funcionario_da_sessao(db, context)
    if funcionario is None:
        _conflito("Seu usuário não está vinculado a um funcionário ativo desta ILPI")
    turno = None
    if payload.turno_id:
        turno = await _obter(db, m.Turno, payload.turno_id, ilpi)
        if turno.situacao != "ativo":
            _conflito("Este turno está inativo")
    areas = [await _area_ativa(db, ilpi, area_id) for area_id in dict.fromkeys(payload.area_ids)]
    instante = _agora()
    plantao = m.Plantao(ilpi_id=ilpi, funcionario_id=funcionario.id, turno_id=turno.id if turno else None,
                        inicio_em=instante, situacao="em_andamento", iniciado_por=context.user.id)
    db.add(plantao)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        _conflito("Você já tem um plantão em andamento")
    await _auditar(db, plantao, context, request, "iniciar")
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
