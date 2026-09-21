"""Captura a linha de base do ambiente de ORIGEM, antes do backup.

Roda dentro do container do backend. Imprime apenas contagens e um resumo dos
anexos — nenhum dado pessoal, porque o ambiente e sintetico e o objetivo e
comparacao, nao conteudo.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import pathlib
import sys

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

sys.path.insert(0, "/app")

from src.infrastructure.database import engine  # noqa: E402
from src.infrastructure import models as m  # noqa: E402

RAIZ_UPLOAD = pathlib.Path(os.getenv("UPLOAD_ROOT", "/data/uploads"))

TABELAS = {
    "users": m.User,
    "instituicoes": m.Instituicao,
    "residentes": m.Residente,
    "documentos": m.Documento,
    "funcionarios": m.Funcionario,
    "auditoria": m.Auditoria,
}


async def principal() -> None:
    fabrica = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with fabrica() as sessao:
        contagens = {}
        for nome, modelo in TABELAS.items():
            contagens[nome] = (
                await sessao.execute(select(func.count()).select_from(modelo))
            ).scalar_one()
        cabeca = (await sessao.execute(select(m.BootstrapState.estado))).scalars().first()

    arquivos = sorted(p for p in RAIZ_UPLOAD.rglob("*") if p.is_file())
    detalhe = [
        {
            "caminho_relativo": str(p.relative_to(RAIZ_UPLOAD)).replace("\\", "/"),
            "tamanho": p.stat().st_size,
            "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        }
        for p in arquivos
    ]

    await engine.dispose()
    print(json.dumps({"contagens": contagens, "bootstrap_state": cabeca, "arquivos": detalhe}, indent=2))


if __name__ == "__main__":
    asyncio.run(principal())
