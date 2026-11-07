"""Relatorio resumido (complementar D5): projecao so leitura das fontes oficiais.

Cada secao exige a mesma permissao de leitura da sua fonte: o relatorio nunca
mostra o que a sessao nao poderia ler na origem. O periodo e o "dia" da ILPI.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from ..infrastructure import models as m
from ..infrastructure.database import get_db
from .security import SecurityContext, allowed_permission_keys, require_ilpi_context

relatorios_router = APIRouter(prefix="/relatorios", tags=["relatorios"])
MAX_DIAS = 366


class Contagem(BaseModel):
    chave: str
    total: int


class RelatorioResumo(BaseModel):
    de: date
    ate: date
    residentes_por_situacao: Optional[list[Contagem]] = None
    intercorrencias_por_gravidade: Optional[list[Contagem]] = None
    administracoes_por_resultado: Optional[list[Contagem]] = None


def _contagens(linhas) -> list[Contagem]:
    return [Contagem(chave=c or "nao_informado", total=t) for c, t in linhas]


@relatorios_router.get("/resumo", response_model=RelatorioResumo)
async def resumo(
    de: date = Query(...),
    ate: date = Query(...),
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_ilpi_context),
):
    if ate < de or (ate - de).days > MAX_DIAS:
        raise HTTPException(status_code=422, detail="Periodo invalido")
    chaves = set(await allowed_permission_keys(db, context))
    if not chaves & {"residentes:ler", "intercorrencias:ler", "administracoes:ler"}:
        raise HTTPException(status_code=403, detail={"code": "PERMISSION_DENIED", "message": "Sem acesso a relatórios."})

    fuso = await db.scalar(select(m.Instituicao.fuso_horario).where(m.Instituicao.id == context.ilpi_id))
    tz = ZoneInfo(fuso or "America/Sao_Paulo")
    inicio = datetime.combine(de, time.min, tz).astimezone(timezone.utc)
    fim = datetime.combine(ate + timedelta(days=1), time.min, tz).astimezone(timezone.utc)
    corpo = RelatorioResumo(de=de, ate=ate)

    if "residentes:ler" in chaves:
        corpo.residentes_por_situacao = _contagens((await db.execute(
            select(m.Residente.situacao, func.count())
            .where(m.Residente.instituicao_id == context.ilpi_id)
            .group_by(m.Residente.situacao).order_by(m.Residente.situacao)
        )).all())
    if "intercorrencias:ler" in chaves:
        corpo.intercorrencias_por_gravidade = _contagens((await db.execute(
            select(m.Intercorrencia.gravidade, func.count())
            .where(m.Intercorrencia.ilpi_id == context.ilpi_id,
                   m.Intercorrencia.ocorrido_em >= inicio, m.Intercorrencia.ocorrido_em < fim)
            .group_by(m.Intercorrencia.gravidade).order_by(m.Intercorrencia.gravidade)
        )).all())
    if "administracoes:ler" in chaves:
        # Vigentes: nao estornadas e nao substituidas por correcao posterior.
        nova = aliased(m.Administracao)
        substituida = select(nova.id).where(nova.substitui_id == m.Administracao.id).exists()
        corpo.administracoes_por_resultado = _contagens((await db.execute(
            select(m.Administracao.resultado, func.count())
            .where(m.Administracao.ilpi_id == context.ilpi_id,
                   m.Administracao.ocorrido_em >= inicio, m.Administracao.ocorrido_em < fim,
                   m.Administracao.estornado_em.is_(None), ~substituida)
            .group_by(m.Administracao.resultado).order_by(m.Administracao.resultado)
        )).all())
    return corpo
