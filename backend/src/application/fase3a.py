from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..domain.validators import validate_cnpj
from ..infrastructure import models as m
from ..infrastructure.database import get_db
from . import schemas as s
from .audit import add_audit
from .auth import (
    REFRESH_COOKIE_NAME,
    check_rate_limit,
    clear_refresh_cookie,
    create_access_token,
    generate_temporary_password,
    get_current_user,
    hash_password,
    issue_refresh_token,
    load_refresh_token,
    refresh_token_is_valid,
    revoke_user_refresh_tokens,
    set_refresh_cookie,
)
from .bootstrap_state import (
    FIRST_PASSWORD_CHANGED,
    ILPI_CREATED,
    ONBOARDING_COMPLETED,
    ONBOARDING_IN_PROGRESS,
    PLATFORM_BOOTSTRAPPED,
    assert_state,
    load_bootstrap_state,
    public_status,
    state_conflict,
    transition_state,
)
from .security import (
    GLOBAL_SCOPE,
    ILPI_SCOPE,
    SecurityContext,
    load_security_context,
    require_permission,
)


ILPI_ADMIN_KEY = "ilpi_admin"
PLATFORM_SUPERUSER_KEY = "platform_superuser"
ADMIN_EMAIL = "admin@ilpi.com"
ILPI_ACTIVE = "ATIVA"
ILPI_INACTIVE = "INATIVA"
ILPI_DRAFT = "ILPI_RASCUNHO"

GLOBAL_ONLY_PERMISSIONS = {
    "ilpis:criar",
    "ilpis:ativar",
    "ilpis:suspender",
    "ilpis:inativar",
}
CLINICAL_MODULES = {
    "residentes",
    "familiares",
    "documentos",
    "quartos_leitos",
    "admissoes",
    "avaliacoes",
    "planos_cuidados",
    "tarefas",
    "cuidados_diarios",
    "medicamentos",
    "prescricoes",
    "sinais_vitais",
    "intercorrencias",
    "agenda",
    "passagem_plantao",
    "alertas",
    "estoque",
    "financeiro",
    "portal_familia",
    "relatorios",
    "supervisao",
    "compliance",
    "uploads",
}


bootstrap_router = APIRouter(prefix="/bootstrap", tags=["bootstrap"])
auth_session_router = APIRouter(prefix="/auth", tags=["auth"])
instituicoes_router = APIRouter(prefix="/instituicoes", tags=["instituicoes"])
onboarding_router = APIRouter(prefix="/onboarding", tags=["onboarding"])
usuarios_router = APIRouter(prefix="/usuarios", tags=["usuarios"])
funcionarios_router = APIRouter(prefix="/funcionarios", tags=["funcionarios"])
perfis_router = APIRouter(prefix="/perfis", tags=["perfis"])
permissoes_router = APIRouter(prefix="/permissoes", tags=["permissoes"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid.uuid4())


def _trim_strings(data: dict) -> dict:
    return {
        key: value.strip() if isinstance(value, str) else value
        for key, value in data.items()
    }


def _public_user(user: m.User) -> dict:
    return {
        "id": user.id,
        "nome": user.nome,
        "email": user.email,
        "ativo": user.ativo,
        "is_superuser": user.is_superuser,
        "exige_troca_senha": user.exige_troca_senha,
    }


def _temporary_password() -> str:
    # Garante senha forte mesmo se token_urlsafe não trouxer todas as classes.
    return f"Aa1!{generate_temporary_password()}"


def _normalise_email(email: str) -> str:
    return email.lower().strip()


def _http_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _require_ilpi_context(context: SecurityContext) -> None:
    if context.scope != ILPI_SCOPE or context.ilpi_id is None:
        raise _http_error(status.HTTP_403_FORBIDDEN, "ILPI_CONTEXT_REQUIRED", "Contexto institucional obrigatório")


def _require_global_context(context: SecurityContext) -> None:
    if context.scope != GLOBAL_SCOPE:
        raise _http_error(status.HTTP_403_FORBIDDEN, "GLOBAL_SCOPE_REQUIRED", "Escopo global obrigatório")


def _ensure_valid_uf(uf: str | None) -> str:
    if uf is None or not uf.strip():
        raise _http_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "UF_REQUIRED", "UF obrigatória para ativar ILPI")
    value = uf.strip().upper()
    if value not in s.UF_VALIDAS:
        raise _http_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "UF_INVALIDA", "UF inválida")
    return value


async def resolve_token_context(
    db: AsyncSession,
    user: m.User,
    *,
    scope: str | None = None,
    ilpi_id: str | None = None,
    perfil_id: str | None = None,
) -> dict[str, str | None]:
    if scope or ilpi_id or perfil_id:
        context = await load_security_context(
            db,
            user,
            scope=scope,
            ilpi_id=ilpi_id,
            perfil_id=perfil_id,
        )
        return {"scope": context.scope, "ilpi_id": context.ilpi_id, "perfil_id": context.perfil.id}

    if user.exige_troca_senha and not user.is_superuser:
        return {"scope": None, "ilpi_id": None, "perfil_id": None}

    if user.is_superuser:
        try:
            context = await load_security_context(db, user, scope=GLOBAL_SCOPE)
            return {"scope": context.scope, "ilpi_id": context.ilpi_id, "perfil_id": context.perfil.id}
        except HTTPException:
            if user.exige_troca_senha:
                return {"scope": None, "ilpi_id": None, "perfil_id": None}
            raise

    context = await load_security_context(db, user)
    return {"scope": context.scope, "ilpi_id": context.ilpi_id, "perfil_id": context.perfil.id}


async def issue_session_response(
    db: AsyncSession,
    user: m.User,
    response: Response,
    request: Request,
    *,
    scope: str | None = None,
    ilpi_id: str | None = None,
    perfil_id: str | None = None,
) -> dict:
    context = await resolve_token_context(
        db,
        user,
        scope=scope,
        ilpi_id=ilpi_id,
        perfil_id=perfil_id,
    )
    refresh = await issue_refresh_token(db, user, request=request, **context)
    access = create_access_token(user, **context)
    set_refresh_cookie(response, refresh)
    return {
        "access_token": access,
        "token_type": "bearer",
        "exige_troca_senha": user.exige_troca_senha,
    }


@bootstrap_router.get("/status")
async def get_bootstrap_status(db: AsyncSession = Depends(get_db)):
    state = await load_bootstrap_state(db)
    return public_status(state)


@auth_session_router.put("/primeiro-acesso", response_model=s.TokenResponse)
async def primeiro_acesso(
    payload: s.PrimeiroAcessoUpdate,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: m.User = Depends(get_current_user),
):
    check_rate_limit(f"primeiro-acesso:{current_user.id}")
    if payload.nova_senha != payload.confirmar:
        raise _http_error(status.HTTP_400_BAD_REQUEST, "PASSWORD_MISMATCH", "Senhas não conferem")
    if not current_user.exige_troca_senha:
        raise state_conflict("Primeiro acesso já concluído")

    try:
        state = await load_bootstrap_state(db, for_update=True)
        assert_state(state, PLATFORM_BOOTSTRAPPED)
        current_user.password_hash = hash_password(payload.nova_senha)
        current_user.exige_troca_senha = False
        transition_state(
            db,
            state,
            FIRST_PASSWORD_CHANGED,
            usuario_id=current_user.id,
            request=request,
        )
        add_audit(
            db,
            acao="auth.primeiro_acesso",
            entidade="users",
            registro_id=current_user.id,
            usuario_id=current_user.id,
            valores_posteriores={"exige_troca_senha": False},
            request=request,
        )
        await revoke_user_refresh_tokens(db, current_user.id)
        session_payload = await issue_session_response(db, current_user, response, request)
        await db.commit()
        return session_payload
    except HTTPException:
        await db.rollback()
        raise


@auth_session_router.post("/refresh", response_model=s.TokenResponse)
async def refresh_session(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    raw_refresh = request.cookies.get(REFRESH_COOKIE_NAME)
    row = await load_refresh_token(db, raw_refresh or "")
    if not refresh_token_is_valid(row):
        clear_refresh_cookie(response)
        raise _http_error(status.HTTP_401_UNAUTHORIZED, "AUTHENTICATION_REQUIRED", "Autenticação obrigatória")

    user = (await db.execute(select(m.User).where(m.User.id == row.user_id))).scalar_one_or_none()
    if user is None or not user.ativo:
        row.revoked_at = _now()
        await db.commit()
        clear_refresh_cookie(response)
        raise _http_error(status.HTTP_401_UNAUTHORIZED, "AUTHENTICATION_REQUIRED", "Autenticação obrigatória")

    refresh = await issue_refresh_token(
        db,
        user,
        scope=row.ilpi_id and ILPI_SCOPE or (GLOBAL_SCOPE if row.perfil_id and row.ilpi_id is None else None),
        ilpi_id=row.ilpi_id,
        perfil_id=row.perfil_id,
        request=request,
        token_family=row.token_family,
        replaces=row,
    )
    access = create_access_token(
        user,
        scope=row.ilpi_id and ILPI_SCOPE or (GLOBAL_SCOPE if row.perfil_id and row.ilpi_id is None else None),
        ilpi_id=row.ilpi_id,
        perfil_id=row.perfil_id,
    )
    await db.commit()
    set_refresh_cookie(response, refresh)
    return {
        "access_token": access,
        "token_type": "bearer",
        "exige_troca_senha": user.exige_troca_senha,
    }


@auth_session_router.post("/logout")
async def logout_session(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    raw_refresh = request.cookies.get(REFRESH_COOKIE_NAME)
    row = await load_refresh_token(db, raw_refresh or "")
    if row is not None and row.revoked_at is None:
        row.revoked_at = _now()
        add_audit(
            db,
            acao="auth.logout",
            entidade="refresh_tokens",
            registro_id=row.id,
            usuario_id=row.user_id,
            request=request,
        )
        await db.commit()
    clear_refresh_cookie(response)
    return {"mensagem": "Sessão encerrada"}


@auth_session_router.post("/contexto", response_model=s.TokenResponse)
async def selecionar_contexto(
    payload: s.ContextSelection,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: m.User = Depends(get_current_user),
):
    if current_user.exige_troca_senha:
        raise _http_error(status.HTTP_403_FORBIDDEN, "FIRST_PASSWORD_CHANGE_REQUIRED", "Troca de senha obrigatória")
    session_payload = await issue_session_response(
        db,
        current_user,
        response,
        request,
        scope=payload.scope,
        ilpi_id=payload.ilpi_id,
        perfil_id=payload.perfil_id,
    )
    await db.commit()
    return session_payload


@instituicoes_router.get("/", response_model=list[s.InstituicaoResponse])
async def list_instituicoes(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("ilpis:ler")),
):
    query = select(m.Instituicao)
    if context.scope == ILPI_SCOPE:
        query = query.where(m.Instituicao.id == context.ilpi_id)
    result = await db.execute(query.order_by(m.Instituicao.created_at.desc()).offset(skip).limit(limit))
    return result.scalars().all()


@instituicoes_router.post("/", response_model=s.InstituicaoResponse, status_code=201)
async def create_instituicao(
    payload: s.InstituicaoCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("ilpis:criar")),
):
    _require_global_context(context)
    data = _trim_strings(payload.model_dump(exclude_unset=True))
    if data.get("capacidade") is None or data.get("capacidade") <= 0:
        raise _http_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "CAPACIDADE_REQUIRED", "Capacidade deve ser maior que zero")
    data["situacao"] = ILPI_DRAFT
    obj = m.Instituicao(**data)
    try:
        state = await load_bootstrap_state(db, for_update=True)
        assert_state(state, FIRST_PASSWORD_CHANGED)
        db.add(obj)
        await db.flush()
        add_audit(
            db,
            acao="ilpi.criada",
            entidade="instituicoes",
            registro_id=obj.id,
            usuario_id=context.user.id,
            ilpi_id=obj.id,
            valores_posteriores={
                "razao_social": obj.razao_social,
                "finalidade": obj.finalidade,
                "situacao": obj.situacao,
                "capacidade": obj.capacidade,
                "uf": obj.uf,
            },
            request=request,
        )
        transition_state(
            db,
            state,
            ILPI_CREATED,
            usuario_id=context.user.id,
            request=request,
            detalhes={"ilpi_id": obj.id},
        )
        await db.commit()
        await db.refresh(obj)
        return obj
    except IntegrityError:
        await db.rollback()
        raise _http_error(status.HTTP_409_CONFLICT, "ILPI_DUPLICADA", "ILPI já cadastrada")
    except HTTPException:
        await db.rollback()
        raise


@instituicoes_router.get("/{item_id}", response_model=s.InstituicaoResponse)
async def get_instituicao(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("ilpis:ler")),
):
    if context.scope == ILPI_SCOPE and item_id != context.ilpi_id:
        raise _http_error(status.HTTP_404_NOT_FOUND, "RESOURCE_NOT_FOUND", "Recurso não encontrado")
    obj = (await db.execute(select(m.Instituicao).where(m.Instituicao.id == item_id))).scalar_one_or_none()
    if obj is None:
        raise _http_error(status.HTTP_404_NOT_FOUND, "RESOURCE_NOT_FOUND", "Recurso não encontrado")
    return obj


@instituicoes_router.put("/{item_id}", response_model=s.InstituicaoResponse)
async def update_instituicao(
    item_id: str,
    payload: s.InstituicaoUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("ilpis:atualizar")),
):
    if context.scope == ILPI_SCOPE and item_id != context.ilpi_id:
        raise _http_error(status.HTTP_404_NOT_FOUND, "RESOURCE_NOT_FOUND", "Recurso não encontrado")
    obj = (await db.execute(select(m.Instituicao).where(m.Instituicao.id == item_id))).scalar_one_or_none()
    if obj is None:
        raise _http_error(status.HTTP_404_NOT_FOUND, "RESOURCE_NOT_FOUND", "Recurso não encontrado")
    before = {"razao_social": obj.razao_social, "situacao": obj.situacao, "cnpj": obj.cnpj, "uf": obj.uf}
    data = _trim_strings(payload.model_dump(exclude_unset=True))
    data.pop("situacao", None)
    for key, value in data.items():
        setattr(obj, key, value)
    add_audit(
        db,
        acao="ilpi.atualizada",
        entidade="instituicoes",
        registro_id=obj.id,
        usuario_id=context.user.id,
        ilpi_id=obj.id,
        valores_anteriores=before,
        valores_posteriores=data,
        request=request,
    )
    try:
        await db.commit()
        await db.refresh(obj)
        return obj
    except IntegrityError:
        await db.rollback()
        raise _http_error(status.HTTP_409_CONFLICT, "ILPI_DUPLICADA", "ILPI já cadastrada")


async def _activation_admin_exists(db: AsyncSession, ilpi_id: str) -> bool:
    result = await db.execute(
        select(func.count())
        .select_from(m.UsuarioIlpiPerfil)
        .join(m.User, m.User.id == m.UsuarioIlpiPerfil.usuario_id)
        .join(m.Perfil, m.Perfil.id == m.UsuarioIlpiPerfil.perfil_id)
        .join(m.Funcionario, m.Funcionario.usuario_id == m.User.id)
        .where(
            m.UsuarioIlpiPerfil.ilpi_id == ilpi_id,
            m.UsuarioIlpiPerfil.situacao == "ativo",
            m.User.ativo.is_(True),
            m.Perfil.ilpi_id == ilpi_id,
            m.Perfil.chave == ILPI_ADMIN_KEY,
            m.Perfil.escopo == ILPI_SCOPE,
            m.Perfil.situacao == "ativo",
            m.Funcionario.ilpi_id == ilpi_id,
            m.Funcionario.situacao == "ativo",
        )
    )
    return result.scalar_one() > 0


def _validate_activation_fields(obj: m.Instituicao) -> None:
    if not obj.cnpj:
        raise _http_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "CNPJ_REQUIRED", "CNPJ obrigatório para ativar ILPI")
    if not validate_cnpj(obj.cnpj):
        raise _http_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "CNPJ_INVALIDO", "CNPJ inválido")
    if obj.capacidade is None or obj.capacidade <= 0:
        raise _http_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "CAPACIDADE_INVALIDA", "Capacidade deve ser maior que zero")
    obj.uf = _ensure_valid_uf(obj.uf)


@instituicoes_router.post("/{item_id}/ativar", response_model=s.InstituicaoResponse)
async def ativar_instituicao(
    item_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("ilpis:ativar")),
):
    _require_global_context(context)
    try:
        state = await load_bootstrap_state(db, for_update=True)
        assert_state(state, ONBOARDING_IN_PROGRESS)
        obj = (await db.execute(select(m.Instituicao).where(m.Instituicao.id == item_id))).scalar_one_or_none()
        if obj is None:
            raise _http_error(status.HTTP_404_NOT_FOUND, "RESOURCE_NOT_FOUND", "Recurso não encontrado")
        _validate_activation_fields(obj)
        if not await _activation_admin_exists(db, obj.id):
            raise _http_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "ONBOARDING_PENDENTE", "Administrador institucional obrigatório")
        before = {"situacao": obj.situacao}
        obj.situacao = ILPI_ACTIVE
        add_audit(
            db,
            acao="ilpi.ativada",
            entidade="instituicoes",
            registro_id=obj.id,
            usuario_id=context.user.id,
            ilpi_id=obj.id,
            valores_anteriores=before,
            valores_posteriores={"situacao": obj.situacao},
            request=request,
        )
        transition_state(
            db,
            state,
            ONBOARDING_COMPLETED,
            usuario_id=context.user.id,
            request=request,
            detalhes={"ilpi_id": obj.id},
        )
        await db.commit()
        await db.refresh(obj)
        return obj
    except HTTPException:
        await db.rollback()
        raise


@instituicoes_router.delete("/{item_id}", status_code=204)
async def delete_instituicao_logico(
    item_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("ilpis:inativar")),
):
    obj = (await db.execute(select(m.Instituicao).where(m.Instituicao.id == item_id))).scalar_one_or_none()
    if obj is None:
        raise _http_error(status.HTTP_404_NOT_FOUND, "RESOURCE_NOT_FOUND", "Recurso não encontrado")
    before = {"situacao": obj.situacao}
    obj.situacao = ILPI_INACTIVE
    add_audit(
        db,
        acao="ilpi.inativada",
        entidade="instituicoes",
        registro_id=obj.id,
        usuario_id=context.user.id,
        ilpi_id=obj.id,
        valores_anteriores=before,
        valores_posteriores={"situacao": obj.situacao},
        request=request,
    )
    await db.commit()
    return None


async def _clone_ilpi_admin_profile(db: AsyncSession, ilpi_id: str, request: Request, user_id: str) -> m.Perfil:
    template = (
        await db.execute(
            select(m.Perfil).where(m.Perfil.chave == ILPI_ADMIN_KEY, m.Perfil.ilpi_id.is_(None))
        )
    ).scalar_one()
    existing = (
        await db.execute(
            select(m.Perfil).where(m.Perfil.chave == ILPI_ADMIN_KEY, m.Perfil.ilpi_id == ilpi_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    profile = m.Perfil(
        id=_new_id(),
        ilpi_id=ilpi_id,
        nome=template.nome,
        chave=template.chave,
        descricao=template.descricao,
        escopo=ILPI_SCOPE,
        situacao="ativo",
    )
    db.add(profile)
    await db.flush()
    permission_ids = (
        await db.execute(
            select(m.PerfilPermissao.permissao_id).where(m.PerfilPermissao.perfil_id == template.id)
        )
    ).scalars().all()
    for permission_id in permission_ids:
        db.add(m.PerfilPermissao(perfil_id=profile.id, permissao_id=permission_id))
    add_audit(
        db,
        acao="perfil.clonado",
        entidade="perfis",
        registro_id=profile.id,
        usuario_id=user_id,
        ilpi_id=ilpi_id,
        valores_posteriores={"chave": profile.chave, "template_id": template.id, "permissoes": len(permission_ids)},
        request=request,
    )
    return profile


async def _create_current_user_as_admin(
    db: AsyncSession,
    *,
    ilpi: m.Instituicao,
    current_user: m.User,
    request: Request,
) -> None:
    profile = await _clone_ilpi_admin_profile(db, ilpi.id, request, current_user.id)
    employee = (
        await db.execute(
            select(m.Funcionario).where(
                m.Funcionario.ilpi_id == ilpi.id,
                m.Funcionario.usuario_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if employee is None:
        employee = m.Funcionario(
            id=_new_id(),
            ilpi_id=ilpi.id,
            usuario_id=current_user.id,
            nome=current_user.nome,
            email=current_user.email,
            cargo="Administrador da ILPI",
            situacao="ativo",
        )
        db.add(employee)
        await db.flush()
        add_audit(
            db,
            acao="funcionario.criado",
            entidade="funcionarios",
            registro_id=employee.id,
            usuario_id=current_user.id,
            ilpi_id=ilpi.id,
            valores_posteriores={"nome": employee.nome, "email": employee.email, "cargo": employee.cargo},
            request=request,
        )

    link = (
        await db.execute(
            select(m.UsuarioIlpiPerfil).where(
                m.UsuarioIlpiPerfil.usuario_id == current_user.id,
                m.UsuarioIlpiPerfil.ilpi_id == ilpi.id,
                m.UsuarioIlpiPerfil.perfil_id == profile.id,
            )
        )
    ).scalar_one_or_none()
    if link is None:
        link = m.UsuarioIlpiPerfil(
            id=_new_id(),
            usuario_id=current_user.id,
            ilpi_id=ilpi.id,
            perfil_id=profile.id,
            situacao="ativo",
        )
        db.add(link)
        await db.flush()
        add_audit(
            db,
            acao="usuario_ilpi_perfil.criado",
            entidade="usuario_ilpi_perfis",
            registro_id=link.id,
            usuario_id=current_user.id,
            ilpi_id=ilpi.id,
            valores_posteriores={"usuario_id": current_user.id, "perfil_id": profile.id, "ilpi_id": ilpi.id},
            request=request,
        )


async def _load_ilpi_for_onboarding(db: AsyncSession, ilpi_id: str) -> m.Instituicao:
    ilpi = (await db.execute(select(m.Instituicao).where(m.Instituicao.id == ilpi_id))).scalar_one_or_none()
    if ilpi is None:
        raise _http_error(status.HTTP_404_NOT_FOUND, "RESOURCE_NOT_FOUND", "Recurso não encontrado")
    return ilpi


@onboarding_router.post("/{ilpi_id}/iniciar")
async def iniciar_onboarding(
    ilpi_id: str,
    payload: s.OnboardingStart,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("ilpis:atualizar")),
):
    _require_global_context(context)
    try:
        state = await load_bootstrap_state(db, for_update=True)
        assert_state(state, ILPI_CREATED)
        ilpi = await _load_ilpi_for_onboarding(db, ilpi_id)
        if payload.usar_usuario_atual_como_admin:
            await _create_current_user_as_admin(db, ilpi=ilpi, current_user=context.user, request=request)
        add_audit(
            db,
            acao="onboarding.iniciado",
            entidade="instituicoes",
            registro_id=ilpi.id,
            usuario_id=context.user.id,
            ilpi_id=ilpi.id,
            valores_posteriores={"usar_usuario_atual_como_admin": payload.usar_usuario_atual_como_admin},
            request=request,
        )
        transition_state(
            db,
            state,
            ONBOARDING_IN_PROGRESS,
            usuario_id=context.user.id,
            request=request,
            detalhes={"ilpi_id": ilpi.id},
        )
        await db.commit()
        return {"estado": ONBOARDING_IN_PROGRESS, "ilpi_id": ilpi.id}
    except HTTPException:
        await db.rollback()
        raise


@onboarding_router.post("/{ilpi_id}/admin-atual")
async def criar_admin_atual_onboarding(
    ilpi_id: str,
    payload: s.OnboardingStart,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("ilpis:atualizar")),
):
    _require_global_context(context)
    if not payload.usar_usuario_atual_como_admin:
        raise _http_error(status.HTTP_422_UNPROCESSABLE_ENTITY, "CONFIRMACAO_REQUIRED", "Confirmação explícita obrigatória")
    try:
        state = await load_bootstrap_state(db, for_update=True)
        assert_state(state, ONBOARDING_IN_PROGRESS)
        ilpi = await _load_ilpi_for_onboarding(db, ilpi_id)
        await _create_current_user_as_admin(db, ilpi=ilpi, current_user=context.user, request=request)
        add_audit(
            db,
            acao="onboarding.admin_atual_criado",
            entidade="instituicoes",
            registro_id=ilpi.id,
            usuario_id=context.user.id,
            ilpi_id=ilpi.id,
            request=request,
        )
        await db.commit()
        return {"estado": state.estado, "ilpi_id": ilpi.id}
    except HTTPException:
        await db.rollback()
        raise


@usuarios_router.post("/", response_model=s.UsuarioAdminResponse, status_code=201)
async def criar_usuario(
    payload: s.UsuarioAdminCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("usuarios:criar")),
):
    _require_ilpi_context(context)
    temp_password = _temporary_password()
    user = m.User(
        id=_new_id(),
        nome=payload.nome.strip(),
        email=_normalise_email(str(payload.email)),
        password_hash=hash_password(temp_password),
        ativo=True,
        is_superuser=False,
        exige_troca_senha=True,
    )
    try:
        db.add(user)
        await db.flush()
        add_audit(
            db,
            acao="usuario.criado",
            entidade="users",
            registro_id=user.id,
            usuario_id=context.user.id,
            ilpi_id=context.ilpi_id,
            valores_posteriores=_public_user(user),
            request=request,
        )
        if payload.perfil_id:
            await _assign_profile_to_user(db, context, user.id, payload.perfil_id, request)
        await db.commit()
        return {**_public_user(user), "senha_temporaria": temp_password}
    except IntegrityError:
        await db.rollback()
        raise _http_error(status.HTTP_409_CONFLICT, "EMAIL_DUPLICADO", "E-mail já cadastrado")
    except HTTPException:
        await db.rollback()
        raise


@usuarios_router.post("/{user_id}/perfis", status_code=201)
async def atribuir_perfil_usuario(
    user_id: str,
    payload: s.UsuarioPerfilAssign,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("usuarios:atribuir_perfil")),
):
    _require_ilpi_context(context)
    try:
        link = await _assign_profile_to_user(db, context, user_id, payload.perfil_id, request)
        await db.commit()
        return {"id": link.id, "usuario_id": link.usuario_id, "perfil_id": link.perfil_id, "ilpi_id": link.ilpi_id}
    except IntegrityError:
        await db.rollback()
        raise _http_error(status.HTTP_409_CONFLICT, "VINCULO_DUPLICADO", "Perfil já atribuído ao usuário")
    except HTTPException:
        await db.rollback()
        raise


async def _assign_profile_to_user(
    db: AsyncSession,
    context: SecurityContext,
    user_id: str,
    perfil_id: str,
    request: Request,
) -> m.UsuarioIlpiPerfil:
    target = (await db.execute(select(m.User).where(m.User.id == user_id))).scalar_one_or_none()
    if target is None:
        raise _http_error(status.HTTP_404_NOT_FOUND, "USER_NOT_FOUND", "Usuário não encontrado")
    profile = (
        await db.execute(
            select(m.Perfil).where(
                m.Perfil.id == perfil_id,
                m.Perfil.ilpi_id == context.ilpi_id,
                m.Perfil.escopo == ILPI_SCOPE,
                m.Perfil.situacao == "ativo",
            )
        )
    ).scalar_one_or_none()
    if profile is None:
        raise _http_error(status.HTTP_403_FORBIDDEN, "PERFIL_LOCAL_REQUIRED", "Perfil institucional obrigatório")
    link = m.UsuarioIlpiPerfil(
        id=_new_id(),
        usuario_id=target.id,
        ilpi_id=context.ilpi_id,
        perfil_id=profile.id,
        situacao="ativo",
    )
    db.add(link)
    await db.flush()
    add_audit(
        db,
        acao="usuario_ilpi_perfil.criado",
        entidade="usuario_ilpi_perfis",
        registro_id=link.id,
        usuario_id=context.user.id,
        ilpi_id=context.ilpi_id,
        valores_posteriores={"usuario_id": target.id, "perfil_id": profile.id, "ilpi_id": context.ilpi_id},
        request=request,
    )
    return link


@usuarios_router.patch("/{user_id}/reset-password", response_model=s.ResetPasswordResponse)
async def reset_password_usuario(
    user_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("usuarios:redefinir_senha")),
):
    target = (await db.execute(select(m.User).where(m.User.id == user_id))).scalar_one_or_none()
    if target is None:
        raise _http_error(status.HTTP_404_NOT_FOUND, "USER_NOT_FOUND", "Usuário não encontrado")
    if context.scope == ILPI_SCOPE:
        link_exists = (
            await db.execute(
                select(func.count()).select_from(m.UsuarioIlpiPerfil).where(
                    m.UsuarioIlpiPerfil.usuario_id == target.id,
                    m.UsuarioIlpiPerfil.ilpi_id == context.ilpi_id,
                    m.UsuarioIlpiPerfil.situacao == "ativo",
                )
            )
        ).scalar_one()
        if link_exists == 0:
            raise _http_error(status.HTTP_404_NOT_FOUND, "USER_NOT_FOUND", "Usuário não encontrado")
    temp_password = _temporary_password()
    target.password_hash = hash_password(temp_password)
    target.exige_troca_senha = True
    await revoke_user_refresh_tokens(db, target.id)
    add_audit(
        db,
        acao="usuario.senha_redefinida",
        entidade="users",
        registro_id=target.id,
        usuario_id=context.user.id,
        ilpi_id=context.ilpi_id,
        valores_posteriores={"exige_troca_senha": True},
        request=request,
    )
    await db.commit()
    return {"senha_temporaria": temp_password}


@funcionarios_router.post("/", response_model=s.FuncionarioResponse, status_code=201)
async def criar_funcionario(
    payload: s.FuncionarioAdminCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("funcionarios:criar")),
):
    _require_ilpi_context(context)
    data = _trim_strings(payload.model_dump(exclude_unset=True))
    employee = m.Funcionario(id=_new_id(), ilpi_id=context.ilpi_id, situacao="ativo", **data)
    try:
        db.add(employee)
        await db.flush()
        add_audit(
            db,
            acao="funcionario.criado",
            entidade="funcionarios",
            registro_id=employee.id,
            usuario_id=context.user.id,
            ilpi_id=context.ilpi_id,
            valores_posteriores={"nome": employee.nome, "cpf": employee.cpf, "email": employee.email},
            request=request,
        )
        await db.commit()
        await db.refresh(employee)
        return employee
    except IntegrityError:
        await db.rollback()
        raise _http_error(status.HTTP_409_CONFLICT, "FUNCIONARIO_DUPLICADO", "Funcionário já cadastrado nesta ILPI")


@funcionarios_router.post("/{funcionario_id}/vincular-usuario", response_model=s.FuncionarioResponse)
async def vincular_usuario_funcionario(
    funcionario_id: str,
    payload: s.VincularUsuarioFuncionario,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("funcionarios:vincular_usuario")),
):
    _require_ilpi_context(context)
    employee = (
        await db.execute(
            select(m.Funcionario).where(m.Funcionario.id == funcionario_id, m.Funcionario.ilpi_id == context.ilpi_id)
        )
    ).scalar_one_or_none()
    if employee is None:
        raise _http_error(status.HTTP_404_NOT_FOUND, "FUNCIONARIO_NOT_FOUND", "Funcionário não encontrado")
    user = (await db.execute(select(m.User).where(m.User.id == payload.usuario_id))).scalar_one_or_none()
    if user is None:
        raise _http_error(status.HTTP_404_NOT_FOUND, "USER_NOT_FOUND", "Usuário não encontrado")
    same_tenant = (
        await db.execute(
            select(func.count()).select_from(m.UsuarioIlpiPerfil).where(
                m.UsuarioIlpiPerfil.usuario_id == user.id,
                m.UsuarioIlpiPerfil.ilpi_id == context.ilpi_id,
                m.UsuarioIlpiPerfil.situacao == "ativo",
            )
        )
    ).scalar_one()
    if same_tenant == 0:
        raise _http_error(status.HTTP_403_FORBIDDEN, "USER_TENANT_MISMATCH", "Usuário não pertence à ILPI")
    before = {"usuario_id": employee.usuario_id}
    employee.usuario_id = user.id
    add_audit(
        db,
        acao="funcionario.usuario_vinculado",
        entidade="funcionarios",
        registro_id=employee.id,
        usuario_id=context.user.id,
        ilpi_id=context.ilpi_id,
        valores_anteriores=before,
        valores_posteriores={"usuario_id": user.id},
        request=request,
    )
    try:
        await db.commit()
        await db.refresh(employee)
        return employee
    except IntegrityError:
        await db.rollback()
        raise _http_error(status.HTTP_409_CONFLICT, "FUNCIONARIO_DUPLICADO", "Usuário já vinculado a funcionário nesta ILPI")


@perfis_router.post("/", response_model=s.PerfilResponse, status_code=201)
async def criar_perfil(
    payload: s.PerfilAdminCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("perfis:criar")),
):
    _require_ilpi_context(context)
    if payload.chave == PLATFORM_SUPERUSER_KEY:
        raise _http_error(status.HTTP_403_FORBIDDEN, "PERFIL_GLOBAL_FORBIDDEN", "Perfil global não permitido em contexto local")
    profile = m.Perfil(
        id=_new_id(),
        ilpi_id=context.ilpi_id,
        nome=payload.nome.strip(),
        chave=payload.chave.strip(),
        descricao=payload.descricao.strip() if payload.descricao else None,
        escopo=ILPI_SCOPE,
        situacao="ativo",
    )
    try:
        db.add(profile)
        await db.flush()
        add_audit(
            db,
            acao="perfil.criado",
            entidade="perfis",
            registro_id=profile.id,
            usuario_id=context.user.id,
            ilpi_id=context.ilpi_id,
            valores_posteriores={"chave": profile.chave, "escopo": profile.escopo},
            request=request,
        )
        await db.commit()
        await db.refresh(profile)
        return profile
    except IntegrityError:
        await db.rollback()
        raise _http_error(status.HTTP_409_CONFLICT, "PERFIL_DUPLICADO", "Perfil já existe nesta ILPI")


def _permission_allowed_for_local(permission: m.Permissao) -> bool:
    return permission.modulo not in CLINICAL_MODULES and permission.chave not in GLOBAL_ONLY_PERMISSIONS and "*" not in permission.chave


@perfis_router.put("/{perfil_id}/permissoes")
async def atualizar_permissoes_perfil(
    perfil_id: str,
    payload: s.PerfilPermissoesUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("perfis:atribuir_permissao")),
):
    _require_ilpi_context(context)
    profile = (
        await db.execute(
            select(m.Perfil).where(m.Perfil.id == perfil_id, m.Perfil.ilpi_id == context.ilpi_id, m.Perfil.escopo == ILPI_SCOPE)
        )
    ).scalar_one_or_none()
    if profile is None:
        raise _http_error(status.HTTP_404_NOT_FOUND, "PERFIL_NOT_FOUND", "Perfil não encontrado")
    permissions = (
        await db.execute(select(m.Permissao).where(m.Permissao.chave.in_(payload.permissoes)))
    ).scalars().all()
    found = {permission.chave for permission in permissions}
    if found != set(payload.permissoes):
        raise _http_error(status.HTTP_404_NOT_FOUND, "PERMISSAO_NOT_FOUND", "Permissão não encontrada")
    if any(not _permission_allowed_for_local(permission) for permission in permissions):
        raise _http_error(status.HTTP_403_FORBIDDEN, "PERMISSAO_FORBIDDEN", "Permissão não permitida nesta fase")
    existing = (
        await db.execute(select(m.PerfilPermissao).where(m.PerfilPermissao.perfil_id == profile.id))
    ).scalars().all()
    before = [item.permissao_id for item in existing]
    for item in existing:
        await db.delete(item)
    for permission in permissions:
        db.add(m.PerfilPermissao(perfil_id=profile.id, permissao_id=permission.id))
    add_audit(
        db,
        acao="perfil.permissoes_atualizadas",
        entidade="perfis",
        registro_id=profile.id,
        usuario_id=context.user.id,
        ilpi_id=context.ilpi_id,
        valores_anteriores={"permissoes": before},
        valores_posteriores={"permissoes": sorted(payload.permissoes)},
        request=request,
    )
    await db.commit()
    return {"perfil_id": profile.id, "permissoes": sorted(payload.permissoes)}


@permissoes_router.get("/")
async def listar_permissoes(
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("permissoes:ler")),
):
    query = select(m.Permissao).order_by(m.Permissao.modulo, m.Permissao.acao)
    permissions = (await db.execute(query)).scalars().all()
    if context.scope == ILPI_SCOPE:
        permissions = [permission for permission in permissions if _permission_allowed_for_local(permission)]
    return [
        {
            "id": permission.id,
            "modulo": permission.modulo,
            "acao": permission.acao,
            "chave": permission.chave,
            "descricao": permission.descricao,
        }
        for permission in permissions
    ]
