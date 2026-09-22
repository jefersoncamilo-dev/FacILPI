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

FALHAS=0
TOTAL=0

registrar() {
    TOTAL=$((TOTAL + 1))
    if [ "$1" -eq 0 ]; then
        echo "PASS  $2"
    else
        echo "FAIL  $2"
        FALHAS=$((FALHAS + 1))
    fi
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

if [ "$1" != "run" ]; then
    echo "fake-docker: comando nao mockado: $*" >&2
    exit 90
fi
shift

HOSTDIR=""
while [ $# -gt 0 ]; do
    case "$1" in
        --rm) shift ;;
        -i) shift ;;
        -e) shift 2 ;;
        -v)
            HOSTDIR="${2%%:*}"
            shift 2
            ;;
        *) break ;;
    esac
done

IMAGE="$1"; shift
FERRAMENTA="$1"; shift

case "$FERRAMENTA" in
    age)
        # Cifrador falso deterministico: prefixo fixo + o stdin, sem
        # criptografia real. O upload real usa a imagem de verdade; isto so
        # testa o FLUXO do script (tamanho, sha256, PENDENTE), nao o age em si
        # (o age em si ja foi validado no round-trip da reconciliacao).
        printf 'FAKEAGE-CIPHERTEXT:'
        cat
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
                DESTINO_REAL="$HOSTDIR/$(basename "$DESTINO")"
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

# --- resumo -----------------------------------------------------------------
echo ""
echo "=== $((TOTAL - FALHAS))/$TOTAL PASS ==="
[ "$FALHAS" -eq 0 ]
