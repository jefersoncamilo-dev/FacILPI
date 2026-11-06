"""M14 (#172): situacao e data_admissao fora do contrato de escrita do residente.

So a Admissao ativa (tests/test_d3_admissao.py) e so a saida tira de "Ativo"
(tests/test_n2_saida_residente.py). Mesmo harness descartavel do prontuario.
"""
import asyncio
from datetime import date

from sqlalchemy import select

from src.infrastructure import models as m
from tests.test_d4_prontuario import (  # noqa: F401 - prontuario_db e fixture
    _create_ilpi_user, _headers, _new_inst, _with_client, prontuario_db,
)

ESCRITA = {"residentes:ler", "residentes:criar", "residentes:atualizar"}


async def _ler(db, registro_id):
    return (await db.execute(select(m.Residente).where(m.Residente.id == registro_id)
                             .execution_options(populate_existing=True))).scalar_one()


def test_m14_post_ignora_situacao_e_data_admissao(prontuario_db):
    async def op(client, db):
        ilpi = _new_inst()
        user = await _create_ilpi_user(db, ilpi, permissions=ESCRITA)
        await db.commit()
        r = await client.post("/api/residentes/", headers=_headers(user, ilpi_id=ilpi.id), json={
            "nome": "Residente M14", "data_nascimento": "1940-01-01",
            "situacao": "Ativo", "data_admissao": "2026-01-01"})
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["situacao"] == "Em admissao" and body["data_admissao"] is None
        res = await _ler(db, body["id"])
        assert res.situacao == "Em admissao" and res.data_admissao is None
    asyncio.run(_with_client(prontuario_db, op))


def test_m14_put_nao_altera_situacao_nem_data_admissao(prontuario_db):
    async def op(client, db):
        ilpi = _new_inst()
        user = await _create_ilpi_user(db, ilpi, permissions=ESCRITA)
        await db.commit()
        h = _headers(user, ilpi_id=ilpi.id)
        criado = (await client.post("/api/residentes/", headers=h,
                                    json={"nome": "Residente M14", "data_nascimento": "1940-01-01"})).json()
        r = await client.put(f"/api/residentes/{criado['id']}", headers=h, json={
            "nome": "Residente M14 editado", "situacao": "Ativo", "data_admissao": "2026-01-01"})
        assert r.status_code == 200, r.text
        assert r.json()["nome"] == "Residente M14 editado"
        assert r.json()["situacao"] == "Em admissao" and r.json()["data_admissao"] is None
        # Residente ativo pela Admissao: o PUT nao o tira de "Ativo" nem troca a data.
        res = await _ler(db, criado["id"])
        res.situacao = "Ativo"
        res.data_admissao = date(2026, 2, 1)
        await db.commit()
        r = await client.put(f"/api/residentes/{criado['id']}", headers=h,
                             json={"situacao": "Falecido", "data_admissao": "2020-01-01"})
        assert r.status_code == 200, r.text
        res = await _ler(db, criado["id"])
        assert res.situacao == "Ativo" and str(res.data_admissao) == "2026-02-01"
    asyncio.run(_with_client(prontuario_db, op))
