#!/usr/bin/env sh
# FacILPI — verificacao independente de um upload off-host PENDENTE.
#
# ESTE SCRIPT NAO RODA NA VPS. Ele usa a credencial de LEITURA
# (readFiles + readFileRetentions), que por decisao de arquitetura (GATE-3R
# a GATE-3S) nunca pode existir no mesmo host que faz o upload. Rodar isto
# na VPS anularia a separacao de custodia: quem comprometesse a VPS passaria
# a conseguir ler todos os backups off-host, nao so escrever lixo novo.
#
# ops/offhost_upload.sh so grava um estado PENDENTE
# (<pacote>.offhost_pending.json) — a resposta do PutObject da Backblaze
# nunca confirma Object Lock nem checksum (ver GATE-3Q/3R). Este script e
# quem confirma de verdade, com tres chamadas independentes:
#
#   A) GetObjectRetention  -> Mode == COMPLIANCE, RetainUntilDate esperado
#   B) HeadObject           -> metadata esperada, ContentLength esperado
#   C) GetObject (download) -> SHA-256 local == SHA-256 calculado no upload
#
# Somente se as tres passarem, o marcador `.uploaded` e o manifesto
# definitivo (offhost_manifest.json) sao gravados — o mesmo par de arquivos
# que ops/offhost_fetch.sh ja sabe ler, sem nenhuma mudanca la.
#
# Uso:
#   ops/offhost_verify.sh -p <pacote>.offhost_pending.json -e <arquivo env verify>
#
# O que este script NUNCA faz:
#   - usar a credencial de upload (writeFiles/writeFileRetentions);
#   - executar PUT, DELETE, COPY, LIST, ou alterar retention/legal hold;
#   - descobrir VersionId por ListObjectVersions — se o pendente nao tiver
#     um, a verificacao opera sobre a versao atual do objeto, sem listar;
#   - confiar no ETag como prova de integridade — a prova e o SHA-256 do
#     artefato baixado, comparado ao SHA-256 calculado ANTES do upload;
#   - promover sucesso parcial: qualquer divergencia aborta antes de gravar
#     `.uploaded` ou o manifesto.
set -eu

export MSYS_NO_PATHCONV=1

PENDENTE=""
ARQUIVO_ENV=""

uso() {
    echo "uso: ops/offhost_verify.sh -p <pacote>.offhost_pending.json -e <arquivo env verify>" >&2
    exit 2
}

while [ $# -gt 0 ]; do
    case "$1" in
        -p) PENDENTE="${2:-}"; shift 2 ;;
        -e) ARQUIVO_ENV="${2:-}"; shift 2 ;;
        -h|--help) uso ;;
        *) echo "argumento desconhecido: $1" >&2; uso ;;
    esac
done

[ -n "$PENDENTE" ] || { echo "falta -p <pacote>.offhost_pending.json" >&2; uso; }
[ -n "$ARQUIVO_ENV" ] || { echo "falta -e <arquivo env verify>" >&2; uso; }
[ -f "$PENDENTE" ] || { echo "arquivo pendente nao encontrado: $PENDENTE" >&2; exit 2; }
[ -f "$ARQUIVO_ENV" ] || { echo "arquivo de ambiente nao encontrado: $ARQUIVO_ENV" >&2; exit 2; }

ler_env() {
    # Mesmo padrao do resto do off-host: le a chave SEM dar source.
    sed -n "s/^$1=//p" "$ARQUIVO_ENV" | head -1
}

ler_pendente() {
    # Extrai um campo string do JSON pendente. Mesmo padrao ja usado em
    # ops/offhost_fetch.sh para ler manifest.json — sem dependencia de jq.
    sed -n "s/.*\"$1\": *\"\([^\"]*\)\".*/\1/p" "$PENDENTE" | head -1
}

B2_KEY_ID="$(ler_env B2_KEY_ID)"
B2_APP_KEY="$(ler_env B2_APP_KEY)"
OFFHOST_IMAGE="$(ler_env OFFHOST_IMAGE)"
SENTINELA="$(ler_env OFFHOST_SENTINELA)"
[ -n "$OFFHOST_IMAGE" ] || OFFHOST_IMAGE="facilpi/offhost:1"

[ -n "$B2_KEY_ID" ] || { echo "FALHA: B2_KEY_ID ausente em $ARQUIVO_ENV" >&2; exit 2; }
[ -n "$B2_APP_KEY" ] || { echo "FALHA: B2_APP_KEY ausente em $ARQUIVO_ENV" >&2; exit 2; }

# --- dados esperados, vindos do PENDENTE (nunca do servidor ainda) -----------
REMOTE_BUCKET="$(ler_pendente remote_bucket)"
REMOTE_ENDPOINT="$(ler_pendente remote_endpoint)"
REMOTE_REGION="$(ler_pendente remote_region)"
REMOTE_KEY="$(ler_pendente remote_key)"
REMOTE_VERSION_ID="$(ler_pendente remote_version_id)"
PACKAGE_NAME="$(ler_pendente package_name)"
AGE_RECIPIENT_ESPERADO="$(ler_pendente encryption_recipient)"
SHA_ESPERADO="$(ler_pendente encrypted_artifact_sha256)"
BYTES_ESPERADO="$(sed -n 's/.*"encrypted_artifact_bytes": *\([0-9]*\).*/\1/p' "$PENDENTE" | head -1)"
LOCK_MODE_ESPERADO="$(ler_pendente expected_object_lock_mode)"
RETAIN_ESPERADO="$(ler_pendente expected_retain_until)"

[ -n "$REMOTE_BUCKET" ] || { echo "FALHA: remote_bucket ausente em $PENDENTE" >&2; exit 2; }
[ -n "$REMOTE_ENDPOINT" ] || { echo "FALHA: remote_endpoint ausente em $PENDENTE" >&2; exit 2; }
[ -n "$REMOTE_REGION" ] || { echo "FALHA: remote_region ausente em $PENDENTE" >&2; exit 2; }
[ -n "$REMOTE_KEY" ] || { echo "FALHA: remote_key ausente em $PENDENTE" >&2; exit 2; }
[ -n "$SHA_ESPERADO" ] || { echo "FALHA: encrypted_artifact_sha256 ausente em $PENDENTE" >&2; exit 2; }
[ -n "$LOCK_MODE_ESPERADO" ] || { echo "FALHA: expected_object_lock_mode ausente em $PENDENTE" >&2; exit 2; }
[ -n "$RETAIN_ESPERADO" ] || { echo "FALHA: expected_retain_until ausente em $PENDENTE" >&2; exit 2; }

DIR_PAI="$(cd "$(dirname "$PENDENTE")" && pwd)"
MARCADOR="$DIR_PAI/$PACKAGE_NAME.uploaded"
MANIFESTO_OFFHOST="$DIR_PAI/$PACKAGE_NAME.offhost_manifest.json"

if [ -f "$MARCADOR" ]; then
    echo "JA VERIFICADO  $PACKAGE_NAME  (marcador: $MARCADOR)"
    echo "Nada a fazer."
    exit 0
fi

command -v docker >/dev/null 2>&1 || { echo "FALHA: docker nao encontrado." >&2; exit 2; }
if ! docker image inspect "$OFFHOST_IMAGE" >/dev/null 2>&1; then
    echo "FALHA: imagem '$OFFHOST_IMAGE' nao esta presente neste host." >&2
    echo "       Prepare-a antes: docker build -t $OFFHOST_IMAGE ops/offhost" >&2
    exit 2
fi

# Diretorio temporario SO para o download de verificacao — nunca o diretorio
# do pacote original. Removido no fim, sucesso ou falha.
TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/facilpi-offhost-verify.XXXXXX")"
limpar() { rm -rf -- "$TEMP_DIR"; }
trap limpar EXIT INT TERM

# Filtro opcional de versao. Se o pendente nao capturou um VersionId (nao
# deveria acontecer — a Backblaze documenta que PutObject sempre o retorna
# — mas o codigo nao presume), a verificacao opera sobre a versao ATUAL do
# objeto por bucket+key, sem jamais listar para descobrir uma versao.
if [ -n "$REMOTE_VERSION_ID" ] && [ "$REMOTE_VERSION_ID" != "None" ] && [ "$REMOTE_VERSION_ID" != "null" ]; then
    set -- --version-id "$REMOTE_VERSION_ID"
else
    set --
    echo "AVISO: nenhum VersionId no estado pendente; verificando a versao atual" >&2
    echo "       de $REMOTE_KEY (sem LIST — apenas bucket+key)." >&2
fi

executar_aws() {
    AWS_ACCESS_KEY_ID="$B2_KEY_ID" \
    AWS_SECRET_ACCESS_KEY="$B2_APP_KEY" \
    AWS_DEFAULT_REGION="$REMOTE_REGION" \
    docker run --rm \
        -e AWS_ACCESS_KEY_ID \
        -e AWS_SECRET_ACCESS_KEY \
        -e AWS_DEFAULT_REGION \
        -v "$TEMP_DIR:/dados" \
        "$OFFHOST_IMAGE" \
        aws "$@"
}

echo "objeto      s3://$REMOTE_BUCKET/$REMOTE_KEY"
[ -n "$REMOTE_VERSION_ID" ] && [ "$REMOTE_VERSION_ID" != "None" ] && [ "$REMOTE_VERSION_ID" != "null" ] && echo "version_id  $REMOTE_VERSION_ID"

# --- [A/C] GetObjectRetention --------------------------------------------------
echo "[A/C] GetObjectRetention — confirmando Object Lock"
set +e
RETENCAO="$(executar_aws s3api get-object-retention \
    --endpoint-url "$REMOTE_ENDPOINT" \
    --bucket "$REMOTE_BUCKET" \
    --key "$REMOTE_KEY" \
    "$@" \
    --query "[Retention.Mode,Retention.RetainUntilDate]" \
    --output text 2>&1)"
CODIGO=$?
set -e
if [ "$CODIGO" -ne 0 ]; then
    echo "FALHA: GetObjectRetention nao retornou sucesso (codigo $CODIGO)." >&2
    echo "$RETENCAO" >&2
    echo "Nao gravando marcador de sucesso." >&2
    exit 1
fi
MODE_OBTIDO="$(printf '%s' "$RETENCAO" | awk '{print $1}')"
RETAIN_OBTIDO="$(printf '%s' "$RETENCAO" | awk '{print $2}')"

if [ "$MODE_OBTIDO" != "$LOCK_MODE_ESPERADO" ]; then
    echo "FALHA: Object Lock Mode divergente." >&2
    echo "       esperado=$LOCK_MODE_ESPERADO  obtido=$MODE_OBTIDO" >&2
    echo "Nao gravando marcador de sucesso." >&2
    exit 1
fi

# Comparacao por INSTANTE, nao por string: formatos ISO-8601 variam (com/sem
# fracao de segundo, "Z" vs "+00:00") sem deixar de ser o mesmo momento.
# Divergencia real de data continua reprovada.
EPOCH_ESPERADO="$(date -u -d "$RETAIN_ESPERADO" +%s 2>/dev/null || true)"
EPOCH_OBTIDO="$(date -u -d "$RETAIN_OBTIDO" +%s 2>/dev/null || true)"
if [ -z "$EPOCH_ESPERADO" ] || [ -z "$EPOCH_OBTIDO" ]; then
    echo "FALHA: nao foi possivel interpretar RetainUntilDate para comparacao." >&2
    echo "       esperado=$RETAIN_ESPERADO  obtido=$RETAIN_OBTIDO" >&2
    echo "Nao gravando marcador de sucesso." >&2
    exit 1
fi
if [ "$EPOCH_ESPERADO" != "$EPOCH_OBTIDO" ]; then
    echo "FALHA: RetainUntilDate divergente." >&2
    echo "       esperado=$RETAIN_ESPERADO  obtido=$RETAIN_OBTIDO" >&2
    echo "Nao gravando marcador de sucesso." >&2
    exit 1
fi
echo "      mode=$MODE_OBTIDO  retain_until=$RETAIN_OBTIDO  (confere)"

# --- [B/C] HeadObject -----------------------------------------------------------
echo "[B/C] HeadObject — confirmando metadata e tamanho"
set +e
CABECALHO="$(executar_aws s3api head-object \
    --endpoint-url "$REMOTE_ENDPOINT" \
    --bucket "$REMOTE_BUCKET" \
    --key "$REMOTE_KEY" \
    "$@" \
    --checksum-mode ENABLED \
    --query "[ContentLength,VersionId,ChecksumSHA256]" \
    --output text 2>&1)"
CODIGO=$?
set -e
if [ "$CODIGO" -ne 0 ]; then
    echo "FALHA: HeadObject nao retornou sucesso (codigo $CODIGO)." >&2
    echo "$CABECALHO" >&2
    echo "Nao gravando marcador de sucesso." >&2
    exit 1
fi
CONTENT_LENGTH_OBTIDO="$(printf '%s' "$CABECALHO" | awk '{print $1}')"
VERSION_ID_OBTIDO="$(printf '%s' "$CABECALHO" | awk '{print $2}')"
CHECKSUM_OBTIDO="$(printf '%s' "$CABECALHO" | awk '{print $3}')"

if [ -n "$BYTES_ESPERADO" ] && [ "$CONTENT_LENGTH_OBTIDO" != "$BYTES_ESPERADO" ]; then
    echo "FALHA: ContentLength divergente." >&2
    echo "       esperado=$BYTES_ESPERADO  obtido=$CONTENT_LENGTH_OBTIDO" >&2
    echo "Nao gravando marcador de sucesso." >&2
    exit 1
fi

META_SHA="$(executar_aws s3api head-object \
    --endpoint-url "$REMOTE_ENDPOINT" --bucket "$REMOTE_BUCKET" --key "$REMOTE_KEY" "$@" \
    --query "Metadata.sha256" --output text 2>/dev/null || echo "")"
META_RECIPIENT="$(executar_aws s3api head-object \
    --endpoint-url "$REMOTE_ENDPOINT" --bucket "$REMOTE_BUCKET" --key "$REMOTE_KEY" "$@" \
    --query 'Metadata."age-recipient"' --output text 2>/dev/null || echo "")"
META_PACKAGE="$(executar_aws s3api head-object \
    --endpoint-url "$REMOTE_ENDPOINT" --bucket "$REMOTE_BUCKET" --key "$REMOTE_KEY" "$@" \
    --query "Metadata.package" --output text 2>/dev/null || echo "")"

if [ "$META_SHA" != "$SHA_ESPERADO" ]; then
    echo "FALHA: metadata sha256 divergente." >&2
    echo "       esperado=$SHA_ESPERADO  obtido=$META_SHA" >&2
    echo "Nao gravando marcador de sucesso." >&2
    exit 1
fi
if [ -n "$AGE_RECIPIENT_ESPERADO" ] && [ "$META_RECIPIENT" != "$AGE_RECIPIENT_ESPERADO" ]; then
    echo "FALHA: metadata age-recipient divergente." >&2
    echo "       esperado=$AGE_RECIPIENT_ESPERADO  obtido=$META_RECIPIENT" >&2
    echo "Nao gravando marcador de sucesso." >&2
    exit 1
fi
if [ -n "$PACKAGE_NAME" ] && [ "$META_PACKAGE" != "$PACKAGE_NAME" ]; then
    echo "FALHA: metadata package divergente." >&2
    echo "       esperado=$PACKAGE_NAME  obtido=$META_PACKAGE" >&2
    echo "Nao gravando marcador de sucesso." >&2
    exit 1
fi
echo "      content_length=$CONTENT_LENGTH_OBTIDO  metadata confere  checksum_sha256=$CHECKSUM_OBTIDO"

# --- [C/C] GetObject + SHA-256 local ---------------------------------------------
echo "[C/C] GetObject — baixando o artefato cifrado para verificar integridade"
# O artefato ja esta cifrado com age; baixa-lo de novo nao expoe nada que o
# desenho original ja nao assumisse como seguro em transito. NAO descriptografa
# aqui — isto verifica o artefato remoto CIFRADO, nao o conteudo do backup.
set +e
executar_aws s3api get-object \
    --endpoint-url "$REMOTE_ENDPOINT" \
    --bucket "$REMOTE_BUCKET" \
    --key "$REMOTE_KEY" \
    "$@" \
    /dados/artefato.tar.age >/dev/null 2>"$TEMP_DIR/get-object-stderr.txt"
CODIGO=$?
set -e
if [ "$CODIGO" -ne 0 ]; then
    echo "FALHA: GetObject nao retornou sucesso (codigo $CODIGO)." >&2
    cat "$TEMP_DIR/get-object-stderr.txt" >&2
    echo "Nao gravando marcador de sucesso." >&2
    exit 1
fi

SHA_OBTIDO="$(sha256sum "$TEMP_DIR/artefato.tar.age" | cut -d' ' -f1)"
if [ "$SHA_OBTIDO" != "$SHA_ESPERADO" ]; then
    echo "FALHA: SHA-256 do artefato baixado diverge do calculado antes do upload." >&2
    echo "       esperado=$SHA_ESPERADO" >&2
    echo "       obtido  =$SHA_OBTIDO" >&2
    echo "Nao gravando marcador de sucesso." >&2
    exit 1
fi
echo "      sha256=$SHA_OBTIDO  (confere byte a byte com o pre-upload)"

# --- sucesso: promover PENDING -> VERIFIED --------------------------------------
echo ""
echo "VERIFIED  $REMOTE_KEY"

cat > "$MANIFESTO_OFFHOST" <<JSON
{
  "offhost_format_version": 2,
  "state": "VERIFIED",
  "package_name": "$PACKAGE_NAME",
  "encryption": "age",
  "encryption_recipient": "$AGE_RECIPIENT_ESPERADO",
  "encrypted_artifact_sha256": "$SHA_ESPERADO",
  "encrypted_artifact_bytes": $BYTES_ESPERADO,
  "remote_provider": "backblaze-b2",
  "remote_bucket": "$REMOTE_BUCKET",
  "remote_endpoint": "$REMOTE_ENDPOINT",
  "remote_key": "$REMOTE_KEY",
  "remote_version_id": "$VERSION_ID_OBTIDO",
  "object_lock_mode": "$MODE_OBTIDO",
  "retain_until": "$RETAIN_OBTIDO",
  "verified_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "restore_notes": "baixar com ops/offhost_fetch.sh FORA da VPS, com a credencial de leitura e a chave privada age sob custodia separada; conferir o sha256 ANTES de decifrar"
}
JSON

date -u +%Y-%m-%dT%H:%M:%SZ > "$MARCADOR"

if [ -n "$SENTINELA" ]; then
    if mkdir -p "$(dirname "$SENTINELA")" 2>/dev/null && date -u +%Y-%m-%dT%H:%M:%SZ > "$SENTINELA" 2>/dev/null; then
        echo "sentinela atualizada: $SENTINELA"
    else
        echo "AVISO: nao foi possivel atualizar a sentinela $SENTINELA." >&2
    fi
fi

echo "marcador: $MARCADOR"
echo "manifesto: $MANIFESTO_OFFHOST"
