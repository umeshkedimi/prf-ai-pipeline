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
    # a clean, deliverable address now flows all the way through the rest of
    # the chain: recommendation, personalization, compliance, PDF generation.
    # d-0001 is registered to solicit, so review_letter_compliance runs rather
    # than pausing a second time at gather_disclosures.
    rec = result["recommendation_result"]
    assert rec["recommended_ask"] in rec["ask_ladder"]
    assert rec["recommended_ask"] < 1000.0  # modest donor — no major-gift pause
    assert result["personalization_result"] is not None
    assert result["compliance_result"] is not None
    assert result["pdf_result"] is not None
    steps = await _audit_steps(workflow_run_id)
    assert steps == [
        "fetch_core_data",
        "gather_context",
        "synthesize_verdict",
        "verify_address",
        "assess_and_normalize",
        "compute_rfm",
        "recommend_ask",
        "personalize_letter",
        "gather_disclosures",
        "review_letter_compliance",
        "generate_pdf",
    ]


async def test_low_confidence_address_pauses_then_resumes_cleanly():
    """d-0009 is moved, with a forwarding address found at only moderate
    confidence — that 0.6 is a deterministic fixture value
    (mcp_servers/address/fixtures.py), not something the LLM invents, since
    assess_and_normalize's prompt hands it the number directly. That's what
    makes this donor a reliable pause case regardless of which model is
    behind LLM_PROVIDER, unlike d-0010 below."""
    donor_id, workflow_run_id = await _create_run("d-0009")  # moved, uncertain forwarding
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
        assert payload["stage"] == "address"
        # `moved` itself is an LLM judgment on top of the deterministic
        # verify_address flag, not guaranteed stable across models — the
        # confidence gate is the actual, reliable trigger being tested here.
        assert payload["under_review"]["confidence"] < 0.80

        steps_paused = await _audit_steps(workflow_run_id)
        assert steps_paused == [
            "fetch_core_data",
            "gather_context",
            "synthesize_verdict",
            "verify_address",
            "assess_and_normalize",
        ]

        decision = {
            "action": "reject",
            "updated_address": None,
            "reviewer": "integration-test",
            "notes": "could not confirm the forwarding address",
        }
        resumed = await graph.ainvoke(Command(resume=decision), config=config, durability="sync")

    assert "__interrupt__" not in resumed
    assert resumed["human_review_decision"]["action"] == "reject"
    assert resumed["address_result"]["deliverable"] is False
    assert resumed["address_result"]["human_reviewed"] is True

    # verification + address steps should not have re-run — only human_review added.
    # A rejected address ends the run: there's nothing to mail, so the pipeline
    # deliberately does not go on to recommend an ask.
    steps_final = await _audit_steps(workflow_run_id)
    assert steps_final == [
        "fetch_core_data",
        "gather_context",
        "synthesize_verdict",
        "verify_address",
        "assess_and_normalize",
        "human_review",
    ]
    assert resumed.get("recommendation_result") is None


async def test_confidently_vacant_address_ends_without_pausing_or_mailing():
    """d-0010 is vacant with no forwarding address to anchor a number to, so
    (unlike d-0009 above) the model has nothing but an unambiguous "vacant,
    nothing found" result to reason over — it reports high confidence rather
    than hedging, which is the correct call, not noise: route_after_address
    is explicitly designed so a confident-but-undeliverable address ends the
    run without a human pause, since there's nothing uncertain to review."""
    donor_id, workflow_run_id = await _create_run("d-0010")  # vacant, no forwarding

    async with build_graph() as graph:
        result = await graph.ainvoke(
            {"workflow_run_id": workflow_run_id, "donor_id": donor_id, "campaign_id": None},
            config={"configurable": {"thread_id": workflow_run_id}},
            durability="sync",
        )

    assert "__interrupt__" not in result
    assert result["address_result"]["deliverable"] is False
    assert result["address_result"]["confidence"] >= 0.80  # CONFIDENCE_THRESHOLD_ADDRESS_INTELLIGENCE
    assert result.get("recommendation_result") is None
    assert await _audit_steps(workflow_run_id) == [
        "fetch_core_data",
        "gather_context",
        "synthesize_verdict",
        "verify_address",
        "assess_and_normalize",
    ]


async def test_major_gift_ask_pauses_for_recommendation_review_then_resumes():
    """The graph's second interrupt trigger, on a different stage than address:
    d-0011 has a clean address (so it never hits address review) but a
    major-gift-sized ask ladder, which must pause for approval."""
    donor_id, workflow_run_id = await _create_run("d-0011")
    config = {"configurable": {"thread_id": workflow_run_id}}

    async with build_graph() as graph:
        interrupted = await graph.ainvoke(
            {"workflow_run_id": workflow_run_id, "donor_id": donor_id, "campaign_id": None},
            config=config,
            durability="sync",
        )

        assert "__interrupt__" in interrupted
        payload = interrupted["__interrupt__"][0].value
        assert payload["stage"] == "recommendation"
        assert payload["reason"] == "recommendation_requires_approval"
        assert payload["under_review"]["recommended_ask"] >= 1000.0

        # it got here without ever pausing on the address
        steps_paused = await _audit_steps(workflow_run_id)
        assert steps_paused == [
            "fetch_core_data",
            "gather_context",
            "synthesize_verdict",
            "verify_address",
            "assess_and_normalize",
            "compute_rfm",
            "recommend_ask",
        ]

        decision = {
            "action": "modify",
            "updated_ask_amount": 500.0,
            "reviewer": "integration-test",
            "notes": "capped pending gift-officer call",
        }
        resumed = await graph.ainvoke(Command(resume=decision), config=config, durability="sync")

    assert "__interrupt__" not in resumed
    rec = resumed["recommendation_result"]
    assert rec["recommended_ask"] == 500.0  # the human's number, not the model's
    assert rec["human_reviewed"] is True
    assert resumed["human_review_decision"]["action"] == "modify"
    # the (now positive) ask continues on into personalization, compliance,
    # and PDF generation — recommendation is no longer terminal since Phase 4.
    # d-0011 is registered to solicit, so it never pauses a second time.
    assert resumed["personalization_result"] is not None
    assert resumed["compliance_result"] is not None
    assert resumed["pdf_result"] is not None

    steps_final = await _audit_steps(workflow_run_id)
    assert steps_final == [
        "fetch_core_data",
        "gather_context",
        "synthesize_verdict",
        "verify_address",
        "assess_and_normalize",
        "compute_rfm",
        "recommend_ask",
        "human_review",
        "personalize_letter",
        "gather_disclosures",
        "review_letter_compliance",
        "generate_pdf",
    ]


async def test_anomalous_donation_does_not_inflate_the_ask():
    """d-0006's history is $60/$75 plus one $50,000 outlier that Donor
    Verification separately flags as suspicious. The ask ladder must anchor on
    the median instead, so the donor completes normally rather than being
    promoted into major-gift review on the strength of a bad record."""
    donor_id, workflow_run_id = await _create_run("d-0006")

    async with build_graph() as graph:
        result = await graph.ainvoke(
            {"workflow_run_id": workflow_run_id, "donor_id": donor_id, "campaign_id": None},
            config={"configurable": {"thread_id": workflow_run_id}},
            durability="sync",
        )

    assert "__interrupt__" not in result
    rec = result["recommendation_result"]
    assert rec["outlier_gift_excluded"] is True
    assert rec["anchor_gift"] == 75.0
    assert rec["segment"] == "active"
    assert max(rec["ask_ladder"]) < 1000.0
    assert rec["recommended_ask"] in rec["ask_ladder"]
