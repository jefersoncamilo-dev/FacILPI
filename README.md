# FáciLPI — Gestão, Cuidados e Conformidade

Plataforma SaaS para gestão completa de Instituições de Longa Permanência para Idosos (ILPI), cobrindo toda a jornada do residente: pré-admissão → admissão → avaliações → grau de dependência → Plano de Cuidados/PAIS → programação → Meu Plantão → execução diária → prontuário → intercorrências → passagem de plantão → supervisão → auditoria e relatórios. Residente no centro da operação, isolamento completo por ILPI, rastreabilidade e conformidade regulatória.

> Gerado a partir de `Project.md` + `Prompt.txt` + `config/*.md` (pegada-de-silicio).

## Stack

- **Backend:** Python 3.11, FastAPI, SQLAlchemy 2 (async), Alembic, Pydantic v2, `asyncpg`/`aiosqlite` + `greenlet`, `PyJWT` + `bcrypt`, Uvicorn
- **Frontend:** React 18 + Vite 6 + TypeScript 5 + Tailwind 3, React Router 6, Axios
- **DB:** SQLite local em `storage/app.db` (dev) ou PostgreSQL via Supabase (`DATABASE_URL=postgresql+asyncpg://...`) — troca zero-código, apenas env
- **Infra:** Docker + docker-compose (bind mount `./storage:/storage`, healthcheck em `/api/health`), Nginx para frontend
- **Auth:** JWT (`sub,email,exp,iat`) com `get_current_user`, rate-limit em `POST /auth/*`, `PrivateRoute` + `AuthContext` no frontend

## Requisitos

- Python 3.11+ e Node 20+ (ou Docker)
- `pip` e `npm` (ou `npm.cmd` no Windows)

## Variáveis de Ambiente

Nunca comite `.env` real. Use `.env.example` como base.

### Backend (`backend/.env`)
```env
DATABASE_URL=sqlite+aiosqlite:///./storage/app.db
# Supabase/Postgres: postgresql+asyncpg://user:password@host:port/database?pgbouncer=true
JWT_SECRET=troque-em-producao-min-32-chars
JWT_ALGORITHM=HS256
JWT_EXPIRY=3600
PORT=8000
STORAGE_PATH=./storage
CORS_ORIGINS=*
# Em produção: CORS_ORIGINS=https://seu-frontend.com
RATE_LIMIT_AUTH=10
```

### Frontend (`frontend/.env`)
```env
VITE_API_BASE_URL=http://localhost:8000/api
# Em produção: https://api.seu-dominio.com/api  (deve incluir /api)
```
> `VITE_*` nunca pode conter segredos (`JWT_SECRET`, `DATABASE_URL`). Frontend fala **exclusivamente** com backend REST — sem SDK Supabase/Firebase.

## Como rodar com Docker Compose (recomendado)

```bash
# na raiz do projeto
docker compose up --build
# Backend: http://localhost:8000/api/health  e  http://localhost:8000/docs
# Frontend: http://localhost:8080
# Dados persistem em ./storage (bind mount) — não edite manualmente
```

- Backend cria `/storage` no container antes do Alembic e instala `wget` para healthcheck.
- Frontend só sobe quando backend fica `healthy` (`wget http://backend:8000/api/health`).
- Para Supabase: ajuste `DATABASE_URL` no `docker-compose.yml` ou via `export DATABASE_URL=postgresql+asyncpg://...` antes do `up`.

```bash
# testar saúde
curl http://localhost:8000/api/health
```

## Como rodar manualmente (desenvolvimento)

### Backend
```bash
cd backend
cp .env.example .env   # edite JWT_SECRET se quiser
pip install -r requirements.txt
alembic upgrade head   # cria storage/app.db via migration 001_initial
uvicorn src.main:app --reload --port 8000
# http://localhost:8000/docs  |  http://localhost:8000/api/health
```

> O código garante `mkdir -p $(dirname $DATABASE_URL)` antes de criar engine/Alembic — não falha se `storage/` não existir.

### Frontend
```bash
cd frontend
cp .env.example .env
npm install
npm run dev      # http://localhost:5173  (VITE_API_BASE_URL aponta para http://localhost:8000/api)
npm run build    # verifica compilação de produção (tsc + vite build)
npm run preview  # pré-visualiza build em http://localhost:4173
```

### Fluxo de auth para testar
```bash
curl -X POST http://localhost:8000/api/auth/register -H "Content-Type: application/json" -d '{"nome":"Ana","email":"ana@ilpi.com","password":"Senha123A"}'
curl -X POST http://localhost:8000/api/auth/token -H "Content-Type: application/json" -d '{"email":"ana@ilpi.com","password":"Senha123A"}'
# use o access_token retornado:
curl http://localhost:8000/api/residentes/ -H "Authorization: Bearer <token>"
```

## Estrutura

```
./
├── backend/src/{application,domain,infrastructure}  # Clean Arch
│   ├── domain/validators.py        # CPF/CNPJ/CNS, senha
│   ├── infrastructure/{database.py,models.py}  # SQLAlchemy async (sqlite+aiosqlite / postgres+asyncpg)
│   ├── application/{schemas.py,auth.py}        # Pydantic + JWT + rate-limit
│   └── main.py                     # FastAPI com prefix /api, CORS, health sem auth
├── backend/alembic/                # migrações (001_initial)
├── frontend/src/{components,pages,hooks,services,context}
│   ├── services/api.ts             # axios com VITE_API_BASE_URL + Bearer + 401→logout
│   ├── context/AuthContext.tsx     # localStorage token, login/logout/updatePassword
│   ├── components/{Layout,Modal,PrivateRoute}
│   └── pages/{Dashboard,Login,Register,Residentes,MeuPlantao}
├── storage/                        # app.db + uploads/<entity_id>/ (git-ignored, bind mount)
├── docker/{Dockerfile.backend,Dockerfile.frontend}
├── docker-compose.yml
└── config/{TechSpecs,Docker,Login,Supabase,SecurityChecklist}.md
```

## Entidades implementadas (core expandível)

`User` (auth), `Instituicao`, `Residente`, `Familiar`, `Documento`, `QuartoLeito`, `Avaliacao`, `PlanoCuidados`, `Tarefa`, `Medicamento`, `Prescricao`, `SinalVital`, `Intercorrencia`, `Alerta` — todas com `id` UUID, validações (CPF/CNPJ/CNS, senha forte, datas) e rotas CRUD protegidas por `Authorization: Bearer <token>`. Outras entidades de `Project.md:80-119` seguem mesmo padrão.

## Segurança — Checklist

- [x] `JWT_SECRET` apenas no backend, `VITE_*` sem segredos (bundle verificado)
- [x] Senhas `bcrypt`, JWT com `exp/iat`, `401` → logout
- [x] `GET /api/health` sem auth; demais `/api/*` com `get_current_user`
- [x] CORS permissivo local (`*`) e restritivo em prod via `CORS_ORIGINS`
- [x] Rate-limit `POST /auth/*` → `429` (10/min por IP/usuário, in-memory)
- [x] Validações de entrada (Pydantic), rejeita payloads inesperados, limites de upload 10MB
- [x] Frontend nunca acessa Supabase diretamente; backend usa `DATABASE_URL` com `asyncpg` ou `aiosqlite`
- [x] Logs sem senhas/tokens, `storage/` tratado como artefato runtime
- [x] `docker compose up --build` sobe backend+frontend com healthcheck ordenado

## Comandos de validação

```bash
# backend
alembic upgrade head
python -c "from src.main import app; print('ok')"
# frontend
npm run build
# docker
docker compose config
docker compose up --build   # e curl http://localhost:8000/api/health
```

## Notas de Supabase (produção)

1. Crie projeto em supabase.com e copie a **Database connection string (pooled)**.
2. Em `backend/.env` ou `docker-compose.yml`: `DATABASE_URL=postgresql+asyncpg://...?pgbouncer=true`
3. Dependências já incluem `asyncpg`+`greenlet` (compatível com `sqlite+aiosqlite` local).
4. `alembic/env.py` já é async e garante `mkdir -p` para SQLite.
5. `alembic upgrade head` funciona contra Postgres; frontend `.env` não muda.

---

Tema visual: `#2563EB` / `#1E3A8A` / `#DBEAFE` / `#06B6D4`, fundo `#F8FAFC`, sucesso `#10B981`, atenção `#F59E0B`, crítico `#DC2626`. Layout mobile-first 360/390/430/768/1366 sem rolagem horizontal, toque mínimo 44×44, datas/moeda pt-BR.
