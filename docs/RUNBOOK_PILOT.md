# Runbook — piloto controlado (ENV-1)

Procedimento operacional para subir e verificar o ambiente do piloto.

> **Não há recuperação de desastre.** `BACKUP_RESTORE` ainda não foi
> implementado. Perder o host significa perder banco e anexos. Enquanto esse gate
> não fechar, o snapshot do provedor é a única rede de proteção, e ela é externa
> a este projeto.

## Topologia

```
Internet ──443──> edge (Caddy, TLS)
                   ├── /api/*  ──> backend:8000   rede edge_api (172.28.10.0/24)
                   └── resto   ──> frontend:8080  rede edge_web
                                     backend ──> db:5432  rede data (internal)
```

Somente o edge publica portas no host (80 e 443). Backend, frontend e banco não
são alcançáveis do host nem da internet. A rede `data` é `internal`: o PostgreSQL
não tem rota para fora.

| volume | conteúdo | dono |
|---|---|---|
| `facilpi_pilot_db` | dados do PostgreSQL | postgres (imagem) |
| `facilpi_pilot_data` | anexos em `/data/uploads` | app (10001) |
| `facilpi_pilot_caddy_data` | certificados ACME | caddy |

## 1. PRE-DEPLOY

1. DNS de `PUBLIC_HOST` apontando para o IP do host. **Antes** de subir o edge:
   o certificado é emitido por validação HTTP, e sem DNS resolvendo a emissão
   falha.
2. Portas 80 e 443 abertas no firewall do provedor.
3. `cp .env.example .env` e preencher. Gerar os segredos no próprio host:
   ```bash
   python3 -c "import secrets; print(secrets.token_hex(32))"      # JWT_SECRET
   python3 -c "import secrets; print(secrets.token_urlsafe(32))"  # POSTGRES_PASSWORD
   ```
4. Conferir que `DATABASE_URL` usa o mesmo usuário, senha e banco das variáveis
   `POSTGRES_*`, e que `CORS_ORIGINS` é `https://<PUBLIC_HOST>` — com `https://`,
   sem barra final, sem porta.
5. `chmod 600 .env`.

Validação sem subir nada:

```bash
docker compose config >/dev/null && echo "compose OK"
```

## 2. DEPLOY — banco primeiro

```bash
docker compose up -d db
docker compose ps db          # aguardar "healthy"
```

Não prossiga enquanto o healthcheck não estiver verde: o `pg_isready` usado
verifica o banco **da aplicação**, não só o processo.

## 3. MIGRATION

Migrar é ato deliberado, nunca efeito colateral de `docker compose up` — o
`alembic upgrade head` foi retirado do CMD da imagem na SAFE2-A, e deve
permanecer fora.

```bash
docker compose run --rm backend alembic upgrade head
docker compose run --rm backend alembic current
```

A saída de `alembic current` deve conter exatamente:

```
020_documentos_admin_anexar (head)
```

Se divergir, **pare aqui**. Subir a aplicação sobre um esquema que não é o head
produz erros que aparecem longe da causa.

## 4. Subir a aplicação

```bash
docker compose up -d
docker compose ps             # os quatro serviços saudáveis
```

## 5. BOOTSTRAP

Uma única vez por banco. Cria o operador da plataforma (`platform_superuser`).

```bash
docker compose run --rm \
  -e BOOTSTRAP_TOKEN_INPUT="<token de uso único>" \
  backend python -m src.scripts.bootstrap --show-password
```

`--show-password` é **obrigatório nesta primeira execução**. Sem ele a senha não
é exibida e **não pode ser recuperada**: apenas o hash fica no banco, e o
bootstrap não se repete no mesmo banco.

Anote a senha, faça o primeiro login imediatamente e, em seguida:

```bash
history -c        # ou remova a linha do histórico do shell
```

O `BOOTSTRAP_TOKEN` não vai para o `.env`: é de uso único e não tem função
depois disso.

## 6. FIRST LOGIN

1. Abrir `https://<PUBLIC_HOST>` e entrar com `admin@ilpi.com` e a senha
   temporária.
2. A troca de senha é obrigatória — o token emitido antes dela não abre nada
   institucional.
3. Após a troca, a Central FacILPI fica disponível em `/platform`.
4. Provisionar a primeira ILPI: criar instituição → cadastrar primeiro gestor →
   **anotar a senha temporária do gestor, que é exibida uma única vez** → ativar.

Se a credencial do gestor for perdida, use "Regerar credencial" na tela da
instituição (PLATFORM-2). A senha anterior deixa de valer.

## 7. VERIFY HTTPS

```bash
curl -sI http://<PUBLIC_HOST>/api/health      # 301/308 -> https
curl -sI https://<PUBLIC_HOST>/api/health     # 200 + Strict-Transport-Security
```

Confirmar também que `/docs`, `/redoc` e `/openapi.json` respondem **404** — com
`ENVIRONMENT=pilot` as rotas de documentação são desligadas.

## 8. VERIFY HEALTH

```bash
docker compose ps                      # todos healthy
curl -s https://<PUBLIC_HOST>/api/health
docker compose logs --tail=50 backend
```

## 9. VERIFY PERSISTENCE

```bash
docker compose restart backend
docker compose down && docker compose up -d
```

Após qualquer um dos dois, os dados devem continuar lá. Verificar que a
instituição provisionada e os anexos enviados permanecem.

> **Nunca** use `docker compose down -v`. A flag remove os volumes e destrói
> banco e anexos de forma irreversível, sem confirmação.

## 10. ROLLBACK / STOP

Parar sem perder dados:

```bash
docker compose down            # sem -v
```

Voltar a aplicação a uma versão anterior:

```bash
git checkout <sha anterior>
docker compose build backend frontend
docker compose up -d
```

**Rollback de aplicação não é rollback de banco.** Se a versão anterior for
anterior a uma migration já aplicada, o esquema continua no head novo. Não existe
downgrade seguro pelo runbook; nesse caso, pare e escale.

## O que o BACKUP_RESTORE precisará proteger

Registrado aqui para que o próximo gate não redescubra a lista:

1. **banco** — `facilpi_pilot_db`, via `pg_dump` consistente
2. **anexos** — `facilpi_pilot_data` → `/data/uploads`
3. **segredos/config** — o `.env` do host, sob custódia própria, fora do backup
   de dados
4. **versão da aplicação** — tag ou SHA da imagem que gerou aqueles dados
5. **head do Alembic** — `020_documentos_admin_anexar` no momento do backup

Os itens 4 e 5 são os que costumam faltar, e são o que separa "temos um dump" de
"conseguimos restaurar".
