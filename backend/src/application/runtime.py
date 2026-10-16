"""SAFE2-C1: leitura canonica do ambiente e das protecoes que dependem dele.

Modulo proprio, e nao uma funcao em `auth.py`, por duas razoes concretas:
`auth.py` resolve JWT_SECRET no corpo do modulo, entao perguntar "qual e o
ambiente?" passaria a exigir um segredo valido; e as decisoes de CORS e de docs,
que vivem em `main.py`, nao sao assunto de autenticacao. Aqui nao ha efeito
colateral de import — so funcoes puras sobre um ambiente injetado, no mesmo
formato de `resolve_jwt_secret` e `ensure_database_allowed`.

O contrato existe porque a protecao anterior dependia de uma variavel que nenhum
artefato de implantacao definia: `secure` do cookie saia de um conjunto que
incluia "staging", "prod" e "homolog", e nem o compose nem o Dockerfile
declaravam ENVIRONMENT. Um piloto subia enviando a sessao sem `Secure`.
"""

from __future__ import annotations

from typing import Mapping

DEVELOPMENT = "development"
TEST = "test"
PILOT = "pilot"
PRODUCTION = "production"

ENVIRONMENTS = (DEVELOPMENT, TEST, PILOT, PRODUCTION)

# Ambientes que atendem rede nao confiavel. As protecoes abaixo NAO sao
# configuraveis neles: deixar `Secure` ou a politica de docs sob uma segunda
# variavel reproduziria exatamente a falha que a SAFE2-C1 fecha.
HARDENED_ENVIRONMENTS = frozenset({PILOT, PRODUCTION})

CORS_ORIGENS_LOCAIS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
)


class InvalidEnvironmentError(RuntimeError):
    """ENVIRONMENT com valor fora do contrato."""


class InsecureCorsError(RuntimeError):
    """CORS_ORIGINS ausente ou permissiva demais para o ambiente."""


def resolve_environment(env: Mapping[str, str]) -> str:
    """Interpreta ENVIRONMENT. Ausencia e development; valor estranho e erro.

    A distincao e deliberada. Ausencia total e o caso do desenvolvedor e da
    suite, e derrubar o processo ali nao protegeria ninguem. Valor PRESENTE e
    irreconhecivel e outra coisa: alguem tentou declarar o ambiente e errou, e
    seguir em `development` entregaria cookie sem `Secure` e docs abertas
    justamente a quem pensava ter configurado um piloto.

    Em pilot e production quem garante a presenca da variavel e o compose, com
    `:?` — mesmo mecanismo que a SAFE2-A aplicou a DATABASE_URL e JWT_SECRET.
    """
    bruto = env.get("ENVIRONMENT")
    if bruto is None:
        return DEVELOPMENT
    valor = bruto.strip().lower()
    if valor not in ENVIRONMENTS:
        raise InvalidEnvironmentError(
            f"ENVIRONMENT={bruto!r} nao pertence ao contrato. "
            f"Use exatamente um de: {', '.join(ENVIRONMENTS)}."
        )
    return valor


def cookie_secure_for(environment: str) -> bool:
    """Em pilot/production `Secure` nao se negocia — nao ha override por variavel."""
    return environment in HARDENED_ENVIRONMENTS


def docs_enabled_for(environment: str) -> bool:
    return environment not in HARDENED_ENVIRONMENTS


def docs_urls_for(environment: str) -> dict[str, str | None]:
    """kwargs de rota do FastAPI.

    Desliga apenas as ROTAS publicas. O gerador em processo continua intacto:
    `app.openapi()` segue funcionando, e e dele que
    test_d1_documentos_filtro_admin depende.
    """
    if docs_enabled_for(environment):
        return {
            "docs_url": "/docs",
            "redoc_url": "/redoc",
            "openapi_url": "/openapi.json",
        }
    return {"docs_url": None, "redoc_url": None, "openapi_url": None}


def resolve_cors_origins(env: Mapping[str, str], environment: str) -> list[str]:
    """Resolve as origens permitidas, falhando fechado em pilot/production."""
    bruto = env.get("CORS_ORIGINS")
    declarado = [item.strip() for item in (bruto or "").split(",") if item.strip()]

    if environment in HARDENED_ENVIRONMENTS:
        if not declarado:
            raise InsecureCorsError(
                "CORS_ORIGINS e obrigatoria em pilot e production. Informe a "
                "origem real do frontend; nao ha default local nesses ambientes."
            )
        if "*" in declarado:
            raise InsecureCorsError(
                "CORS_ORIGINS nao aceita '*' em pilot e production: a sessao usa "
                "cookie com credentials, incompativel com origem coringa."
            )
        return declarado

    if not declarado or "*" in declarado:
        # Ergonomia local preservada: fora dos ambientes endurecidos o wildcard
        # continua virando as origens locais, em vez de derrubar o processo de
        # quem esta desenvolvendo.
        return list(CORS_ORIGENS_LOCAIS)
    return declarado
