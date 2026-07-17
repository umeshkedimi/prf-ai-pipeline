from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import quote

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import get_settings


@asynccontextmanager
async def get_checkpointer() -> AsyncIterator[AsyncPostgresSaver]:
    """Checkpoints live in the `langgraph` Postgres schema (provisioned in the
    baseline Alembic migration), kept separate from the Alembic-managed business
    tables in `public`. .setup() is idempotent (CREATE TABLE IF NOT EXISTS under
    the hood) so it's safe to call on every graph build."""
    settings = get_settings()
    conn_string = f"{settings.checkpointer_database_url}?options=-csearch_path%3D{quote('langgraph')}"
    async with AsyncPostgresSaver.from_conn_string(conn_string) as checkpointer:
        await checkpointer.setup()
        yield checkpointer
