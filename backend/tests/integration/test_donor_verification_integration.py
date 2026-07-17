"""End-to-end Donor Verification tests against the real stack: live LLM call,
real CRM MCP server (streamable-HTTP), real Postgres, real checkpointer.

Requires: docker compose up -d postgres redis mcp-crm; python scripts/seed_db.py;
ANTHROPIC_API_KEY set in the repo-root .env.
"""

import pytest
from sqlalchemy import select

from app.db.models import AgentAuditLog, WorkflowRun
from app.db.session import db_session
from app.graph.builder import build_graph
from tests.conftest import seed_uuid

pytestmark = pytest.mark.integration


async def _run(external_id: str) -> tuple[dict, str]:
    """Creates a real workflow_runs row (agent_audit_log FKs into it, same as the
    Celery task in production will do) and runs the graph using its id as both
    workflow_run_id and the LangGraph thread_id."""
    donor_id = str(seed_uuid("donor", external_id))
    async with db_session() as session:
        run = WorkflowRun(donor_id=donor_id)
        session.add(run)
        await session.commit()
        await session.refresh(run)
        workflow_run_id = str(run.id)

    async with build_graph() as graph:
        result = await graph.ainvoke(
            {"workflow_run_id": workflow_run_id, "donor_id": donor_id, "campaign_id": None},
            config={"configurable": {"thread_id": workflow_run_id}},
        )
    return result["verification_result"], workflow_run_id


async def test_clean_donor_is_eligible_with_high_confidence():
    verdict, _ = await _run("d-0001")
    assert verdict["eligible"] is True
    assert verdict["confidence"] > 0.85
    assert verdict["is_duplicate"] is False
    assert verdict["is_suspicious"] is False


async def test_do_not_contact_donor_is_ineligible():
    verdict, _ = await _run("d-0004")
    assert verdict["eligible"] is False
    assert verdict["confidence"] > 0.85


async def test_suppressed_donor_is_ineligible():
    verdict, _ = await _run("d-0005")
    assert verdict["eligible"] is False


async def test_duplicate_pair_flagged():
    verdict, _ = await _run("d-0002")
    assert verdict["is_duplicate"] is True
    assert verdict["duplicate_of_donor_id"] == str(seed_uuid("donor", "d-0003"))


async def test_suspicious_donation_flagged_for_review():
    verdict, workflow_run_id = await _run("d-0006")
    # get_llm() deliberately doesn't pin temperature (see core/llm.py), so the
    # categorical is_suspicious flag can occasionally vary run-to-run; the
    # operationally meaningful, stable signal is that confidence crosses the
    # human-review threshold — that's what Phase 2's routing will act on.
    assert verdict["confidence"] < 0.80  # CONFIDENCE_THRESHOLD_DONOR_VERIFICATION

    # explainability: every node should have left a real audit trail
    async with db_session() as session:
        rows = (
            (
                await session.execute(
                    select(AgentAuditLog)
                    .where(AgentAuditLog.workflow_run_id == workflow_run_id)
                    .order_by(AgentAuditLog.created_at)
                )
            )
            .scalars()
            .all()
        )

    steps = [row.step for row in rows]
    assert steps == ["fetch_core_data", "gather_context", "synthesize_verdict"]
    assert rows[-1].confidence is not None
    assert rows[-1].reasoning
    assert rows[1].tool_calls  # gather_context recorded its MCP tool calls
