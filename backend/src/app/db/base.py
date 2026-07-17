from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """Lazily created per-process. Must not be called before a Celery prefork
    worker forks — asyncpg connections are not fork-safe."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def reset_engine() -> None:
    """Dispose and clear the cached engine/sessionmaker.

    The cache above is correct for a process with one long-lived event loop
    (FastAPI/uvicorn) but wrong for anything that calls asyncio.run() more than
    once per process — each call gets a brand-new loop, and asyncpg connections
    are bound to the loop that created them. Celery's prefork workers handle many
    tasks per process, each wrapped in its own asyncio.run(), so task code must
    call this before (and after) doing DB work. See tests/conftest.py for the
    same issue under pytest-asyncio's per-test event loops.
    """
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
