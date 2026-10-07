"""Stalled-agent detection and takeover against a real DB."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, update

from app.db.models import AgentRun, Campaign
from app.db.session import db_session
from app.harness import store
from app.harness.budget import Budget
from app.workers.agent_recovery import find_stalled_agent_run_ids, reclaim_stalled_agent_run

pytestmark = pytest.mark.integration


@pytest.fixture
async def make_run():
    created: list[tuple[uuid.UUID, uuid.UUID]] = []

    async def make(status="running", age_s=3600):
        async with db_session() as s:
            c = Campaign(name=f"rec-{uuid.uuid4().hex[:6]}")
            s.add(c)
            await s.commit()
            cid = c.id
        rid = await store.create_agent_run(cid, "g", Budget())
        async with db_session() as s:
            await s.execute(update(AgentRun).where(AgentRun.id == rid).values(
                status=status, heartbeat_at=datetime.now(UTC) - timedelta(seconds=age_s)))
            await s.commit()
        created.append((rid, cid))
        return rid

    yield make
    async with db_session() as s:
        for rid, cid in created:
            await s.execute(delete(AgentRun).where(AgentRun.id == rid))
            await s.execute(delete(Campaign).where(Campaign.id == cid))
        await s.commit()


async def test_only_a_quiet_running_agent_is_stalled(make_run):
    stale, fresh, paused = await make_run(), await make_run(age_s=1), await make_run("awaiting_approval")
    async with db_session() as s:
        found = set(await find_stalled_agent_run_ids(s))
    assert stale in found and fresh not in found and paused not in found


async def test_takeover_is_won_by_exactly_one_recoverer(make_run):
    rid = await make_run()

    async def attempt():
        async with db_session() as s:
            return await reclaim_stalled_agent_run(s, rid)

    results = await asyncio.gather(attempt(), attempt())
    assert sorted(results) == [False, True]
    async with db_session() as s:
        assert rid not in await find_stalled_agent_run_ids(s)  # heartbeat refreshed


async def test_the_budget_save_beats_the_heart(make_run):
    rid = await make_run()
    await store.save_budget(rid, Budget())
    async with db_session() as s:
        assert rid not in await find_stalled_agent_run_ids(s)
