"""PLATFORM-1A: provisionamento repetivel de ILPIs pelo operador da plataforma.

Porta separada do bootstrap, de proposito. `POST /api/instituicoes/` e as rotas de
`/api/onboarding/` continuam sendo a sequencia de NASCIMENTO da plataforma: estao
presas a `bootstrap_state`, uma linha unica e monotonica, e por isso so podem
rodar uma vez. Este modulo nao importa `bootstrap_state` em ponto algum — e essa
ausencia que torna o provisionamento repetivel.

O operador nunca recebe vinculo, perfil institucional nem contexto de tenant: o
`ilpi_id` vem sempre do path. Continua valendo o que a SAFE ja garantia — escopo
global nao obtem contexto ILPI (`_candidate_for`) e o perfil da plataforma segue
barrado de modulos clinicos (`_permission_is_allowed`).

Fora deste ciclo, ja mapeado e NAO corrigido aqui:
  GATE-1  ILPI INATIVA ainda consegue obter contexto institucional.
  GATE-2  ILPI em rascunho ainda alcanca modulos clinicos.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..infrastructure import models as m
from ..infrastructure.database import get_db
from . import schemas as s
from .audit import add_audit
from .auth import hash_password
from .fase3a import (
    ILPI_ACTIVE,
    ILPI_DRAFT,
    ILPI_INACTIVE,
    _activation_admin_exists,
    _assign_profile_to_user,
    _clone_ilpi_admin_profile,
    _http_error,
    _new_id,
    _normalise_email,
    _public_user,
    _require_global_context,
    _temporary_password,
    _trim_strings,
    _validate_activation_fields,
)
from .security import SecurityContext, require_permission

platform_router = APIRouter(prefix="/platform", tags=["platform"])


async def _load_ilpi(db: AsyncSession, ilpi_id: str) -> m.Instituicao:
    ilpi = (
        await db.execute(select(m.Instituicao).where(m.Instituicao.id == ilpi_id))
    ).scalar_one_or_none()
    if ilpi is None:
        raise _http_error(status.HTTP_404_NOT_FOUND, "RESOURCE_NOT_FOUND", "Recurso não encontrado")
    return ilpi


# `_require_global_context` basta como guarda de plataforma: `_context_is_valid`
# ja garante que um contexto de escopo global so existe para o perfil
# `platform_superuser`, com perfil e vinculo sem tenant. Repetir a checagem de
# chave aqui seria uma segunda fonte de verdade sobre quem e o operador.


@platform_router.get("/instituicoes", response_model=list[s.InstituicaoResponse])
async def listar_instituicoes_plataforma(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("ilpis:ler")),
):
    _require_global_context(context)
    result = await db.execute(
        select(m.Instituicao)
        .order_by(m.Instituicao.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()


@platform_router.post("/instituicoes", response_model=s.InstituicaoResponse, status_code=201)
async def criar_instituicao_plataforma(
    payload: s.InstituicaoCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("ilpis:criar")),
):
    """Cria uma ILPI cliente. Repetivel: nao consulta nem altera `bootstrap_state`."""
    _require_global_context(context)
    data = _trim_strings(payload.model_dump(exclude_unset=True))
    if data.get("capacidade") is None or data.get("capacidade") <= 0:
        raise _http_error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "CAPACIDADE_REQUIRED",
            "Capacidade deve ser maior que zero",
        )
    # A situacao inicial e sempre do servidor: nasce em configuracao, e so a
    # ativacao explicita a torna operacional.
    data["situacao"] = ILPI_DRAFT
    obj = m.Instituicao(**data)
    try:
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
                "situacao": obj.situacao,
                "capacidade": obj.capacidade,
                "uf": obj.uf,
                "origem": "platform",
            },
            request=request,
        )
        await db.commit()
        await db.refresh(obj)
        return obj
    except IntegrityError:
        await db.rollback()
        raise _http_error(status.HTTP_409_CONFLICT, "ILPI_DUPLICADA", "ILPI já cadastrada")


@platform_router.get("/instituicoes/{ilpi_id}", response_model=s.InstituicaoResponse)
async def obter_instituicao_plataforma(
    ilpi_id: str,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("ilpis:ler")),
):
    _require_global_context(context)
    return await _load_ilpi(db, ilpi_id)


@platform_router.put("/instituicoes/{ilpi_id}", response_model=s.InstituicaoResponse)
async def atualizar_instituicao_plataforma(
    ilpi_id: str,
    payload: s.InstituicaoUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("ilpis:atualizar")),
):
    _require_global_context(context)
    obj = await _load_ilpi(db, ilpi_id)
    before = {"razao_social": obj.razao_social, "situacao": obj.situacao, "cnpj": obj.cnpj, "uf": obj.uf}
    data = _trim_strings(payload.model_dump(exclude_unset=True))
    # `situacao` nunca vem do payload: muda apenas por ativar/inativar, que tem
    # validacao propria. Mesma regra do endpoint institucional.
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


@platform_router.post(
    "/instituicoes/{ilpi_id}/primeiro-gestor",
    response_model=s.UsuarioAdminResponse,
    status_code=201,
)
async def criar_primeiro_gestor(
    ilpi_id: str,
    payload: s.PlatformPrimeiroGestorCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("ilpis:criar")),
):
    """Semeia o primeiro `ilpi_admin` da ILPI — um TERCEIRO, nunca o operador.

    Substitui, para clientes, o `usar_usuario_atual_como_admin` do onboarding, que
    tornava o proprio operador da plataforma administrador institucional. Aqui o
    operador permanece sem vinculo: as tres linhas criadas (usuario, funcionario e
    vinculo) apontam para o gestor.

    A senha temporaria volta UMA vez no corpo. Nao e persistida em claro, nao vai
    para stdout, log nem auditoria — apenas o hash fica no banco, e o gestor e
    obrigado a troca-la no primeiro acesso.
    """
    _require_global_context(context)
    ilpi = await _load_ilpi(db, ilpi_id)

    # "Primeiro" e literal: havendo administrador institucional, a operacao de
    # provisionamento ja aconteceu e repeti-la criaria um segundo dono silencioso.
    if await _activation_admin_exists(db, ilpi.id):
        raise _http_error(
            status.HTTP_409_CONFLICT,
            "PRIMEIRO_GESTOR_JA_EXISTE",
            "Esta ILPI já possui administrador institucional",
        )

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
            ilpi_id=ilpi.id,
            # _public_user nao inclui senha nem hash.
            valores_posteriores=_public_user(user),
            request=request,
        )

        perfil = await _clone_ilpi_admin_profile(db, ilpi.id, request, context.user.id)

        # O funcionario ativo nao e formalidade: `_activation_admin_exists` exige o
        # trio usuario + perfil + funcionario para permitir a ativacao.
        funcionario = m.Funcionario(
            id=_new_id(),
            ilpi_id=ilpi.id,
            usuario_id=user.id,
            nome=payload.nome.strip(),
            cpf=payload.cpf,
            telefone=payload.telefone,
            email=user.email,
            cargo=payload.cargo or "Administrador da ILPI",
            situacao="ativo",
        )
        db.add(funcionario)
        await db.flush()
        add_audit(
            db,
            acao="funcionario.criado",
            entidade="funcionarios",
            registro_id=funcionario.id,
            usuario_id=context.user.id,
            ilpi_id=ilpi.id,
            valores_posteriores={"nome": funcionario.nome, "usuario_id": user.id, "cargo": funcionario.cargo},
            request=request,
        )

        await _assign_profile_to_user(
            db, context, user.id, perfil.id, request, ilpi_id=ilpi.id
        )

        add_audit(
            db,
            acao="ilpi.primeiro_gestor_criado",
            entidade="instituicoes",
            registro_id=ilpi.id,
            usuario_id=context.user.id,
            ilpi_id=ilpi.id,
            valores_posteriores={
                "usuario_id": user.id,
                "funcionario_id": funcionario.id,
                "perfil_id": perfil.id,
            },
            request=request,
        )
        await db.commit()
        return {**_public_user(user), "senha_temporaria": temp_password}
    except IntegrityError:
        await db.rollback()
        raise _http_error(status.HTTP_409_CONFLICT, "EMAIL_DUPLICADO", "E-mail já cadastrado")
    except Exception:
        await db.rollback()
        raise


@platform_router.post("/instituicoes/{ilpi_id}/ativar", response_model=s.InstituicaoResponse)
async def ativar_instituicao_plataforma(
    ilpi_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("ilpis:ativar")),
):
    """Ativa a ILPI sem exigir contexto institucional do operador.

    `_validate_activation_fields` e `_activation_admin_exists` sao funcao pura e
    consulta direta sobre `ilpi_id` — reaproveitadas como estao. O primeiro gestor
    nunca precisa entrar na ILPI em rascunho so para ativa-la.
    """
    _require_global_context(context)
    try:
        obj = await _load_ilpi(db, ilpi_id)
        _validate_activation_fields(obj)
        if not await _activation_admin_exists(db, obj.id):
            raise _http_error(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "ONBOARDING_PENDENTE",
                "Administrador institucional obrigatório",
            )
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
            valores_posteriores={"situacao": obj.situacao, "origem": "platform"},
            request=request,
        )
        await db.commit()
        await db.refresh(obj)
        return obj
    except Exception:
        await db.rollback()
        raise


@platform_router.post("/instituicoes/{ilpi_id}/inativar", response_model=s.InstituicaoResponse)
async def inativar_instituicao_plataforma(
    ilpi_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("ilpis:inativar")),
):
    """Marca a ILPI como inativa.

    ATENCAO (GATE-1, fora deste ciclo): inativar hoje NAO revoga vinculos, perfis
    nem funcionarios, e os usuarios seguem obtendo contexto institucional. Este
    endpoint preserva o comportamento existente de `DELETE /api/instituicoes/{id}`
    de proposito — corrigir aqui seria corrigir incidentalmente algo que tem ciclo
    proprio e impacto em fixtures de teste.
    """
    _require_global_context(context)
    obj = await _load_ilpi(db, ilpi_id)
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
        valores_posteriores={"situacao": obj.situacao, "origem": "platform"},
        request=request,
    )
    await db.commit()
    await db.refresh(obj)
    return obj
