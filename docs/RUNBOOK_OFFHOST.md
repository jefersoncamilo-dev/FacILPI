# Runbook — cópia off-host cifrada (Backblaze B2 + age)

> **Estado.** Os scripts existem e foram exercitados localmente com material
> sintético. **Nenhum upload real foi feito**, nenhuma Application Key existe e
> nenhuma chave `age` foi gerada. Enquanto os gates abaixo não forem cumpridos,
> `OFF_HOST_COPY = CÓDIGO PRONTO / NÃO PROVADO CONTRA O B2`.

O backup local (`docs/RUNBOOK_BACKUP_RESTORE.md`) protege contra perda do banco,
dos anexos ou de um container. **Não protege contra perda do host.** É isso que
esta cópia fecha.

## Desenho

```
ops/backup.sh  →  facilpi-backup-<UTC>/          (inalterado, já validado)
                          │
                          ▼
ops/offhost_upload.sh     roda NA VPS
   valida SHA256SUMS → tar → age -r <público> → SHA-256 do cifrado
   → PUT único no B2 com Object Lock no mesmo PUT → manifesto + marcador
                          │
                          ▼
ops/offhost_fetch.sh      roda FORA DA VPS
   download → confere SHA-256 → age -d → extrai → reconfere SHA256SUMS
                          │
                          ▼
ops/restore.sh            inalterado
```

O caminho de backup validado **não muda**. O off-host é um segundo script que
consome o pacote pronto: se ele falhar, o backup local continua íntegro e válido.

## Separação de custódia — a decisão que sustenta todo o resto

| Onde | O que existe lá | O que **não** pode existir lá |
|---|---|---|
| VPS | recipient `age` **público**; credencial de upload (só escreve) | chave privada `age`, credencial de leitura, Master Key |
| Cofre do responsável | chave privada `age`, credencial de restore | — |
| Cópia offline, outro local físico | segunda cópia da chave privada `age` | — |
| Bucket B2 | apenas artefatos cifrados | qualquer chave |
| Repositório | nada disso | qualquer segredo |

Duas propriedades precisam valer ao mesmo tempo, e elas puxam para lados opostos:

- **nenhum evento único pode destruir** o bucket *e* as duas cópias da chave —
  por isso as cópias ficam em locais distintos e nenhuma delas é o B2;
- **nenhum evento único pode comprometer** o bucket *e* a chave — por isso a
  chave privada nunca toca a VPS, que é a máquina exposta.

Consequência direta e assumida: **perder as duas cópias da chave privada `age`
destrói todos os backups off-host.** A cifra que protege o dado assistencial se
o bucket vazar é a mesma que o torna irrecuperável sem a chave. Uma chave que
nunca foi testada não é um backup — por isso o drill (GATE-6) decifra usando a
cópia custodiada, não uma cópia de conveniência.

## Ferramentas — imagem controlada no upload, binário local no fetch

```
upload (VPS)        container, imagem própria facilpi/offhost:1
                    alpine:3.20 pinado por digest + age 1.2.1-r0 + aws-cli 2.15.57-r0

fetch (recuperação) OFFHOST_RUNTIME=local  (padrão)  → binário age do operador
                    OFFHOST_RUNTIME=container        → opção consciente
```

**Por que container no upload.** `ops/backup.sh` já usa `docker compose exec db
pg_dump` e `docker run alpine`. Sem Docker não existe pacote para enviar, então
exigir Docker no upload **não acrescenta modo de falha novo** — e entrega
reprodutibilidade que instalar pacotes numa distro arbitrária não entrega.

**Por que binário local no fetch.** Esta é a assimetria que decide o desenho: no
upload circula apenas o recipient **público**, e um container não teria o que
vazar. Na recuperação é a chave **privada** que entra em jogo — a que decifra
*todos* os backups off-host. Em modo `container` ela precisa ser bind-montada
para dentro da imagem; em modo `local` nunca sai do sistema de arquivos do
operador. O modo `container` existe para quem não tem o binário, avisa em voz
alta e **não é o padrão**.

A imagem precisa existir **antes** do primeiro backup (GATE-7). O script **não
faz pull nem build automático** — se a imagem faltar, ele falha com instrução
explícita em vez de baixar algo em silêncio no meio da madrugada:

```bash
docker build -t facilpi/offhost:1 ops/offhost
```

Construção, preparação offline (`docker save`/`load`), operação sem rede e o
procedimento de atualização — que exige **revalidar versões e digest** — estão em
`ops/offhost/README.md`.

## Configuração

`ops/offhost.env.example` é o modelo. O arquivo real vive **fora do
repositório**:

```
/etc/facilpi/offhost.env        root:root        chmod 0600
```

Nenhum script deste repositório cria credencial, gera chave `age` ou pede
segredo. Segredos entram apenas por esse arquivo, são lidos sem `source` (mesmo
padrão de `ops/backup.sh`) e nunca são passados por argumento — argumento é
visível em `ps` para qualquer usuário da máquina.

## Application Keys — menor privilégio

A **Master Application Key não é usada pelo runtime.** Ela serve uma única vez,
em sessão interativa de um humano, para criar as duas chaves abaixo e configurar
o bucket. Não entra em script, VPS, variável de serviço ou log.

O preset **"Write Only" da interface do Backblaze não é contrato.** As chaves são
criadas por `b2 key create` / `b2_create_key` com a lista explícita.

### Upload — única credencial que pode viver na VPS

```
nome          facilpi-pilot-upload
bucket        facilpi-pilot-backup-x7k9p2   (restrita por bucketId)
namePrefix    facilpi/
capabilities  writeFiles
              writeFileRetentions
```

`listBuckets` **não** é concedida de saída. Só entra se o GATE-3 provar que o
endpoint S3 exige; nesse caso a chave é recriada, e o pior caso continua sendo
enumerar um bucket que ela já podia escrever.

Negadas por decisão: `deleteFiles`, `readFiles`, `listFiles`, `deleteBuckets`,
`writeBuckets`, `writeBucketRetentions`, `bypassGovernance`, `listAllBucketNames`,
`shareFiles`, `readFileLegalHolds`/`writeFileLegalHolds`, administração de keys,
qualquer `*Logging` e `*Notifications`.

Três consequências, todas intencionais:

- **sem `readFiles`**, a VPS não consegue verificar o objeto remoto por download
  → a verificação profunda roda fora dela (GATE-6 e auditorias);
- **sem `readFiles`/`listFiles`**, a VPS não consegue perguntar se o objeto já
  existe → a idempotência usa um **marcador local** `<pacote>.uploaded`;
- **sem `deleteFiles`**, a VPS não consegue apagar nada remoto → a retenção
  off-host é executada por **lifecycle rule do bucket**, criada uma vez pelo
  humano, nunca pelo runtime.

Se a VPS for comprometida, o atacante pode subir lixo novo. Não pode ler e não
pode destruir o que já está lá.

### Restore — nunca na VPS

```
nome          facilpi-pilot-restore
bucket        facilpi-pilot-backup-x7k9p2
namePrefix    facilpi/
capabilities  listBuckets
              listFiles
              readFiles
              readFileRetentions
```

Sem nenhum `write*`, sem `deleteFiles`, sem `bypassGovernance`.

## Object Lock — Compliance é irreversível

O bucket está com Object Lock em **Compliance Mode**. Nesse modo a retenção
**não pode ser removida nem encurtada por ninguém** — nem pelo dono da conta,
nem com `bypassGovernance`. Só pode ser estendida. Lifecycle rule que tente
apagar objeto ainda travado **falha**.

Em termos práticos: **cada objeto travado custa armazenamento até expirar, sem
saída.** Um `365` digitado no lugar de `14` custa um ano.

Três barreiras contra isso:

1. teto de **31 dias** codificado em `ops/offhost_upload.sh`, não configurável;
2. `--dry-run` imprime o `retain_until` calculado, para conferência humana,
   antes de qualquer operação real;
3. a primeira prova contra o B2 usa **dados sintéticos e retenção de 1 dia** —
   um erro que desaparece sozinho em 24h.

### Retenção decidida

| Classe | Object Lock | Retenção |
|---|---|---|
| `daily` | COMPLIANCE, 14 dias | ≥ 14 dias |
| `weekly` | COMPLIANCE, 28 dias | ≥ 28 dias |

Lock e janela de retenção **precisam ser coerentes**: em Compliance Mode um
objeto travado por 14 dias não pode ser apagado no dia 7, então a política
escrita é piso, nunca teto. As classes vivem em prefixos separados
(`facilpi/daily/`, `facilpi/weekly/`) justamente para que a lifecycle rule possa
tratá-las com prazos diferentes.

## Integridade — o ETag não entra em lugar nenhum

O ETag do S3 não é SHA-256 e, em multipart, não é sequer um hash do conteúdo.

```
1. pacote            SHA256SUMS revalidado ANTES de cifrar        (fail closed)
2. artefato cifrado  sha256sum local do .tar.age
3. no PUT            --checksum-sha256: o servidor recomputa e recusa se divergir
4. metadata própria  sha256 gravado no objeto, independente do manifesto local
5. no download       confere o SHA-256 ANTES de decifrar
6. após extrair      SHA256SUMS interno reconferido
7. após restore      verificar_restauracao.py já compara documentos.arquivo_hash
```

Conferir o hash **antes** de decifrar separa "chegou corrompido" de "a chave
está errada" — dois problemas com respostas completamente diferentes no dia do
desastre.

**Se o B2 recusar `--checksum-sha256`:** o script para e imprime a evidência
para o GATE-3. Ele **não** cai para uma alternativa sozinho. Trocar a verificação
de integridade é mudança de arquitetura e exige decisão do Control Tower.

## Operação

```bash
# backup local (inalterado)
ops/backup.sh -p facilpi -e .env -d /var/backups/facilpi

# conferência antes de qualquer envio real — sem rede, sem credencial
ops/offhost_upload.sh -b /var/backups/facilpi/facilpi-backup-<UTC> \
    -e /etc/facilpi/offhost.env -c daily --dry-run

# envio
ops/offhost_upload.sh -b /var/backups/facilpi/facilpi-backup-<UTC> \
    -e /etc/facilpi/offhost.env -c daily

# retenção local — simulação é o padrão
ops/retencao_local.sh -d /var/backups/facilpi -k 7
ops/retencao_local.sh -d /var/backups/facilpi -k 7 --apply
```

### Agendamento (exemplo — não instalado; GATE-7)

```cron
# /etc/cron.d/facilpi-backup — na VPS, nunca na máquina do desenvolvedor
15 3 * * *  root  cd /opt/facilpi && ops/backup.sh -p facilpi -e .env -d /var/backups/facilpi >> /var/log/facilpi-backup.log 2>&1
45 3 * * *  root  cd /opt/facilpi && ops/offhost_upload.sh -b "$(ls -1d /var/backups/facilpi/facilpi-backup-* | tail -1)" -e /etc/facilpi/offhost.env -c daily >> /var/log/facilpi-offhost.log 2>&1
45 4 * * 0  root  cd /opt/facilpi && ops/offhost_upload.sh -b "$(ls -1d /var/backups/facilpi/facilpi-backup-* | tail -1)" -e /etc/facilpi/offhost.env -c weekly >> /var/log/facilpi-offhost.log 2>&1
30 5 * * *  root  cd /opt/facilpi && ops/retencao_local.sh -d /var/backups/facilpi -k 7 --apply >> /var/log/facilpi-retencao.log 2>&1
```

## Comportamento de falha

Fail closed em cada etapa: checksum do pacote, `AGE_RECIPIENT` ausente ou com
cara de chave privada, retenção acima do teto, falha do `age`, artefato acima do
limite de PUT único, erro no upload, ausência de `retain-until` na resposta.

Em qualquer uma delas: **sem marcador, sem sentinela, `exit` diferente de zero**,
e o artefato parcial é removido — mesma disciplina do `.parcial` em
`ops/backup.sh`. Nunca fica um artefato incompleto parecendo completo.

**Monitoração alarma pela ausência de sucesso recente**, não pela presença de
erro: o modo de falha real de backup é falhar em silêncio por semanas. A
sentinela `OFFHOST_SENTINELA` tem como `mtime` o último upload bem-sucedido.

```bash
# alarme se o último sucesso tiver mais de 26h
find /var/lib/facilpi/offhost-ultimo-sucesso -mmin +1560 -o ! -name '*' 2>/dev/null
```

## Recuperação a partir do off-host

**Fora da VPS**, com a credencial de restore e a chave privada `age`:

```bash
ops/offhost_fetch.sh \
    -k facilpi/daily/facilpi-backup-<UTC>.tar.age \
    -e /caminho/seguro/offhost-restore.env \
    -i /caminho/seguro/facilpi-age.key \
    -d /recuperacao

# entrega um pacote que o restore consome sem alteração
docker compose -p facilpi --env-file .env.novo up -d db
ops/restore.sh -p facilpi -e .env.novo -b /recuperacao/facilpi-backup-<UTC>
docker compose -p facilpi --env-file .env.novo up -d
```

`JWT_SECRET` **não** vem do backup: o ambiente novo recebe um segredo novo e
todas as sessões anteriores deixam de valer. É o ponto natural de revogação num
evento em que não se sabe o que aconteceu com o host perdido.

## Drill off-host (GATE-6)

Somente dados sintéticos. Reusa integralmente `ops/drill/popular_sintetico.py`,
`ops/drill/linha_de_base.py` e `ops/drill/verificar_restauracao.py`, e o
procedimento de ensaio de `docs/RUNBOOK_BACKUP_RESTORE.md`. O que o drill
off-host acrescenta:

1. cifrar e subir ao B2, confirmando objeto e retenção pela resposta do PUT;
2. **apagar a cópia local do pacote e do `.tar.age`** — sem isso o teste pode
   passar apoiado em estado sobrevivente, o mesmo erro que o ensaio local já
   evita destruindo a origem;
3. destruir o ambiente de origem (apenas objetos cujo label
   `com.docker.compose.project` seja exatamente o do ensaio, enumerados antes;
   nunca `docker system prune` ou `volume prune`);
4. recuperar **só** do B2, com a credencial de leitura e a chave privada trazida
   de fora;
5. restaurar em ambiente novo e rodar o verificador existente;
6. cronometrar e registrar o **RTO observado**.

Evidências: as 10 do ensaio local, mais

11. objeto presente com o `sha256` esperado na metadata;
12. retenção Compliance aplicada com o `retain_until` esperado;
13. `DeleteObject` com a credencial de **upload** falha;
14. `DeleteObject` com a credencial de **restore** falha;
15. recuperação feita sem nenhum artefato local sobrevivente;
16. RTO observado registrado — em host não representativo, portanto **não é SLA**.

## Gates

| Gate | Ação | Estado |
|---|---|---|
| GATE-1 | Gerar o par `age` e estabelecer as duas custódias | pendente |
| GATE-2 | Criar as duas Application Keys; confirmar região/endpoint | pendente |
| GATE-3 | Upload de prova, sintético, retenção **1 dia**; comprovar `--checksum-sha256` e a necessidade de `listBuckets` | pendente |
| GATE-4 | Fixar os prazos reais de retenção | **decidido**: 14d daily / 28d weekly |
| GATE-5 | Lifecycle rule e retenção padrão do bucket | pendente |
| GATE-6 | Drill off-host completo | pendente |
| GATE-7 | Construir `facilpi/offhost:1` na VPS; instalar cron e `/etc/facilpi/offhost.env`; garantir `age` no ambiente de recuperação | pendente |
| GATE-8 | Liberar dado real | **bloqueado** até o drill PASS |

```
REAL DATA = BLOCKED
```
