"""SAFE2-B: prova de posse na troca de senha (H01) e replay de refresh (M01).

Um unico banco descartavel por modulo: a migration roda uma vez e cada teste cria
a propria ILPI, o proprio perfil e o proprio usuario, entao os cenarios nao se
cruzam sem pagar uma migration por teste.

Nenhum teste toca storage/app.db.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys
import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tests.db_safety import run_alembic

ROOT = pathlib.Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from src import main  # noqa: E402
from src.application import auth  # noqa: E402
from src.application import schemas as s  # noqa: E402
from src.infrastructure import database  # noqa: E402
from src.infrastructure import models as m  # noqa: E402

SENHA_INICIAL = "SenhaInicial123A"
SENHA_NOVA = "SenhaNova456B"
SENHA_TEMPORARIA = "TempInicial789C"


# ------------------------------------------------------------- infra ------

@pytest.fixture(scope="module")
def safe2b_db(tmp_path_factory) -> pathlib.Path:
    caminho = tmp_path_factory.mktemp("safe2b") / "safe2b.db"
    url = f"sqlite+aiosqlite:///{caminho.resolve().as_posix()}"
    resultado = run_alembic(url, "upgrade", "head")
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    return caminho


async def _com_cliente(caminho: pathlib.Path, operacao):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{caminho.resolve().as_posix()}", poolclass=NullPool
    )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    main.app.dependency_overrides[main.get_db] = override_get_db
    main.app.dependency_overrides[database.get_db] = override_get_db
    auth._rate_store.clear()
    transport = httpx.ASGITransport(app=main.app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            async with factory() as session:
                return await operacao(client, session)
    finally:
        main.app.dependency_overrides.clear()
        await engine.dispose()


def _executa(caminho: pathlib.Path, cenario) -> None:
    asyncio.run(_com_cliente(caminho, cenario))


async def _criar_usuario(
    session: AsyncSession,
    *,
    senha: str,
    exige_troca: bool = False,
    com_vinculo: bool = True,
) -> str:
    """Cria usuario isolado. Com vinculo ativo, o login resolve contexto e volta 200.

    Sem vinculo, `load_security_context` nega — por isso so o usuario de primeiro
    acesso (que nao resolve contexto enquanto a flag estiver de pe) dispensa ILPI.
    """
    sufixo = uuid.uuid4().hex[:10]
    usuario = m.User(
        id=str(uuid.uuid4()),
        nome=f"Usuario SAFE2B {sufixo}",
        # Dominio comum de proposito: EmailStr recusa .test/.example por serem
        # reservados, e o login passa pela validacao do schema antes do hash.
        email=f"safe2b-{sufixo}@safe2b.com.br",
        password_hash=auth.hash_password(senha),
        ativo=True,
        is_superuser=False,
        exige_troca_senha=exige_troca,
    )
    session.add(usuario)

    if com_vinculo:
        ilpi = m.Instituicao(
            id=str(uuid.uuid4()),
            razao_social=f"ILPI SAFE2B {sufixo}",
            situacao="ativa",
        )
        perfil = m.Perfil(
            id=str(uuid.uuid4()),
            ilpi_id=ilpi.id,
            nome="Perfil SAFE2B",
            chave=f"safe2b_{sufixo}",
            escopo="ilpi",
            situacao="ativo",
        )
        vinculo = m.UsuarioIlpiPerfil(
            id=str(uuid.uuid4()),
            usuario_id=usuario.id,
            ilpi_id=ilpi.id,
            perfil_id=perfil.id,
            situacao="ativo",
            # Explicito e no passado: evita depender de CURRENT_TIMESTAMP do banco
            # coincidir com o relogio do processo em _is_current_link.
            data_inicial=datetime.now(timezone.utc) - timedelta(days=1),
        )
        # Escopo ILPI exige tambem funcionario ativo (security.py:455); sem ele o
        # contexto e negado e o login volta 403 mesmo com vinculo de perfil.
        funcionario = m.Funcionario(
            id=str(uuid.uuid4()),
            ilpi_id=ilpi.id,
            usuario_id=usuario.id,
            nome=usuario.nome,
            situacao="ativo",
        )
        session.add_all([ilpi, perfil, vinculo, funcionario])

    await session.commit()
    return usuario.email


async def _login(client: httpx.AsyncClient, email: str, senha: str) -> httpx.Response:
    return await client.post("/api/auth/token", json={"email": email, "password": senha})


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _trocar_senha(client, token, *, atual, nova, confirmar=None):
    return await client.put(
        "/api/auth/password",
        headers=_headers(token),
        json={
            "senha_atual": atual,
            "nova_senha": nova,
            "confirmar_senha": nova if confirmar is None else confirmar,
        },
    )


async def _refresh_com(client: httpx.AsyncClient, raw_token: str) -> httpx.Response:
    client.cookies.clear()
    return await client.post(
        "/api/auth/refresh", headers={"Cookie": f"refresh_token={raw_token}"}
    )


async def _linha_do_token(session: AsyncSession, raw_token: str) -> m.RefreshToken:
    linha = (
        await session.execute(
            select(m.RefreshToken).where(
                m.RefreshToken.token_hash == auth.token_hash(raw_token)
            )
        )
    ).scalar_one()
    await session.refresh(linha)
    return linha


# --------------------------------------------------------------- H01 ------

def test_h01_troca_com_senha_atual_correta(safe2b_db):
    async def cenario(client, session):
        email = await _criar_usuario(session, senha=SENHA_INICIAL)
        login = await _login(client, email, SENHA_INICIAL)
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]

        troca = await _trocar_senha(client, token, atual=SENHA_INICIAL, nova=SENHA_NOVA)
        assert troca.status_code == 200, troca.text

    _executa(safe2b_db, cenario)


def test_h01_senha_antiga_nao_autentica_e_nova_autentica(safe2b_db):
    async def cenario(client, session):
        email = await _criar_usuario(session, senha=SENHA_INICIAL)
        login = await _login(client, email, SENHA_INICIAL)
        token = login.json()["access_token"]
        assert (await _trocar_senha(client, token, atual=SENHA_INICIAL, nova=SENHA_NOVA)).status_code == 200

        antiga = await _login(client, email, SENHA_INICIAL)
        assert antiga.status_code == 401

        nova = await _login(client, email, SENHA_NOVA)
        assert nova.status_code == 200, nova.text

    _executa(safe2b_db, cenario)


def test_h01_senha_atual_incorreta_e_recusada(safe2b_db):
    async def cenario(client, session):
        email = await _criar_usuario(session, senha=SENHA_INICIAL)
        login = await _login(client, email, SENHA_INICIAL)
        token = login.json()["access_token"]

        troca = await _trocar_senha(client, token, atual="SenhaErrada999Z", nova=SENHA_NOVA)
        assert troca.status_code == 400

        # Nada foi escrito: a senha original continua valendo.
        assert (await _login(client, email, SENHA_INICIAL)).status_code == 200
        assert (await _login(client, email, SENHA_NOVA)).status_code == 401

    _executa(safe2b_db, cenario)


def test_h01_confirmacao_divergente_e_recusada(safe2b_db):
    async def cenario(client, session):
        email = await _criar_usuario(session, senha=SENHA_INICIAL)
        login = await _login(client, email, SENHA_INICIAL)
        token = login.json()["access_token"]

        troca = await _trocar_senha(
            client, token, atual=SENHA_INICIAL, nova=SENHA_NOVA, confirmar="OutraCoisa123A"
        )
        assert troca.status_code == 400
        assert (await _login(client, email, SENHA_INICIAL)).status_code == 200

    _executa(safe2b_db, cenario)


def test_h01_nova_igual_a_atual_e_recusada(safe2b_db):
    """Trocar a temporaria por ela mesma encerraria o primeiro acesso sem trocar nada."""
    async def cenario(client, session):
        email = await _criar_usuario(
            session, senha=SENHA_TEMPORARIA, exige_troca=True, com_vinculo=False
        )
        login = await _login(client, email, SENHA_TEMPORARIA)
        assert login.status_code == 200, login.text
        assert login.json()["exige_troca_senha"] is True
        token = login.json()["access_token"]

        troca = await _trocar_senha(
            client, token, atual=SENHA_TEMPORARIA, nova=SENHA_TEMPORARIA
        )
        assert troca.status_code == 400

        usuario = (
            await session.execute(select(m.User).where(m.User.email == email))
        ).scalar_one()
        await session.refresh(usuario)
        assert usuario.exige_troca_senha is True

    _executa(safe2b_db, cenario)


def test_h01_primeiro_acesso_comum_usa_a_senha_temporaria(safe2b_db):
    """Usuario criado com senha temporaria troca informando a propria temporaria.

    E o caminho que a tela /primeiro-acesso do frontend usa: PUT /auth/password.
    Nao ha excecao para `exige_troca_senha` — a temporaria E a senha atual.
    """
    async def cenario(client, session):
        email = await _criar_usuario(
            session, senha=SENHA_TEMPORARIA, exige_troca=True, com_vinculo=False
        )
        login = await _login(client, email, SENHA_TEMPORARIA)
        assert login.status_code == 200, login.text
        token = login.json()["access_token"]

        troca = await _trocar_senha(client, token, atual=SENHA_TEMPORARIA, nova=SENHA_NOVA)
        assert troca.status_code == 200, troca.text

        usuario = (
            await session.execute(select(m.User).where(m.User.email == email))
        ).scalar_one()
        await session.refresh(usuario)
        assert usuario.exige_troca_senha is False

    _executa(safe2b_db, cenario)


def test_h01_contrato_do_bootstrap_permanece_intacto():
    """`/auth/primeiro-acesso` e o caminho do bootstrap da plataforma e nao muda.

    O fluxo completo dele continua coberto por
    test_fase3a_bootstrap_auth::test_fase3a_full_auth_onboarding_and_admin_flow;
    aqui so se afirma que a exigencia de senha atual nao vazou para o contrato.
    """
    assert set(s.PrimeiroAcessoUpdate.model_fields) == {"nova_senha", "confirmar"}
    assert set(s.PasswordUpdate.model_fields) == {
        "senha_atual",
        "nova_senha",
        "confirmar_senha",
    }


def test_h01_politica_de_forca_nao_se_aplica_a_senha_atual():
    """Conta antiga pode ter senha fora da politica; exigi-la aqui travaria a troca."""
    modelo = s.PasswordUpdate(
        senha_atual="x", nova_senha=SENHA_NOVA, confirmar_senha=SENHA_NOVA
    )
    assert modelo.senha_atual == "x"
    with pytest.raises(ValueError):
        s.PasswordUpdate(senha_atual="x", nova_senha="fraca", confirmar_senha="fraca")


# --------------------------------------------------------------- M01 ------

def test_m01_refresh_valido_rotaciona(safe2b_db):
    async def cenario(client, session):
        email = await _criar_usuario(session, senha=SENHA_INICIAL)
        assert (await _login(client, email, SENHA_INICIAL)).status_code == 200
        primeiro = client.cookies.get("refresh_token")

        renovado = await client.post("/api/auth/refresh")
        assert renovado.status_code == 200, renovado.text
        segundo = client.cookies.get("refresh_token")
        assert segundo and segundo != primeiro

        anterior = await _linha_do_token(session, primeiro)
        atual = await _linha_do_token(session, segundo)
        assert anterior.revoked_at is not None
        assert anterior.replaced_by == atual.id
        assert atual.revoked_at is None
        assert atual.token_family == anterior.token_family

    _executa(safe2b_db, cenario)


def test_m01_replay_do_anterior_revoga_a_familia(safe2b_db):
    async def cenario(client, session):
        email = await _criar_usuario(session, senha=SENHA_INICIAL)
        await _login(client, email, SENHA_INICIAL)
        primeiro = client.cookies.get("refresh_token")
        assert (await client.post("/api/auth/refresh")).status_code == 200
        segundo = client.cookies.get("refresh_token")

        replay = await _refresh_com(client, primeiro)
        assert replay.status_code == 401

        # O token ATIVO cai junto: ele e o que pode estar com quem roubou.
        ativo = await _linha_do_token(session, segundo)
        assert ativo.revoked_at is not None

    _executa(safe2b_db, cenario)


def test_m01_descendente_da_familia_comprometida_deixa_de_funcionar(safe2b_db):
    async def cenario(client, session):
        email = await _criar_usuario(session, senha=SENHA_INICIAL)
        await _login(client, email, SENHA_INICIAL)
        primeiro = client.cookies.get("refresh_token")
        assert (await client.post("/api/auth/refresh")).status_code == 200
        segundo = client.cookies.get("refresh_token")

        assert (await _refresh_com(client, primeiro)).status_code == 401
        # Antes da SAFE2-B este seguia renovando indefinidamente.
        assert (await _refresh_com(client, segundo)).status_code == 401

    _executa(safe2b_db, cenario)


def test_m01_familia_independente_do_mesmo_usuario_sobrevive(safe2b_db):
    """Cada login abre familia nova: derrubar a comprometida nao desloga o resto."""
    async def cenario(client, session):
        email = await _criar_usuario(session, senha=SENHA_INICIAL)

        await _login(client, email, SENHA_INICIAL)
        familia_a_primeiro = client.cookies.get("refresh_token")
        assert (await client.post("/api/auth/refresh")).status_code == 200

        client.cookies.clear()
        await _login(client, email, SENHA_INICIAL)
        familia_b = client.cookies.get("refresh_token")

        linha_a = await _linha_do_token(session, familia_a_primeiro)
        linha_b = await _linha_do_token(session, familia_b)
        assert linha_a.token_family != linha_b.token_family

        assert (await _refresh_com(client, familia_a_primeiro)).status_code == 401
        renovado_b = await _refresh_com(client, familia_b)
        assert renovado_b.status_code == 200, renovado_b.text

    _executa(safe2b_db, cenario)


def test_m01_token_apenas_expirado_nao_revoga_a_familia(safe2b_db):
    """Expiracao nao e evidencia de roubo: 401 simples, sessao preservada."""
    async def cenario(client, session):
        email = await _criar_usuario(session, senha=SENHA_INICIAL)
        await _login(client, email, SENHA_INICIAL)
        assert (await client.post("/api/auth/refresh")).status_code == 200
        ativo_raw = client.cookies.get("refresh_token")

        linha = await _linha_do_token(session, ativo_raw)
        linha.expires_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        await session.commit()

        assert (await _refresh_com(client, ativo_raw)).status_code == 401

        linha = await _linha_do_token(session, ativo_raw)
        assert linha.revoked_at is None, "expiracao nao pode disparar revogacao de familia"

    _executa(safe2b_db, cenario)


def test_m01_logout_preserva_o_comportamento(safe2b_db):
    async def cenario(client, session):
        email = await _criar_usuario(session, senha=SENHA_INICIAL)
        await _login(client, email, SENHA_INICIAL)

        assert (await client.post("/api/auth/logout")).status_code == 200
        assert (await client.post("/api/auth/refresh")).status_code == 401

    _executa(safe2b_db, cenario)


def test_m01_replay_e_auditado_sem_expor_segredo(safe2b_db):
    async def cenario(client, session):
        email = await _criar_usuario(session, senha=SENHA_INICIAL)
        await _login(client, email, SENHA_INICIAL)
        primeiro = client.cookies.get("refresh_token")
        assert (await client.post("/api/auth/refresh")).status_code == 200
        segundo = client.cookies.get("refresh_token")

        assert (await _refresh_com(client, primeiro)).status_code == 401

        usuario = (
            await session.execute(select(m.User).where(m.User.email == email))
        ).scalar_one()
        # Filtra pelo usuario: o banco do modulo e compartilhado e outros
        # cenarios deste arquivo tambem disparam replay.
        registros = (
            await session.execute(
                select(m.Auditoria).where(
                    m.Auditoria.acao == "auth.refresh_replay",
                    m.Auditoria.usuario_id == usuario.id,
                )
            )
        ).scalars().all()
        assert len(registros) == 1

        texto = "\n".join(
            parte
            for registro in registros
            for parte in (
                registro.valores_anteriores or "",
                registro.valores_posteriores or "",
                registro.registro_id or "",
            )
        )
        for segredo in (primeiro, segundo, auth.token_hash(primeiro)):
            assert segredo not in texto

    _executa(safe2b_db, cenario)


def test_m01_resposta_de_replay_e_igual_a_de_token_invalido(safe2b_db):
    """Quem replica nao pode descobrir que disparou a deteccao."""
    async def cenario(client, session):
        email = await _criar_usuario(session, senha=SENHA_INICIAL)
        await _login(client, email, SENHA_INICIAL)
        primeiro = client.cookies.get("refresh_token")
        assert (await client.post("/api/auth/refresh")).status_code == 200

        replay = await _refresh_com(client, primeiro)
        inexistente = await _refresh_com(client, "token-que-nunca-existiu")

        assert replay.status_code == inexistente.status_code == 401
        assert replay.json() == inexistente.json()

    _executa(safe2b_db, cenario)
