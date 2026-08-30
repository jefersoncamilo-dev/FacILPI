import os
import pathlib
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase


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


def _resolve_default_sqlite_url() -> str:
    # B: caminho independente de CWD — resolve para <raiz>/storage/app.db via Path(__file__)
    # __file__ = .../backend/src/infrastructure/database.py -> parents[3] == <raiz>
    try:
        root = pathlib.Path(__file__).resolve().parents[3]
        default_path = root / "storage" / "app.db"
        # usa 4 slashes para caminho absoluto posix (ex: sqlite+aiosqlite:////abs/path)
        # para compatibilidade docker (/storage/app.db) aceita absoluto; local usa absoluto também
        return f"sqlite+aiosqlite:///{default_path.as_posix()}"
    except Exception:
        return "sqlite+aiosqlite:///./storage/app.db"


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


# B: DATABASE_URL explícita tem prioridade; se não definida, usa caminho resolvido independente de CWD
# No Docker, DATABASE_URL=sqlite+aiosqlite:////storage/app.db (absoluto) via compose
DATABASE_URL = _normalize_database_url(
    os.getenv("DATABASE_URL", _resolve_default_sqlite_url())
)

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
