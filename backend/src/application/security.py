"""Security context and authorization guards for the RBAC core.

The access token identifies an authenticated user only.  Institutional and
profile context is resolved from the database on every context load; request
selectors are merely validated hints and never become authorization data by
themselves.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure.database import get_db
from ..infrastructure.models import (
    Funcionario,
    Perfil,
    PerfilPermissao,
    Permissao,
    User,
    UsuarioIlpiPerfil,
)
from .auth import (
    AUTH_CONTEXT_REQUIRED,
    AUTHENTICATION_REQUIRED,
    decode_access_token,
    get_current_user,
)


logger = logging.getLogger("facilpi.security")

GLOBAL_SCOPE = "global"
ILPI_SCOPE = "ilpi"

GLOBAL_SCOPE_REQUIRED = "GLOBAL_SCOPE_REQUIRED"
ILPI_CONTEXT_REQUIRED = "ILPI_CONTEXT_REQUIRED"
PROFILE_SELECTION_REQUIRED = "PROFILE_SELECTION_REQUIRED"
PERMISSION_DENIED = "PERMISSION_DENIED"
RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
PERMISSION_CATALOG_PENDING = "PERMISSION_CATALOG_PENDING"
FIRST_PASSWORD_CHANGE_REQUIRED = "FIRST_PASSWORD_CHANGE_REQUIRED"

# These values are the scope metadata of migration 004.  The database model
# intentionally stores the permission key, not this catalog annotation.
_GLOBAL_ONLY_PERMISSIONS = frozenset(
    {
        "ilpis:criar",
        "ilpis:ativar",
        "ilpis:suspender",
        "ilpis:inativar",
    }
)
_ILPI_ONLY_PERMISSIONS = frozenset(
    {
        "funcionarios:ler",
        "funcionarios:criar",
        "funcionarios:atualizar",
        "funcionarios:inativar",
        "funcionarios:vincular_usuario",
        "perfis:criar",
        "perfis:atualizar",
        "perfis:inativar",
        "perfis:atribuir_permissao",
        "configuracoes:ler",
        "configuracoes:atualizar",
        "residentes:ler",
        "residentes:criar",
        "residentes:atualizar",
        "residentes:inativar",
        "familiares:ler",
        "familiares:criar",
        "familiares:atualizar",
        "familiares:inativar",
        "tarefas:ler",
        "tarefas:criar",
        "tarefas:atualizar",
        "tarefas:inativar",
        "sinais_vitais:ler",
        "sinais_vitais:criar",
    }
)
_CLINICAL_MODULES = frozenset(
    {
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
)


@dataclass(frozen=True, slots=True)
class SecurityContext:
    """A database-verified authorization context for one request."""

    user: User
    perfil: Perfil
    vinculo: UsuarioIlpiPerfil
    scope: str
    ilpi_id: str | None
    permission_keys: frozenset[str] = field(default_factory=frozenset)

    @property
    def profile(self) -> Perfil:
        return self.perfil

    @property
    def link(self) -> UsuarioIlpiPerfil:
        return self.vinculo

    @property
    def perfil_id(self) -> str:
        return self.perfil.id

    @property
    def tenant_id(self) -> str | None:
        return self.ilpi_id


@dataclass(frozen=True, slots=True)
class _ContextCandidate:
    perfil: Perfil
    vinculo: UsuarioIlpiPerfil
    scope: str
    ilpi_id: str | None


def _deny(
    *,
    code: str,
    http_status: int,
    message: str,
    context: SecurityContext | None = None,
    user_id: str | None = None,
) -> None:
    """Log only technical identifiers, never request or credential data."""

    resolved_user_id = user_id
    resolved_scope: str | None = None
    resolved_ilpi_id: str | None = None
    resolved_perfil_id: str | None = None
    if context is not None:
        resolved_user_id = context.user.id
        resolved_scope = context.scope
        resolved_ilpi_id = context.ilpi_id
        resolved_perfil_id = context.perfil.id

    logger.warning(
        "authorization_denied code=%s status=%s user_id=%s scope=%s ilpi_id=%s perfil_id=%s",
        code,
        http_status,
        resolved_user_id,
        resolved_scope,
        resolved_ilpi_id,
        resolved_perfil_id,
    )
    raise HTTPException(
        status_code=http_status,
        detail={"code": code, "message": message},
    )


def _is_current_link(vinculo: UsuarioIlpiPerfil) -> bool:
    now = datetime.now(timezone.utc)
    if vinculo.data_inicial is not None:
        start = vinculo.data_inicial
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        if start > now:
            return False
    if vinculo.data_final is not None:
        end = vinculo.data_final
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if end <= now:
            return False
    return True


def _candidate_for(
    user_id: str,
    perfil: Perfil,
    vinculo: UsuarioIlpiPerfil,
) -> _ContextCandidate | None:
    if vinculo.usuario_id != user_id:
        return None
    if vinculo.situacao != "ativo" or perfil.situacao != "ativo":
        return None
    if not _is_current_link(vinculo):
        return None

    if perfil.escopo == GLOBAL_SCOPE:
        if (
            perfil.chave != "platform_superuser"
            or perfil.ilpi_id is not None
            or vinculo.ilpi_id is not None
        ):
            return None
        return _ContextCandidate(perfil, vinculo, GLOBAL_SCOPE, None)

    if perfil.escopo == ILPI_SCOPE:
        # A template profile (including ilpi_admin) has no tenant and cannot
        # authorize institutional access by itself.
        if (
            perfil.chave == "platform_superuser"
            or perfil.ilpi_id is None
            or vinculo.ilpi_id is None
            or perfil.ilpi_id != vinculo.ilpi_id
        ):
            return None
        return _ContextCandidate(perfil, vinculo, ILPI_SCOPE, vinculo.ilpi_id)

    return None


def _normalise_selector(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None


def _context_is_valid(context: SecurityContext) -> bool:
    """Validate the invariants again for guards receiving a context object."""

    if not isinstance(context, SecurityContext) or not context.user.ativo:
        return False
    if context.perfil.situacao != "ativo" or context.vinculo.situacao != "ativo":
        return False
    if context.vinculo.usuario_id != context.user.id or not _is_current_link(context.vinculo):
        return False

    if context.scope == GLOBAL_SCOPE:
        return (
            context.ilpi_id is None
            and context.perfil.escopo == GLOBAL_SCOPE
            and context.perfil.chave == "platform_superuser"
            and context.perfil.ilpi_id is None
            and context.vinculo.ilpi_id is None
        )

    return (
        context.scope == ILPI_SCOPE
        and context.ilpi_id is not None
        and context.perfil.escopo == ILPI_SCOPE
        and context.perfil.ilpi_id is not None
        and context.vinculo.ilpi_id == context.perfil.ilpi_id == context.ilpi_id
        and context.perfil.chave != "platform_superuser"
    )


async def load_security_context(
    db: AsyncSession,
    user: User | str,
    *,
    scope: str | None = None,
    ilpi_id: str | None = None,
    perfil_id: str | None = None,
) -> SecurityContext:
    """Load and validate one context from the authenticated user's database row."""

    user_id = user.id if isinstance(user, User) else user
    if not isinstance(user_id, str) or not user_id:
        _deny(
            code=AUTHENTICATION_REQUIRED,
            http_status=status.HTTP_401_UNAUTHORIZED,
            message="Autenticação obrigatória",
            user_id=None,
        )

    user_result = await db.execute(select(User).where(User.id == user_id))
    database_user = user_result.scalar_one_or_none()
    if database_user is None:
        _deny(
            code=AUTHENTICATION_REQUIRED,
            http_status=status.HTTP_401_UNAUTHORIZED,
            message="Autenticação obrigatória",
            user_id=user_id,
        )
    if not database_user.ativo:
        _deny(
            code=AUTH_CONTEXT_REQUIRED,
            http_status=status.HTTP_403_FORBIDDEN,
            message="Contexto de autorização não disponível",
            user_id=database_user.id,
        )

    selected_scope = _normalise_selector(scope)
    selected_ilpi_id = _normalise_selector(ilpi_id)
    selected_perfil_id = _normalise_selector(perfil_id)
    if selected_scope is not None:
        selected_scope = selected_scope.lower()
        if selected_scope not in {GLOBAL_SCOPE, ILPI_SCOPE}:
            _deny(
                code=AUTH_CONTEXT_REQUIRED,
                http_status=status.HTTP_403_FORBIDDEN,
                message="Contexto de autorização não disponível",
                user_id=database_user.id,
            )

    rows = (
        await db.execute(
            select(UsuarioIlpiPerfil, Perfil)
            .join(Perfil, Perfil.id == UsuarioIlpiPerfil.perfil_id)
            .where(UsuarioIlpiPerfil.usuario_id == database_user.id)
        )
    ).all()
    candidates = [
        candidate
        for vinculo, perfil in rows
        if (candidate := _candidate_for(database_user.id, perfil, vinculo)) is not None
    ]

    if selected_scope == GLOBAL_SCOPE and selected_ilpi_id is not None:
        candidates = []
    else:
        if selected_scope is not None:
            candidates = [item for item in candidates if item.scope == selected_scope]
        if selected_ilpi_id is not None:
            candidates = [
                item for item in candidates if item.ilpi_id == selected_ilpi_id
            ]
    if selected_perfil_id is not None:
        candidates = [item for item in candidates if item.perfil.id == selected_perfil_id]

    if len(candidates) == 0:
        _deny(
            code=AUTH_CONTEXT_REQUIRED,
            http_status=status.HTTP_403_FORBIDDEN,
            message="Contexto de autorização não disponível",
            user_id=database_user.id,
        )
    if len(candidates) > 1:
        _deny(
            code=PROFILE_SELECTION_REQUIRED,
            http_status=status.HTTP_403_FORBIDDEN,
            message="Selecione um perfil e contexto",
            user_id=database_user.id,
        )

    candidate = candidates[0]
    permissions = (
        await db.execute(
            select(Permissao.chave)
            .join(PerfilPermissao, PerfilPermissao.permissao_id == Permissao.id)
            .where(PerfilPermissao.perfil_id == candidate.perfil.id)
        )
    ).scalars().all()
    context = SecurityContext(
        user=database_user,
        perfil=candidate.perfil,
        vinculo=candidate.vinculo,
        scope=candidate.scope,
        ilpi_id=candidate.ilpi_id,
        permission_keys=frozenset(permissions),
    )
    if not _context_is_valid(context):
        _deny(
            code=AUTH_CONTEXT_REQUIRED,
            http_status=status.HTTP_403_FORBIDDEN,
            message="Contexto de autorização não disponível",
            context=context,
        )
    if context.scope == ILPI_SCOPE:
        active_employee = (
            await db.execute(
                select(Funcionario.id).where(
                    Funcionario.ilpi_id == context.ilpi_id,
                    Funcionario.usuario_id == context.user.id,
                    Funcionario.situacao == "ativo",
                )
            )
        ).scalar_one_or_none()
        if active_employee is None:
            _deny(
                code=AUTH_CONTEXT_REQUIRED,
                http_status=status.HTTP_403_FORBIDDEN,
                message="Contexto de autorização não disponível",
                context=context,
            )
    return context


async def build_security_context(
    user: User | str,
    db: AsyncSession,
    *,
    scope: str | None = None,
    ilpi_id: str | None = None,
    perfil_id: str | None = None,
) -> SecurityContext:
    """Argument-order convenience wrapper for application services/tests."""

    return await load_security_context(
        db,
        user,
        scope=scope,
        ilpi_id=ilpi_id,
        perfil_id=perfil_id,
    )


def _header(request: Request, *names: str) -> str | None:
    for name in names:
        value = _normalise_selector(request.headers.get(name))
        if value is not None:
            return value
    return None


def _token_payload_from_request(request: Request) -> dict | None:
    header = request.headers.get("authorization")
    if not header:
        return None
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        return None
    return decode_access_token(token)


async def get_security_context(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SecurityContext:
    """FastAPI dependency resolving only validated header selectors.

    Body and query-string tenant values are deliberately not read here.  A
    future route may send a profile/tenant selector in these headers, but the
    selector is always checked against the user's database links.
    """
    if current_user.exige_troca_senha:
        _deny(
            code=FIRST_PASSWORD_CHANGE_REQUIRED,
            http_status=status.HTTP_403_FORBIDDEN,
            message="Troca de senha obrigatória",
            user_id=current_user.id,
        )

    token_payload = _token_payload_from_request(request)
    token_scope = _normalise_selector(token_payload.get("scope") if token_payload else None)
    token_ilpi_id = _normalise_selector(token_payload.get("ilpi_id") if token_payload else None)
    token_perfil_id = _normalise_selector(token_payload.get("perfil_id") if token_payload else None)
    header_scope = _header(request, "X-Scope", "X-Context-Scope")
    header_ilpi_id = _header(request, "X-ILPI-ID", "X-Instituicao-ID")
    header_perfil_id = _header(request, "X-Perfil-ID", "X-Profile-ID")

    if token_scope is not None:
        for selected, header_value in (
            (token_scope, header_scope),
            (token_ilpi_id, header_ilpi_id),
            (token_perfil_id, header_perfil_id),
        ):
            if header_value is not None and header_value != selected:
                _deny(
                    code=AUTH_CONTEXT_REQUIRED,
                    http_status=status.HTTP_403_FORBIDDEN,
                    message="Contexto de autorização não disponível",
                    user_id=current_user.id,
                )
        scope = token_scope
        ilpi_id = token_ilpi_id
        perfil_id = token_perfil_id
    else:
        scope = header_scope
        ilpi_id = header_ilpi_id
        perfil_id = header_perfil_id

    return await load_security_context(
        db,
        current_user,
        scope=scope,
        ilpi_id=ilpi_id,
        perfil_id=perfil_id,
    )


async def require_global_scope(
    context: SecurityContext = Depends(get_security_context),
) -> SecurityContext:
    if not _context_is_valid(context):
        _deny(
            code=AUTH_CONTEXT_REQUIRED,
            http_status=status.HTTP_403_FORBIDDEN,
            message="Contexto de autorização não disponível",
            context=context if isinstance(context, SecurityContext) else None,
        )
    if context.scope != GLOBAL_SCOPE:
        _deny(
            code=GLOBAL_SCOPE_REQUIRED,
            http_status=status.HTTP_403_FORBIDDEN,
            message="Escopo global obrigatório",
            context=context,
        )
    return context


async def require_ilpi_context(
    context: SecurityContext = Depends(get_security_context),
) -> SecurityContext:
    if not _context_is_valid(context):
        _deny(
            code=AUTH_CONTEXT_REQUIRED,
            http_status=status.HTTP_403_FORBIDDEN,
            message="Contexto de autorização não disponível",
            context=context if isinstance(context, SecurityContext) else None,
        )
    if context.scope != ILPI_SCOPE:
        _deny(
            code=ILPI_CONTEXT_REQUIRED,
            http_status=status.HTTP_403_FORBIDDEN,
            message="Contexto institucional obrigatório",
            context=context,
        )
    return context


def _permission_is_allowed(context: SecurityContext, permission: Permissao) -> bool:
    key = permission.chave
    if "*" in key:
        return False
    if context.scope == GLOBAL_SCOPE and key in _ILPI_ONLY_PERMISSIONS:
        return False
    if context.scope == ILPI_SCOPE and key in _GLOBAL_ONLY_PERMISSIONS:
        return False
    # The platform profile is intentionally limited to non-clinical catalog
    # permissions even if an unsafe link is inserted later.
    return not (
        context.perfil.chave == "platform_superuser"
        and permission.modulo in _CLINICAL_MODULES
    )


def require_permission(permission_key: str):
    """Create a FastAPI dependency for one exact permission key."""

    async def permission_guard(
        context: SecurityContext = Depends(get_security_context),
        db: AsyncSession = Depends(get_db),
    ) -> SecurityContext:
        if not _context_is_valid(context):
            _deny(
                code=AUTH_CONTEXT_REQUIRED,
                http_status=status.HTTP_403_FORBIDDEN,
                message="Contexto de autorização não disponível",
                context=context if isinstance(context, SecurityContext) else None,
            )

        if not isinstance(permission_key, str) or not permission_key or "*" in permission_key:
            _deny(
                code=PERMISSION_DENIED,
                http_status=status.HTTP_403_FORBIDDEN,
                message="Permissão não autorizada",
                context=context,
            )

        # Re-read the context so an inactivated user/profile/link cannot use a
        # context object created before the change.
        if isinstance(db, AsyncSession):
            context = await load_security_context(
                db,
                context.user.id,
                scope=context.scope,
                ilpi_id=context.ilpi_id,
                perfil_id=context.perfil.id,
            )
            permission = (
                await db.execute(
                    select(Permissao)
                    .join(PerfilPermissao, PerfilPermissao.permissao_id == Permissao.id)
                    .where(
                        PerfilPermissao.perfil_id == context.perfil.id,
                        Permissao.chave == permission_key,
                    )
                )
            ).scalar_one_or_none()
        else:
            permission = None
            if permission_key in context.permission_keys:
                # Direct callers without a session still get exact-key
                # semantics; FastAPI always supplies the database session.
                permission = Permissao(
                    chave=permission_key,
                    modulo=permission_key.split(":", 1)[0],
                    acao=permission_key.split(":", 1)[1]
                    if ":" in permission_key
                    else "",
                )

        if permission is None or not _permission_is_allowed(context, permission):
            _deny(
                code=PERMISSION_DENIED,
                http_status=status.HTTP_403_FORBIDDEN,
                message="Permissão não autorizada",
                context=context,
            )
        return context

    permission_guard.__name__ = (
        f"require_permission_{str(permission_key).replace(':', '_')}"
    )
    return permission_guard


async def block_pending_permission_catalog(
    current_user: User = Depends(get_current_user),
) -> None:
    _deny(
        code=PERMISSION_CATALOG_PENDING,
        http_status=status.HTTP_403_FORBIDDEN,
        message="Catálogo de permissões pendente",
        user_id=current_user.id,
    )


def _resource_tenant(resource: Any) -> str | None:
    if resource is None or isinstance(resource, str):
        return resource
    if isinstance(resource, Mapping):
        for attribute in ("ilpi_id", "instituicao_id"):
            value = resource.get(attribute)
            if value is not None:
                return value
        return None
    for attribute in ("ilpi_id", "instituicao_id"):
        if hasattr(resource, attribute):
            value = getattr(resource, attribute)
            if value is not None:
                return value
    return None


def ensure_same_tenant(
    context: SecurityContext,
    resource: Any,
) -> str:
    """Ensure an institutional resource belongs to the session tenant.

    A global context has no tenant and is allowed to compare/access a resource
    from any tenant; the permission guard still applies.  Institutional
    mismatches deliberately look like a missing resource.
    """

    resource_ilpi_id = _resource_tenant(resource)
    if not _context_is_valid(context):
        _deny(
            code=AUTH_CONTEXT_REQUIRED,
            http_status=status.HTTP_403_FORBIDDEN,
            message="Contexto de autorização não disponível",
            context=context if isinstance(context, SecurityContext) else None,
        )
    if context.scope == GLOBAL_SCOPE:
        if resource_ilpi_id is None:
            _deny(
                code=RESOURCE_NOT_FOUND,
                http_status=status.HTTP_404_NOT_FOUND,
                message="Recurso não encontrado",
                context=context,
            )
        return resource_ilpi_id
    if resource_ilpi_id != context.ilpi_id:
        _deny(
            code=RESOURCE_NOT_FOUND,
            http_status=status.HTTP_404_NOT_FOUND,
            message="Recurso não encontrado",
            context=context,
        )
    return resource_ilpi_id


# Public aliases keep the helper name explicit at call sites.
validate_tenant = ensure_same_tenant
require_same_tenant = ensure_same_tenant


__all__ = [
    "AUTHENTICATION_REQUIRED",
    "AUTH_CONTEXT_REQUIRED",
    "GLOBAL_SCOPE",
    "ILPI_SCOPE",
    "GLOBAL_SCOPE_REQUIRED",
    "ILPI_CONTEXT_REQUIRED",
    "PROFILE_SELECTION_REQUIRED",
    "PERMISSION_DENIED",
    "RESOURCE_NOT_FOUND",
    "PERMISSION_CATALOG_PENDING",
    "FIRST_PASSWORD_CHANGE_REQUIRED",
    "SecurityContext",
    "load_security_context",
    "build_security_context",
    "get_security_context",
    "require_global_scope",
    "require_ilpi_context",
    "require_permission",
    "block_pending_permission_catalog",
    "ensure_same_tenant",
    "validate_tenant",
    "require_same_tenant",
]
