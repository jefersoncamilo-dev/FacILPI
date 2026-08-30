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
            # For sqlite we may have absolute /storage/app.db
            # pathlib expects relative or absolute
            p = pathlib.Path(path)
            parent = p.parent
            if str(parent) not in ("", "."):
                parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass


DATABASE_URL = _normalize_database_url(
    os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./storage/app.db")
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

SessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with SessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()
