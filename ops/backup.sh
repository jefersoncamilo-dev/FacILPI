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

echo "[1/4] dump do banco (pg_dump -Fc, dentro do container db)"
# Executado DENTRO do container: a versao do cliente casa com a do servidor por
# construcao, em vez de virar uma segunda coisa para manter alinhada no host.
# `.parcial` ate o fim: um backup interrompido nunca parece completo.
$COMPOSE exec -T db pg_dump -U "$PG_USER" -d "$PG_DB" -Fc > "$PACOTE/database.dump.parcial"
mv "$PACOTE/database.dump.parcial" "$PACOTE/database.dump"

echo "[2/4] snapshot dos anexos (somente leitura)"
# Container efemero monta o volume :ro — o backup nao pode alterar o que copia.
docker run --rm \
    -v "$VOLUME_UPLOADS:/dados:ro" \
    -v "$PACOTE:/saida" \
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
