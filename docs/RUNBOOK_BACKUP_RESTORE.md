# Runbook — backup e restore do piloto

> **Estado.** O mecanismo existe e a recuperação foi **demonstrada** num ensaio
> em que o ambiente de origem foi destruído antes do restore. Isto protege contra
> perda do banco, dos anexos ou de um container — **não** contra perda do host.
> A cópia off-host, que fecha essa lacuna, tem código pronto e ainda **não** foi
> provada contra o provedor: ver `docs/RUNBOOK_OFFHOST.md`.

## O que o pacote contém

```
facilpi-backup-<UTC>/
  database.dump     pg_dump -Fc do banco inteiro, incluindo alembic_version
  uploads.tar.gz    /data/uploads
  manifest.json     versão da app, head do Alembic, versão do PostgreSQL, hashes
  SHA256SUMS        checksums dos três arquivos acima
```

**Nenhum segredo entra no pacote.** `JWT_SECRET`, senha do PostgreSQL e
`DATABASE_URL` vivem no `.env` do host, sob custódia separada. Um pacote que
contivesse o dado assistencial **e** as chaves que o protegem transformaria um
vazamento de backup em comprometimento total.

## Backup

```bash
ops/backup.sh -p facilpi -e .env -d /var/backups/facilpi
```

A ordem é contrato, não estilo: **dump do banco primeiro, anexos depois.** O
upload promove o arquivo para o destino final *antes* de commitar o registro, e
nenhum caminho de produção apaga anexo. Nessa ordem o pior caso é um arquivo
órfão no pacote — invisível à aplicação. Na ordem inversa o pior caso seria uma
linha do banco apontando para arquivo que não foi copiado, que a aplicação
exibiria como documento quebrado.

Por isso o piloto **não precisa de janela de manutenção** para fazer backup.

## Restore — sempre em ambiente NOVO

```bash
# 1. subir só o banco, vazio, e esperar healthy
docker compose -p facilpi --env-file .env up -d db

# 2. restaurar
ops/restore.sh -p facilpi -e .env -b /var/backups/facilpi/facilpi-backup-<UTC>

# 3. subir a aplicação
docker compose -p facilpi --env-file .env up -d
```

O script verifica os checksums **antes** de tocar o banco e aborta se algum
divergir — pacote corrompido não é restaurado pela metade.

**Não execute `alembic upgrade head` antes do restore.** O dump já carrega o
esquema e a tabela `alembic_version`; migrar o banco vazio faria o `pg_restore`
colidir com objetos existentes. Depois do restore, na mesma versão da aplicação,
`upgrade head` é no-op — só é necessário se você estiver deliberadamente subindo
um backup antigo numa versão mais nova, o que é migração de versão, não
recuperação de desastre.

`pg_restore` roda com `--no-owner --no-acl`: o ambiente novo pode ter outro
usuário e outra senha de banco sem que o dump precise ser editado.

## Sessões após o desastre

O `JWT_SECRET` **não** é restaurado do backup — o ambiente novo recebe um segredo
novo. A consequência é deliberada: **todas as sessões anteriores deixam de
valer.** Um evento de desastre é exatamente o momento em que não se sabe o que
aconteceu com o host perdido, e forçar novo login é um ponto natural de
revogação. Os usuários entram de novo com as mesmas senhas, que estão no banco
restaurado.

## Retenção

```
local     7 diários
off-host  7 diários + 4 semanais
```

Compatível com o RPO de 24h. A limpeza opera **apenas** dentro do diretório
dedicado de backups e apenas sobre diretórios que casem com o padrão
`facilpi-backup-<UTC>` contendo um `manifest.json` válido — nunca por wildcard
amplo.

A retenção local é executada por `ops/retencao_local.sh`, que implementa essas
travas. **Simulação é o padrão**; nada é removido sem `--apply`:

```bash
ops/retencao_local.sh -d /var/backups/facilpi -k 7            # simula
ops/retencao_local.sh -d /var/backups/facilpi -k 7 --apply    # remove
```

A retenção off-host é executada por lifecycle rule do bucket, não pelo host — a
credencial de upload não tem `deleteFiles`. Ver `docs/RUNBOOK_OFFHOST.md`.

## Agendamento (exemplo — não instalado)

```cron
# /etc/cron.d/facilpi-backup — 1x por dia, 03:15, na VPS
15 3 * * * root cd /opt/facilpi && ops/backup.sh -p facilpi -e .env -d /var/backups/facilpi >> /var/log/facilpi-backup.log 2>&1
```

O job tem de nascer e morrer na VPS. Não depender da máquina do desenvolvedor:
ela não está ligada às 3h, não está na mesma rede e não é parte do ambiente.

## Cópia off-host — obrigatória antes de dado real

```
LOCAL_BACKUP  = IMPLEMENTADO E ENSAIADO
OFF_HOST_COPY = CÓDIGO PRONTO / NÃO PROVADO CONTRA O PROVEDOR
```

O pacote é um diretório de arquivos comuns, então o off-host o consome **depois
de pronto** e não altera nada deste documento: `ops/backup.sh` e `ops/restore.sh`
permanecem exatamente como foram ensaiados.

Implementação, custódia de chaves, Object Lock, capabilities mínimas e o drill
off-host estão em **`docs/RUNBOOK_OFFHOST.md`**. Nenhuma Application Key foi
criada, nenhuma chave `age` foi gerada e nenhum upload real foi feito — o
release para dado real segue bloqueado até o drill passar.

## RPO e RTO

```
RPO alvo = 24h     consequência direta do backup diário
RTO alvo = 4h      provisionar host + restaurar + validar
GARANTIA = nenhuma além do que o ensaio demonstrou
```

24h de RPO significa que até um dia de registros assistenciais pode precisar ser
reconstituído a partir do papel. Se isso for inaceitável, a resposta é aumentar a
frequência, não prometer melhor.

## Ensaio de restore

O ensaio é o que separa "temos um `.dump`" de "conseguimos restaurar". Ele
destrói o ambiente de origem antes de recuperar — sem isso, o teste poderia estar
passando por depender de algum estado sobrevivente.

```bash
export DRILL_PREFIX=drillorig
COMPOSE="docker compose -p facilpi-drill-origem --env-file <env> \
    -f docker-compose.yml -f ops/drill/compose.drill.yml"

$COMPOSE up -d db                                    # aguardar healthy
$COMPOSE run --rm backend alembic upgrade head
$COMPOSE up -d backend
$COMPOSE run --rm -e BOOTSTRAP_TOKEN=<token> -e BOOTSTRAP_TOKEN_INPUT=<token> \
    backend python -m src.scripts.bootstrap --show-password
$COMPOSE exec -T backend python - '<senha>' < ops/drill/popular_sintetico.py
$COMPOSE exec -T backend python - < ops/drill/linha_de_base.py

ops/backup.sh -p facilpi-drill-origem -e <env> -d <destino>

# ANTES de destruir: enumerar e conferir o label de CADA objeto
docker ps -aq  --filter label=com.docker.compose.project=facilpi-drill-origem
docker volume ls -q --filter label=com.docker.compose.project=facilpi-drill-origem
$COMPOSE down -v

# reconstruir com JWT_SECRET e senha de banco NOVOS
export DRILL_PREFIX=drillrest
docker compose -p facilpi-drill-restaurado --env-file <env-novo> ... up -d db
ops/restore.sh -p facilpi-drill-restaurado -e <env-novo> -b <pacote>
docker compose -p facilpi-drill-restaurado ... up -d backend
... exec -T backend python - /tmp/base.json < ops/drill/verificar_restauracao.py
```

O verificador falha se houver **referência pendente** (linha apontando para
arquivo ausente). **Órfãos** — arquivo sem linha — são apenas reportados: são o
resíduo esperado da ordem de backup, e nunca são apagados automaticamente.

A destruição é a única operação irreversível do procedimento. Ela só pode agir
sobre objetos cujo label `com.docker.compose.project` seja exatamente o do
projeto do ensaio. Nunca use `docker system prune`, `docker volume prune` ou
limpeza por prefixo de nome.

## Evidências exigidas do ensaio

1. `pg_restore` conclui sem erro
2. `alembic current` = `020_documentos_admin_anexar`
3. contagens iguais à linha de base
4. instituição, gestor, residente e documento sintéticos presentes
5. SHA-256 de cada arquivo restaurado == `documentos.arquivo_hash`
6. nenhuma referência pendente
7. aplicação sobe saudável contra o ambiente restaurado
8. download autenticado devolve o conteúdo original
9. token emitido sob o `JWT_SECRET` antigo é recusado
10. nenhum container ou volume da origem sobreviveu
