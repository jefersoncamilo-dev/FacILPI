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

from src.infrastructure.models import Base  # noqa: E402
from src.infrastructure.database import DATABASE_URL as APP_DATABASE_URL  # noqa: E402

target_metadata = Base.metadata

def get_url():
    # B: prioriza DATABASE_URL explícita e APP_DATABASE_URL (Path resolvido independente de CWD) antes de alembic.ini
    url = context.get_x_argument(as_dictionary=True).get("database_url") or os.getenv("DATABASE_URL") or APP_DATABASE_URL or config.get_main_option("sqlalchemy.url")
    # normalize like database.py
    if url.startswith("sqlite:///"):
        url = url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    elif url.startswith("sqlite://"):
        url = url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    elif url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
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
