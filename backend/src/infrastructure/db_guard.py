"""Recusa fail-closed do banco historico protegido, em runtime.

`storage/app.db` e `backend/storage/app.db` sao artefatos historicos: ficam
deliberadamente parados em `006_catalogo_clinico_rbac` e nao sao o banco
operacional de nenhum ambiente. Antes deste modulo, cinco fontes independentes
resolviam para eles por default — a aplicacao, o `alembic.ini`, o `.env.example`
e as duas camadas de Docker — e o CMD do container ainda executava
`alembic upgrade head` na subida. `docker compose up` bastava para migra-los.

DENYLIST, e nao allowlist. `tests/db_safety.py` exige que o alvo esteja sob um
diretorio temporario registrado, o que e correto para teste e errado para
runtime: o banco do piloto vive em diretorio persistente. Aqui os dois arquivos
protegidos sao recusados e todo o resto e liberado.

Este modulo nao tem efeito colateral e nao importa nada do projeto: `database.py`
e `alembic/env.py` dependem dele, nunca o contrario. `tests/` pode importa-lo;
`src/` nunca importa de `tests/`.
"""

from __future__ import annotations

import os
import pathlib
from urllib.parse import unquote

from sqlalchemy.engine import make_url


# __file__ = <raiz>/backend/src/infrastructure/db_guard.py -> parents[3] == <raiz>
# Mesma derivacao de `_resolve_default_sqlite_url`, e igualmente independente do CWD.
ROOT = pathlib.Path(__file__).resolve().parents[3]

PROTECTED_DATABASES = (
    (ROOT / "storage" / "app.db").resolve(),
    (ROOT / "backend" / "storage" / "app.db").resolve(),
)


class ProtectedDatabaseError(RuntimeError):
    """A URL resolvida aponta para um banco historico protegido."""


def _normalised(path: pathlib.Path) -> str:
    # normcase resolve a insensibilidade a maiusculas do Windows; no POSIX e no-op.
    return os.path.normcase(str(path))


def _same_file(candidate: pathlib.Path, protected: pathlib.Path) -> bool:
    """Compara em duas camadas, porque cada uma sozinha tem furo.

    `samefile` compara identidade real no filesystem e por isso pega symlink,
    hardlink e junction do Windows — aliases que comparacao textual nao pega.
    Mas exige que os dois lados existam. Quando o alvo ainda nao existe (banco
    novo), a comparacao textual normalizada cobre `..`, caminho relativo e case.
    """
    try:
        if candidate.exists() and protected.exists():
            return os.path.samefile(candidate, protected)
    except OSError:
        # Permissao negada ou path invalido: cai na comparacao textual em vez de
        # deixar o erro do filesystem virar liberacao silenciosa.
        pass
    return _normalised(candidate) == _normalised(protected)


def sqlite_target(url: str) -> pathlib.Path | None:
    """Caminho do arquivo SQLite da URL, ou None se nao for arquivo SQLite.

    Descarta a query: `?mode=ro` e qualquer outro parametro nao mudam QUAL
    arquivo e aberto, e portanto nao sao rota de escape desta recusa.
    """
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        return None
    database = parsed.database
    if database is None or database in ("", ":memory:"):
        return None
    return pathlib.Path(unquote(database)).resolve()


def ensure_database_allowed(url: str) -> str:
    """Devolve a URL ou levanta se ela apontar para um banco protegido.

    PostgreSQL passa direto. SQLite em memoria e SQLite descartavel passam.
    A mensagem nomeia o arquivo protegido, nunca credencial da URL.
    """
    candidate = sqlite_target(url)
    if candidate is None:
        return url
    for protected in PROTECTED_DATABASES:
        if _same_file(candidate, protected):
            raise ProtectedDatabaseError(
                "Banco historico protegido recusado: "
                f"{protected}. Defina DATABASE_URL apontando para o banco do "
                "ambiente; este arquivo nao e operacional e nao deve ser migrado."
            )
    return url
