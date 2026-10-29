"""N3: auditoria de acesso (login, login recusado, troca de contexto, primeiro acesso).

Reaproveita a infraestrutura descartavel do SAFE2-B: banco SQLite temporario
por modulo, migrado do zero. Nenhum teste toca storage/app.db.
"""

from __future__ import annotations

import json
import uuid

from sqlalchemy import select

from tests.test_safe2b_auth_hardening import (  # noqa: F401  (fixture)
    SENHA_INICIAL,
    SENHA_NOVA,
    SENHA_TEMPORARIA,
    _criar_usuario,
    _executa,
    _headers,
    _login,
    _trocar_senha,
    safe2b_db,
)
from src.infrastructure import models as m


async def _auditorias(session, usuario_id, acao):
    # Sem expire_all: as linhas de auditoria sao novas para esta sessao, e
    # expirar o usuario forcaria lazy load sincrono no teste.
    linhas = (
        await session.execute(
            select(m.Auditoria).where(
                m.Auditoria.usuario_id == usuario_id, m.Auditoria.acao == acao
            )
        )
    ).scalars().all()
    return list(linhas)


async def _usuario(session, email):
    return (await session.execute(select(m.User).where(m.User.email == email))).scalar_one()


def _sem_segredo(linha, *segredos):
    texto = " ".join(
        str(v or "") for v in (linha.valores_anteriores, linha.valores_posteriores)
    )
    for segredo in segredos:
        assert segredo not in texto
    assert "password" not in texto and "token" not in texto


def test_login_com_sucesso_e_auditado_com_contexto_do_servidor(safe2b_db):
    async def cenario(client, session):
        email = await _criar_usuario(session, senha=SENHA_INICIAL)
        resposta = await _login(client, email, SENHA_INICIAL)
        assert resposta.status_code == 200, resposta.text
        usuario = await _usuario(session, email)
        vinculo = (
            await session.execute(
                select(m.UsuarioIlpiPerfil).where(m.UsuarioIlpiPerfil.usuario_id == usuario.id)
            )
        ).scalar_one()

        linhas = await _auditorias(session, usuario.id, "auth.login")
        assert len(linhas) == 1
        linha = linhas[0]
        assert linha.ilpi_id == vinculo.ilpi_id
        dados = json.loads(linha.valores_posteriores)
        assert dados["scope"] == "ilpi"
        assert dados["perfil_id"] == vinculo.perfil_id
        assert dados["sessao"]
        _sem_segredo(linha, SENHA_INICIAL, resposta.json()["access_token"],
                     client.cookies.get("refresh_token"))

    _executa(safe2b_db, cenario)


def test_login_recusado_por_senha_errada_e_auditado_sem_a_senha(safe2b_db):
    async def cenario(client, session):
        email = await _criar_usuario(session, senha=SENHA_INICIAL)
        resposta = await _login(client, email, "SenhaErrada999Z")
        assert resposta.status_code == 401
        usuario = await _usuario(session, email)
        linhas = await _auditorias(session, usuario.id, "auth.login_recusado")
        assert len(linhas) == 1
        assert json.loads(linhas[0].valores_posteriores) == {"motivo": "credenciais_invalidas"}
        _sem_segredo(linhas[0], "SenhaErrada999Z", usuario.password_hash)
        assert await _auditorias(session, usuario.id, "auth.login") == []

    _executa(safe2b_db, cenario)


def test_login_recusado_de_conta_inexistente_nao_grava_o_login_digitado(safe2b_db):
    async def cenario(client, session):
        email = f"inexistente-{uuid.uuid4().hex[:8]}@safe2b.com.br"
        resposta = await _login(client, email, "QualquerSenha1A")
        assert resposta.status_code == 401
        session.expire_all()
        linhas = (
            await session.execute(
                select(m.Auditoria).where(
                    m.Auditoria.acao == "auth.login_recusado",
                    m.Auditoria.usuario_id.is_(None),
                )
            )
        ).scalars().all()
        assert linhas
        for linha in linhas:
            assert email not in (linha.valores_posteriores or "")
            assert "QualquerSenha1A" not in (linha.valores_posteriores or "")

    _executa(safe2b_db, cenario)


def test_login_recusado_de_usuario_inativo_e_auditado(safe2b_db):
    async def cenario(client, session):
        email = await _criar_usuario(session, senha=SENHA_INICIAL)
        usuario = await _usuario(session, email)
        usuario.ativo = False
        await session.commit()
        resposta = await _login(client, email, SENHA_INICIAL)
        assert resposta.status_code == 401
        linhas = await _auditorias(session, usuario.id, "auth.login_recusado")
        assert [json.loads(l.valores_posteriores) for l in linhas] == [{"motivo": "usuario_inativo"}]

    _executa(safe2b_db, cenario)


def test_troca_de_contexto_e_auditada(safe2b_db):
    async def cenario(client, session):
        email = await _criar_usuario(session, senha=SENHA_INICIAL)
        login = await _login(client, email, SENHA_INICIAL)
        token = login.json()["access_token"]
        usuario = await _usuario(session, email)
        vinculo = (
            await session.execute(
                select(m.UsuarioIlpiPerfil).where(m.UsuarioIlpiPerfil.usuario_id == usuario.id)
            )
        ).scalar_one()
        troca = await client.post(
            "/api/auth/contexto",
            headers=_headers(token),
            json={"scope": "ilpi", "ilpi_id": vinculo.ilpi_id, "perfil_id": vinculo.perfil_id},
        )
        assert troca.status_code == 200, troca.text
        linhas = await _auditorias(session, usuario.id, "auth.contexto_selecionado")
        assert len(linhas) == 1
        assert linhas[0].ilpi_id == vinculo.ilpi_id
        assert json.loads(linhas[0].valores_posteriores)["perfil_id"] == vinculo.perfil_id
        _sem_segredo(linhas[0], token, troca.json()["access_token"])

    _executa(safe2b_db, cenario)


def test_primeiro_acesso_pela_troca_de_senha_e_marcado(safe2b_db):
    async def cenario(client, session):
        email = await _criar_usuario(
            session, senha=SENHA_TEMPORARIA, exige_troca=True, com_vinculo=False
        )
        login = await _login(client, email, SENHA_TEMPORARIA)
        troca = await _trocar_senha(
            client, login.json()["access_token"], atual=SENHA_TEMPORARIA, nova=SENHA_NOVA
        )
        assert troca.status_code == 200, troca.text
        usuario = await _usuario(session, email)
        linhas = await _auditorias(session, usuario.id, "auth.senha_alterada")
        assert len(linhas) == 1
        # `exige_troca_senha` some na sanitizacao (chave contem "senha").
        assert json.loads(linhas[0].valores_posteriores) == {"primeiro_acesso": True}
        _sem_segredo(linhas[0], SENHA_TEMPORARIA, SENHA_NOVA)

    _executa(safe2b_db, cenario)
