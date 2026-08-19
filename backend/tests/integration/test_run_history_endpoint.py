"""Exercises the new GET /workflow/runs endpoint against a real DB: unlike
GET /workflow/reviews (scoped to awaiting_review/needs_review), this one
returns every status -- the general run-history browser -- and defaults to
newest-first instead of the queue's oldest-first FIFO ordering."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.api.v1.endpoints.workflow import list_runs
from app.db.models import WorkflowRun
from tests.conftest import seed_uuid

pytestmark = pytest.mark.integration


@pytest.fixture
async def history_runs(db_session):
    donor_id = seed_uuid("donor", "d-0001")
    # Postgres's now() is frozen for the whole transaction, so relying on
    # created_at's server_default would give all four rows an identical
    # timestamp within one commit -- explicit, strictly increasing values
    # are needed for the ordering assertion below to mean anything.
    base = datetime.now(UTC)
    runs = [
        WorkflowRun(donor_id=donor_id, status="completed", created_at=base),
        WorkflowRun(donor_id=donor_id, status="failed", created_at=base + timedelta(seconds=1)),
        WorkflowRun(donor_id=donor_id, status="awaiting_review", created_at=base + timedelta(seconds=2)),
        WorkflowRun(donor_id=donor_id, status="running", created_at=base + timedelta(seconds=3)),
    ]
    db_session.add_all(runs)
    await db_session.commit()
    for run in runs:
        await db_session.refresh(run)
    yield runs
    await db_session.execute(delete(WorkflowRun).where(WorkflowRun.id.in_([r.id for r in runs])))
    await db_session.commit()


async def test_lists_every_status_by_default(db_session, history_runs):
    completed, failed, awaiting, running = history_runs
    result = await list_runs(status=None, limit=200, offset=0, session=db_session)
    ids = {run.id for run in result}
    assert {completed.id, failed.id, awaiting.id, running.id} <= ids


async def test_filters_to_a_single_status(db_session, history_runs):
    completed, failed, _, _ = history_runs
    result = await list_runs(status="completed", limit=200, offset=0, session=db_session)
    ids = {run.id for run in result}
    assert completed.id in ids
    assert failed.id not in ids


async def test_defaults_to_newest_first(db_session, history_runs):
    result = await list_runs(status=None, limit=200, offset=0, session=db_session)
    ours = [run for run in result if run.id in {r.id for r in history_runs}]
    # history_runs was inserted in order completed, failed, awaiting, running --
    # newest-first should return that reversed.
    assert [run.id for run in ours] == [r.id for r in reversed(history_runs)]
