# Runbook — homologação (Render + Neon)

Ambiente publicado onde cada versão é validada antes do piloto na VPS
(`docs/RUNBOOK_PILOT.md`). Nenhum segredo vive aqui: connection strings e
tokens ficam nas CLIs autenticadas (`neonctl`, `render`) e no painel do Render.

## Topologia

| Peça | Onde | Origem do deploy |
|---|---|---|
| API (`facilpi-api`) | Render, web service | `main`, deploy automático |
| Frontend (`facilpi-web`) | Render, static site | `main`, deploy automático |
| Banco | Neon, projeto `facilpi-pilot`, branch `production` | migrations manuais |

**Regra:** só a `main` publica. Merge na `fase-3b/funcionarios-usuarios-vinculos`
não vai para o ar; promover para a `main` (PR com CI verde + autorização) **é** a
decisão de publicar. Até 16/10/2026 os dois serviços publicavam a `fase-3b`, e
uma migration podia chegar ao ar depois do código que dependia dela.

## Publicar uma versão

1. **PR de promoção** `fase-3b` → `main`, com CI verde. Não fazer o merge ainda.
2. **Backup:** criar a branch do Neon a partir da `production`, sem compute:
   ```bash
   neonctl branches create --project-id <projeto> --name backup-pre-<versao> --parent production --no-compute
   ```
3. **Migration, se a versão trouxer alguma** — antes do merge, porque o merge já
   publica o código. Conferir `alembic heads` (um único head) e aplicar na
   `production` com a connection string vinda da `neonctl`, sem exibi-la. Depois,
   `alembic current` deve mostrar o head novo. Sem migration nova, só conferir que
   `current` é o head do repositório.
4. **Merge** do PR de promoção (autorização explícita) e **tag** anotada na `main`.
5. **Conferir o deploy:** `render deploys list <serviço>` deve mostrar o commit do
   merge como `live`. Cada serviço tem diretório raiz (`backend/` na API,
   `frontend/` no site) e só publica quando algo dentro dele mudou; versão só de
   docs ou infra não gera deploy.
6. **Verificar:** `GET https://facilpi-api.onrender.com/api/health` → 200; os
   cabeçalhos abaixo presentes em `https://facilpi-web.onrender.com/`; login e
   telas principais sem violação de CSP no console.

## API na mesma origem do frontend (#207, painel do Render)

Desde o #207 a sessão vai em cookie HttpOnly `SameSite=Strict`. `onrender.com`
está na Public Suffix List: `facilpi-web` e `facilpi-api` são sites diferentes,
e um cookie entre eles seria de terceiros, bloqueado pelo Safari/iOS. Por isso o
frontend chama `/api` na própria origem e o Render repassa para a API, como o
Caddy faz na VPS. Passo manual, feito uma vez:

1. `facilpi-web` → **Redirects/Rewrites**: regra `Source /api/*` →
   `Destination https://facilpi-api.onrender.com/api/*`, `Action Rewrite`,
   **acima** da regra do SPA (`/*` → `/index.html`).
2. `facilpi-web` → **Environment**: `VITE_API_BASE_URL=/api` (vale no build;
   disparar novo deploy depois de mudar).
3. Verificar: `GET https://facilpi-web.onrender.com/api/health` → 200; o login
   devolve `Set-Cookie` de `access_token` (HttpOnly) e `csrf_token`; telas
   principais funcionam; sair e voltar exige novo login.

Com a mudança, abas abertas com o bundle antigo continuam no Bearer (o servidor
ainda o aceita na transição); quem abrir o bundle novo entra uma vez de novo.
O rate limit por IP passa a ver o IP repassado pelo Render: conferir nos logs da
API, depois da mudança, que `request.client.host` não é sempre o mesmo endereço.

## Cabeçalhos do `facilpi-web` (painel → Headers, Path `/*`)

Os mesmos do `docker/Caddyfile`, com uma diferença: aqui a API está em outro
domínio, então `connect-src` libera `https://facilpi-api.onrender.com`. Sem isso o
login quebra. Ao mudar a política no Caddyfile, mudar aqui também.

| Name | Value |
|---|---|
| `Content-Security-Policy` | `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https:; connect-src 'self' https://facilpi-api.onrender.com; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'` |
| `X-Frame-Options` | `DENY` |
| `X-Content-Type-Options` | `nosniff` |
| `Referrer-Policy` | `strict-origin-when-cross-origin` |
| `Permissions-Policy` | `camera=(), geolocation=(), microphone=(self)` |

## Rollback

- **Aplicação:** novo deploy do commit anterior pelo painel do Render (ou
  reverter o merge na `main`, que publica sozinho).
- **Banco:** restaurar a `production` a partir da branch `backup-pre-<versao>`
  (Neon → Branches → Restore). Rollback de aplicação não desfaz migration: se a
  versão anterior for de antes de uma migration já aplicada, restaurar o banco
  junto ou parar e escalar.
- Branches de backup antigas podem ser apagadas depois que a versão seguinte
  estiver validada — decisão humana.
