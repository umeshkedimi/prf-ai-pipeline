"""Recovery for pipeline runs whose worker died mid-graph.

A run's status is set to `running` by the task that executes it. If that
process is killed, nothing ever moves the run on: the task's message was
already acknowledged (so the broker won't redeliver it) and the status says
"someone is working on this". The work itself is not lost — the graph
checkpoints after every node (`durability="sync"`) — so recovery is just
*detect* and *continue from the checkpoint*.

- **Detect.** Every node stamps `heartbeat_at` as it starts. A `running` run
  with no heartbeat inside the TTL is stalled. The TTL is sized to the slowest
  single node, not a whole run, because a long run keeps beating.
- **Claim.** Takeover is a compare-and-swap with the staleness test inside the
  UPDATE's WHERE, so two recoverers cannot both resume the same run.
- **Scope.** Only runs with no `result` yet. A held-letter release also sits in
  `running`, but it already has a result and has its own recovery
  (release_claims.py).

Resuming re-executes the node that was in flight. That is safe here: reads are
repeatable, the PDF render overwrites the same file, the vendor order is keyed
on the run's deterministic reference, and a node's output only reaches state
when it completes. The cost is a repeated LLM call and a duplicate audit row."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.models import WorkflowRun
from app.db.session import db_session

log = get_logger(__name__)


def stall_cutoff(now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) - timedelta(seconds=get_settings().run_stall_ttl_seconds)


def _stalled(cutoff: datetime):
    # heartbeat_at IS NULL (rows from before the column existed) compares as NULL
    # here, so they are never selected — we cannot tell stalled from slow.
    return (
        WorkflowRun.status == "running",
        WorkflowRun.result.is_(None),
        WorkflowRun.heartbeat_at < cutoff,
    )


async def touch_heartbeat(workflow_run_id: str | None) -> None:
    """Best-effort: a failed heartbeat write must never fail the node it is
    announcing, so errors are logged and swallowed."""
    if not workflow_run_id:
        return
    try:
        async with db_session() as session:
            await session.execute(
                update(WorkflowRun)
                .where(WorkflowRun.id == uuid.UUID(workflow_run_id), WorkflowRun.status == "running")
                .values(heartbeat_at=func.now())
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning("workflow_run.heartbeat_failed", workflow_run_id=workflow_run_id, error=str(exc))


async def find_stalled_run_ids(session: AsyncSession) -> list[uuid.UUID]:
    rows = await session.execute(select(WorkflowRun.id).where(*_stalled(stall_cutoff())))
    return list(rows.scalars().all())


async def reclaim_stalled_run(session: AsyncSession, run_id: uuid.UUID) -> bool:
    """Take over a stalled run by refreshing its heartbeat, only if it is still
    stalled at write time. Returns False if someone else got there first or the
    run came back to life."""
    taken = await session.execute(
        update(WorkflowRun)
        .where(WorkflowRun.id == run_id, *_stalled(stall_cutoff()))
        .values(heartbeat_at=func.now())
        .returning(WorkflowRun.id)
    )
    return taken.scalar_one_or_none() is not None
