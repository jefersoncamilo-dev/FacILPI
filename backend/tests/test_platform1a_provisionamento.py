"""PLATFORM-1A: provisionamento repetivel de ILPIs pelo operador da plataforma.

O banco e migrado uma vez por modulo e a plataforma e inicializada uma vez —
`run_bootstrap` e one-shot por banco, entao repeti-lo a cada teste exigiria uma
migration por teste. Cada cenario faz login com a senha ja conhecida.

Nenhum teste toca storage/app.db.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
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
from src.application.bootstrap_state import FIRST_PASSWORD_CHANGED  # noqa: E402
from src.application.fase3a import ADMIN_EMAIL, ILPI_ACTIVE, ILPI_DRAFT  # noqa: E402
from src.infrastructure import database  # noqa: E402
from src.infrastructure import models as m  # noqa: E402
from src.scripts import bootstrap as bootstrap_script  # noqa: E402

BOOTSTRAP_TOKEN = "platform1a-test-bootstrap-token"
OPERADOR_SENHA = "SenhaOperador123A"
GESTOR_SENHA = "SenhaGestor456B"


# ------------------------------------------------------------- infra ------

def _engine_e_factory(caminho: pathlib.Path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{caminho.resolve().as_posix()}", poolclass=NullPool
    )
    return engine, async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


@pytest.fixture(scope="module")
def platform_db(tmp_path_factory) -> pathlib.Path:
    caminho = tmp_path_factory.mktemp("platform1a") / "platform1a.db"
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
            # Troca a senha inicial pela via oficial, levando o estado ate
            # FIRST_PASSWORD_CHANGED — que e onde ele deve PERMANECER durante todo
            # este modulo, provando a independencia do provisionamento.
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


def _override(factory):
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        async with factory() as session:
            yield session

    return override_get_db


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


async def _token_operador(client: httpx.AsyncClient) -> str:
    login = await client.post(
        "/api/auth/token", json={"email": ADMIN_EMAIL, "password": OPERADOR_SENHA}
    )
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


async def _criar_ilpi(client, token, *, nome: str, cnpj: str | None = None) -> dict:
    corpo = {"razao_social": nome, "capacidade": 10, "uf": "SP"}
    if cnpj:
        corpo["cnpj"] = cnpj
    resposta = await client.post(
        "/api/platform/instituicoes", headers=_headers(token), json=corpo
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


async def _criar_gestor(client, token, ilpi_id: str, *, email: str) -> dict:
    resposta = await client.post(
        f"/api/platform/instituicoes/{ilpi_id}/primeiro-gestor",
        headers=_headers(token),
        json={"nome": "Gestor Provisionado", "email": email},
    )
    assert resposta.status_code == 201, resposta.text
    return resposta.json()


def _email() -> str:
    return f"gestor-{uuid.uuid4().hex[:10]}@facilpi.com.br"


# ------------------------------------------- criacao repetivel (1-4) ------

def test_operador_cria_duas_ilpis_distintas(platform_db):
    async def cenario(client, session):
        token = await _token_operador(client)
        a = await _criar_ilpi(client, token, nome="ILPI Alpha")
        b = await _criar_ilpi(client, token, nome="ILPI Beta")

        assert a["id"] != b["id"]
        assert a["situacao"] == ILPI_DRAFT
        assert b["situacao"] == ILPI_DRAFT

    _executa(platform_db, cenario)


def test_criacao_nao_depende_nem_altera_bootstrap_state(platform_db):
    """A rota historica so criaria UMA ILPI; esta cria N sem mover o estado."""
    async def cenario(client, session):
        token = await _token_operador(client)
        antes = (await session.execute(select(m.BootstrapState.estado))).scalar_one()
        assert antes == FIRST_PASSWORD_CHANGED

        await _criar_ilpi(client, token, nome="ILPI Gamma")
        await _criar_ilpi(client, token, nome="ILPI Delta")

        depois = (
            await session.execute(select(m.BootstrapState.estado))
        ).scalar_one()
        assert depois == FIRST_PASSWORD_CHANGED

    _executa(platform_db, cenario)


def test_listagem_e_detalhe_da_plataforma(platform_db):
    async def cenario(client, session):
        token = await _token_operador(client)
        criada = await _criar_ilpi(client, token, nome="ILPI Listavel")

        lista = await client.get("/api/platform/instituicoes", headers=_headers(token))
        assert lista.status_code == 200, lista.text
        assert criada["id"] in {item["id"] for item in lista.json()}

        detalhe = await client.get(
            f"/api/platform/instituicoes/{criada['id']}", headers=_headers(token)
        )
        assert detalhe.status_code == 200
        assert detalhe.json()["razao_social"] == "ILPI Listavel"

        inexistente = await client.get(
            f"/api/platform/instituicoes/{uuid.uuid4()}", headers=_headers(token)
        )
        assert inexistente.status_code == 404

    _executa(platform_db, cenario)


# ------------------------------ operador nao entra no tenant (5-7) --------

def test_operador_nao_recebe_vinculo_com_as_ilpis_provisionadas(platform_db):
    """O contraste com `usar_usuario_atual_como_admin`, que criava esse vinculo."""
    async def cenario(client, session):
        token = await _token_operador(client)
        a = await _criar_ilpi(client, token, nome="ILPI Sem Vinculo A")
        b = await _criar_ilpi(client, token, nome="ILPI Sem Vinculo B")
        await _criar_gestor(client, token, a["id"], email=_email())
        await _criar_gestor(client, token, b["id"], email=_email())

        operador = (
            await session.execute(select(m.User).where(m.User.email == ADMIN_EMAIL))
        ).scalar_one()
        vinculos = (
            await session.execute(
                select(m.UsuarioIlpiPerfil).where(
                    m.UsuarioIlpiPerfil.usuario_id == operador.id
                )
            )
        ).scalars().all()

        # Continua existindo exatamente um vinculo: o global, sem tenant.
        assert [v.ilpi_id for v in vinculos] == [None]
        assert a["id"] not in {v.ilpi_id for v in vinculos}
        assert b["id"] not in {v.ilpi_id for v in vinculos}

        # E nenhum funcionario do operador foi criado nas ILPIs.
        funcionarios = (
            await session.execute(
                select(m.Funcionario).where(m.Funcionario.usuario_id == operador.id)
            )
        ).scalars().all()
        assert funcionarios == []

    _executa(platform_db, cenario)


def test_operador_segue_sem_contexto_institucional_ou_clinico(platform_db):
    async def cenario(client, session):
        token = await _token_operador(client)
        ilpi = await _criar_ilpi(client, token, nome="ILPI Sem Clinico")
        await _criar_gestor(client, token, ilpi["id"], email=_email())

        # Rota clinica institucional com token global: negada.
        clinico = await client.get("/api/residentes/", headers=_headers(token))
        assert clinico.status_code == 403

        # E nao consegue assumir contexto da ILPI que acabou de provisionar.
        contexto = await client.post(
            "/api/auth/contexto",
            headers=_headers(token),
            json={"scope": "ilpi", "ilpi_id": ilpi["id"]},
        )
        assert contexto.status_code == 403

    _executa(platform_db, cenario)


# ------------------------------------- primeiro gestor (8-13) -------------

def test_primeiro_gestor_recebe_ilpi_admin_apenas_na_propria_ilpi(platform_db):
    async def cenario(client, session):
        token = await _token_operador(client)
        a = await _criar_ilpi(client, token, nome="ILPI Escopo A")
        b = await _criar_ilpi(client, token, nome="ILPI Escopo B")
        email_a, email_b = _email(), _email()
        gestor_a = await _criar_gestor(client, token, a["id"], email=email_a)
        gestor_b = await _criar_gestor(client, token, b["id"], email=email_b)

        for gestor, ilpi_id in ((gestor_a, a["id"]), (gestor_b, b["id"])):
            vinculos = (
                await session.execute(
                    select(m.UsuarioIlpiPerfil, m.Perfil)
                    .join(m.Perfil, m.Perfil.id == m.UsuarioIlpiPerfil.perfil_id)
                    .where(m.UsuarioIlpiPerfil.usuario_id == gestor["id"])
                )
            ).all()
            assert len(vinculos) == 1
            vinculo, perfil = vinculos[0]
            assert vinculo.ilpi_id == ilpi_id
            assert perfil.chave == "ilpi_admin"
            assert perfil.ilpi_id == ilpi_id  # clone local, nunca o template

    _executa(platform_db, cenario)


def test_gestor_de_uma_ilpi_nao_administra_a_outra(platform_db):
    async def cenario(client, session):
        token = await _token_operador(client)
        a = await _criar_ilpi(client, token, nome="ILPI Isolada A")
        b = await _criar_ilpi(client, token, nome="ILPI Isolada B")
        email_a = _email()
        gestor_a = await _criar_gestor(client, token, a["id"], email=email_a)
        await _criar_gestor(client, token, b["id"], email=_email())

        gestor_token = await _login_e_troca(client, email_a, gestor_a["senha_temporaria"])

        # Nao alcanca a porta da plataforma: escopo institucional, nao global.
        plataforma = await client.get(
            "/api/platform/instituicoes", headers=_headers(gestor_token)
        )
        assert plataforma.status_code == 403

        # E nao enxerga a ILPI vizinha: nao-divulgacao por 404.
        vizinha = await client.get(
            f"/api/instituicoes/{b['id']}", headers=_headers(gestor_token)
        )
        assert vizinha.status_code == 404

    _executa(platform_db, cenario)


def test_credencial_temporaria_volta_uma_vez_e_exige_troca(platform_db):
    async def cenario(client, session):
        token = await _token_operador(client)
        ilpi = await _criar_ilpi(client, token, nome="ILPI Credencial")
        email = _email()
        gestor = await _criar_gestor(client, token, ilpi["id"], email=email)

        senha = gestor["senha_temporaria"]
        assert senha
        assert gestor["exige_troca_senha"] is True

        usuario = (
            await session.execute(select(m.User).where(m.User.id == gestor["id"]))
        ).scalar_one()
        assert usuario.password_hash != senha  # hash, nunca plaintext
        assert usuario.exige_troca_senha is True

        # A senha autentica de fato.
        login = await client.post(
            "/api/auth/token", json={"email": email, "password": senha}
        )
        assert login.status_code == 200, login.text
        assert login.json()["exige_troca_senha"] is True

    _executa(platform_db, cenario)


def test_senha_temporaria_nunca_aparece_na_auditoria(platform_db):
    async def cenario(client, session):
        token = await _token_operador(client)
        ilpi = await _criar_ilpi(client, token, nome="ILPI Auditoria")
        gestor = await _criar_gestor(client, token, ilpi["id"], email=_email())
        senha = gestor["senha_temporaria"]

        registros = (
            await session.execute(
                select(m.Auditoria).where(m.Auditoria.ilpi_id == ilpi["id"])
            )
        ).scalars().all()
        assert registros, "o provisionamento precisa deixar rastro"

        texto = "\n".join(
            parte
            for registro in registros
            for parte in (
                registro.valores_anteriores or "",
                registro.valores_posteriores or "",
            )
        )
        assert senha not in texto
        assert "password_hash" not in texto

        acoes = {registro.acao for registro in registros}
        assert "ilpi.primeiro_gestor_criado" in acoes

    _executa(platform_db, cenario)


def test_segundo_primeiro_gestor_e_recusado(platform_db):
    """"Primeiro" e literal: repetir criaria um segundo dono em silencio."""
    async def cenario(client, session):
        token = await _token_operador(client)
        ilpi = await _criar_ilpi(client, token, nome="ILPI Gestor Unico")
        await _criar_gestor(client, token, ilpi["id"], email=_email())

        repetido = await client.post(
            f"/api/platform/instituicoes/{ilpi['id']}/primeiro-gestor",
            headers=_headers(token),
            json={"nome": "Outro Gestor", "email": _email()},
        )
        assert repetido.status_code == 409

    _executa(platform_db, cenario)


# ------------------------------------------------ ativacao (14-16) --------

def test_ativacao_recusa_dados_incompletos_e_ausencia_de_gestor(platform_db):
    async def cenario(client, session):
        token = await _token_operador(client)

        sem_cnpj = await _criar_ilpi(client, token, nome="ILPI Sem CNPJ")
        await _criar_gestor(client, token, sem_cnpj["id"], email=_email())
        resposta = await client.post(
            f"/api/platform/instituicoes/{sem_cnpj['id']}/ativar", headers=_headers(token)
        )
        assert resposta.status_code == 422
        assert resposta.json()["detail"]["code"] == "CNPJ_REQUIRED"

        sem_gestor = await _criar_ilpi(
            client, token, nome="ILPI Sem Gestor", cnpj="11222333000181"
        )
        resposta = await client.post(
            f"/api/platform/instituicoes/{sem_gestor['id']}/ativar", headers=_headers(token)
        )
        assert resposta.status_code == 422
        assert resposta.json()["detail"]["code"] == "ONBOARDING_PENDENTE"

    _executa(platform_db, cenario)


def test_ativacao_e_inativacao_com_precondicoes_satisfeitas(platform_db):
    async def cenario(client, session):
        token = await _token_operador(client)
        ilpi = await _criar_ilpi(client, token, nome="ILPI Completa", cnpj="11444777000161")
        await _criar_gestor(client, token, ilpi["id"], email=_email())

        ativada = await client.post(
            f"/api/platform/instituicoes/{ilpi['id']}/ativar", headers=_headers(token)
        )
        assert ativada.status_code == 200, ativada.text
        assert ativada.json()["situacao"] == ILPI_ACTIVE

        inativada = await client.post(
            f"/api/platform/instituicoes/{ilpi['id']}/inativar", headers=_headers(token)
        )
        assert inativada.status_code == 200, inativada.text
        assert inativada.json()["situacao"] == "INATIVA"

    _executa(platform_db, cenario)


def test_atualizacao_nao_muda_situacao_pelo_payload(platform_db):
    async def cenario(client, session):
        token = await _token_operador(client)
        ilpi = await _criar_ilpi(client, token, nome="ILPI Update")

        resposta = await client.put(
            f"/api/platform/instituicoes/{ilpi['id']}",
            headers=_headers(token),
            json={"nome_fantasia": "Casa Serena", "situacao": ILPI_ACTIVE},
        )
        assert resposta.status_code == 200, resposta.text
        assert resposta.json()["nome_fantasia"] == "Casa Serena"
        assert resposta.json()["situacao"] == ILPI_DRAFT

    _executa(platform_db, cenario)


# ----------------------- _assign_profile_to_user: dois caminhos (17-18) ---

async def _login_e_troca(client: httpx.AsyncClient, email: str, senha_temporaria: str) -> str:
    """Conclui o primeiro acesso do gestor e devolve token com contexto da ILPI.

    Enquanto `exige_troca_senha` esta de pe, o login nao resolve contexto
    institucional — por isso e preciso trocar a senha e autenticar de novo para
    obter um token de escopo ILPI.
    """
    primeiro = await client.post(
        "/api/auth/token", json={"email": email, "password": senha_temporaria}
    )
    assert primeiro.status_code == 200, primeiro.text
    assert primeiro.json()["exige_troca_senha"] is True

    troca = await client.put(
        "/api/auth/password",
        headers=_headers(primeiro.json()["access_token"]),
        json={
            "senha_atual": senha_temporaria,
            "nova_senha": GESTOR_SENHA,
            "confirmar_senha": GESTOR_SENHA,
        },
    )
    assert troca.status_code == 200, troca.text

    segundo = await client.post(
        "/api/auth/token", json={"email": email, "password": GESTOR_SENHA}
    )
    assert segundo.status_code == 200, segundo.text
    assert segundo.json()["exige_troca_senha"] is False
    return segundo.json()["access_token"]


def test_assign_profile_nos_dois_caminhos(platform_db):
    """Plataforma (ilpi_id do path) e institucional (context.ilpi_id) no mesmo teste."""
    async def cenario(client, session):
        token = await _token_operador(client)
        ilpi = await _criar_ilpi(client, token, nome="ILPI Dois Caminhos")
        email = _email()

        # Caminho PLATAFORMA: o vinculo do gestor nasce com ilpi_id do path.
        gestor = await _criar_gestor(client, token, ilpi["id"], email=email)
        vinculo = (
            await session.execute(
                select(m.UsuarioIlpiPerfil).where(
                    m.UsuarioIlpiPerfil.usuario_id == gestor["id"]
                )
            )
        ).scalar_one()
        assert vinculo.ilpi_id == ilpi["id"]

        # Caminho INSTITUCIONAL: o gestor troca a senha, assume contexto da ILPI e
        # cria outro usuario — ali o tenant vem de context.ilpi_id.
        gestor_token = await _login_e_troca(client, email, gestor["senha_temporaria"])
        perfil = (
            await session.execute(
                select(m.Perfil).where(
                    m.Perfil.chave == "ilpi_admin", m.Perfil.ilpi_id == ilpi["id"]
                )
            )
        ).scalar_one()
        novo = await client.post(
            "/api/usuarios/",
            headers=_headers(gestor_token),
            json={"nome": "Usuario Institucional", "email": _email(), "perfil_id": perfil.id},
        )
        assert novo.status_code == 201, novo.text
        vinculo_novo = (
            await session.execute(
                select(m.UsuarioIlpiPerfil).where(
                    m.UsuarioIlpiPerfil.usuario_id == novo.json()["id"]
                )
            )
        ).scalar_one()
        assert vinculo_novo.ilpi_id == ilpi["id"]

    _executa(platform_db, cenario)
