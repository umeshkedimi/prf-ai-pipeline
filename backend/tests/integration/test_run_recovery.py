"""Stalled-run recovery against a real DB: only genuinely stalled pipeline runs
are selected, takeover is a compare-and-swap, and recovery re-enqueues once."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.core.config import get_settings
from app.db.models import WorkflowRun
from app.workers import run_recovery, tasks
from tests.conftest import seed_uuid

pytestmark = pytest.mark.integration

TTL = get_settings().run_stall_ttl_seconds


@pytest.fixture
async def make_run(db_session):
    created: list = []

    async def _make(*, status="running", beat_age=None, result=None):
        # `result` is only passed when set: SQLAlchemy stores an explicit None as
        # JSON null rather than SQL NULL, and a real mid-run row never has it set.
        extra = {} if result is None else {"result": result}
        run = WorkflowRun(
            donor_id=seed_uuid("donor", "d-0001"),
            status=status,
            heartbeat_at=None if beat_age is None else datetime.now(UTC) - timedelta(seconds=beat_age),
            **extra,
        )
        db_session.add(run)
        await db_session.commit()
        created.append(run.id)
        return run.id

    yield _make
    await db_session.rollback()
    await db_session.execute(delete(WorkflowRun).where(WorkflowRun.id.in_(created)))
    await db_session.commit()


async def test_only_a_running_run_with_a_quiet_heartbeat_is_stalled(db_session, make_run):
    stalled = await make_run(beat_age=TTL + 60)
    fresh = await make_run(beat_age=5)
    no_beat = await make_run(beat_age=None)  # predates the column: can't tell
    paused = await make_run(status="awaiting_review", beat_age=TTL + 60)
    release = await make_run(beat_age=TTL + 60, result={"pdf_generation": {"held": True}})

    ids = set(await run_recovery.find_stalled_run_ids(db_session))

    assert stalled in ids
    assert not ids & {fresh, no_beat, paused, release}


async def test_takeover_is_a_compare_and_swap(db_session, make_run):
    rid = await make_run(beat_age=TTL + 60)
    assert await run_recovery.reclaim_stalled_run(db_session, rid) is True
    await db_session.commit()
    # The takeover refreshed the heartbeat, so a second recoverer loses.
    assert await run_recovery.reclaim_stalled_run(db_session, rid) is False


async def test_recovery_re_enqueues_a_stalled_run_exactly_once(make_run, monkeypatch):
    stalled = await make_run(beat_age=TTL + 60)
    fresh = await make_run(beat_age=5)
    calls: list[tuple] = []
    monkeypatch.setattr(tasks.continue_stalled_run, "delay", lambda *a: calls.append(a))

    await tasks._recover_stalled_runs()
    assert (str(stalled),) in calls and (str(fresh),) not in calls

    calls.clear()
    await tasks._recover_stalled_runs()  # heartbeat was refreshed by the takeover
    assert (str(stalled),) not in calls
