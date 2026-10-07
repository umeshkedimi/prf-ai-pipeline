"""Recovery for campaign-agent runs whose worker died mid-loop. Same shape as
run_recovery.py: detect by a quiet heartbeat, claim by compare-and-swap, continue
from the LangGraph checkpoint.

Continuing re-executes the node that was in flight, which is safe by construction:
`launch_donor_runs` only launches donors still `staged` (a repeat is a no-op),
`pad_postal_codes` prechecks for 4-digit codes (already-padded ids are refused), and
reads are repeatable. The cost is a repeated model call and a duplicate audit row."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import AgentRun


def stall_cutoff(now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) - timedelta(seconds=get_settings().run_stall_ttl_seconds)


def _stalled(cutoff: datetime):
    # NULL heartbeat (a row from before the column existed) compares as NULL and is
    # never selected: we cannot tell stalled from slow.
    return AgentRun.status == "running", AgentRun.heartbeat_at < cutoff


async def find_stalled_agent_run_ids(session: AsyncSession) -> list[uuid.UUID]:
    rows = await session.execute(select(AgentRun.id).where(*_stalled(stall_cutoff())))
    return list(rows.scalars().all())


async def reclaim_stalled_agent_run(session: AsyncSession, run_id: uuid.UUID) -> bool:
    """One conditional UPDATE: only a run that is still stalled at write time is taken."""
    taken = await session.execute(
        update(AgentRun)
        .where(AgentRun.id == run_id, *_stalled(stall_cutoff()))
        .values(heartbeat_at=func.now())
        .returning(AgentRun.id)
    )
    await session.commit()
    return taken.first() is not None
