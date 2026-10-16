"""UX-10 (#98): GET /api/perfis/{id}/permissoes — permissoes reais do perfil.

Sem esta leitura a tela de perfis partia de "tudo marcado" e, como o PUT
substitui a lista inteira, salvar concedia ou apagava permissoes sem intencao.
O contrato: devolve exatamente o que o perfil tem, marca o que o PUT local nao
aceita (e por isso apagaria) e respeita o tenant da sessao. Banco descartavel.
"""

from __future__ import annotations

from tests.test_ux01_permissoes_sessao import (  # noqa: F401 (fixture importada)
    _headers,
    _ilpi_user,
    _with_client,
    ux01_db,
)

import asyncio


ADMIN = {"perfis:ler", "perfis:atribuir_permissao", "funcionarios:ler"}


def _chaves(body: dict) -> set[str]:
    return {item["chave"] for item in body["permissoes"]}


def test_devolve_exatamente_as_permissoes_do_perfil(ux01_db):
    async def op(client, db):
        user, ilpi, perfil = await _ilpi_user(db, permissions=ADMIN)
        r = await client.get(f"/api/perfis/{perfil.id}/permissoes", headers=_headers(user, scope="ilpi", ilpi_id=ilpi.id))
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["perfil_id"] == perfil.id
        assert _chaves(body) == ADMIN
        assert all(item["editavel"] for item in body["permissoes"]) and body["editavel"] is True
        assert {"modulo", "acao", "descricao"} <= set(body["permissoes"][0])
    asyncio.run(_with_client(ux01_db, op))


def test_permissao_clinica_marca_perfil_como_nao_editavel_localmente(ux01_db):
    async def op(client, db):
        user, ilpi, perfil = await _ilpi_user(db, permissions=ADMIN | {"residentes:ler"})
        r = await client.get(f"/api/perfis/{perfil.id}/permissoes", headers=_headers(user, scope="ilpi", ilpi_id=ilpi.id))
        assert r.status_code == 200, r.text
        body = r.json()
        por_chave = {item["chave"]: item for item in body["permissoes"]}
        assert por_chave["residentes:ler"]["editavel"] is False
        assert por_chave["perfis:ler"]["editavel"] is True
        assert body["editavel"] is False
    asyncio.run(_with_client(ux01_db, op))


def test_perfil_de_outra_ilpi_responde_404(ux01_db):
    async def op(client, db):
        _, _, perfil_a = await _ilpi_user(db, permissions=ADMIN)
        user_b, ilpi_b, _ = await _ilpi_user(db, permissions=ADMIN)
        r = await client.get(f"/api/perfis/{perfil_a.id}/permissoes", headers=_headers(user_b, scope="ilpi", ilpi_id=ilpi_b.id))
        assert r.status_code == 404, r.text
        inexistente = await client.get("/api/perfis/nao-existe/permissoes", headers=_headers(user_b, scope="ilpi", ilpi_id=ilpi_b.id))
        assert inexistente.status_code == 404
        # Mesma resposta para outra ILPI e para inexistente: sem vazar existência.
        assert r.json() == inexistente.json()
    asyncio.run(_with_client(ux01_db, op))


def test_sem_perfis_ler_e_recusado(ux01_db):
    async def op(client, db):
        user, ilpi, perfil = await _ilpi_user(db, permissions={"funcionarios:ler"})
        r = await client.get(f"/api/perfis/{perfil.id}/permissoes", headers=_headers(user, scope="ilpi", ilpi_id=ilpi.id))
        assert r.status_code == 403, r.text
    asyncio.run(_with_client(ux01_db, op))


def test_leitura_reflete_o_put(ux01_db):
    async def op(client, db):
        user, ilpi, perfil = await _ilpi_user(db, permissions=ADMIN)
        h = _headers(user, scope="ilpi", ilpi_id=ilpi.id)
        nova = sorted(ADMIN | {"usuarios:ler"})
        r = await client.put(f"/api/perfis/{perfil.id}/permissoes", json={"permissoes": nova}, headers=h)
        assert r.status_code == 200, r.text
        r = await client.get(f"/api/perfis/{perfil.id}/permissoes", headers=h)
        assert r.status_code == 200, r.text
        assert _chaves(r.json()) == set(nova)
    asyncio.run(_with_client(ux01_db, op))
