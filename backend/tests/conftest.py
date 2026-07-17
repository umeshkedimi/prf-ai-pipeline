import uuid

import pytest

import app.db.base as db_base
from app.db.session import db_session as db_session_cm

# Must match scripts/seed_db.py's NAMESPACE — kept in sync manually since the two
# are logically the same "demo fixture ids" concern but live in different layers
# (seed script vs. tests).
SEED_NAMESPACE = uuid.UUID("6f9c3b1a-9b0e-4c9a-9c2e-9d6a2b6b8a10")


def seed_uuid(*parts: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, ":".join(parts))


@pytest.fixture(autouse=True)
async def _reset_db_engine():
    """app.db.base caches the engine/sessionmaker per-process (correct for a real
    single-event-loop process). pytest-asyncio gives each test its own event loop,
    so the cached engine must be torn down and recreated between tests or asyncpg
    connections end up bound to a closed loop."""
    yield
    if db_base._engine is not None:
        await db_base._engine.dispose()
    db_base._engine = None
    db_base._sessionmaker = None


@pytest.fixture
async def db_session():
    async with db_session_cm() as session:
        yield session
