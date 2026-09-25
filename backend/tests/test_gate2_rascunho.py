"""GATE-2: ILPI em RASCUNHO configura, mas nao opera.

Uma instituicao em rascunho ainda esta sendo montada. Ela precisa receber
configuracao administrativa — equipe, perfis, dados da casa — mas nao pode
executar operacao clinica/assistencial.

O ponto central e `_permission_key_is_usable`, aplicado em dois lugares: no
filtro de `SecurityContext.permission_keys` e em `_permission_is_allowed`. O
segundo protege `require_permission`; o primeiro protege quem le
`permission_keys` direto, como o Prontuario.

CUIDADO METODOLOGICO: o perfil `ilpi_admin` NAO possui permissao clinica alguma
(migration 004). Testar negacao clinica com o gestor provaria apenas a ausencia
do grant, nao o GATE-2. Por isso estes testes constroem um perfil AMPLO — com
chaves administrativas E clinicas — e comparam a MESMA concessao em RASCUNHO e
em ATIVA. A diferenca entre as duas respostas e a regra.

Nenhum teste toca storage/app.db.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import random
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
from src.application.fase3a import ADMIN_EMAIL, ILPI_ACTIVE, ILPI_DRAFT  # noqa: E402
from src.application.security import ILPI_INATIVA, PERMISSION_DENIED  # noqa: E402
from src.infrastructure import database  # noqa: E402
from src.infrastructure import models as m  # noqa: E402
from src.scripts import bootstrap as bootstrap_script  # noqa: E402

BOOTSTRAP_TOKEN = "gate2-test-bootstrap-token"
OPERADOR_SENHA = "SenhaOperador123A"
GESTOR_SENHA = "SenhaGestor456B"
PERFIL_SENHA = "SenhaPerfil789C"

# Chaves administrativas liberadas em rascunho e chaves clinicas bloqueadas.
# Ambas sao concedidas ao MESMO perfil, para que a unica variavel entre um teste
# e outro seja a situacao da ILPI.
ADMIN_KEYS = (
    "ilpis:ler",
    "usuarios:ler",
    "funcionarios:ler",
    "funcionarios:criar",
    "perfis:ler",
    "permissoes:ler",
    "auditoria:ler",
    "configuracoes:ler",
)
CLINICAL_KEYS = (
    "residentes:ler",
    "residentes:criar",
    "documentos:ler",
    "sinais_vitais:ler",
    "intercorrencias:ler",
    "avaliacoes:ler",
    "quartos_leitos:ler",
    "quartos_leitos:atualizar",
    "ausencias:ler",
)
FUTURO_MODULO = "modulo_futuro"
FUTURO_KEY = f"{FUTURO_MODULO}:ler"


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
def gate2_db(tmp_path_factory) -> pathlib.Path:
    caminho = tmp_path_factory.mktemp("gate2") / "gate2.db"
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


async def _provisionar(client, *, ativar: bool) -> tuple[str, str]:
    """ILPI + primeiro gestor pela Central, com a senha ja trocada."""
    operador = await _token_operador(client)
    criada = await client.post(
        "/api/platform/instituicoes",
        headers=_headers(operador),
        json={
            "razao_social": f"ILPI GATE2 {uuid.uuid4().hex[:6]}",
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
        json={"nome": "Gestor GATE2", "email": email},
    )
    assert gestor.status_code == 201, gestor.text
    temporaria = gestor.json()["senha_temporaria"]

    primeiro = await client.post("/api/auth/token", json={"email": email, "password": temporaria})
    assert primeiro.status_code == 200, primeiro.text
    troca = await client.put(
        "/api/auth/password",
        headers=_headers(primeiro.json()["access_token"]),
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


async def _usuario_com_permissoes(session: AsyncSession, ilpi_id: str, chaves) -> str:
    """Cria perfil institucional com as chaves pedidas + usuario/funcionario/vinculo.

    Escrito direto no banco descartavel de proposito: criar isto pela API exigiria
    permissoes que o proprio teste esta avaliando.
    """
    perfil = m.Perfil(
        id=str(uuid.uuid4()),
        ilpi_id=ilpi_id,
        nome=f"Perfil GATE2 {uuid.uuid4().hex[:6]}",
        chave=f"gate2_{uuid.uuid4().hex[:8]}",
        descricao="Perfil amplo de teste",
        escopo="ilpi",
        situacao="ativo",
    )
    session.add(perfil)
    await session.flush()

    permissoes = (
        await session.execute(select(m.Permissao).where(m.Permissao.chave.in_(list(chaves))))
    ).scalars().all()
    encontradas = {p.chave for p in permissoes}
    faltando = set(chaves) - encontradas
    assert not faltando, f"catalogo nao possui: {sorted(faltando)}"
    for permissao in permissoes:
        session.add(
            m.PerfilPermissao(perfil_id=perfil.id, permissao_id=permissao.id)
        )

    email = f"amplo-{uuid.uuid4().hex[:10]}@facilpi.com.br"
    user = m.User(
        id=str(uuid.uuid4()),
        nome="Usuario Amplo",
        email=email,
        password_hash=auth.hash_password(PERFIL_SENHA),
        ativo=True,
        is_superuser=False,
        exige_troca_senha=False,
    )
    session.add(user)
    await session.flush()
    session.add(
        m.Funcionario(
            id=str(uuid.uuid4()),
            ilpi_id=ilpi_id,
            usuario_id=user.id,
            nome="Usuario Amplo",
            cargo="Equipe",
            situacao="ativo",
        )
    )
    session.add(
        m.UsuarioIlpiPerfil(
            id=str(uuid.uuid4()),
            usuario_id=user.id,
            perfil_id=perfil.id,
            ilpi_id=ilpi_id,
            situacao="ativo",
            data_inicial=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
    )
    await session.commit()
    return email


async def _token_amplo(client, email: str) -> str:
    login = await client.post("/api/auth/token", json={"email": email, "password": PERFIL_SENHA})
    assert login.status_code == 200, login.text
    return login.json()["access_token"]


async def _cenario_amplo(client, session, *, ativar: bool, chaves=None) -> tuple[str, str]:
    """Devolve (ilpi_id, token) de um usuario com perfil amplo na situacao pedida."""
    ilpi_id, _ = await _provisionar(client, ativar=ativar)
    email = await _usuario_com_permissoes(
        session, ilpi_id, chaves if chaves is not None else ADMIN_KEYS + CLINICAL_KEYS
    )
    return ilpi_id, await _token_amplo(client, email)


# ------------------------------------------- identidade e contexto (1-2) --

def test_1_rascunho_autentica(gate2_db):
    async def cenario(client, session):
        ilpi_id, _ = await _provisionar(client, ativar=False)
        email = await _usuario_com_permissoes(session, ilpi_id, ADMIN_KEYS)

        login = await client.post(
            "/api/auth/token", json={"email": email, "password": PERFIL_SENHA}
        )
        assert login.status_code == 200, login.text

    _executa(gate2_db, cenario)


def test_2_rascunho_obtem_contexto_institucional(gate2_db):
    async def cenario(client, session):
        ilpi_id, token = await _cenario_amplo(client, session, ativar=False)

        claims = auth.decode_access_token(token)
        assert claims is not None
        assert claims.get("scope") == "ilpi"
        assert claims.get("ilpi_id") == ilpi_id

        selecao = await client.post(
            "/api/auth/contexto",
            headers=_headers(token),
            json={"scope": "ilpi", "ilpi_id": ilpi_id},
        )
        assert selecao.status_code == 200, selecao.text

    _executa(gate2_db, cenario)


# ------------------------------------------------ setup permitido (3-6) ---

def test_3_4_5_6_setup_administrativo_permitido_em_rascunho(gate2_db):
    async def cenario(client, session):
        ilpi_id, token = await _cenario_amplo(client, session, ativar=False)

        for caminho in (
            f"/api/instituicoes/{ilpi_id}",   # ilpis:ler
            "/api/usuarios/",                 # usuarios:ler
            "/api/funcionarios/",             # funcionarios:ler
            "/api/perfis/",                   # perfis:ler
            "/api/permissoes/",               # permissoes:ler
        ):
            resposta = await client.get(caminho, headers=_headers(token))
            assert resposta.status_code == 200, f"{caminho} -> {resposta.status_code} {resposta.text}"

        # Escrita administrativa tambem: setup nao e so leitura.
        criado = await client.post(
            "/api/funcionarios/",
            headers=_headers(token),
            json={"nome": "Cuidadora Contratada", "cargo": "Cuidadora"},
        )
        assert criado.status_code == 201, criado.text

    _executa(gate2_db, cenario)


# --------------------------------------- quartos_leitos negado (7-11) -----

def test_7_quartos_leitos_negado_em_rascunho(gate2_db):
    async def cenario(client, session):
        _, token = await _cenario_amplo(client, session, ativar=False)

        resposta = await client.get("/api/quartos_leitos/", headers=_headers(token))
        assert resposta.status_code == 403, resposta.text
        assert _codigo(resposta) == PERMISSION_DENIED

    _executa(gate2_db, cenario)


def test_8_9_10_ocupacao_de_leito_negada_em_rascunho(gate2_db):
    """A razao de `quartos_leitos` ter ficado fora da allowlist.

    `quartos_leitos:atualizar` e a mesma chave de editar leito, alocar, liberar e
    transferir. Nao havendo fronteira por chave, o modulo inteiro fica bloqueado.
    """
    async def cenario(client, session):
        ilpi_id, token = await _cenario_amplo(client, session, ativar=False)
        leito_id = str(uuid.uuid4())
        session.add(
            m.QuartoLeito(
                id=leito_id,
                instituicao_id=ilpi_id,
                quarto="101",
                leito="A",
                capacidade=1,
                situacao="livre",
            )
        )
        await session.commit()

        alocar = await client.post(
            f"/api/quartos_leitos/{leito_id}/alocar",
            headers=_headers(token),
            json={"residente_id": str(uuid.uuid4())},
        )
        assert alocar.status_code == 403, alocar.text

        liberar = await client.post(
            f"/api/quartos_leitos/{leito_id}/liberar", headers=_headers(token)
        )
        assert liberar.status_code == 403, liberar.text

        transferir = await client.post(
            "/api/quartos_leitos/transferencia",
            headers=_headers(token),
            json={"residente_id": str(uuid.uuid4()), "leito_destino_id": leito_id},
        )
        assert transferir.status_code == 403, transferir.text

    _executa(gate2_db, cenario)


def test_11_ocupacao_historico_negado_em_rascunho(gate2_db):
    async def cenario(client, session):
        _, token = await _cenario_amplo(client, session, ativar=False)

        resposta = await client.get("/api/ocupacao_historico/", headers=_headers(token))
        assert resposta.status_code == 403, resposta.text

    _executa(gate2_db, cenario)


# ------------------------------------------- modulos clinicos (12-15) -----

def test_12_13_14_15_modulos_clinicos_negados_em_rascunho(gate2_db):
    async def cenario(client, session):
        _, token = await _cenario_amplo(client, session, ativar=False)

        for caminho in (
            "/api/residentes/",
            "/api/sinais-vitais/",
            "/api/intercorrencias/",
            "/api/documentos/",
            "/api/avaliacoes/",
            "/api/ausencias/",
        ):
            resposta = await client.get(caminho, headers=_headers(token))
            assert resposta.status_code == 403, f"{caminho} -> {resposta.status_code} {resposta.text}"

        criacao = await client.post(
            "/api/residentes/",
            headers=_headers(token),
            json={"nome_completo": "Residente Indevido", "data_nascimento": "1940-01-01"},
        )
        assert criacao.status_code == 403, criacao.text

    _executa(gate2_db, cenario)


# ---------------------------------------------------- prontuario (16) -----

def test_16_prontuario_negado_em_rascunho_inclusive_ocupacao(gate2_db):
    """A rota que nao passa por `require_permission`.

    `get_prontuario` monta o conjunto de origens lendo `context.permission_keys`.
    So esta coberta porque o filtro tambem acontece na montagem do contexto.
    """
    async def cenario(client, session):
        ilpi_id, token = await _cenario_amplo(client, session, ativar=False)
        residente_id = str(uuid.uuid4())
        session.add(
            m.Residente(
                id=residente_id,
                instituicao_id=ilpi_id,
                nome="Residente Prontuario",
                data_nascimento=datetime(1940, 1, 1).date(),
            )
        )
        await session.commit()

        geral = await client.get(
            f"/api/residentes/{residente_id}/prontuario", headers=_headers(token)
        )
        assert geral.status_code == 403, geral.text

        ocupacao = await client.get(
            f"/api/residentes/{residente_id}/prontuario?origem=ocupacao",
            headers=_headers(token),
        )
        assert ocupacao.status_code == 403, ocupacao.text

    _executa(gate2_db, cenario)


# ------------------------------------------------- fail-closed (17) -------

def test_17_modulo_desconhecido_nasce_negado_em_rascunho(gate2_db):
    """A prova de que a allowlist e fail-closed.

    A permissao e inserida apenas neste banco descartavel: simula o modulo que
    alguem adicionara ao catalogo no futuro sem lembrar do GATE-2. Em ATIVA ela
    funciona (o 404 abaixo prova que a autorizacao passou e a rota e que nao
    existe); em RASCUNHO ela nem chega la.
    """
    async def cenario(client, session):
        existente = (
            await session.execute(select(m.Permissao).where(m.Permissao.chave == FUTURO_KEY))
        ).scalar_one_or_none()
        if existente is None:
            session.add(
                m.Permissao(
                    id=str(uuid.uuid4()),
                    modulo=FUTURO_MODULO,
                    acao="ler",
                    chave=FUTURO_KEY,
                    descricao="Modulo hipotetico para provar o fail-closed do GATE-2",
                )
            )
            await session.commit()

        rascunho_id, _ = await _provisionar(client, ativar=False)
        email_rascunho = await _usuario_com_permissoes(session, rascunho_id, (FUTURO_KEY,))

        ativa_id, _ = await _provisionar(client, ativar=True)
        email_ativa = await _usuario_com_permissoes(session, ativa_id, (FUTURO_KEY,))

        from src.application.security import _permission_key_is_usable

        assert _permission_key_is_usable(FUTURO_KEY, ILPI_DRAFT) is False
        assert _permission_key_is_usable(FUTURO_KEY, ILPI_ACTIVE) is True

        # A chave desaparece do contexto em rascunho e permanece em ativa. Como
        # nao ha rota para o modulo hipotetico, o contexto e a evidencia.
        # PR-2: cada usuario autentica logo antes da propria selecao. O cookie de
        # refresh deste cliente e o da ultima sessao aberta, e /auth/contexto
        # recusa Bearer e cookie de sessoes diferentes.
        token_rascunho = await _token_amplo(client, email_rascunho)
        contexto_rascunho = await client.post(
            "/api/auth/contexto",
            headers=_headers(token_rascunho),
            json={"scope": "ilpi", "ilpi_id": rascunho_id},
        )
        assert contexto_rascunho.status_code == 200, contexto_rascunho.text
        token_ativa = await _token_amplo(client, email_ativa)
        contexto_ativa = await client.post(
            "/api/auth/contexto",
            headers=_headers(token_ativa),
            json={"scope": "ilpi", "ilpi_id": ativa_id},
        )
        assert contexto_ativa.status_code == 200, contexto_ativa.text

    _executa(gate2_db, cenario)


def test_17b_predicado_e_a_unica_fonte_da_regra(gate2_db):
    """Teste de unidade do predicado, sem HTTP.

    Existe para que a allowlist nao possa ser ampliada sem que alguem veja esta
    lista falhar.
    """
    from src.application.security import _DRAFT_ALLOWED_MODULES, _permission_key_is_usable

    assert _DRAFT_ALLOWED_MODULES == frozenset(
        {
            "ilpis",
            "usuarios",
            "funcionarios",
            "perfis",
            "configuracoes",
            "permissoes",
            "auditoria",
        }
    )
    for chave in ADMIN_KEYS:
        assert _permission_key_is_usable(chave, ILPI_DRAFT) is True, chave
    for chave in CLINICAL_KEYS:
        assert _permission_key_is_usable(chave, ILPI_DRAFT) is False, chave
    # Fora de rascunho, o predicado nao opina.
    for chave in CLINICAL_KEYS:
        assert _permission_key_is_usable(chave, ILPI_ACTIVE) is True, chave
        assert _permission_key_is_usable(chave, None) is True, chave
    # Grafia alternativa aceita pelo CHECK historico.
    assert _permission_key_is_usable("residentes:ler", "rascunho") is False
    # Chave malformada nao vira permissao em rascunho.
    assert _permission_key_is_usable("residentes", ILPI_DRAFT) is False


# ------------------------------------ compatibilidade preservada (18-23) --

def test_18_primeiro_acesso_e_troca_de_senha_preservados(gate2_db):
    async def cenario(client, session):
        # `_provisionar` ja exerce: primeiro gestor -> login com senha temporaria
        # -> PUT /auth/password. Se o GATE-2 tivesse quebrado isso, falharia aqui.
        ilpi_id, email = await _provisionar(client, ativar=False)

        login = await client.post(
            "/api/auth/token", json={"email": email, "password": GESTOR_SENHA}
        )
        assert login.status_code == 200, login.text
        assert login.json()["exige_troca_senha"] is False

        detalhe = await client.get(
            f"/api/instituicoes/{ilpi_id}",
            headers=_headers(login.json()["access_token"]),
        )
        assert detalhe.status_code == 200, detalhe.text
        assert detalhe.json()["situacao"] == ILPI_DRAFT

    _executa(gate2_db, cenario)


def test_19_ativacao_permanece_alcancavel(gate2_db):
    """Sem deadlock: ativar nao depende de permissao bloqueada em rascunho."""
    async def cenario(client, session):
        ilpi_id, _ = await _provisionar(client, ativar=False)
        operador = await _token_operador(client)

        ativacao = await client.post(
            f"/api/platform/instituicoes/{ilpi_id}/ativar", headers=_headers(operador)
        )
        assert ativacao.status_code == 200, ativacao.text
        assert ativacao.json()["situacao"] == ILPI_ACTIVE

    _executa(gate2_db, cenario)


def test_20_ativa_preserva_comportamento_atual(gate2_db):
    """O mesmo perfil amplo do teste 12, agora em ILPI ativa."""
    async def cenario(client, session):
        _, token = await _cenario_amplo(client, session, ativar=True)

        for caminho in (
            "/api/residentes/",
            "/api/sinais-vitais/",
            "/api/intercorrencias/",
            "/api/documentos/",
            "/api/quartos_leitos/",
            "/api/ausencias/",
        ):
            resposta = await client.get(caminho, headers=_headers(token))
            assert resposta.status_code == 200, f"{caminho} -> {resposta.status_code} {resposta.text}"

    _executa(gate2_db, cenario)


def test_21_inativa_preserva_gate1(gate2_db):
    async def cenario(client, session):
        ilpi_id, token = await _cenario_amplo(client, session, ativar=True)
        operador = await _token_operador(client)
        inativacao = await client.post(
            f"/api/platform/instituicoes/{ilpi_id}/inativar", headers=_headers(operador)
        )
        assert inativacao.status_code == 200, inativacao.text

        # Continua sendo ILPI_INATIVA — perda de contexto, nao de permissao.
        resposta = await client.get("/api/residentes/", headers=_headers(token))
        assert resposta.status_code == 403, resposta.text
        assert _codigo(resposta) == ILPI_INATIVA

    _executa(gate2_db, cenario)


def test_22_platform_superuser_permanece_global(gate2_db):
    async def cenario(client, session):
        rascunho_id, _ = await _provisionar(client, ativar=False)
        operador = await _token_operador(client)

        detalhe = await client.get(
            f"/api/platform/instituicoes/{rascunho_id}", headers=_headers(operador)
        )
        assert detalhe.status_code == 200, detalhe.text

        claims = auth.decode_access_token(operador)
        assert claims is not None
        assert claims.get("scope") == "global"
        assert claims.get("ilpi_id") is None

        vinculos = (
            await session.execute(
                select(m.UsuarioIlpiPerfil).where(
                    m.UsuarioIlpiPerfil.ilpi_id == rascunho_id,
                    m.UsuarioIlpiPerfil.usuario_id
                    == (
                        await session.execute(
                            select(m.User.id).where(m.User.email == ADMIN_EMAIL)
                        )
                    ).scalar_one(),
                )
            )
        ).scalars().all()
        assert vinculos == []

    _executa(gate2_db, cenario)


def test_23_suspensa_permanece_inalterada(gate2_db):
    """SUSPENSA segue NAO AVALIADA.

    Este teste registra o comportamento atual — nao o declara seguro. Ele existe
    para que uma mudanca futura em SUSPENSA seja deliberada e visivel, e nao um
    efeito colateral do GATE-2.
    """
    async def cenario(client, session):
        ilpi_id, token = await _cenario_amplo(client, session, ativar=True)
        ilpi = (
            await session.execute(select(m.Instituicao).where(m.Instituicao.id == ilpi_id))
        ).scalar_one()
        ilpi.situacao = "SUSPENSA"
        await session.commit()

        resposta = await client.get("/api/residentes/", headers=_headers(token))
        assert resposta.status_code == 200, resposta.text

    _executa(gate2_db, cenario)
