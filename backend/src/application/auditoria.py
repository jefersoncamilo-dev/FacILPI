"""Consulta da trilha de auditoria (complementar D5): so leitura, so a ILPI da sessao.

A trilha pode conter dados assistenciais; por isso o escopo global nao consulta
aqui, mesmo com ``auditoria:ler`` (Platform nao tem acesso clinico implicito).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure import models as m
from ..infrastructure.database import get_db
from .security import ILPI_SCOPE, SecurityContext, require_permission

auditoria_router = APIRouter(prefix="/auditoria", tags=["auditoria"])


class AuditoriaItem(BaseModel):
    id: str
    acao: str
    entidade: Optional[str] = None
    registro_id: Optional[str] = None
    usuario_id: Optional[str] = None
    usuario_nome: Optional[str] = None
    valores_anteriores: Optional[str] = None
    valores_posteriores: Optional[str] = None
    created_at: datetime


@auditoria_router.get("/", response_model=list[AuditoriaItem])
async def listar_auditoria(
    acao: Optional[str] = Query(None, max_length=100),
    entidade: Optional[str] = Query(None, max_length=100),
    usuario_id: Optional[str] = Query(None, max_length=36),
    de: Optional[datetime] = None,
    ate: Optional[datetime] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("auditoria:ler")),
):
    if context.scope != ILPI_SCOPE or not context.ilpi_id:
        raise HTTPException(status_code=403, detail={"code": "ILPI_CONTEXT_REQUIRED", "message": "Selecione uma instituição."})
    q = (
        select(m.Auditoria, m.User.nome)
        .outerjoin(m.User, m.User.id == m.Auditoria.usuario_id)
        .where(m.Auditoria.ilpi_id == context.ilpi_id)
    )
    if acao:
        q = q.where(m.Auditoria.acao == acao)
    if entidade:
        q = q.where(m.Auditoria.entidade == entidade)
    if usuario_id:
        q = q.where(m.Auditoria.usuario_id == usuario_id)
    if de:
        q = q.where(m.Auditoria.created_at >= de)
    if ate:
        q = q.where(m.Auditoria.created_at <= ate)
    linhas = (await db.execute(
        q.order_by(m.Auditoria.created_at.desc(), m.Auditoria.id.desc()).offset(skip).limit(limit)
    )).all()
    return [
        AuditoriaItem(
            id=a.id, acao=a.acao, entidade=a.entidade, registro_id=a.registro_id, usuario_id=a.usuario_id,
            usuario_nome=nome, valores_anteriores=a.valores_anteriores,
            valores_posteriores=a.valores_posteriores, created_at=a.created_at,
        )
        for a, nome in linhas
    ]
