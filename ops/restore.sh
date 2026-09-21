#!/usr/bin/env sh
# FacILPI — restore de um pacote de backup em ambiente NOVO.
#
# Destina-se a um ambiente VAZIO: banco sem esquema e volume de anexos novo.
# NUNCA restaure por cima do ambiente de origem — o restore nao foi projetado
# para mesclar, e um pg_restore sobre esquema existente falha ou duplica.
#
# ORDEM E MOTIVO (decidido no PLAN, nao por preferencia):
#   1. verificar checksums   — pacote corrompido nao chega a tocar o banco
#   2. pg_restore            — o dump JA carrega esquema e alembic_version
#   3. extrair anexos + dono
# Nao rodar `alembic upgrade head` ANTES: o banco vazio ganharia o esquema e o
# pg_restore colidiria com objetos existentes. Depois, na mesma versao, e no-op.
#
# Uso:
#   ops/restore.sh -p <projeto-compose> -e <arquivo .env> -b <pacote de backup>
set -eu

# Git Bash (MSYS) reescreve argumentos que parecem caminho POSIX antes de
# entregar ao docker, e `/saida/arquivo` viraria `C:/Program Files/Git/saida/...`.
# Em Linux a variavel nao existe e a linha e inofensiva; no Windows ela e o que
# permite rodar o mesmo script sem uma segunda versao.
export MSYS_NO_PATHCONV=1

PROJETO=""
ARQUIVO_ENV=".env"
PACOTE=""

while [ $# -gt 0 ]; do
    case "$1" in
        -p) PROJETO="$2"; shift 2 ;;
        -e) ARQUIVO_ENV="$2"; shift 2 ;;
        -b) PACOTE="$2"; shift 2 ;;
        *) echo "argumento desconhecido: $1" >&2; exit 2 ;;
    esac
done

[ -n "$PROJETO" ] || { echo "falta -p <projeto-compose>" >&2; exit 2; }
[ -n "$PACOTE" ] || { echo "falta -b <pacote de backup>" >&2; exit 2; }
[ -d "$PACOTE" ] || { echo "pacote nao encontrado: $PACOTE" >&2; exit 2; }
[ -f "$ARQUIVO_ENV" ] || { echo "arquivo de ambiente nao encontrado: $ARQUIVO_ENV" >&2; exit 2; }

ler_env() {
    sed -n "s/^$1=//p" "$ARQUIVO_ENV" | head -1
}

PG_USER="$(ler_env POSTGRES_USER)"
PG_DB="$(ler_env POSTGRES_DB)"
[ -n "$PG_USER" ] || { echo "POSTGRES_USER ausente em $ARQUIVO_ENV" >&2; exit 2; }
[ -n "$PG_DB" ] || { echo "POSTGRES_DB ausente em $ARQUIVO_ENV" >&2; exit 2; }

COMPOSE="docker compose -p $PROJETO --env-file $ARQUIVO_ENV"
VOLUME_UPLOADS="${PROJETO}_facilpi_pilot_data"

echo "[1/4] verificando integridade do pacote"
# FAIL CLOSED: divergencia de checksum encerra aqui, antes de qualquer escrita.
if ! ( cd "$PACOTE" && sha256sum -c SHA256SUMS ); then
    echo "FALHA: checksums divergentes. O pacote NAO sera restaurado." >&2
    exit 1
fi
CABECA_ESPERADA="$(sed -n 's/.*"alembic_head": "\([^"]*\)".*/\1/p' "$PACOTE/manifest.json")"
SHA_APP="$(sed -n 's/.*"app_git_sha": "\([^"]*\)".*/\1/p' "$PACOTE/manifest.json")"
echo "     manifesto: alembic_head=$CABECA_ESPERADA app_git_sha=$SHA_APP"

echo "[2/4] restaurando banco (pg_restore --no-owner --no-acl)"
# --no-owner/--no-acl desacoplam do nome do papel de origem: o ambiente novo pode
# ter outro usuario e outra senha sem que o dump precise ser editado.
$COMPOSE exec -T db pg_restore -U "$PG_USER" -d "$PG_DB" --no-owner --no-acl < "$PACOTE/database.dump"

echo "[3/4] restaurando anexos e corrigindo dono"
# 10001 e o UID/GID do usuario `app` da imagem do backend. Sem o chown, o
# conteudo volta com dono errado e o backend nao consegue anexar nada novo.
docker run --rm \
    -v "$VOLUME_UPLOADS:/dados" \
    -v "$PACOTE:/entrada:ro" \
    alpine:3.20 \
    sh -c 'tar -xzf /entrada/uploads.tar.gz -C /dados && chown -R 10001:10001 /dados'

echo "[4/4] conferindo estado do banco restaurado"
CABECA_RESTAURADA="$($COMPOSE exec -T db psql -U "$PG_USER" -d "$PG_DB" -tAc 'SELECT version_num FROM alembic_version' | tr -d '\r')"
echo "     alembic_version restaurado: $CABECA_RESTAURADA"
if [ "$CABECA_RESTAURADA" != "$CABECA_ESPERADA" ]; then
    echo "FALHA: head restaurado difere do manifesto ($CABECA_ESPERADA)." >&2
    exit 1
fi

echo "OK  restore concluido."
echo "Nao execute 'alembic upgrade head' para recuperar a MESMA versao: e no-op."
echo "So execute se estiver deliberadamente subindo o backup em versao mais nova."
