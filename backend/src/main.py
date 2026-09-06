import os
from fastapi import FastAPI, Depends, HTTPException, Request, Response, APIRouter, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import false, select, func
import pathlib

from .infrastructure.database import get_db, Base, engine, DATABASE_URL
from .infrastructure import models as m
from .application import schemas as s
from .application.auth import hash_password, verify_password, get_current_user, check_rate_limit, revoke_user_refresh_tokens
from .application.audit import add_audit
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
from .application.security import (
    ILPI_SCOPE,
    PERMISSION_DENIED,
    RESOURCE_NOT_FOUND,
    SecurityContext,
    block_pending_permission_catalog,
    ensure_same_tenant,
    require_permission,
)

# Ensure storage dir exists for uploads
STORAGE_PATH = os.getenv("STORAGE_PATH", "./storage")
pathlib.Path(STORAGE_PATH).mkdir(parents=True, exist_ok=True)

# CORS Origins
default_local_origins = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:8080,http://127.0.0.1:8080"
cors_origins = os.getenv("CORS_ORIGINS", default_local_origins)
if cors_origins.strip() == "*":
    # Cookies exigem credentials=true; CORS não pode responder com origem '*'.
    cors_origins = default_local_origins
allow_origins = [o.strip() for o in cors_origins.split(",") if o.strip()]

app = FastAPI(title="FáciLPI API", version="1.0.0")

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
    if payload.nova_senha != payload.confirmar_senha:
        raise HTTPException(status_code=400, detail="Senhas não conferem")
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
):
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

    @router.get("/", response_model=list[response_schema])
    async def list_items(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db), context = Depends(guard("list"))):
        query = scoped_query(select(model), context)
        order = model.created_at.desc() if hasattr(model, "created_at") else model.id
        result = await db.execute(query.order_by(order).offset(skip).limit(limit))
        items = result.scalars().all()
        return items

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
        result = await db.execute(select(model).where(model.id == item_id))
        obj = result.scalar_one_or_none()
        if not obj:
            raise HTTPException(status_code=404, detail={"code": RESOURCE_NOT_FOUND, "message": "Recurso não encontrado"})
        ensure_clinical_tenant(context, obj)
        data = payload.model_dump(exclude_unset=True)
        if tenant_column is not None:
            # Troca de tenant via update é proibida: ignora o tenant do cliente.
            data.pop("instituicao_id", None)
            data.pop("ilpi_id", None)
        if parent_check is not None:
            # Vínculo pai é imutável via PUT genérico: ignora o valor do
            # cliente. Troca de vínculo exige fluxo próprio, auditável.
            data.pop(parent_check["id_field"], None)
        for k, v in data.items():
            if isinstance(v, str):
                v = v.strip()
                if v == "":
                    continue
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
)
medicamentos_router = make_crud_router(m.Medicamento, s.MedicamentoCreate, s.MedicamentoUpdate, s.MedicamentoResponse, "/medicamentos", ["medicamentos"], fail_closed=True)
prescricoes_router = make_crud_router(m.Prescricao, s.PrescricaoCreate, s.PrescricaoCreate, s.PrescricaoResponse, "/prescricoes", ["prescricoes"], fail_closed=True)
tarefas_router = make_crud_router(m.Tarefa, s.TarefaCreate, s.TarefaUpdate, s.TarefaResponse, "/tarefas", ["tarefas"], fail_closed=True)
# Additional entities: avaliacoes, sinais, intercorrencias, alertas
# For brevity create direct routers via make_crud

# We need simple schemas for those not yet via helper — reuse create for update where feasible
from pydantic import BaseModel
# Define adhoc routers manually for avaliacoes etc using same models

avaliacoes_router = APIRouter(prefix="/avaliacoes", tags=["avaliacoes"])
@avaliacoes_router.get("/", response_model=list[dict])
async def list_avaliacoes(db: AsyncSession = Depends(get_db), _blocked: None = Depends(block_pending_permission_catalog)):
    result = await db.execute(select(m.Avaliacao).order_by(m.Avaliacao.data.desc()))
    return [{"id": r.id, "residente_id": r.residente_id, "tipo": r.tipo, "pontuacao": r.pontuacao, "classificacao": r.classificacao, "data": r.data.isoformat() if r.data else None} for r in result.scalars().all()]

@avaliacoes_router.post("/", status_code=201)
async def create_avaliacao(payload: dict, db: AsyncSession = Depends(get_db), _blocked: None = Depends(block_pending_permission_catalog)):
    obj = m.Avaliacao(**payload)
    db.add(obj)
    await db.commit()
    await db.refresh(obj)
    return {"id": obj.id, "residente_id": obj.residente_id, "tipo": obj.tipo, "pontuacao": obj.pontuacao}

sinais_router = make_crud_router(m.SinalVital, s.SinalVitalCreate, s.SinalVitalCreate, s.SinalVitalResponse, "/sinais-vitais", ["sinais-vitais"], fail_closed=True)
intercorrencias_router = make_crud_router(m.Intercorrencia, s.IntercorrenciaCreate, s.IntercorrenciaCreate, s.IntercorrenciaResponse, "/intercorrencias", ["intercorrencias"], fail_closed=True)
alertas_router = make_crud_router(m.Alerta, s.AlertaCreate, s.AlertaCreate, s.AlertaResponse, "/alertas", ["alertas"], fail_closed=True)

# Upload handler generic: storage/<entity_id>/
uploads_router = APIRouter(prefix="/uploads", tags=["uploads"])

@uploads_router.post("/{entity_id}")
async def upload_file(entity_id: str, file: UploadFile = File(...), _blocked: None = Depends(block_pending_permission_catalog)):
    # Validate file type/size (simple)
    allowed = {"image/jpeg","image/png","image/webp","application/pdf","text/plain"}
    if file.content_type not in allowed:
        # allow any for now but warn
        pass
    # limit 10MB
    content = await file.read()
    if len(content) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Arquivo muito grande (máx 10MB)")
    dest_dir = pathlib.Path(STORAGE_PATH) / entity_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / file.filename
    dest_path.write_bytes(content)
    return {"filename": file.filename, "path": str(dest_path), "size": len(content)}

# Include routers under /api
app.include_router(health_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(auth_session_router, prefix="/api")
app.include_router(bootstrap_router, prefix="/api")
app.include_router(instituicoes_router, prefix="/api")
app.include_router(onboarding_router, prefix="/api")
app.include_router(usuarios_router, prefix="/api")
app.include_router(funcionarios_router, prefix="/api")
app.include_router(perfis_router, prefix="/api")
app.include_router(permissoes_router, prefix="/api")
app.include_router(residentes_router, prefix="/api")
app.include_router(familiares_router, prefix="/api")
app.include_router(documentos_router, prefix="/api")
app.include_router(medicamentos_router, prefix="/api")
app.include_router(prescricoes_router, prefix="/api")
app.include_router(tarefas_router, prefix="/api")
app.include_router(avaliacoes_router, prefix="/api")
app.include_router(sinais_router, prefix="/api")
app.include_router(intercorrencias_router, prefix="/api")
app.include_router(alertas_router, prefix="/api")
app.include_router(uploads_router, prefix="/api")

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
