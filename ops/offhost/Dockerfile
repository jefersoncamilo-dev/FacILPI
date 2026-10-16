# FacILPI — imagem operacional da copia off-host.
#
# Contem as DUAS ferramentas que o off-host precisa e nada alem disso:
#   age      cifra client-side, antes de o pacote sair do host
#   aws-cli  PUT unico no Backblaze B2, com Object Lock no mesmo PUT
#
# POR QUE UMA IMAGEM PROPRIA, E NAO BINARIOS NO HOST:
# o backup ja depende de Docker (ops/backup.sh usa `docker compose exec db
# pg_dump` e `docker run alpine`). Sem Docker nao existe pacote para enviar,
# entao containerizar o upload nao acrescenta nenhum modo de falha novo — e
# entrega reprodutibilidade que `apt install` em distro arbitraria nao entrega.
#
# POR QUE NAO amazon/aws-cli OFICIAL:
# 646 MB contra 240 MB desta, e obrigaria uma SEGUNDA base (Amazon Linux) mais
# uma imagem separada para o age, que nao tem imagem oficial. Uma base so, ja
# usada pelo projeto, com duas versoes fixas, e menos superficie para auditar.
#
# POR QUE apk:
# `apk` e um dos canais de instalacao que o proprio projeto age lista como
# oficiais. Nao e atalho comunitario.
#
# BASE PINADA POR DIGEST, nao por tag: tag e movel, digest nao. Este digest foi
# validado em spike tecnico junto com as duas versoes abaixo.
FROM alpine:3.20@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc

# Versoes EXATAS, nunca `latest` e nunca sem sufixo de release. Trocar qualquer
# uma delas exige revalidar o conjunto — ver ops/offhost/README.md.
RUN apk add --no-cache \
        age=1.2.1-r0 \
        aws-cli=2.15.57-r0 \
    && age --version \
    && aws --version

# Sem ENTRYPOINT: o chamador diz qual ferramenta quer (`age ...` ou `aws ...`).
# Um entrypoint fixo obrigaria duas imagens ou um wrapper, sem ganho.
#
# Sem ENV de credencial. Credencial entra em runtime, por `-e NOME` (somente o
# NOME — `-e NOME=valor` colocaria o segredo no argv, visivel em `ps`).
