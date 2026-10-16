#!/usr/bin/env sh
# FacILPI — retencao dos backups LOCAIS.
#
# O runbook ja especificava "7 diarios" desde o inicio, mas a politica existia
# apenas como texto: sem script, o disco do host enche e o backup para de
# funcionar exatamente quando passa a ser necessario.
#
# Uso:
#   ops/retencao_local.sh -d <diretorio de backups> [-k <manter>] [--apply]
#
# PADRAO E SIMULACAO. Este e o unico script do conjunto que APAGA coisas, entao
# nada e removido sem `--apply` explicito.
#
# TRAVAS (o runbook exige todas):
#   - age SOMENTE dentro do diretorio dedicado informado em -d;
#   - remove SOMENTE diretorios que casem `facilpi-backup-<UTC>`;
#   - remove SOMENTE se o diretorio contiver um `manifest.json`;
#   - NUNCA usa wildcard amplo, `find -delete` ou prune por prefixo de nome.
# Um diretorio com nome parecido mas sem `manifest.json` nao e um backup deste
# sistema, e este script nao tem nada a fazer com ele.
set -eu

export MSYS_NO_PATHCONV=1

DESTINO=""
MANTER=7
APLICAR=0

uso() {
    echo "uso: ops/retencao_local.sh -d <diretorio de backups> [-k <manter>] [--apply]" >&2
    exit 2
}

while [ $# -gt 0 ]; do
    case "$1" in
        -d) DESTINO="${2:-}"; shift 2 ;;
        -k) MANTER="${2:-}"; shift 2 ;;
        --apply) APLICAR=1; shift ;;
        -h|--help) uso ;;
        *) echo "argumento desconhecido: $1" >&2; uso ;;
    esac
done

[ -n "$DESTINO" ] || { echo "falta -d <diretorio de backups>" >&2; uso; }
[ -d "$DESTINO" ] || { echo "diretorio nao encontrado: $DESTINO" >&2; exit 2; }

case "$MANTER" in
    ''|*[!0-9]*) echo "FALHA: -k deve ser numerico (obtido '$MANTER')" >&2; exit 2 ;;
esac
# Manter zero backups seria "apagar tudo". Se e isso que se quer, o caminho e
# uma decisao humana explicita, nao um argumento deste script.
[ "$MANTER" -ge 1 ] || { echo "FALHA: -k deve ser >= 1. Este script nao apaga todos os backups." >&2; exit 2; }

DESTINO="$(cd "$DESTINO" && pwd)"

# Barreira contra o erro classico: apontar a retencao para a raiz, para o home
# ou para a arvore do projeto e sair apagando.
case "$DESTINO" in
    /|/root|/home|/usr|/var|/etc|/opt|/tmp)
        echo "FALHA: $DESTINO nao e um diretorio dedicado de backups." >&2; exit 2 ;;
esac
if [ -n "${HOME:-}" ] && [ "$DESTINO" = "$HOME" ]; then
    echo "FALHA: $DESTINO e o diretorio home, nao um diretorio dedicado de backups." >&2
    exit 2
fi
if [ -d "$DESTINO/.git" ]; then
    echo "FALHA: $DESTINO e a raiz de um repositorio git, nao um diretorio de backups." >&2
    exit 2
fi

# --- inventario ---------------------------------------------------------------
# Nome carimbado em UTC ordena cronologicamente por ordem lexicografica, entao
# `sort` basta e nao e preciso confiar em mtime (que um `cp` ou um rsync mudam).
PACOTES=""
TOTAL=0
IGNORADOS=0
for CAMINHO in "$DESTINO"/facilpi-backup-*; do
    [ -d "$CAMINHO" ] || continue
    NOME="$(basename "$CAMINHO")"
    # Formato exato: facilpi-backup-YYYYMMDDTHHMMSSZ
    case "$NOME" in
        facilpi-backup-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z) ;;
        *) echo "ignorado (nome fora do padrao): $NOME"; IGNORADOS=$((IGNORADOS + 1)); continue ;;
    esac
    if [ ! -f "$CAMINHO/manifest.json" ]; then
        echo "ignorado (sem manifest.json, nao e um pacote deste sistema): $NOME"
        IGNORADOS=$((IGNORADOS + 1))
        continue
    fi
    PACOTES="$PACOTES$NOME
"
    TOTAL=$((TOTAL + 1))
done

if [ "$TOTAL" -eq 0 ]; then
    echo "nenhum pacote valido em $DESTINO (ignorados: $IGNORADOS). Nada a fazer."
    exit 0
fi

ORDENADOS="$(printf '%s' "$PACOTES" | sort)"
EXCEDENTE=$((TOTAL - MANTER))

echo ""
echo "diretorio   $DESTINO"
echo "pacotes     $TOTAL validos, $IGNORADOS ignorados"
echo "politica    manter os $MANTER mais recentes"

if [ "$EXCEDENTE" -le 0 ]; then
    echo "nada a remover."
    exit 0
fi

A_REMOVER="$(printf '%s\n' "$ORDENADOS" | head -n "$EXCEDENTE")"

echo ""
if [ "$APLICAR" -eq 1 ]; then
    echo "=== REMOVENDO $EXCEDENTE pacote(s) mais antigo(s) ==="
else
    echo "=== SIMULACAO — nada sera removido (use --apply) ==="
fi

printf '%s\n' "$A_REMOVER" | while IFS= read -r NOME; do
    [ -n "$NOME" ] || continue
    ALVO="$DESTINO/$NOME"
    # Reconferido item a item, ja dentro do laco de remocao: a validacao do
    # inventario e barata de repetir e cara de confiar apenas uma vez.
    [ -d "$ALVO" ] || continue
    [ -f "$ALVO/manifest.json" ] || continue
    if [ "$APLICAR" -eq 1 ]; then
        rm -rf "$ALVO"
        # Os acompanhantes do off-host tem nome derivado do pacote e nao servem
        # para nada depois que o pacote sai. O objeto REMOTO nao e tocado: a
        # credencial de upload nem tem deleteFiles, e a retencao remota e
        # responsabilidade da lifecycle rule do bucket.
        rm -f "$ALVO.tar.age" "$ALVO.uploaded" "$ALVO.offhost_manifest.json"
        echo "removido  $NOME"
    else
        echo "removeria $NOME"
        if [ -f "$ALVO.tar.age" ]; then echo "removeria $NOME.tar.age"; fi
        if [ -f "$ALVO.uploaded" ]; then echo "removeria $NOME.uploaded"; fi
        if [ -f "$ALVO.offhost_manifest.json" ]; then echo "removeria $NOME.offhost_manifest.json"; fi
    fi
done

echo ""
if [ "$APLICAR" -eq 1 ]; then
    echo "OK  retencao local aplicada."
else
    echo "OK  simulacao concluida. Nenhum arquivo foi tocado."
fi
