#!/usr/bin/env sh
# FacILPI — recuperacao de um pacote de backup a partir do Backblaze B2.
#
# ESTE SCRIPT NAO RODA NA VPS. Ele usa a credencial de LEITURA e a chave PRIVADA
# age, e nenhuma das duas pode existir no host que faz o upload. Rodar isto na
# VPS anularia toda a separacao de custodia: quem comprometesse a VPS passaria a
# ler todos os backups.
#
# Entrega um diretorio de pacote que `ops/restore.sh` consome SEM ALTERACAO.
#
# Uso:
#   ops/offhost_fetch.sh -k <chave remota> -e <env restore> -i <identidade age> -d <destino>
#   ops/offhost_fetch.sh -m <offhost_manifest.json> -e <env restore> -i <identidade age> -d <destino>
#
# ORDEM E CONTRATO:
#   1. baixar
#   2. conferir SHA-256 ANTES de decifrar
#   3. decifrar
#   4. extrair
#   5. reconferir o SHA256SUMS interno do pacote
# Conferir o hash antes de decifrar separa "chegou corrompido" de "a chave esta
# errada" — dois problemas com respostas completamente diferentes no dia do
# desastre.
set -eu

export MSYS_NO_PATHCONV=1

CHAVE_REMOTA=""
MANIFESTO=""
ARQUIVO_ENV=""
IDENTIDADE=""
DESTINO=""

uso() {
    echo "uso: ops/offhost_fetch.sh (-k <chave remota> | -m <offhost_manifest.json>) -e <env restore> -i <identidade age> -d <destino>" >&2
    exit 2
}

while [ $# -gt 0 ]; do
    case "$1" in
        -k) CHAVE_REMOTA="${2:-}"; shift 2 ;;
        -m) MANIFESTO="${2:-}"; shift 2 ;;
        -e) ARQUIVO_ENV="${2:-}"; shift 2 ;;
        -i) IDENTIDADE="${2:-}"; shift 2 ;;
        -d) DESTINO="${2:-}"; shift 2 ;;
        -h|--help) uso ;;
        *) echo "argumento desconhecido: $1" >&2; uso ;;
    esac
done

[ -n "$ARQUIVO_ENV" ] || { echo "falta -e <env restore>" >&2; uso; }
[ -n "$IDENTIDADE" ] || { echo "falta -i <identidade age>" >&2; uso; }
[ -n "$DESTINO" ] || { echo "falta -d <destino>" >&2; uso; }
[ -f "$ARQUIVO_ENV" ] || { echo "arquivo de ambiente nao encontrado: $ARQUIVO_ENV" >&2; exit 2; }
[ -f "$IDENTIDADE" ] || { echo "identidade age nao encontrada: $IDENTIDADE" >&2; exit 2; }

SHA_ESPERADO=""
if [ -n "$MANIFESTO" ]; then
    [ -f "$MANIFESTO" ] || { echo "manifesto nao encontrado: $MANIFESTO" >&2; exit 2; }
    [ -n "$CHAVE_REMOTA" ] || CHAVE_REMOTA="$(sed -n 's/.*"remote_key": "\([^"]*\)".*/\1/p' "$MANIFESTO")"
    SHA_ESPERADO="$(sed -n 's/.*"encrypted_artifact_sha256": "\([^"]*\)".*/\1/p' "$MANIFESTO")"
fi
[ -n "$CHAVE_REMOTA" ] || { echo "falta -k <chave remota> (ou um manifesto que a contenha)" >&2; uso; }

ler_env() {
    sed -n "s/^$1=//p" "$ARQUIVO_ENV" | head -1
}

B2_ENDPOINT="$(ler_env B2_ENDPOINT)"
B2_REGION="$(ler_env B2_REGION)"
B2_BUCKET="$(ler_env B2_BUCKET)"
OFFHOST_RUNTIME="$(ler_env OFFHOST_RUNTIME)"
OFFHOST_IMAGE="$(ler_env OFFHOST_IMAGE)"
[ -n "$OFFHOST_RUNTIME" ] || OFFHOST_RUNTIME="local"
[ -n "$OFFHOST_IMAGE" ] || OFFHOST_IMAGE="facilpi/offhost:1"
case "$OFFHOST_RUNTIME" in
    local|container) ;;
    *) echo "FALHA: OFFHOST_RUNTIME invalido: '$OFFHOST_RUNTIME' (use local ou container)" >&2; exit 2 ;;
esac

B2_KEY_ID="$(ler_env B2_KEY_ID)"
B2_APP_KEY="$(ler_env B2_APP_KEY)"
[ -n "$B2_KEY_ID" ] || { echo "FALHA: B2_KEY_ID ausente em $ARQUIVO_ENV" >&2; exit 2; }
[ -n "$B2_APP_KEY" ] || { echo "FALHA: B2_APP_KEY ausente em $ARQUIVO_ENV" >&2; exit 2; }
[ -n "$B2_BUCKET" ] || { echo "FALHA: B2_BUCKET ausente em $ARQUIVO_ENV" >&2; exit 2; }
[ -n "$B2_ENDPOINT" ] || { echo "FALHA: B2_ENDPOINT ausente em $ARQUIVO_ENV" >&2; exit 2; }
[ -n "$B2_REGION" ] || { echo "FALHA: B2_REGION ausente em $ARQUIVO_ENV" >&2; exit 2; }

# --- runtime ------------------------------------------------------------------
# PADRAO E `local`, e isso e uma decisao de seguranca, nao de conveniencia.
#
# No upload so o recipient PUBLICO circula, entao container nao expoe nada. Aqui
# e diferente: decifrar exige a chave PRIVADA, que decifra TODOS os backups
# off-host. Em modo container ela teria de ser bind-montada para dentro de uma
# imagem — superficie que o modo local simplesmente nao tem.
if [ "$OFFHOST_RUNTIME" = "local" ]; then
    command -v age >/dev/null 2>&1 || {
        echo "FALHA: 'age' nao encontrado neste ambiente." >&2
        echo "       Instale o age (https://github.com/FiloSottile/age) — e a forma" >&2
        echo "       recomendada, porque mantem a chave privada fora de container." >&2
        echo "       Alternativa consciente: OFFHOST_RUNTIME=container, que exige" >&2
        echo "       montar a chave privada na imagem. Ver docs/RUNBOOK_OFFHOST.md." >&2
        exit 2
    }
    command -v aws >/dev/null 2>&1 || { echo "FALHA: 'aws' (AWS CLI v2) nao encontrado neste ambiente." >&2; exit 2; }
else
    command -v docker >/dev/null 2>&1 || { echo "FALHA: docker nao encontrado, e OFFHOST_RUNTIME=container." >&2; exit 2; }
    docker image inspect "$OFFHOST_IMAGE" >/dev/null 2>&1 || {
        echo "FALHA: imagem '$OFFHOST_IMAGE' ausente. Construa com:" >&2
        echo "           docker build -t $OFFHOST_IMAGE ops/offhost" >&2
        exit 2
    }
    echo "AVISO: OFFHOST_RUNTIME=container." >&2
    echo "       A chave privada age sera montada DENTRO do container para a" >&2
    echo "       decifra. Ela decifra todos os backups off-host. Prefira o modo" >&2
    echo "       'local' sempre que houver um binario age disponivel." >&2
fi

# Executa uma ferramenta no runtime escolhido. Em modo container, `$DESTINO` e o
# diretorio da identidade sao montados; em modo local nao ha nenhuma montagem.
executar_age() {
    if [ "$OFFHOST_RUNTIME" = "local" ]; then
        age "$@"
    else
        docker run --rm -i \
            -v "$DESTINO:/dados" \
            -v "$DIR_IDENTIDADE:/chave:ro" \
            "$OFFHOST_IMAGE" age "$@"
    fi
}

executar_aws() {
    if [ "$OFFHOST_RUNTIME" = "local" ]; then
        AWS_ACCESS_KEY_ID="$B2_KEY_ID" \
        AWS_SECRET_ACCESS_KEY="$B2_APP_KEY" \
        AWS_DEFAULT_REGION="$B2_REGION" \
        aws "$@"
    else
        # Mesma regra do upload: `-e NOME`, nunca `-e NOME=valor`.
        AWS_ACCESS_KEY_ID="$B2_KEY_ID" \
        AWS_SECRET_ACCESS_KEY="$B2_APP_KEY" \
        AWS_DEFAULT_REGION="$B2_REGION" \
        docker run --rm \
            -e AWS_ACCESS_KEY_ID \
            -e AWS_SECRET_ACCESS_KEY \
            -e AWS_DEFAULT_REGION \
            -v "$DESTINO:/dados" \
            "$OFFHOST_IMAGE" aws "$@"
    fi
}

# A identidade age e a chave que decifra TODOS os backups off-host. Se ela
# estiver legivel por outros usuarios da maquina, o problema nao e este restore
# — e a custodia inteira.
PERMISSOES="$(stat -c '%a' "$IDENTIDADE" 2>/dev/null || echo "")"
case "$PERMISSOES" in
    ""|600|400) ;;
    *) echo "AVISO: $IDENTIDADE esta com permissao $PERMISSOES. A chave privada age" >&2
       echo "       deveria ser 0600. Ela decifra TODOS os backups off-host." >&2 ;;
esac

mkdir -p "$DESTINO"
# Caminhos absolutos: `docker run -v` nao aceita caminho relativo, e o modo
# local nao perde nada com isso.
DESTINO="$(cd "$DESTINO" && pwd)"
DIR_IDENTIDADE="$(cd "$(dirname "$IDENTIDADE")" && pwd)"
NOME_IDENTIDADE="$(basename "$IDENTIDADE")"
NOME_ARTEFATO="$(basename "$CHAVE_REMOTA")"
ARTEFATO="$DESTINO/$NOME_ARTEFATO"
PARCIAL="$ARTEFATO.parcial"

# Onde cada ferramenta enxerga o diretorio de trabalho: no modo local e o
# proprio caminho do host; no modo container e o ponto de montagem.
if [ "$OFFHOST_RUNTIME" = "local" ]; then
    VISAO_DESTINO="$DESTINO"
    VISAO_IDENTIDADE="$IDENTIDADE"
else
    VISAO_DESTINO="/dados"
    VISAO_IDENTIDADE="/chave/$NOME_IDENTIDADE"
fi

limpar() { rm -f "$PARCIAL"; }
trap limpar EXIT INT TERM

# --- [1/5] download -----------------------------------------------------------
echo "[1/5] baixando s3://$B2_BUCKET/$CHAVE_REMOTA"
rm -f "$PARCIAL"
executar_aws s3api get-object \
    --endpoint-url "$B2_ENDPOINT" \
    --bucket "$B2_BUCKET" \
    --key "$CHAVE_REMOTA" \
    "$VISAO_DESTINO/$NOME_ARTEFATO.parcial" >/dev/null
mv "$PARCIAL" "$ARTEFATO"
trap - EXIT INT TERM

# --- [2/5] integridade do artefato cifrado ------------------------------------
echo "[2/5] conferindo SHA-256 ANTES de decifrar"
if [ -z "$SHA_ESPERADO" ]; then
    # Sem manifesto local, o hash vem da metadata propria do objeto. O ETag NAO
    # e usado em nenhuma hipotese: ele nao e SHA-256 e, em multipart, nao e nem
    # um hash do conteudo.
    echo "      sem manifesto local; lendo a metadata propria do objeto"
    SHA_ESPERADO="$(
        executar_aws s3api head-object \
            --endpoint-url "$B2_ENDPOINT" \
            --bucket "$B2_BUCKET" \
            --key "$CHAVE_REMOTA" \
            --query "Metadata.sha256" \
            --output text 2>/dev/null || echo ""
    )"
    SHA_ESPERADO="$(printf '%s' "$SHA_ESPERADO" | tr -d ' \r\n')"
    [ "$SHA_ESPERADO" = "None" ] && SHA_ESPERADO=""
fi

SHA_OBTIDO="$(sha256sum "$ARTEFATO" | cut -d' ' -f1)"
if [ -z "$SHA_ESPERADO" ]; then
    echo "FALHA: nao foi possivel obter o SHA-256 esperado, nem do manifesto local" >&2
    echo "       nem da metadata do objeto. Recuperar sem poder verificar a" >&2
    echo "       integridade nao e recuperacao — e esperanca." >&2
    exit 1
fi
if [ "$SHA_OBTIDO" != "$SHA_ESPERADO" ]; then
    echo "FALHA: SHA-256 divergente." >&2
    echo "       esperado=$SHA_ESPERADO" >&2
    echo "       obtido  =$SHA_OBTIDO" >&2
    echo "       O artefato NAO sera decifrado." >&2
    exit 1
fi
echo "      sha256 confere: $SHA_OBTIDO"

# --- [3/5] decifra ------------------------------------------------------------
echo "[3/5] decifrando com a chave privada age"
TAR_CLARO="$DESTINO/$NOME_ARTEFATO.tar"
if ! executar_age -d -i "$VISAO_IDENTIDADE" "$VISAO_DESTINO/$NOME_ARTEFATO" > "$TAR_CLARO"; then
    rm -f "$TAR_CLARO"
    echo "FALHA ao decifrar. O SHA-256 ja conferiu, entao o artefato chegou intacto:" >&2
    echo "       a identidade age fornecida nao corresponde ao recipient usado no" >&2
    echo "       upload. Tente a outra copia custodiada da chave." >&2
    exit 1
fi

# --- [4/5] extracao -----------------------------------------------------------
echo "[4/5] extraindo o pacote"
tar -xf "$TAR_CLARO" -C "$DESTINO"
rm -f "$TAR_CLARO"
NOME_PACOTE="${NOME_ARTEFATO%.tar.age}"
PACOTE="$DESTINO/$NOME_PACOTE"
[ -d "$PACOTE" ] || { echo "FALHA: pacote esperado nao encontrado apos extracao: $PACOTE" >&2; exit 1; }

# --- [5/5] integridade interna ------------------------------------------------
echo "[5/5] reconferindo o SHA256SUMS interno do pacote"
# Segunda verificacao independente: a primeira provou que o artefato cifrado
# chegou intacto; esta prova que o conteudo dentro dele e o que o backup gravou.
if ! ( cd "$PACOTE" && sha256sum -c SHA256SUMS ); then
    echo "FALHA: checksums internos divergem. NAO restaure este pacote." >&2
    exit 1
fi

CABECA="$(sed -n 's/.*"alembic_head": "\([^"]*\)".*/\1/p' "$PACOTE/manifest.json")"
echo ""
echo "OK  $PACOTE"
echo "alembic_head=$CABECA"
echo ""
echo "Proximo passo — restore em ambiente NOVO e vazio:"
echo "  ops/restore.sh -p <projeto> -e <env novo> -b $PACOTE"
