"""#15 (034, D3 = opcao B): transicao das escritas clinicas do ilpi_admin.

Dois pontos, ambos so leitura:
- ``GET /transicao-clinica/``: a ILPI da sessao ve o prazo e se ja tem perfil
  clinico atribuido (a tela mostra o aviso ao administrador);
- ``GET /platform/transicao-clinica``: relatorio por ILPI para o Platform, antes
  do corte: o que cada uma perde e se ja tem perfil clinico atribuido.

"Perfil clinico atribuido" = vinculo ativo e vigente, na ILPI, a um perfil ativo
que nao e o ilpi_admin e que tem ao menos uma das escritas clinicas retiradas.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure import models as m
from ..infrastructure.database import get_db
from . import schemas as s
from .fase3a import _require_global_context
from .security import (
    ESCRITAS_CLINICAS_ADMIN,
    ILPI_ADMIN_KEY,
    SecurityContext,
    require_ilpi_context,
    require_permission,
)

transicao_router = APIRouter(prefix="/transicao-clinica", tags=["transicao-clinica"])
platform_transicao_router = APIRouter(prefix="/platform", tags=["platform"])

_ESCRITAS = sorted(ESCRITAS_CLINICAS_ADMIN)


def _utc(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def _ilpis_com_perfil_clinico(db: AsyncSession, ilpi_ids: list[str]) -> set[str]:
    if not ilpi_ids:
        return set()
    agora = datetime.now(timezone.utc)
    rows = await db.execute(
        select(m.UsuarioIlpiPerfil.ilpi_id)
        .join(m.Perfil, m.Perfil.id == m.UsuarioIlpiPerfil.perfil_id)
        .join(m.PerfilPermissao, m.PerfilPermissao.perfil_id == m.Perfil.id)
        .join(m.Permissao, m.Permissao.id == m.PerfilPermissao.permissao_id)
        .join(m.User, m.User.id == m.UsuarioIlpiPerfil.usuario_id)
        .where(
            m.UsuarioIlpiPerfil.ilpi_id.in_(ilpi_ids),
            m.UsuarioIlpiPerfil.situacao == "ativo",
            or_(m.UsuarioIlpiPerfil.data_inicial.is_(None), m.UsuarioIlpiPerfil.data_inicial <= agora),
            or_(m.UsuarioIlpiPerfil.data_final.is_(None), m.UsuarioIlpiPerfil.data_final > agora),
            m.User.ativo.is_(True),
            m.Perfil.situacao == "ativo",
            m.Perfil.chave != ILPI_ADMIN_KEY,
            m.Permissao.chave.in_(_ESCRITAS),
        )
        .distinct()
    )
    return set(rows.scalars().all())


def _situacao(prazo: datetime | None, agora: datetime) -> tuple[datetime | None, bool]:
    prazo = _utc(prazo)
    return prazo, bool(prazo and prazo > agora)


@transicao_router.get("/", response_model=s.TransicaoClinicaResponse)
async def situacao_da_ilpi(
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_ilpi_context),
):
    prazo = (await db.execute(select(m.TransicaoAdminClinico.prazo).where(
        m.TransicaoAdminClinico.ilpi_id == context.ilpi_id))).scalar_one_or_none()
    prazo, em_carencia = _situacao(prazo, datetime.now(timezone.utc))
    return {
        "afeta_esta_sessao": context.perfil.chave == ILPI_ADMIN_KEY,
        "prazo": prazo,
        "em_carencia": em_carencia,
        "perfil_clinico_atribuido": context.ilpi_id in await _ilpis_com_perfil_clinico(db, [context.ilpi_id]),
        "escritas_retiradas": _ESCRITAS,
    }


@platform_transicao_router.get("/transicao-clinica", response_model=list[s.TransicaoClinicaIlpi])
async def relatorio_por_ilpi(
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("ilpis:ler")),
):
    _require_global_context(context)
    ilpis = (await db.execute(select(m.Instituicao).order_by(m.Instituicao.razao_social, m.Instituicao.id))).scalars().all()
    ids = [ilpi.id for ilpi in ilpis]
    prazos = dict((await db.execute(select(m.TransicaoAdminClinico.ilpi_id, m.TransicaoAdminClinico.prazo).where(
        m.TransicaoAdminClinico.ilpi_id.in_(ids)))).all()) if ids else {}
    com_perfil = await _ilpis_com_perfil_clinico(db, ids)
    agora = datetime.now(timezone.utc)
    relatorio = []
    for ilpi in ilpis:
        prazo, em_carencia = _situacao(prazos.get(ilpi.id), agora)
        relatorio.append({
            "ilpi_id": ilpi.id,
            "nome": ilpi.nome_fantasia or ilpi.razao_social,
            "situacao": ilpi.situacao,
            "prazo": prazo,
            "em_carencia": em_carencia,
            "perfil_clinico_atribuido": ilpi.id in com_perfil,
            "escritas_que_o_administrador_perde": _ESCRITAS,
        })
    return relatorio
