"""Tests for the generalized human_review node, which serves two review stages
(address and recommendation) from a single node. Patches interrupt() so the
decision can be injected directly without running a real graph."""

import pytest

from app.agents.human_review import agent as agent_module
from app.graph import builder as builder_module


@pytest.fixture(autouse=True)
def _mock_audit_log(monkeypatch):
    calls: list[dict] = []

    async def fake_write_audit_log(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(agent_module, "write_audit_log", fake_write_audit_log)
    return calls


def _patch_interrupt(monkeypatch, decision):
    """Capture the payload the node would have paused with, and return the
    decision as if a reviewer had submitted it."""
    captured = {}

    def fake_interrupt(payload):
        captured["payload"] = payload
        return decision

    monkeypatch.setattr(agent_module, "interrupt", fake_interrupt)
    return captured


async def test_address_stage_modify_sets_new_address_and_marks_deliverable(monkeypatch, _mock_audit_log):
    captured = _patch_interrupt(
        monkeypatch, {"action": "modify", "updated_address": "1225 Pine St", "reviewer": "demo"}
    )
    state = {
        "workflow_run_id": "wf-1",
        "address_result": {"deliverable": False, "confidence": 0.6},
    }
    result = await agent_module.human_review(state)

    assert captured["payload"]["stage"] == "address"
    assert captured["payload"]["reason"] == "address_confidence_below_threshold"
    assert result["address_result"]["updated_address"] == "1225 Pine St"
    assert result["address_result"]["deliverable"] is True
    assert result["address_result"]["human_reviewed"] is True


async def test_address_stage_approve_does_not_inflate_confidence(monkeypatch, _mock_audit_log):
    """Approving a low-confidence assessment means accepting it as-is, not
    asserting new certainty — the audit trail must stay honest."""
    _patch_interrupt(monkeypatch, {"action": "approve", "reviewer": "demo"})
    state = {"workflow_run_id": "wf-1", "address_result": {"deliverable": True, "confidence": 0.62}}

    result = await agent_module.human_review(state)

    assert result["address_result"]["confidence"] == 0.62
    assert result["address_result"]["human_reviewed"] is True


async def test_recommendation_stage_is_detected_and_modify_caps_the_ask(monkeypatch, _mock_audit_log):
    captured = _patch_interrupt(
        monkeypatch,
        {"action": "modify", "updated_ask_amount": 500.0, "reviewer": "demo", "notes": "capped"},
    )
    state = {
        "workflow_run_id": "wf-1",
        "address_result": {"deliverable": True, "confidence": 0.95},
        "recommendation_result": {"recommended_ask": 5000.0, "confidence": 0.9},
    }
    result = await agent_module.human_review(state)

    assert captured["payload"]["stage"] == "recommendation"
    assert captured["payload"]["reason"] == "recommendation_requires_approval"
    assert result["recommendation_result"]["recommended_ask"] == 500.0
    assert result["recommendation_result"]["human_reviewed"] is True
    # the address result must be left completely untouched by this stage
    assert "address_result" not in result


async def test_recommendation_stage_reject_zeroes_the_ask(monkeypatch, _mock_audit_log):
    _patch_interrupt(monkeypatch, {"action": "reject", "reviewer": "demo"})
    state = {
        "workflow_run_id": "wf-1",
        "recommendation_result": {"recommended_ask": 5000.0, "confidence": 0.9},
    }
    result = await agent_module.human_review(state)

    assert result["recommendation_result"]["recommended_ask"] == 0.0
    assert result["recommendation_result"]["human_reviewed"] is True


async def test_audit_row_records_stage_reviewer_and_action(monkeypatch, _mock_audit_log):
    _patch_interrupt(monkeypatch, {"action": "reject", "reviewer": "alex", "notes": "vacant"})
    state = {"workflow_run_id": "wf-1", "address_result": {"deliverable": False, "confidence": 0.3}}

    await agent_module.human_review(state)

    audit = _mock_audit_log[0]
    assert audit["step"] == "human_review"
    assert audit["input_snapshot"]["stage"] == "address"
    assert audit["reasoning"] == "vacant"
    assert audit["source_refs"][0] == {"reviewer": "alex", "action": "reject", "stage": "address"}


# --- routing: the other half of the two-stage design ---


def test_address_review_continues_into_recommendation_when_deliverable():
    state = {"address_result": {"deliverable": True, "human_reviewed": True}}
    assert builder_module.route_after_human_review(state) == "compute_rfm"


def test_address_review_stops_when_address_is_rejected():
    """Nothing to mail — don't spend an LLM call recommending an ask."""
    state = {"address_result": {"deliverable": False, "human_reviewed": True}}
    assert builder_module.route_after_human_review(state) == "__end__"


def test_recommendation_review_is_terminal():
    state = {
        "address_result": {"deliverable": True},
        "recommendation_result": {"recommended_ask": 500.0, "human_reviewed": True},
    }
    assert builder_module.route_after_human_review(state) == "__end__"


def test_major_gift_ask_routes_to_human_review():
    state = {"recommendation_result": {"recommended_ask": 5000.0, "confidence": 0.95}}
    assert builder_module.route_after_recommendation(state) == "human_review"


def test_low_confidence_alone_does_not_block_the_pipeline():
    """Confidence is a non-deterministic prediction about a future gift, so it
    must not decide a blocking pause — it only marks the run needs_review."""
    state = {"recommendation_result": {"recommended_ask": 100.0, "confidence": 0.4}}
    assert builder_module.route_after_recommendation(state) == "__end__"


def test_major_gift_ask_pauses_even_at_high_confidence():
    state = {"recommendation_result": {"recommended_ask": 2000.0, "confidence": 0.99}}
    assert builder_module.route_after_recommendation(state) == "human_review"


def test_modest_confident_recommendation_completes():
    state = {"recommendation_result": {"recommended_ask": 225.0, "confidence": 0.92}}
    assert builder_module.route_after_recommendation(state) == "__end__"


def test_confident_deliverable_address_flows_into_recommendation():
    state = {"address_result": {"deliverable": True, "confidence": 0.95}}
    assert builder_module.route_after_address(state) == "compute_rfm"


def test_confidently_undeliverable_address_ends_without_review():
    state = {"address_result": {"deliverable": False, "confidence": 0.95}}
    assert builder_module.route_after_address(state) == "__end__"


# --- schema drift: the API body is what actually reaches the graph ---


def test_review_request_schema_matches_the_agent_decision_schema():
    """The endpoint passes ReviewDecisionCreate.model_dump() straight into
    Command(resume=...), so any field the agent expects but the request model
    lacks is silently dropped — which once let a reviewer's capped ask amount
    vanish with a cheerful HTTP 202. Keep the two field sets identical."""
    from app.agents.human_review.schemas import HumanReviewDecision
    from app.schemas.workflow import ReviewDecisionCreate

    assert set(ReviewDecisionCreate.model_fields) == set(HumanReviewDecision.model_fields)


def test_review_request_carries_an_updated_ask_amount():
    from app.schemas.workflow import ReviewDecisionCreate

    payload = ReviewDecisionCreate(action="modify", updated_ask_amount=500.0, reviewer="demo")
    assert payload.model_dump()["updated_ask_amount"] == 500.0
