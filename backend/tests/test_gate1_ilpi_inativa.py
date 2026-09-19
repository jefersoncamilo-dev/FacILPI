"""GATE-1: uma ILPI inativa nao concede mais contexto institucional.

Antes desta correcao, `inativar` mudava um campo e mais nada: os usuarios da
instituicao seguiam operando normalmente. O bloqueio mora em
`load_security_context`, que roda em toda requisicao institucional — e e isso
que faz um token emitido ANTES da inativacao parar de valer na requisicao
seguinte, sem revogar sessao alguma.

Escopo deliberado: apenas INATIVA. RASCUNHO (GATE-2) e SUSPENSA seguem com o
comportamento atual, e ha teste aqui para provar que seguem.

A infraestrutura espelha test_platform1a_provisionamento.py: banco descartavel
migrado uma vez por modulo. Nenhum teste toca storage/app.db.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import random
import sys
import uuid
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from tests.db_safety import run_alembic

BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from src import main  # noqa: E402
from src.application import auth  # noqa: E402
from src.application.fase3a import ADMIN_EMAIL, ILPI_ACTIVE, ILPI_DRAFT  # noqa: E402
from src.application.security import ILPI_INATIVA  # noqa: E402
from src.infrastructure import database  # noqa: E402
from src.infrastructure import models as m  # noqa: E402
from src.scripts import bootstrap as bootstrap_script  # noqa: E402

BOOTSTRAP_TOKEN = "gate1-test-bootstrap-token"
OPERADOR_SENHA = "SenhaOperador123A"
GESTOR_SENHA = "SenhaGestor456B"


# ------------------------------------------------------------- infra ------

def _engine_e_factory(caminho: pathlib.Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{caminho.resolve().as_posix()}", poolclass=NullPool
    )
    return engine, async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


def _override(factory):
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    return override_get_db


@pytest.fixture(scope="module")
def gate1_db(tmp_path_factory) -> pathlib.Path:
    caminho = tmp_path_factory.mktemp("gate1") / "gate1.db"
    url = f"sqlite+aiosqlite:///{caminho.resolve().as_posix()}"
    resultado = run_alembic(url, "upgrade", "head")
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr

    async def inicializar():
        engine, factory = _engine_e_factory(caminho)
        original_session = bootstrap_script.SessionLocal
        original_token = os.environ.get("BOOTSTRAP_TOKEN")
        bootstrap_script.SessionLocal = factory
        os.environ["BOOTSTRAP_TOKEN"] = BOOTSTRAP_TOKEN
        try:
            resultado_bootstrap = await bootstrap_script.run_bootstrap(BOOTSTRAP_TOKEN)
            main.app.dependency_overrides[main.get_db] = _override(factory)
            main.app.dependency_overrides[database.get_db] = _override(factory)
            transport = httpx.ASGITransport(app=main.app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
                login = await client.post(
                    "/api/auth/token",
                    json={"email": ADMIN_EMAIL, "password": resultado_bootstrap.temporary_password},
                )
                assert login.status_code == 200, login.text
                troca = await client.put(
                    "/api/auth/primeiro-acesso",
                    headers={"Authorization": f"Bearer {login.json()['access_token']}"},
                    json={"nova_senha": OPERADOR_SENHA, "confirmar": OPERADOR_SENHA},
                )
                assert troca.status_code == 200, troca.text
        finally:
            main.app.dependency_overrides.clear()
            bootstrap_script.SessionLocal = original_session
            if original_token is None:
                os.environ.pop("BOOTSTRAP_TOKEN", None)
            else:
                os.environ["BOOTSTRAP_TOKEN"] = original_token
            await engine.dispose()

    asyncio.run(inicializar())
    return caminho


async def _com_cliente(caminho: pathlib.Path, operacao):
    engine, factory = _engine_e_factory(caminho)
    main.app.dependency_overrides[main.get_db] = _override(factory)
    main.app.dependency_overrides[database.get_db] = _override(factory)
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


def _headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _codigo(resposta: httpx.Response) -> str | None:
    detalhe = resposta.json().get("detail")
    return detalhe.get("code") if isinstance(detalhe, dict) else None


# ------------------------------------------------------ provisionamento ---

async def _token_operador(client: httpx.AsyncClient) -> str:
    login = await client.post(
        "/api/auth/token", json={"email": ADMIN_EMAIL, "password": OPERADOR_SENHA}
    )
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


def _cnpj_valido() -> str:
    """CNPJ sintetico com digitos verificadores corretos.

    Ativar exige CNPJ valido e a coluna e unica, entao cada ILPI deste modulo
    precisa do seu — fixar um literal faria o segundo teste colidir.
    """
    base = [random.randint(0, 9) for _ in range(12)]
    for pesos in ([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]):
        soma = sum(d * p for d, p in zip(base, pesos))
        resto = soma % 11
        base.append(0 if resto < 2 else 11 - resto)
    return "".join(str(d) for d in base)


async def _provisionar(client, *, ativar: bool) -> tuple[str, str]:
    """Cria ILPI + primeiro gestor e devolve (ilpi_id, email do gestor).

    O gestor sai daqui com a senha definitiva `GESTOR_SENHA`: a temporaria ja foi
    trocada pela via oficial, entao o login seguinte devolve contexto ILPI real.
    """
    operador = await _token_operador(client)
    criada = await client.post(
        "/api/platform/instituicoes",
        headers=_headers(operador),
        json={
            "razao_social": f"ILPI GATE1 {uuid.uuid4().hex[:6]}",
            "capacidade": 10,
            "uf": "SP",
            "cnpj": _cnpj_valido(),
        },
    )
    assert criada.status_code == 201, criada.text
    ilpi_id = criada.json()["id"]

    email = f"gestor-{uuid.uuid4().hex[:10]}@facilpi.com.br"
    gestor = await client.post(
        f"/api/platform/instituicoes/{ilpi_id}/primeiro-gestor",
        headers=_headers(operador),
        json={"nome": "Gestor GATE1", "email": email},
    )
    assert gestor.status_code == 201, gestor.text
    temporaria = gestor.json()["senha_temporaria"]

    primeiro_login = await client.post(
        "/api/auth/token", json={"email": email, "password": temporaria}
    )
    assert primeiro_login.status_code == 200, primeiro_login.text
    troca = await client.put(
        "/api/auth/password",
        headers=_headers(primeiro_login.json()["access_token"]),
        json={
            "senha_atual": temporaria,
            "nova_senha": GESTOR_SENHA,
            "confirmar_senha": GESTOR_SENHA,
        },
    )
    assert troca.status_code == 200, troca.text

    if ativar:
        ativacao = await client.post(
            f"/api/platform/instituicoes/{ilpi_id}/ativar", headers=_headers(operador)
        )
        assert ativacao.status_code == 200, ativacao.text

    return ilpi_id, email


async def _login_gestor(client, email: str) -> httpx.Response:
    return await client.post("/api/auth/token", json={"email": email, "password": GESTOR_SENHA})


async def _token_gestor(client, email: str) -> str:
    resposta = await _login_gestor(client, email)
    assert resposta.status_code == 200, resposta.text
    return resposta.json()["access_token"]


async def _inativar(client, ilpi_id: str) -> None:
    operador = await _token_operador(client)
    resposta = await client.post(
        f"/api/platform/instituicoes/{ilpi_id}/inativar", headers=_headers(operador)
    )
    assert resposta.status_code == 200, resposta.text
    assert resposta.json()["situacao"] == "INATIVA"


# ------------------------------------------- comportamento preservado -----

def test_1_ilpi_ativa_segue_operando(gate1_db):
    async def cenario(client, session):
        ilpi_id, email = await _provisionar(client, ativar=True)
        token = await _token_gestor(client, email)

        resposta = await client.get(f"/api/instituicoes/{ilpi_id}", headers=_headers(token))
        assert resposta.status_code == 200, resposta.text
        assert resposta.json()["situacao"] == ILPI_ACTIVE

    _executa(gate1_db, cenario)


def test_2_rascunho_preserva_comportamento_atual(gate1_db):
    """GATE-2 continua aberto DE PROPOSITO.

    Se este teste passar a falhar, alguem trocou a denylist de INATIVA por uma
    allowlist de ATIVA e fechou o GATE-2 por acidente — o que derrubaria tambem
    a base de testes institucional, que provisiona ILPIs em rascunho.
    """
    async def cenario(client, session):
        ilpi_id, email = await _provisionar(client, ativar=False)
        token = await _token_gestor(client, email)

        resposta = await client.get(f"/api/instituicoes/{ilpi_id}", headers=_headers(token))
        assert resposta.status_code == 200, resposta.text
        assert resposta.json()["situacao"] == ILPI_DRAFT

    _executa(gate1_db, cenario)


# -------------------------------------------------- bloqueio da inativa ---

def test_3_token_emitido_antes_da_inativacao_para_de_valer(gate1_db):
    """O caso critico: a sessao ja estava aberta quando a ILPI foi inativada."""
    async def cenario(client, session):
        ilpi_id, email = await _provisionar(client, ativar=True)
        token = await _token_gestor(client, email)

        antes = await client.get(f"/api/instituicoes/{ilpi_id}", headers=_headers(token))
        assert antes.status_code == 200, antes.text

        await _inativar(client, ilpi_id)

        # Mesmo token, requisicao seguinte.
        depois = await client.get(f"/api/instituicoes/{ilpi_id}", headers=_headers(token))
        assert depois.status_code == 403, depois.text
        assert _codigo(depois) == ILPI_INATIVA

    _executa(gate1_db, cenario)


def test_4_selecao_de_contexto_institucional_e_negada(gate1_db):
    async def cenario(client, session):
        ilpi_id, email = await _provisionar(client, ativar=True)
        token = await _token_gestor(client, email)
        await _inativar(client, ilpi_id)

        resposta = await client.post(
            "/api/auth/contexto",
            headers=_headers(token),
            json={"scope": "ilpi", "ilpi_id": ilpi_id},
        )
        assert resposta.status_code == 403, resposta.text
        assert _codigo(resposta) == ILPI_INATIVA

    _executa(gate1_db, cenario)


def test_7_grafia_minuscula_bloqueia_igual(gate1_db):
    """O CHECK historico aceita 'INATIVA' e 'inativa' no mesmo banco."""
    async def cenario(client, session):
        ilpi_id, email = await _provisionar(client, ativar=True)
        token = await _token_gestor(client, email)

        ilpi = (
            await session.execute(select(m.Instituicao).where(m.Instituicao.id == ilpi_id))
        ).scalar_one()
        ilpi.situacao = "inativa"
        await session.commit()

        resposta = await client.get(f"/api/instituicoes/{ilpi_id}", headers=_headers(token))
        assert resposta.status_code == 403, resposta.text
        assert _codigo(resposta) == ILPI_INATIVA

    _executa(gate1_db, cenario)


# ------------------------------------------------- identidade preservada --

def test_5_login_continua_funcionando_sem_contexto(gate1_db):
    async def cenario(client, session):
        ilpi_id, email = await _provisionar(client, ativar=True)
        await _inativar(client, ilpi_id)

        login = await _login_gestor(client, email)
        assert login.status_code == 200, login.text

        claims = auth.decode_access_token(login.json()["access_token"])
        assert claims is not None
        # Identidade sim; autorizacao institucional nao.
        assert claims.get("sub")
        assert claims.get("scope") is None
        assert claims.get("ilpi_id") is None

    _executa(gate1_db, cenario)


def test_6_troca_de_senha_continua_possivel(gate1_db):
    async def cenario(client, session):
        ilpi_id, email = await _provisionar(client, ativar=True)
        await _inativar(client, ilpi_id)

        token = (await _login_gestor(client, email)).json()["access_token"]
        nova = "SenhaGestorNova789C"
        troca = await client.put(
            "/api/auth/password",
            headers=_headers(token),
            json={"senha_atual": GESTOR_SENHA, "nova_senha": nova, "confirmar_senha": nova},
        )
        assert troca.status_code == 200, troca.text

        relogin = await client.post("/api/auth/token", json={"email": email, "password": nova})
        assert relogin.status_code == 200, relogin.text

    _executa(gate1_db, cenario)


def test_5b_usuario_sem_vinculo_algum_continua_recebendo_403(gate1_db):
    """A degradacao do login vale SO para ILPI_INATIVA, nada alem disso."""
    async def cenario(client, session):
        email = f"avulso-{uuid.uuid4().hex[:10]}@facilpi.com.br"
        senha = "SenhaAvulsa123D"
        session.add(
            m.User(
                id=str(uuid.uuid4()),
                nome="Usuario Sem Vinculo",
                email=email,
                password_hash=auth.hash_password(senha),
                ativo=True,
                is_superuser=False,
                exige_troca_senha=False,
            )
        )
        await session.commit()

        login = await client.post("/api/auth/token", json={"email": email, "password": senha})
        assert login.status_code == 403, login.text

    _executa(gate1_db, cenario)


# ------------------------------------------------ PLATFORM-1A intocado ----

def test_8_operador_global_segue_usando_a_central(gate1_db):
    async def cenario(client, session):
        ilpi_id, _ = await _provisionar(client, ativar=True)
        await _inativar(client, ilpi_id)

        operador = await _token_operador(client)
        detalhe = await client.get(
            f"/api/platform/instituicoes/{ilpi_id}", headers=_headers(operador)
        )
        assert detalhe.status_code == 200, detalhe.text
        assert detalhe.json()["situacao"] == "INATIVA"

        lista = await client.get("/api/platform/instituicoes", headers=_headers(operador))
        assert lista.status_code == 200, lista.text
        assert ilpi_id in {item["id"] for item in lista.json()}

    _executa(gate1_db, cenario)
