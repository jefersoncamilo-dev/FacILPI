"""UX-02 (#85): resumo do Dashboard — espelho da instituicao, so leitura.

Cada numero e uma contagem de fatos oficiais ja existentes, feita no banco e
filtrada pela ILPI da sessao (nunca por parametro do cliente). Cada bloco so e
calculado se o contexto puder ler o modulo de origem — mesmo predicado do
`require_permission` —; sem permissao o bloco vem `None` e a tela nao o exibe.

Nao ha metrica inventada: ocupacao segue a regra do modulo de leitos
(ocupado = `residente_atual_id` preenchido), ausencia ativa e `data_fim` nulo,
e a situacao do residente (nao governada, #76) nao e usada — so o total.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure import models as m
from ..infrastructure.database import get_db
from . import schemas as s
from .security import SecurityContext, allowed_permission_keys, require_ilpi_context

dashboard_router = APIRouter(prefix="/dashboard", tags=["dashboard"])

ADMISSAO_ENCERRADA = ("concluida", "cancelada", "desistencia")
LEITO_INDISPONIVEL = ("reservado", "bloqueado", "manutencao")


async def _contar(db: AsyncSession, model, *condicoes) -> int:
    return (await db.execute(select(func.count()).select_from(model).where(*condicoes))).scalar_one()


async def _por_situacao(db: AsyncSession, coluna, *condicoes) -> dict[str, int]:
    linhas = (await db.execute(select(coluna, func.count()).where(*condicoes).group_by(coluna))).all()
    return {situacao: total for situacao, total in linhas}


@dashboard_router.get("/resumo", response_model=s.DashboardResumoResponse)
async def resumo(
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_ilpi_context),
):
    chaves = set(await allowed_permission_keys(db, context))
    ilpi = context.ilpi_id
    resposta: dict = {"gerado_em": datetime.now(timezone.utc)}

    if "residentes:ler" in chaves:
        resposta["residentes_total"] = await _contar(db, m.Residente, m.Residente.instituicao_id == ilpi)

    if "quartos_leitos:ler" in chaves:
        leito = m.QuartoLeito
        do_ilpi = leito.instituicao_id == ilpi
        sem_ocupante = leito.residente_atual_id.is_(None)
        resposta["ocupacao"] = {
            "leitos_ativos": await _contar(db, leito, do_ilpi, leito.situacao != "inativo"),
            "ocupados": await _contar(db, leito, do_ilpi, leito.residente_atual_id.is_not(None)),
            "livres": await _contar(db, leito, do_ilpi, sem_ocupante, leito.situacao == "livre"),
            "indisponiveis": await _contar(
                db, leito, do_ilpi, sem_ocupante, leito.situacao.in_(LEITO_INDISPONIVEL)
            ),
        }

    if "ausencias:ler" in chaves:
        ativa = (m.Ausencia.instituicao_id == ilpi, m.Ausencia.data_fim.is_(None))
        resposta["ausencias_ativas"] = {
            "total": await _contar(db, m.Ausencia, *ativa),
            "hospitalizacoes": await _contar(db, m.Ausencia, *ativa, m.Ausencia.tipo == "hospitalizacao"),
        }

    if "intercorrencias:ler" in chaves:
        resposta["intercorrencias_abertas"] = await _contar(
            db, m.Intercorrencia, m.Intercorrencia.ilpi_id == ilpi, m.Intercorrencia.situacao == "aberta"
        )

    if "admissoes:ler" in chaves:
        resposta["admissoes_em_andamento"] = await _contar(
            db, m.Admissao, m.Admissao.ilpi_id == ilpi, m.Admissao.situacao.not_in(ADMISSAO_ENCERRADA)
        )

    if "planos_cuidados:ler" in chaves:
        planos = await _por_situacao(db, m.PlanoCuidados.situacao, m.PlanoCuidados.ilpi_id == ilpi)
        resposta["planos"] = {
            "vigentes": planos.get("vigente", 0),
            "em_revisao": planos.get("em_revisao", 0),
            "em_elaboracao": planos.get("rascunho", 0) + planos.get("em_elaboracao", 0),
            "aprovados_aguardando_vigencia": planos.get("aprovado", 0),
        }

    if "funcionarios:ler" in chaves:
        equipe = await _por_situacao(db, m.Funcionario.situacao, m.Funcionario.ilpi_id == ilpi)
        resposta["equipe"] = {"ativos": equipe.get("ativo", 0), "afastados": equipe.get("afastado", 0)}

    return resposta
