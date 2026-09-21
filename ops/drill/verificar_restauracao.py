"""Evidencias objetivas de que o restore recuperou o ambiente.

Roda DENTRO do container do backend, contra o ambiente RESTAURADO. Compara o
estado recuperado com a linha de base capturada antes do backup e prova, ponta a
ponta, que documento e arquivo voltaram integros e servíveis.

A verificacao de integridade dos anexos nao depende de manifesto paralelo: a
coluna `documentos.arquivo_hash` ja guarda o SHA-256 gravado no momento do
upload, entao recomputar o hash do arquivo restaurado e compara-lo com o banco
prova que arquivo e registro continuam correspondendo um ao outro.

Distincao que o relatorio precisa preservar:
  - REFERENCIA PENDENTE (linha aponta para arquivo ausente) = FALHA
  - ORFAO (arquivo sem linha) = apenas reportado; e o residuo esperado da ordem
    de backup, e nunca apagado automaticamente.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import pathlib
import sys

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

sys.path.insert(0, "/app")

from src.infrastructure.database import engine  # noqa: E402
from src.infrastructure import models as m  # noqa: E402

BASE = "http://localhost:8000/api"
RAIZ_UPLOAD = pathlib.Path(os.getenv("UPLOAD_ROOT", "/data/uploads"))

TABELAS = {
    "users": m.User,
    "instituicoes": m.Instituicao,
    "residentes": m.Residente,
    "documentos": m.Documento,
    "funcionarios": m.Funcionario,
    "auditoria": m.Auditoria,
}


async def contagens(sessao: AsyncSession) -> dict[str, int]:
    resultado = {}
    for nome, modelo in TABELAS.items():
        resultado[nome] = (await sessao.execute(select(func.count()).select_from(modelo))).scalar_one()
    return resultado


async def integridade_anexos(sessao: AsyncSession) -> dict:
    documentos = (
        await sessao.execute(select(m.Documento).where(m.Documento.arquivo.is_not(None)))
    ).scalars().all()

    pendentes: list[str] = []
    hash_divergente: list[str] = []
    conferidos = 0
    referenciados: set[str] = set()

    for documento in documentos:
        caminho = RAIZ_UPLOAD / documento.arquivo
        referenciados.add(str(caminho.resolve()))
        if not caminho.is_file():
            pendentes.append(documento.id)
            continue
        if documento.arquivo_hash:
            digest = hashlib.sha256(caminho.read_bytes()).hexdigest()
            if digest != documento.arquivo_hash:
                hash_divergente.append(documento.id)
            else:
                conferidos += 1

    no_disco = {str(p.resolve()) for p in RAIZ_UPLOAD.rglob("*") if p.is_file()}
    orfaos = sorted(no_disco - referenciados)

    return {
        "documentos_com_arquivo": len(documentos),
        "arquivos_no_disco": len(no_disco),
        "hashes_conferidos": conferidos,
        "hash_divergente": hash_divergente,
        "referencias_pendentes": pendentes,
        "orfaos": orfaos,
    }


async def principal(base_linha: dict) -> int:
    fabrica = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    falhas: list[str] = []

    async with fabrica() as sessao:
        cabeca = (
            await sessao.execute(select(m.BootstrapState.estado))
        ).scalars().first()
        atuais = await contagens(sessao)
        anexos = await integridade_anexos(sessao)

    esperadas = base_linha["contagens"]
    if atuais != esperadas:
        falhas.append(f"contagens divergentes: esperado {esperadas}, obtido {atuais}")

    if anexos["referencias_pendentes"]:
        falhas.append(f"referencias pendentes: {anexos['referencias_pendentes']}")
    if anexos["hash_divergente"]:
        falhas.append(f"hash divergente: {anexos['hash_divergente']}")
    if anexos["hashes_conferidos"] < 1:
        falhas.append("nenhum anexo pode ser conferido por hash")

    # Download autenticado do arquivo restaurado, pela aplicacao restaurada.
    baixado = {"status": None, "sha256": None, "confere_com_origem": False}
    async with httpx.AsyncClient(timeout=60.0) as cliente:
        # O usuario do ensaio tem DOIS vinculos (ilpi_admin + administrativo), entao
        # o login precisa dizer qual perfil quer — sem isso a resposta correta da
        # aplicacao e PROFILE_SELECTION_REQUIRED. Que essa selecao ainda seja
        # necessaria depois do restore e, em si, evidencia de que os vinculos
        # voltaram fieis.
        credenciais = {
            "email": base_linha["equipe_email"],
            "password": base_linha["equipe_senha"],
        }
        if base_linha.get("perfil_administrativo_id"):
            credenciais.update(
                {
                    "scope": "ilpi",
                    "ilpi_id": base_linha["ilpi_id"],
                    "perfil_id": base_linha["perfil_administrativo_id"],
                }
            )
        entrada = await cliente.post(f"{BASE}/auth/token", json=credenciais)
        if entrada.status_code != 200:
            falhas.append(f"login pos-restore falhou: {entrada.status_code} {entrada.text}")
        else:
            token = entrada.json()["access_token"]
            resposta = await cliente.get(
                f"{BASE}/documentos/{base_linha['documento_id']}/arquivo",
                headers={"Authorization": f"Bearer {token}"},
            )
            baixado["status"] = resposta.status_code
            if resposta.status_code != 200:
                falhas.append(f"download pos-restore falhou: {resposta.status_code}")
            else:
                baixado["sha256"] = hashlib.sha256(resposta.content).hexdigest()
                baixado["confere_com_origem"] = (
                    baixado["sha256"] == base_linha["arquivo_sha256_local"]
                )
                if not baixado["confere_com_origem"]:
                    falhas.append("conteudo baixado difere do original")

            # Rotacao do JWT_SECRET: token emitido no ambiente de ORIGEM nao pode
            # ser aceito aqui. E o comportamento desejado no disaster recovery.
            antigo = base_linha.get("token_antigo")
            if antigo:
                sonda = await cliente.get(
                    f"{BASE}/usuarios/", headers={"Authorization": f"Bearer {antigo}"}
                )
                baixado["token_antigo_status"] = sonda.status_code
                if sonda.status_code == 200:
                    falhas.append("token do ambiente de origem AINDA e aceito apos rotacao")

    await engine.dispose()

    print(
        json.dumps(
            {
                "bootstrap_state": cabeca,
                "contagens_restauradas": atuais,
                "contagens_baseline": esperadas,
                "contagens_conferem": atuais == esperadas,
                "anexos": anexos,
                "download_autenticado": baixado,
                "falhas": falhas,
                "resultado": "PASS" if not falhas else "FAIL",
            },
            indent=2,
        )
    )
    return 0 if not falhas else 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("uso: verificar_restauracao.py <arquivo json da linha de base>")
    dados = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
    raise SystemExit(asyncio.run(principal(dados)))
