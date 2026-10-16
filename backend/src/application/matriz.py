"""S.1: matriz institucional de permissões clínicas.

Perfis institucionais (cuidador/enfermagem/medico/responsavel_tecnico/
administrativo) existem como templates (migration 015). Atribuição é
ação administrativa explícita com clone-on-assign por tenant,
anti-escalation ("só conceda o que possui") e auditoria completa.

Profissão/cargo textual NUNCA concede permissão. Platform segue global
sem acesso clínico. ilpi_admin preservado temporariamente (documentado).
"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure import models as m
from ..infrastructure.database import get_db
from . import schemas as s
from .audit import add_audit
from .security import ILPI_SCOPE, RESOURCE_NOT_FOUND, SecurityContext, require_ilpi_context, require_permission


matriz_router = APIRouter(prefix="/matriz", tags=["matriz"], dependencies=[Depends(require_ilpi_context)])

INSTITUCIONAL_CHAVES = ("cuidador", "enfermagem", "medico", "responsavel_tecnico", "administrativo")


def _now():
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


def _deny(code, http_status, message):
    raise HTTPException(status_code=http_status, detail={"code": code, "message": message})


async def _template(db, chave):
    return (await db.execute(select(m.Perfil).where(
        m.Perfil.chave == chave, m.Perfil.ilpi_id.is_(None),
        m.Perfil.escopo == ILPI_SCOPE, m.Perfil.situacao == "ativo"))).scalar_one_or_none()


async def _template_keys(db, template):
    rows = (await db.execute(select(m.Permissao.chave).join(
        m.PerfilPermissao, m.PerfilPermissao.permissao_id == m.Permissao.id).where(
            m.PerfilPermissao.perfil_id == template.id))).scalars().all()
    return set(rows)


async def _ensure_clone(db, template, context, request):
    clone = (await db.execute(select(m.Perfil).where(
        m.Perfil.chave == template.chave, m.Perfil.ilpi_id == context.ilpi_id))).scalar_one_or_none()
    if clone is not None:
        return clone, False
    clone = m.Perfil(id=_new_id(), ilpi_id=context.ilpi_id, nome=template.nome,
                     chave=template.chave, descricao=template.descricao,
                     escopo=ILPI_SCOPE, situacao="ativo")
    db.add(clone)
    await db.flush()
    permission_ids = (await db.execute(select(m.PerfilPermissao.permissao_id).where(
        m.PerfilPermissao.perfil_id == template.id))).scalars().all()
    for permission_id in permission_ids:
        db.add(m.PerfilPermissao(perfil_id=clone.id, permissao_id=permission_id))
    await db.flush()
    add_audit(db, acao="perfil.clonado", entidade="perfis", registro_id=clone.id,
              usuario_id=context.user.id, ilpi_id=context.ilpi_id,
              valores_posteriores={"chave": clone.chave, "template_id": template.id,
                                   "permissoes": len(permission_ids)}, request=request)
    return clone, True


async def _target_no_tenant(db, user_id, context):
    target = (await db.execute(select(m.User).where(m.User.id == user_id))).scalar_one_or_none()
    if target is None:
        _deny("USER_NOT_FOUND", status.HTTP_404_NOT_FOUND, "Usuário não encontrado")
    link = (await db.execute(select(m.UsuarioIlpiPerfil.id).where(
        m.UsuarioIlpiPerfil.usuario_id == user_id, m.UsuarioIlpiPerfil.ilpi_id == context.ilpi_id,
        m.UsuarioIlpiPerfil.situacao == "ativo").limit(1))).scalar_one_or_none()
    if link is None:
        _deny(RESOURCE_NOT_FOUND, status.HTTP_404_NOT_FOUND, "Recurso não encontrado")
    return target


@matriz_router.get("/perfis", response_model=list[s.MatrizPerfilResponse])
async def listar_institucionais(db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("perfis:ler"))):
    result = []
    for chave in INSTITUCIONAL_CHAVES:
        template = await _template(db, chave)
        if template is None:
            continue
        clone = (await db.execute(select(m.Perfil).where(
            m.Perfil.chave == chave, m.Perfil.ilpi_id == context.ilpi_id))).scalar_one_or_none()
        result.append({"chave": chave, "nome": template.nome, "descricao": template.descricao,
                       "clone_id": clone.id if clone else None,
                       "permissoes": sorted(await _template_keys(db, template))})
    return result


@matriz_router.post("/atribuicoes", status_code=201)
async def atribuir_institucional(payload: s.MatrizAtribuir, request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("usuarios:atribuir_perfil"))):
    template = await _template(db, payload.perfil_chave)
    if template is None:
        _deny(RESOURCE_NOT_FOUND, status.HTTP_404_NOT_FOUND, "Recurso não encontrado")
    # Anti-escalation: só conceda o que possui. Exceção nomeada: ilpi_admin
    # mantém gestão de usuários/vínculos/perfis (§5: perfil administrativo
    # institucional); demais perfis obedecem ao subconjunto estrito.
    faltantes = await _template_keys(db, template) - set(context.permission_keys)
    administracao_institucional = (
        context.perfil.chave == "ilpi_admin" and context.perfil.ilpi_id == context.ilpi_id)
    if faltantes and not administracao_institucional:
        _deny("PERMISSAO_ESCALATION", status.HTTP_403_FORBIDDEN,
              "Atribuidor não possui todas as permissões do perfil")
    target = await _target_no_tenant(db, payload.usuario_id, context)
    try:
        clone, _ = await _ensure_clone(db, template, context, request)
        existing = (await db.execute(select(m.UsuarioIlpiPerfil).where(
            m.UsuarioIlpiPerfil.usuario_id == target.id, m.UsuarioIlpiPerfil.ilpi_id == context.ilpi_id,
            m.UsuarioIlpiPerfil.perfil_id == clone.id))).scalar_one_or_none()
        if existing is not None:
            if existing.situacao == "ativo":
                _deny("VINCULO_DUPLICADO", status.HTTP_409_CONFLICT, "Perfil já atribuído ao usuário")
            before = {"situacao": existing.situacao}
            existing.situacao, existing.data_inicial, existing.data_final = "ativo", _now(), None
            await db.flush()
            add_audit(db, acao="usuario_ilpi_perfil.reativado", entidade="usuario_ilpi_perfis",
                      registro_id=existing.id, usuario_id=context.user.id, ilpi_id=context.ilpi_id,
                      valores_anteriores=before,
                      valores_posteriores={"usuario_id": target.id, "perfil_id": clone.id},
                      request=request)
            await db.commit()
            return {"id": existing.id, "usuario_id": target.id, "perfil_id": clone.id,
                    "ilpi_id": context.ilpi_id, "reativado": True}
        link = m.UsuarioIlpiPerfil(id=_new_id(), usuario_id=target.id, ilpi_id=context.ilpi_id,
                                   perfil_id=clone.id, situacao="ativo")
        db.add(link)
        await db.flush()
        add_audit(db, acao="usuario_ilpi_perfil.criado", entidade="usuario_ilpi_perfis",
                  registro_id=link.id, usuario_id=context.user.id, ilpi_id=context.ilpi_id,
                  valores_posteriores={"usuario_id": target.id, "perfil_id": clone.id,
                                       "ilpi_id": context.ilpi_id}, request=request)
        await db.commit()
        return {"id": link.id, "usuario_id": target.id, "perfil_id": clone.id,
                "ilpi_id": context.ilpi_id, "reativado": False}
    except IntegrityError:
        await db.rollback()
        _deny("VINCULO_DUPLICADO", status.HTTP_409_CONFLICT, "Perfil já atribuído ao usuário")
    except HTTPException:
        await db.rollback()
        raise


@matriz_router.post("/revogacoes")
async def revogar_institucional(payload: s.MatrizRevogar, request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("usuarios:atribuir_perfil"))):
    if payload.perfil_chave not in INSTITUCIONAL_CHAVES:
        _deny(RESOURCE_NOT_FOUND, status.HTTP_404_NOT_FOUND, "Recurso não encontrado")
    target = await _target_no_tenant(db, payload.usuario_id, context)
    link = (await db.execute(select(m.UsuarioIlpiPerfil).join(
        m.Perfil, m.Perfil.id == m.UsuarioIlpiPerfil.perfil_id).where(
            m.UsuarioIlpiPerfil.usuario_id == target.id,
            m.UsuarioIlpiPerfil.ilpi_id == context.ilpi_id,
            m.UsuarioIlpiPerfil.situacao == "ativo",
            m.Perfil.chave == payload.perfil_chave,
            m.Perfil.ilpi_id == context.ilpi_id))).scalar_one_or_none()
    if link is None:
        _deny(RESOURCE_NOT_FOUND, status.HTTP_404_NOT_FOUND, "Recurso não encontrado")
    before = {"situacao": link.situacao}
    link.situacao, link.data_final = "inativo", _now()
    add_audit(db, acao="usuario_ilpi_perfil.revogado", entidade="usuario_ilpi_perfis",
              registro_id=link.id, usuario_id=context.user.id, ilpi_id=context.ilpi_id,
              valores_anteriores=before,
              valores_posteriores={"usuario_id": target.id, "perfil_id": link.perfil_id,
                                   "situacao": "inativo"}, request=request)
    await db.commit()
    return {"id": link.id, "usuario_id": target.id, "perfil_id": link.perfil_id,
            "ilpi_id": context.ilpi_id, "situacao": "inativo"}
