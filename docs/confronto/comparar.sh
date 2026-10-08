#!/usr/bin/env bash
# Compara a cópia local do FáciLPI com o manifesto da cópia remota.
# Uso: na raiz do projeto local, com manifest.sha256 ao lado: bash comparar.sh
set -u
MANIFEST="${1:-manifest.sha256}"
[ -f "$MANIFEST" ] || { echo "manifest não encontrado: $MANIFEST"; exit 1; }
if command -v sha256sum >/dev/null; then SUM="sha256sum"; else SUM="shasum -a 256"; fi

echo "== Commit local: $(git rev-parse HEAD 2>/dev/null || echo 'sem git')"
echo "== Commit remoto: 20082b5316b14bb181a624161dc1e7317c26d7a7"
echo

iguais=0; dif=0; falta=0
while read -r hash file; do
  if [ ! -f "$file" ]; then echo "FALTANDO LOCAL : $file"; falta=$((falta+1)); continue; fi
  h=$($SUM "$file" | cut -d' ' -f1)
  if [ "$h" = "$hash" ]; then iguais=$((iguais+1)); else echo "DIFERENTE      : $file"; dif=$((dif+1)); fi
done < "$MANIFEST"

echo
echo "== Arquivos só no local (versionados ou não-ignorados):"
cut -d' ' -f3- "$MANIFEST" | sort > /tmp/.facilpi_remoto
{ git ls-files; git ls-files --others --exclude-standard; } 2>/dev/null | sort -u > /tmp/.facilpi_local
comm -13 /tmp/.facilpi_remoto /tmp/.facilpi_local | sed 's/^/EXTRA LOCAL    : /'
rm -f /tmp/.facilpi_remoto /tmp/.facilpi_local

echo
echo "== Resumo: $iguais iguais, $dif diferentes, $falta faltando no local"
