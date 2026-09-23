#!/usr/bin/env sh
# FacILPI — copia off-host cifrada de um pacote de backup ja pronto.
#
# NAO substitui nem altera `ops/backup.sh`. Consome o pacote depois de pronto,
# cifra com age e envia para o Backblaze B2 com Object Lock. Se ESTE script
# falhar, o backup local continua integro e valido — os dois caminhos sao
# independentes de proposito.
#
# SUCESSO DO PUT NAO E SUCESSO FINAL. Este script grava um estado PENDENTE
# (<pacote>.offhost_pending.json) e para — nunca escreve o marcador
# `.uploaded` nem o manifesto definitivo. A resposta do PutObject da
# Backblaze so documenta VersionId e ETag; ela NUNCA confirma Object Lock
# ou checksum, tenham sido aplicados ou nao (ver GATE-3Q/3R). Exigir isso
# aqui produzia um falso negativo. A confirmacao real — GetObjectRetention,
# HeadObject e download+SHA-256 — e feita por `ops/offhost_verify.sh`, fora
# da VPS, com uma credencial read-only separada que este script nunca usa.
#
# Uso:
#   ops/offhost_upload.sh -b <pacote> -e <arquivo env> [-c daily|weekly] [--dry-run]
#
# O que este script NUNCA faz:
#   - criar credencial, gerar chave age, pedir segredo;
#   - apagar qualquer coisa no B2 (a credencial nem tem deleteFiles);
#   - passar segredo por argumento (visivel em `ps`);
#   - imprimir segredo;
#   - improvisar se o servidor recusar a verificacao SHA-256 no PUT (ver GATE-3);
#   - declarar sucesso definitivo — isso e exclusivo de ops/offhost_verify.sh.
set -eu

# Git Bash (MSYS) reescreve argumentos que parecem caminho POSIX. Mesma razao e
# mesmo efeito que em backup.sh: um script so para os dois sistemas.
export MSYS_NO_PATHCONV=1

# Tetos de seguranca. Nao sao configuraveis de proposito: sao a ultima barreira
# contra erro de digitacao com consequencia irreversivel.
#
# 31 dias: Object Lock COMPLIANCE nao pode ser encurtado nem removido. Um `365`
# digitado por engano custaria um ano de armazenamento sem saida possivel.
MAX_DIAS_LOCK=31
# 4 GiB: acima disso o PUT precisaria ser multipart, e o ETag deixaria de ter
# qualquer relacao com o conteudo. Em vez de fazer multipart em silencio e
# enfraquecer a cadeia de integridade, o script para e reporta.
MAX_BYTES_ARTEFATO=4294967296

PACOTE=""
ARQUIVO_ENV=""
CLASSE="daily"
SIMULACAO=0

uso() {
    echo "uso: ops/offhost_upload.sh -b <pacote> -e <arquivo env> [-c daily|weekly] [--dry-run]" >&2
    exit 2
}

while [ $# -gt 0 ]; do
    case "$1" in
        -b) PACOTE="${2:-}"; shift 2 ;;
        -e) ARQUIVO_ENV="${2:-}"; shift 2 ;;
        -c) CLASSE="${2:-}"; shift 2 ;;
        --dry-run) SIMULACAO=1; shift ;;
        -h|--help) uso ;;
        *) echo "argumento desconhecido: $1" >&2; uso ;;
    esac
done

[ -n "$PACOTE" ] || { echo "falta -b <pacote>" >&2; uso; }
[ -n "$ARQUIVO_ENV" ] || { echo "falta -e <arquivo env>" >&2; uso; }
[ -d "$PACOTE" ] || { echo "pacote nao encontrado: $PACOTE" >&2; exit 2; }
[ -f "$ARQUIVO_ENV" ] || { echo "arquivo de ambiente nao encontrado: $ARQUIVO_ENV" >&2; exit 2; }

case "$CLASSE" in
    daily|weekly) ;;
    *) echo "classe invalida: $CLASSE (use daily ou weekly)" >&2; exit 2 ;;
esac

ler_env() {
    # Mesmo padrao de backup.sh: le a chave SEM dar source. O arquivo contem a
    # Application Key do B2, e um `source` exportaria tudo para este processo e
    # para todos os filhos — inclusive o `aws`, que nao precisa de mais nada
    # alem das variaveis que passamos explicitamente.
    sed -n "s/^$1=//p" "$ARQUIVO_ENV" | head -1
}

B2_ENDPOINT="$(ler_env B2_ENDPOINT)"
B2_REGION="$(ler_env B2_REGION)"
B2_BUCKET="$(ler_env B2_BUCKET)"
OFFHOST_PREFIX="$(ler_env OFFHOST_PREFIX)"
AGE_RECIPIENT="$(ler_env AGE_RECIPIENT)"
OFFHOST_IMAGE="$(ler_env OFFHOST_IMAGE)"
[ -n "$OFFHOST_IMAGE" ] || OFFHOST_IMAGE="facilpi/offhost:1"
[ -n "$OFFHOST_PREFIX" ] || OFFHOST_PREFIX="facilpi/"

if [ "$CLASSE" = "daily" ]; then
    DIAS_LOCK="$(ler_env OFFHOST_LOCK_DAYS_DAILY)"
else
    DIAS_LOCK="$(ler_env OFFHOST_LOCK_DAYS_WEEKLY)"
fi

# --- validacao de configuracao (fail closed, antes de qualquer trabalho) ------

[ -n "$AGE_RECIPIENT" ] || { echo "FALHA: AGE_RECIPIENT ausente em $ARQUIVO_ENV. Sem recipient publico nao ha cifra, e pacote em claro NAO sai do host." >&2; exit 2; }
# Barreira contra o pior erro possivel deste arquivo: colar a chave PRIVADA onde
# vai o recipient publico. Isso colocaria a chave de recuperacao na mesma maquina
# que o dado, anulando toda a custodia separada. Conferido ANTES do formato, para
# que o operador receba a mensagem que descreve o problema real.
case "$AGE_RECIPIENT" in
    *AGE-SECRET-KEY*)
        echo "FALHA: AGE_RECIPIENT contem uma chave PRIVADA age." >&2
        echo "       A chave privada NUNCA pode existir no ambiente de upload:" >&2
        echo "       ela decifra TODOS os backups off-host e deve viver apenas sob" >&2
        echo "       custodia separada. Use o recipient PUBLICO (age1...)." >&2
        exit 2 ;;
esac
case "$AGE_RECIPIENT" in
    age1*) ;;
    *) echo "FALHA: AGE_RECIPIENT nao parece um recipient publico age (esperado age1...)." >&2; exit 2 ;;
esac

[ -n "$B2_BUCKET" ] || { echo "FALHA: B2_BUCKET ausente em $ARQUIVO_ENV" >&2; exit 2; }
[ -n "$B2_ENDPOINT" ] || { echo "FALHA: B2_ENDPOINT ausente em $ARQUIVO_ENV" >&2; exit 2; }
[ -n "$B2_REGION" ] || { echo "FALHA: B2_REGION ausente em $ARQUIVO_ENV" >&2; exit 2; }

case "$DIAS_LOCK" in
    ''|*[!0-9]*) echo "FALHA: dias de Object Lock para a classe $CLASSE ausente ou nao numerico: '$DIAS_LOCK'" >&2; exit 2 ;;
esac
[ "$DIAS_LOCK" -ge 1 ] || { echo "FALHA: dias de Object Lock deve ser >= 1 (obtido $DIAS_LOCK)" >&2; exit 2; }
if [ "$DIAS_LOCK" -gt "$MAX_DIAS_LOCK" ]; then
    echo "FALHA: retencao de $DIAS_LOCK dias excede o teto de $MAX_DIAS_LOCK." >&2
    echo "       Object Lock COMPLIANCE e IRREVERSIVEL: o objeto ficaria travado" >&2
    echo "       — e cobrado — por todo o periodo, sem remocao possivel." >&2
    echo "       Se o valor for realmente intencional, ele exige decisao do" >&2
    echo "       Control Tower, nao uma edicao do arquivo de ambiente." >&2
    exit 2
fi

NOME_PACOTE="$(basename "$PACOTE")"
DIR_PAI="$(cd "$(dirname "$PACOTE")" && pwd)"
ARTEFATO="$DIR_PAI/$NOME_PACOTE.tar.age"
PARCIAL="$ARTEFATO.parcial"
# MARCADOR e o manifesto definitivo (offhost_manifest.json) so passam a
# existir depois da VERIFICACAO independente (ops/offhost_verify.sh) — nao
# mais escritos por este script. PENDENTE e o que este script produz ao
# terminar; MARCADOR aqui so serve para a checagem de idempotencia abaixo.
MARCADOR="$DIR_PAI/$NOME_PACOTE.uploaded"
PENDENTE="$DIR_PAI/$NOME_PACOTE.offhost_pending.json"
CHAVE_REMOTA="${OFFHOST_PREFIX}${CLASSE}/${NOME_PACOTE}.tar.age"

RETAIN_UNTIL="$(date -u -d "+$DIAS_LOCK days" +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || true)"
[ -n "$RETAIN_UNTIL" ] || { echo "FALHA: nao foi possivel calcular retain_until (GNU date requerido)." >&2; exit 2; }

# --- idempotencia -------------------------------------------------------------
# A credencial de upload nao tem readFiles nem listFiles de proposito, entao o
# script NAO pode perguntar ao B2 se o objeto ja existe. O marcador/pendente
# local e o que evita que uma reexecucao (cron repetido, retry manual) crie
# uma segunda versao travada por Compliance — que ficaria la, cobrando, ate
# expirar. PENDENTE conta tanto quanto MARCADOR: um upload que ja foi enviado
# e so aguarda verificacao independente nao deve ser reenviado.
if [ "$SIMULACAO" -eq 0 ]; then
    if [ -f "$MARCADOR" ]; then
        echo "JA ENVIADO E VERIFICADO  $NOME_PACOTE  (marcador: $MARCADOR)"
        echo "Nada a fazer. Remova o marcador apenas se tiver certeza de que o envio anterior falhou."
        exit 0
    fi
    if [ -f "$PENDENTE" ]; then
        echo "JA ENVIADO, AGUARDANDO VERIFICACAO  $NOME_PACOTE  (pendente: $PENDENTE)"
        echo "Execute ops/offhost_verify.sh com a credencial read-only para confirmar"
        echo "o sucesso. Remova o arquivo pendente apenas se tiver certeza de que o"
        echo "envio anterior falhou e precisa ser refeito."
        exit 0
    fi
fi

# --- [1/5] integridade do pacote de origem ------------------------------------
echo "[1/5] verificando o pacote de origem (SHA256SUMS)"
# FAIL CLOSED e ANTES da cifra: cifrar um pacote corrompido produziria um
# artefato perfeitamente valido do ponto de vista do age, travado por Compliance,
# contendo lixo. O erro so apareceria no dia da recuperacao.
if ! ( cd "$PACOTE" && sha256sum -c SHA256SUMS >/dev/null 2>&1 ); then
    echo "FALHA: checksums do pacote divergem. Nada sera cifrado nem enviado." >&2
    exit 1
fi
[ -f "$PACOTE/manifest.json" ] || { echo "FALHA: manifest.json ausente em $PACOTE" >&2; exit 1; }
echo "      pacote integro"

# --- simulacao ----------------------------------------------------------------
if [ "$SIMULACAO" -eq 1 ]; then
    echo ""
    echo "=== DRY RUN — nenhuma rede, nenhuma credencial, nenhuma escrita remota ==="
    echo "pacote              $PACOTE"
    echo "classe              $CLASSE"
    echo "destino             $B2_BUCKET  ($B2_REGION)"
    echo "endpoint            $B2_ENDPOINT"
    echo "chave remota        $CHAVE_REMOTA"
    echo "artefato local      $ARTEFATO"
    echo "recipient age       $AGE_RECIPIENT"
    echo "object lock         COMPLIANCE"
    echo "retencao            $DIAS_LOCK dias  (teto do script: $MAX_DIAS_LOCK)"
    echo "retain_until        $RETAIN_UNTIL"
    echo ""
    echo "ATENCAO: Object Lock COMPLIANCE e IRREVERSIVEL. Ate $RETAIN_UNTIL o"
    echo "objeto nao podera ser apagado nem ter a retencao encurtada por ninguem,"
    echo "inclusive pelo dono da conta."
    echo ""
    echo "estado pendente     $PENDENTE"
    echo "marcador definitivo $MARCADOR  (so apos ops/offhost_verify.sh)"
    echo "=== fim do DRY RUN ==="
    exit 0
fi

# --- credencial ---------------------------------------------------------------
# Lida so agora: o dry-run acima roda sem nenhum segredo presente.
B2_KEY_ID="$(ler_env B2_KEY_ID)"
B2_APP_KEY="$(ler_env B2_APP_KEY)"
[ -n "$B2_KEY_ID" ] || { echo "FALHA: B2_KEY_ID ausente em $ARQUIVO_ENV" >&2; exit 2; }
[ -n "$B2_APP_KEY" ] || { echo "FALHA: B2_APP_KEY ausente em $ARQUIVO_ENV" >&2; exit 2; }

# --- imagem operacional -------------------------------------------------------
# O backup ja depende de Docker (ops/backup.sh usa `docker compose exec db
# pg_dump` e `docker run alpine`), entao exigi-lo aqui nao acrescenta modo de
# falha novo: sem Docker nao existiria pacote para enviar.
command -v docker >/dev/null 2>&1 || { echo "FALHA: docker nao encontrado. O off-host usa a mesma infraestrutura que ops/backup.sh ja exige." >&2; exit 2; }

# NAO ha pull nem build automatico. Baixar ou construir imagem sozinho, no meio
# da madrugada, e como um cron decide mudar a propria ferramenta sem ninguem
# ver. A imagem e preparada antes, no GATE-7, e a ausencia dela e falha.
if ! docker image inspect "$OFFHOST_IMAGE" >/dev/null 2>&1; then
    echo "FALHA: imagem '$OFFHOST_IMAGE' nao esta presente neste host." >&2
    echo "       Este script NAO baixa nem constroi imagem automaticamente." >&2
    echo "       Prepare-a antes:" >&2
    echo "           docker build -t $OFFHOST_IMAGE ops/offhost" >&2
    echo "       Em host sem acesso ao registry, use docker save/load —" >&2
    echo "       ver ops/offhost/README.md." >&2
    exit 2
fi

# Artefato parcial nunca pode sobreviver a uma falha parecendo completo — mesma
# disciplina do `.parcial` em backup.sh.
limpar() { rm -f "$PARCIAL"; }
trap limpar EXIT INT TERM

# --- [2/5] cifra --------------------------------------------------------------
echo "[2/5] empacotando e cifrando com age (somente recipient publico)"
rm -f "$PARCIAL"
# O `tar` fica no HOST e so o `age` entra no container, lendo stdin e escrevendo
# stdout. Assim nao e preciso montar o diretorio do pacote para cifrar, e o
# conteudo em claro nunca aparece como arquivo dentro do container.
#
# O recipient e PUBLICO, entao pode ir em argv sem risco — ao contrario da
# credencial do B2, que nunca vai (ver etapa 4).
tar -cf - -C "$DIR_PAI" "$NOME_PACOTE" \
    | docker run --rm -i "$OFFHOST_IMAGE" age -r "$AGE_RECIPIENT" \
    > "$PARCIAL"
mv "$PARCIAL" "$ARTEFATO"
trap - EXIT INT TERM

# --- [3/5] integridade do artefato cifrado ------------------------------------
echo "[3/5] SHA-256 do artefato cifrado"
SHA_ARTEFATO="$(sha256sum "$ARTEFATO" | cut -d' ' -f1)"
BYTES_ARTEFATO="$(wc -c < "$ARTEFATO" | tr -d ' ')"
echo "      sha256=$SHA_ARTEFATO  bytes=$BYTES_ARTEFATO"

if [ "$BYTES_ARTEFATO" -gt "$MAX_BYTES_ARTEFATO" ]; then
    echo "FALHA: artefato de $BYTES_ARTEFATO bytes excede o limite de PUT unico ($MAX_BYTES_ARTEFATO)." >&2
    echo "       Enviar por multipart quebraria a cadeia de integridade: o ETag" >&2
    echo "       de um objeto multipart nao tem relacao com o conteudo. O script" >&2
    echo "       para aqui de proposito, em vez de enfraquecer a verificacao." >&2
    echo "       Isto exige decisao do Control Tower, nao um ajuste silencioso." >&2
    exit 1
fi

# O cabecalho de checksum do S3 leva o digest em base64, nao em hexadecimal.
SHA_BASE64="$(printf '%s' "$SHA_ARTEFATO" | xxd -r -p | base64 | tr -d '\n')"

# --- [4/5] upload -------------------------------------------------------------
echo "[4/5] enviando ao Backblaze B2 (PUT unico, com retencao no mesmo PUT)"
echo "      s3://$B2_BUCKET/$CHAVE_REMOTA"
echo "      object lock COMPLIANCE ate $RETAIN_UNTIL"

# A retencao vai NO PROPRIO PUT. Uma segunda chamada para aplicar o lock poderia
# falhar e deixar o objeto gravado e desprotegido — exatamente o estado que a
# protecao contra ransomware nao pode ter.
#
# A credencial entra por variavel de ambiente de UM comando, nunca por
# argumento: argumento e visivel em `ps` para qualquer usuario da maquina.
#
# `-e NOME` (so o NOME) faz o docker HERDAR o valor do proprio ambiente e
# repassar ao container. `-e NOME=valor` colocaria o segredo no argv do
# `docker run` — a diferenca entre as duas formas e a diferenca entre credencial
# protegida e credencial publicada em `ps`.
#
# O diretorio do pacote entra :ro — o upload nao pode alterar o que envia.
set +e
RESPOSTA="$(
    AWS_ACCESS_KEY_ID="$B2_KEY_ID" \
    AWS_SECRET_ACCESS_KEY="$B2_APP_KEY" \
    AWS_DEFAULT_REGION="$B2_REGION" \
    docker run --rm \
        -e AWS_ACCESS_KEY_ID \
        -e AWS_SECRET_ACCESS_KEY \
        -e AWS_DEFAULT_REGION \
        -v "$DIR_PAI:/dados:ro" \
        "$OFFHOST_IMAGE" \
        aws s3api put-object \
        --endpoint-url "$B2_ENDPOINT" \
        --bucket "$B2_BUCKET" \
        --key "$CHAVE_REMOTA" \
        --body "/dados/$NOME_PACOTE.tar.age" \
        --checksum-algorithm SHA256 \
        --checksum-sha256 "$SHA_BASE64" \
        --object-lock-mode COMPLIANCE \
        --object-lock-retain-until-date "$RETAIN_UNTIL" \
        --metadata "sha256=$SHA_ARTEFATO,age-recipient=$AGE_RECIPIENT,package=$NOME_PACOTE" \
        --query "[VersionId,ETag]" \
        --output text 2>&1
)"
CODIGO=$?
set -e

if [ "$CODIGO" -ne 0 ]; then
    echo "FALHA no upload (codigo $CODIGO)." >&2
    echo "$RESPOSTA" >&2
    case "$RESPOSTA" in
        *hecksum*)
            echo "" >&2
            echo "EVIDENCIA PARA O GATE-3: o servidor recusou a verificacao SHA-256." >&2
            echo "Isto NAO deve ser contornado aqui. A alternativa (Content-MD5 no PUT" >&2
            echo "mais verificacao por download fora do host) e uma mudanca de" >&2
            echo "arquitetura e exige decisao do Control Tower." >&2
            ;;
        *nauthorized*|*ccess*enied*|*orbidden*)
            echo "" >&2
            echo "Verifique as capabilities da Application Key: sao necessarias" >&2
            echo "writeFiles e writeFileRetentions, restritas a este bucket e ao" >&2
            echo "prefixo. Se o erro for de resolucao do bucket, listBuckets pode" >&2
            echo "ser necessaria — essa e a comprovacao prevista no GATE-3." >&2
            ;;
    esac
    echo "" >&2
    echo "Nenhum marcador foi gravado. O backup LOCAL continua integro e valido." >&2
    exit 1
fi

# A resposta do PutObject SO documenta VersionId e ETag (Backblaze,
# confirmado no GATE-3R contra a doc oficial e no GATE-3U contra o B2 real).
# ChecksumSHA256 e ObjectLockRetainUntilDate NUNCA aparecem aqui, tenham ou
# nao sido aplicados de verdade — exigir isso da PROPRIA resposta do PUT e
# o falso negativo que o GATE-3Q expos. A confirmacao real de Object Lock,
# checksum e integridade e responsabilidade EXCLUSIVA de
# ops/offhost_verify.sh, com a credencial read-only separada.
VERSION_ID="$(printf '%s' "$RESPOSTA" | awk '{print $1}')"
ETAG_RESPOSTA="$(printf '%s' "$RESPOSTA" | awk '{print $2}')"
# O `--output text` entrega o ETag com as aspas do proprio protocolo S3
# (ex.: "96ec...438f"). Interpolar isso direto no JSON do pendente produziria
# ""96ec...438f"" e o arquivo deixaria de ser JSON valido. As aspas sao
# sintaxe de transporte e nao fazem parte do valor: um ETag e hexadecimal,
# com sufixo -N quando multipart. Remover aspas e barras invertidas normaliza
# o valor sem perder nada que pertenca a um ETag real, e mantem o pendente
# valido por construcao — sem precisar de um serializador JSON aqui.
#
# Whitelist em vez de blacklist: um ETag legitimo e hexadecimal, com sufixo
# -N quando multipart. Manter apenas [A-Za-z0-9._:-] preserva o valor inteiro
# e descarta aspas, barras invertidas e qualquer outro caractere hostil ao
# JSON, sem depender das regras de escape do proprio `tr`.
ETAG_RESPOSTA="$(printf '%s' "$ETAG_RESPOSTA" | tr -cd 'A-Za-z0-9._:-')"
echo "      version_id=$VERSION_ID"

# --- [5/5] registrando estado PENDENTE ----------------------------------------
echo "[5/5] registrando estado pendente (aguardando verificacao independente)"
# Isto NAO e um marcador de sucesso. E o suficiente para que
# ops/offhost_verify.sh, rodando fora da VPS com a credencial read-only,
# confirme de forma independente Object Lock, metadata e integridade antes
# de promover o backup a sucesso de fato. Os campos "expected_*" sao o que
# ESTE host pediu — nao o que o servidor confirmou, porque o servidor nao
# confirma isso aqui.
#
# Nenhum segredo entra aqui: o recipient age e publico e nao ha credencial
# alguma.
cat > "$PENDENTE" <<JSON
{
  "offhost_format_version": 2,
  "state": "PENDING",
  "package_name": "$NOME_PACOTE",
  "backup_class": "$CLASSE",
  "encryption": "age",
  "encryption_recipient": "$AGE_RECIPIENT",
  "encrypted_artifact": "$NOME_PACOTE.tar.age",
  "encrypted_artifact_sha256": "$SHA_ARTEFATO",
  "encrypted_artifact_bytes": $BYTES_ARTEFATO,
  "remote_provider": "backblaze-b2",
  "remote_bucket": "$B2_BUCKET",
  "remote_endpoint": "$B2_ENDPOINT",
  "remote_region": "$B2_REGION",
  "remote_key": "$CHAVE_REMOTA",
  "remote_version_id": "$VERSION_ID",
  "put_etag": "$ETAG_RESPOSTA",
  "expected_object_lock_mode": "COMPLIANCE",
  "expected_retain_until": "$RETAIN_UNTIL",
  "uploaded_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "verify_notes": "executar ops/offhost_verify.sh FORA da VPS, com a credencial read-only (readFiles + readFileRetentions), para confirmar Object Lock, metadata e SHA-256 antes de considerar este backup bem-sucedido"
}
JSON

echo ""
echo "PENDENTE  $CHAVE_REMOTA"
echo "sha256=$SHA_ARTEFATO  bytes=$BYTES_ARTEFATO  expected_retain_until=$RETAIN_UNTIL"
echo "estado pendente: $PENDENTE"
echo ""
echo "Upload aceito pelo servidor, mas isto NAO e sucesso confirmado."
echo "Execute ops/offhost_verify.sh (fora da VPS, credencial read-only) para"
echo "confirmar Object Lock, metadata e integridade antes de contar este"
echo "backup como concluido."
