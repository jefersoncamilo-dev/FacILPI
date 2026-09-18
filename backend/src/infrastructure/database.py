import os
import pathlib
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from .db_guard import ensure_database_allowed


def _normalize_database_url(url: str) -> str:
    url = url.strip()
    # Compat: convert sync sqlite URL to async
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if url.startswith("sqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


# SAFE2-A/B02: `_resolve_default_sqlite_url()` foi removida. Ela montava a URL de
# <raiz>/storage/app.db e era o fallback de DATABASE_URL, o que fazia a aplicacao
# abrir o banco historico protegido sempre que a variavel nao estivesse definida.
# Nao ha substituto: ver `resolve_database_url`, que falha fechado.


def _ensure_parent_dir(database_url: str) -> None:
    # Only for sqlite file-based URLs
    # Extract file path after third slash: sqlite+aiosqlite:///./storage/app.db -> ./storage/app.db
    if "sqlite" in database_url:
        # Find path after "://"
        try:
            path = database_url.split("://", 1)[1]
            # remove query params
            path = path.split("?", 1)[0]
            # handle leading ./ and /
            # Para URL absoluta com 4 slashes, path começa com / (ex: /storage/app.db ou C:/...)
            # Remove leading slash duplicado para Path absoluto em Windows
            # pathlib handles both /storage and C:/path
            # Strip leading "/" only if path like "//" ?
            p = pathlib.Path(path)
            # Se for relativo com "./", manter
            parent = p.parent
            if str(parent) not in ("", ".", "/"):
                parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


class MissingDatabaseUrlError(RuntimeError):
    """DATABASE_URL nao definida e nao ha default."""


def resolve_database_url(env) -> str:
    """Resolve a URL operacional, falhando fechado.

    SAFE2-A/B02: o fallback anterior era `_resolve_default_sqlite_url()`, que
    apontava para <raiz>/storage/app.db — o banco historico protegido. Esquecer
    a variavel abria esse arquivo em modo de escrita, em silencio. Nao ha mais
    default: a ausencia e erro, e o guard ainda recusa o alvo protegido caso
    alguem o informe explicitamente.
    """
    bruta = env.get("DATABASE_URL")
    if bruta is None or not bruta.strip():
        raise MissingDatabaseUrlError(
            "DATABASE_URL nao definida. Informe o banco do ambiente; nao ha "
            "default. O banco historico em storage/app.db nao e operacional."
        )
    return ensure_database_allowed(_normalize_database_url(bruta))


DATABASE_URL = resolve_database_url(os.environ)

_ensure_parent_dir(DATABASE_URL)

# Decide engine kwargs based on backend
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    # sqlite async needs check_same_thread false is default via aiosqlite
    pass
else:
    # postgres: enable pool; pgbouncer handling via query params already
    pass

_engine_kwargs = {"echo": False}
if DATABASE_URL.startswith("postgresql"):
    _engine_kwargs.update({"pool_size": 5, "max_overflow": 10})

engine = create_async_engine(DATABASE_URL, **_engine_kwargs)

# H: Ativar PRAGMA foreign_keys=ON para SQLite (conexão real da aplicação)
if DATABASE_URL.startswith("sqlite"):
    from sqlalchemy import event as sa_event

    @sa_event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
