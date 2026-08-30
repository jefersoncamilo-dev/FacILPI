# AGENTS — FáciLPI

Scaffold repo. No backend/frontend code yet — only `Project.md`, `Prompt.txt`, `config/*.md` and `.gitignore`s. Follow `Prompt.txt:13-102` order strictly. `storage/` is runtime data, never edited manually (`README.md:15`, `storage/.gitignore:1`).

## Source of Truth
Executable config > prose. Trust `config/TechSpecsConfig.md`, `config/DockerConfig.md`, `config/LoginConfig.md`, `config/SupabaseConfig.md`, `config/SecurityChecklist.md` over `Project.md`/`README.md` when they conflict. Business rules, entities and visual spec in `Project.md:6-168`.

## Structure
```
./
├── backend/src/{application,domain,infrastructure}  # Clean Architecture, DI service→controller, db→service
├── frontend/src/{components,pages,hooks,services}   # React+Vite+Tailwind+TS
├── storage/                                         # SQLite `app.db` + uploads `storage/<entity_id>/` — bind mount, git-ignored
├── docker/                                          # Dockerfiles
├── docker-compose.yml                               # at root
└── config/{TechSpecs,Docker,Login,Supabase,SecurityChecklist}.md
```

## Build Order (do not skip)
1. Read `Project.md` + all `config/*.md` 2. Scaffold dirs per `Prompt.txt:27-43` 3. Backend 4. Frontend 5. Docker 6. Apply `LoginConfig.md` + `SupabaseConfig.md` + `SecurityChecklist.md` 7. Update `README.md` 8. Validate — `Prompt.txt:96-102`

## Backend — Quirks
- UUIDs for all entity IDs (`Prompt.txt:49`, `TechSpecsConfig.md:10`).
- SQLAlchemy + Alembic only; migrations via Alembic API. Before creating engine or running Alembic with SQLite, ensure parent dir of `DATABASE_URL` exists (`Prompt.txt:54`, `TechSpecsConfig.md:44`, `DockerConfig.md:14`).
- All public routes under `prefix="/api"` (`TechSpecsConfig.md:46`): declare `APIRouter` paths as `/health`, `/clientes` etc. and `app.include_router(router, prefix="/api")`. Never mix prefixed/unprefixed.
- `GET /api/health` must NOT require auth/middleware — used by Docker/frontend healthcheck (`TechSpecsConfig.md:47`).
- CORS: permissive locally, restricted to real frontend origin in prod via env (`TechSpecsConfig.md:45`).
- Env only via backend `os.getenv`: `DATABASE_URL`, `JWT_SECRET`, `JWT_ALGORITHM=HS256`, `JWT_EXPIRY=3600`, `PORT`, `STORAGE_PATH`, CORS origins, rate-limit. No hardcoded secrets (`SecurityChecklist.md:13`).
- Uploads to `storage/<entity_id>/` (`Prompt.txt:55`, `TechSpecsConfig.md:9`); create `/storage` in backend Dockerfile before Alembic (`DockerConfig.md:14`).

## Frontend — Quirks
- `VITE_API_BASE_URL` must include `/api` (e.g. `http://localhost:8000/api`); services append only `/health`, `/clientes` — never duplicate to `/api/api` (`TechSpecsConfig.md:27`).
- Talks EXCLUSIVELY to backend REST. Never import Supabase/Firebase SDK or `SUPABASE_URL`/`anon key` — all integrations go through backend (`TechSpecsConfig.md:14`, `SupabaseConfig.md:7-21`, `SecurityChecklist.md:30`).
- Never expose `JWT_SECRET`, `DATABASE_URL` or keys in `VITE_*` (`TechSpecsConfig.md:29`, `SecurityChecklist.md:14`).
- Never use `alert()`/`confirm()` — use Modal component (`TechSpecsConfig.md:12`).
- Dashboard is initial page; sidebar = `Project.md:152` (Início, Meu Plantão, Residentes, ...). Theme `Project.md:155-158`: `#2563EB`/`#1E3A8A`/`#DBEAFE`/`#06B6D4`, bg `#F8FAFC`. Responsive 360/390/430/768/1366px no horizontal scroll, min touch 44×44, format dates/currency pt-BR (`TechSpecsConfig.md:24-25`).

## Docker (`config/DockerConfig.md`)
- Compose at repo root: `docker compose up --build`. Storage bind mount `./storage:/storage`.
- Backend Dockerfile: `RUN mkdir -p /storage` (no data in image), install `wget` for healthcheck.
- Healthcheck ordering: frontend `depends_on: backend: condition: service_healthy` probing `GET /api/health`. Backend not on port 80; frontend e.g. `8080`.

## Auth / Supabase / Security — Not Optional (`Prompt.txt:8-11`)
- Auth: implement `LoginConfig.md` fully after base CRUDs — `User` (id UUID, email unique, password_hash bcrypt, nome, ativo), `POST /auth/register` 409 on dup, `POST /auth/token` → `{access_token, token_type:"bearer"}` with `{sub,email,exp,iat}`, `PUT /auth/password` authenticated without current password, `get_current_user` middleware protects all CRUDs. Frontend: `/register`, `/login`, `AuthContext` (`localStorage` token, `login`/`logout`/`updatePassword`), `PrivateRoute`, `Authorization: Bearer <token>` on every request, 401 → logout.
- Supabase: only as managed Postgres via `DATABASE_URL=postgresql+asyncpg://...?pgbouncer=true` in `backend/.env` (`SupabaseConfig.md:44`). Switch to `create_async_engine` + `async_sessionmaker` + `async def` endpoints. Deps `asyncpg`+`greenlet`, remove `aiosqlite`. Adapt `alembic/env.py` to async. Frontend `.env` unchanged.
- Security checklist before done (`SecurityChecklist.md:71-83`): backend starts, frontend builds, `alembic upgrade head` succeeds, compose up, no secret in bundle, private routes require Bearer, rate-limit on `POST /auth/*` → 429, prod CORS configurable.

## Commands (after scaffold)
```bash
# backend (from backend/)
pip install -r requirements.txt
alembic upgrade head
uvicorn src.main:app --reload --port 8000

# frontend (from frontend/)
npm install
npm run dev      # vite
npm run build    # verify compile

# docker (from repo root)
docker compose up --build
curl http://localhost:8000/api/health
```
No tests yet — when added, run single file with `pytest backend/tests/test_<entity>.py -k test_name`.

## What NOT to Do
- Don't let frontend send `instituicao_id`/`autor_id` — derive from session (`Project.md:28-29`).
- Don't commit `storage/*`, `.env`, `*.db`; don't write generated code assumptions — check `alembic/` + `infrastructure/database.py` first.
