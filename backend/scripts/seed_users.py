"""Idempotently seeds a demo admin user for local development.

Usage: uv run python scripts/seed_users.py

Dev-only credentials -- rotate before this ever runs against a real deployment.
The admin can create further users (reviewers, more admins) via
POST /api/v1/auth/users once logged in.
"""

import asyncio

from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.security import hash_password
from app.db.models import User
from app.db.session import db_session

ADMIN_EMAIL = "admin@prf.local"
ADMIN_PASSWORD = "changeme123"


async def seed() -> None:
    async with db_session() as session:
        stmt = pg_insert(User).values(
            email=ADMIN_EMAIL,
            full_name="Demo Admin",
            hashed_password=hash_password(ADMIN_PASSWORD),
            role="admin",
        )
        stmt = stmt.on_conflict_do_nothing(index_elements=[User.email])
        await session.execute(stmt)
        await session.commit()

    print(f"Seeded admin user: {ADMIN_EMAIL} / {ADMIN_PASSWORD} (change before any real deployment)")


if __name__ == "__main__":
    asyncio.run(seed())
