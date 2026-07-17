"""End-to-end Donor Verification tests against the real stack: live LLM call,
real CRM MCP server (streamable-HTTP), real Postgres, real checkpointer.

Requires: docker compose up -d postgres redis mcp-crm; python scripts/seed_db.py;
ANTHROPIC_API_KEY set in the repo-root .env.
"""

import pytest

from app.graph.builder import build_graph
from tests.conftest import seed_uuid

pytestmark = pytest.mark.integration


async def _run(external_id: str) -> dict:
    donor_id = str(seed_uuid("donor", external_id))
    thread_id = f"integration-test-{external_id}"
    async with build_graph() as graph:
        result = await graph.ainvoke(
            {"workflow_run_id": thread_id, "donor_id": donor_id, "campaign_id": None},
            config={"configurable": {"thread_id": thread_id}},
        )
    return result["verification_result"]


async def test_clean_donor_is_eligible_with_high_confidence():
    verdict = await _run("d-0001")
    assert verdict["eligible"] is True
    assert verdict["confidence"] > 0.85
    assert verdict["is_duplicate"] is False
    assert verdict["is_suspicious"] is False


async def test_do_not_contact_donor_is_ineligible():
    verdict = await _run("d-0004")
    assert verdict["eligible"] is False
    assert verdict["confidence"] > 0.85


async def test_suppressed_donor_is_ineligible():
    verdict = await _run("d-0005")
    assert verdict["eligible"] is False


async def test_duplicate_pair_flagged():
    verdict = await _run("d-0002")
    assert verdict["is_duplicate"] is True
    assert verdict["duplicate_of_donor_id"] == str(seed_uuid("donor", "d-0003"))


async def test_suspicious_donation_flagged_for_review():
    verdict = await _run("d-0006")
    assert verdict["is_suspicious"] is True
    assert verdict["confidence"] < 0.80  # below CONFIDENCE_THRESHOLD_DONOR_VERIFICATION
