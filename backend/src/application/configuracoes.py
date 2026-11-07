"""Configuracoes da instituicao (complementar D5): sempre a ILPI da sessao.

Razao social, CNPJ e situacao nao se editam aqui: pertencem ao fluxo da Plataforma.
"""

from __future__ import annotations

from datetime import date
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure import models as m
from ..infrastructure.database import get_db
from .audit import add_audit
from .security import SecurityContext, require_permission

configuracoes_router = APIRouter(prefix="/configuracoes", tags=["configuracoes"])


class ConfiguracoesUpdate(BaseModel):
    nome_fantasia: Optional[str] = Field(None, max_length=255)
    endereco: Optional[str] = None
    municipio: Optional[str] = Field(None, max_length=255)
    uf: Optional[str] = Field(None, max_length=2)
    telefone: Optional[str] = Field(None, max_length=20)
    email: Optional[EmailStr] = None
    responsavel_legal: Optional[str] = Field(None, max_length=255)
    responsavel_tecnico: Optional[str] = Field(None, max_length=255)
    capacidade: Optional[int] = Field(None, gt=0)
    licenca_sanitaria: Optional[str] = Field(None, max_length=100)
    validade_licenca: Optional[date] = None
    fuso_horario: Optional[str] = Field(None, max_length=64)

    @field_validator("*", mode="before")
    @classmethod
    def _vazio_vira_nulo(cls, v):
        if isinstance(v, str):
            return v.strip() or None
        return v

    @field_validator("uf")
    @classmethod
    def _uf(cls, v):
        if v is None:
            return v
        if len(v) != 2 or not v.isalpha():
            raise ValueError("UF invalida")
        return v.upper()

    @field_validator("fuso_horario")
    @classmethod
    def _fuso(cls, v):
        if v is None:
            return v
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError, OSError):
            raise ValueError("Fuso horario invalido")
        return v


class ConfiguracoesResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    razao_social: str
    cnpj: Optional[str] = None
    situacao: str
    nome_fantasia: Optional[str] = None
    endereco: Optional[str] = None
    municipio: Optional[str] = None
    uf: Optional[str] = None
    telefone: Optional[str] = None
    email: Optional[str] = None
    responsavel_legal: Optional[str] = None
    responsavel_tecnico: Optional[str] = None
    capacidade: Optional[int] = None
    licenca_sanitaria: Optional[str] = None
    validade_licenca: Optional[date] = None
    fuso_horario: Optional[str] = None


async def _ilpi(db: AsyncSession, context: SecurityContext) -> m.Instituicao:
    return (await db.execute(select(m.Instituicao).where(m.Instituicao.id == context.ilpi_id))).scalar_one()


@configuracoes_router.get("/", response_model=ConfiguracoesResponse)
async def ler_configuracoes(
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("configuracoes:ler")),
):
    return await _ilpi(db, context)


@configuracoes_router.put("/", response_model=ConfiguracoesResponse)
async def atualizar_configuracoes(
    payload: ConfiguracoesUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("configuracoes:atualizar")),
):
    obj = await _ilpi(db, context)
    dados = payload.model_dump(exclude_unset=True)
    if "fuso_horario" in dados and dados["fuso_horario"] is None:
        dados.pop("fuso_horario")  # toda ILPI tem fuso: vazio nao apaga.
    antes = {k: getattr(obj, k) for k in dados}
    for k, v in dados.items():
        setattr(obj, k, v)
    add_audit(db, acao="configuracoes.atualizadas", entidade="instituicoes", registro_id=obj.id,
              usuario_id=context.user.id, ilpi_id=context.ilpi_id,
              valores_anteriores=antes, valores_posteriores=dados, request=request)
    await db.commit()
    await db.refresh(obj)
    return obj
