"""SAFE2-C1: contrato de ambiente, cookie, CORS e docs.

Funcoes puras com ambiente injetado: nao sobem a aplicacao, nao abrem conexao e
nao criam subprocesso. As duas unicas excecoes montam um FastAPI descartavel
para provar que as ROTAS de documentacao somem — o que uma assercao sobre
kwargs sozinha nao demonstraria.
"""

from __future__ import annotations

import asyncio
import pathlib
import sys

import httpx
import pytest
from fastapi import FastAPI

BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from src.application.runtime import (  # noqa: E402
    CORS_ORIGENS_LOCAIS,
    DEVELOPMENT,
    ENVIRONMENTS,
    PILOT,
    PRODUCTION,
    TEST,
    InsecureCorsError,
    InvalidEnvironmentError,
    cookie_secure_for,
    docs_enabled_for,
    docs_urls_for,
    resolve_cors_origins,
    resolve_environment,
)

ORIGEM_REAL = "https://ilpi.exemplo.com.br"
ENDURECIDOS = [PILOT, PRODUCTION]


# ------------------------------------------------- contrato de ambiente ----

@pytest.mark.parametrize("ambiente", ENVIRONMENTS)
def test_os_quatro_ambientes_sao_reconhecidos(ambiente):
    assert resolve_environment({"ENVIRONMENT": ambiente}) == ambiente


def test_contrato_tem_exatamente_os_quatro_ambientes():
    assert ENVIRONMENTS == (DEVELOPMENT, TEST, PILOT, PRODUCTION)


def test_ausencia_total_e_development():
    """Caso do desenvolvedor e da suite: derrubar o processo aqui nao protege ninguem."""
    assert resolve_environment({}) == DEVELOPMENT


@pytest.mark.parametrize(
    "valor",
    ["", "   ", "staging", "prod", "homolog", "homologacao", "producao", "dev", "PILOTO"],
)
def test_ambiente_desconhecido_falha_fechado(valor):
    """Inclui os aliases removidos: quem escrever "prod" tem de saber que errou.

    Cair em development com um valor irreconhecivel entregaria cookie sem
    `Secure` e docs abertas exatamente a quem pensou ter declarado um piloto.
    """
    with pytest.raises(InvalidEnvironmentError) as erro:
        resolve_environment({"ENVIRONMENT": valor})
    assert "ENVIRONMENT" in str(erro.value)


@pytest.mark.parametrize("valor", ["  Pilot  ", "PRODUCTION", "Development"])
def test_espaco_e_caixa_sao_normalizados(valor):
    assert resolve_environment({"ENVIRONMENT": valor}) == valor.strip().lower()


# ------------------------------------------------------------- cookie ------

def test_development_nao_exige_cookie_secure():
    assert cookie_secure_for(DEVELOPMENT) is False


def test_test_nao_exige_cookie_secure():
    assert cookie_secure_for(TEST) is False


@pytest.mark.parametrize("ambiente", ENDURECIDOS)
def test_ambiente_endurecido_exige_cookie_secure(ambiente):
    assert cookie_secure_for(ambiente) is True


def test_cookie_secure_nao_tem_override_por_variavel():
    """A funcao nao le ambiente: nao ha REFRESH_COOKIE_SECURE para rebaixar pilot."""
    import inspect

    from src.application import runtime

    assert list(inspect.signature(runtime.cookie_secure_for).parameters) == ["environment"]
    assert "REFRESH_COOKIE_SECURE" not in inspect.getsource(runtime)


def test_auth_deriva_o_flag_do_contrato():
    """Ponte com o consumidor real: auth.py usa a mesma funcao."""
    from src.application import auth

    assert auth.REFRESH_COOKIE_SECURE is cookie_secure_for(auth.ENVIRONMENT)
    assert auth.ENVIRONMENT in ENVIRONMENTS


# --------------------------------------------------------------- CORS ------

def test_development_usa_origens_locais_por_default():
    assert resolve_cors_origins({}, DEVELOPMENT) == list(CORS_ORIGENS_LOCAIS)


def test_development_reescreve_wildcard_em_vez_de_derrubar():
    assert resolve_cors_origins({"CORS_ORIGINS": "*"}, DEVELOPMENT) == list(CORS_ORIGENS_LOCAIS)


def test_development_respeita_origem_explicita():
    assert resolve_cors_origins({"CORS_ORIGINS": ORIGEM_REAL}, DEVELOPMENT) == [ORIGEM_REAL]


@pytest.mark.parametrize("ambiente", ENDURECIDOS)
@pytest.mark.parametrize("ambiente_os", [{}, {"CORS_ORIGINS": ""}, {"CORS_ORIGINS": "  , ,"}])
def test_endurecido_sem_cors_falha(ambiente, ambiente_os):
    with pytest.raises(InsecureCorsError) as erro:
        resolve_cors_origins(ambiente_os, ambiente)
    assert "CORS_ORIGINS" in str(erro.value)


@pytest.mark.parametrize("ambiente", ENDURECIDOS)
@pytest.mark.parametrize("valor", ["*", f"{ORIGEM_REAL},*"])
def test_endurecido_recusa_wildcard(ambiente, valor):
    """Nao ha reescrita silenciosa aqui: '*' com credentials e configuracao errada."""
    with pytest.raises(InsecureCorsError):
        resolve_cors_origins({"CORS_ORIGINS": valor}, ambiente)


@pytest.mark.parametrize("ambiente", ENDURECIDOS)
def test_endurecido_aceita_origem_explicita(ambiente):
    assert resolve_cors_origins({"CORS_ORIGINS": ORIGEM_REAL}, ambiente) == [ORIGEM_REAL]


@pytest.mark.parametrize("ambiente", ENDURECIDOS)
def test_endurecido_nunca_cai_em_localhost(ambiente):
    origens = resolve_cors_origins({"CORS_ORIGINS": ORIGEM_REAL}, ambiente)
    assert not any(origem in origens for origem in CORS_ORIGENS_LOCAIS)


def test_lista_com_varias_origens_preserva_ordem_e_limpa_espaco():
    outra = "https://admin.exemplo.com.br"
    assert resolve_cors_origins(
        {"CORS_ORIGINS": f" {ORIGEM_REAL} , {outra} "}, PILOT
    ) == [ORIGEM_REAL, outra]


# --------------------------------------------------------------- docs ------

@pytest.mark.parametrize("ambiente", [DEVELOPMENT, TEST])
def test_docs_ligadas_fora_dos_ambientes_endurecidos(ambiente):
    assert docs_enabled_for(ambiente) is True
    assert docs_urls_for(ambiente) == {
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "openapi_url": "/openapi.json",
    }


@pytest.mark.parametrize("ambiente", ENDURECIDOS)
def test_docs_desligadas_em_ambiente_endurecido(ambiente):
    assert docs_enabled_for(ambiente) is False
    assert docs_urls_for(ambiente) == {
        "docs_url": None,
        "redoc_url": None,
        "openapi_url": None,
    }


async def _status(app: FastAPI, rota: str) -> int:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return (await client.get(rota)).status_code


@pytest.mark.parametrize("rota", ["/docs", "/redoc", "/openapi.json"])
def test_rotas_de_documentacao_somem_em_pilot(rota):
    """Prova de rota, nao de kwargs: um FastAPI descartavel montado como pilot."""
    app = FastAPI(title="descartavel", **docs_urls_for(PILOT))
    assert asyncio.run(_status(app, rota)) == 404


@pytest.mark.parametrize("rota", ["/docs", "/openapi.json"])
def test_rotas_de_documentacao_existem_em_development(rota):
    app = FastAPI(title="descartavel", **docs_urls_for(DEVELOPMENT))
    assert asyncio.run(_status(app, rota)) == 200


def test_app_openapi_continua_funcional_com_rotas_desligadas():
    """Desligar a rota nao pode destruir o schema em processo.

    test_d1_documentos_filtro_admin chama main.app.openapi() para conferir o
    parametro residente_id; se `openapi_url=None` apagasse o gerador, aquele
    teste cairia por um motivo sem relacao com o que ele afirma.
    """
    app = FastAPI(title="descartavel", version="9.9.9", **docs_urls_for(PILOT))

    @app.get("/exemplo")
    def exemplo():  # pragma: no cover - so precisa existir no schema
        return {}

    schema = app.openapi()
    assert schema["info"]["version"] == "9.9.9"
    assert "/exemplo" in schema["paths"]


def test_app_real_da_suite_mantem_docs_e_schema():
    """A suite roda fora dos ambientes endurecidos, entao nada muda para ela."""
    from src import main

    assert main.ENVIRONMENT in (DEVELOPMENT, TEST)
    assert main.app.openapi_url == "/openapi.json"
    assert main.app.openapi()["info"]["title"] == "FáciLPI API"
