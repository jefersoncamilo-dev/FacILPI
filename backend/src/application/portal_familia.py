"""Portal da familia (#271).

- A equipe libera ou bloqueia o portal de um familiar (``POST /familiares/{id}/portal``).
  Liberar cria a conta do familiar com senha provisoria aleatoria, mostrada uma
  unica vez, e troca obrigatoria no primeiro acesso. Bloquear inativa o vinculo e
  revoga as sessoes: o proximo pedido de uma sessao aberta ja e recusado.
- #303: o portal inteiro e cada categoria comecam bloqueados por ILPI (/portal/config).
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


# ---------- Configuracao por ILPI (#303) ----------
# Categorias que o familiar pode ver. Todas comecam BLOQUEADAS e o portal inteiro
# comeca DESLIGADO por ILPI; quem decide o que liberar e a equipe (portal_familia:publicar).
CATEGORIAS = ("medicacao", "alimentacao", "atividades", "bem_estar", "recados", "agenda", "mensalidades")
JANELA_DIAS = 30


class PortalConfig(BaseModel):
    ativo: bool = False
    categorias: list[str] = Field(default_factory=list)


async def _config(db, ilpi_id) -> PortalConfig:
    row = await db.get(m.PortalFamiliaConfig, ilpi_id, populate_existing=True)
    if row is None:
        return PortalConfig()
    return PortalConfig(ativo=bool(row.ativo), categorias=[c for c in (row.categorias or []) if c in CATEGORIAS])


@portal_router.get("/config", response_model=PortalConfig)
async def ler_config(db: AsyncSession = Depends(get_db),
                     context: SecurityContext = Depends(require_permission("portal_familia:publicar"))):
    return await _config(db, context.ilpi_id)


@portal_router.put("/config", response_model=PortalConfig)
async def salvar_config(payload: PortalConfig, request: Request, db: AsyncSession = Depends(get_db),
                        context: SecurityContext = Depends(require_permission("portal_familia:publicar"))):
    invalidas = [c for c in payload.categorias if c not in CATEGORIAS]
    if invalidas:
        raise HTTPException(status_code=422, detail={"code": "CATEGORIA_INVALIDA",
                                                     "message": f"Categoria desconhecida: {', '.join(invalidas)}"})
    antes = await _config(db, context.ilpi_id)
    row = await db.get(m.PortalFamiliaConfig, context.ilpi_id)
    if row is None:
        row = m.PortalFamiliaConfig(ilpi_id=context.ilpi_id)
        db.add(row)
    row.ativo = payload.ativo
    row.categorias = [c for c in CATEGORIAS if c in set(payload.categorias)]
    row.atualizado_por = context.user.id
    row.updated_at = datetime.now(timezone.utc)
    add_audit(db, acao="portal_familia.config", entidade="portal_familia_config", registro_id=context.ilpi_id,
              usuario_id=context.user.id, ilpi_id=context.ilpi_id, valores_anteriores=antes.model_dump(),
              valores_posteriores={"ativo": row.ativo, "categorias": row.categorias}, request=request)
    await db.commit()
    return await _config(db, context.ilpi_id)


class Percentual(BaseModel):
    # Contagens simples dos ultimos 30 dias; sem julgamento clinico.
    feitos: int
    total: int
    percentual: Optional[int] = None


class PontoPeso(BaseModel):
    data: datetime
    peso: float


class PortalResumo(BaseModel):
    residente_nome: str
    familiar_nome: str
    hoje: date
    portal_liberado: bool
    categorias: list[str]
    medicacao: Optional[Percentual] = None
    alimentacao: Optional[Percentual] = None
    atividades: Optional[Percentual] = None
    peso: Optional[list[PontoPeso]] = None
    compromissos_hoje: Optional[list[Compromisso]] = None
    recados_hoje: Optional[int] = None
    agenda: Optional[list[Compromisso]] = None
    mensalidades: Optional[list[MensalidadePortal]] = None
    recados: Optional[list[Recado]] = None


def _pct(feitos: int, total: int) -> Percentual:
    return Percentual(feitos=feitos, total=total, percentual=round(100 * feitos / total) if total else None)


def _aware(v: datetime) -> datetime:
    return v if v.tzinfo else v.replace(tzinfo=timezone.utc)


@portal_router.get("/resumo", response_model=PortalResumo)
async def resumo_do_familiar(request: Request, db: AsyncSession = Depends(get_db),
                             context: SecurityContext = Depends(require_permission("portal_familia:ler"))):
    familiar = await db.scalar(select(m.Familiar).where(
        m.Familiar.usuario_id == context.user.id, m.Familiar.ilpi_id == context.ilpi_id, m.Familiar.portal_ativo.is_(True)))
    if familiar is None:
        raise _404()
    residente = await db.scalar(select(m.Residente).where(
        m.Residente.id == familiar.residente_id, m.Residente.instituicao_id == context.ilpi_id))
    if residente is None:
        raise _404()
    config = await _config(db, context.ilpi_id)
    ver = set(config.categorias) if config.ativo else set()
    # #303: todo acesso do familiar fica na auditoria, com as categorias mostradas.
    add_audit(db, acao="portal_familia.acesso", entidade="residentes", registro_id=residente.id, usuario_id=context.user.id,
              ilpi_id=context.ilpi_id, valores_posteriores={"familiar_id": familiar.id, "categorias": sorted(ver)},
              request=request)
    await db.commit()
    fuso = await db.scalar(select(m.Instituicao.fuso_horario).where(m.Instituicao.id == context.ilpi_id))
    tz = ZoneInfo(fuso or "America/Sao_Paulo")
    agora = datetime.now(timezone.utc)
    hoje = agora.astimezone(tz).date()
    inicio = datetime.combine(hoje, time.min, tz).astimezone(timezone.utc)
    amanha = inicio + timedelta(days=1)
    desde = agora - timedelta(days=JANELA_DIAS)
    resposta = PortalResumo(residente_nome=residente.nome_social or residente.nome, familiar_nome=familiar.nome,
                            hoje=hoje, portal_liberado=config.ativo, categorias=sorted(ver))
    rid, iid = residente.id, context.ilpi_id

    if "medicacao" in ver:
        doses = (await db.execute(select(m.DosePrevista.id, m.Administracao.resultado).outerjoin(
            m.Administracao, (m.Administracao.dose_prevista_id == m.DosePrevista.id)
            & (m.Administracao.ilpi_id == m.DosePrevista.ilpi_id) & m.Administracao.estornado_em.is_(None)).where(
            m.DosePrevista.ilpi_id == iid, m.DosePrevista.residente_id == rid, m.DosePrevista.situacao == "prevista",
            m.DosePrevista.previsto_em >= desde, m.DosePrevista.previsto_em < agora))).all()
        resposta.medicacao = _pct(sum(1 for _, r in doses if r == "administrada"), len(doses))
    if "atividades" in ver or "alimentacao" in ver:
        ocorr = (await db.execute(select(m.OcorrenciaCuidado.id, m.ExecucaoCuidado.resultado,
                                         m.ExecucaoCuidado.percentual_consumido).outerjoin(
            m.ExecucaoCuidado, (m.ExecucaoCuidado.ocorrencia_id == m.OcorrenciaCuidado.id)
            & (m.ExecucaoCuidado.ilpi_id == m.OcorrenciaCuidado.ilpi_id) & m.ExecucaoCuidado.estornado_em.is_(None)).where(
            m.OcorrenciaCuidado.ilpi_id == iid, m.OcorrenciaCuidado.residente_id == rid,
            m.OcorrenciaCuidado.situacao == "prevista",
            m.OcorrenciaCuidado.previsto_em >= desde, m.OcorrenciaCuidado.previsto_em < agora))).all()
        if "atividades" in ver:
            resposta.atividades = _pct(sum(1 for _, r, _p in ocorr if r == "executada"), len(ocorr))
        if "alimentacao" in ver:
            # G4: so execucoes com percentual de refeicao; media simples do quanto foi comido.
            refeicoes = [p for _, _r, p in ocorr if p is not None]
            resposta.alimentacao = Percentual(feitos=sum(refeicoes), total=100 * len(refeicoes),
                                              percentual=round(sum(refeicoes) / len(refeicoes)) if refeicoes else None)
    if "bem_estar" in ver:
        resposta.peso = [PontoPeso(data=_aware(d), peso=p) for d, p in (await db.execute(
            select(m.SinalVital.data, m.SinalVital.peso).where(
                m.SinalVital.ilpi_id == iid, m.SinalVital.residente_id == rid, m.SinalVital.peso.is_not(None),
                m.SinalVital.data >= desde).order_by(m.SinalVital.data))).all()]
    if "agenda" in ver:
        eventos = (await db.scalars(select(m.AgendaEvento).where(
            m.AgendaEvento.ilpi_id == iid, m.AgendaEvento.residente_id == rid,
            m.AgendaEvento.situacao != "cancelado", m.AgendaEvento.inicio_em >= inicio,
            m.AgendaEvento.inicio_em < inicio + timedelta(days=30),
        ).order_by(m.AgendaEvento.inicio_em))).all()
        resposta.agenda = [Compromisso(motivo=e.motivo, inicio_em=e.inicio_em, local=e.local, situacao=e.situacao)
                           for e in eventos]
        resposta.compromissos_hoje = [c for c in resposta.agenda if _aware(c.inicio_em) < amanha]
    if "recados" in ver:
        recados = (await db.scalars(select(m.PortalRecado).where(
            m.PortalRecado.ilpi_id == iid, m.PortalRecado.residente_id == rid
        ).order_by(m.PortalRecado.created_at.desc()).limit(50))).all()
        resposta.recados = [_recado(r) for r in recados]
        resposta.recados_hoje = sum(1 for r in recados if _aware(r.created_at) >= inicio)
    if "mensalidades" in ver:
        mensalidades = (await db.scalars(select(m.Mensalidade).where(
            m.Mensalidade.ilpi_id == iid, m.Mensalidade.residente_id == rid, m.Mensalidade.situacao != "cancelada",
        ).order_by(m.Mensalidade.vencimento.desc()).limit(24))).all()
        resposta.mensalidades = [MensalidadePortal(competencia=x.competencia, valor_centavos=x.valor_centavos,
                                                   vencimento=x.vencimento, situacao=x.situacao, pago_em=x.pago_em)
                                 for x in mensalidades]
    return resposta
