# Imagem operacional do off-host

Imagem própria do projeto, usada por `ops/offhost_upload.sh` para cifrar com
`age` e enviar ao Backblaze B2 com `aws-cli`.

```
tag       facilpi/offhost:1
base      alpine:3.20@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc
age       1.2.1-r0       (alpine v3.20/community)
aws-cli   2.15.57-r0     (alpine v3.20/community — AWS CLI v2)
tamanho   ~240 MB
```

## Responsabilidade

**Esta imagem é mantida pelo projeto, não por terceiros.** Não existe imagem
oficial de container do `age`, e nenhuma imagem comunitária foi adotada. A
contrapartida de controlar a cadeia de suprimento é ter de mantê-la: versões
fixas que ninguém revisa envelhecem e viram dívida de segurança silenciosa.

Quem mantém o off-host mantém esta imagem.

## Build

```bash
docker build -t facilpi/offhost:1 ops/offhost
```

O build valida a si próprio: falha se `age --version` ou `aws --version` não
executarem.

## Preparação — obrigatória antes do primeiro backup (GATE-7)

A imagem precisa existir **antes** de o cron rodar. `ops/offhost_upload.sh`
**não faz pull nem build automático**: se a imagem não estiver presente, ele
falha com mensagem acionável em vez de baixar algo em silêncio no meio da noite.

```bash
docker build -t facilpi/offhost:1 ops/offhost
docker image inspect facilpi/offhost:1 >/dev/null && echo "pronta"
```

Em host sem acesso ao Docker Hub, prepare em outra máquina e transfira:

```bash
docker save facilpi/offhost:1 | gzip > facilpi-offhost-1.tar.gz
# na VPS
gunzip -c facilpi-offhost-1.tar.gz | docker load
```

## Operação offline

Depois de construída ou carregada, a imagem **não precisa de rede** para
funcionar. Verificado com `--network none`: `age` cifra e decifra, `aws`
executa. Só o upload em si precisa de rede, pela natureza do que faz.

Isso importa porque um procedimento de recuperação de desastre não pode
depender de baixar nada no momento do desastre.

## Atualização

Trocar qualquer versão **exige revalidar o conjunto inteiro**. Não basta subir o
número:

1. confirmar que os pacotes existem na versão pretendida
   (`apk policy age aws-cli` dentro da base nova);
2. confirmar o **digest** da base nova — o digest acima vale para
   `alpine:3.20` no momento da validação e muda a cada rebuild do Alpine;
3. confirmar que `aws s3api put-object --generate-cli-skeleton` ainda expõe
   `ChecksumAlgorithm`, `ChecksumSHA256`, `ObjectLockMode`,
   `ObjectLockRetainUntilDate` e `Metadata` — a arquitetura de integridade
   depende dos cinco;
4. round-trip `age` com chave efêmera sintética: cifrar, decifrar, comparar
   SHA-256, e confirmar que chave errada e artefato corrompido são recusados;
5. atualizar `Dockerfile`, este README e `OFFHOST_IMAGE` na configuração;
6. nova tag (`facilpi/offhost:2`), nunca sobrescrever a anterior — assim um
   rollback continua possível.

Passar direto para o passo 5 é o jeito de descobrir em produção que a CLI nova
renomeou um campo.

## O que esta imagem não faz

- **não contém credencial alguma** — `Config.Env` tem apenas `PATH`;
- **não contém chave `age`** — nem pública nem privada;
- **não é usada pelo `ops/offhost_fetch.sh` por padrão.** A recuperação roda em
  modo `local`, com `age` binário, para que a **chave privada** não precise ser
  montada dentro de uma imagem. O modo `container` existe, mas é opção
  consciente com exposição adicional documentada.
