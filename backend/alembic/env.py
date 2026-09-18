import asyncio
import os
import pathlib
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine
from alembic import context

# this is the Alembic Config object
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# import Base and models
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# SAFE2-A/B02: `-x database_url=` precisa ser promovido ANTES do import abaixo.
# `models` importa `database`, que resolve DATABASE_URL no corpo do modulo e
# falha fechado sem ela. Sem esta promocao, um `alembic -x database_url=<url>`
# perfeitamente valido seria recusado por causa de uma variavel de ambiente que o
# operador acabou de tornar desnecessaria ao passar o alvo explicitamente.
_x_database_url = context.get_x_argument(as_dictionary=True).get("database_url")
if _x_database_url:
    os.environ["DATABASE_URL"] = _x_database_url

from src.infrastructure.models import Base  # noqa: E402
from src.infrastructure.db_guard import ensure_database_allowed  # noqa: E402

target_metadata = Base.metadata

# SAFE2-A/B02: o import de `src.infrastructure.database` foi removido de propósito.
# Ele resolvia DATABASE_URL no corpo do módulo, então bastava importá-lo para
# herdar o default que apontava ao banco histórico — inclusive quando o operador
# passava `-x database_url=` correto. Aqui a URL é resolvida só a partir de
# fontes explícitas, e a ausência de todas é erro, não fallback.
def get_url():
    # Ordem: -x database_url= (ato deliberado) > URL de teste descartável > DATABASE_URL.
    url = (
        context.get_x_argument(as_dictionary=True).get("database_url")
        or os.getenv("FASE3A_TEST_POSTGRES_URL")
        or os.getenv("DATABASE_URL")
    )
    if not url:
        raise RuntimeError(
            "Alembic sem banco de destino. Defina DATABASE_URL ou passe "
            "-x database_url=<url>. Não há default: migrar é ato deliberado "
            "sobre um banco escolhido, nunca efeito colateral de um comando."
        )
    # normalize like database.py
    if url.startswith("sqlite:///"):
        url = url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    elif url.startswith("sqlite://"):
        url = url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    # Recusa o banco historico protegido ANTES de criar diretorio ou conectar.
    ensure_database_allowed(url)
    # ensure parent dir for sqlite
    if "sqlite" in url:
        try:
            path = url.split("://", 1)[1].split("?", 1)[0]
            p = pathlib.Path(path)
            if str(p.parent) not in ("", "."):
                p.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    return url

def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()

async def run_async_migrations():
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_url()
    connectable = create_async_engine(
        configuration["sqlalchemy.url"],
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()

def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
