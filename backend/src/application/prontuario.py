"""D.4: Prontuario Longitudinal como PROJECAO read-only.

Sem tabela propria, sem copia de fatos, sem duplicacao.
Origens oficiais: avaliacoes, graus_dependencia, sinais_vitais,
intercorrencias, prescricoes (transicoes efetivadas), administracoes,
planos_cuidados (aprovado/vigente/encerrado/substituido), execucoes_cuidado,
ocupacao_historico, ausencias. Documentos adiados.
RBAC por origem (sem prontuario:ler). Tenant via SecurityContext.ilpi_id.
Paginacao keyset real em SQL (WHERE < cursor, ORDER BY, LIMIT), ordenador
(ocorrido_em, registrado_em, origem, registro_id, tipo) DESC.
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure import models as m
from ..infrastructure.database import get_db
from .security import (
    RESOURCE_NOT_FOUND,
    PERMISSION_DENIED,
    SecurityContext,
    ensure_same_tenant,
    get_security_context,
    require_ilpi_context,
)

prontuario_router = APIRouter(prefix="/residentes", tags=["prontuario"], dependencies=[Depends(require_ilpi_context)])

ORIGEM_PERMISSION = {
    "avaliacao": "avaliacoes:ler",
    "grau_dependencia": "grau_dependencia:ler",
    "sinal_vital": "sinais_vitais:ler",
    "intercorrencia": "intercorrencias:ler",
    "prescricao": "prescricoes:ler",
    "administracao": "administracoes:ler",
    "pais": "planos_cuidados:ler",
    "execucao_cuidado": "execucoes:ler",
    "ocupacao": "quartos_leitos:ler",
    "ausencia": "ausencias:ler",
}

ORIGEM_CATEGORIA = {
    "avaliacao": "clinico",
    "grau_dependencia": "assistencia",
    "sinal_vital": "clinico",
    "intercorrencia": "clinico",
    "prescricao": "medicacao",
    "administracao": "medicacao",
    "pais": "assistencia",
    "execucao_cuidado": "assistencia",
    "ocupacao": "administrativo",
    "ausencia": "administrativo",
}

EFFECTIVE_PAIS_STATES = {"aprovado", "vigente", "encerrado", "substituido"}

PRESCRICAO_TRANSICOES = (
    ("ativado_em", "ativada", "ativa"),
    ("suspenso_em", "suspensa", "suspensa"),
    ("substituido_em", "substituida", "substituida"),
    ("encerrado_em", "encerrada", "encerrada"),
)


def _utc(v: Optional[datetime]) -> Optional[datetime]:
    if v is None:
        return None
    if v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc)


CursorTuple = tuple[datetime, datetime, str, str, str]


def _cursor_invalid() -> HTTPException:
    return HTTPException(status_code=400, detail={"code": "CURSOR_INVALIDO", "message": "Cursor invalido"})


def _parse_cursor(cursor: Optional[str]) -> Optional[CursorTuple]:
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded).decode())
        if not isinstance(data, dict):
            raise ValueError("cursor payload invalido")
        for key in ("origem", "registro_id", "tipo"):
            value = data.get(key)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{key} invalido")
        for key in ("ocorrido_em", "registrado_em"):
            if not isinstance(data.get(key), str):
                raise ValueError(f"{key} invalido")
        ocorr = datetime.fromisoformat(data["ocorrido_em"].replace("Z", "+00:00"))
        reg = datetime.fromisoformat(data["registrado_em"].replace("Z", "+00:00"))
        if ocorr.tzinfo is None:
            ocorr = ocorr.replace(tzinfo=timezone.utc)
        if reg.tzinfo is None:
            reg = reg.replace(tzinfo=timezone.utc)
        return (ocorr, reg, data["origem"], data["registro_id"], data["tipo"])
    except Exception:
        raise _cursor_invalid()


def _encode_cursor(ocorr: datetime, reg: datetime, origem: str, registro_id: str, tipo: str) -> str:
    payload = {
        "ocorrido_em": ocorr.isoformat(),
        "registrado_em": reg.isoformat(),
        "origem": origem,
        "registro_id": registro_id,
        "tipo": tipo,
    }
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _keyset_predicate(ocorr_col, reg_col, id_col, origem_const: str, tipo_const: str, cursor: CursorTuple):
    co, cr, cg, cid, ct = cursor
    if origem_const < cg:
        return or_(ocorr_col < co, and_(ocorr_col == co, reg_col <= cr))
    if origem_const > cg:
        return or_(ocorr_col < co, and_(ocorr_col == co, reg_col < cr))
    # origem_const == cg: desempate por registro_id, com folga se o tipo desta
    # sub-query ja e conhecido como "menor" que o tipo do cursor.
    id_op = (id_col <= cid) if tipo_const < ct else (id_col < cid)
    return or_(
        ocorr_col < co,
        and_(ocorr_col == co, reg_col < cr),
        and_(ocorr_col == co, reg_col == cr, id_op),
    )


class ProntuarioEvento(BaseModel):
    origem: str
    categoria: str
    tipo: str
    registro_id: str
    residente_id: str
    ocorrido_em: datetime
    registrado_em: Optional[datetime] = None
    autor_id: Optional[str] = None
    resumo: str
    situacao: Optional[str] = None
    estornado: bool = False
    substituido: bool = False
    substituido_por: Optional[str] = None
    substituto: bool = False
    substitui_id: Optional[str] = None
    motivo_estorno: Optional[str] = None
    link: Optional[str] = None


class ProntuarioResponse(BaseModel):
    items: list[ProntuarioEvento]
    next_cursor: Optional[str] = None
    has_more: bool = False


def _event(
    ocorrido_em,
    registrado_em,
    origem,
    tipo,
    categoria,
    registro_id,
    residente_id,
    autor_id,
    resumo,
    situacao,
    link=None,
    estornado=False,
    substituido=False,
    substituido_por=None,
    substituto=False,
    substitui_id=None,
    motivo_estorno=None,
):
    return {
        "origem": origem,
        "categoria": categoria,
        "tipo": tipo,
        "registro_id": registro_id,
        "residente_id": residente_id,
        "ocorrido_em": _utc(ocorrido_em),
        "registrado_em": _utc(registrado_em) if registrado_em is not None else _utc(ocorrido_em),
        "autor_id": autor_id,
        "resumo": resumo,
        "situacao": situacao,
        "estornado": estornado,
        "substituido": substituido,
        "substituido_por": substituido_por,
        "substituto": substituto,
        "substitui_id": substitui_id,
        "motivo_estorno": motivo_estorno,
        "link": link,
    }


def _apply_keyset(q, ocorr_col, reg_col, id_col, origem_const, tipo_const, cursor_tuple, limit):
    if cursor_tuple is not None:
        q = q.where(_keyset_predicate(ocorr_col, reg_col, id_col, origem_const, tipo_const, cursor_tuple))
    return q.order_by(ocorr_col.desc(), reg_col.desc(), id_col.desc()).limit(limit + 1)


@prontuario_router.get("/{residente_id}/prontuario", response_model=ProntuarioResponse)
async def get_prontuario(
    residente_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(get_security_context),
    origem: Optional[str] = Query(None),
    categoria: Optional[str] = Query(None),
    desde: Optional[datetime] = Query(None),
    ate: Optional[datetime] = Query(None),
    situacao: Optional[str] = Query(None),
    incluir_movimentacoes: bool = Query(True),
    limit: int = Query(20, ge=1, le=100),
    cursor: Optional[str] = Query(None),
):
    # Platform bloqueado
    if context.scope != "ilpi" or context.ilpi_id is None:
        raise HTTPException(status_code=403, detail={"code": PERMISSION_DENIED, "message": "Permissao nao autorizada"})

    # Tenant residente
    residente = (await db.execute(select(m.Residente).where(m.Residente.id == residente_id))).scalar_one_or_none()
    if residente is None:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso nao encontrado"})
    ensure_same_tenant(context, residente.instituicao_id)

    # Validacao de datas
    if desde is not None and ate is not None:
        d = _utc(desde)
        a = _utc(ate)
        if d and a and d > a:
            raise HTTPException(status_code=422, detail="Intervalo de consulta invalido")
    if limit < 1 or limit > 100:
        raise HTTPException(status_code=422, detail="Limit invalido")

    # RBAC por origem
    allowed = set()
    for ori, perm in ORIGEM_PERMISSION.items():
        if perm in context.permission_keys:
            allowed.add(ori)
    # filtra por incluir_movimentacoes
    if not incluir_movimentacoes:
        allowed.discard("ocupacao")
        allowed.discard("ausencia")
    if origem is not None:
        if origem not in ORIGEM_PERMISSION:
            raise HTTPException(status_code=422, detail=f"Origem invalida: {origem}")
        if origem not in allowed:
            raise HTTPException(status_code=403, detail={"code": PERMISSION_DENIED, "message": "Permissao nao autorizada"})
        allowed = {origem}
    if categoria is not None:
        allowed = {o for o in allowed if ORIGEM_CATEGORIA.get(o) == categoria}
        if not allowed and categoria not in set(ORIGEM_CATEGORIA.values()):
            raise HTTPException(status_code=422, detail=f"Categoria invalida: {categoria}")
    if not allowed:
        raise HTTPException(status_code=403, detail={"code": PERMISSION_DENIED, "message": "Permissao nao autorizada"})

    cursor_tuple = _parse_cursor(cursor)
    tenant = context.ilpi_id
    events: list[dict[str, Any]] = []

    # Avaliacoes
    if "avaliacao" in allowed:
        q = select(m.Avaliacao).where(m.Avaliacao.ilpi_id == tenant, m.Avaliacao.residente_id == residente_id)
        if desde is not None:
            q = q.where(m.Avaliacao.data >= _utc(desde))
        if ate is not None:
            q = q.where(m.Avaliacao.data <= _utc(ate))
        if situacao is not None:
            q = q.where(or_(m.Avaliacao.tipo == situacao, m.Avaliacao.classificacao == situacao))
        q = _apply_keyset(q, m.Avaliacao.data, m.Avaliacao.data, m.Avaliacao.id, "avaliacao", "avaliacao", cursor_tuple, limit)
        rows = (await db.execute(q)).scalars().all()
        for r in rows:
            ocorr = _utc(r.data)
            events.append(_event(
                ocorrido_em=ocorr,
                registrado_em=ocorr,
                origem="avaliacao",
                tipo="avaliacao",
                categoria=ORIGEM_CATEGORIA["avaliacao"],
                registro_id=r.id,
                residente_id=residente_id,
                autor_id=r.profissional,
                resumo=f"Avaliacao {r.tipo}" + (f" - {r.classificacao}" if r.classificacao else ""),
                situacao=r.classificacao or r.tipo,
                link=f"/api/avaliacoes/{r.id}",
            ))

    # Grau dependencia
    if "grau_dependencia" in allowed:
        q = select(m.GrauDependencia).where(m.GrauDependencia.ilpi_id == tenant, m.GrauDependencia.residente_id == residente_id)
        if desde is not None:
            q = q.where(m.GrauDependencia.confirmado_em >= _utc(desde))
        if ate is not None:
            q = q.where(m.GrauDependencia.confirmado_em <= _utc(ate))
        if situacao is not None:
            q = q.where(m.GrauDependencia.situacao == situacao)
        q = _apply_keyset(q, m.GrauDependencia.confirmado_em, m.GrauDependencia.created_at, m.GrauDependencia.id, "grau_dependencia", "grau_dependencia", cursor_tuple, limit)
        rows = (await db.execute(q)).scalars().all()
        for r in rows:
            events.append(_event(
                ocorrido_em=_utc(r.confirmado_em),
                registrado_em=_utc(r.created_at),
                origem="grau_dependencia",
                tipo="grau_dependencia",
                categoria=ORIGEM_CATEGORIA["grau_dependencia"],
                registro_id=r.id,
                residente_id=residente_id,
                autor_id=r.confirmado_por,
                resumo=f"Grau {r.classificacao} ({r.situacao})",
                situacao=r.situacao,
                link=None,
                estornado=r.situacao == "revogado",
                substituido=r.situacao == "substituido",
                substituido_por=r.superseded_by,
                motivo_estorno=r.motivo_revogacao if r.situacao == "revogado" else None,
            ))

    # Sinais vitais
    if "sinal_vital" in allowed:
        q = select(m.SinalVital).where(m.SinalVital.ilpi_id == tenant, m.SinalVital.residente_id == residente_id)
        if desde is not None:
            q = q.where(m.SinalVital.data >= _utc(desde))
        if ate is not None:
            q = q.where(m.SinalVital.data <= _utc(ate))
        if situacao is not None:
            # sinais vitais nao tem conceito de situacao: filtro nunca casa
            q = q.where(m.SinalVital.id == "__none__")
        q = _apply_keyset(q, m.SinalVital.data, m.SinalVital.data, m.SinalVital.id, "sinal_vital", "sinal_vital", cursor_tuple, limit)
        rows = (await db.execute(q)).scalars().all()
        for r in rows:
            ocorr = _utc(r.data)
            parts = []
            if r.temperatura is not None:
                parts.append(f"T:{r.temperatura}")
            if r.pressao_sistolica is not None:
                parts.append(f"PA:{r.pressao_sistolica}/{r.pressao_diastolica}")
            resumo = "Sinais vitais " + ", ".join(parts) if parts else "Sinais vitais"
            events.append(_event(
                ocorrido_em=ocorr,
                registrado_em=ocorr,
                origem="sinal_vital",
                tipo="sinal_vital",
                categoria=ORIGEM_CATEGORIA["sinal_vital"],
                registro_id=r.id,
                residente_id=residente_id,
                autor_id=r.profissional,
                resumo=resumo,
                situacao=None,
                link=f"/api/sinais-vitais/{r.id}",
            ))

    # Intercorrencias
    if "intercorrencia" in allowed:
        q = select(m.Intercorrencia).where(m.Intercorrencia.ilpi_id == tenant, m.Intercorrencia.residente_id == residente_id)
        if desde is not None:
            q = q.where(m.Intercorrencia.data >= _utc(desde))
        if ate is not None:
            q = q.where(m.Intercorrencia.data <= _utc(ate))
        if situacao is not None:
            q = q.where(m.Intercorrencia.situacao == situacao)
        q = _apply_keyset(q, m.Intercorrencia.data, m.Intercorrencia.data, m.Intercorrencia.id, "intercorrencia", "intercorrencia", cursor_tuple, limit)
        rows = (await db.execute(q)).scalars().all()
        for r in rows:
            events.append(_event(
                ocorrido_em=_utc(r.data),
                registrado_em=_utc(r.data),
                origem="intercorrencia",
                tipo="intercorrencia",
                categoria=ORIGEM_CATEGORIA["intercorrencia"],
                registro_id=r.id,
                residente_id=residente_id,
                autor_id=r.responsavel,
                resumo=f"Intercorrencia {r.tipo} ({r.situacao})",
                situacao=r.situacao,
                link=f"/api/intercorrencias/{r.id}",
            ))

    # Prescricoes: um evento por transicao realmente persistida (nao por linha).
    if "prescricao" in allowed:
        for field, tipo, situ in PRESCRICAO_TRANSICOES:
            if situacao is not None and situacao != situ:
                continue
            col = getattr(m.Prescricao, field)
            q = select(m.Prescricao).where(
                m.Prescricao.ilpi_id == tenant,
                m.Prescricao.residente_id == residente_id,
                m.Prescricao.situacao != "rascunho",
                col.isnot(None),
            )
            if desde is not None:
                q = q.where(col >= _utc(desde))
            if ate is not None:
                q = q.where(col <= _utc(ate))
            q = _apply_keyset(q, col, col, m.Prescricao.id, "prescricao", tipo, cursor_tuple, limit)
            rows = (await db.execute(q)).scalars().all()
            for r in rows:
                stamp = _utc(getattr(r, field))
                events.append(_event(
                    ocorrido_em=stamp,
                    registrado_em=stamp,
                    origem="prescricao",
                    tipo=tipo,
                    categoria=ORIGEM_CATEGORIA["prescricao"],
                    registro_id=r.id,
                    residente_id=residente_id,
                    autor_id=r.autor_id,
                    resumo=f"Prescricao {situ} - {r.medicamento_id}",
                    situacao=situ,
                    link=f"/api/prescricoes/{r.id}",
                    substituido=situ == "substituida",
                ))

    # Administracoes
    if "administracao" in allowed:
        q = select(m.Administracao).where(m.Administracao.ilpi_id == tenant, m.Administracao.residente_id == residente_id)
        if desde is not None:
            q = q.where(m.Administracao.ocorrido_em >= _utc(desde))
        if ate is not None:
            q = q.where(m.Administracao.ocorrido_em <= _utc(ate))
        if situacao is not None:
            q = q.where(m.Administracao.resultado == situacao)
        q = _apply_keyset(q, m.Administracao.ocorrido_em, m.Administracao.registrado_em, m.Administracao.id, "administracao", "administracao", cursor_tuple, limit)
        rows = (await db.execute(q)).scalars().all()
        ids = [r.id for r in rows]
        substituido_por_map: dict[str, str] = {}
        if ids:
            succ = (await db.execute(
                select(m.Administracao.id, m.Administracao.substitui_id).where(
                    m.Administracao.ilpi_id == tenant,
                    m.Administracao.residente_id == residente_id,
                    m.Administracao.substitui_id.in_(ids),
                )
            )).all()
            substituido_por_map = {s.substitui_id: s.id for s in succ}
        for r in rows:
            events.append(_event(
                ocorrido_em=_utc(r.ocorrido_em),
                registrado_em=_utc(r.registrado_em),
                origem="administracao",
                tipo="administracao",
                categoria=ORIGEM_CATEGORIA["administracao"],
                registro_id=r.id,
                residente_id=residente_id,
                autor_id=r.executor_id,
                resumo=f"Administracao {r.resultado}",
                situacao=r.resultado,
                link=f"/api/administracoes/{r.id}",
                estornado=r.estornado_em is not None,
                motivo_estorno=r.motivo_estorno,
                substituto=r.substitui_id is not None,
                substitui_id=r.substitui_id,
                substituido=r.id in substituido_por_map,
                substituido_por=substituido_por_map.get(r.id),
            ))

    # PAIS (estado efetivo atual por versao; historico ja fica em linhas separadas)
    if "pais" in allowed:
        q = select(m.PlanoCuidados).where(m.PlanoCuidados.ilpi_id == tenant, m.PlanoCuidados.residente_id == residente_id, m.PlanoCuidados.situacao.in_(EFFECTIVE_PAIS_STATES))
        if situacao is not None:
            q = q.where(m.PlanoCuidados.situacao == situacao)

        def _pais_ocorr(r):
            if r.situacao in ("aprovado", "vigente"):
                return _utc(r.aprovado_em) or _utc(r.created_at)
            if r.situacao == "encerrado":
                return _utc(r.encerrado_em) or _utc(r.aprovado_em) or _utc(r.created_at)
            return _utc(r.created_at)

        # keyset SQL usa a mesma expressao de timestamp que ocorrido_em do evento,
        # garantindo que o cursor seja comparavel ao valor real exibido ao cliente.
        _pais_ocorr_col = case(
            (m.PlanoCuidados.situacao.in_(["aprovado", "vigente"]),
             func.coalesce(m.PlanoCuidados.aprovado_em, m.PlanoCuidados.created_at)),
            (m.PlanoCuidados.situacao == "encerrado",
             func.coalesce(m.PlanoCuidados.encerrado_em, m.PlanoCuidados.aprovado_em, m.PlanoCuidados.created_at)),
            else_=m.PlanoCuidados.created_at,
        )
        q = _apply_keyset(q, _pais_ocorr_col, m.PlanoCuidados.created_at, m.PlanoCuidados.id, "pais", "pais", cursor_tuple, limit)
        rows = (await db.execute(q)).scalars().all()
        for r in rows:
            ocorr = _pais_ocorr(r)
            if desde is not None and ocorr and ocorr < _utc(desde):
                continue
            if ate is not None and ocorr and ocorr > _utc(ate):
                continue
            events.append(_event(
                ocorrido_em=ocorr,
                registrado_em=_utc(r.created_at) or ocorr,
                origem="pais",
                tipo="pais",
                categoria=ORIGEM_CATEGORIA["pais"],
                registro_id=r.id,
                residente_id=residente_id,
                autor_id=r.autor_id,
                resumo=f"PAIS {r.situacao} v{r.versao}",
                situacao=r.situacao,
                link=f"/api/planos-cuidados/{r.id}",
                substituido=r.situacao == "substituido",
                substituido_por=r.superseded_by,
            ))

    # Execucoes cuidado
    if "execucao_cuidado" in allowed:
        q = select(m.ExecucaoCuidado).where(m.ExecucaoCuidado.ilpi_id == tenant, m.ExecucaoCuidado.residente_id == residente_id)
        if desde is not None:
            q = q.where(m.ExecucaoCuidado.ocorrido_em >= _utc(desde))
        if ate is not None:
            q = q.where(m.ExecucaoCuidado.ocorrido_em <= _utc(ate))
        if situacao is not None:
            q = q.where(m.ExecucaoCuidado.resultado == situacao)
        q = _apply_keyset(q, m.ExecucaoCuidado.ocorrido_em, m.ExecucaoCuidado.registrado_em, m.ExecucaoCuidado.id, "execucao_cuidado", "execucao_cuidado", cursor_tuple, limit)
        rows = (await db.execute(q)).scalars().all()
        ids = [r.id for r in rows]
        substituido_por_map = {}
        if ids:
            succ = (await db.execute(
                select(m.ExecucaoCuidado.id, m.ExecucaoCuidado.substitui_id).where(
                    m.ExecucaoCuidado.ilpi_id == tenant,
                    m.ExecucaoCuidado.residente_id == residente_id,
                    m.ExecucaoCuidado.substitui_id.in_(ids),
                )
            )).all()
            substituido_por_map = {s.substitui_id: s.id for s in succ}
        for r in rows:
            events.append(_event(
                ocorrido_em=_utc(r.ocorrido_em),
                registrado_em=_utc(r.registrado_em),
                origem="execucao_cuidado",
                tipo="execucao_cuidado",
                categoria=ORIGEM_CATEGORIA["execucao_cuidado"],
                registro_id=r.id,
                residente_id=residente_id,
                autor_id=r.executor_id,
                resumo=f"Execucao {r.resultado}",
                situacao=r.resultado,
                link=f"/api/execucoes-cuidado/{r.id}",
                estornado=r.estornado_em is not None,
                motivo_estorno=r.motivo_estorno,
                substituto=r.substitui_id is not None,
                substitui_id=r.substitui_id,
                substituido=r.id in substituido_por_map,
                substituido_por=substituido_por_map.get(r.id),
            ))

    # Ocupacao
    if "ocupacao" in allowed:
        q = select(m.OcupacaoHistorico).where(m.OcupacaoHistorico.instituicao_id == tenant, m.OcupacaoHistorico.residente_id == residente_id)
        if desde is not None:
            q = q.where(m.OcupacaoHistorico.data_entrada >= _utc(desde))
        if ate is not None:
            q = q.where(m.OcupacaoHistorico.data_entrada <= _utc(ate))
        if situacao is not None:
            q = q.where(m.OcupacaoHistorico.tipo_movimentacao == situacao)
        q = _apply_keyset(q, m.OcupacaoHistorico.data_entrada, m.OcupacaoHistorico.created_at, m.OcupacaoHistorico.id, "ocupacao", "ocupacao", cursor_tuple, limit)
        rows = (await db.execute(q)).scalars().all()
        for r in rows:
            events.append(_event(
                ocorrido_em=_utc(r.data_entrada),
                registrado_em=_utc(r.created_at) or _utc(r.data_entrada),
                origem="ocupacao",
                tipo="ocupacao",
                categoria=ORIGEM_CATEGORIA["ocupacao"],
                registro_id=r.id,
                residente_id=residente_id,
                autor_id=r.usuario_id,
                resumo=f"Ocupacao {r.tipo_movimentacao}",
                situacao=r.tipo_movimentacao,
                link=f"/api/ocupacao_historico/{r.id}",
            ))

    # Ausencias
    if "ausencia" in allowed:
        q = select(m.Ausencia).where(m.Ausencia.instituicao_id == tenant, m.Ausencia.residente_id == residente_id)
        if desde is not None:
            q = q.where(m.Ausencia.data_inicio >= _utc(desde))
        if ate is not None:
            q = q.where(m.Ausencia.data_inicio <= _utc(ate))
        if situacao is not None:
            if situacao not in ("hospitalizacao", "saida_temporaria", "ativa", "encerrada"):
                q = q.where(m.Ausencia.id == "__none__")
            elif situacao in ("hospitalizacao", "saida_temporaria"):
                q = q.where(m.Ausencia.tipo == situacao)
            elif situacao == "ativa":
                q = q.where(m.Ausencia.data_fim.is_(None))
            elif situacao == "encerrada":
                q = q.where(m.Ausencia.data_fim.isnot(None))
        q = _apply_keyset(q, m.Ausencia.data_inicio, m.Ausencia.created_at, m.Ausencia.id, "ausencia", "ausencia", cursor_tuple, limit)
        rows = (await db.execute(q)).scalars().all()
        for r in rows:
            events.append(_event(
                ocorrido_em=_utc(r.data_inicio),
                registrado_em=_utc(r.created_at) or _utc(r.data_inicio),
                origem="ausencia",
                tipo="ausencia",
                categoria=ORIGEM_CATEGORIA["ausencia"],
                registro_id=r.id,
                residente_id=residente_id,
                autor_id=r.usuario_id,
                resumo=f"Ausencia {r.tipo}",
                situacao=r.tipo,
                link=f"/api/ausencias/{r.id}",
            ))

    # filtro categoria residual (defesa extra; allowed ja restringe por origem)
    if categoria is not None:
        events = [e for e in events if e["categoria"] == categoria]

    # ordenacao global estavel DESC pela 5-tupla (ocorrido_em, registrado_em, origem, registro_id, tipo)
    def sort_key(e):
        return (
            e["ocorrido_em"] or datetime.min.replace(tzinfo=timezone.utc),
            e["registrado_em"] or datetime.min.replace(tzinfo=timezone.utc),
            e["origem"],
            e["registro_id"],
            e["tipo"],
        )

    events.sort(key=sort_key, reverse=True)

    # deduplicacao defesa: garante chave unica (origem, registro_id, tipo)
    seen = set()
    deduped = []
    for e in events:
        key = (e["origem"], e["registro_id"], e["tipo"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(e)
    events = deduped

    has_more = len(events) > limit
    page = events[:limit]
    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = _encode_cursor(last["ocorrido_em"], last["registrado_em"] or last["ocorrido_em"], last["origem"], last["registro_id"], last["tipo"])

    items = [ProntuarioEvento(**e) for e in page]
    return ProntuarioResponse(items=items, next_cursor=next_cursor, has_more=has_more)
