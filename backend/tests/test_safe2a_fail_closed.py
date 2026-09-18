"""SAFE2-A: fail-closed de JWT_SECRET (B01) e do banco historico (B02).

Testes de unidade sobre funcoes puras com ambiente injetado: nao sobem a
aplicacao, nao abrem conexao e nao criam subprocesso. Por isso a suite inteira
roda em segundos, que e o que a politica FAST exige.

Nenhum teste toca storage/app.db. As assercoes sao sobre a RECUSA de alcanca-lo.
"""

import os
import pathlib

import pytest

from src.application.auth import (
    JWT_SECRETS_CONHECIDOS,
    JWT_SECRET_MIN_BYTES,
    InsecureJWTSecretError,
    resolve_jwt_secret,
)
from src.infrastructure.database import MissingDatabaseUrlError, resolve_database_url
from src.infrastructure.db_guard import (
    PROTECTED_DATABASES,
    ROOT,
    ProtectedDatabaseError,
    ensure_database_allowed,
    sqlite_target,
)

SEGREDO_VALIDO = "k9QbW3zR7tYx2LmP5vNc8HjF4dSg6aEu"  # 32 bytes, so para teste


# ------------------------------------------------------------------ B01 ----

def test_jwt_ausente_falha():
    with pytest.raises(InsecureJWTSecretError) as erro:
        resolve_jwt_secret({})
    assert "JWT_SECRET" in str(erro.value)


@pytest.mark.parametrize("vazio", ["", "   ", "\t\n"])
def test_jwt_vazio_ou_so_espaco_falha(vazio):
    # String vazia passaria num teste de `is None`; a recusa precisa ser por valor.
    with pytest.raises(InsecureJWTSecretError):
        resolve_jwt_secret({"JWT_SECRET": vazio})


@pytest.mark.parametrize("conhecido", sorted(JWT_SECRETS_CONHECIDOS))
def test_jwt_default_conhecido_falha(conhecido):
    """Os tres defaults que ja circularam versionados neste repositorio."""
    # Todos tem 32+ bytes: sem a lista, passariam na checagem de tamanho.
    assert len(conhecido.encode()) >= JWT_SECRET_MIN_BYTES
    with pytest.raises(InsecureJWTSecretError) as erro:
        resolve_jwt_secret({"JWT_SECRET": conhecido})
    assert "desenvolvimento" in str(erro.value)


def test_jwt_curto_falha():
    curto = "a" * (JWT_SECRET_MIN_BYTES - 1)
    with pytest.raises(InsecureJWTSecretError) as erro:
        resolve_jwt_secret({"JWT_SECRET": curto})
    assert str(JWT_SECRET_MIN_BYTES) in str(erro.value)


def test_jwt_conta_bytes_e_nao_caracteres():
    """16 caracteres acentuados sao 32 bytes em UTF-8, mas nao 32 caracteres.

    Medir por len(str) trataria o inverso — um segredo de 32 caracteres ASCII e
    um de 32 caracteres multibyte — como equivalentes. O que importa para
    entropia de assinatura e o tamanho em bytes.
    """
    dezesseis_acentuados = "ç" * 16
    assert len(dezesseis_acentuados) == 16
    assert len(dezesseis_acentuados.encode("utf-8")) == 32
    assert resolve_jwt_secret({"JWT_SECRET": dezesseis_acentuados}) == dezesseis_acentuados


def test_jwt_valido_e_aceito_sem_alteracao():
    assert resolve_jwt_secret({"JWT_SECRET": SEGREDO_VALIDO}) == SEGREDO_VALIDO


@pytest.mark.parametrize(
    "ambiente",
    [
        {"JWT_SECRET": "curto-demais"},
        {"JWT_SECRET": sorted(JWT_SECRETS_CONHECIDOS)[0]},
    ],
)
def test_excecao_nunca_contem_o_segredo(ambiente):
    """Erro de configuracao nao pode virar vazamento em log de startup."""
    segredo = ambiente["JWT_SECRET"]
    with pytest.raises(InsecureJWTSecretError) as erro:
        resolve_jwt_secret(ambiente)
    mensagem = str(erro.value)
    assert segredo not in mensagem
    # Nem um prefixo util: 8 caracteres ja bastariam para confirmar um palpite.
    assert segredo[:8] not in mensagem


def test_suite_roda_com_segredo_explicito():
    """conftest injeta um segredo controlado; nenhum default sustenta a suite."""
    atual = os.environ.get("JWT_SECRET")
    assert atual, "conftest deve definir JWT_SECRET"
    assert atual not in JWT_SECRETS_CONHECIDOS
    assert len(atual.encode()) >= JWT_SECRET_MIN_BYTES


# ------------------------------------------------------------------ B02 ----

PROTEGIDO = PROTECTED_DATABASES[0]          # <raiz>/storage/app.db
PROTEGIDO_BACKEND = PROTECTED_DATABASES[1]  # <raiz>/backend/storage/app.db


def _url(caminho) -> str:
    return f"sqlite+aiosqlite:///{pathlib.Path(caminho).as_posix()}"


def test_alvos_protegidos_sao_os_dois_esperados():
    assert PROTEGIDO == (ROOT / "storage" / "app.db").resolve()
    assert PROTEGIDO_BACKEND == (ROOT / "backend" / "storage" / "app.db").resolve()


@pytest.mark.parametrize("protegido", PROTECTED_DATABASES, ids=["storage", "backend_storage"])
def test_banco_protegido_absoluto_recusado(protegido):
    with pytest.raises(ProtectedDatabaseError) as erro:
        ensure_database_allowed(_url(protegido))
    assert "protegido" in str(erro.value).lower()


def test_banco_protegido_por_caminho_relativo_recusado():
    """Forma equivalente que a comparacao textual ingenua deixaria passar."""
    relativo = os.path.relpath(PROTEGIDO, pathlib.Path.cwd())
    with pytest.raises(ProtectedDatabaseError):
        ensure_database_allowed(f"sqlite+aiosqlite:///{pathlib.Path(relativo).as_posix()}")


def test_banco_protegido_com_ponto_ponto_recusado():
    com_volta = ROOT / "backend" / ".." / "storage" / "app.db"
    with pytest.raises(ProtectedDatabaseError):
        ensure_database_allowed(_url(com_volta))


@pytest.mark.skipif(os.name != "nt", reason="case-insensitivity e especifica do Windows")
def test_banco_protegido_com_case_diferente_recusado_no_windows():
    trocado = str(PROTEGIDO).upper()
    with pytest.raises(ProtectedDatabaseError):
        ensure_database_allowed(_url(trocado))


def test_query_sqlite_nao_e_rota_de_escape():
    """`?mode=ro` nao muda QUAL arquivo e aberto, entao nao libera o alvo."""
    with pytest.raises(ProtectedDatabaseError):
        ensure_database_allowed(f"{_url(PROTEGIDO)}?mode=ro")


def test_url_encoding_nao_e_rota_de_escape():
    codificado = _url(PROTEGIDO).replace("app.db", "app%2edb")
    with pytest.raises(ProtectedDatabaseError):
        ensure_database_allowed(codificado)


def test_sqlite_descartavel_permitido(tmp_path):
    alvo = tmp_path / "descartavel.db"
    url = _url(alvo)
    assert ensure_database_allowed(url) == url


def test_sqlite_em_memoria_permitido():
    for url in ("sqlite+aiosqlite:///:memory:", "sqlite+aiosqlite://"):
        assert ensure_database_allowed(url) == url


def test_postgres_permitido():
    url = "postgresql+asyncpg://postgres:postgres@127.0.0.1:55486/facilpi_qa_test"
    assert ensure_database_allowed(url) == url
    # E nao e sequer tratado como alvo SQLite.
    assert sqlite_target(url) is None


def test_outro_arquivo_na_mesma_pasta_e_permitido(tmp_path):
    """A recusa e por ARQUIVO, nao por diretorio.

    Uma denylist de pasta impediria um banco de piloto legitimo em
    storage/pilot/, que e exatamente onde o compose passa a monta-lo.
    """
    vizinho = PROTEGIDO.parent / "pilot" / "facilpi.db"
    url = _url(vizinho)
    assert ensure_database_allowed(url) == url


@pytest.mark.parametrize("ambiente", [{}, {"DATABASE_URL": ""}, {"DATABASE_URL": "   "}])
def test_database_url_ausente_falha_em_vez_de_cair_no_banco_protegido(ambiente):
    """Antes da SAFE2-A, este caminho resolvia para <raiz>/storage/app.db."""
    with pytest.raises(MissingDatabaseUrlError) as erro:
        resolve_database_url(ambiente)
    assert "DATABASE_URL" in str(erro.value)


def test_database_url_normaliza_e_valida_junto(tmp_path):
    """A forma sincrona `sqlite:///` vira async e passa pelo guard na mesma etapa."""
    alvo = tmp_path / "op.db"
    resolvida = resolve_database_url({"DATABASE_URL": f"sqlite:///{alvo.as_posix()}"})
    assert resolvida.startswith("sqlite+aiosqlite:///")


def test_database_url_explicita_para_banco_protegido_ainda_e_recusada():
    """Remover o default nao basta: informar o alvo a mao tambem tem de falhar."""
    with pytest.raises(ProtectedDatabaseError):
        resolve_database_url({"DATABASE_URL": _url(PROTEGIDO)})


@pytest.mark.parametrize("protegido", PROTECTED_DATABASES, ids=["storage", "backend_storage"])
def test_guard_nao_cria_nem_toca_o_arquivo_protegido(protegido):
    """A recusa e inspecao de caminho: nada e aberto, nada e criado.

    O artefato existe na maquina do piloto e nao existe no runner do CI, entao o
    invariante e afirmado nos dois estados. O teste nunca cria o arquivo para
    poder observa-lo: ausente, o que se afirma e que a recusa nao o materializa —
    que e a metade mais relevante para seguranca.
    """
    existia = protegido.exists()
    antes = protegido.stat() if existia else None

    with pytest.raises(ProtectedDatabaseError):
        ensure_database_allowed(_url(protegido))

    assert protegido.exists() is existia, "o guard nao pode criar nem remover o alvo"
    if antes is not None:
        depois = protegido.stat()
        assert (antes.st_size, antes.st_mtime_ns) == (depois.st_size, depois.st_mtime_ns)
