#!/usr/bin/env sh
# FacILPI — backup do ambiente (banco + anexos + manifesto + checksums).
#
# ORDEM É CONTRATO, não estilo: dump do banco PRIMEIRO, snapshot dos uploads
# DEPOIS. O upload promove o arquivo para o destino final ANTES de commitar o
# registro (main.py), e nenhum caminho de producao apaga anexo — entao nesta
# ordem o pior caso e um arquivo orfao no pacote, inofensivo. Na ordem inversa o
# pior caso seria uma linha do banco apontando para arquivo que nao foi copiado,
# o que a aplicacao exibiria como documento quebrado. Por isso o piloto NAO
# precisa de janela de manutencao — precisa desta ordem.
#
# Uso:
#   ops/backup.sh -p <projeto-compose> -e <arquivo .env> -d <diretorio destino>
#
# Nao recebe nem grava segredo algum: usuario e banco saem do arquivo de
# ambiente, e a senha nunca transita por argumento.
set -eu

# Git Bash (MSYS) reescreve argumentos que parecem caminho POSIX antes de
# entregar ao docker, e `/saida/arquivo` viraria `C:/Program Files/Git/saida/...`.
# Em Linux a variavel nao existe e a linha e inofensiva; no Windows ela e o que
# permite rodar o mesmo script sem uma segunda versao.
export MSYS_NO_PATHCONV=1

PROJETO=""
ARQUIVO_ENV=".env"
DESTINO=""

while [ $# -gt 0 ]; do
    case "$1" in
        -p) PROJETO="$2"; shift 2 ;;
        -e) ARQUIVO_ENV="$2"; shift 2 ;;
        -d) DESTINO="$2"; shift 2 ;;
        *) echo "argumento desconhecido: $1" >&2; exit 2 ;;
    esac
done

[ -n "$PROJETO" ] || { echo "falta -p <projeto-compose>" >&2; exit 2; }
[ -n "$DESTINO" ] || { echo "falta -d <diretorio destino>" >&2; exit 2; }
[ -f "$ARQUIVO_ENV" ] || { echo "arquivo de ambiente nao encontrado: $ARQUIVO_ENV" >&2; exit 2; }

ler_env() {
    # Le uma chave do arquivo de ambiente sem dar source nele: o arquivo contem
    # senha, e um `source` exportaria tudo para o processo e para os filhos.
    sed -n "s/^$1=//p" "$ARQUIVO_ENV" | head -1
}

# Traduz um caminho do SHELL para a forma que o DOCKER precisa receber em `-v`.
#
# Em Linux os dois textos sao identicos e esta funcao nao faz nada. Em Git
# Bash/MSYS + Docker Desktop NAO sao: um caminho interno do MSYS (ex.:
# /tmp/...) chega cru ao `docker` por causa de MSYS_NO_PATHCONV=1 e e resolvido
# DENTRO da VM Linux do Docker — o container escreve num diretorio que o host
# nunca enxerga. Foi a falha do GATE-3Y. `pwd -W` (builtin do MSYS) devolve a
# forma Windows (C:/...), que o Docker Desktop mapeia para o MESMO diretorio
# que o shell le; em Linux o builtin nao existe e o caminho original vale.
#
# Duplicada de proposito em cada script de ops/, como `ler_env`: estes scripts
# sao auto-contidos para sobreviverem a uma copia avulsa no dia do desastre.
# `ops/offhost_test.sh` tem um teste que reprova se alguma montagem de caminho
# de host deixar de usar a forma convertida.
caminho_para_montagem() {
    CAMINHO_MONTE="$1"
    if CAMINHO_WINDOWS="$(cd "$1" && pwd -W 2>/dev/null)"; then
        case "$CAMINHO_WINDOWS" in
            ?:/*) CAMINHO_MONTE="$CAMINHO_WINDOWS" ;;
        esac
    fi
    printf '%s' "$CAMINHO_MONTE"
}

PG_USER="$(ler_env POSTGRES_USER)"
PG_DB="$(ler_env POSTGRES_DB)"
AMBIENTE="$(ler_env ENVIRONMENT)"
RAIZ_UPLOAD="$(ler_env UPLOAD_ROOT)"
[ -n "$RAIZ_UPLOAD" ] || RAIZ_UPLOAD="/data/uploads"
[ -n "$PG_USER" ] || { echo "POSTGRES_USER ausente em $ARQUIVO_ENV" >&2; exit 2; }
[ -n "$PG_DB" ] || { echo "POSTGRES_DB ausente em $ARQUIVO_ENV" >&2; exit 2; }

COMPOSE="docker compose -p $PROJETO --env-file $ARQUIVO_ENV"
VOLUME_UPLOADS="${PROJETO}_facilpi_pilot_data"

CARIMBO="$(date -u +%Y%m%dT%H%M%SZ)"
PACOTE="$DESTINO/facilpi-backup-$CARIMBO"
mkdir -p "$PACOTE"
# Absoluto porque `docker run -v` rejeita caminho relativo — um `-d .` quebraria
# o snapshot dos anexos. PACOTE_MONTE e a forma que vai NO `-v`; o resto do
# script continua usando PACOTE.
PACOTE="$(cd "$PACOTE" && pwd)"
PACOTE_MONTE="$(caminho_para_montagem "$PACOTE")"

echo "[1/4] dump do banco (pg_dump -Fc, dentro do container db)"
# Executado DENTRO do container: a versao do cliente casa com a do servidor por
# construcao, em vez de virar uma segunda coisa para manter alinhada no host.
# `.parcial` ate o fim: um backup interrompido nunca parece completo.
$COMPOSE exec -T db pg_dump -U "$PG_USER" -d "$PG_DB" -Fc > "$PACOTE/database.dump.parcial"
mv "$PACOTE/database.dump.parcial" "$PACOTE/database.dump"

# FAIL CLOSED: o dump precisa ser mesmo um archive custom (-Fc), nao um arquivo
# de texto que so PARECE um backup. O GATE-3Y provou o custo de descobrir isso
# tarde: um pacote inteiro foi cifrado, enviado e travado por Object Lock
# carregando um `database.dump` que o `pg_restore` jamais aceitaria. Duas
# checagens independentes e baratas, aqui, antes de qualquer coisa irreversivel.
if [ "$(head -c 5 "$PACOTE/database.dump")" != "PGDMP" ]; then
    echo "FALHA: database.dump nao comeca com PGDMP — nao e um archive pg_dump -Fc." >&2
    echo "       Backup abortado ANTES do manifesto. Nada sera declarado valido." >&2
    exit 1
fi
# `pg_restore --list` le o indice do archive: se o arquivo estiver truncado ou
# corrompido, falha aqui em vez de no dia da recuperacao. Roda DENTRO do
# container db (mesma versao do servidor) e recebe o dump por stdin, sem mount.
if ! $COMPOSE exec -T db pg_restore --list > /dev/null 2>&1 < "$PACOTE/database.dump"; then
    echo "FALHA: 'pg_restore --list' recusou o database.dump." >&2
    echo "       O archive existe mas nao e legivel como custom format." >&2
    exit 1
fi

echo "[2/4] snapshot dos anexos (somente leitura)"
# Container efemero monta o volume :ro — o backup nao pode alterar o que copia.
docker run --rm \
    -v "$VOLUME_UPLOADS:/dados:ro" \
    -v "$PACOTE_MONTE:/saida" \
    alpine:3.20 \
    tar -czf /saida/uploads.tar.gz.parcial -C /dados uploads
mv "$PACOTE/uploads.tar.gz.parcial" "$PACOTE/uploads.tar.gz"

echo "[3/4] manifesto"
VERSAO_PG="$($COMPOSE exec -T db psql -U "$PG_USER" -d "$PG_DB" -tAc 'SHOW server_version' | tr -d '\r')"
CABECA_ALEMBIC="$($COMPOSE exec -T db psql -U "$PG_USER" -d "$PG_DB" -tAc 'SELECT version_num FROM alembic_version' | tr -d '\r')"
SHA_APP="$(git rev-parse HEAD 2>/dev/null || echo desconhecido)"
CONTAGEM_ARQUIVOS="$(docker run --rm -v "$VOLUME_UPLOADS:/dados:ro" alpine:3.20 sh -c 'find /dados/uploads -type f 2>/dev/null | wc -l' | tr -d ' \r')"
BYTES_ARQUIVOS="$(docker run --rm -v "$VOLUME_UPLOADS:/dados:ro" alpine:3.20 sh -c 'find /dados/uploads -type f -exec cat {} + 2>/dev/null | wc -c' | tr -d ' \r')"
SHA_DUMP="$(sha256sum "$PACOTE/database.dump" | cut -d' ' -f1)"
SHA_UPLOADS="$(sha256sum "$PACOTE/uploads.tar.gz" | cut -d' ' -f1)"

# FAIL CLOSED: sem alembic_head o pacote nao e restauravel com verificacao —
# `ops/restore.sh` compara o head restaurado contra este campo, e um valor
# vazio transformaria essa checagem em teatro.
[ -n "$CABECA_ALEMBIC" ] || {
    echo "FALHA: alembic_version vazio no banco de origem." >&2
    echo "       Um pacote sem alembic_head nao pode ser validado no restore." >&2
    exit 1
}

# Nenhum segredo entra aqui: nem senha, nem JWT_SECRET, nem DATABASE_URL.
cat > "$PACOTE/manifest.json" <<JSON
{
  "backup_format_version": 1,
  "backup_timestamp": "$CARIMBO",
  "app_git_sha": "$SHA_APP",
  "alembic_head": "$CABECA_ALEMBIC",
  "database_engine": "PostgreSQL",
  "postgres_version": "$VERSAO_PG",
  "environment": "$AMBIENTE",
  "db_backup_format": "custom (-Fc)",
  "upload_root": "$RAIZ_UPLOAD",
  "db_dump_file": "database.dump",
  "db_dump_sha256": "$SHA_DUMP",
  "uploads_archive": "uploads.tar.gz",
  "uploads_archive_sha256": "$SHA_UPLOADS",
  "uploads_file_count": $CONTAGEM_ARQUIVOS,
  "uploads_total_bytes": $BYTES_ARQUIVOS,
  "restore_notes": "pg_restore --no-owner --no-acl em banco VAZIO; nao executar alembic upgrade antes do restore"
}
JSON

echo "[4/4] checksums"
# O manifesto tambem entra no SHA256SUMS: sem isso, alterar o manifesto (e com
# ele os hashes que ele declara) passaria despercebido.
( cd "$PACOTE" && sha256sum database.dump uploads.tar.gz manifest.json > SHA256SUMS )

echo "OK  $PACOTE"
echo "alembic_head=$CABECA_ALEMBIC  arquivos=$CONTAGEM_ARQUIVOS  postgres=$VERSAO_PG"
