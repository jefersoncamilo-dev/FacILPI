"""Portal da familia (#271).

- A equipe libera ou bloqueia o portal de um familiar (``POST /familiares/{id}/portal``).
  Liberar cria a conta do familiar com senha provisoria aleatoria, mostrada uma
  unica vez, e troca obrigatoria no primeiro acesso. Bloquear inativa o vinculo e
  revoga as sessoes: o proximo pedido de uma sessao aberta ja e recusado.
- O familiar so le o proprio residente vinculado: resumo do dia, agenda,
  mensalidades e recados. Nada do prontuario clinico. Nao envia nada.
- Residente e tenant vem do vinculo da sessao, nunca de parametro.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure import models as m
from ..infrastructure.database import get_db
from .audit import add_audit
from .auth import hash_password
from .fase3a import _revoke_context_refresh_tokens, _temporary_password
from .security import PORTAL_FAMILIA_KEY, RESOURCE_NOT_FOUND, SecurityContext, require_permission

familiar_portal_router = APIRouter(prefix="/familiares", tags=["portal-familia"])
portal_router = APIRouter(prefix="/portal", tags=["portal-familia"])


def _404():
    return HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})


def _409(mensagem: str):
    return HTTPException(status_code=409, detail={"code": "CONFLITO", "message": mensagem})


class PortalAcesso(BaseModel):
    ativo: bool


class PortalAcessoResposta(BaseModel):
    familiar_id: str
    portal_ativo: bool
    email: Optional[str] = None
    senha_provisoria: Optional[str] = None


async def _perfil_portal(db: AsyncSession, ilpi_id: str) -> m.Perfil:
    """Clone local do template ``familiar_portal`` (criado na primeira liberacao)."""
    clone = await db.scalar(select(m.Perfil).where(m.Perfil.chave == PORTAL_FAMILIA_KEY, m.Perfil.ilpi_id == ilpi_id))
    if clone is not None:
        return clone
    template = await db.scalar(select(m.Perfil).where(m.Perfil.chave == PORTAL_FAMILIA_KEY, m.Perfil.ilpi_id.is_(None)))
    if template is None:
        raise HTTPException(status_code=503, detail={"code": "PORTAL_INDISPONIVEL", "message": "Portal não configurado."})
    clone = m.Perfil(ilpi_id=ilpi_id, nome=template.nome, chave=template.chave, descricao=template.descricao,
                     escopo=template.escopo, situacao="ativo")
    db.add(clone)
    await db.flush()
    for (permissao,) in (await db.execute(select(m.PerfilPermissao.permissao_id).where(
            m.PerfilPermissao.perfil_id == template.id))).all():
        db.add(m.PerfilPermissao(perfil_id=clone.id, permissao_id=permissao))
    await db.flush()
    return clone


@familiar_portal_router.post("/{familiar_id}/portal", response_model=PortalAcessoResposta)
async def definir_portal(
    familiar_id: str, payload: PortalAcesso, request: Request, db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("portal_familia:publicar")),
):
    familiar = await db.scalar(select(m.Familiar).where(m.Familiar.id == familiar_id, m.Familiar.ilpi_id == context.ilpi_id))
    if familiar is None:
        raise _404()
    senha = None
    if payload.ativo:
        email = (familiar.email or "").strip().lower()
        if not email:
            raise HTTPException(status_code=422, detail={"code": "EMAIL_OBRIGATORIO", "message": "Cadastre o e-mail do familiar antes de liberar o portal."})
        perfil = await _perfil_portal(db, context.ilpi_id)
        user = await db.get(m.User, familiar.usuario_id) if familiar.usuario_id else None
        if user is None:
            if await db.scalar(select(m.User.id).where(m.User.email == email)):
                # Nunca reaproveita conta de outra pessoa (equipe ou outro familiar).
                raise _409("Este e-mail já é usado por outra conta. Use outro e-mail para o familiar.")
            user = m.User(nome=familiar.nome, email=email, password_hash="!", ativo=True)
            db.add(user)
            await db.flush()
            familiar.usuario_id = user.id
        senha = _temporary_password()
        user.password_hash = hash_password(senha)
        user.exige_troca_senha = True
        user.ativo = True
        vinculo = await db.scalar(select(m.UsuarioIlpiPerfil).where(
            m.UsuarioIlpiPerfil.usuario_id == user.id, m.UsuarioIlpiPerfil.ilpi_id == context.ilpi_id,
            m.UsuarioIlpiPerfil.perfil_id == perfil.id))
        if vinculo is None:
            db.add(m.UsuarioIlpiPerfil(usuario_id=user.id, ilpi_id=context.ilpi_id, perfil_id=perfil.id, situacao="ativo",
                                       data_inicial=datetime.now(timezone.utc)))
        else:
            vinculo.situacao, vinculo.data_inicial, vinculo.data_final = "ativo", datetime.now(timezone.utc), None
        await _revoke_context_refresh_tokens(db, user.id, context.ilpi_id)
        familiar.portal_ativo = True
        acao = "portal_familia.liberado"
    else:
        if familiar.usuario_id:
            for vinculo in (await db.scalars(select(m.UsuarioIlpiPerfil).where(
                    m.UsuarioIlpiPerfil.usuario_id == familiar.usuario_id,
                    m.UsuarioIlpiPerfil.ilpi_id == context.ilpi_id))).all():
                vinculo.situacao, vinculo.data_final = "inativo", datetime.now(timezone.utc)
            await _revoke_context_refresh_tokens(db, familiar.usuario_id, context.ilpi_id)
        familiar.portal_ativo = False
        acao = "portal_familia.bloqueado"
    add_audit(db, acao=acao, entidade="familiares", registro_id=familiar.id, usuario_id=context.user.id,
              ilpi_id=context.ilpi_id, valores_posteriores={"portal_ativo": familiar.portal_ativo,
                                                            "conta_id": familiar.usuario_id}, request=request)
    await db.commit()
    return PortalAcessoResposta(familiar_id=familiar.id, portal_ativo=familiar.portal_ativo,
                                email=familiar.email, senha_provisoria=senha)


# ---------- Recados da equipe ----------
class RecadoNovo(BaseModel):
    residente_id: str
    texto: str = Field(min_length=1, max_length=2000)


class Recado(BaseModel):
    id: str
    texto: str
    autor_nome: str
    created_at: datetime


def _recado(r: m.PortalRecado) -> Recado:
    return Recado(id=r.id, texto=r.texto, autor_nome=r.autor_nome, created_at=r.created_at)


async def _residente_do_tenant(db, context, residente_id):
    if await db.scalar(select(m.Residente.id).where(m.Residente.id == residente_id,
                                                    m.Residente.instituicao_id == context.ilpi_id)) is None:
        raise _404()


@portal_router.post("/recados", response_model=Recado, status_code=201)
async def publicar_recado(payload: RecadoNovo, request: Request, db: AsyncSession = Depends(get_db),
                          context: SecurityContext = Depends(require_permission("portal_familia:publicar"))):
    await _residente_do_tenant(db, context, payload.residente_id)
    r = m.PortalRecado(ilpi_id=context.ilpi_id, residente_id=payload.residente_id, texto=payload.texto.strip(),
                       autor_id=context.user.id, autor_nome=context.user.nome)
    db.add(r)
    await db.flush()
    add_audit(db, acao="portal_familia.recado", entidade="portal_recados", registro_id=r.id, usuario_id=context.user.id,
              ilpi_id=context.ilpi_id, request=request)
    await db.commit()
    await db.refresh(r)
    return _recado(r)


@portal_router.get("/recados/{residente_id}", response_model=list[Recado])
async def recados_do_residente(residente_id: str, db: AsyncSession = Depends(get_db),
                               context: SecurityContext = Depends(require_permission("portal_familia:publicar"))):
    await _residente_do_tenant(db, context, residente_id)
    return [_recado(r) for r in (await db.scalars(select(m.PortalRecado).where(
        m.PortalRecado.ilpi_id == context.ilpi_id, m.PortalRecado.residente_id == residente_id
    ).order_by(m.PortalRecado.created_at.desc()).limit(100))).all()]


# ---------- Leitura do familiar ----------
class Compromisso(BaseModel):
    motivo: str
    inicio_em: datetime
    local: Optional[str] = None
    situacao: str


class MensalidadePortal(BaseModel):
    competencia: str
    valor_centavos: int
    vencimento: date
    situacao: str
    pago_em: Optional[date] = None


class PortalResumo(BaseModel):
    residente_nome: str
    familiar_nome: str
    hoje: date
    compromissos_hoje: list[Compromisso]
    recados_hoje: int
    agenda: list[Compromisso]
    mensalidades: list[MensalidadePortal]
    recados: list[Recado]


@portal_router.get("/resumo", response_model=PortalResumo)
async def resumo_do_familiar(db: AsyncSession = Depends(get_db),
                             context: SecurityContext = Depends(require_permission("portal_familia:ler"))):
    familiar = await db.scalar(select(m.Familiar).where(
        m.Familiar.usuario_id == context.user.id, m.Familiar.ilpi_id == context.ilpi_id, m.Familiar.portal_ativo.is_(True)))
    if familiar is None:
        raise _404()
    residente = await db.scalar(select(m.Residente).where(
        m.Residente.id == familiar.residente_id, m.Residente.instituicao_id == context.ilpi_id))
    if residente is None:
        raise _404()
    fuso = await db.scalar(select(m.Instituicao.fuso_horario).where(m.Instituicao.id == context.ilpi_id))
    tz = ZoneInfo(fuso or "America/Sao_Paulo")
    hoje = datetime.now(tz).date()
    inicio = datetime.combine(hoje, time.min, tz).astimezone(timezone.utc)
    amanha = inicio + timedelta(days=1)

    eventos = (await db.scalars(select(m.AgendaEvento).where(
        m.AgendaEvento.ilpi_id == context.ilpi_id, m.AgendaEvento.residente_id == residente.id,
        m.AgendaEvento.situacao != "cancelado", m.AgendaEvento.inicio_em >= inicio,
        m.AgendaEvento.inicio_em < inicio + timedelta(days=30),
    ).order_by(m.AgendaEvento.inicio_em))).all()
    agenda = [Compromisso(motivo=e.motivo, inicio_em=e.inicio_em, local=e.local, situacao=e.situacao) for e in eventos]
    recados = (await db.scalars(select(m.PortalRecado).where(
        m.PortalRecado.ilpi_id == context.ilpi_id, m.PortalRecado.residente_id == residente.id
    ).order_by(m.PortalRecado.created_at.desc()).limit(50))).all()
    mensalidades = (await db.scalars(select(m.Mensalidade).where(
        m.Mensalidade.ilpi_id == context.ilpi_id, m.Mensalidade.residente_id == residente.id,
        m.Mensalidade.situacao != "cancelada",
    ).order_by(m.Mensalidade.vencimento.desc()).limit(24))).all()

    def _aware(v: datetime) -> datetime:
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)

    return PortalResumo(
        residente_nome=residente.nome_social or residente.nome, familiar_nome=familiar.nome, hoje=hoje,
        compromissos_hoje=[c for c in agenda if _aware(c.inicio_em) < amanha],
        recados_hoje=sum(1 for r in recados if _aware(r.created_at) >= inicio),
        agenda=agenda,
        mensalidades=[MensalidadePortal(competencia=x.competencia, valor_centavos=x.valor_centavos, vencimento=x.vencimento,
                                        situacao=x.situacao, pago_em=x.pago_em) for x in mensalidades],
        recados=[_recado(r) for r in recados],
    )
