"""Persistence for agent runs. Each write opens its own short transaction and commits
immediately: a worker that dies mid-loop must leave every completed step on disk."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import text, update
from sqlalchemy.dialects.postgresql import insert

from app.db.models import AgentRun, AgentStep
from app.db.session import db_session
from app.harness.budget import Budget
from app.harness.gateway import AuditRecord, AuditSink

_TERMINAL = {"completed", "budget_exhausted", "stopped", "failed"}


async def create_agent_run(
    campaign_id: uuid.UUID, goal: str, budget: Budget, user_id: uuid.UUID | None = None
) -> uuid.UUID:
    async with db_session() as session:
        run = AgentRun(campaign_id=campaign_id, goal=goal, budget=budget.snapshot(), created_by_user_id=user_id)
        session.add(run)
        await session.commit()
        return run.id


def make_audit_sink(agent_run_id: uuid.UUID) -> AuditSink:
    async def sink(rec: AuditRecord) -> None:
        async with db_session() as session:
            # ON CONFLICT DO NOTHING: a retried write of the same (run, seq) is a no-op.
            await session.execute(
                insert(AgentStep)
                .values(
                    agent_run_id=agent_run_id, seq=rec.seq, tool=rec.tool,
                    tier=rec.tier.value if rec.tier else None, args=rec.args,
                    outcome=rec.outcome.value, observation=rec.observation, latency_ms=rec.latency_ms,
                )
                .on_conflict_do_nothing(constraint="uq_agent_steps_run_seq")
            )
            await session.commit()

    return sink


async def save_budget(agent_run_id: uuid.UUID, budget: Budget) -> None:
    async with db_session() as session:
        await session.execute(update(AgentRun).where(AgentRun.id == agent_run_id).values(budget=budget.snapshot()))
        await session.commit()


async def finish_run(agent_run_id: uuid.UUID, status: str, final_report: dict | None = None) -> bool:
    """Terminal transition. Only moves a non-terminal run, so a late writer cannot
    overwrite an outcome a human already set (e.g. `stopped`)."""
    assert status in _TERMINAL, status
    async with db_session() as session:
        res = await session.execute(
            update(AgentRun)
            .where(AgentRun.id == agent_run_id, AgentRun.status.not_in(_TERMINAL))
            .values(status=status, final_report=final_report, pending_approval=None,
                    completed_at=datetime.now(UTC))
        )
        await session.commit()
        return res.rowcount == 1


async def request_approval(agent_run_id: uuid.UUID, pending: dict) -> bool:
    async with db_session() as session:
        res = await session.execute(
            update(AgentRun)
            .where(AgentRun.id == agent_run_id, AgentRun.status == "running")
            .values(status="awaiting_approval", pending_approval=pending)
        )
        await session.commit()
        return res.rowcount == 1


async def claim_approval(agent_run_id: uuid.UUID) -> dict | None:
    """Atomically take the pending approval: one conditional UPDATE, so two reviewers
    answering at once cannot both resume the run. Returns the pending call to execute
    (or None if someone else got there first / nothing is pending). RETURNING would
    hand back the NEW value (NULL), so the old value is read in a locked subselect."""
    async with db_session() as session:
        row = (
            await session.execute(
                text(
                    """
                    UPDATE agent_runs AS r
                       SET status = 'running', pending_approval = NULL
                      FROM (SELECT id, pending_approval FROM agent_runs
                             WHERE id = :id AND status = 'awaiting_approval' FOR UPDATE) AS old
                     WHERE r.id = old.id
                 RETURNING old.pending_approval AS pending
                    """
                ),
                {"id": agent_run_id},
            )
        ).first()
        await session.commit()
    return None if row is None else (row.pending or {})
