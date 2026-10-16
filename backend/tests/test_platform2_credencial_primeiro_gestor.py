"""PLATFORM-2: regeneracao da credencial do primeiro gestor.

A senha temporaria e mostrada UMA vez. Sem esta rota, um dialogo fechado antes da
anotacao deixava a ILPI sem caminho de acesso pela aplicacao — e a saida seria
SQL, exatamente o que o PLATFORM-1A eliminou.

E regeneracao, nao recuperacao: a senha anterior deixa de valer. E nao e reset
generico: o alvo e derivado da ILPI do path, nunca enviado pelo cliente.

Nenhum teste toca storage/app.db.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import random
import subprocess
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

BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from src import main  # noqa: E402
from src.application import auth  # noqa: E402
from src.application.fase3a import ADMIN_EMAIL, ILPI_ADMIN_KEY  # noqa: E402
from src.infrastructure import database  # noqa: E402
from src.infrastructure import models as m  # noqa: E402
from src.scripts import bootstrap as bootstrap_script  # noqa: E402

BOOTSTRAP_TOKEN = "platform2-test-bootstrap-token"
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
def platform2_db(tmp_path_factory) -> pathlib.Path:
    caminho = tmp_path_factory.mktemp("platform2") / "platform2.db"
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


def _cnpj_valido() -> str:
    base = [random.randint(0, 9) for _ in range(12)]
    for pesos in ([5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2], [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]):
        soma = sum(d * p for d, p in zip(base, pesos))
        resto = soma % 11
        base.append(0 if resto < 2 else 11 - resto)
    return "".join(str(d) for d in base)


# ------------------------------------------------------ provisionamento ---

async def _token_operador(client: httpx.AsyncClient) -> str:
    login = await client.post(
        "/api/auth/token", json={"email": ADMIN_EMAIL, "password": OPERADOR_SENHA}
    )
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


async def _criar_ilpi(client, operador: str) -> str:
    criada = await client.post(
        "/api/platform/instituicoes",
        headers=_headers(operador),
        json={
            "razao_social": f"ILPI PLAT2 {uuid.uuid4().hex[:6]}",
            "capacidade": 10,
            "uf": "SP",
            "cnpj": _cnpj_valido(),
        },
    )
    assert criada.status_code == 201, criada.text
    return criada.json()["id"]


async def _provisionar(client, *, ativar: bool = False) -> tuple[str, str, str]:
    """Devolve (ilpi_id, email, senha_temporaria_original)."""
    operador = await _token_operador(client)
    ilpi_id = await _criar_ilpi(client, operador)
    email = f"gestor-{uuid.uuid4().hex[:10]}@facilpi.com.br"
    gestor = await client.post(
        f"/api/platform/instituicoes/{ilpi_id}/primeiro-gestor",
        headers=_headers(operador),
        json={"nome": "Gestor PLAT2", "email": email},
    )
    assert gestor.status_code == 201, gestor.text
    if ativar:
        ativacao = await client.post(
            f"/api/platform/instituicoes/{ilpi_id}/ativar", headers=_headers(operador)
        )
        assert ativacao.status_code == 200, ativacao.text
    return ilpi_id, email, gestor.json()["senha_temporaria"]


async def _regerar(client, ilpi_id: str) -> httpx.Response:
    operador = await _token_operador(client)
    return await client.post(
        f"/api/platform/instituicoes/{ilpi_id}/primeiro-gestor/credencial",
        headers=_headers(operador),
    )


# ------------------------------------------------- efeito da regeneracao --

def test_1_2_3_4_senha_nova_substitui_a_anterior(platform2_db):
    async def cenario(client, session):
        ilpi_id, email, antiga = await _provisionar(client)

        resposta = await _regerar(client, ilpi_id)
        assert resposta.status_code == 200, resposta.text
        nova = resposta.json()["senha_temporaria"]

        assert nova
        assert nova != antiga

        recusada = await client.post("/api/auth/token", json={"email": email, "password": antiga})
        assert recusada.status_code == 401, recusada.text

        aceita = await client.post("/api/auth/token", json={"email": email, "password": nova})
        assert aceita.status_code == 200, aceita.text

    _executa(platform2_db, cenario)


def test_5_exige_troca_de_senha_volta_a_valer(platform2_db):
    """O gestor ja pode ter concluido o primeiro acesso antes de perder a senha."""
    async def cenario(client, session):
        ilpi_id, email, antiga = await _provisionar(client)

        primeiro = await client.post("/api/auth/token", json={"email": email, "password": antiga})
        assert primeiro.status_code == 200, primeiro.text
        troca = await client.put(
            "/api/auth/password",
            headers=_headers(primeiro.json()["access_token"]),
            json={
                "senha_atual": antiga,
                "nova_senha": GESTOR_SENHA,
                "confirmar_senha": GESTOR_SENHA,
            },
        )
        assert troca.status_code == 200, troca.text

        resposta = await _regerar(client, ilpi_id)
        assert resposta.status_code == 200, resposta.text
        assert resposta.json()["exige_troca_senha"] is True

        login = await client.post(
            "/api/auth/token",
            json={"email": email, "password": resposta.json()["senha_temporaria"]},
        )
        assert login.status_code == 200, login.text
        assert login.json()["exige_troca_senha"] is True

        # A senha que o gestor tinha definido tambem deixa de valer.
        antiga_definitiva = await client.post(
            "/api/auth/token", json={"email": email, "password": GESTOR_SENHA}
        )
        assert antiga_definitiva.status_code == 401, antiga_definitiva.text

    _executa(platform2_db, cenario)


def test_6_refresh_tokens_anteriores_sao_revogados(platform2_db):
    async def cenario(client, session):
        ilpi_id, email, antiga = await _provisionar(client)
        login = await client.post("/api/auth/token", json={"email": email, "password": antiga})
        assert login.status_code == 200, login.text

        usuario = (
            await session.execute(select(m.User).where(m.User.email == email))
        ).scalar_one()
        ativos_antes = (
            await session.execute(
                select(m.RefreshToken).where(
                    m.RefreshToken.user_id == usuario.id,
                    m.RefreshToken.revoked_at.is_(None),
                )
            )
        ).scalars().all()
        assert ativos_antes, "o login deveria ter aberto uma familia de refresh"

        assert (await _regerar(client, ilpi_id)).status_code == 200

        ativos_depois = (
            await session.execute(
                select(m.RefreshToken).where(
                    m.RefreshToken.user_id == usuario.id,
                    m.RefreshToken.revoked_at.is_(None),
                )
            )
        ).scalars().all()
        assert ativos_depois == []

    _executa(platform2_db, cenario)


# --------------------------------------------- nao vazamento (7-8) --------

def test_7_8_plaintext_nao_vaza_para_auditoria_nem_para_leituras(platform2_db):
    async def cenario(client, session):
        ilpi_id, email, _ = await _provisionar(client)
        resposta = await _regerar(client, ilpi_id)
        assert resposta.status_code == 200, resposta.text
        nova = resposta.json()["senha_temporaria"]

        usuario = (
            await session.execute(select(m.User).where(m.User.email == email))
        ).scalar_one()

        registros = (
            await session.execute(
                select(m.Auditoria).where(m.Auditoria.registro_id == usuario.id)
            )
        ).scalars().all()
        eventos = {registro.acao for registro in registros}
        assert "ilpi.credencial_primeiro_gestor_regenerada" in eventos
        for registro in registros:
            texto = f"{registro.valores_anteriores} {registro.valores_posteriores}"
            assert nova not in texto
            assert usuario.password_hash not in texto

        # A senha tambem nao reaparece em nenhuma leitura posterior.
        operador = await _token_operador(client)
        detalhe = await client.get(
            f"/api/platform/instituicoes/{ilpi_id}", headers=_headers(operador)
        )
        assert detalhe.status_code == 200
        assert nova not in detalhe.text

        # Persistido no banco, so o hash.
        assert usuario.password_hash != nova

    _executa(platform2_db, cenario)


# ------------------------------------------------- alvo e guardas (9-11) --

def test_9_ilpi_sem_primeiro_gestor_recusa(platform2_db):
    async def cenario(client, session):
        operador = await _token_operador(client)
        ilpi_id = await _criar_ilpi(client, operador)

        resposta = await _regerar(client, ilpi_id)
        assert resposta.status_code == 409, resposta.text
        assert _codigo(resposta) == "PRIMEIRO_GESTOR_INEXISTENTE"

        # E nenhum usuario foi criado por tabela.
        usuarios = (
            await session.execute(
                select(m.UsuarioIlpiPerfil).where(m.UsuarioIlpiPerfil.ilpi_id == ilpi_id)
            )
        ).scalars().all()
        assert usuarios == []

    _executa(platform2_db, cenario)


def test_10_rota_nao_alcanca_outro_usuario_da_ilpi(platform2_db):
    """Nao e reset generico: com mais de um admin, a operacao recusa.

    A partir do momento em que a ILPI administra a propria equipe, redefinir a
    senha de um usuario institucional e capacidade institucional
    (`usuarios:redefinir_senha`, ILPI-only), nao da plataforma.
    """
    async def cenario(client, session):
        ilpi_id, email, _ = await _provisionar(client)

        gestor = (
            await session.execute(select(m.User).where(m.User.email == email))
        ).scalar_one()
        hash_gestor = gestor.password_hash
        perfil = (
            await session.execute(
                select(m.Perfil).where(
                    m.Perfil.ilpi_id == ilpi_id, m.Perfil.chave == ILPI_ADMIN_KEY
                )
            )
        ).scalar_one()

        outro_email = f"outro-{uuid.uuid4().hex[:8]}@facilpi.com.br"
        outro = m.User(
            id=str(uuid.uuid4()),
            nome="Segundo Admin",
            email=outro_email,
            password_hash=auth.hash_password("SenhaOutro123X"),
            ativo=True,
            is_superuser=False,
            exige_troca_senha=False,
        )
        session.add(outro)
        await session.flush()
        session.add(
            m.Funcionario(
                id=str(uuid.uuid4()),
                ilpi_id=ilpi_id,
                usuario_id=outro.id,
                nome="Segundo Admin",
                cargo="Administrador",
                situacao="ativo",
            )
        )
        session.add(
            m.UsuarioIlpiPerfil(
                id=str(uuid.uuid4()),
                usuario_id=outro.id,
                perfil_id=perfil.id,
                ilpi_id=ilpi_id,
                situacao="ativo",
                data_inicial=datetime.now(timezone.utc) - timedelta(minutes=1),
            )
        )
        await session.commit()

        resposta = await _regerar(client, ilpi_id)
        assert resposta.status_code == 409, resposta.text
        assert _codigo(resposta) == "PRIMEIRO_GESTOR_AMBIGUO"

        # Nenhuma das duas credenciais foi tocada.
        await session.refresh(gestor)
        await session.refresh(outro)
        assert gestor.password_hash == hash_gestor
        login_outro = await client.post(
            "/api/auth/token", json={"email": outro_email, "password": "SenhaOutro123X"}
        )
        assert login_outro.status_code in (200, 403), login_outro.text

    _executa(platform2_db, cenario)


def test_11_usuario_institucional_nao_alcanca_a_rota(platform2_db):
    async def cenario(client, session):
        ilpi_id, email, antiga = await _provisionar(client, ativar=True)

        primeiro = await client.post("/api/auth/token", json={"email": email, "password": antiga})
        assert primeiro.status_code == 200, primeiro.text
        troca = await client.put(
            "/api/auth/password",
            headers=_headers(primeiro.json()["access_token"]),
            json={
                "senha_atual": antiga,
                "nova_senha": GESTOR_SENHA,
                "confirmar_senha": GESTOR_SENHA,
            },
        )
        assert troca.status_code == 200, troca.text
        institucional = (
            await client.post("/api/auth/token", json={"email": email, "password": GESTOR_SENHA})
        ).json()["access_token"]

        resposta = await client.post(
            f"/api/platform/instituicoes/{ilpi_id}/primeiro-gestor/credencial",
            headers=_headers(institucional),
        )
        assert resposta.status_code == 403, resposta.text

    _executa(platform2_db, cenario)


# ------------------------------------------- situacao da ILPI (12-16) -----

def test_12_rascunho_permite(platform2_db):
    async def cenario(client, session):
        ilpi_id, _, _ = await _provisionar(client, ativar=False)
        resposta = await _regerar(client, ilpi_id)
        assert resposta.status_code == 200, resposta.text

    _executa(platform2_db, cenario)


def test_13_ativa_permite(platform2_db):
    async def cenario(client, session):
        ilpi_id, _, _ = await _provisionar(client, ativar=True)
        resposta = await _regerar(client, ilpi_id)
        assert resposta.status_code == 200, resposta.text

    _executa(platform2_db, cenario)


def test_14_15_inativa_bloqueia_e_gate1_segue_valendo(platform2_db):
    async def cenario(client, session):
        ilpi_id, email, antiga = await _provisionar(client, ativar=True)
        operador = await _token_operador(client)
        inativacao = await client.post(
            f"/api/platform/instituicoes/{ilpi_id}/inativar", headers=_headers(operador)
        )
        assert inativacao.status_code == 200, inativacao.text

        gestor_antes = (
            await session.execute(select(m.User).where(m.User.email == email))
        ).scalar_one()
        hash_antes = gestor_antes.password_hash

        resposta = await _regerar(client, ilpi_id)
        assert resposta.status_code == 409, resposta.text
        assert _codigo(resposta) == "ILPI_INATIVA"

        # Nada foi alterado na recusa.
        await session.refresh(gestor_antes)
        assert gestor_antes.password_hash == hash_antes
        # E a credencial original continua valendo como identidade (GATE-1: o que
        # se perde e o contexto institucional, nao a autenticacao).
        login = await client.post("/api/auth/token", json={"email": email, "password": antiga})
        assert login.status_code == 200, login.text

    _executa(platform2_db, cenario)


def test_16_suspensa_mantem_comportamento_atual(platform2_db):
    """SUSPENSA segue NAO AVALIADA.

    A guarda e denylist de INATIVA, entao nenhuma politica nova nasce aqui. Este
    teste registra o comportamento atual para que uma mudanca futura seja
    deliberada — nao o declara seguro.
    """
    async def cenario(client, session):
        ilpi_id, _, _ = await _provisionar(client, ativar=True)
        ilpi = (
            await session.execute(select(m.Instituicao).where(m.Instituicao.id == ilpi_id))
        ).scalar_one()
        ilpi.situacao = "SUSPENSA"
        await session.commit()

        resposta = await _regerar(client, ilpi_id)
        assert resposta.status_code == 200, resposta.text

    _executa(platform2_db, cenario)


# ----------------------------------------------------- fluxo completo -----

def test_17_regerar_login_troca_e_contexto(platform2_db):
    async def cenario(client, session):
        ilpi_id, email, _ = await _provisionar(client, ativar=True)

        nova = (await _regerar(client, ilpi_id)).json()["senha_temporaria"]

        login = await client.post("/api/auth/token", json={"email": email, "password": nova})
        assert login.status_code == 200, login.text
        assert login.json()["exige_troca_senha"] is True
        token_pre_troca = login.json()["access_token"]

        # Antes da troca, nada institucional abre.
        bloqueado = await client.get(
            f"/api/instituicoes/{ilpi_id}", headers=_headers(token_pre_troca)
        )
        assert bloqueado.status_code == 403, bloqueado.text

        definitiva = "SenhaDefinitiva789Z"
        troca = await client.put(
            "/api/auth/password",
            headers=_headers(token_pre_troca),
            json={"senha_atual": nova, "nova_senha": definitiva, "confirmar_senha": definitiva},
        )
        assert troca.status_code == 200, troca.text

        final = await client.post(
            "/api/auth/token", json={"email": email, "password": definitiva}
        )
        assert final.status_code == 200, final.text
        detalhe = await client.get(
            f"/api/instituicoes/{ilpi_id}", headers=_headers(final.json()["access_token"])
        )
        assert detalhe.status_code == 200, detalhe.text

    _executa(platform2_db, cenario)


# -------------------------------------------------------- bootstrap ------

def _roda_bootstrap(tmp_path: pathlib.Path, *extra: str) -> subprocess.CompletedProcess:
    banco = tmp_path / f"bootstrap-{uuid.uuid4().hex[:8]}.db"
    url = f"sqlite+aiosqlite:///{banco.resolve().as_posix()}"
    resultado = run_alembic(url, "upgrade", "head")
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr

    ambiente = dict(os.environ)
    ambiente["DATABASE_URL"] = url
    ambiente["JWT_SECRET"] = "x" * 64
    ambiente["BOOTSTRAP_TOKEN"] = BOOTSTRAP_TOKEN
    ambiente["BOOTSTRAP_TOKEN_INPUT"] = BOOTSTRAP_TOKEN
    return subprocess.run(
        [sys.executable, "-m", "src.scripts.bootstrap", *extra],
        cwd=str(BACKEND),
        env=ambiente,
        capture_output=True,
        text=True,
    )


def test_18_bootstrap_padrao_nao_imprime_senha(tmp_path):
    resultado = _roda_bootstrap(tmp_path)
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    assert "BOOTSTRAP_OK" in resultado.stdout
    assert "senha_temporaria=NAO_EXIBIDA" in resultado.stdout
    # O prefixo fixo de `_temporary_password` e a evidencia mais direta de que
    # nenhum plaintext escapou para stdout ou stderr.
    assert "Aa1!" not in resultado.stdout
    assert "Aa1!" not in resultado.stderr


def test_19_bootstrap_com_opt_in_exibe_senha(tmp_path):
    resultado = _roda_bootstrap(tmp_path, "--show-password")
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr
    assert "senha_temporaria=Aa1!" in resultado.stdout
    assert "dado sensivel" in resultado.stdout.lower()


def test_20_bootstrap_nao_cria_arquivo_de_senha(tmp_path):
    antes = set(tmp_path.iterdir())
    resultado = _roda_bootstrap(tmp_path)
    assert resultado.returncode == 0, resultado.stdout + resultado.stderr

    novos = set(tmp_path.iterdir()) - antes
    # Apenas o banco descartavel do proprio teste (e arquivos auxiliares do SQLite).
    assert all(caminho.name.startswith("bootstrap-") for caminho in novos), novos
    for caminho in BACKEND.glob("*senha*"):
        raise AssertionError(f"arquivo de senha criado: {caminho}")
