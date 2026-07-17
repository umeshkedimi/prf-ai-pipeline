import uuid

import pytest

from app.db.base import reset_engine
from app.db.session import db_session as db_session_cm

# Must match scripts/seed_db.py's NAMESPACE — kept in sync manually since the two
# are logically the same "demo fixture ids" concern but live in different layers
# (seed script vs. tests).
SEED_NAMESPACE = uuid.UUID("6f9c3b1a-9b0e-4c9a-9c2e-9d6a2b6b8a10")


def seed_uuid(*parts: str) -> uuid.UUID:
    return uuid.uuid5(SEED_NAMESPACE, ":".join(parts))


@pytest.fixture(autouse=True)
async def _reset_db_engine():
    """pytest-asyncio gives each test its own event loop; see reset_engine()'s
    docstring for why the cached engine can't survive across loops."""
    yield
    await reset_engine()


@pytest.fixture
async def db_session():
    async with db_session_cm() as session:
        yield session
