"""Saida do residente (N2, #171, migration 030).

Obito, transferencia, desligamento ou retorno a familia, registrados de forma
auditavel com o autor da sessao. Regras (DOMAIN_RULES §Saida do residente):

- So residente "Ativo" sai; uma saida vigente por residente (indice parcial).
- A situacao do residente muda na mesma transacao do registro.
- O leito so e liberado por escolha explicita de quem registra, e so com
  ``quartos_leitos:atualizar``; nada e liberado sozinho.
- PAIS, prescricoes e programacoes nao sao encerrados aqui: a tela lista as
  pendencias e cada uma segue a acao humana do proprio modulo.
- Estorno preserva o registro original e devolve o residente a "Ativo"; o leito
  nao volta sozinho.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AwareDatetime, BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure import models as m
from ..infrastructure.database import get_db
from .audit import add_audit
from .fase5a2d import liberar_leito_ocupado
from .security import RESOURCE_NOT_FOUND, SecurityContext, require_permission

router = APIRouter(prefix="/residentes", tags=["residentes"])

RESIDENTE_ATIVO = "Ativo"
SITUACAO_POR_TIPO = {
    "obito": "Falecido",
    "transferencia": "Transferido",
    "desligamento": "Desligado",
    "retorno_familia": "Retornou a familia",
}
# Fonte unica das situacoes de quem saiu; alertas e turno filtram por elas.
SITUACOES_SAIDA = tuple(SITUACAO_POR_TIPO.values())
TipoSaida = Literal["obito", "transferencia", "desligamento", "retorno_familia"]


class SaidaCreate(BaseModel):
    tipo: TipoSaida
    ocorrido_em: AwareDatetime
    local_obito: Optional[Literal["ilpi", "hospital"]] = None
    destino_tipo: Optional[Literal["instituicao", "hospital"]] = None
    destino_descricao: Optional[str] = Field(None, max_length=255)
    motivo_desligamento: Optional[Literal["fim_contrato", "pedido_familia", "pedido_residente", "pedido_ilpi"]] = None
    observacao: Optional[str] = Field(None, max_length=500)
    liberar_leito: bool = False

    @model_validator(mode="after")
    def _campos_do_tipo(self):
        if self.destino_descricao is not None:
            self.destino_descricao = self.destino_descricao.strip() or None
        if self.tipo == "obito" and self.local_obito is None:
            raise ValueError("Óbito exige o local (ILPI ou hospital)")
        if self.tipo == "transferencia" and (self.destino_tipo is None or not self.destino_descricao):
            raise ValueError("Transferência exige o tipo e a descrição do destino")
        if self.tipo == "desligamento" and self.motivo_desligamento is None:
            raise ValueError("Desligamento exige o motivo")
        # Campos de outro tipo nao entram no registro.
        if self.tipo != "obito":
            self.local_obito = None
        if self.tipo != "transferencia":
            self.destino_tipo = self.destino_descricao = None
        if self.tipo != "desligamento":
            self.motivo_desligamento = None
        return self


class SaidaEstorno(BaseModel):
    motivo: str = Field(..., min_length=3, max_length=500)


class SaidaResponse(BaseModel):
    id: str
    residente_id: str
    tipo: str
    ocorrido_em: datetime
    local_obito: Optional[str] = None
    destino_tipo: Optional[str] = None
    destino_descricao: Optional[str] = None
    motivo_desligamento: Optional[str] = None
    observacao: Optional[str] = None
    registrado_por: str
    registrado_em: datetime
    estornado_em: Optional[datetime] = None
    estornado_por: Optional[str] = None
    motivo_estorno: Optional[str] = None
    situacao_residente: str
    leito_liberado: bool = False

    model_config = {"from_attributes": True}


class Pendencia(BaseModel):
    origem: str
    registro_id: str
    descricao: str
    link: Optional[str] = None


class PendenciasResponse(BaseModel):
    pendencias: list[Pendencia]
    # Origens que quem consulta nao pode ler: a lista nao afirma que estao vazias.
    origens_sem_leitura: list[str]


def _nao_encontrado() -> HTTPException:
    return HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})


async def _residente(db: AsyncSession, context: SecurityContext, residente_id: str) -> m.Residente:
    # Tenant na propria consulta: id de outra ILPI e id inexistente dao o mesmo 404.
    residente = (await db.execute(select(m.Residente).where(
        m.Residente.id == residente_id, m.Residente.instituicao_id == context.ilpi_id))).scalar_one_or_none()
    if residente is None:
        raise _nao_encontrado()
    return residente


async def _saida_vigente(db: AsyncSession, context: SecurityContext, residente_id: str) -> Optional[m.ResidenteSaida]:
    return (await db.execute(select(m.ResidenteSaida).where(
        m.ResidenteSaida.ilpi_id == context.ilpi_id,
        m.ResidenteSaida.residente_id == residente_id,
        m.ResidenteSaida.estornado_em.is_(None)))).scalar_one_or_none()


def _resposta(saida: m.ResidenteSaida, situacao: str, leito_liberado: bool = False) -> SaidaResponse:
    return SaidaResponse(**{c: getattr(saida, c) for c in SaidaResponse.model_fields if hasattr(saida, c)},
                         situacao_residente=situacao, leito_liberado=leito_liberado)


@router.post("/{residente_id}/saida", response_model=SaidaResponse, status_code=201)
async def registrar_saida(
    residente_id: str,
    payload: SaidaCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("residentes:registrar_saida")),
):
    residente = await _residente(db, context, residente_id)
    if residente.situacao != RESIDENTE_ATIVO:
        raise HTTPException(status_code=409, detail="Só residente ativo pode ter a saída registrada")
    if payload.ocorrido_em > datetime.now(timezone.utc):
        raise HTTPException(status_code=422, detail="A saída não pode ter data futura")

    leito = None
    if payload.liberar_leito:
        if "quartos_leitos:atualizar" not in context.permission_keys:
            raise HTTPException(status_code=403, detail="Liberar o leito exige permissão de quartos e leitos")
        leito = (await db.execute(select(m.QuartoLeito).where(
            m.QuartoLeito.instituicao_id == context.ilpi_id,
            m.QuartoLeito.residente_atual_id == residente.id))).scalar_one_or_none()
        if leito is None:
            raise HTTPException(status_code=409, detail="O residente não ocupa leito para liberar")

    agora = datetime.now(timezone.utc)
    saida = m.ResidenteSaida(
        ilpi_id=context.ilpi_id,
        residente_id=residente.id,
        tipo=payload.tipo,
        ocorrido_em=payload.ocorrido_em,
        local_obito=payload.local_obito,
        destino_tipo=payload.destino_tipo,
        destino_descricao=payload.destino_descricao,
        motivo_desligamento=payload.motivo_desligamento,
        observacao=payload.observacao,
        registrado_por=context.user.id,
        registrado_em=agora,
    )
    db.add(saida)
    anterior = residente.situacao
    residente.situacao = SITUACAO_POR_TIPO[payload.tipo]
    if leito is not None:
        await liberar_leito_ocupado(db, context, leito, request)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="O residente já tem uma saída registrada")
    add_audit(
        db,
        acao="residentes.registrar_saida",
        entidade="residente_saidas",
        registro_id=saida.id,
        usuario_id=context.user.id,
        ilpi_id=context.ilpi_id,
        valores_anteriores={"residente_id": residente.id, "situacao": anterior},
        valores_posteriores={"residente_id": residente.id, "situacao": residente.situacao, "tipo": saida.tipo,
                             "ocorrido_em": saida.ocorrido_em.isoformat(), "leito_liberado": leito is not None},
        request=request,
    )
    await db.commit()
    return _resposta(saida, residente.situacao, leito_liberado=leito is not None)


@router.post("/{residente_id}/saida/estornar", response_model=SaidaResponse)
async def estornar_saida(
    residente_id: str,
    payload: SaidaEstorno,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("residentes:estornar_saida")),
):
    residente = await _residente(db, context, residente_id)
    saida = await _saida_vigente(db, context, residente.id)
    if saida is None:
        raise HTTPException(status_code=409, detail="O residente não tem saída vigente para estornar")
    anterior = residente.situacao
    saida.estornado_em = datetime.now(timezone.utc)
    saida.estornado_por = context.user.id
    saida.motivo_estorno = payload.motivo.strip()
    residente.situacao = RESIDENTE_ATIVO
    add_audit(
        db,
        acao="residentes.estornar_saida",
        entidade="residente_saidas",
        registro_id=saida.id,
        usuario_id=context.user.id,
        ilpi_id=context.ilpi_id,
        valores_anteriores={"residente_id": residente.id, "situacao": anterior},
        valores_posteriores={"residente_id": residente.id, "situacao": RESIDENTE_ATIVO,
                             "motivo_estorno": saida.motivo_estorno},
        request=request,
    )
    await db.commit()
    return _resposta(saida, RESIDENTE_ATIVO)


@router.get("/{residente_id}/saida/pendencias", response_model=PendenciasResponse)
async def pendencias_saida(
    residente_id: str,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("residentes:registrar_saida")),
):
    """O que segue ativo para o residente; so leitura, cada item pela leitura da sua origem."""
    residente = await _residente(db, context, residente_id)
    chaves = context.permission_keys
    ilpi = context.ilpi_id
    itens: list[Pendencia] = []
    sem_leitura: list[str] = []

    if "planos_cuidados:ler" in chaves:
        for p in (await db.scalars(select(m.PlanoCuidados).where(
                m.PlanoCuidados.ilpi_id == ilpi, m.PlanoCuidados.residente_id == residente.id,
                m.PlanoCuidados.situacao == "vigente"))).all():
            itens.append(Pendencia(origem="pais", registro_id=p.id, descricao=f"PAIS vigente (v{p.versao})",
                                   link=f"/plano/{p.id}"))
    else:
        sem_leitura.append("pais")

    if "prescricoes:ler" in chaves:
        rows = (await db.execute(select(m.Prescricao, m.Medicamento.nome).join(
            m.Medicamento, (m.Medicamento.id == m.Prescricao.medicamento_id) & (m.Medicamento.ilpi_id == m.Prescricao.ilpi_id)
        ).where(m.Prescricao.ilpi_id == ilpi, m.Prescricao.residente_id == residente.id,
                m.Prescricao.situacao.in_(("ativa", "suspensa"))))).all()
        for presc, nome in rows:
            itens.append(Pendencia(origem="prescricao", registro_id=presc.id,
                                   descricao=f"Prescrição {presc.situacao}: {nome}"))
    else:
        sem_leitura.append("prescricao")

    if "programacoes:ler" in chaves:
        for prog in (await db.scalars(select(m.ProgramacaoCuidado).where(
                m.ProgramacaoCuidado.ilpi_id == ilpi, m.ProgramacaoCuidado.residente_id == residente.id,
                m.ProgramacaoCuidado.situacao == "ativa"))).all():
            itens.append(Pendencia(origem="programacao_cuidado", registro_id=prog.id,
                                   descricao="Programação de cuidado ativa", link=f"/plano/{prog.plano_id}"))
    else:
        sem_leitura.append("programacao_cuidado")

    if "quartos_leitos:ler" in chaves:
        leito = (await db.execute(select(m.QuartoLeito).where(
            m.QuartoLeito.instituicao_id == ilpi, m.QuartoLeito.residente_atual_id == residente.id))).scalar_one_or_none()
        if leito is not None:
            local = " · ".join(str(x) for x in (leito.unidade, leito.quarto, leito.leito) if x)
            itens.append(Pendencia(origem="leito", registro_id=leito.id, descricao=f"Leito ocupado: {local}",
                                   link="/quartos"))
    else:
        sem_leitura.append("leito")

    if "ausencias:ler" in chaves:
        ausencia = (await db.execute(select(m.Ausencia).where(
            m.Ausencia.instituicao_id == ilpi, m.Ausencia.residente_id == residente.id,
            m.Ausencia.data_fim.is_(None)))).scalar_one_or_none()
        if ausencia is not None:
            itens.append(Pendencia(origem="ausencia", registro_id=ausencia.id,
                                   descricao=f"Ausência aberta ({ausencia.tipo})"))
    else:
        sem_leitura.append("ausencia")

    return PendenciasResponse(pendencias=itens, origens_sem_leitura=sem_leitura)
