"""Claim bookkeeping for releasing a held letter.

Releasing a letter is two steps that cannot be one transaction: claim the run
(status -> running) and place the vendor order in a Celery task. A process can
die between them, or mid-task, leaving a run in `running` that nothing will
ever advance.

Two properties make that recoverable:

- **Safety** — retrying is harmless, because the order is keyed on the run's
  deterministic mail-piece reference, so a repeat cannot create a second
  order. (A real vendor needs that reference passed as its idempotency key;
  the mock derives its whole response from it.)
- **Liveness** — something has to retry. Each claim stamps `release_claim`
  (when, who, why) onto `pdf_result`; a claim older than the TTL is *stale*,
  and a stale claim can be taken over by a compare-and-swap on that same
  timestamp, so two recoverers can't both win.

The claim lives inside `pdf_result` rather than a new column: it is only
meaningful while that letter is held, and it avoids a migration."""

import json
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import DateTime, Text, cast, func, literal, select, update
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import WorkflowRun

_CLAIM_PATH = cast(literal("{pdf_generation,release_claim}"), ARRAY(Text))
_CLAIMED_AT = WorkflowRun.result["pdf_generation"]["release_claim"]["claimed_at"].astext
_HELD = WorkflowRun.result["pdf_generation"]["held"].astext == "true"


def build_claim(decision: dict, now: datetime | None = None) -> dict:
    return {
        "claimed_at": (now or datetime.now(UTC)).isoformat(),
        "reviewer": decision["reviewer"],
        "notes": decision["notes"],
    }


def stale_cutoff(now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) - timedelta(seconds=get_settings().release_claim_ttl_seconds)


def _stamp(claim: dict):
    return func.jsonb_set(
        WorkflowRun.result, _CLAIM_PATH, cast(literal(json.dumps(claim)), JSONB), True
    )


async def claim_release(session: AsyncSession, run_id: uuid.UUID, claim: dict) -> bool:
    """Fresh claim: a held `needs_review` run -> `running`, stamped. A single
    conditional UPDATE, so of two simultaneous callers exactly one gets a row."""
    claimed = await session.execute(
        update(WorkflowRun)
        .where(WorkflowRun.id == run_id, WorkflowRun.status == "needs_review", _HELD)
        .values(status="running", result=_stamp(claim))
        .returning(WorkflowRun.id)
    )
    return claimed.scalar_one_or_none() is not None


async def reclaim_stale_release(session: AsyncSession, run_id: uuid.UUID, claim: dict) -> bool:
    """Take over a `running` release whose claim has outlived the TTL. The
    staleness test is part of the UPDATE's WHERE, so a claim that is refreshed
    (or completed) between a caller's read and its write no longer matches and
    the takeover is refused rather than duplicated."""
    taken = await session.execute(
        update(WorkflowRun)
        .where(
            WorkflowRun.id == run_id,
            WorkflowRun.status == "running",
            _HELD,
            cast(_CLAIMED_AT, DateTime(timezone=True)) < stale_cutoff(),
        )
        .values(result=_stamp(claim))
        .returning(WorkflowRun.id)
    )
    return taken.scalar_one_or_none() is not None


async def find_stale_release_ids(session: AsyncSession) -> list[uuid.UUID]:
    rows = await session.execute(
        select(WorkflowRun.id).where(
            WorkflowRun.status == "running",
            _HELD,
            cast(_CLAIMED_AT, DateTime(timezone=True)) < stale_cutoff(),
        )
    )
    return list(rows.scalars().all())
