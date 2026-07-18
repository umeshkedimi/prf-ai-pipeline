"""End-to-end tests for the chained Donor Verification -> Address Intelligence
-> Human Review graph against the real stack: live LLM calls, both real MCP
servers, real Postgres, real checkpointer.

Requires: docker compose up -d postgres redis mcp-crm mcp-address;
python scripts/seed_db.py; ANTHROPIC_API_KEY set in the repo-root .env.
"""

import pytest
from langgraph.types import Command
from sqlalchemy import select

from app.db.models import AgentAuditLog, WorkflowRun
from app.db.session import db_session
from app.graph.builder import build_graph
from tests.conftest import seed_uuid

pytestmark = pytest.mark.integration


async def _create_run(external_id: str) -> tuple[str, str]:
    donor_id = str(seed_uuid("donor", external_id))
    async with db_session() as session:
        run = WorkflowRun(donor_id=donor_id)
        session.add(run)
        await session.commit()
        await session.refresh(run)
        workflow_run_id = str(run.id)
    return donor_id, workflow_run_id


async def _audit_steps(workflow_run_id: str) -> list[str]:
    async with db_session() as session:
        result = await session.execute(
            select(AgentAuditLog.step)
            .where(AgentAuditLog.workflow_run_id == workflow_run_id)
            .order_by(AgentAuditLog.created_at)
        )
        return list(result.scalars().all())


async def test_ineligible_donor_never_reaches_address_intelligence():
    donor_id, workflow_run_id = await _create_run("d-0004")  # do-not-contact

    async with build_graph() as graph:
        result = await graph.ainvoke(
            {"workflow_run_id": workflow_run_id, "donor_id": donor_id, "campaign_id": None},
            config={"configurable": {"thread_id": workflow_run_id}},
            durability="sync",
        )

    assert result["verification_result"]["eligible"] is False
    assert result.get("address_result") is None
    assert "__interrupt__" not in result
    assert await _audit_steps(workflow_run_id) == ["fetch_core_data", "gather_context", "synthesize_verdict"]


async def test_eligible_clean_donor_completes_with_no_interrupt():
    donor_id, workflow_run_id = await _create_run("d-0001")  # clean

    async with build_graph() as graph:
        result = await graph.ainvoke(
            {"workflow_run_id": workflow_run_id, "donor_id": donor_id, "campaign_id": None},
            config={"configurable": {"thread_id": workflow_run_id}},
            durability="sync",
        )

    assert "__interrupt__" not in result
    assert result["verification_result"]["eligible"] is True
    assert result["address_result"]["confidence"] > 0.85
    steps = await _audit_steps(workflow_run_id)
    assert steps == [
        "fetch_core_data",
        "gather_context",
        "synthesize_verdict",
        "verify_address",
        "assess_and_normalize",
    ]


async def test_low_confidence_address_pauses_then_resumes_cleanly():
    donor_id, workflow_run_id = await _create_run("d-0010")  # vacant, no forwarding
    config = {"configurable": {"thread_id": workflow_run_id}}

    async with build_graph() as graph:
        interrupted = await graph.ainvoke(
            {"workflow_run_id": workflow_run_id, "donor_id": donor_id, "campaign_id": None},
            config=config,
            durability="sync",
        )

        assert "__interrupt__" in interrupted
        payload = interrupted["__interrupt__"][0].value
        assert payload["reason"] == "address_confidence_below_threshold"
        assert payload["address_result"]["deliverable"] is False

        steps_paused = await _audit_steps(workflow_run_id)
        assert steps_paused == [
            "fetch_core_data",
            "gather_context",
            "synthesize_verdict",
            "verify_address",
            "assess_and_normalize",
        ]

        decision = {"action": "reject", "updated_address": None, "reviewer": "integration-test", "notes": "confirmed vacant"}
        resumed = await graph.ainvoke(Command(resume=decision), config=config, durability="sync")

    assert "__interrupt__" not in resumed
    assert resumed["human_review_decision"]["action"] == "reject"
    assert resumed["address_result"]["deliverable"] is False
    assert resumed["address_result"]["human_reviewed"] is True

    # verification + address steps should not have re-run — only human_review added
    steps_final = await _audit_steps(workflow_run_id)
    assert steps_final == [
        "fetch_core_data",
        "gather_context",
        "synthesize_verdict",
        "verify_address",
        "assess_and_normalize",
        "human_review",
    ]
