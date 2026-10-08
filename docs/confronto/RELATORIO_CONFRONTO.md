# Relatório de confronto — FáciLPI (cópia remota)

Gerado em 2026-10-08 a partir do repositório remoto, para comparar com a sua cópia local.

## 1. Referência do repositório

| Item | Valor |
|---|---|
| Branch | `claude/adoring-sagan-ra7le9` |
| Commit HEAD | `20082b5316b14bb181a624161dc1e7317c26d7a7` |
| Mensagem | `feat: versão inicial do FacILPI` |
| Data do commit | 2026-08-30 04:32:46 -0300 |
| Arquivos versionados | 56 |
| Linhas totais (arquivos versionados) | 6769 |
| Ferramentas usadas no teste | Python 3.11.15, Node v22.22.0 |

**Teste rápido local:** `git rev-parse HEAD`. Se der o mesmo hash acima e `git status` estiver limpo, as duas cópias são idênticas e o resto do relatório vale integralmente para você.

## 2. Resultado das verificações (ambiente remoto)

| # | Verificação | Comando (rodar local) | Resultado remoto |
|---|---|---|---|
| 1 | Instalar deps backend | `cd backend && pip install -r requirements.txt` | ✅ OK |
| 2 | Migração em clone limpo | `rm -rf backend/storage && cd backend && alembic upgrade head` | ❌ `sqlite3.OperationalError: unable to open database file` |
| 3 | Backend sobe | `uvicorn src.main:app --port 8000` | ✅ OK |
| 4 | Healthcheck sem auth | `curl localhost:8000/api/health` | ✅ 200 `{"status":"ok"}` |
| 5 | Rota privada sem token | `curl -i localhost:8000/api/residentes/` | ✅ 401 |
| 6 | Validação do registro | `POST /api/auth/register` com nome de 1 caractere | ✅ 422 |
| 7 | Frontend compila | `cd frontend && npm ci && npm run build` | ✅ 97 módulos, JS ~250 kB |
| 8 | Docker Compose | `docker compose up --build` | ⚠️ não testado (sem Docker no ambiente) |
| 9 | Rate limit `POST /auth/*` → 429 | repetir `POST /api/auth/token` várias vezes | ⚠️ implementado no código, não exercitado |
| 10 | Testes automatizados | `pytest backend/tests` | ❌ pasta `backend/tests` não existe |

Preencha a coluna local:

| # | Resultado local | Igual? |
|---|---|---|
| 1 | | |
| 2 | | |
| 3 | | |
| 4 | | |
| 5 | | |
| 6 | | |
| 7 | | |
| 8 | | |
| 9 | | |
| 10 | | |

## 3. Bug conhecido — caminho do SQLite

- Arquivos: `backend/src/infrastructure/database.py` (`_ensure_parent_dir`, ~linha 27) e `backend/alembic/env.py` (`get_url`, ~linha 39).
- Causa: `url.split("://", 1)[1]` em `sqlite+aiosqlite:///./storage/app.db` devolve `/./storage/app.db`, então cria `/storage` (raiz) em vez de `./storage`.
- Sintoma local: item 2 falha se `backend/storage/` não existir. No Docker não aparece porque lá o caminho real é `/storage`.
- Para conferir aí: depois de rodar o item 2, veja se apareceu uma pasta `/storage` na raiz da sua máquina.

## 4. Inventário funcional

### Backend — rotas (todas sob `/api`)
| Rota | Métodos | Auth |
|---|---|---|
| `/health` | GET | não |
| `/auth/register`, `/auth/token` | POST (com rate limit) | não |
| `/auth/password` | PUT | sim |
| `/instituicoes`, `/residentes`, `/familiares`, `/medicamentos`, `/prescricoes`, `/tarefas`, `/sinais-vitais`, `/intercorrencias`, `/alertas` | GET lista, POST, GET/PUT/DELETE `{id}` | sim |
| `/avaliacoes` | GET, POST (payload `dict`, sem schema) | sim |
| `/uploads/{entity_id}` | POST (whitelist de content-type) | sim |

### Backend — modelos (14)
User, Instituicao, Residente, Familiar, Documento, QuartoLeito, Avaliacao, PlanoCuidados, Tarefa, Medicamento, Prescricao, SinalVital, Intercorrencia, Alerta.
Sem rota: Documento, QuartoLeito, PlanoCuidados. Migração única: `alembic/versions/001_initial.py`.

### Frontend — telas
- **Com conteúdo:** `/login`, `/register`, `/` (Dashboard), `/plantao` (Meu Plantão), `/residentes`.
- **Só Placeholder (20):** admissoes, avaliacoes, plano, cuidados, medicacao, sinais, intercorrencias, agenda, passagem, quartos, equipe, estoque, financeiro, familia, relatorios, supervisao, compliance, auditoria, config, alertas.

## 5. Desvios em relação ao spec (`Project.md` / `AGENTS.md`)

| # | Desvio | Onde | Severidade |
|---|---|---|---|
| 1 | `instituicao_id` vem do payload; listas não filtram por instituição | `backend/src/main.py` ~linha 102 | Alta |
| 2 | `User` sem `instituicao_id` nem perfis/permissões | `models.py` | Alta |
| 3 | `DELETE` apaga registros clínicos fisicamente | `make_crud_router` ~linha 148 | Alta |
| 4 | Sem autoria (`autor_id`) e sem auditoria antes/depois | todo o backend | Alta |
| 5 | `/avaliacoes` aceita `dict` sem validação | `main.py` ~linha 181 | Média |
| 6 | Bug do caminho SQLite (seção 3) | `database.py`, `alembic/env.py` | Média |
| 7 | Sem testes | `backend/tests` ausente | Média |
| 8 | `requirements.txt` com `aiosqlite` e `asyncpg` juntos (SupabaseConfig pede remover `aiosqlite`) | `backend/requirements.txt` | Baixa |
| 9 | `AGENTS.md` ainda diz "Scaffold, no code" | `AGENTS.md` | Baixa |
| 10 | 20 telas em Placeholder | `frontend/src/App.tsx` | Escopo |

## 6. Inventário de arquivos (SHA-256)

Os hashes completos estão no arquivo `manifest.sha256`, que vem junto. Para comparar automaticamente, rode na raiz do projeto local: `bash docs/confronto/comparar.sh docs/confronto/manifest.sha256` (ou copie os dois arquivos para a raiz e rode `bash comparar.sh`).

| Arquivo | Linhas | SHA-256 (16 primeiros) |
|---|---|---|
| `.dockerignore` | 11 | `c8fbc24ac5478f8e` |
| `AGENTS.md` | 68 | `b7b1193f3623557e` |
| `Project.md` | 173 | `6391dc08b1a8b5cb` |
| `Prompt.txt` | 103 | `05d50b1bc8ebfa36` |
| `README.md` | 156 | `e464bacd7b6de3ac` |
| `backend/.env.example` | 12 | `e01d95e2a61fcb3c` |
| `backend/.gitignore` | 55 | `e9f162cbd16c8af3` |
| `backend/alembic.ini` | 42 | `fa515919a69db0fe` |
| `backend/alembic/env.py` | 81 | `ad4b56fd12194524` |
| `backend/alembic/script.py.mako` | 26 | `304a8bfb6a804e54` |
| `backend/alembic/versions/001_initial.py` | 291 | `01699883b8ea8c69` |
| `backend/requirements.txt` | 15 | `39ed4e57eb3d59e6` |
| `backend/src/__init__.py` | 0 | `e3b0c44298fc1c14` |
| `backend/src/application/__init__.py` | 0 | `e3b0c44298fc1c14` |
| `backend/src/application/auth.py` | 76 | `c3650fa5c2a1eaab` |
| `backend/src/application/schemas.py` | 322 | `86b8f347c7c64236` |
| `backend/src/domain/__init__.py` | 0 | `e3b0c44298fc1c14` |
| `backend/src/domain/validators.py` | 60 | `58f55a0d97a9b8f0` |
| `backend/src/infrastructure/__init__.py` | 0 | `e3b0c44298fc1c14` |
| `backend/src/infrastructure/database.py` | 74 | `ed40572490591ed8` |
| `backend/src/infrastructure/models.py` | 246 | `a3a9faa226af6619` |
| `backend/src/main.py` | 236 | `d6aabe4b70e4ed96` |
| `config/DockerConfig.md` | 16 | `0a14eda226077b1d` |
| `config/LoginConfig.md` | 144 | `ec78c9482bb62c21` |
| `config/SecurityChecklist.md` | 83 | `02d2a2466f60e2c9` |
| `config/SupabaseConfig.md` | 190 | `6e57327924213cb9` |
| `config/TechSpecsConfig.md` | 47 | `b149bc527b60add6` |
| `docker-compose.yml` | 42 | `3c6775b3624b7c52` |
| `docker/Dockerfile.backend` | 30 | `27449732a8fbb575` |
| `docker/Dockerfile.frontend` | 20 | `2c60946878dd2422` |
| `frontend/.env.example` | 2 | `0664b2d9c16777e1` |
| `frontend/.gitignore` | 41 | `2587992e6c632c5d` |
| `frontend/index.html` | 16 | `495c3f284eba8a15` |
| `frontend/package-lock.json` | 3161 | `181a7c4473cc4fb0` |
| `frontend/package.json` | 29 | `ca1d40c4254ec4bd` |
| `frontend/postcss.config.js` | 6 | `190c877db466995b` |
| `frontend/src/App.tsx` | 51 | `f800b6ea62a8e38c` |
| `frontend/src/components/Layout.tsx` | 149 | `03d2e073c2b6be13` |
| `frontend/src/components/Modal.tsx` | 22 | `81904b87079fbdc8` |
| `frontend/src/components/PrivateRoute.tsx` | 8 | `84d3cd34b3710b5a` |
| `frontend/src/context/AuthContext.tsx` | 77 | `0069e27e2b27b5ed` |
| `frontend/src/index.css` | 16 | `43e699dca8f049c9` |
| `frontend/src/main.tsx` | 10 | `abe0edc1f91f5d41` |
| `frontend/src/pages/Dashboard.tsx` | 122 | `bed481e3f327fe59` |
| `frontend/src/pages/Login.tsx` | 51 | `297ce1bcac85dc3b` |
| `frontend/src/pages/MeuPlantao.tsx` | 76 | `a19214cbdbbad89c` |
| `frontend/src/pages/Placeholder.tsx` | 20 | `88c409f4ed5fb0c4` |
| `frontend/src/pages/Register.tsx` | 51 | `a3665a1df472ecdd` |
| `frontend/src/pages/Residentes.tsx` | 105 | `2f6605d09e6113ac` |
| `frontend/src/services/api.ts` | 48 | `22c246fab982b30b` |
| `frontend/src/vite-env.d.ts` | 7 | `62d2085e3bf185f7` |
| `frontend/tailwind.config.js` | 30 | `53350e27f2217479` |
| `frontend/tsconfig.json` | 25 | `ad6be7ffededce9d` |
| `frontend/tsconfig.node.json` | 10 | `9e2abb169ea87b71` |
| `frontend/vite.config.ts` | 14 | `138eb5f755599ba4` |
| `storage/.gitignore` | 3 | `9ff8dacd84281c2a` |

> Diferenças de fim de linha (CRLF no Windows) mudam o hash. Se tudo vier "DIFERENTE", rode `git config core.autocrlf false` ou compare com `git diff` em vez dos hashes.
