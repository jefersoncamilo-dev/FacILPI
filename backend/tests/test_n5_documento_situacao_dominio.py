"""N5: DocumentoUpdate.situacao tem dominio fechado na entrada.

"validado" e valores fora do dominio sao recusados com 422 sem efeito; os
valores do dominio ("pendente", "rejeitado") passam.
"""
import asyncio

import pytest

from .test_h03_documentos_validacao import _create_doc, _reload_doc, h03_db  # noqa: F401
from .test_d3_admissao import _client, _setup
from .test_d2_rotina import _code


@pytest.mark.parametrize("situacao", ["validado", " validado ", "aprovado", "VALIDADO", "", 1])
def test_put_situacao_fora_do_dominio_422_sem_efeito(h03_db, situacao):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db)
        doc = await _create_doc(client, h, resident.id)
        r = await client.put(f"/api/documentos/{doc['id']}", headers=h, json={"situacao": situacao})
        assert r.status_code == 422, r.text
        if situacao in ("validado", " validado "):
            assert _code(r) == "DOCUMENTO_TRANSICAO_PROTEGIDA"
        stored = await _reload_doc(db, doc["id"])
        assert stored.situacao == "pendente"
        assert stored.validado_por is None
    asyncio.run(_client(h03_db, op))


@pytest.mark.parametrize("situacao,esperada", [("rejeitado", "rejeitado"), (" rejeitado ", "rejeitado"), ("pendente", "pendente")])
def test_put_situacao_no_dominio_passa(h03_db, situacao, esperada):
    async def op(client, db):
        tenant, user, resident, employee, h = await _setup(db)
        doc = await _create_doc(client, h, resident.id)
        r = await client.put(f"/api/documentos/{doc['id']}", headers=h, json={"situacao": situacao})
        assert r.status_code == 200, r.text
        assert r.json()["situacao"] == esperada
        stored = await _reload_doc(db, doc["id"])
        assert stored.situacao == esperada
    asyncio.run(_client(h03_db, op))
