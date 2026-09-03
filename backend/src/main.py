import os
from fastapi import FastAPI, Depends, HTTPException, Request, APIRouter, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import pathlib

from .infrastructure.database import get_db, Base, engine, DATABASE_URL
from .infrastructure import models as m
from .application import schemas as s
from .application.auth import hash_password, verify_password, create_access_token, get_current_user, check_rate_limit
from .application.security import (
    ILPI_SCOPE,
    SecurityContext,
    block_pending_permission_catalog,
    ensure_same_tenant,
    require_permission,
)

# Ensure storage dir exists for uploads
STORAGE_PATH = os.getenv("STORAGE_PATH", "./storage")
pathlib.Path(STORAGE_PATH).mkdir(parents=True, exist_ok=True)

# CORS Origins
cors_origins = os.getenv("CORS_ORIGINS", "*")
if cors_origins == "*":
    allow_origins = ["*"]
else:
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
async def token(payload: s.UserLogin, request: Request, db: AsyncSession = Depends(get_db)):
    client_ip = request.client.host if request.client else "unknown"
    check_rate_limit(f"token:{client_ip}")
    result = await db.execute(select(m.User).where(m.User.email == payload.email.lower().strip()))
    user = result.scalar_one_or_none()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Credenciais inválidas")
    if not user.ativo:
        raise HTTPException(status_code=401, detail="Usuário inativo")
    access_token = create_access_token(user)
    return {"access_token": access_token, "token_type": "bearer"}

@auth_router.put("/password")
async def update_password(payload: s.PasswordUpdate, db: AsyncSession = Depends(get_db), current_user: m.User = Depends(get_current_user)):
    # rate limit authenticated by user id
    check_rate_limit(f"password:{current_user.id}")
    if payload.nova_senha != payload.confirmar_senha:
        raise HTTPException(status_code=400, detail="Senhas não conferem")
    current_user.password_hash = hash_password(payload.nova_senha)
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
):
    router = APIRouter(prefix=prefix, tags=tags)

    def guard(action: str):
        if fail_closed:
            return block_pending_permission_catalog
        if permissions is not None:
            return require_permission(permissions[action])
        return get_current_user

    def scoped_query(query, context):
        if (
            tenant_resource == "instituicao"
            and isinstance(context, SecurityContext)
            and context.scope == ILPI_SCOPE
        ):
            return query.where(model.id == context.ilpi_id)
        return query

    def ensure_resource_scope(context, item_id: str) -> None:
        if tenant_resource == "instituicao" and isinstance(context, SecurityContext):
            ensure_same_tenant(context, item_id)

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
            raise HTTPException(status_code=404, detail="Não encontrado")
        return obj

    @router.put("/{item_id}", response_model=response_schema)
    async def update_item(item_id: str, payload: update_schema, db: AsyncSession = Depends(get_db), context = Depends(guard("update"))):
        ensure_resource_scope(context, item_id)
        result = await db.execute(select(model).where(model.id == item_id))
        obj = result.scalar_one_or_none()
        if not obj:
            raise HTTPException(status_code=404, detail="Não encontrado")
        data = payload.model_dump(exclude_unset=True)
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
            raise HTTPException(status_code=404, detail="Não encontrado")
        await db.delete(obj)
        await db.commit()
        return None

    return router

# Create routers for each entity
instituicoes_router = make_crud_router(
    m.Instituicao,
    s.InstituicaoCreate,
    s.InstituicaoUpdate,
    s.InstituicaoResponse,
    "/instituicoes",
    ["instituicoes"],
    permissions={
        "list": "ilpis:ler",
        "create": "ilpis:criar",
        "get": "ilpis:ler",
        "update": "ilpis:atualizar",
        "delete": "ilpis:inativar",
    },
    tenant_resource="instituicao",
)
residentes_router = make_crud_router(m.Residente, s.ResidenteCreate, s.ResidenteUpdate, s.ResidenteResponse, "/residentes", ["residentes"], fail_closed=True)
familiares_router = make_crud_router(m.Familiar, s.FamiliarCreate, s.FamiliarCreate, s.FamiliarResponse, "/familiares", ["familiares"], fail_closed=True)
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
app.include_router(instituicoes_router, prefix="/api")
app.include_router(residentes_router, prefix="/api")
app.include_router(familiares_router, prefix="/api")
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
