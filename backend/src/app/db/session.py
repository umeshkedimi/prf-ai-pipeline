from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_sessionmaker


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency."""
    async with get_sessionmaker()() as session:
        yield session


@asynccontextmanager
async def db_session() -> AsyncIterator[AsyncSession]:
    """Context manager for use outside FastAPI (Celery tasks, scripts, agent nodes)."""
    async with get_sessionmaker()() as session:
        yield session
