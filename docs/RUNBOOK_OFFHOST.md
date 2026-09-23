# Runbook — cópia off-host cifrada (Backblaze B2 + age)

> **Estado.** Upload sintético provado contra o B2 real e confirmado por
> verificação independente (Object Lock, metadata e SHA-256 do artefato —
> todos corretos). `REAL DATA = BLOCKED` continua até o drill completo
> (GATE-6) e o restante dos gates abaixo passarem.

O backup local (`docs/RUNBOOK_BACKUP_RESTORE.md`) protege contra perda do banco,
dos anexos ou de um container. **Não protege contra perda do host.** É isso que
esta cópia fecha.

## Desenho

**Sucesso do PUT não é sucesso final.** A resposta do PutObject da Backblaze
só documenta `VersionId` e `ETag` — ela nunca confirma Object Lock nem
checksum, tenham sido aplicados ou não. Exigir isso da própria resposta do PUT
foi um falso negativo já identificado e corrigido: a confirmação real é uma
etapa separada, com credencial separada, fora da VPS.

```
ops/backup.sh  →  facilpi-backup-<UTC>/          (inalterado, já validado)
                          │
                          ▼
ops/offhost_upload.sh     roda NA VPS — credencial write-only
   valida SHA256SUMS → tar → age -r <público> → SHA-256 do cifrado
   → PUT único no B2 com Object Lock no mesmo PUT
   → grava ESTADO PENDENTE (<pacote>.offhost_pending.json)
   → NÃO grava marcador de sucesso
                          │
                          ▼
ops/offhost_verify.sh     roda FORA DA VPS — credencial read-only, SEPARADA
   GetObjectRetention  → confirma Mode == COMPLIANCE e RetainUntilDate
   HeadObject          → confirma metadata e ContentLength
   GetObject (download)→ SHA-256 local == SHA-256 calculado antes do upload
   → só se as três passarem: marcador `.uploaded` + manifesto definitivo
                          │
                          ▼
ops/offhost_fetch.sh      roda FORA DA VPS
   download → confere SHA-256 → age -d → extrai → reconfere SHA256SUMS
                          │
                          ▼
ops/restore.sh            inalterado
```

O caminho de backup validado **não muda**. O off-host é um conjunto de scripts
que consome o pacote pronto: se qualquer um deles falhar, o backup local
continua íntegro e válido, e nenhum marcador de sucesso falso é gravado.

## Separação de custódia — a decisão que sustenta todo o resto

| Onde | O que existe lá | O que **não** pode existir lá |
|---|---|---|
| VPS | recipient `age` **público**; credencial de upload (só escreve) | chave privada `age`, **qualquer** credencial de leitura (verificação ou restore), Master Key |
| Cofre do responsável | chave privada `age`; credencial de verificação; credencial de restore | — |
| Cópia offline, outro local físico | segunda cópia da chave privada `age` | — |
| Bucket B2 | apenas artefatos cifrados | qualquer chave |
| Repositório | nada disso | qualquer segredo |

A credencial de **verificação** (`readFiles`+`readFileRetentions`, usada por
`ops/offhost_verify.sh`) e a credencial de **restore** (`listBuckets`,
`listFiles`, `readFiles`, `readFileRetentions`, usada por
`ops/offhost_fetch.sh`) são, por ora, credenciais **separadas** — a de
verificação é um subconjunto estrito da de restore, mas nenhuma automação as
unifica. Ambas seguem a mesma regra de localização: nunca na VPS. Se devem ou
não ser fundidas numa única credencial de Disaster Recovery é decisão futura,
não tomada aqui.

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

## Custódia do manifesto VERIFIED — o mapa do backup

A credencial de leitura **não tem `listFiles`**, e isso é decisão, não
esquecimento. A consequência precisa ser dita com todas as letras: a recuperação
encontra o objeto pela `remote_key` gravada no **manifesto VERIFIED**, e por mais
nada.

Se esse manifesto existir só no host de origem, uma perda **total** leva junto o
único mapa do backup. O objeto continua lá — íntegro, travado por Object Lock,
cobrando armazenamento — e ninguém sabe o nome dele.

Por isso `ops/offhost_verify.sh` aceita `OFFHOST_CUSTODIA`: o diretório do cofre
onde já vive a chave privada `age`. Ao promover PENDING → VERIFIED, o script
copia o manifesto para lá **antes** de gravar o marcador de sucesso, e **falha
fechado** se não conseguir — um backup que não poderá ser encontrado depois não é
um backup verificado.

| O que | Onde | Por quê |
|---|---|---|
| Chave privada `age` | cofre | decifra o artefato |
| Manifesto VERIFIED | **mesmo cofre** | diz *qual* artefato buscar e qual SHA-256 esperar |

Guardá-los juntos é deliberado: um sem o outro não recupera nada, então separá-los
criaria dois modos de falha em vez de um.

**Break-glass.** Numa perda total *sem* manifesto custodiado, a saída não é
conceder `listFiles` de forma permanente. É criar, **naquele momento**, uma
credencial de recuperação com a Master Key — que vive com o humano, não na
infraestrutura. O privilégio mínimo permanece no estado estacionário e a
recuperabilidade continua garantida.

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

`listBuckets`/`listAllBucketNames` **não** são concedidas — comprovado
empiricamente contra o B2 real (GATE-3P) que o `PutObject` executado por este
script funciona sem nenhuma das duas. A recomendação genérica da Backblaze de
concedê-las "para compatibilidade com SDKs" não se aplica ao caminho de código
exato que este script exercita.

Negadas por decisão: `deleteFiles`, `readFiles`, `listFiles`, `deleteBuckets`,
`writeBuckets`, `writeBucketRetentions`, `bypassGovernance`, `listAllBucketNames`,
`listBuckets`, `shareFiles`, `readFileLegalHolds`/`writeFileLegalHolds`,
administração de keys, qualquer `*Logging`, `*Notifications` e `*Replications`.

**Atenção ao criar esta key:** o preset **"Write Only" do console web da
Backblaze concede um conjunto bem mais amplo** do que a lista acima —
incluindo `deleteFiles`, `bypassGovernance` e mais seis capabilities de
administração de bucket — comprovado empiricamente criando duas keys distintas
por esse preset. Use sempre `b2_create_key` (API nativa) com a lista explícita.

Três consequências, todas intencionais:

- **sem `readFiles`**, a VPS não consegue verificar o objeto remoto por
  download → a verificação (`ops/offhost_verify.sh`) roda fora dela, com
  credencial separada, logo após cada upload — não só no drill;
- **sem `readFiles`/`listFiles`**, a VPS não consegue perguntar se o objeto já
  existe → a idempotência usa dois arquivos locais: `<pacote>.offhost_pending.json`
  (enviado, aguardando verificação) e `<pacote>.uploaded` (verificado de fato,
  escrito só por `ops/offhost_verify.sh`);
- **sem `deleteFiles`**, a VPS não consegue apagar nada remoto → a retenção
  off-host é executada por **lifecycle rule do bucket**, criada uma vez pelo
  humano, nunca pelo runtime.

Se a VPS for comprometida, o atacante pode subir lixo novo. Não pode ler e não
pode destruir o que já está lá.

### Verificação — nunca na VPS, roda logo após cada upload

```
nome          facilpi-pilot-backup-verify
bucket        facilpi-pilot-backup-x7k9p2   (restrita por bucketId)
capabilities  readFiles
              readFileRetentions
```

Usada exclusivamente por `ops/offhost_verify.sh`: `GetObjectRetention` (Object
Lock), `HeadObject` (metadata e tamanho) e `GetObject` (download para conferir
SHA-256). Sem nenhum `write*`, sem `deleteFiles`, sem `bypassGovernance`, sem
`listFiles`/`listBuckets` — o objeto a verificar já é conhecido pelo estado
pendente que o upload produziu, nenhuma enumeração é necessária.

Mesmo aviso do preset do console se aplica aqui: crie via `b2_create_key` com
a lista explícita, não pelo preset "Read Only".

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

Sem nenhum `write*`, sem `deleteFiles`, sem `bypassGovernance`. Superconjunto
da credencial de verificação acima — usada para recuperação de desastre, onde
a chave remota exata pode não ser conhecida de antemão.

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

A resposta do `PutObject` da Backblaze **não documenta** confirmação de
checksum nem de Object Lock — só `VersionId` e `ETag`. Exigir isso da própria
resposta do upload foi um falso negativo já identificado e corrigido: a
verificação real acontece **depois**, em `ops/offhost_verify.sh`, com uma
chamada dedicada por tipo de garantia.

```
1. pacote              SHA256SUMS revalidado ANTES de cifrar     (fail closed, upload)
2. artefato cifrado    sha256sum local do .tar.age                (upload)
3. no PUT              --checksum-sha256: o servidor recomputa e recusa se divergir (upload)
4. metadata própria    sha256 gravado no objeto                   (upload)
5. GetObjectRetention  confirma Mode e RetainUntilDate             (verify, credencial separada)
6. HeadObject          confirma metadata e ContentLength           (verify, credencial separada)
7. GetObject           download + SHA-256 local == SHA-256 do passo 2 (verify, credencial separada)
8. no download (fetch) confere o SHA-256 ANTES de decifrar         (restore)
9. após extrair        SHA256SUMS interno reconferido              (restore)
10. após restore       verificar_restauracao.py já compara documentos.arquivo_hash
```

Os passos 5-7 são o que transforma um upload **aceito** em um upload
**confirmado**: nenhum deles depende do que a resposta do PUT diz, e nenhum
usa a credencial de upload.

Conferir o hash **antes** de decifrar (passo 8) separa "chegou corrompido" de
"a chave está errada" — dois problemas com respostas completamente diferentes
no dia do desastre.

**Se o B2 recusar `--checksum-sha256`** no PUT (passo 3): o script para e
imprime a evidência. Ele **não** cai para uma alternativa sozinho. Trocar a
verificação de integridade é mudança de arquitetura e exige decisão do
Control Tower.

## Operação

```bash
# backup local (inalterado)
ops/backup.sh -p facilpi -e .env -d /var/backups/facilpi

# conferência antes de qualquer envio real — sem rede, sem credencial
ops/offhost_upload.sh -b /var/backups/facilpi/facilpi-backup-<UTC> \
    -e /etc/facilpi/offhost.env -c daily --dry-run

# envio — NA VPS, credencial write-only. Termina em PENDENTE, não em sucesso.
ops/offhost_upload.sh -b /var/backups/facilpi/facilpi-backup-<UTC> \
    -e /etc/facilpi/offhost.env -c daily

# verificação — FORA DA VPS, credencial read-only separada. So aqui o backup
# passa a contar como concluido (grava .uploaded e o manifesto definitivo).
ops/offhost_verify.sh \
    -p /var/backups/facilpi/facilpi-backup-<UTC>.offhost_pending.json \
    -e /caminho/seguro/offhost_verify.env

# retenção local — simulação é o padrão
ops/retencao_local.sh -d /var/backups/facilpi -k 7
ops/retencao_local.sh -d /var/backups/facilpi -k 7 --apply
```

`ops/offhost_verify.sh` roda em qualquer máquina fora da VPS que tenha Docker
e a credencial read-only — não precisa ser a mesma usada para restore, embora
possa usar as mesmas ferramentas (`facilpi/offhost:1`). O arquivo pendente
(`.offhost_pending.json`) precisa estar acessível a ela — copiá-lo para fora
da VPS é seguro: ele não contém nenhum segredo, só metadados do que verificar.

### Agendamento (exemplo — não instalado; GATE-7)

```cron
# /etc/cron.d/facilpi-backup — na VPS, nunca na máquina do desenvolvedor
15 3 * * *  root  cd /opt/facilpi && ops/backup.sh -p facilpi -e .env -d /var/backups/facilpi >> /var/log/facilpi-backup.log 2>&1
45 3 * * *  root  cd /opt/facilpi && ops/offhost_upload.sh -b "$(ls -1d /var/backups/facilpi/facilpi-backup-* | tail -1)" -e /etc/facilpi/offhost.env -c daily >> /var/log/facilpi-offhost.log 2>&1
45 4 * * 0  root  cd /opt/facilpi && ops/offhost_upload.sh -b "$(ls -1d /var/backups/facilpi/facilpi-backup-* | tail -1)" -e /etc/facilpi/offhost.env -c weekly >> /var/log/facilpi-offhost.log 2>&1
30 5 * * *  root  cd /opt/facilpi && ops/retencao_local.sh -d /var/backups/facilpi -k 7 --apply >> /var/log/facilpi-retencao.log 2>&1
```

Este crontab só cobre o **upload** — de propósito, é tudo que a VPS pode fazer.
A **verificação** (`ops/offhost_verify.sh`) não entra aqui: ela precisa da
credencial read-only, que esta máquina nunca deve ter. Seu agendamento, se
houver, vive num crontab separado, em outra máquina, fora do escopo deste
arquivo de exemplo.

## Comportamento de falha

**No upload**, fail closed em cada etapa: checksum do pacote, `AGE_RECIPIENT`
ausente ou com cara de chave privada, retenção acima do teto, falha do `age`,
artefato acima do limite de PUT único, erro no PUT. Em qualquer uma delas: nem
o pendente nem o marcador são gravados, `exit` diferente de zero, e o artefato
parcial é removido — mesma disciplina do `.parcial` em `ops/backup.sh`.

**Na verificação**, fail closed em cada checagem: `Mode` diferente de
`COMPLIANCE`, `RetainUntilDate` fora do instante solicitado, metadata
divergente, `ContentLength` divergente, SHA-256 do download diferente do
calculado antes do upload. Qualquer uma delas impede a gravação do marcador
`.uploaded` e do manifesto definitivo — o estado pendente permanece, disponível
para nova tentativa de verificação ou investigação.

Nunca fica um artefato incompleto, ou um upload não confirmado, parecendo
completo.

**Monitoração alarma pela ausência de sucesso recente**, não pela presença de
erro: o modo de falha real de backup é falhar em silêncio por semanas. A
sentinela `OFFHOST_SENTINELA` tem como `mtime` a **última verificação**
bem-sucedida — não o último upload. Um upload sem verificação correspondente
não deve silenciar o alarme; por isso a sentinela agora é responsabilidade de
`ops/offhost_verify.sh`, não mais de `ops/offhost_upload.sh`.

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

1. cifrar e subir ao B2 (`ops/offhost_upload.sh`), confirmando com
   `ops/offhost_verify.sh` — **não** pela resposta do PUT, que não confirma
   Object Lock nem checksum (ver seção Integridade);
2. **apagar a cópia local do pacote e do `.tar.age`** — sem isso o teste pode
   passar apoiado em estado sobrevivente, o mesmo erro que o ensaio local já
   evita destruindo a origem;
3. destruir o ambiente de origem (apenas objetos cujo label
   `com.docker.compose.project` seja exatamente o do ensaio, enumerados antes;
   nunca `docker system prune` ou `volume prune`);
4. recuperar **só** do B2, com a credencial de restore e a chave privada trazida
   de fora;
5. restaurar em ambiente novo e rodar o verificador existente;
6. cronometrar e registrar o **RTO observado**.

Evidências: as 10 do ensaio local, mais

11. `ops/offhost_verify.sh` confirma `state: VERIFIED` — Object Lock
    COMPLIANCE, metadata e SHA-256 do artefato baixado todos corretos;
12. retenção Compliance aplicada com o `retain_until` esperado;
13. `DeleteObject` com a credencial de **upload** falha;
14. `DeleteObject` com a credencial de **verificação** falha;
15. `DeleteObject` com a credencial de **restore** falha;
16. recuperação feita sem nenhum artefato local sobrevivente;
17. RTO observado registrado — em host não representativo, portanto **não é SLA**.

## Gates

| Gate | Ação | Estado |
|---|---|---|
| GATE-1 | Gerar o par `age` e estabelecer as duas custódias | pendente |
| GATE-2 | Criar as duas Application Keys; confirmar região/endpoint | pendente |
| GATE-3 | Upload de prova, sintético, retenção **1 dia**; comprovar `--checksum-sha256` e a necessidade de `listBuckets` | **feito**: PUT confirmado contra o B2 real; `listBuckets`/`listAllBucketNames` comprovadamente desnecessárias; verificação independente (`ops/offhost_verify.sh`) confirmou Object Lock COMPLIANCE, metadata e SHA-256 corretos |
| GATE-4 | Fixar os prazos reais de retenção | **decidido**: 14d daily / 28d weekly |
| GATE-5 | Lifecycle rule e retenção padrão do bucket | pendente |
| GATE-6 | Drill off-host completo | pendente |
| GATE-7 | Construir `facilpi/offhost:1` na VPS; instalar cron e `/etc/facilpi/offhost.env`; garantir `age` no ambiente de recuperação | pendente |
| GATE-8 | Liberar dado real | **bloqueado** até o drill PASS |

```
REAL DATA = BLOCKED
```
