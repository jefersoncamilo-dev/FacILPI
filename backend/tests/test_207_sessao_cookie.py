"""#207: access token em cookie HttpOnly, CSRF double-submit e Bearer na transicao.

Banco SQLite descartavel do SAFE2-B (um por modulo). Nenhum teste toca storage/app.db.
"""

from __future__ import annotations

from sqlalchemy import select

from tests.test_safe2b_auth_hardening import (  # noqa: F401  (fixture)
    SENHA_INICIAL,
    _criar_usuario,
    _executa,
    _headers,
    _login,
    safe2b_db,
)
from src.infrastructure import models as m


def _set_cookies(resposta) -> dict[str, str]:
    linhas = resposta.headers.get_list("set-cookie")
    return {linha.split("=", 1)[0]: linha.lower() for linha in linhas}


async def _vinculo(session, email):
    usuario = (await session.execute(select(m.User).where(m.User.email == email))).scalar_one()
    return (
        await session.execute(
            select(m.UsuarioIlpiPerfil).where(m.UsuarioIlpiPerfil.usuario_id == usuario.id)
        )
    ).scalar_one()


def _payload_contexto(vinculo):
    return {"scope": "ilpi", "ilpi_id": vinculo.ilpi_id, "perfil_id": vinculo.perfil_id}


def test_login_grava_access_httponly_strict_e_csrf_legivel(safe2b_db):
    async def cenario(client, session):
        email = await _criar_usuario(session, senha=SENHA_INICIAL)
        resposta = await _login(client, email, SENHA_INICIAL)
        assert resposta.status_code == 200, resposta.text
        cookies = _set_cookies(resposta)
        assert "httponly" in cookies["access_token"]
        assert "samesite=strict" in cookies["access_token"]
        assert "path=/api" in cookies["access_token"]
        assert "httponly" not in cookies["csrf_token"]
        assert "samesite=strict" in cookies["csrf_token"]
        # Transicao: o corpo ainda traz o token para clientes antigos.
        assert resposta.json()["access_token"] == client.cookies.get("access_token")

    _executa(safe2b_db, cenario)


def test_leitura_autentica_so_pelo_cookie(safe2b_db):
    async def cenario(client, session):
        email = await _criar_usuario(session, senha=SENHA_INICIAL)
        await _login(client, email, SENHA_INICIAL)
        resposta = await client.get("/api/auth/permissoes")
        assert resposta.status_code == 200, resposta.text

    _executa(safe2b_db, cenario)


def test_escrita_pelo_cookie_sem_csrf_e_recusada(safe2b_db):
    async def cenario(client, session):
        email = await _criar_usuario(session, senha=SENHA_INICIAL)
        await _login(client, email, SENHA_INICIAL)
        vinculo = await _vinculo(session, email)
        sem = await client.post("/api/auth/contexto", json=_payload_contexto(vinculo))
        assert sem.status_code == 403
        assert sem.json()["detail"]["code"] == "CSRF_FAILED"
        errado = await client.post(
            "/api/auth/contexto",
            json=_payload_contexto(vinculo),
            headers={"X-CSRF-Token": "outro-valor"},
        )
        assert errado.status_code == 403
        certo = await client.post(
            "/api/auth/contexto",
            json=_payload_contexto(vinculo),
            headers={"X-CSRF-Token": client.cookies.get("csrf_token")},
        )
        assert certo.status_code == 200, certo.text

    _executa(safe2b_db, cenario)


def test_bearer_continua_valendo_sem_csrf(safe2b_db):
    async def cenario(client, session):
        email = await _criar_usuario(session, senha=SENHA_INICIAL)
        token = (await _login(client, email, SENHA_INICIAL)).json()["access_token"]
        vinculo = await _vinculo(session, email)
        client.cookies.clear()
        resposta = await client.post(
            "/api/auth/contexto", json=_payload_contexto(vinculo), headers=_headers(token)
        )
        assert resposta.status_code == 200, resposta.text

    _executa(safe2b_db, cenario)


def test_bearer_malformado_nao_cai_para_o_cookie(safe2b_db):
    async def cenario(client, session):
        email = await _criar_usuario(session, senha=SENHA_INICIAL)
        await _login(client, email, SENHA_INICIAL)
        resposta = await client.get("/api/auth/permissoes", headers={"Authorization": "Basic x"})
        assert resposta.status_code == 401

    _executa(safe2b_db, cenario)


def test_logout_pelo_cookie_revoga_no_servidor_e_limpa_cookies(safe2b_db):
    async def cenario(client, session):
        email = await _criar_usuario(session, senha=SENHA_INICIAL)
        await _login(client, email, SENHA_INICIAL)
        access = client.cookies.get("access_token")
        saida = await client.post("/api/auth/logout")
        assert saida.status_code == 200
        cookies = _set_cookies(saida)
        assert "max-age=0" in cookies["access_token"]
        assert "max-age=0" in cookies["csrf_token"]
        # O cookie antigo, reapresentado, nao vale mais: a familia caiu no servidor.
        client.cookies.clear()
        depois = await client.get("/api/auth/permissoes", cookies={"access_token": access})
        assert depois.status_code == 401

    _executa(safe2b_db, cenario)
