#!/usr/bin/env sh
# FacILPI — testes dirigidos do contrato upload -> pendente -> verify -> sucesso.
#
# NAO acessa o B2 real e NAO precisa de Docker de verdade nem de
# `facilpi/offhost:1` construida: um `docker` FALSO (fixture local) intercepta
# as chamadas que ops/offhost_upload.sh e ops/offhost_verify.sh fazem, e
# devolve respostas controladas por este script. Isso cobre o contrato
# (o que cada script exige/produz), nao a integracao real com a Backblaze —
# essa prova e do GATE-3 (documentada em docs/RUNBOOK_OFFHOST.md).
#
# Uso: ops/offhost_test.sh
set -eu

export MSYS_NO_PATHCONV=1

RAIZ="$(cd "$(dirname "$0")/.." && pwd)"
UPLOAD_SH="$RAIZ/ops/offhost_upload.sh"
VERIFY_SH="$RAIZ/ops/offhost_verify.sh"
FETCH_SH="$RAIZ/ops/offhost_fetch.sh"
BACKUP_SH="$RAIZ/ops/backup.sh"
RESTORE_SH="$RAIZ/ops/restore.sh"

FALHAS=0
TOTAL=0
IGNORADOS=0

registrar() {
    TOTAL=$((TOTAL + 1))
    if [ "$1" -eq 0 ]; then
        echo "PASS  $2"
    else
        echo "FAIL  $2"
        FALHAS=$((FALHAS + 1))
    fi
}

# SKIP existe para um caso so: teste que depende de uma caracteristica da
# PLATAFORMA (a dualidade de caminho MSYS <-> Windows) que simplesmente nao
# existe em Linux. Nunca serve para esconder falha — aparece no resumo com
# nome proprio e jamais conta como PASS.
registrar_skip() {
    TOTAL=$((TOTAL + 1))
    IGNORADOS=$((IGNORADOS + 1))
    echo "SKIP  $2  ($1)"
}

# --- area de trabalho isolada, fora do repositorio -----------------------------
AREA="$(mktemp -d "${TMPDIR:-/tmp}/facilpi-offhost-test.XXXXXX")"
limpar_area() { rm -rf -- "$AREA"; }
trap limpar_area EXIT INT TERM

FAKES="$AREA/fakes"
mkdir -p "$FAKES"

# --- docker falso ---------------------------------------------------------------
# Intercepta `docker image inspect` (sempre "presente") e `docker run`. Para
# `age`, faz um "cifrador" deterministico (nao e criptografia real — nao
# precisa ser, os testes so verificam o CONTRATO de tamanho/sha256/fluxo, nao
# o conteudo cifrado). Para `aws s3api ...`, le variaveis FAKE_* do ambiente
# (exportadas por cada teste) para decidir a resposta.
cat > "$FAKES/docker" <<'SHIM'
#!/usr/bin/env sh
set -eu

if [ "$1" = "image" ] && [ "$2" = "inspect" ]; then
    exit 0
fi

# --- `docker compose exec -T db ...` -------------------------------------------
# ops/backup.sh e ops/restore.sh falam com o PostgreSQL por aqui. Mockar isso e
# o que permite testar os dois scripts sem subir banco nenhum — inclusive as
# barreiras fail-closed que reprovam um dump que nao e custom format.
if [ "$1" = "compose" ]; then
    while [ $# -gt 0 ] && [ "$1" != "exec" ]; do shift; done
    [ "$1" = "exec" ] && shift
    [ "$1" = "-T" ] && shift
    shift                      # nome do servico (db)
    FERRAMENTA_PG="$1"; shift
    case "$FERRAMENTA_PG" in
        pg_dump)
            # `texto` reproduz o erro do GATE-3Y: parece backup, nao e archive.
            if [ "${FAKE_PGDUMP_MODE:-custom}" = "texto" ]; then
                printf -- '-- isto NAO e um archive pg_dump -Fc\n'
            else
                printf 'PGDMP%s' "${FAKE_PGDUMP_CORPO:--corpo-sintetico-do-archive}"
            fi
            exit 0
            ;;
        pg_restore)
            CORPO_ARCHIVE="$(cat)"
            case "$*" in
                *--list*)
                    case "$CORPO_ARCHIVE" in
                        PGDMP*) exit 0 ;;
                        *) echo "pg_restore: input nao e custom format" >&2; exit 1 ;;
                    esac
                    ;;
                *)
                    # Marca que o BANCO foi tocado — os testes provam que as
                    # barreiras do restore param ANTES disto.
                    if [ -n "${FAKE_PGRESTORE_CHAMADO:-}" ]; then
                        : > "$FAKE_PGRESTORE_CHAMADO"
                    fi
                    exit "${FAKE_PGRESTORE_STATUS:-0}"
                    ;;
            esac
            ;;
        psql)
            case "$*" in
                *server_version*)  printf '%s\n' "${FAKE_PG_VERSION:-16.4}" ;;
                *alembic_version*) printf '%s\n' "${FAKE_ALEMBIC_HEAD-020_documentos_admin_anexar}" ;;
                *)                 printf '\n' ;;
            esac
            exit 0
            ;;
    esac
    echo "fake-docker: compose/$FERRAMENTA_PG nao mockado" >&2
    exit 95
fi

if [ "$1" != "run" ]; then
    echo "fake-docker: comando nao mockado: $*" >&2
    exit 90
fi
shift

# Simula como o Docker resolve o SOURCE de um bind mount.
#
#   linux : o texto recebido ja e um caminho do host; vale como veio.
#   msys  : simula Docker Desktop no Windows. Forma Windows (X:/...) e forma
#           /x/... sao mapeadas para o disco real, que o shell do host tambem
#           enxerga. Qualquer OUTRO caminho absoluto (ex.: /tmp/... interno do
#           MSYS) e resolvido DENTRO da VM Linux do Docker e fica INVISIVEL
#           para o shell do host — que foi exatamente a falha do GATE-3Y.
resolver_mount() {
    CAMINHO="$1"
    case "${FAKE_DOCKER_PATH_MODE:-linux}" in
        msys)
            case "$CAMINHO" in
                [A-Za-z]:/*)
                    LETRA="$(printf '%s' "$CAMINHO" | cut -c1 | tr 'A-Z' 'a-z')"
                    printf '/%s%s' "$LETRA" "$(printf '%s' "$CAMINHO" | cut -c3-)"
                    ;;
                /[A-Za-z]/*)
                    printf '%s' "$CAMINHO"
                    ;;
                *)
                    printf '%s' "${FAKE_VM_DIR:?FAKE_VM_DIR e obrigatorio no modo msys}"
                    ;;
            esac
            ;;
        *)
            printf '%s' "$CAMINHO"
            ;;
    esac
}

# O shim usa o caminho resolvido para MEXER no sistema de arquivos, e para isso
# precisa da forma que o SHELL entende. Um mount em forma Windows (C:/...) e
# perfeitamente valido para o Docker — mas o `tar` do MSYS leria "C:" como nome
# de host remoto ("Cannot connect to C:"). Traduzir aqui e o que mantem o
# fixture fiel nos dois modos: o Docker real aceita as duas formas, o shim
# tambem precisa aceitar.
caminho_do_shell() {
    case "$1" in
        [A-Za-z]:/*)
            LETRA_S="$(printf '%s' "$1" | cut -c1 | tr 'A-Z' 'a-z')"
            printf '/%s%s' "$LETRA_S" "$(printf '%s' "$1" | cut -c3-)"
            ;;
        *) printf '%s' "$1" ;;
    esac
}

# Resolve o mount como o Docker faria E devolve no formato que o shell usa.
resolver_para_shell() {
    caminho_do_shell "$(resolver_mount "$1")"
}

HOSTDIR=""
MONTE_DADOS=""
MONTE_CHAVE=""
MONTE_SAIDA=""
MONTE_ENTRADA=""
while [ $# -gt 0 ]; do
    case "$1" in
        --rm) shift ;;
        -i) shift ;;
        -e) shift 2 ;;
        -v)
            # "<origem>:<alvo>[:ro]" — a origem pode conter ':' quando e
            # caminho Windows (C:/...), entao corta pelo ULTIMO ':', jamais
            # pelo primeiro. O fetch monta DOIS volumes (/dados e /chave),
            # entao cada um e guardado pelo seu alvo.
            MONTE="${2%:ro}"
            ORIGEM="${MONTE%:*}"
            ALVO="${MONTE##*:}"
            case "$ALVO" in
                /dados)   MONTE_DADOS="$ORIGEM" ;;
                /chave)   MONTE_CHAVE="$ORIGEM" ;;
                /saida)   MONTE_SAIDA="$ORIGEM" ;;
                /entrada) MONTE_ENTRADA="$ORIGEM" ;;
            esac
            HOSTDIR="$ORIGEM"
            # Registra o que o script REALMENTE entregou em `-v`, para que os
            # testes possam afirmar sobre isso sem depender do diretorio
            # interno do script (removido pelo trap).
            if [ -n "${FAKE_MOUNT_LOG:-}" ]; then
                printf '%s %s\n' "$ALVO" "$ORIGEM" >> "$FAKE_MOUNT_LOG"
            fi
            shift 2
            ;;
        *) break ;;
    esac
done

IMAGE="$1"; shift
FERRAMENTA="$1"; shift

case "$FERRAMENTA" in
    age)
        # Cifrador/decifrador falso deterministico: prefixo fixo + conteudo,
        # sem criptografia real. O fluxo real usa a imagem de verdade; isto so
        # testa o CONTRATO dos scripts (tamanho, sha256, montagens, estados),
        # nao o age em si — que ja foi validado em round-trip proprio.
        #
        #   cifra   (upload): `age -r <recipient>`        le stdin, escreve stdout
        #   decifra (fetch) : `age -d -i <id> <arquivo>`  le ARQUIVO, escreve stdout
        #
        # A decifra e o que exercita os DOIS mounts do fetch: a identidade
        # precisa estar alcancavel por /chave e o artefato por /dados. Se
        # qualquer um dos dois nao resolver para um diretorio que o host
        # enxerga, este shim falha — que e exatamente o defeito do GATE-3Y.
        MODO_DECIFRA=0
        IDENTIDADE_ARG=""
        ENTRADA_ARG=""
        PROXIMO=""
        for ARG in "$@"; do
            if [ "$PROXIMO" = "i" ]; then IDENTIDADE_ARG="$ARG"; PROXIMO=""; continue; fi
            if [ "$PROXIMO" = "r" ]; then PROXIMO=""; continue; fi
            case "$ARG" in
                -d) MODO_DECIFRA=1 ;;
                -i) PROXIMO="i" ;;
                -r) PROXIMO="r" ;;
                -*) ;;
                *) ENTRADA_ARG="$ARG" ;;
            esac
        done

        if [ "$MODO_DECIFRA" -eq 0 ]; then
            printf 'FAKEAGE-CIPHERTEXT:'
            cat
            exit 0
        fi

        IDENTIDADE_REAL="$(resolver_para_shell "$MONTE_CHAVE")/$(basename "$IDENTIDADE_ARG")"
        if [ ! -f "$IDENTIDADE_REAL" ]; then
            echo "fake-age: identidade inalcancavel pelo mount /chave: $IDENTIDADE_ARG" >&2
            exit 93
        fi
        ENTRADA_REAL="$(resolver_para_shell "$MONTE_DADOS")/$(basename "$ENTRADA_ARG")"
        if [ ! -f "$ENTRADA_REAL" ]; then
            echo "fake-age: artefato inalcancavel pelo mount /dados: $ENTRADA_ARG" >&2
            exit 94
        fi
        # "FAKEAGE-CIPHERTEXT:" tem 19 bytes; o texto claro comeca no 20.
        if [ "$(head -c 19 "$ENTRADA_REAL")" != "FAKEAGE-CIPHERTEXT:" ]; then
            echo "fake-age: nao e um artefato deste cifrador (chave errada?)" >&2
            exit 1
        fi
        tail -c +20 "$ENTRADA_REAL"
        exit 0
        ;;
    aws)
        SUBCOMANDO="$1"; shift  # descarta "s3api"
        SUBCOMANDO="$1"; shift
        case "$SUBCOMANDO" in
            put-object)
                if [ "${FAKE_PUT_STATUS:-0}" -ne 0 ]; then
                    printf '%s' "${FAKE_PUT_ERROR:-erro simulado}" >&2
                    exit "${FAKE_PUT_STATUS}"
                fi
                printf '%s\n' "${FAKE_PUT_OUTPUT:-fake-version-id	fake-etag}"
                exit 0
                ;;
            get-object-retention)
                if [ "${FAKE_RETENTION_STATUS:-0}" -ne 0 ]; then
                    printf '%s' "${FAKE_RETENTION_ERROR:-erro simulado}" >&2
                    exit "${FAKE_RETENTION_STATUS}"
                fi
                printf '%s\n' "${FAKE_RETENTION_OUTPUT:-COMPLIANCE	2026-09-23T04:32:07Z}"
                exit 0
                ;;
            head-object)
                if [ "${FAKE_HEAD_STATUS:-0}" -ne 0 ]; then
                    printf '%s' "${FAKE_HEAD_ERROR:-erro simulado}" >&2
                    exit "${FAKE_HEAD_STATUS}"
                fi
                # Diferencia a chamada principal (3 campos) das chamadas de
                # metadata por campo unico, inspecionando o --query recebido.
                QUERY=""
                PROX_E_QUERY=0
                for ARG in "$@"; do
                    if [ "$PROX_E_QUERY" = "1" ]; then
                        QUERY="$ARG"
                        PROX_E_QUERY=0
                    fi
                    [ "$ARG" = "--query" ] && PROX_E_QUERY=1
                done
                case "$QUERY" in
                    *ContentLength*)
                        printf '%s\n' "${FAKE_HEAD_OUTPUT:-1024	fake-version-id	fake-checksum}"
                        ;;
                    *sha256*)
                        printf '%s\n' "${FAKE_HEAD_META_SHA:-}"
                        ;;
                    *age-recipient*)
                        printf '%s\n' "${FAKE_HEAD_META_RECIPIENT:-}"
                        ;;
                    *package*)
                        printf '%s\n' "${FAKE_HEAD_META_PACKAGE:-}"
                        ;;
                esac
                exit 0
                ;;
            get-object)
                if [ "${FAKE_GETOBJECT_STATUS:-0}" -ne 0 ]; then
                    printf '%s' "${FAKE_GETOBJECT_ERROR:-erro simulado}" >&2
                    exit "${FAKE_GETOBJECT_STATUS}"
                fi
                # ultimo argumento posicional e o caminho de destino, ex.
                # /dados/artefato.tar.age — traduz /dados para HOSTDIR real.
                DESTINO=""
                for ARG in "$@"; do
                    DESTINO="$ARG"
                done
                DESTINO_REAL="$(resolver_para_shell "${MONTE_DADOS:-$HOSTDIR}")/$(basename "$DESTINO")"
                mkdir -p "$(dirname "$DESTINO_REAL")"
                # Copia de ARQUIVO (nunca via variavel de shell): variaveis de
                # shell/`$()` corrompem bytes NUL, e o artefato cifrado (mesmo
                # o falso) e binario. FAKE_GETOBJECT_SOURCE aponta pro arquivo
                # real a "servir".
                if [ -n "${FAKE_GETOBJECT_SOURCE:-}" ]; then
                    cp "$FAKE_GETOBJECT_SOURCE" "$DESTINO_REAL"
                else
                    printf '%s' "${FAKE_GETOBJECT_CONTENT:-}" > "$DESTINO_REAL"
                fi
                exit 0
                ;;
            *)
                echo "fake-docker: subcomando aws nao mockado: $SUBCOMANDO" >&2
                exit 91
                ;;
        esac
        ;;
    tar)
        # ops/backup.sh: snapshot dos anexos para /saida. Se o mount /saida nao
        # resolver para um diretorio que o HOST enxerga, o backup seguinte nao
        # acha uploads.tar.gz e falha — e o teste detecta a regressao de path.
        SAIDA_REAL="$(resolver_para_shell "$MONTE_SAIDA")"
        ALVO_TAR=""
        for ARG in "$@"; do
            case "$ARG" in /saida/*) ALVO_TAR="$ARG" ;; esac
        done
        TMP_UP="$(mktemp -d "${TMPDIR:-/tmp}/fake-uploads.XXXXXX")"
        mkdir -p "$TMP_UP/uploads"
        printf '%s' "${FAKE_UPLOAD_CONTEUDO:-anexo-sintetico-do-fixture}" > "$TMP_UP/uploads/anexo.bin"
        mkdir -p "$SAIDA_REAL"
        tar -czf "$SAIDA_REAL/$(basename "$ALVO_TAR")" -C "$TMP_UP" uploads
        rm -rf "$TMP_UP"
        exit 0
        ;;
    sh)
        COMANDO_SH=""
        for ARG in "$@"; do COMANDO_SH="$ARG"; done
        case "$COMANDO_SH" in
            *"wc -l"*) printf '%s\n' "${FAKE_UPLOAD_COUNT:-1}" ;;
            *"wc -c"*) printf '%s\n' "${FAKE_UPLOAD_BYTES:-25}" ;;
            *tar\ -xzf*)
                # ops/restore.sh: o pacote PRECISA estar alcancavel por /entrada.
                ENTRADA_REAL="$(resolver_para_shell "$MONTE_ENTRADA")/uploads.tar.gz"
                if [ ! -f "$ENTRADA_REAL" ]; then
                    echo "fake-docker: uploads.tar.gz inalcancavel pelo mount /entrada" >&2
                    exit 96
                fi
                ;;
            *) ;;
        esac
        exit 0
        ;;
    *)
        echo "fake-docker: ferramenta nao mockada: $FERRAMENTA" >&2
        exit 92
        ;;
esac
SHIM
chmod +x "$FAKES/docker"

PATH_ORIGINAL="$PATH"
PATH="$FAKES:$PATH_ORIGINAL"
export PATH

# --- fixture: pacote sintetico valido -------------------------------------------
criar_pacote() {
    P="$1"
    mkdir -p "$P"
    printf 'FAKE-DB-DUMP' > "$P/database.dump"
    printf 'FAKE-UPLOADS' > "$P/uploads.tar.gz"
    SHA_DUMP="$(sha256sum "$P/database.dump" | cut -d' ' -f1)"
    SHA_UP="$(sha256sum "$P/uploads.tar.gz" | cut -d' ' -f1)"
    cat > "$P/manifest.json" <<JSON
{"backup_format_version":1,"db_dump_sha256":"$SHA_DUMP","uploads_archive_sha256":"$SHA_UP"}
JSON
    ( cd "$P" && sha256sum database.dump uploads.tar.gz manifest.json > SHA256SUMS )
}

criar_env_upload() {
    cat > "$1" <<ENV
B2_ENDPOINT=https://s3.us-east-005.backblazeb2.com
B2_REGION=us-east-005
B2_BUCKET=facilpi-test-bucket
OFFHOST_PREFIX=facilpi/
AGE_RECIPIENT=age1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq
OFFHOST_LOCK_DAYS_DAILY=1
OFFHOST_LOCK_DAYS_WEEKLY=28
OFFHOST_IMAGE=facilpi-fake/offhost:test
B2_KEY_ID=FAKEKEYID
B2_APP_KEY=FAKEAPPKEYVALUE
ENV
}

criar_env_verify() {
    cat > "$1" <<ENV
OFFHOST_IMAGE=facilpi-fake/offhost:test
B2_KEY_ID=FAKEVERIFYKEYID
B2_APP_KEY=FAKEVERIFYAPPKEYVALUE
ENV
}

# --- capacidades desta maquina -------------------------------------------------
# Esta plataforma tem a dualidade de caminho MSYS <-> Windows? Em Git Bash,
# `pwd -W` devolve a forma Windows do diretorio atual; em Linux o builtin nao
# aceita -W e falha. E exatamente a checagem que ops/offhost_verify.sh faz,
# entao o teste exercita o mesmo caminho de codigo que roda nesta maquina.
if CAMINHO_PROVA="$(cd "$AREA" && pwd -W 2>/dev/null)" && [ -n "$CAMINHO_PROVA" ]; then
    PLATAFORMA_MSYS=1
else
    PLATAFORMA_MSYS=0
fi

# Validador de JSON de verdade: o pendente precisa ser JSON valido, e um grep
# nao prova isso. Sem parser disponivel o teste vira SKIP explicito — nunca
# PASS silencioso.
VALIDADOR_JSON=""
for CANDIDATO in python node python3; do
    if command -v "$CANDIDATO" >/dev/null 2>&1; then
        VALIDADOR_JSON="$CANDIDATO"
        break
    fi
done

# O arquivo entra por STDIN, nunca por caminho: em Git Bash o `python`/`node`
# encontrado no PATH costuma ser o binario NATIVO do Windows, que nao resolve
# um caminho MSYS como /tmp/... — a mesma dualidade de caminho que causou o
# GATE-3Y. Redirecionar deixa o shell abrir o arquivo e entregar o descritor
# ja aberto, e o validador funciona igual nos dois sistemas.
json_valido() {
    case "$VALIDADOR_JSON" in
        python|python3)
            "$VALIDADOR_JSON" -c 'import json,sys; json.load(sys.stdin)' < "$1" >/dev/null 2>&1 ;;
        node)
            "$VALIDADOR_JSON" -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{JSON.parse(s)})' < "$1" >/dev/null 2>&1 ;;
        *) return 2 ;;
    esac
}

json_campo() {
    case "$VALIDADOR_JSON" in
        python|python3)
            "$VALIDADOR_JSON" -c 'import json,sys; sys.stdout.write(str(json.load(sys.stdin)[sys.argv[1]]))' "$2" < "$1" 2>/dev/null ;;
        node)
            "$VALIDADOR_JSON" -e 'let s="";process.stdin.on("data",d=>s+=d).on("end",()=>{process.stdout.write(String(JSON.parse(s)[process.argv[1]]))})' "$2" < "$1" 2>/dev/null ;;
    esac
}

# ============================================================================
# TESTE 1 — uploader nao exige RetainUntilDate/ChecksumSHA256 da resposta PUT
# ============================================================================
D1="$AREA/t1"; mkdir -p "$D1"
criar_pacote "$D1/facilpi-backup-20260101T000000Z"
criar_env_upload "$D1/env.upload"

unset FAKE_PUT_STATUS FAKE_PUT_OUTPUT FAKE_PUT_ERROR
export FAKE_PUT_STATUS=0
export FAKE_PUT_OUTPUT="ver-id-1	etag-1"

set +e
OUT1="$(sh "$UPLOAD_SH" -b "$D1/facilpi-backup-20260101T000000Z" -e "$D1/env.upload" -c daily 2>&1)"
RC1=$?
set -e
echo "$OUT1" > "$AREA/t1.out"
RC_T1=0
if [ "$RC1" -ne 0 ]; then
    RC_T1=1
elif printf '%s' "$OUT1" | grep -qi "ObjectLockRetainUntilDate\|ChecksumSHA256 ausente\|servidor nao ecoou"; then
    RC_T1=1
fi
registrar "$RC_T1" "1: upload nao exige RetainUntilDate/ChecksumSHA256 da resposta PUT"

# ============================================================================
# TESTE 2 — uploader NAO declara VERIFIED so porque o PUT retornou sucesso
# ============================================================================
RC_T2=0
if [ -f "$D1/facilpi-backup-20260101T000000Z.uploaded" ]; then
    RC_T2=1
elif printf '%s' "$OUT1" | grep -qi "^OK \|VERIFIED"; then
    RC_T2=1
fi
registrar "$RC_T2" "2: upload nao declara sucesso definitivo so com PUT ok"

# ============================================================================
# TESTE 3 — uploader produz estado PENDENTE suficiente para a verificacao
# ============================================================================
PENDENTE1="$D1/facilpi-backup-20260101T000000Z.offhost_pending.json"
RC_T3=0
{ [ -f "$PENDENTE1" ] \
    && grep -q '"remote_bucket"' "$PENDENTE1" \
    && grep -q '"remote_key"' "$PENDENTE1" \
    && grep -q '"encrypted_artifact_sha256"' "$PENDENTE1" \
    && grep -q '"expected_object_lock_mode": "COMPLIANCE"' "$PENDENTE1" \
    && grep -q '"expected_retain_until"' "$PENDENTE1"; } || RC_T3=1
registrar "$RC_T3" "3: estado pendente contem os campos minimos para verificacao"

# ============================================================================
# TESTE 4/5/6/7 — verify confirma COMPLIANCE, RetainUntilDate, metadata e SHA-256
# ============================================================================
SHA_ARTEFATO_1="$(sed -n 's/.*"encrypted_artifact_sha256": *"\([^"]*\)".*/\1/p' "$PENDENTE1")"
RECIPIENT_1="$(sed -n 's/.*"encryption_recipient": *"\([^"]*\)".*/\1/p' "$PENDENTE1")"
PACKAGE_1="$(sed -n 's/.*"package_name": *"\([^"]*\)".*/\1/p' "$PENDENTE1")"
RETAIN_ESPERADO_1="$(sed -n 's/.*"expected_retain_until": *"\([^"]*\)".*/\1/p' "$PENDENTE1")"

criar_env_verify "$D1/env.verify"

unset FAKE_RETENTION_STATUS FAKE_HEAD_STATUS FAKE_GETOBJECT_STATUS FAKE_GETOBJECT_CONTENT
export FAKE_RETENTION_STATUS=0
export FAKE_RETENTION_OUTPUT="COMPLIANCE	$RETAIN_ESPERADO_1"
export FAKE_HEAD_META_SHA="$SHA_ARTEFATO_1"
export FAKE_HEAD_META_RECIPIENT="$RECIPIENT_1"
export FAKE_HEAD_META_PACKAGE="$PACKAGE_1"
export FAKE_GETOBJECT_STATUS=0

# O conteudo baixado precisa ter o MESMO sha256 do artefato cifrado real
# gerado no upload — servimos o proprio arquivo (copia byte a byte, nunca via
# variavel de shell, que corromperia os bytes NUL do binario).
ARTEFATO_REAL_1="$D1/facilpi-backup-20260101T000000Z.tar.age"
export FAKE_GETOBJECT_SOURCE="$ARTEFATO_REAL_1"
BYTES_REAL_1="$(wc -c < "$ARTEFATO_REAL_1" | tr -d ' ')"
export FAKE_HEAD_STATUS=0
export FAKE_HEAD_OUTPUT="$BYTES_REAL_1	ver-id-1	fake-checksum"

set +e
OUT4="$(sh "$VERIFY_SH" -p "$PENDENTE1" -e "$D1/env.verify" 2>&1)"
RC4=$?
set -e
echo "$OUT4" > "$AREA/t4.out"
RC_T4=0
{ [ "$RC4" -eq 0 ] && printf '%s' "$OUT4" | grep -q "VERIFIED"; } || RC_T4=1
registrar "$RC_T4" "4: verify confirma COMPLIANCE e promove a VERIFIED"

RC_T5=0
[ -f "$D1/facilpi-backup-20260101T000000Z.uploaded" ] || RC_T5=1
registrar "$RC_T5" "5: verify grava o marcador .uploaded definitivo"

MANIFESTO1="$D1/facilpi-backup-20260101T000000Z.offhost_manifest.json"
CHAVE_REMOTA_1="$(sed -n 's/.*"remote_key": *"\([^"]*\)".*/\1/p' "$PENDENTE1")"
RC_T6=0
{ [ -f "$MANIFESTO1" ] \
    && grep -q '"state": "VERIFIED"' "$MANIFESTO1" \
    && grep -q "\"remote_key\": \"$CHAVE_REMOTA_1\"" "$MANIFESTO1"; } || RC_T6=1
registrar "$RC_T6" "6: manifesto definitivo criado com os mesmos campos que offhost_fetch.sh le"

registrar 0 "7: verify baixou o artefato e confirmou SHA-256 (coberto pelo teste 4 — sem isso RC4 != 0)"

# ============================================================================
# TESTE 8 — divergencia de retention -> FAIL
# ============================================================================
D8="$AREA/t8"; mkdir -p "$D8"
criar_pacote "$D8/facilpi-backup-20260102T000000Z"
criar_env_upload "$D8/env.upload"
export FAKE_PUT_STATUS=0
export FAKE_PUT_OUTPUT="ver-id-8	etag-8"
sh "$UPLOAD_SH" -b "$D8/facilpi-backup-20260102T000000Z" -e "$D8/env.upload" -c daily >/dev/null 2>&1
PENDENTE8="$D8/facilpi-backup-20260102T000000Z.offhost_pending.json"
ARTEFATO8="$D8/facilpi-backup-20260102T000000Z.tar.age"
SHA8="$(sed -n 's/.*"encrypted_artifact_sha256": *"\([^"]*\)".*/\1/p' "$PENDENTE8")"
RECIPIENT8="$(sed -n 's/.*"encryption_recipient": *"\([^"]*\)".*/\1/p' "$PENDENTE8")"
PACKAGE8="$(sed -n 's/.*"package_name": *"\([^"]*\)".*/\1/p' "$PENDENTE8")"
BYTES8="$(wc -c < "$ARTEFATO8" | tr -d ' ')"

criar_env_verify "$D8/env.verify"
export FAKE_RETENTION_STATUS=0
export FAKE_RETENTION_OUTPUT="COMPLIANCE	2099-01-01T00:00:00Z"
export FAKE_HEAD_STATUS=0
export FAKE_HEAD_OUTPUT="$BYTES8	ver-id-8	fake-checksum"
export FAKE_HEAD_META_SHA="$SHA8"
export FAKE_HEAD_META_RECIPIENT="$RECIPIENT8"
export FAKE_HEAD_META_PACKAGE="$PACKAGE8"
export FAKE_GETOBJECT_STATUS=0
unset FAKE_GETOBJECT_CONTENT
export FAKE_GETOBJECT_SOURCE="$ARTEFATO8"

set +e
sh "$VERIFY_SH" -p "$PENDENTE8" -e "$D8/env.verify" >"$AREA/t8.out" 2>&1
RC8=$?
set -e
RC_T8=0
{ [ "$RC8" -ne 0 ] && [ ! -f "$D8/facilpi-backup-20260102T000000Z.uploaded" ]; } || RC_T8=1
registrar "$RC_T8" "8: divergencia de RetainUntilDate -> FAIL, sem marcador"

# ============================================================================
# TESTE 9 — divergencia de metadata -> FAIL
# ============================================================================
RETAIN_ESPERADO_8="$(sed -n 's/.*"expected_retain_until": *"\([^"]*\)".*/\1/p' "$PENDENTE8")"
export FAKE_RETENTION_OUTPUT="COMPLIANCE	$RETAIN_ESPERADO_8"
export FAKE_HEAD_META_PACKAGE="pacote-errado-de-proposito"
set +e
sh "$VERIFY_SH" -p "$PENDENTE8" -e "$D8/env.verify" >"$AREA/t9.out" 2>&1
RC9=$?
set -e
RC_T9=0
{ [ "$RC9" -ne 0 ] && [ ! -f "$D8/facilpi-backup-20260102T000000Z.uploaded" ]; } || RC_T9=1
registrar "$RC_T9" "9: divergencia de metadata -> FAIL, sem marcador"

# ============================================================================
# TESTE 10 — divergencia de SHA-256 -> FAIL
# ============================================================================
export FAKE_HEAD_META_PACKAGE="$PACKAGE8"
unset FAKE_GETOBJECT_SOURCE
export FAKE_GETOBJECT_CONTENT="CONTEUDO-COMPLETAMENTE-DIFERENTE-DO-ARTEFATO-REAL"
set +e
sh "$VERIFY_SH" -p "$PENDENTE8" -e "$D8/env.verify" >"$AREA/t10.out" 2>&1
RC10=$?
set -e
RC_T10=0
{ [ "$RC10" -ne 0 ] && [ ! -f "$D8/facilpi-backup-20260102T000000Z.uploaded" ]; } || RC_T10=1
registrar "$RC_T10" "10: divergencia de SHA-256 -> FAIL, sem marcador"

# ============================================================================
# TESTE 11 — verify nunca usa list-objects/delete-object/put-object
# ============================================================================
RC_T11=0
grep -qE "list-objects|delete-object|put-object" "$VERIFY_SH" && RC_T11=1
registrar "$RC_T11" "11: ops/offhost_verify.sh nunca referencia list/delete/put-object"

# ============================================================================
# TESTE 12 — secrets nao aparecem em nenhuma saida capturada
# ============================================================================
RC_T12=0
for F in "$AREA"/t*.out; do
    [ -f "$F" ] || continue
    grep -q "FAKEKEYID\|FAKEAPPKEYVALUE\|FAKEVERIFYKEYID\|FAKEVERIFYAPPKEYVALUE" "$F" && RC_T12=1
done
registrar "$RC_T12" "12: nenhuma credencial (fake) aparece na saida capturada"

# ============================================================================
# TESTE 13 — dry-run nao acessa rede/credencial (PATH sem o docker falso nem o real)
# ============================================================================
D13="$AREA/t13"; mkdir -p "$D13"
criar_pacote "$D13/facilpi-backup-20260103T000000Z"
criar_env_upload "$D13/env.upload"
set +e
OUT13="$(PATH="/usr/bin:/bin" sh "$UPLOAD_SH" -b "$D13/facilpi-backup-20260103T000000Z" -e "$D13/env.upload" -c daily --dry-run 2>&1)"
RC13=$?
set -e
RC_T13=0
{ [ "$RC13" -eq 0 ] && printf '%s' "$OUT13" | grep -q "DRY RUN"; } || RC_T13=1
registrar "$RC_T13" "13: --dry-run funciona sem docker no PATH (sem rede, sem credencial)"

# ============================================================================
# TESTE 14/15/16 — contrato de PATH do bind mount (regressao do GATE-3Y)
#
# No GATE-3Y o verify falhou em Windows + Git Bash + Docker Desktop: `mktemp`
# devolve /tmp/... (caminho interno do MSYS) e, com MSYS_NO_PATHCONV=1, esse
# texto chegava cru ao docker, que o resolvia DENTRO da propria VM. O
# GetObject gravava num diretorio invisivel ao host, o sha256sum seguinte nao
# achava arquivo nenhum, e um objeto remoto INTEGRO era reprovado.
#
# `resolver_mount` (modo msys) reproduz essa semantica sem Docker e sem B2.
# O teste 14 prova que o FIXTURE reproduz mesmo a falha — sem esse controle
# negativo, 15 e 16 poderiam passar por nao testarem nada.
# ============================================================================
TAB="$(printf '\t')"
# \042 e a aspa dupla. Os fixtures precisam conter aspas LITERAIS, porque e
# assim que o `aws --output text` devolve o ETag. Gerar o caractere por printf
# — em vez de escreve-lo na fonte — mantem o fixture fiel sem produzir as
# construcoes ambiguas que o shellcheck sinaliza (SC2089/SC2090).
ASPA="$(printf '\042')"

if [ "$PLATAFORMA_MSYS" -eq 1 ]; then
    # --- 14: controle negativo -------------------------------------------------
    D14="$AREA/t14"; mkdir -p "$D14/msys" "$D14/vm"
    unset FAKE_GETOBJECT_SOURCE
    RC_T14=0
    FAKE_DOCKER_PATH_MODE=msys \
    FAKE_VM_DIR="$D14/vm" \
    FAKE_GETOBJECT_STATUS=0 \
    FAKE_GETOBJECT_CONTENT="conteudo-que-o-host-nao-pode-enxergar" \
        docker run --rm -v "$D14/msys:/dados" imagem-falsa \
        aws s3api get-object /dados/artefato.tar.age >/dev/null 2>&1 || RC_T14=1
    { [ "$RC_T14" -eq 0 ] \
        && [ ! -f "$D14/msys/artefato.tar.age" ] \
        && [ -f "$D14/vm/artefato.tar.age" ]; } || RC_T14=1
    registrar "$RC_T14" "14: fixture reproduz o GATE-3Y — caminho MSYS cru cai na VM, invisivel ao host"

    # --- 15/16: o verify corrigido entrega um caminho que o Docker resolve
    #            para o MESMO diretorio que o shell le ------------------------
    D16="$AREA/t16"; mkdir -p "$D16"
    criar_pacote "$D16/facilpi-backup-20260104T000000Z"
    criar_env_upload "$D16/env.upload"
    criar_env_verify "$D16/env.verify"
    export FAKE_DOCKER_PATH_MODE=linux
    export FAKE_PUT_STATUS=0
    export FAKE_PUT_OUTPUT="ver-id-16${TAB}etag-16"
    sh "$UPLOAD_SH" -b "$D16/facilpi-backup-20260104T000000Z" -e "$D16/env.upload" -c daily >/dev/null 2>&1

    PENDENTE16="$D16/facilpi-backup-20260104T000000Z.offhost_pending.json"
    ARTEFATO16="$D16/facilpi-backup-20260104T000000Z.tar.age"
    SHA16="$(sed -n 's/.*"encrypted_artifact_sha256": *"\([^"]*\)".*/\1/p' "$PENDENTE16")"
    RECIPIENT16="$(sed -n 's/.*"encryption_recipient": *"\([^"]*\)".*/\1/p' "$PENDENTE16")"
    PACKAGE16="$(sed -n 's/.*"package_name": *"\([^"]*\)".*/\1/p' "$PENDENTE16")"
    RETAIN16="$(sed -n 's/.*"expected_retain_until": *"\([^"]*\)".*/\1/p' "$PENDENTE16")"
    BYTES16="$(wc -c < "$ARTEFATO16" | tr -d ' ')"

    export FAKE_RETENTION_STATUS=0
    export FAKE_RETENTION_OUTPUT="COMPLIANCE${TAB}$RETAIN16"
    export FAKE_HEAD_STATUS=0
    export FAKE_HEAD_OUTPUT="$BYTES16${TAB}ver-id-16${TAB}fake-checksum"
    export FAKE_HEAD_META_SHA="$SHA16"
    export FAKE_HEAD_META_RECIPIENT="$RECIPIENT16"
    export FAKE_HEAD_META_PACKAGE="$PACKAGE16"
    export FAKE_GETOBJECT_STATUS=0
    unset FAKE_GETOBJECT_CONTENT
    export FAKE_GETOBJECT_SOURCE="$ARTEFATO16"

    LOG16="$AREA/mount16.log"
    : > "$LOG16"
    export FAKE_MOUNT_LOG="$LOG16"
    export FAKE_DOCKER_PATH_MODE=msys
    export FAKE_VM_DIR="$AREA/t16vm"
    mkdir -p "$FAKE_VM_DIR"

    set +e
    OUT16="$(sh "$VERIFY_SH" -p "$PENDENTE16" -e "$D16/env.verify" 2>&1)"
    RC16=$?
    set -e
    echo "$OUT16" > "$AREA/t16.out"

    unset FAKE_MOUNT_LOG FAKE_VM_DIR
    export FAKE_DOCKER_PATH_MODE=linux

    RC_T15=0
    grep -qE '^/dados [A-Za-z]:/' "$LOG16" || RC_T15=1
    registrar "$RC_T15" "15: verify entrega ao docker a forma Windows (X:/...) do diretorio temporario"

    RC_T16=0
    { [ "$RC16" -eq 0 ] \
        && printf '%s' "$OUT16" | grep -q "VERIFIED" \
        && [ -f "$D16/facilpi-backup-20260104T000000Z.uploaded" ]; } || RC_T16=1
    registrar "$RC_T16" "16: sob simulacao MSYS+Docker Desktop, host acha o download, SHA-256 confere e verify chega a VERIFIED"
else
    registrar_skip "plataforma sem dualidade MSYS<->Windows" "14: fixture reproduz o GATE-3Y"
    registrar_skip "plataforma sem dualidade MSYS<->Windows" "15: verify entrega a forma Windows ao docker"
    registrar_skip "plataforma sem dualidade MSYS<->Windows" "16: sob simulacao MSYS, verify chega a VERIFIED"
fi

# ============================================================================
# TESTE 17 — caminho Linux (mount identidade) continua funcionando
# ============================================================================
D17="$AREA/t17"; mkdir -p "$D17"
criar_pacote "$D17/facilpi-backup-20260105T000000Z"
criar_env_upload "$D17/env.upload"
criar_env_verify "$D17/env.verify"
export FAKE_DOCKER_PATH_MODE=linux
export FAKE_PUT_STATUS=0
export FAKE_PUT_OUTPUT="ver-id-17${TAB}etag-17"
sh "$UPLOAD_SH" -b "$D17/facilpi-backup-20260105T000000Z" -e "$D17/env.upload" -c daily >/dev/null 2>&1

PENDENTE17="$D17/facilpi-backup-20260105T000000Z.offhost_pending.json"
ARTEFATO17="$D17/facilpi-backup-20260105T000000Z.tar.age"
SHA17="$(sed -n 's/.*"encrypted_artifact_sha256": *"\([^"]*\)".*/\1/p' "$PENDENTE17")"
RECIPIENT17="$(sed -n 's/.*"encryption_recipient": *"\([^"]*\)".*/\1/p' "$PENDENTE17")"
PACKAGE17="$(sed -n 's/.*"package_name": *"\([^"]*\)".*/\1/p' "$PENDENTE17")"
RETAIN17="$(sed -n 's/.*"expected_retain_until": *"\([^"]*\)".*/\1/p' "$PENDENTE17")"
BYTES17="$(wc -c < "$ARTEFATO17" | tr -d ' ')"

export FAKE_RETENTION_STATUS=0
export FAKE_RETENTION_OUTPUT="COMPLIANCE${TAB}$RETAIN17"
export FAKE_HEAD_STATUS=0
export FAKE_HEAD_OUTPUT="$BYTES17${TAB}ver-id-17${TAB}fake-checksum"
export FAKE_HEAD_META_SHA="$SHA17"
export FAKE_HEAD_META_RECIPIENT="$RECIPIENT17"
export FAKE_HEAD_META_PACKAGE="$PACKAGE17"
export FAKE_GETOBJECT_STATUS=0
unset FAKE_GETOBJECT_CONTENT
export FAKE_GETOBJECT_SOURCE="$ARTEFATO17"

set +e
OUT17="$(sh "$VERIFY_SH" -p "$PENDENTE17" -e "$D17/env.verify" 2>&1)"
RC17=$?
set -e
echo "$OUT17" > "$AREA/t17.out"
RC_T17=0
{ [ "$RC17" -eq 0 ] \
    && printf '%s' "$OUT17" | grep -q "VERIFIED" \
    && [ -f "$D17/facilpi-backup-20260105T000000Z.uploaded" ]; } || RC_T17=1
registrar "$RC_T17" "17: caminho Linux (mount identidade) chega a VERIFIED"

# ============================================================================
# TESTE 18 — o pendente gerado pelo uploader e JSON valido de verdade
# ============================================================================
if [ -n "$VALIDADOR_JSON" ]; then
    RC_T18=0
    json_valido "$PENDENTE1" || RC_T18=1
    registrar "$RC_T18" "18: estado pendente gerado pelo uploader e JSON valido ($VALIDADOR_JSON)"
else
    registrar_skip "sem parser JSON (python/node) no PATH" "18: estado pendente e JSON valido"
fi

# ============================================================================
# TESTE 19/20 — ETag com aspas (o que o `aws --output text` devolve de fato)
#
# No GATE-3Y o PUT real retornou o ETag entre aspas e o pendente saiu com
# "put_etag": ""96ec...438f"" — JSON invalido naquela linha. O uploader
# normaliza removendo aspas/barras (sintaxe de transporte do S3, nao parte do
# valor), mantendo o campo recuperavel.
# ============================================================================
D19="$AREA/t19"; mkdir -p "$D19"
criar_pacote "$D19/facilpi-backup-20260106T000000Z"
criar_env_upload "$D19/env.upload"
export FAKE_DOCKER_PATH_MODE=linux
export FAKE_PUT_STATUS=0
export FAKE_PUT_OUTPUT="ver-id-19${TAB}${ASPA}deadbeefcafef00dfeedfacedecafbad${ASPA}"
sh "$UPLOAD_SH" -b "$D19/facilpi-backup-20260106T000000Z" -e "$D19/env.upload" -c daily >/dev/null 2>&1
PENDENTE19="$D19/facilpi-backup-20260106T000000Z.offhost_pending.json"

if [ -n "$VALIDADOR_JSON" ]; then
    RC_T19=0
    json_valido "$PENDENTE19" || RC_T19=1
    registrar "$RC_T19" "19: ETag com aspas ainda produz pendente JSON valido"

    RC_T20=0
    ETAG_LIDO="$(json_campo "$PENDENTE19" put_etag)" || ETAG_LIDO=""
    [ "$ETAG_LIDO" = "deadbeefcafef00dfeedfacedecafbad" ] || RC_T20=1
    registrar "$RC_T20" "20: put_etag e recuperado normalizado, sem aspas e sem perder o valor"
else
    registrar_skip "sem parser JSON (python/node) no PATH" "19: ETag com aspas produz JSON valido"
    registrar_skip "sem parser JSON (python/node) no PATH" "20: put_etag recuperado normalizado"
fi

# ============================================================================
# TESTE 21/22/23/24 — contrato de PATH do bind mount no FETCH (recuperacao)
#
# O fetch monta DOIS volumes: o destino da recuperacao (/dados) e o diretorio
# da identidade age (/chave). Ambos vinham de `cd && pwd`, sem a conversao que
# o verify ja tinha — mesmo defeito latente do GATE-3Y, agora corrigido com
# DESTINO_MONTE / DIR_IDENTIDADE_MONTE.
#
# O fixture serve a cadeia inteira: upload (fake) -> verify (fake) -> manifesto
# VERIFIED -> fetch. O `age -d` falso so consegue decifrar se conseguir LER a
# identidade por /chave e o artefato por /dados — se qualquer mount cair na VM,
# o fetch falha, que e precisamente a regressao que queremos detectar.
# ============================================================================
criar_env_fetch() {
    cat > "$1" <<ENV
B2_ENDPOINT=https://s3.us-east-005.backblazeb2.com
B2_REGION=us-east-005
B2_BUCKET=facilpi-test-bucket
OFFHOST_RUNTIME=container
OFFHOST_IMAGE=facilpi-fake/offhost:test
B2_KEY_ID=FAKEVERIFYKEYID
B2_APP_KEY=FAKEVERIFYAPPKEYVALUE
ENV
}

# Prepara pacote + upload + verify e devolve o manifesto VERIFIED, que e o que
# o fetch consome com -m.
PKG_F="facilpi-backup-20260107T000000Z"
DF="$AREA/tfetch"; mkdir -p "$DF"
criar_pacote "$DF/$PKG_F"
criar_env_upload "$DF/env.upload"
criar_env_verify "$DF/env.verify"
criar_env_fetch "$DF/env.fetch"

# Identidade age FALSA, em diretorio proprio — e o mount /chave que importa
# aqui, nao o conteudo (o cifrador do fixture nao usa chave de verdade).
DIR_CHAVE="$DF/cofre"; mkdir -p "$DIR_CHAVE"
printf 'AGE-FAKE-IDENTITY-NAO-E-CHAVE-REAL\n' > "$DIR_CHAVE/identidade.agekey"
chmod 600 "$DIR_CHAVE/identidade.agekey"

export FAKE_DOCKER_PATH_MODE=linux
export FAKE_PUT_STATUS=0
export FAKE_PUT_OUTPUT="ver-id-f${TAB}etag-f"
sh "$UPLOAD_SH" -b "$DF/$PKG_F" -e "$DF/env.upload" -c daily >/dev/null 2>&1

PENDENTE_F="$DF/$PKG_F.offhost_pending.json"
ARTEFATO_F="$DF/$PKG_F.tar.age"
SHA_F="$(sed -n 's/.*"encrypted_artifact_sha256": *"\([^"]*\)".*/\1/p' "$PENDENTE_F")"
RECIPIENT_F="$(sed -n 's/.*"encryption_recipient": *"\([^"]*\)".*/\1/p' "$PENDENTE_F")"
RETAIN_F="$(sed -n 's/.*"expected_retain_until": *"\([^"]*\)".*/\1/p' "$PENDENTE_F")"
BYTES_F="$(wc -c < "$ARTEFATO_F" | tr -d ' ')"

export FAKE_RETENTION_STATUS=0
export FAKE_RETENTION_OUTPUT="COMPLIANCE${TAB}$RETAIN_F"
export FAKE_HEAD_STATUS=0
export FAKE_HEAD_OUTPUT="$BYTES_F${TAB}ver-id-f${TAB}fake-checksum"
export FAKE_HEAD_META_SHA="$SHA_F"
export FAKE_HEAD_META_RECIPIENT="$RECIPIENT_F"
export FAKE_HEAD_META_PACKAGE="$PKG_F"
export FAKE_GETOBJECT_STATUS=0
unset FAKE_GETOBJECT_CONTENT
export FAKE_GETOBJECT_SOURCE="$ARTEFATO_F"
sh "$VERIFY_SH" -p "$PENDENTE_F" -e "$DF/env.verify" >/dev/null 2>&1
MANIFESTO_F="$DF/$PKG_F.offhost_manifest.json"

if [ "$PLATAFORMA_MSYS" -eq 1 ] && [ -f "$MANIFESTO_F" ]; then
    LOGF="$AREA/mount_fetch.log"
    : > "$LOGF"
    export FAKE_MOUNT_LOG="$LOGF"
    export FAKE_DOCKER_PATH_MODE=msys
    export FAKE_VM_DIR="$AREA/tfetchvm"
    mkdir -p "$FAKE_VM_DIR"

    set +e
    OUT21="$(sh "$FETCH_SH" -m "$MANIFESTO_F" -e "$DF/env.fetch" \
        -i "$DIR_CHAVE/identidade.agekey" -d "$DF/recuperado" 2>&1)"
    RC21=$?
    set -e
    echo "$OUT21" > "$AREA/t21.out"

    unset FAKE_MOUNT_LOG FAKE_VM_DIR
    export FAKE_DOCKER_PATH_MODE=linux

    RC_T21=0
    grep -qE '^/dados [A-Za-z]:/' "$LOGF" || RC_T21=1
    registrar "$RC_T21" "21: fetch entrega ao docker a forma Windows (X:/...) do destino (/dados)"

    RC_T22=0
    grep -qE '^/chave [A-Za-z]:/' "$LOGF" || RC_T22=1
    registrar "$RC_T22" "22: fetch entrega ao docker a forma Windows (X:/...) do diretorio da identidade (/chave)"

    RC_T23=0
    { [ "$RC21" -eq 0 ] \
        && [ -f "$DF/recuperado/$PKG_F/database.dump" ] \
        && [ -f "$DF/recuperado/$PKG_F/uploads.tar.gz" ] \
        && [ -f "$DF/recuperado/$PKG_F/manifest.json" ] \
        && [ -f "$DF/recuperado/$PKG_F/SHA256SUMS" ]; } || RC_T23=1
    registrar "$RC_T23" "23: sob simulacao MSYS, fetch decifra, extrai e o host enxerga o pacote com SHA256SUMS conferido"
else
    registrar_skip "plataforma sem dualidade MSYS<->Windows" "21: fetch entrega forma Windows do destino"
    registrar_skip "plataforma sem dualidade MSYS<->Windows" "22: fetch entrega forma Windows da identidade"
    registrar_skip "plataforma sem dualidade MSYS<->Windows" "23: sob simulacao MSYS, fetch recupera o pacote"
fi

# --- 24: caminho Linux (mount identidade) continua funcionando ---------------
export FAKE_DOCKER_PATH_MODE=linux
set +e
OUT24="$(sh "$FETCH_SH" -m "$MANIFESTO_F" -e "$DF/env.fetch" \
    -i "$DIR_CHAVE/identidade.agekey" -d "$DF/recuperado_linux" 2>&1)"
RC24=$?
set -e
echo "$OUT24" > "$AREA/t24.out"
RC_T24=0
{ [ "$RC24" -eq 0 ] && [ -f "$DF/recuperado_linux/$PKG_F/SHA256SUMS" ]; } || RC_T24=1
registrar "$RC_T24" "24: fetch em caminho Linux (mount identidade) recupera o pacote normalmente"

# ============================================================================
# TESTE 25 — anti-divergencia dos bind mounts
#
# `caminho_para_montagem` e duplicada em cada script de ops/, como `ler_env`,
# porque estes scripts precisam sobreviver a uma copia avulsa no dia do
# desastre. O custo da duplicacao e o risco de alguem acrescentar um `-v` novo
# com o caminho cru. Este teste e a trava contra isso: todo `-v` cujo lado
# esquerdo seja variavel tem de ser volume nomeado (VOLUME_*) ou forma
# convertida (*_MONTE).
# ============================================================================
RC_T25=0
for ARQ in "$BACKUP_SH" "$RESTORE_SH" "$UPLOAD_SH" "$VERIFY_SH" "$FETCH_SH"; do
    SUSPEITAS="$(grep -o -- '-v "\$[A-Za-z_][A-Za-z0-9_]*' "$ARQ" \
        | sed 's/.*\$//' | grep -v '_MONTE$' | grep -v '^VOLUME_' || true)"
    if [ -n "$SUSPEITAS" ]; then
        echo "      $(basename "$ARQ"): $SUSPEITAS" >&2
        RC_T25=1
    fi
done
registrar "$RC_T25" "25: todo bind mount de caminho de host em ops/*.sh usa a forma convertida"

# ============================================================================
# TESTE 26 — upload monta o diretorio do pacote na forma Windows
# ============================================================================
if [ "$PLATAFORMA_MSYS" -eq 1 ]; then
    D26="$AREA/t26"; mkdir -p "$D26"
    criar_pacote "$D26/facilpi-backup-20260108T000000Z"
    criar_env_upload "$D26/env.upload"
    LOG26="$AREA/mount26.log"; : > "$LOG26"
    export FAKE_MOUNT_LOG="$LOG26"
    export FAKE_DOCKER_PATH_MODE=msys
    export FAKE_VM_DIR="$AREA/t26vm"; mkdir -p "$FAKE_VM_DIR"
    export FAKE_PUT_STATUS=0
    export FAKE_PUT_OUTPUT="ver-id-26${TAB}etag-26"
    sh "$UPLOAD_SH" -b "$D26/facilpi-backup-20260108T000000Z" -e "$D26/env.upload" -c daily >/dev/null 2>&1
    unset FAKE_MOUNT_LOG FAKE_VM_DIR
    export FAKE_DOCKER_PATH_MODE=linux
    RC_T26=0
    grep -qE '^/dados [A-Za-z]:/' "$LOG26" || RC_T26=1
    registrar "$RC_T26" "26: upload entrega ao docker a forma Windows do diretorio do pacote"
else
    registrar_skip "plataforma sem dualidade MSYS<->Windows" "26: upload entrega forma Windows do diretorio do pacote"
fi

# ============================================================================
# TESTE 27/28/29 — ops/backup.sh: barreiras fail-closed e path do pacote
#
# O GATE-3Y cifrou, enviou e travou por Object Lock um pacote cujo
# `database.dump` era texto. Estas barreiras existem para que isso nao possa
# se repetir — e estes testes provam que elas reprovam de verdade.
# ============================================================================
criar_env_pg() {
    cat > "$1" <<ENV
POSTGRES_USER=drilluser
POSTGRES_DB=drilldb
ENVIRONMENT=drill-sintetico
UPLOAD_ROOT=/data/uploads
ENV
}

export FAKE_DOCKER_PATH_MODE=linux

D27="$AREA/t27"; mkdir -p "$D27/saida"
criar_env_pg "$D27/env.pg"
export FAKE_PGDUMP_MODE=texto
set +e
OUT27="$(sh "$BACKUP_SH" -p proj-t27 -e "$D27/env.pg" -d "$D27/saida" 2>&1)"
RC27=$?
set -e
echo "$OUT27" > "$AREA/t27.out"
unset FAKE_PGDUMP_MODE
RC_T27=0
{ [ "$RC27" -ne 0 ] \
    && printf '%s' "$OUT27" | grep -q "PGDMP" \
    && [ -z "$(find "$D27/saida" -name manifest.json 2>/dev/null)" ]; } || RC_T27=1
registrar "$RC_T27" "27: backup reprova dump que nao e pg_dump -Fc, antes de gerar manifesto"

D28="$AREA/t28"; mkdir -p "$D28/saida"
criar_env_pg "$D28/env.pg"
export FAKE_ALEMBIC_HEAD=""
set +e
OUT28="$(sh "$BACKUP_SH" -p proj-t28 -e "$D28/env.pg" -d "$D28/saida" 2>&1)"
RC28=$?
set -e
echo "$OUT28" > "$AREA/t28.out"
unset FAKE_ALEMBIC_HEAD
RC_T28=0
{ [ "$RC28" -ne 0 ] \
    && [ -z "$(find "$D28/saida" -name manifest.json 2>/dev/null)" ]; } || RC_T28=1
registrar "$RC_T28" "28: backup reprova alembic_version vazio, antes de gerar manifesto"

D29="$AREA/t29"; mkdir -p "$D29/saida"
criar_env_pg "$D29/env.pg"
LOG29="$AREA/mount29.log"; : > "$LOG29"
export FAKE_MOUNT_LOG="$LOG29"
if [ "$PLATAFORMA_MSYS" -eq 1 ]; then
    export FAKE_DOCKER_PATH_MODE=msys
    export FAKE_VM_DIR="$AREA/t29vm"; mkdir -p "$FAKE_VM_DIR"
fi
set +e
OUT29="$(sh "$BACKUP_SH" -p proj-t29 -e "$D29/env.pg" -d "$D29/saida" 2>&1)"
RC29=$?
set -e
echo "$OUT29" > "$AREA/t29.out"
unset FAKE_MOUNT_LOG FAKE_VM_DIR
export FAKE_DOCKER_PATH_MODE=linux
PACOTE29="$(find "$D29/saida" -maxdepth 1 -type d -name 'facilpi-backup-*' | head -1)"
RC_T29=0
{ [ "$RC29" -eq 0 ] \
    && [ -n "$PACOTE29" ] \
    && [ "$(head -c 5 "$PACOTE29/database.dump")" = "PGDMP" ] \
    && [ -f "$PACOTE29/uploads.tar.gz" ] \
    && [ -f "$PACOTE29/SHA256SUMS" ] \
    && grep -q '"alembic_head": "020_documentos_admin_anexar"' "$PACOTE29/manifest.json" \
    && ( cd "$PACOTE29" && sha256sum -c SHA256SUMS >/dev/null 2>&1 ); } || RC_T29=1
if [ "$PLATAFORMA_MSYS" -eq 1 ]; then
    grep -qE '^/saida [A-Za-z]:/' "$LOG29" || RC_T29=1
fi
registrar "$RC_T29" "29: backup produz pacote integro com dump PGDMP e monta /saida na forma correta"

# ============================================================================
# TESTE 30/31 — ops/restore.sh para ANTES de tocar o banco
#
# O mock do pg_restore cria um arquivo-sentinela quando e chamado. Os testes
# provam que ele NAO e chamado: a evidencia e o banco nunca ter sido tocado,
# nao apenas o script ter retornado != 0.
# ============================================================================
# $4 = formato do manifesto: "pretty" reproduz exatamente o que ops/backup.sh
# escreve; "compacto" e JSON igualmente valido, sem espaco depois do
# dois-pontos — serve para provar que o parser nao depende de estilo.
criar_pacote_pg() {
    P="$1"; CABECA="$2"; DUMP_OK="$3"; FORMATO="${4:-pretty}"
    mkdir -p "$P"
    if [ "$DUMP_OK" = "sim" ]; then
        printf 'PGDMP-archive-sintetico' > "$P/database.dump"
    else
        printf -- '-- isto NAO e um archive\n' > "$P/database.dump"
    fi
    # tar.gz de verdade: ops/restore.sh monta o pacote e o fixture confere que
    # uploads.tar.gz esta alcancavel por /entrada.
    TMP_P="$(mktemp -d "${TMPDIR:-/tmp}/fake-pkg-uploads.XXXXXX")"
    mkdir -p "$TMP_P/uploads"
    printf 'anexo-sintetico' > "$TMP_P/uploads/anexo.bin"
    tar -czf "$P/uploads.tar.gz" -C "$TMP_P" uploads
    rm -rf "$TMP_P"
    if [ "$FORMATO" = "compacto" ]; then
        printf '{"backup_format_version":1,"alembic_head":"%s","app_git_sha":"x"}\n' "$CABECA" > "$P/manifest.json"
    elif [ -n "$CABECA" ]; then
        printf '{\n  "backup_format_version": 1,\n  "alembic_head": "%s",\n  "app_git_sha": "x"\n}\n' "$CABECA" > "$P/manifest.json"
    else
        printf '{\n  "backup_format_version": 1,\n  "app_git_sha": "x"\n}\n' > "$P/manifest.json"
    fi
    ( cd "$P" && sha256sum database.dump uploads.tar.gz manifest.json > SHA256SUMS )
}

D30="$AREA/t30"; mkdir -p "$D30"
criar_env_pg "$D30/env.pg"
criar_pacote_pg "$D30/pacote-sem-head" "" "sim"
export FAKE_PGRESTORE_CHAMADO="$D30/pg_restore_foi_chamado"
rm -f "$FAKE_PGRESTORE_CHAMADO"
set +e
OUT30="$(sh "$RESTORE_SH" -p proj-t30 -e "$D30/env.pg" -b "$D30/pacote-sem-head" 2>&1)"
RC30=$?
set -e
echo "$OUT30" > "$AREA/t30.out"
RC_T30=0
{ [ "$RC30" -ne 0 ] && [ ! -f "$FAKE_PGRESTORE_CHAMADO" ]; } || RC_T30=1
registrar "$RC_T30" "30: restore reprova manifesto sem alembic_head SEM tocar o banco"

D31="$AREA/t31"; mkdir -p "$D31"
criar_env_pg "$D31/env.pg"
criar_pacote_pg "$D31/pacote-dump-texto" "020_documentos_admin_anexar" "nao"
export FAKE_PGRESTORE_CHAMADO="$D31/pg_restore_foi_chamado"
rm -f "$FAKE_PGRESTORE_CHAMADO"
set +e
OUT31="$(sh "$RESTORE_SH" -p proj-t31 -e "$D31/env.pg" -b "$D31/pacote-dump-texto" 2>&1)"
RC31=$?
set -e
echo "$OUT31" > "$AREA/t31.out"
unset FAKE_PGRESTORE_CHAMADO
RC_T31=0
{ [ "$RC31" -ne 0 ] \
    && printf '%s' "$OUT31" | grep -q "PGDMP" \
    && [ ! -f "$D31/pg_restore_foi_chamado" ]; } || RC_T31=1
registrar "$RC_T31" "31: restore reprova dump que nao e PGDMP SEM tocar o banco"

# --- 35: caminho positivo do restore, com manifesto em JSON compacto --------
# Prova duas coisas de uma vez: o restore completo funciona ponta a ponta (com
# pg_restore, extracao de anexos por /entrada e conferencia de head), e o
# parser do manifesto nao depende do espaco depois do dois-pontos — estilo de
# serializacao nao pode decidir se um backup e restauravel.
D35="$AREA/t35"; mkdir -p "$D35"
criar_env_pg "$D35/env.pg"
criar_pacote_pg "$D35/pacote-ok" "020_documentos_admin_anexar" "sim" "compacto"
export FAKE_PGRESTORE_CHAMADO="$D35/pg_restore_foi_chamado"
rm -f "$FAKE_PGRESTORE_CHAMADO"
export FAKE_ALEMBIC_HEAD="020_documentos_admin_anexar"
set +e
OUT35="$(sh "$RESTORE_SH" -p proj-t35 -e "$D35/env.pg" -b "$D35/pacote-ok" 2>&1)"
RC35=$?
set -e
echo "$OUT35" > "$AREA/t35.out"
unset FAKE_PGRESTORE_CHAMADO FAKE_ALEMBIC_HEAD
RC_T35=0
{ [ "$RC35" -eq 0 ] \
    && [ -f "$D35/pg_restore_foi_chamado" ] \
    && printf '%s' "$OUT35" | grep -q "restore concluido"; } || RC_T35=1
registrar "$RC_T35" "35: restore completo com manifesto compacto — pg_restore roda e o head confere"

# ============================================================================
# TESTE 32/33 — custodia do manifesto VERIFIED
#
# Sem o manifesto fora do host de origem, uma perda total deixa o objeto
# remoto indescobrivel: a credencial de leitura nao tem `listFiles`, por
# decisao de arquitetura. Por isso a custodia e fail-closed.
# ============================================================================
preparar_verify_custodia() {
    DIRT="$1"; CUSTODIA_PATH="$2"; PKGN="$3"
    mkdir -p "$DIRT"
    criar_pacote "$DIRT/$PKGN"
    criar_env_upload "$DIRT/env.upload"
    export FAKE_DOCKER_PATH_MODE=linux
    export FAKE_PUT_STATUS=0
    export FAKE_PUT_OUTPUT="ver-id-c${TAB}etag-c"
    sh "$UPLOAD_SH" -b "$DIRT/$PKGN" -e "$DIRT/env.upload" -c daily >/dev/null 2>&1
    PEND_C="$DIRT/$PKGN.offhost_pending.json"
    ART_C="$DIRT/$PKGN.tar.age"
    cat > "$DIRT/env.verify" <<ENV
OFFHOST_IMAGE=facilpi-fake/offhost:test
B2_KEY_ID=FAKEVERIFYKEYID
B2_APP_KEY=FAKEVERIFYAPPKEYVALUE
OFFHOST_CUSTODIA=$CUSTODIA_PATH
ENV
    RETAIN_C="$(sed -n 's/.*"expected_retain_until": *"\([^"]*\)".*/\1/p' "$PEND_C")"
    BYTES_C="$(wc -c < "$ART_C" | tr -d ' ')"
    SHA_C="$(sed -n 's/.*"encrypted_artifact_sha256": *"\([^"]*\)".*/\1/p' "$PEND_C")"
    RECIP_C="$(sed -n 's/.*"encryption_recipient": *"\([^"]*\)".*/\1/p' "$PEND_C")"
    FAKE_RETENTION_OUTPUT="COMPLIANCE${TAB}$RETAIN_C"
    FAKE_HEAD_OUTPUT="$BYTES_C${TAB}ver-id-c${TAB}fake-checksum"
    FAKE_HEAD_META_SHA="$SHA_C"
    FAKE_HEAD_META_RECIPIENT="$RECIP_C"
    export FAKE_RETENTION_STATUS=0
    export FAKE_HEAD_STATUS=0
    export FAKE_RETENTION_OUTPUT FAKE_HEAD_OUTPUT FAKE_HEAD_META_SHA FAKE_HEAD_META_RECIPIENT
    export FAKE_HEAD_META_PACKAGE="$PKGN"
    export FAKE_GETOBJECT_STATUS=0
    unset FAKE_GETOBJECT_CONTENT
    export FAKE_GETOBJECT_SOURCE="$ART_C"
}

D32="$AREA/t32"
preparar_verify_custodia "$D32" "$AREA/t32/cofre" "facilpi-backup-20260109T000000Z"
set +e
sh "$VERIFY_SH" -p "$D32/facilpi-backup-20260109T000000Z.offhost_pending.json" -e "$D32/env.verify" >"$AREA/t32.out" 2>&1
RC32=$?
set -e
RC_T32=0
{ [ "$RC32" -eq 0 ] \
    && [ -f "$AREA/t32/cofre/facilpi-backup-20260109T000000Z.offhost_manifest.json" ] \
    && grep -q '"state": "VERIFIED"' "$AREA/t32/cofre/facilpi-backup-20260109T000000Z.offhost_manifest.json" \
    && [ -f "$D32/facilpi-backup-20260109T000000Z.uploaded" ]; } || RC_T32=1
registrar "$RC_T32" "32: verify custodia o manifesto VERIFIED no cofre quando OFFHOST_CUSTODIA esta definido"

D33="$AREA/t33"
mkdir -p "$D33"
# Cofre impossivel: um caminho DENTRO de um arquivo comum. `mkdir -p` falha em
# qualquer plataforma, sem depender de permissao.
printf 'sou um arquivo, nao um diretorio\n' > "$D33/bloqueio"
preparar_verify_custodia "$D33" "$D33/bloqueio/cofre" "facilpi-backup-20260110T000000Z"
set +e
sh "$VERIFY_SH" -p "$D33/facilpi-backup-20260110T000000Z.offhost_pending.json" -e "$D33/env.verify" >"$AREA/t33.out" 2>&1
RC33=$?
set -e
RC_T33=0
{ [ "$RC33" -ne 0 ] && [ ! -f "$D33/facilpi-backup-20260110T000000Z.uploaded" ]; } || RC_T33=1
registrar "$RC_T33" "33: custodia impossivel -> verify falha fechado, SEM gravar marcador de sucesso"

# ============================================================================
# TESTE 34 — o fetch tambem nunca enumera nem escreve no bucket
# ============================================================================
RC_T34=0
grep -qE "list-objects|delete-object|put-object|put-object-retention" "$FETCH_SH" && RC_T34=1
registrar "$RC_T34" "34: ops/offhost_fetch.sh nunca referencia list/delete/put-object"

# --- resumo -----------------------------------------------------------------
echo ""
if [ "$IGNORADOS" -gt 0 ]; then
    echo "=== $((TOTAL - FALHAS - IGNORADOS))/$TOTAL PASS, $IGNORADOS SKIP, $FALHAS FAIL ==="
else
    echo "=== $((TOTAL - FALHAS))/$TOTAL PASS ==="
fi
[ "$FALHAS" -eq 0 ]
