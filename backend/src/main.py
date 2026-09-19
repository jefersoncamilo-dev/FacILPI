import hashlib
import os
import uuid
from datetime import datetime, timezone
from fastapi import FastAPI, Depends, HTTPException, Request, Response, APIRouter, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import false, select, func, update
from sqlalchemy.exc import IntegrityError, OperationalError
import pathlib

from .infrastructure.database import get_db, Base, engine, DATABASE_URL
from .infrastructure import models as m
from .application import schemas as s
from .application.auth import hash_password, verify_password, get_current_user, check_rate_limit, revoke_user_refresh_tokens
from .application.runtime import docs_urls_for, resolve_cors_origins, resolve_environment
from .application.audit import add_audit
from .application.medicacao import (
    medicamentos_router,
    prescricoes_router,
    doses_previstas_router,
    administracoes_router,
)
from .application.pais import planos_router
from .application.matriz import matriz_router
from .application.admissoes import admissoes_router
from .application.rotina import (
    execucoes_router,
    ocorrencias_router,
    plantao_router,
    programacoes_router,
)
from .application.fase3a import (
    auth_session_router,
    bootstrap_router,
    funcionarios_router,
    instituicoes_router as fase3a_instituicoes_router,
    onboarding_router,
    perfis_router,
    permissoes_router,
    usuarios_router,
    issue_session_response,
)
from .application.platform import platform_router
from .application.prontuario import prontuario_router
from .application.fase5a2d import (
    quartos_leitos_router,
    ausencias_router,
    ocupacao_historico_router,
)
from .application.security import (
    ILPI_SCOPE,
    PERMISSION_DENIED,
    RESOURCE_NOT_FOUND,
    SecurityContext,
    block_pending_permission_catalog,
    ensure_same_tenant,
    require_permission,
)

# STORAGE_PATH é a raiz de dados de runtime e contém o banco SQLite oficial.
# Arquivos enviados NUNCA vão para ela: UPLOAD_ROOT é um diretório dedicado,
# fora do alcance do banco. Antes da Issue #45 o upload gravava direto em
# STORAGE_PATH, ao lado de app.db.
STORAGE_PATH = os.getenv("STORAGE_PATH", "./storage")
pathlib.Path(STORAGE_PATH).mkdir(parents=True, exist_ok=True)

UPLOAD_ROOT = pathlib.Path(os.getenv("UPLOAD_ROOT", "./storage/uploads")).resolve()
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

# SAFE2-C1: ambiente, CORS e docs saem da mesma leitura canônica (runtime.py).
ENVIRONMENT = resolve_environment(os.environ)

# CORS. Em development/test o wildcard continua virando as origens locais; em
# pilot/production ausência ou '*' é erro de configuração, não fallback — cair
# em localhost lá dentro bloquearia o frontend real sem dizer por quê.
allow_origins = resolve_cors_origins(os.environ, ENVIRONMENT)

# Docs desligadas em pilot/production: não vazam dado, mas entregam o mapa das
# rotas de auth, reset de senha e bootstrap. Só as ROTAS somem — `app.openapi()`
# continua funcionando.
app = FastAPI(title="FáciLPI API", version="1.0.0", **docs_urls_for(ENVIRONMENT))

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===== Health (no auth) =====
health_router = APIRouter()

@health_router.get("/health")
async def health():
    return {"status": "ok", "service": "FáciLPI", "database": "connected"}

# ===== Auth routes (rate-limited, no auth for register/token) =====
auth_router = APIRouter(prefix="/auth", tags=["auth"])

@auth_router.post("/register", status_code=410)
async def register(request: Request):
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(f"register:{client_ip}")
    raise HTTPException(
        status_code=410,
        detail={
            "code": "PUBLIC_REGISTER_DISABLED",
            "message": "Cadastro público desativado",
        },
    )

@auth_router.post("/token", response_model=s.TokenResponse)
async def token(payload: s.UserLogin, request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(f"token:{client_ip}")
    result = await db.execute(select(m.User).where(m.User.email == payload.email.lower().strip()))
    user = result.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Credenciais inválidas")
    if not user.ativo:
        raise HTTPException(status_code=401, detail="Usuário inativo")
    session_payload = await issue_session_response(
        db,
        user,
        response,
        request,
        scope=payload.scope,
        ilpi_id=payload.ilpi_id,
        perfil_id=payload.perfil_id,
    )
    await db.commit()
    return session_payload

@auth_router.put("/password")
async def update_password(payload: s.PasswordUpdate, request: Request, db: AsyncSession = Depends(get_db), current_user: m.User = Depends(get_current_user)):
    # rate limit authenticated by user id
    check_rate_limit(f"password:{current_user.id}")
    # SAFE2-B/H01: prova de posse antes de qualquer escrita. Sem isto, um access
    # token roubado trocava a senha do dono — e a troca ainda revoga os refresh
    # tokens dele, de modo que o invasor fixava a credencial e expulsava a vítima
    # no mesmo movimento. Vale também no primeiro acesso: a senha temporária é a
    # senha atual. Abrir excecao para `exige_troca_senha` recriaria a janela.
    if not verify_password(payload.senha_atual, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Senha atual incorreta")
    if payload.nova_senha != payload.confirmar_senha:
        raise HTTPException(status_code=400, detail="Senhas não conferem")
    if payload.nova_senha == payload.senha_atual:
        # Trocar a senha temporária por ela mesma zerava exige_troca_senha e
        # encerrava o primeiro acesso sem que senha alguma mudasse.
        raise HTTPException(status_code=400, detail="A nova senha deve ser diferente da senha atual")
    current_user.password_hash = hash_password(payload.nova_senha)
    current_user.exige_troca_senha = False
    await revoke_user_refresh_tokens(db, current_user.id)
    add_audit(
        db,
        acao="auth.senha_alterada",
        entidade="users",
        registro_id=current_user.id,
        usuario_id=current_user.id,
        valores_posteriores={"exige_troca_senha": False},
        request=request,
    )
    await db.commit()
    return {"mensagem": "Senha alterada com sucesso"}

# ===== Protected CRUD helpers =====
def make_crud_router(
    model,
    create_schema,
    update_schema,
    response_schema,
    prefix: str,
    tags: list,
    *,
    permissions: dict[str, str] | None = None,
    fail_closed: bool = False,
    tenant_resource: str | None = None,
    tenant_column: str | None = None,
    parent_check: dict | None = None,
    parent_filter_param: str | None = None,
):
    # D1: filtro por pai na listagem, opt-in por roteador. Declarar o parametro
    # numa assinatura unica o faria aparecer no OpenAPI de TODOS os roteadores da
    # factory e transformaria um query param hoje ignorado em erro nos que nao o
    # suportam — quebra silenciosa fora do escopo. Por isso o handler tem duas
    # definicoes condicionais e so quem declara o flag expoe o parametro.
    if parent_filter_param is not None:
        if parent_check is None or parent_filter_param != parent_check.get("id_field"):
            raise RuntimeError("parent_filter_param exige parent_check com o mesmo id_field")
        if parent_filter_param != "residente_id":
            # FastAPI deriva o nome do query param do nome do argumento Python,
            # que precisa ser literal. Hoje so `residente_id` e suportado; outro
            # valor falha aqui, no import, e nao em silencio na rota.
            raise RuntimeError(f"parent_filter_param nao suportado: {parent_filter_param}")

    router = APIRouter(prefix=prefix, tags=tags)

    def guard(action: str):
        if fail_closed:
            return block_pending_permission_catalog
        if permissions is not None:
            permission_key = permissions.get(action)
            if not permission_key:
                # Ação sem permissão aprovada (ex.: DELETE físico aguardando
                # inativação lógica na F5B): continua fail-closed.
                return block_pending_permission_catalog
            return require_permission(permission_key)
        return get_current_user

    def scoped_query(query, context):
        if (
            tenant_resource == "instituicao"
            and isinstance(context, SecurityContext)
            and context.scope == ILPI_SCOPE
        ):
            return query.where(model.id == context.ilpi_id)
        if tenant_column is not None:
            if (
                isinstance(context, SecurityContext)
                and context.scope == ILPI_SCOPE
                and context.ilpi_id is not None
            ):
                return query.where(getattr(model, tenant_column) == context.ilpi_id)
            # Fail-closed: sem contexto ILPI válido, nada é listado.
            return query.where(false())
        return query

    def ensure_resource_scope(context, item_id: str) -> None:
        if tenant_resource == "instituicao" and isinstance(context, SecurityContext):
            ensure_same_tenant(context, item_id)

    def ensure_clinical_tenant(context, obj) -> None:
        # Recurso clínico precisa pertencer à ILPI da sessão; divergência
        # retorna 404 sem revelar existência (via ensure_same_tenant).
        if tenant_column is None or not isinstance(context, SecurityContext):
            return
        ensure_same_tenant(context, getattr(obj, tenant_column, None))

    def resolve_session_tenant(context) -> str:
        # Única fonte válida de tenant: SecurityContext.ilpi_id. Valores de
        # body/query/path/header nunca decidem o tenant efetivo.
        if (
            isinstance(context, SecurityContext)
            and context.scope == ILPI_SCOPE
            and context.ilpi_id is not None
        ):
            return context.ilpi_id
        raise HTTPException(
            status_code=403,
            detail={"code": PERMISSION_DENIED, "message": "Permissão não autorizada"},
        )

    async def ensure_parent_same_tenant(db, data, session_tenant: str | None, context) -> None:
        # Validação genérica de vínculo pai: o registro pai precisa pertencer
        # à mesma ILPI da sessão. Divergência (inclusive cross-tenant) retorna
        # 404 sem revelar existência. `parent_check` é explicitamente
        # configurado por roteador: {"model", "id_field", "tenant_column"}.
        parent_model = parent_check["model"]
        id_field = parent_check["id_field"]
        parent_tenant_column = parent_check["tenant_column"]
        tenant = session_tenant if session_tenant is not None else resolve_session_tenant(context)
        parent_id = data.get(id_field)
        if not parent_id:
            raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})
        parent = (
            await db.execute(
                select(parent_model).where(
                    parent_model.id == parent_id,
                    getattr(parent_model, parent_tenant_column) == tenant,
                )
            )
        ).scalar_one_or_none()
        if parent is None:
            raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})

    async def listar(db, context, skip: int, limit: int, parent_id: str | None):
        query = scoped_query(select(model), context)
        if parent_id is not None:
            # Mesma convencao de list_sinais_vitais (main.py:1130) e
            # list_intercorrencias (main.py:1218): o pai e validado no tenant da
            # sessao ANTES de filtrar. Inexistente e cross-tenant compartilham o
            # mesmo 404, sem revelar existencia.
            await ensure_parent_same_tenant(db, {parent_check["id_field"]: parent_id}, None, context)
            query = query.where(getattr(model, parent_check["id_field"]) == parent_id)
        order = model.created_at.desc() if hasattr(model, "created_at") else model.id
        result = await db.execute(query.order_by(order).offset(skip).limit(limit))
        items = result.scalars().all()
        return items

    if parent_filter_param is not None:
        @router.get("/", response_model=list[response_schema])
        async def list_items(residente_id: str | None = None, skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db), context = Depends(guard("list"))):
            return await listar(db, context, skip, limit, residente_id)
    else:
        @router.get("/", response_model=list[response_schema])
        async def list_items(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db), context = Depends(guard("list"))):
            return await listar(db, context, skip, limit, None)

    @router.post("/", response_model=response_schema, status_code=201)
    async def create_item(payload: create_schema, db: AsyncSession = Depends(get_db), context = Depends(guard("create"))):
        data = payload.model_dump(exclude_unset=True)
        session_tenant: str | None = None
        if tenant_column is not None:
            # O cliente nunca escolhe o tenant: sobrescreve qualquer valor
            # recebido (ex.: ResidenteCreate.instituicao_id) pelo da sessão.
            session_tenant = resolve_session_tenant(context)
            data[tenant_column] = session_tenant
        if parent_check is not None:
            # O vínculo pai é validado na ILPI da sessão ANTES do INSERT
            # (fail-closed; também evita violação da FK composta no PG).
            await ensure_parent_same_tenant(db, data, session_tenant, context)
        if model == m.Instituicao and data.get("cnpj"):
            existing = await db.execute(select(m.Instituicao).where(m.Instituicao.cnpj == data["cnpj"]))
            if existing.scalar_one_or_none():
                raise HTTPException(status_code=409, detail="CNPJ já cadastrado")
        if model == m.Residente and data.get("cpf") and data.get("instituicao_id"):
            existing = await db.execute(select(m.Residente).where(m.Residente.cpf == data["cpf"], m.Residente.instituicao_id == data["instituicao_id"]))
            if existing.scalar_one_or_none():
                raise HTTPException(status_code=409, detail="CPF já cadastrado nesta instituição")
        # trim strings
        for k, v in list(data.items()):
            if isinstance(v, str):
                data[k] = v.strip()
        obj = model(**data)
        db.add(obj)
        await db.commit()
        await db.refresh(obj)
        return obj

    @router.get("/{item_id}", response_model=response_schema)
    async def get_item(item_id: str, db: AsyncSession = Depends(get_db), context = Depends(guard("get"))):
        ensure_resource_scope(context, item_id)
        result = await db.execute(select(model).where(model.id == item_id))
        obj = result.scalar_one_or_none()
        if not obj:
            raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})
        ensure_clinical_tenant(context, obj)
        return obj

    @router.put("/{item_id}", response_model=response_schema)
    async def update_item(item_id: str, payload: update_schema, db: AsyncSession = Depends(get_db), context = Depends(guard("update"))):
        ensure_resource_scope(context, item_id)
        data = payload.model_dump(exclude_unset=True)
        query = select(model).where(model.id == item_id)
        situacao_e_documento = model is m.Documento and "situacao" in data
        if situacao_e_documento:
            # Issue #25: lock de linha quando suportado (PostgreSQL) para
            # serializar com POST /documentos/{id}/validar. No SQLite o
            # dialeto ignora FOR UPDATE (compilação verificada: mesmo SQL
            # com ou sem a cláusula) — a corretude nesse caso vem do UPDATE
            # condicional abaixo, não do lock.
            query = query.with_for_update()
        result = await db.execute(query)
        obj = result.scalar_one_or_none()
        if not obj:
            raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})
        ensure_clinical_tenant(context, obj)
        if situacao_e_documento:
            # Decide o bloqueio com o MESMO valor normalizado que seria
            # persistido (o .strip() abaixo), não o valor cru do payload —
            # caso contrário " validado "/"validado\t" escapam do guard.
            situacao_normalizada = data["situacao"].strip() if isinstance(data["situacao"], str) else data["situacao"]
            if situacao_normalizada == "validado" or obj.situacao == "validado":
                raise HTTPException(
                    status_code=422,
                    detail={
                        "code": DOCUMENTO_TRANSICAO_PROTEGIDA,
                        "message": "Transição de situação protegida; use POST /documentos/{id}/validar.",
                    },
                )
        if tenant_column is not None:
            # Troca de tenant via update é proibida: ignora o tenant do cliente.
            data.pop("instituicao_id", None)
            data.pop("ilpi_id", None)
        if parent_check is not None:
            # Vínculo pai é imutável via PUT genérico: ignora o valor do
            # cliente. Troca de vínculo exige fluxo próprio, auditável.
            data.pop(parent_check["id_field"], None)
        update_values = {}
        for k, v in data.items():
            if isinstance(v, str):
                v = v.strip()
                if v == "":
                    continue
            update_values[k] = v
        if situacao_e_documento:
            if update_values:
                # Persistência atômica: se uma validação concorrente
                # concluiu entre a leitura acima e este UPDATE, a condição
                # não bate e a transição é recusada em vez de sobrescrever.
                exec_result = await db.execute(
                    update(model)
                    .where(model.id == item_id, model.situacao != "validado")
                    .values(**update_values)
                )
                if exec_result.rowcount != 1:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "code": DOCUMENTO_TRANSICAO_PROTEGIDA,
                            "message": "Transição de situação protegida; use POST /documentos/{id}/validar.",
                        },
                    )
        else:
            for k, v in update_values.items():
                setattr(obj, k, v)
        await db.commit()
        await db.refresh(obj)
        return obj

    @router.delete("/{item_id}", status_code=204)
    async def delete_item(item_id: str, db: AsyncSession = Depends(get_db), context = Depends(guard("delete"))):
        ensure_resource_scope(context, item_id)
        result = await db.execute(select(model).where(model.id == item_id))
        obj = result.scalar_one_or_none()
        if not obj:
            raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})
        ensure_clinical_tenant(context, obj)
        await db.delete(obj)
        await db.commit()
        return None

    return router

# Create routers for each entity
instituicoes_router = fase3a_instituicoes_router
# F5A-2A: Residentes protegido por RBAC + tenant (coluna instituicao_id).
# DELETE permanece fail-closed (físico; inativação lógica é F5B) via "delete": None.
residentes_router = make_crud_router(
    m.Residente,
    s.ResidenteCreate,
    s.ResidenteUpdate,
    s.ResidenteResponse,
    "/residentes",
    ["residentes"],
    permissions={
        "list": "residentes:ler",
        "get": "residentes:ler",
        "create": "residentes:criar",
        "update": "residentes:atualizar",
        "delete": None,
    },
    tenant_column="instituicao_id",
)
# F5A-2B: Familiares protegido por RBAC + tenant (coluna ilpi_id própria) +
# vínculo seguro com Residente (validado no POST; imutável no PUT).
# DELETE permanece fail-closed (físico; inativação lógica é F5B) via "delete": None.
# familiares:inativar existe no catálogo mas NÃO autoriza DELETE físico.
familiares_router = make_crud_router(
    m.Familiar,
    s.FamiliarCreate,
    s.FamiliarUpdate,
    s.FamiliarResponse,
    "/familiares",
    ["familiares"],
    permissions={
        "list": "familiares:ler",
        "get": "familiares:ler",
        "create": "familiares:criar",
        "update": "familiares:atualizar",
        "delete": None,
    },
    tenant_column="ilpi_id",
    parent_check={
        "model": m.Residente,
        "id_field": "residente_id",
        "tenant_column": "instituicao_id",
    },
)
# F5A-2C: Documentos do Residente protegido por RBAC + tenant (coluna
# instituicao_id) + vínculo seguro com Residente (validado no POST;
# residente_id imutável no PUT). DELETE permanece fail-closed (físico;
# documentos:inativar NÃO autoriza DELETE físico).
DOCUMENTO_TRANSICAO_PROTEGIDA = "DOCUMENTO_TRANSICAO_PROTEGIDA"
DOCUMENTO_JA_VALIDADO = "DOCUMENTO_JA_VALIDADO"
documentos_router = make_crud_router(
    m.Documento,
    s.DocumentoCreate,
    s.DocumentoUpdate,
    s.DocumentoResponse,
    "/documentos",
    ["documentos"],
    permissions={
        "list": "documentos:ler",
        "get": "documentos:ler",
        "create": "documentos:criar",
        "update": "documentos:atualizar",
        "delete": None,
    },
    tenant_column="instituicao_id",
    parent_check={
        "model": m.Residente,
        "id_field": "residente_id",
        "tenant_column": "instituicao_id",
    },
    # D1: unico roteador da factory que expoe ?residente_id=. Sem o parametro a
    # resposta e identica a anterior.
    parent_filter_param="residente_id",
)


# Issue #25: ato dedicado de validação documental. Fecha o bypass do PUT
# genérico (situacao="validado" sem autoria/timestamp/auditoria próprios).
# Permissão exclusiva "documentos:validar" (ILPI-only); tenant da sessão;
# autoria e timestamp do backend, nunca do payload; sem invalidar/revalidar.
@documentos_router.post("/{item_id}/validar", response_model=s.DocumentoResponse)
async def validar_documento(
    item_id: str,
    payload: s.DocumentoValidar,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("documentos:validar")),
):
    result = await db.execute(
        select(m.Documento)
        .where(
            m.Documento.id == item_id,
            m.Documento.instituicao_id == context.ilpi_id,
        )
        .with_for_update()
    )
    obj = result.scalar_one_or_none()
    if not obj:
        # Inexistente e cross-tenant preservam o mesmo contrato 404.
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})
    if obj.situacao == "validado":
        raise HTTPException(status_code=409, detail={"code": DOCUMENTO_JA_VALIDADO, "message": "Documento já validado"})
    before = {"situacao": obj.situacao, "validado_por": obj.validado_por, "validado_em": None}
    now = datetime.now(timezone.utc)
    # Escrita atômica e condicional: se outra requisição validou entre a
    # leitura acima e este UPDATE, a condição não bate (rowcount == 0) e
    # devolvemos 409 em vez de sobrescrever/duplicar auditoria.
    exec_result = await db.execute(
        update(m.Documento)
        .where(
            m.Documento.id == item_id,
            m.Documento.instituicao_id == context.ilpi_id,
            m.Documento.situacao != "validado",
        )
        .values(situacao="validado", validado_por=context.user.id, validado_em=now)
    )
    if exec_result.rowcount != 1:
        raise HTTPException(status_code=409, detail={"code": DOCUMENTO_JA_VALIDADO, "message": "Documento já validado"})
    add_audit(
        db,
        acao="documentos.validar",
        entidade="documentos",
        registro_id=obj.id,
        usuario_id=context.user.id,
        ilpi_id=context.ilpi_id,
        valores_anteriores=before,
        valores_posteriores={"situacao": "validado", "validado_por": context.user.id, "validado_em": now.isoformat()},
        request=request,
    )
    await db.commit()
    await db.refresh(obj)
    return obj


# ===== A3 (Issue #45): anexo de arquivo em Documento =====
# Substitui POST /uploads/{entity_id}, que gravava em STORAGE_PATH (mesmo
# diretório do banco) usando entity_id e file.filename crus — dois vetores de
# path traversal. Aqui nenhum componente de caminho vem do cliente.

DOCUMENTO_ARQUIVO_JA_ANEXADO = "DOCUMENTO_ARQUIVO_JA_ANEXADO"
DOCUMENTO_ARQUIVO_AUSENTE = "DOCUMENTO_ARQUIVO_AUSENTE"
ARQUIVO_TIPO_NAO_PERMITIDO = "ARQUIVO_TIPO_NAO_PERMITIDO"
ARQUIVO_MUITO_GRANDE = "ARQUIVO_MUITO_GRANDE"
ARQUIVO_VAZIO = "ARQUIVO_VAZIO"

ARQUIVO_MAX_BYTES = 10 * 1024 * 1024
ARQUIVO_CHUNK_BYTES = 1024 * 1024

# Allowlist restrita ao que uma ILPI de fato anexa a um documento. O MIME é
# decidido pela assinatura do conteúdo; extensão e content_type do multipart
# são descartados. Formatos sem assinatura verificável (texto puro) ficam de
# fora justamente por não permitirem inspeção real.
ARQUIVO_ASSINATURAS = (
    ("application/pdf", ".pdf", (b"%PDF-",)),
    ("image/jpeg", ".jpg", (b"\xff\xd8\xff",)),
    ("image/png", ".png", (b"\x89PNG\r\n\x1a\n",)),
)
ARQUIVO_MAGIC_BYTES = max(len(magic) for _, _, magics in ARQUIVO_ASSINATURAS for magic in magics)


def _detectar_tipo(cabeca: bytes) -> tuple[str, str]:
    for mime, extensao, magics in ARQUIVO_ASSINATURAS:
        if any(cabeca.startswith(magic) for magic in magics):
            return mime, extensao
    raise HTTPException(
        status_code=422,
        detail={"code": ARQUIVO_TIPO_NAO_PERMITIDO, "message": "Tipo de arquivo não permitido. Aceitos: PDF, JPEG, PNG."},
    )


def _nome_para_exibicao(nome: str | None) -> str:
    """Nome original reduzido a rótulo seguro: nunca vira componente de caminho."""
    bruto = (nome or "").strip()
    # Corta qualquer prefixo de diretório em ambos os separadores e remove
    # caracteres de controle, que envenenariam o Content-Disposition.
    bruto = bruto.replace("\\", "/").split("/")[-1]
    limpo = "".join(c for c in bruto if c.isprintable() and c not in '"\r\n')
    limpo = limpo.strip(" .")
    return limpo[:255] or "documento"


def _caminho_do_anexo(chave: str) -> pathlib.Path:
    """Resolve a chave relativa e exige containment em UPLOAD_ROOT."""
    destino = (UPLOAD_ROOT / chave).resolve()
    if destino != UPLOAD_ROOT and UPLOAD_ROOT not in destino.parents:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})
    return destino


async def _receber_para_temporario(upload: UploadFile, temporario: pathlib.Path) -> tuple[int, str, bytes]:
    """Grava em chunks: limite e hash são apurados durante o streaming."""
    hasher = hashlib.sha256()
    tamanho = 0
    cabeca = b""
    with temporario.open("wb") as destino:
        while True:
            chunk = await upload.read(ARQUIVO_CHUNK_BYTES)
            if not chunk:
                break
            tamanho += len(chunk)
            if tamanho > ARQUIVO_MAX_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail={"code": ARQUIVO_MUITO_GRANDE, "message": "Arquivo excede o limite de 10 MB."},
                )
            if len(cabeca) < ARQUIVO_MAGIC_BYTES:
                cabeca += chunk[: ARQUIVO_MAGIC_BYTES - len(cabeca)]
            hasher.update(chunk)
            destino.write(chunk)
        destino.flush()
        os.fsync(destino.fileno())
    return tamanho, hasher.hexdigest(), cabeca


def _descartar(caminho: pathlib.Path) -> None:
    """Cleanup best-effort: nunca deixa a falha original ser mascarada."""
    try:
        caminho.unlink(missing_ok=True)
    except OSError:
        pass


@documentos_router.post("/{item_id}/arquivo", response_model=s.DocumentoResponse, status_code=201)
async def anexar_arquivo_documento(
    item_id: str,
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("documentos:anexar")),
):
    # O documento é localizado dentro do tenant da sessão: inexistente e
    # cross-tenant compartilham o mesmo 404.
    obj = (await db.execute(
        select(m.Documento).where(
            m.Documento.id == item_id,
            m.Documento.instituicao_id == context.ilpi_id,
        )
    )).scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})
    if obj.arquivo:
        raise HTTPException(
            status_code=409,
            detail={"code": DOCUMENTO_ARQUIVO_JA_ANEXADO, "message": "Documento já possui arquivo anexado"},
        )
    if obj.situacao == "validado":
        raise HTTPException(
            status_code=409,
            detail={"code": DOCUMENTO_JA_VALIDADO, "message": "Documento já validado não recebe novo arquivo"},
        )

    temporario = UPLOAD_ROOT / f".tmp-{uuid.uuid4().hex}"
    chave: str | None = None
    destino: pathlib.Path | None = None
    promovido = False
    commit_tentado = False
    try:
        tamanho, digest, cabeca = await _receber_para_temporario(file, temporario)
        if tamanho == 0:
            raise HTTPException(status_code=422, detail={"code": ARQUIVO_VAZIO, "message": "Arquivo vazio"})
        mime, extensao = _detectar_tipo(cabeca)

        # Todos os componentes do caminho são do backend: tenant da sessão,
        # id do recurso já validado e um uuid gerado aqui.
        chave = f"{context.ilpi_id}/{obj.id}/{uuid.uuid4().hex}{extensao}"
        destino = _caminho_do_anexo(chave)
        destino.parent.mkdir(parents=True, exist_ok=True)

        agora = datetime.now(timezone.utc)
        nome_original = _nome_para_exibicao(file.filename)
        # UPDATE condicional: se outra requisição anexou entre a leitura acima
        # e aqui, rowcount == 0 e devolvemos 409 sem sobrescrever nada.
        resultado = await db.execute(
            update(m.Documento)
            .where(
                m.Documento.id == item_id,
                m.Documento.instituicao_id == context.ilpi_id,
                m.Documento.arquivo.is_(None),
                m.Documento.situacao != "validado",
            )
            .values(
                arquivo=chave,
                arquivo_nome_original=nome_original,
                arquivo_mime=mime,
                arquivo_tamanho=tamanho,
                arquivo_hash=digest,
                anexado_por=context.user.id,
                anexado_em=agora,
            )
        )
        if resultado.rowcount != 1:
            raise HTTPException(
                status_code=409,
                detail={"code": DOCUMENTO_ARQUIVO_JA_ANEXADO, "message": "Documento já possui arquivo anexado"},
            )

        add_audit(
            db,
            acao="documentos.anexar",
            entidade="documentos",
            registro_id=obj.id,
            usuario_id=context.user.id,
            ilpi_id=context.ilpi_id,
            valores_anteriores={"arquivo_presente": False},
            # Auditoria guarda metadados, nunca conteúdo nem caminho absoluto.
            valores_posteriores={
                "arquivo_presente": True,
                "arquivo_nome_original": nome_original,
                "arquivo_mime": mime,
                "arquivo_tamanho": tamanho,
                "arquivo_hash": digest,
                "anexado_em": agora.isoformat(),
            },
            request=request,
        )

        # Promoção atômica antes do commit. A ordem inversa deixaria registro
        # apontando para arquivo inexistente.
        os.replace(temporario, destino)
        promovido = True
        # A partir daqui o resultado do commit é AMBÍGUO: uma exceção não prova
        # que o servidor deixou de efetivar a transação (ack perdido, conexão
        # cortada durante o COMMIT). Marcar antes de chamar, nunca depois.
        commit_tentado = True
        await db.commit()
    except BaseException:
        # Best-effort: sobre um commit ambíguo, rollback não decide nada.
        await db.rollback()
        # Arquivo órfão recuperável é preferível a registro commitado apontando
        # para arquivo apagado. Só removemos o arquivo já promovido quando há
        # prova de que o commit sequer chegou a ser tentado.
        if promovido and not commit_tentado and destino is not None:
            _descartar(destino)
        _descartar(temporario)
        raise
    finally:
        await file.close()

    await db.refresh(obj)
    return obj


@documentos_router.get("/{item_id}/arquivo")
async def baixar_arquivo_documento(
    item_id: str,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("documentos:ler")),
):
    obj = (await db.execute(
        select(m.Documento).where(
            m.Documento.id == item_id,
            m.Documento.instituicao_id == context.ilpi_id,
        )
    )).scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})
    if not obj.arquivo:
        raise HTTPException(
            status_code=404,
            detail={"code": DOCUMENTO_ARQUIVO_AUSENTE, "message": "Documento não possui arquivo anexado"},
        )
    caminho = _caminho_do_anexo(obj.arquivo)
    if not caminho.is_file():
        # Registro sem arquivo em disco é inconsistência de infraestrutura; a
        # resposta não revela caminho nem distingue do caso "sem anexo".
        raise HTTPException(
            status_code=404,
            detail={"code": DOCUMENTO_ARQUIVO_AUSENTE, "message": "Documento não possui arquivo anexado"},
        )
    return FileResponse(
        caminho,
        # MIME é o detectado e persistido pelo backend, nunca o declarado.
        media_type=obj.arquivo_mime or "application/octet-stream",
        filename=_nome_para_exibicao(obj.arquivo_nome_original),
    )


tarefas_router = make_crud_router(m.Tarefa, s.TarefaCreate, s.TarefaUpdate, s.TarefaResponse, "/tarefas", ["tarefas"], fail_closed=True)
# ===== Avaliacoes Router (F5A-3A1) =====

avaliacoes_router = APIRouter(prefix="/avaliacoes", tags=["avaliacoes"])


async def _resolve_profissional(db: AsyncSession, context: SecurityContext) -> str:
    func = (
        await db.execute(
            select(m.Funcionario).where(
                m.Funcionario.usuario_id == context.user.id,
                m.Funcionario.ilpi_id == context.ilpi_id,
                m.Funcionario.situacao == "ativo",
            )
        )
    ).scalar_one_or_none()
    if func is not None and func.nome:
        return func.nome
    return context.user.nome


async def _ensure_avaliacao_parent(db: AsyncSession, data: dict, context: SecurityContext) -> None:
    residente_id = data.get("residente_id")
    if not residente_id:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})
    tenant = context.ilpi_id
    parent = (
        await db.execute(
            select(m.Residente).where(
                m.Residente.id == residente_id,
                m.Residente.instituicao_id == tenant,
            )
        )
    ).scalar_one_or_none()
    if parent is None:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})


@avaliacoes_router.get("/", response_model=list[s.AvaliacaoResponse])
async def list_avaliacoes(
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("avaliacoes:ler")),
):
    query = (
        select(m.Avaliacao)
        .where(m.Avaliacao.ilpi_id == context.ilpi_id)
        .order_by(m.Avaliacao.data.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(query)
    return result.scalars().all()


@avaliacoes_router.post("/", response_model=s.AvaliacaoResponse, status_code=201)
async def create_avaliacao(
    payload: s.AvaliacaoCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("avaliacoes:criar")),
):
    data = payload.model_dump(exclude_unset=True)
    session_tenant = context.ilpi_id
    data["ilpi_id"] = session_tenant
    data["profissional"] = await _resolve_profissional(db, context)
    await _ensure_avaliacao_parent(db, data, context)
    if data.get("data") is None:
        data["data"] = datetime.now(timezone.utc)
    for k, v in list(data.items()):
        if isinstance(v, str):
            data[k] = v.strip()
    obj = m.Avaliacao(**data)
    db.add(obj)
    add_audit(
        db,
        acao="avaliacoes.criar",
        entidade="avaliacoes",
        registro_id=obj.id,
        usuario_id=context.user.id,
        ilpi_id=context.ilpi_id,
        valores_posteriores={"residente_id": data.get("residente_id"), "tipo": data.get("tipo")},
        request=request,
    )
    await db.commit()
    await db.refresh(obj)
    return obj


@avaliacoes_router.get("/{avaliacao_id}", response_model=s.AvaliacaoResponse)
async def get_avaliacao(
    avaliacao_id: str,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("avaliacoes:ler")),
):
    result = await db.execute(
        select(m.Avaliacao).where(
            m.Avaliacao.id == avaliacao_id,
            m.Avaliacao.ilpi_id == context.ilpi_id,
        )
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})
    return obj


@avaliacoes_router.put("/{avaliacao_id}", response_model=s.AvaliacaoResponse)
async def update_avaliacao(
    avaliacao_id: str,
    payload: s.AvaliacaoUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("avaliacoes:atualizar")),
):
    result = await db.execute(
        select(m.Avaliacao).where(
            m.Avaliacao.id == avaliacao_id,
            m.Avaliacao.ilpi_id == context.ilpi_id,
        )
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})
    data = payload.model_dump(exclude_unset=True)
    data.pop("residente_id", None)
    data.pop("ilpi_id", None)
    data.pop("profissional", None)
    for k, v in data.items():
        if isinstance(v, str):
            v = v.strip()
            if v == "":
                continue
        setattr(obj, k, v)
    add_audit(
        db,
        acao="avaliacoes.atualizar",
        entidade="avaliacoes",
        registro_id=obj.id,
        usuario_id=context.user.id,
        ilpi_id=context.ilpi_id,
        valores_posteriores=data,
        request=request,
    )
    await db.commit()
    await db.refresh(obj)
    return obj


# ===== Graus de Dependencia (F5A-3A2: fonte única oficial) =====
# Residente.grau_dependencia é legado congelado: nunca lido aqui, nunca
# escrito aqui, sem sincronização, sem trigger. Avaliação SUGERE (via
# leitura); somente a confirmação humana explícita persiste o grau.

graus_router = APIRouter(prefix="/graus-dependencia", tags=["graus-dependencia"])

GRAU_ATIVO_CONFLITO = "GRAU_ATIVO_CONFLITO"
GRAU_NAO_ATIVO = "GRAU_NAO_ATIVO"


async def _ensure_grau_parent(db: AsyncSession, residente_id: str, context: SecurityContext):
    parent = (
        await db.execute(
            select(m.Residente).where(
                m.Residente.id == residente_id,
                m.Residente.instituicao_id == context.ilpi_id,
            )
        )
    ).scalar_one_or_none()
    if parent is None:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})
    return parent


@graus_router.get("/", response_model=list[s.GrauDependenciaResponse])
async def list_graus(
    residente_id: str | None = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("grau_dependencia:ler")),
):
    query = select(m.GrauDependencia).where(m.GrauDependencia.ilpi_id == context.ilpi_id)
    if residente_id is not None:
        await _ensure_grau_parent(db, residente_id, context)
        query = query.where(m.GrauDependencia.residente_id == residente_id)
    query = query.order_by(m.GrauDependencia.confirmado_em.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@graus_router.get("/ativo", response_model=s.GrauDependenciaResponse)
async def get_grau_ativo(
    residente_id: str,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("grau_dependencia:ler")),
):
    await _ensure_grau_parent(db, residente_id, context)
    result = await db.execute(
        select(m.GrauDependencia).where(
            m.GrauDependencia.ilpi_id == context.ilpi_id,
            m.GrauDependencia.residente_id == residente_id,
            m.GrauDependencia.situacao == "ativo",
        )
    )
    obj = result.scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})
    return obj


@graus_router.post("/", response_model=s.GrauDependenciaResponse, status_code=201)
async def confirm_grau(
    payload: s.GrauDependenciaCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("grau_dependencia:criar")),
):
    data = payload.model_dump()
    # Tenant e autoria vêm exclusivamente da sessão; o payload nunca decide.
    data.pop("ilpi_id", None)
    data.pop("instituicao_id", None)
    data.pop("confirmado_por", None)
    data.pop("profissional", None)
    data.pop("usuario_id", None)
    await _ensure_grau_parent(db, data["residente_id"], context)
    sugestao = None
    if data["origem"] == "avaliacao":
        avaliacao = (
            await db.execute(
                select(m.Avaliacao).where(
                    m.Avaliacao.id == data["avaliacao_id"],
                    m.Avaliacao.ilpi_id == context.ilpi_id,
                    m.Avaliacao.residente_id == data["residente_id"],
                )
            )
        ).scalar_one_or_none()
        if avaliacao is None:
            raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})
        sugestao = avaliacao.classificacao
    obj = m.GrauDependencia(
        ilpi_id=context.ilpi_id,
        residente_id=data["residente_id"],
        classificacao=data["classificacao"],
        sugestao_classificacao=sugestao,
        origem=data["origem"],
        avaliacao_id=data.get("avaliacao_id"),
        validade=data.get("validade"),
        justificativa=data["justificativa"].strip(),
        confirmado_por=context.user.id,
        situacao="ativo",
    )
    try:
        # Localiza o ativo anterior ANTES do INSERT: o SELECT dispara
        # autoflush e veria a própria linha nova como "anterior".
        previous = (
            await db.execute(
                select(m.GrauDependencia).where(
                    m.GrauDependencia.ilpi_id == context.ilpi_id,
                    m.GrauDependencia.residente_id == data["residente_id"],
                    m.GrauDependencia.situacao == "ativo",
                )
            )
        ).scalar_one_or_none()
        if previous is not None:
            previous.situacao = "substituido"
            await db.flush()  # flip primeiro: nunca dois ativos, ordem estável
        db.add(obj)
        await db.flush()
        if previous is not None:
            previous.superseded_by = obj.id
        add_audit(
            db,
            acao="graus_dependencia.criar",
            entidade="graus_dependencia",
            registro_id=obj.id,
            usuario_id=context.user.id,
            ilpi_id=context.ilpi_id,
            valores_anteriores={"substituido_id": previous.id} if previous is not None else None,
            valores_posteriores={
                "residente_id": obj.residente_id,
                "classificacao": obj.classificacao,
                "origem": obj.origem,
                "avaliacao_id": obj.avaliacao_id,
            },
            request=request,
        )
        await db.commit()
    except (IntegrityError, OperationalError):
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail={"code": GRAU_ATIVO_CONFLITO, "message": "Conflito de confirmação: já existe grau ativo"},
        )
    await db.refresh(obj)
    return obj


@graus_router.post("/{grau_id}/revogar", response_model=s.GrauDependenciaResponse)
async def revoke_grau(
    grau_id: str,
    payload: s.GrauDependenciaRevogar,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("grau_dependencia:criar")),
):
    result = await db.execute(
        select(m.GrauDependencia).where(
            m.GrauDependencia.id == grau_id,
            m.GrauDependencia.ilpi_id == context.ilpi_id,
        )
    )
    obj = result.scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})
    if obj.situacao != "ativo":
        raise HTTPException(
            status_code=409,
            detail={"code": GRAU_NAO_ATIVO, "message": "Somente grau ativo pode ser revogado"},
        )
    obj.situacao = "revogado"
    obj.motivo_revogacao = payload.motivo.strip()
    add_audit(
        db,
        acao="graus_dependencia.revogar",
        entidade="graus_dependencia",
        registro_id=obj.id,
        usuario_id=context.user.id,
        ilpi_id=context.ilpi_id,
        valores_anteriores={"situacao": "ativo"},
        valores_posteriores={"situacao": "revogado", "motivo": obj.motivo_revogacao},
        request=request,
    )
    await db.commit()
    await db.refresh(obj)
    return obj


# ===== Sinais Vitais (C.3: registro mínimo seguro, histórico imutável) =====
# Modelo colunar mantido; correção = novo INSERT. Sem PUT, sem DELETE
# (rotas ausentes retornam 405). Tenant e autoria vêm exclusivamente da
# sessão (SecurityContext.ilpi_id + identidade autenticada). Unidades
# implícitas por campo; sistolica<=diastolica NÃO bloqueada nesta fase.

sinais_router = APIRouter(prefix="/sinais-vitais", tags=["sinais-vitais"])


async def _ensure_sinal_parent(db: AsyncSession, residente_id: str, context: SecurityContext):
    if not residente_id:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})
    parent = (
        await db.execute(
            select(m.Residente).where(
                m.Residente.id == residente_id,
                m.Residente.instituicao_id == context.ilpi_id,
            )
        )
    ).scalar_one_or_none()
    if parent is None:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})
    return parent


@sinais_router.get("/", response_model=list[s.SinalVitalResponse])
async def list_sinais_vitais(
    residente_id: str | None = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("sinais_vitais:ler")),
):
    query = select(m.SinalVital).where(m.SinalVital.ilpi_id == context.ilpi_id)
    if residente_id is not None:
        await _ensure_sinal_parent(db, residente_id, context)
        query = query.where(m.SinalVital.residente_id == residente_id)
    query = query.order_by(m.SinalVital.data.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    return result.scalars().all()


@sinais_router.post("/", response_model=s.SinalVitalResponse, status_code=201)
async def create_sinal_vital(
    payload: s.SinalVitalCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("sinais_vitais:criar")),
):
    data = payload.model_dump(exclude_unset=True)
    # Tenant e autoria vêm exclusivamente da sessão; o payload nunca decide.
    data.pop("ilpi_id", None)
    data.pop("instituicao_id", None)
    data.pop("profissional", None)
    data.pop("usuario_id", None)
    data.pop("autor", None)
    data.pop("executor", None)
    data["ilpi_id"] = context.ilpi_id
    data["profissional"] = await _resolve_profissional(db, context)
    await _ensure_sinal_parent(db, data.get("residente_id"), context)
    if data.get("data") is None:
        data["data"] = datetime.now(timezone.utc)
    for k, v in list(data.items()):
        if isinstance(v, str):
            data[k] = v.strip()
    obj = m.SinalVital(**data)
    db.add(obj)
    await db.flush()
    add_audit(
        db,
        acao="sinais_vitais.criar",
        entidade="sinais_vitais",
        registro_id=obj.id,
        usuario_id=context.user.id,
        ilpi_id=context.ilpi_id,
        valores_posteriores={"residente_id": data.get("residente_id"), "data": data.get("data")},
        request=request,
    )
    await db.commit()
    await db.refresh(obj)
    return obj


@sinais_router.get("/{sinal_id}", response_model=s.SinalVitalResponse)
async def get_sinal_vital(
    sinal_id: str,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("sinais_vitais:ler")),
):
    result = await db.execute(
        select(m.SinalVital).where(
            m.SinalVital.id == sinal_id,
            m.SinalVital.ilpi_id == context.ilpi_id,
        )
    )
    obj = result.scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})
    return obj


intercorrencias_router = APIRouter(prefix="/intercorrencias", tags=["intercorrencias"])


async def _ensure_intercorrencia_parent(db: AsyncSession, residente_id: str, context: SecurityContext):
    parent = (await db.execute(select(m.Residente.id).where(
        m.Residente.id == residente_id,
        m.Residente.instituicao_id == context.ilpi_id,
    ))).scalar_one_or_none()
    if parent is None:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso nao encontrado"})


@intercorrencias_router.get("/", response_model=list[s.IntercorrenciaResponse])
async def list_intercorrencias(
    residente_id: str | None = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("intercorrencias:ler")),
):
    query = select(m.Intercorrencia).where(m.Intercorrencia.ilpi_id == context.ilpi_id)
    if residente_id is not None:
        await _ensure_intercorrencia_parent(db, residente_id, context)
        query = query.where(m.Intercorrencia.residente_id == residente_id)
    # B1: a ordem passa a ser a do evento, nao a do registro. Uma intercorrencia
    # da madrugada anotada de manha aparece no lugar em que aconteceu.
    result = await db.execute(query.order_by(m.Intercorrencia.ocorrido_em.desc(), m.Intercorrencia.id).offset(max(0, skip)).limit(max(1, min(limit, 100))))
    return result.scalars().all()


@intercorrencias_router.post("/", response_model=s.IntercorrenciaResponse, status_code=201)
async def create_intercorrencia(
    payload: s.IntercorrenciaCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("intercorrencias:criar")),
):
    await _ensure_intercorrencia_parent(db, payload.residente_id, context)
    agora = datetime.now(timezone.utc)
    # Omitido, o registro vale por agora. Informado, e sempre timezone-aware
    # (AwareDatetime no schema) e normalizado para UTC antes de persistir.
    ocorrido_em = payload.ocorrido_em.astimezone(timezone.utc) if payload.ocorrido_em is not None else agora
    # Mesmo limite de rotina.py:419-420: o registro descreve o que ja aconteceu.
    if ocorrido_em > agora:
        raise HTTPException(status_code=422, detail="Ocorrido em nao pode estar no futuro")
    # Schemas ignore extra fields: neither tenant nor authorship comes from JSON.
    dados = payload.model_dump()
    dados["ocorrido_em"] = ocorrido_em
    # `data` (registrado_em) passa a ser escrita pela aplicacao, como ExecucaoCuidado
    # (rotina.py:428) e Administracao (medicacao.py:293) ja fazem. O server_default
    # CURRENT_TIMESTAMP do SQLite grava com precisao de SEGUNDO, enquanto qualquer
    # datetime vinculado chega com microssegundos: no keyset do Prontuario
    # '…:06' < '…:06.000000' e verdadeiro, e a linha do cursor voltava como primeira
    # da pagina seguinte. Escrever do Python torna armazenado e vinculado identicos.
    dados["data"] = agora
    obj = m.Intercorrencia(
        **dados,
        ilpi_id=context.ilpi_id,
        responsavel=await _resolve_profissional(db, context),
    )
    db.add(obj)
    await db.flush()
    add_audit(
        db, acao="intercorrencias.criar", entidade="intercorrencias",
        registro_id=obj.id, usuario_id=context.user.id, ilpi_id=context.ilpi_id,
        valores_posteriores=s.IntercorrenciaResponse.model_validate(obj).model_dump(),
        request=request,
    )
    await db.commit()
    await db.refresh(obj)
    return obj


@intercorrencias_router.get("/{intercorrencia_id}", response_model=s.IntercorrenciaResponse)
async def get_intercorrencia(
    intercorrencia_id: str,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("intercorrencias:ler")),
):
    obj = (await db.execute(select(m.Intercorrencia).where(
        m.Intercorrencia.id == intercorrencia_id,
        m.Intercorrencia.ilpi_id == context.ilpi_id,
    ))).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso nao encontrado"})
    return obj


async def _change_intercorrencia(db, context, intercorrencia_id, changes, action, request):
    obj = await get_intercorrencia(intercorrencia_id, db, context)
    if obj.situacao != "aberta":
        raise HTTPException(status_code=409, detail={"code": "INTERCORRENCIA_NAO_ABERTA", "message": "Intercorrencia nao esta aberta"})
    if not changes:
        raise HTTPException(status_code=422, detail="Informe ao menos um campo de correcao")
    before = {key: getattr(obj, key) for key in changes}
    # Compare-and-swap protects SQLite and PostgreSQL, including close vs correction.
    # Audit and mutation commit together; a stale writer never records false history.
    statement = update(m.Intercorrencia).where(
        m.Intercorrencia.id == obj.id,
        m.Intercorrencia.ilpi_id == context.ilpi_id,
        m.Intercorrencia.situacao == "aberta",
        *(getattr(m.Intercorrencia, key) == value for key, value in before.items()),
    ).values(**changes).execution_options(synchronize_session=False)
    try:
        result = await db.execute(statement)
        if result.rowcount != 1:
            await db.rollback()
            raise HTTPException(status_code=409, detail={"code": "INTERCORRENCIA_CONFLITO", "message": "Registro alterado; consulte novamente"})
        add_audit(
            db, acao=action, entidade="intercorrencias", registro_id=obj.id,
            usuario_id=context.user.id, ilpi_id=context.ilpi_id,
            valores_anteriores=before, valores_posteriores=changes, request=request,
        )
        await db.commit()
    except OperationalError:
        await db.rollback()
        raise HTTPException(status_code=409, detail={"code": "INTERCORRENCIA_CONFLITO", "message": "Conflito de escrita; tente novamente"})
    await db.refresh(obj)
    return obj


@intercorrencias_router.patch("/{intercorrencia_id}", response_model=s.IntercorrenciaResponse)
async def correct_intercorrencia(
    intercorrencia_id: str,
    payload: s.IntercorrenciaUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("intercorrencias:atualizar")),
):
    changes = payload.model_dump(exclude_unset=True)
    if "tipo" in changes:
        changes["tipo"] = changes["tipo"].strip()
    return await _change_intercorrencia(db, context, intercorrencia_id, changes, "intercorrencias.corrigir", request)


@intercorrencias_router.post("/{intercorrencia_id}/encerrar", response_model=s.IntercorrenciaResponse)
async def close_intercorrencia(
    intercorrencia_id: str,
    payload: s.IntercorrenciaEncerrar,
    request: Request,
    db: AsyncSession = Depends(get_db),
    context: SecurityContext = Depends(require_permission("intercorrencias:atualizar")),
):
    return await _change_intercorrencia(
        db, context, intercorrencia_id,
        {"situacao": "encerrada", "desfecho": payload.desfecho},
        "intercorrencias.encerrar", request,
    )


alertas_router = make_crud_router(m.Alerta, s.AlertaCreate, s.AlertaCreate, s.AlertaResponse, "/alertas", ["alertas"], fail_closed=True)

# Include routers under /api
app.include_router(health_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(auth_session_router, prefix="/api")
app.include_router(bootstrap_router, prefix="/api")
app.include_router(instituicoes_router, prefix="/api")
app.include_router(onboarding_router, prefix="/api")
# PLATFORM-1A: porta de provisionamento repetivel, separada do bootstrap acima.
app.include_router(platform_router, prefix="/api")
app.include_router(usuarios_router, prefix="/api")
app.include_router(funcionarios_router, prefix="/api")
app.include_router(perfis_router, prefix="/api")
app.include_router(permissoes_router, prefix="/api")
app.include_router(residentes_router, prefix="/api")
app.include_router(familiares_router, prefix="/api")
app.include_router(documentos_router, prefix="/api")
app.include_router(medicamentos_router, prefix="/api")
app.include_router(prescricoes_router, prefix="/api")
app.include_router(doses_previstas_router, prefix="/api")
app.include_router(administracoes_router, prefix="/api")
app.include_router(tarefas_router, prefix="/api")
app.include_router(avaliacoes_router, prefix="/api")
app.include_router(graus_router, prefix="/api")
app.include_router(planos_router, prefix="/api")
app.include_router(matriz_router, prefix="/api")
app.include_router(admissoes_router, prefix="/api")
app.include_router(programacoes_router, prefix="/api")
app.include_router(ocorrencias_router, prefix="/api")
app.include_router(execucoes_router, prefix="/api")
app.include_router(plantao_router, prefix="/api")
app.include_router(sinais_router, prefix="/api")
app.include_router(intercorrencias_router, prefix="/api")
app.include_router(alertas_router, prefix="/api")
app.include_router(quartos_leitos_router, prefix="/api")
app.include_router(ausencias_router, prefix="/api")
app.include_router(ocupacao_historico_router, prefix="/api")
app.include_router(prontuario_router, prefix="/api")

@app.get("/")
async def root():
    return {"message": "FáciLPI API — veja /docs e /api/health"}

# J: Alembic é única fonte oficial; create_all desabilitado por padrão
ALLOW_CREATE_ALL = os.getenv("ALLOW_CREATE_ALL", "false").lower() == "true"

@app.on_event("startup")
async def on_startup():
    if not ALLOW_CREATE_ALL:
        return
    # Permitido apenas em testes descartáveis explicitamente configurados
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
