#!/bin/bash
# block-env-files.sh
# PreToolUse hook (matcher: Read) — bloqueia leitura de arquivos .env* reais,
# preservando .env.example. Hardening do fluxo do Claude Code, não sandbox de
# sistema operacional: não impede acesso por processos fora deste fluxo.

INPUT="$(cat)"

if command -v jq >/dev/null 2>&1; then
  FILE_PATH="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty')"
elif command -v python >/dev/null 2>&1; then
  FILE_PATH="$(printf '%s' "$INPUT" | python -c 'import json,sys
try:
    d = json.load(sys.stdin)
    print(d.get("tool_input", {}).get("file_path", ""))
except Exception:
    print("")' 2>/dev/null)"
else
  FILE_PATH="$(printf '%s' "$INPUT" | grep -o '"file_path"[[:space:]]*:[[:space:]]*"[^"]*"' | head -n1 | sed -E 's/^.*:[[:space:]]*"(.*)"$/\1/')"
fi

if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

# Normaliza separadores do Windows (\) para / antes de extrair o basename
NORMALIZED="${FILE_PATH//\\//}"
BASENAME="${NORMALIZED##*/}"

if [[ "$BASENAME" == .env* && "$BASENAME" != ".env.example" ]]; then
  echo "Blocked: leitura de arquivo de ambiente real bloqueada (${BASENAME}). Use .env.example como referência de variáveis." >&2
  exit 2
fi

exit 0
