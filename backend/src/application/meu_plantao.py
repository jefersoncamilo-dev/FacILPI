"""Camada Operacional, Fase 5 (#126): Meu Plantao como destino operacional.

Agregador de APRESENTACAO — nao cria fonte nem formulario:
- turno, areas e residentes sob responsabilidade vem do plantao real e das
  responsabilidades abertas (2A/2B);
- prioridades sao os itens da central (mesma projecao, mesma ordem, com o
  estado de atendimento) dos residentes da area;
- atividades atrasadas e proximas vem da mesma projecao do Meu Plantao
  (rotina), recortada pelos residentes da area;
- passagens a receber vem da passagem persistida (Fase 4).
Cada bloco so sai com a leitura correspondente (RBAC); sem, fica nulo.
SEM plantao ativo, nenhum bloco novo aparece: a tela continua como era
(projecao da ILPI inteira), sem ampliar nada para quem nao esta de plantao.
Responsabilidade nunca concede acesso: so recorta o que o RBAC ja permite.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure import models as m
from ..infrastructure.database import get_db
from . import schemas as s
from .alertas import _estado_item, _estados_abertos, _local, _nomes_de, projetar
from .operacao import (
    EscalaResposta, PlantaoResposta, _escalas_resposta, _plantoes_resposta, _responsabilidades,
    funcionario_da_sessao, residentes_das_areas,
)
from .rotina import meu_plantao as projecao_do_plantao
from .security import SecurityContext, allowed_permission_keys, require_ilpi_context

meu_plantao_router = APIRouter(prefix="/meu-plantao", tags=["meu-plantao"], dependencies=[Depends(require_ilpi_context)])

HORAS_PROXIMAS = 4
LIMITE_PRIORIDADES = 30


class AreaDoTurno(BaseModel):
    id: str
    nome: str


class ResidenteDoTurno(BaseModel):
    id: str
    nome: str
    local: Optional[str] = None
    em_atencao: bool
    motivos: list[str] = []


class AtividadeDoTurno(BaseModel):
    origem: str
    registro_id: str
    residente_id: str
    residente_nome: Optional[str] = None
    descricao: str
    previsto_em: Optional[datetime] = None


class Atividades(BaseModel):
    atrasadas: list[AtividadeDoTurno]
    proximas: list[AtividadeDoTurno]


class MeuPlantaoResposta(BaseModel):
    gerado_em: datetime
    plantao: Optional[PlantaoResposta] = None
    escalas_pendentes: list[EscalaResposta] = []
    areas: list[AreaDoTurno] = []
    # Blocos novos: so com plantao ativo em ao menos uma area, e cada um com sua leitura.
    residentes: Optional[list[ResidenteDoTurno]] = None
    prioridades: Optional[list[s.AlertaGestorItem]] = None
    atividades: Optional[Atividades] = None
    passagens_a_receber: Optional[int] = None


@meu_plantao_router.get("/", response_model=MeuPlantaoResposta)
async def meu_plantao(db: AsyncSession = Depends(get_db), context: SecurityContext = Depends(require_ilpi_context)):
    ilpi = context.ilpi_id
    agora = datetime.now(timezone.utc)
    chaves = set(await allowed_permission_keys(db, context))
    resposta = MeuPlantaoResposta(gerado_em=agora)
    funcionario = await funcionario_da_sessao(db, context)
    if funcionario is None:
        return resposta
    plantao = (await db.execute(select(m.Plantao).where(
        m.Plantao.ilpi_id == ilpi, m.Plantao.funcionario_id == funcionario.id,
        m.Plantao.situacao == "em_andamento"))).scalar_one_or_none()
    if plantao is None:
        pendentes = (await db.scalars(select(m.Escala).where(
            m.Escala.ilpi_id == ilpi, m.Escala.funcionario_id == funcionario.id, m.Escala.situacao == "prevista",
            m.Escala.plantao_id.is_(None), m.Escala.fim_previsto > agora)
            .order_by(m.Escala.inicio_previsto, m.Escala.id).limit(3))).all()
        resposta.escalas_pendentes = await _escalas_resposta(db, ilpi, list(pendentes))
        return resposta

    resposta.plantao = (await _plantoes_resposta(db, ilpi, [plantao]))[0]
    abertas = await _responsabilidades(db, ilpi, plantao_ids=[plantao.id], abertas=True)
    resposta.plantao.responsabilidades = abertas
    resposta.areas = [AreaDoTurno(id=r.area_id, nome=r.area_nome) for r in abertas]
    if not abertas:
        return resposta

    por_area = await residentes_das_areas(db, ilpi, [r.area_id for r in abertas])
    escopo = {rid for ids in por_area.values() for rid in ids}

    if "alertas:ler" in chaves:
        proj = await projetar(db, context)
        estados = await _estados_abertos(db, ilpi)
        nomes_estado = await _nomes_de(db, ilpi, estados.values())
        prioridades = []
        for item in proj.itens:
            if item["residente_id"] not in escopo:
                continue
            estado = estados.get(item["id"])
            item["estado"] = _estado_item(estado, nomes_estado, context.user.id) if estado is not None else None
            prioridades.append(item)
        resposta.prioridades = [s.AlertaGestorItem(**i) for i in prioridades[:LIMITE_PRIORIDADES]]

    nomes: dict[str, str] = {}
    if "residentes:ler" in chaves and escopo:
        nomes = dict((await db.execute(select(m.Residente.id, m.Residente.nome).where(
            m.Residente.instituicao_id == ilpi, m.Residente.id.in_(escopo)))).all())

    if "plantao:ler" in chaves:
        itens = await projecao_do_plantao(a_partir_de=_min(plantao.inicio_em, agora), ate=agora + timedelta(hours=HORAS_PROXIMAS),
                                          residente_id=None, limit=1000, db=db, context=context)
        atrasadas, proximas = [], []
        for p in itens:
            if p["residente_id"] not in escopo or p["origem"] == "intercorrencia":
                continue
            atividade = AtividadeDoTurno(origem=p["origem"], registro_id=p["registro_id"], residente_id=p["residente_id"],
                                         residente_nome=nomes.get(p["residente_id"]), descricao=p["descricao"],
                                         previsto_em=p["previsto_em"])
            (atrasadas if p["previsto_em"] is not None and p["previsto_em"] < agora else proximas).append(atividade)
        resposta.atividades = Atividades(atrasadas=atrasadas, proximas=proximas)

    if "residentes:ler" in chaves:
        motivos: dict[str, list[str]] = {rid: [] for rid in escopo}
        for p in resposta.prioridades or []:
            if p.gravidade == "critico" and p.residente_id in motivos:
                motivos[p.residente_id].append(p.titulo)
        if "intercorrencias:ler" in chaves and escopo:
            for i in (await db.scalars(select(m.Intercorrencia).where(
                    m.Intercorrencia.ilpi_id == ilpi, m.Intercorrencia.situacao == "aberta",
                    m.Intercorrencia.residente_id.in_(escopo)))).all():
                rotulo = f"Intercorrência aberta: {i.tipo}"
                if not any(rotulo in t for t in motivos[i.residente_id]):
                    motivos[i.residente_id].append(rotulo)
        leitos = {r.residente_atual_id: (r.unidade, r.quarto, r.leito) for r in (await db.execute(
            select(m.QuartoLeito.residente_atual_id, m.QuartoLeito.unidade, m.QuartoLeito.quarto, m.QuartoLeito.leito)
            .where(m.QuartoLeito.instituicao_id == ilpi, m.QuartoLeito.residente_atual_id.in_(escopo)))).all()} if escopo else {}
        residentes = [ResidenteDoTurno(id=rid, nome=nomes.get(rid, ""), local=_local(*leitos[rid]) if rid in leitos else None,
                                       em_atencao=bool(motivos[rid]), motivos=motivos[rid]) for rid in escopo]
        # Em atencao primeiro; depois por nome.
        resposta.residentes = sorted(residentes, key=lambda r: (not r.em_atencao, r.nome, r.id))

    if "passagem_plantao:ler" in chaves:
        area_ids = [r.area_id for r in abertas]
        resposta.passagens_a_receber = len((await db.scalars(select(m.PassagemPlantao.id).where(
            m.PassagemPlantao.ilpi_id == ilpi, m.PassagemPlantao.situacao == "entregue",
            m.PassagemPlantao.entregue_por != context.user.id,
            (m.PassagemPlantao.area_id.in_(area_ids)) | (m.PassagemPlantao.area_id.is_(None))))).all())
    return resposta


def _min(inicio, agora):
    inicio = inicio.replace(tzinfo=timezone.utc) if inicio.tzinfo is None else inicio
    # A janela de atrasadas comeca no inicio do plantao (limitada a 24 h para tras).
    return max(inicio, agora - timedelta(hours=24))
