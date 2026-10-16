"""Popula um ambiente DESCARTAVEL com dados SINTETICOS, via fluxos reais da API.

Roda DENTRO do container do backend (`docker compose exec -T backend python -`),
falando com a propria aplicacao em localhost:8000. Nada e escrito direto no
banco: se um fluxo estiver quebrado, o ensaio falha aqui em vez de provar o
restore de um estado que a aplicacao nunca produziria.

Sequencia — toda ela por endpoint publico:
    bootstrap -> operador troca senha -> cria ILPI -> cria primeiro gestor ->
    gestor troca senha -> operador ativa -> gestor recebe tambem o template
    `administrativo` (a matriz isenta `ilpi_admin` da anti-escalacao) -> nesse
    perfil cria residente, documento e anexa arquivo.

O template `administrativo` e usado porque e ele que tem `residentes:criar`,
`documentos:criar` (migration 015) e `documentos:anexar` (migration 020). O
`ilpi_admin` nao tem permissao clinica alguma, entao seria incapaz de produzir
o documento que o ensaio precisa recuperar.

NENHUM dado real. NENHUM acesso a storage/app.db.
"""

from __future__ import annotations

import hashlib
import json
import random
import sys
import uuid

import httpx

BASE = "http://localhost:8000/api"
ADMIN_EMAIL = "admin@ilpi.com"
SENHA_OPERADOR = "DrillOperador123A"
SENHA_GESTOR = "DrillGestor456B"
CONTEUDO = b"%PDF-1.4\n% FacILPI restore drill - conteudo sintetico\n" + uuid.uuid4().hex.encode()


def cnpj_valido() -> str:
    base = [random.randint(0, 9) for _ in range(12)]
    for pesos in ([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]):
        soma = sum(d * p for d, p in zip(base, pesos))
        resto = soma % 11
        base.append(0 if resto < 2 else 11 - resto)
    return "".join(str(d) for d in base)


def cabecalhos(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def exigir(resposta: httpx.Response, esperado: int, etapa: str) -> httpx.Response:
    if resposta.status_code != esperado:
        raise SystemExit(f"FALHA em {etapa}: {resposta.status_code} {resposta.text}")
    return resposta


def login(cliente: httpx.Client, email: str, senha: str, etapa: str) -> str:
    resposta = exigir(
        cliente.post(f"{BASE}/auth/token", json={"email": email, "password": senha}), 200, etapa
    )
    return resposta.json()["access_token"]


def trocar_senha(cliente: httpx.Client, token: str, atual: str, nova: str, etapa: str) -> None:
    exigir(
        cliente.put(
            f"{BASE}/auth/password",
            headers=cabecalhos(token),
            json={"senha_atual": atual, "nova_senha": nova, "confirmar_senha": nova},
        ),
        200,
        etapa,
    )


def main(senha_bootstrap: str) -> None:
    with httpx.Client(timeout=60.0) as cliente:
        # --- operador da plataforma -------------------------------------------
        # O primeiro acesso e consumivel: uma vez trocada, a senha temporaria do
        # bootstrap deixa de valer. Aceitar as duas entradas torna o ensaio
        # repetivel sobre o mesmo ambiente sem exigir banco novo a cada tentativa.
        inicial = cliente.post(
            f"{BASE}/auth/token", json={"email": ADMIN_EMAIL, "password": senha_bootstrap}
        )
        if inicial.status_code == 200:
            token = inicial.json()["access_token"]
            exigir(
                cliente.put(
                    f"{BASE}/auth/primeiro-acesso",
                    headers=cabecalhos(token),
                    json={"nova_senha": SENHA_OPERADOR, "confirmar": SENHA_OPERADOR},
                ),
                200,
                "primeiro acesso do operador",
            )
        operador = login(cliente, ADMIN_EMAIL, SENHA_OPERADOR, "login do operador")

        # --- ILPI sintetica ----------------------------------------------------
        ilpi = exigir(
            cliente.post(
                f"{BASE}/platform/instituicoes",
                headers=cabecalhos(operador),
                json={
                    "razao_social": "ILPI Sintetica do Ensaio",
                    "nome_fantasia": "Ensaio",
                    "capacidade": 20,
                    "uf": "SP",
                    "municipio": "Sao Paulo",
                    "cnpj": cnpj_valido(),
                },
            ),
            201,
            "criacao da ILPI",
        ).json()

        email_gestor = f"gestor-{uuid.uuid4().hex[:8]}@ensaio.com.br"
        gestor = exigir(
            cliente.post(
                f"{BASE}/platform/instituicoes/{ilpi['id']}/primeiro-gestor",
                headers=cabecalhos(operador),
                json={"nome": "Gestora do Ensaio", "email": email_gestor},
            ),
            201,
            "criacao do primeiro gestor",
        ).json()

        token_gestor = login(cliente, email_gestor, gestor["senha_temporaria"], "login do gestor")
        trocar_senha(cliente, token_gestor, gestor["senha_temporaria"], SENHA_GESTOR, "troca de senha do gestor")

        exigir(
            cliente.post(
                f"{BASE}/platform/instituicoes/{ilpi['id']}/ativar", headers=cabecalhos(operador)
            ),
            200,
            "ativacao da ILPI",
        )
        token_gestor = login(cliente, email_gestor, SENHA_GESTOR, "relogin do gestor")

        # --- perfil administrativo para o proprio gestor ----------------------
        # A matriz exige que o alvo JA tenha vinculo ativo no tenant
        # (`_target_no_tenant`, matriz.py:79), entao atribuir ao gestor evita
        # montar um segundo usuario so para satisfazer essa pre-condicao. O
        # gestor passa a ter dois vinculos, e por isso o login seguinte informa
        # `perfil_id` — sem ele viria PROFILE_SELECTION_REQUIRED.
        #
        # E o template `administrativo` que tem `residentes:criar`,
        # `documentos:criar` (015) e `documentos:anexar` (020); o `ilpi_admin`
        # nao possui permissao clinica alguma.
        atribuicao = exigir(
            cliente.post(
                f"{BASE}/matriz/atribuicoes",
                headers=cabecalhos(token_gestor),
                json={"usuario_id": gestor["id"], "perfil_chave": "administrativo"},
            ),
            201,
            "atribuicao do perfil administrativo",
        ).json()

        entrada = exigir(
            cliente.post(
                f"{BASE}/auth/token",
                json={
                    "email": email_gestor,
                    "password": SENHA_GESTOR,
                    "scope": "ilpi",
                    "ilpi_id": ilpi["id"],
                    "perfil_id": atribuicao["perfil_id"],
                },
            ),
            200,
            "login no perfil administrativo",
        ).json()
        token_equipe = entrada["access_token"]

        # --- residente, documento e anexo -------------------------------------
        residente = exigir(
            cliente.post(
                f"{BASE}/residentes/",
                headers=cabecalhos(token_equipe),
                json={"nome": "Residente Sintetica do Ensaio", "data_nascimento": "1938-04-12"},
            ),
            201,
            "criacao do residente",
        ).json()

        documento = exigir(
            cliente.post(
                f"{BASE}/documentos/",
                headers=cabecalhos(token_equipe),
                json={"residente_id": residente["id"], "tipo": "contrato", "numero": "ENSAIO-001"},
            ),
            201,
            "criacao do documento",
        ).json()

        anexado = exigir(
            cliente.post(
                f"{BASE}/documentos/{documento['id']}/arquivo",
                headers=cabecalhos(token_equipe),
                files={"file": ("contrato-sintetico.pdf", CONTEUDO, "application/pdf")},
            ),
            201,
            "anexo do arquivo",
        ).json()

        print(
            json.dumps(
                {
                    "ilpi_id": ilpi["id"],
                    "gestor_email": email_gestor,
                    "equipe_email": email_gestor,
                    "equipe_senha": SENHA_GESTOR,
                    "perfil_administrativo_id": atribuicao["perfil_id"],
                    # Guardado para provar, depois do restore, que um token
                    # emitido sob o JWT_SECRET antigo deixa de ser aceito.
                    "token_antigo": token_equipe,
                    "residente_id": residente["id"],
                    "documento_id": documento["id"],
                    # `arquivo` (a chave interna de armazenamento) e
                    # deliberadamente nao serializada pelo DocumentoResponse; o
                    # ensaio nao precisa dela, e pedi-la seria depender de um
                    # detalhe que a API esconde de proposito.
                    "arquivo_presente": anexado["arquivo_presente"],
                    "arquivo_sha256_local": hashlib.sha256(CONTEUDO).hexdigest(),
                    "arquivo_hash_no_banco": anexado["arquivo_hash"],
                    "arquivo_tamanho": anexado["arquivo_tamanho"],
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("uso: popular_sintetico.py <senha temporaria do bootstrap>")
    main(sys.argv[1])
