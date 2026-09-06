"""F5A-2D: Quarto/Leito + Ocupação + Ausências + Histórico.

Custom routers for quartos_leitos (with allocate/release/transfer operations),
ausencias (with close operation), and ocupacao_historico (read-only).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select, and_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure.database import get_db
from ..infrastructure import models as m
from ..application import schemas as s
from ..application.audit import add_audit
from ..application.security import (
    RESOURCE_NOT_FOUND,
    SecurityContext,
    ensure_same_tenant,
    get_security_context,
    require_permission,
)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# ===== QuartoLeito Router =====

quartos_leitos_router = APIRouter(prefix="/quartos_leitos", tags=["quartos_leitos"])


@quartos_leitos_router.get("/", response_model=list[s.QuartoLeitoResponse])
async def list_quartos_leitos(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("quartos_leitos:ler")),
):
    query = (
        select(m.QuartoLeito)
        .where(m.QuartoLeito.instituicao_id == context.ilpi_id)
        .order_by(m.QuartoLeito.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    return result.scalars().all()


@quartos_leitos_router.get("/{leito_id}", response_model=s.QuartoLeitoResponse)
async def get_quarto_leito(
    leito_id: str,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("quartos_leitos:ler")),
):
    result = await db.execute(
        select(m.QuartoLeito).where(
            m.QuartoLeito.id == leito_id,
            m.QuartoLeito.instituicao_id == context.ilpi_id,
        )
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})
    return obj


@quartos_leitos_router.post("/", response_model=s.QuartoLeitoResponse, status_code=201)
async def create_quarto_leito(
    payload: s.QuartoLeitoCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("quartos_leitos:criar")),
):
    data = payload.model_dump(exclude_unset=True)
    data["instituicao_id"] = context.ilpi_id
    data["capacidade"] = 1
    obj = m.QuartoLeito(**data)
    db.add(obj)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Já existe leito com esta combinação de quarto/leito nesta ILPI")
    add_audit(
        db,
        acao="quartos_leitos.criar",
        entidade="quartos_leitos",
        registro_id=obj.id,
        usuario_id=context.user.id,
        ilpi_id=context.ilpi_id,
        valores_posteriores=data,
        request=request,
    )
    await db.commit()
    await db.refresh(obj)
    return obj


@quartos_leitos_router.put("/{leito_id}", response_model=s.QuartoLeitoResponse)
async def update_quarto_leito(
    leito_id: str,
    payload: s.QuartoLeitoUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("quartos_leitos:atualizar")),
):
    result = await db.execute(
        select(m.QuartoLeito).where(
            m.QuartoLeito.id == leito_id,
            m.QuartoLeito.instituicao_id == context.ilpi_id,
        )
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})

    old_vals = {c: getattr(obj, c) for c in ("unidade", "quarto", "leito", "acessibilidade", "situacao")}
    data = payload.model_dump(exclude_unset=True)
    data.pop("instituicao_id", None)
    data.pop("residente_atual_id", None)
    data.pop("capacidade", None)
    for k, v in data.items():
        setattr(obj, k, v)
    new_vals = {c: getattr(obj, c) for c in ("unidade", "quarto", "leito", "acessibilidade", "situacao")}

    add_audit(
        db,
        acao="quartos_leitos.atualizar",
        entidade="quartos_leitos",
        registro_id=obj.id,
        usuario_id=context.user.id,
        ilpi_id=context.ilpi_id,
        valores_anteriores=old_vals,
        valores_posteriores=new_vals,
        request=request,
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Já existe leito com esta combinação de quarto/leito nesta ILPI")
    await db.refresh(obj)
    return obj


@quartos_leitos_router.post("/{leito_id}/inativar", response_model=s.QuartoLeitoResponse)
async def inativar_quarto_leito(
    leito_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("quartos_leitos:inativar")),
):
    result = await db.execute(
        select(m.QuartoLeito).where(
            m.QuartoLeito.id == leito_id,
            m.QuartoLeito.instituicao_id == context.ilpi_id,
        )
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})
    if obj.residente_atual_id is not None:
        raise HTTPException(status_code=409, detail="Não é possível inativar leito com residente ocupante")

    old_situacao = obj.situacao
    obj.situacao = "inativo"
    add_audit(
        db,
        acao="quartos_leitos.inativar",
        entidade="quartos_leitos",
        registro_id=obj.id,
        usuario_id=context.user.id,
        ilpi_id=context.ilpi_id,
        valores_anteriores={"situacao": old_situacao},
        valores_posteriores={"situacao": "inativo"},
        request=request,
    )
    await db.commit()
    await db.refresh(obj)
    return obj


@quartos_leitos_router.post("/{leito_id}/alocar", response_model=s.QuartoLeitoResponse)
async def alocar_residente(
    leito_id: str,
    payload: s.QuartoLeitoAlocar,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("quartos_leitos:atualizar")),
):
    # 1. Find the bed
    result = await db.execute(
        select(m.QuartoLeito).where(
            m.QuartoLeito.id == leito_id,
            m.QuartoLeito.instituicao_id == context.ilpi_id,
        )
    )
    leito = result.scalar_one_or_none()
    if not leito:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})

    # 2. Bed must be 'livre'
    if leito.situacao != "livre":
        raise HTTPException(status_code=409, detail="Leito não está livre para alocação")
    if leito.residente_atual_id is not None:
        raise HTTPException(status_code=409, detail="Leito já possui residente")

    # 3. Find the resident in same tenant
    resident_result = await db.execute(
        select(m.Residente).where(
            m.Residente.id == payload.residente_id,
            m.Residente.instituicao_id == context.ilpi_id,
        )
    )
    residente = resident_result.scalar_one_or_none()
    if not residente:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})

    # 4. Check resident doesn't already have a bed
    existing_bed = (
        await db.execute(
            select(m.QuartoLeito).where(
                m.QuartoLeito.residente_atual_id == payload.residente_id,
                m.QuartoLeito.instituicao_id == context.ilpi_id,
            )
        )
    ).scalar_one_or_none()
    if existing_bed:
        raise HTTPException(status_code=409, detail="Residente já possui leito ocupado")

    # 5. Allocate
    now = _now_utc()
    old_vals = {c: getattr(leito, c) for c in ("residente_atual_id", "situacao", "data_ocupacao")}
    leito.residente_atual_id = payload.residente_id
    leito.situacao = "livre"  # ocupado is derived from residente_atual_id IS NOT NULL
    leito.data_ocupacao = now

    # 6. Create history
    historico = m.OcupacaoHistorico(
        instituicao_id=context.ilpi_id,
        residente_id=payload.residente_id,
        quarto_leito_id=leito_id,
        data_entrada=now,
        tipo_movimentacao="alocacao",
        usuario_id=context.user.id,
    )
    db.add(historico)

    add_audit(
        db,
        acao="quartos_leitos.alocar",
        entidade="quartos_leitos",
        registro_id=leito.id,
        usuario_id=context.user.id,
        ilpi_id=context.ilpi_id,
        valores_anteriores=old_vals,
        valores_posteriores={"residente_atual_id": payload.residente_id, "data_ocupacao": now.isoformat()},
        request=request,
    )
    await db.commit()
    await db.refresh(leito)
    return leito


@quartos_leitos_router.post("/{leito_id}/liberar", response_model=s.QuartoLeitoResponse)
async def liberar_leito(
    leito_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("quartos_leitos:atualizar")),
):
    result = await db.execute(
        select(m.QuartoLeito).where(
            m.QuartoLeito.id == leito_id,
            m.QuartoLeito.instituicao_id == context.ilpi_id,
        )
    )
    leito = result.scalar_one_or_none()
    if not leito:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})
    if leito.residente_atual_id is None:
        raise HTTPException(status_code=409, detail="Leito não possui residente para liberar")

    now = _now_utc()
    old_vals = {"residente_atual_id": leito.residente_atual_id, "data_ocupacao": str(leito.data_ocupacao)}

    # Close history
    hist_result = await db.execute(
        select(m.OcupacaoHistorico).where(
            m.OcupacaoHistorico.quarto_leito_id == leito_id,
            m.OcupacaoHistorico.instituicao_id == context.ilpi_id,
            m.OcupacaoHistorico.residente_id == leito.residente_atual_id,
            m.OcupacaoHistorico.data_saida.is_(None),
        ).order_by(m.OcupacaoHistorico.data_entrada.desc())
    )
    historico = hist_result.scalar_one_or_none()
    if historico:
        historico.data_saida = now

    leito.residente_atual_id = None
    leito.data_ocupacao = None

    add_audit(
        db,
        acao="quartos_leitos.liberar",
        entidade="quartos_leitos",
        registro_id=leito.id,
        usuario_id=context.user.id,
        ilpi_id=context.ilpi_id,
        valores_anteriores=old_vals,
        valores_posteriores={"residente_atual_id": None, "data_ocupacao": None},
        request=request,
    )
    await db.commit()
    await db.refresh(leito)
    return leito


@quartos_leitos_router.post("/transferencia", response_model=s.QuartoLeitoResponse)
async def transferir_residente(
    payload: s.TransferenciaRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("quartos_leitos:atualizar")),
):
    now = _now_utc()

    # 1. Find resident in same tenant
    resident_result = await db.execute(
        select(m.Residente).where(
            m.Residente.id == payload.residente_id,
            m.Residente.instituicao_id == context.ilpi_id,
        )
    )
    residente = resident_result.scalar_one_or_none()
    if not residente:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})

    # 2. Find current bed
    origem_result = await db.execute(
        select(m.QuartoLeito).where(
            m.QuartoLeito.residente_atual_id == payload.residente_id,
            m.QuartoLeito.instituicao_id == context.ilpi_id,
        )
    )
    origem = origem_result.scalar_one_or_none()
    if not origem:
        raise HTTPException(status_code=409, detail="Residente não possui leito para transferir")

    # 3. Find destination bed
    destino_result = await db.execute(
        select(m.QuartoLeito).where(
            m.QuartoLeito.id == payload.novo_leito_id,
            m.QuartoLeito.instituicao_id == context.ilpi_id,
        )
    )
    destino = destino_result.scalar_one_or_none()
    if not destino:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})

    # 4. Validate destination
    if destino.id == origem.id:
        raise HTTPException(status_code=409, detail="Leito de origem e destino não podem ser o mesmo")
    if destino.situacao != "livre":
        raise HTTPException(status_code=409, detail="Leito destino não está livre para transferência")
    if destino.residente_atual_id is not None:
        raise HTTPException(status_code=409, detail="Leito destino já possui residente")

    # 5. Close old history
    hist_result = await db.execute(
        select(m.OcupacaoHistorico).where(
            m.OcupacaoHistorico.quarto_leito_id == origem.id,
            m.OcupacaoHistorico.instituicao_id == context.ilpi_id,
            m.OcupacaoHistorico.residente_id == payload.residente_id,
            m.OcupacaoHistorico.data_saida.is_(None),
        ).order_by(m.OcupacaoHistorico.data_entrada.desc())
    )
    hist_origem = hist_result.scalar_one_or_none()
    if hist_origem:
        hist_origem.data_saida = now

    # 6. Release origin — flush first so SQLite unique index sees NULL before assign
    origem.residente_atual_id = None
    origem.data_ocupacao = None
    await db.flush()

    # 7. Occupy destination
    destino.residente_atual_id = payload.residente_id
    destino.data_ocupacao = now

    # 8. Create new history
    historico_destino = m.OcupacaoHistorico(
        instituicao_id=context.ilpi_id,
        residente_id=payload.residente_id,
        quarto_leito_id=destino.id,
        data_entrada=now,
        tipo_movimentacao="transferencia",
        motivo=payload.motivo,
        usuario_id=context.user.id,
    )
    db.add(historico_destino)

    add_audit(
        db,
        acao="quartos_leitos.transferencia",
        entidade="quartos_leitos",
        registro_id=destino.id,
        usuario_id=context.user.id,
        ilpi_id=context.ilpi_id,
        valores_anteriores={"origem_id": origem.id, "destino_id": destino.id},
        valores_posteriores={"residente_id": payload.residente_id, "novo_leito_id": destino.id},
        request=request,
    )
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Conflito de integridade durante transferência")
    await db.refresh(destino)
    return destino


# ===== Ausencia Router =====

ausencias_router = APIRouter(prefix="/ausencias", tags=["ausencias"])


@ausencias_router.get("/", response_model=list[s.AusenciaResponse])
async def list_ausencias(
    skip: int = 0,
    limit: int = 100,
    residente_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("ausencias:ler")),
):
    query = select(m.Ausencia).where(m.Ausencia.instituicao_id == context.ilpi_id)
    if residente_id:
        query = query.where(m.Ausencia.residente_id == residente_id)
    query = query.order_by(m.Ausencia.created_at.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@ausencias_router.get("/{ausencia_id}", response_model=s.AusenciaResponse)
async def get_ausencia(
    ausencia_id: str,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("ausencias:ler")),
):
    result = await db.execute(
        select(m.Ausencia).where(
            m.Ausencia.id == ausencia_id,
            m.Ausencia.instituicao_id == context.ilpi_id,
        )
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})
    return obj


@ausencias_router.post("/", response_model=s.AusenciaResponse, status_code=201)
async def create_ausencia(
    payload: s.AusenciaCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("ausencias:criar")),
):
    # 1. Check resident in same tenant
    resident_result = await db.execute(
        select(m.Residente).where(
            m.Residente.id == payload.residente_id,
            m.Residente.instituicao_id == context.ilpi_id,
        )
    )
    residente = resident_result.scalar_one_or_none()
    if not residente:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})

    # 2. Check no active absence exists
    active = (
        await db.execute(
            select(m.Ausencia).where(
                m.Ausencia.residente_id == payload.residente_id,
                m.Ausencia.instituicao_id == context.ilpi_id,
                m.Ausencia.data_fim.is_(None),
            )
        )
    ).scalar_one_or_none()
    if active:
        raise HTTPException(status_code=409, detail="Residente já possui ausência ativa")

    # 3. Validate quarto_leito_id if provided
    if payload.quarto_leito_id:
        leito_result = await db.execute(
            select(m.QuartoLeito).where(
                m.QuartoLeito.id == payload.quarto_leito_id,
                m.QuartoLeito.instituicao_id == context.ilpi_id,
            )
        )
        if not leito_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})

    now = _now_utc()
    data = payload.model_dump(exclude_unset=True)
    data["instituicao_id"] = context.ilpi_id
    data["usuario_id"] = context.user.id
    data["data_inicio"] = now

    obj = m.Ausencia(**data)
    db.add(obj)
    await db.flush()

    add_audit(
        db,
        acao="ausencias.criar",
        entidade="ausencias",
        registro_id=obj.id,
        usuario_id=context.user.id,
        ilpi_id=context.ilpi_id,
        valores_posteriores=data,
        request=request,
    )
    await db.commit()
    await db.refresh(obj)
    return obj


@ausencias_router.post("/{ausencia_id}/encerrar", response_model=s.AusenciaResponse)
async def encerrar_ausencia(
    ausencia_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("ausencias:atualizar")),
):
    result = await db.execute(
        select(m.Ausencia).where(
            m.Ausencia.id == ausencia_id,
            m.Ausencia.instituicao_id == context.ilpi_id,
        )
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})
    if obj.data_fim is not None:
        raise HTTPException(status_code=409, detail="Ausência já está encerrada")

    now = _now_utc()
    old_fim = obj.data_fim
    obj.data_fim = now

    add_audit(
        db,
        acao="ausencias.encerrar",
        entidade="ausencias",
        registro_id=obj.id,
        usuario_id=context.user.id,
        ilpi_id=context.ilpi_id,
        valores_anteriores={"data_fim": None},
        valores_posteriores={"data_fim": now.isoformat()},
        request=request,
    )
    await db.commit()
    await db.refresh(obj)
    return obj


# ===== OcupacaoHistorico Router (read-only) =====

ocupacao_historico_router = APIRouter(prefix="/ocupacao_historico", tags=["ocupacao_historico"])


@ocupacao_historico_router.get("/", response_model=list[s.OcupacaoHistoricoResponse])
async def list_ocupacao_historico(
    skip: int = 0,
    limit: int = 100,
    residente_id: Optional[str] = None,
    quarto_leito_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("quartos_leitos:ler")),
):
    query = select(m.OcupacaoHistorico).where(m.OcupacaoHistorico.instituicao_id == context.ilpi_id)
    if residente_id:
        query = query.where(m.OcupacaoHistorico.residente_id == residente_id)
    if quarto_leito_id:
        query = query.where(m.OcupacaoHistorico.quarto_leito_id == quarto_leito_id)
    query = query.order_by(m.OcupacaoHistorico.data_entrada.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@ocupacao_historico_router.get("/{historico_id}", response_model=s.OcupacaoHistoricoResponse)
async def get_ocupacao_historico(
    historico_id: str,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("quartos_leitos:ler")),
):
    result = await db.execute(
        select(m.OcupacaoHistorico).where(
            m.OcupacaoHistorico.id == historico_id,
            m.OcupacaoHistorico.instituicao_id == context.ilpi_id,
        )
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})
    return obj
