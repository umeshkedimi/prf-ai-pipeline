"""Durable agent-run state against a real DB: steps persist and dedupe, the approval
claim is atomic, and a terminal outcome cannot be overwritten."""

import asyncio
import uuid

import pytest
from sqlalchemy import delete, select

from app.db.models import AgentRun, AgentStep, Campaign
from app.db.session import db_session
from app.harness import store
from app.harness.budget import Budget
from app.harness.gateway import AuditRecord, Outcome
from app.harness.tools import Tier

pytestmark = pytest.mark.integration


@pytest.fixture
async def run_id():
    async with db_session() as s:
        c = Campaign(name=f"store-test-{uuid.uuid4().hex[:6]}")
        s.add(c)
        await s.commit()
        cid = c.id
    rid = await store.create_agent_run(cid, "prepare for mailing", Budget())
    yield rid
    async with db_session() as s:
        await s.execute(delete(AgentStep).where(AgentStep.agent_run_id == rid))
        await s.execute(delete(AgentRun).where(AgentRun.id == rid))
        await s.execute(delete(Campaign).where(Campaign.id == cid))
        await s.commit()


async def test_steps_persist_and_a_retried_write_does_not_duplicate(run_id):
    sink = store.make_audit_sink(run_id)
    rec = AuditRecord(1, "profile_campaign", Tier.READ, {}, Outcome.OK, {"total": 5}, 12)
    await sink(rec)
    await sink(rec)
    async with db_session() as s:
        rows = (await s.execute(select(AgentStep).where(AgentStep.agent_run_id == run_id))).scalars().all()
    assert len(rows) == 1 and rows[0].observation == {"total": 5} and rows[0].tier == "read"


async def test_approval_can_be_claimed_exactly_once(run_id):
    assert await store.request_approval(run_id, {"tool": "submit_print_batch", "args": {}})
    results = await asyncio.gather(store.claim_approval(run_id), store.claim_approval(run_id))
    assert sorted(r is not None for r in results) == [False, True]
    winner = next(r for r in results if r is not None)
    assert winner["tool"] == "submit_print_batch"


async def test_claim_without_a_pending_approval_returns_none(run_id):
    assert await store.claim_approval(run_id) is None


async def test_a_terminal_status_cannot_be_overwritten(run_id):
    assert await store.finish_run(run_id, "stopped")
    assert not await store.finish_run(run_id, "completed", {"ready": 3})
    async with db_session() as s:
        assert (await s.get(AgentRun, run_id)).status == "stopped"


async def test_budget_usage_is_saved(run_id):
    b = Budget()
    b.charge_step()
    b.charge_tokens(500)
    await store.save_budget(run_id, b)
    async with db_session() as s:
        saved = (await s.get(AgentRun, run_id)).budget
    assert saved["steps"] == 1 and saved["tokens"] == 500
