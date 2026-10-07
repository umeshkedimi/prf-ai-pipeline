"""Tests for the generalized human_review node, which serves two review stages
(address and recommendation) from a single node. Patches interrupt() so the
decision can be injected directly without running a real graph."""

import json

import pytest
from langgraph.graph import END

from app.agents.human_review import agent as agent_module
from app.graph import builder as builder_module


@pytest.fixture(autouse=True)
def _mock_audit_log(monkeypatch):
    calls: list[dict] = []

    async def fake_write_audit_log(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(agent_module, "write_audit_log", fake_write_audit_log)
    return calls


class _FakeCrmTool:
    def __init__(self, profile: dict):
        self.profile = profile
        self.calls: list[dict] = []

    async def ainvoke(self, args):
        self.calls.append(args)
        return json.dumps(self.profile)


@pytest.fixture(autouse=True)
def _mock_crm(monkeypatch):
    """human_review re-reads the donor's eligibility flags after a decision.
    Default: a clean donor. Tests that need a revoked donor mutate `.profile`."""
    tool = _FakeCrmTool({"do_not_contact": False, "is_suppressed": False})

    async def fake_get_crm_tools():
        return {"get_donor_profile": tool}

    monkeypatch.setattr(agent_module, "get_crm_tools", fake_get_crm_tools)
    return tool


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
    assert builder_module.route_after_human_review(state) == "recommend_ask"


def test_address_review_stops_when_address_is_rejected():
    """Nothing to mail — don't spend an LLM call recommending an ask."""
    state = {"address_result": {"deliverable": False, "human_reviewed": True}}
    assert builder_module.route_after_human_review(state) == "__end__"


def test_approved_recommendation_review_continues_to_personalization():
    state = {
        "address_result": {"deliverable": True},
        "recommendation_result": {
            "recommended_ask": 500.0,
            "human_reviewed": True,
        },
    }
    assert builder_module.route_after_human_review(state) == "personalize_letter"


def test_rejected_recommendation_review_is_terminal():
    """A rejected recommendation is zeroed out by human_review — nothing to
    personalize for a $0 letter."""
    state = {
        "address_result": {"deliverable": True},
        "recommendation_result": {"recommended_ask": 0.0, "human_reviewed": True},
    }
    assert builder_module.route_after_human_review(state) == "__end__"


def test_major_gift_ask_routes_to_human_review():
    state = {"recommendation_result": {"recommended_ask": 5000.0, "confidence": 0.95}}
    assert builder_module.route_after_recommendation(state) == "human_review"


def test_low_confidence_alone_does_not_block_the_pipeline():
    """Confidence is a non-deterministic prediction about a future gift, so it
    must not decide a blocking pause — it only marks the run needs_review."""
    state = {"recommendation_result": {"recommended_ask": 100.0, "confidence": 0.4}}
    assert builder_module.route_after_recommendation(state) == "personalize_letter"


def test_major_gift_ask_pauses_even_at_high_confidence():
    state = {"recommendation_result": {"recommended_ask": 2000.0, "confidence": 0.99}}
    assert builder_module.route_after_recommendation(state) == "human_review"


def test_modest_confident_recommendation_continues_to_personalization():
    state = {"recommendation_result": {"recommended_ask": 225.0, "confidence": 0.92}}
    assert builder_module.route_after_recommendation(state) == "personalize_letter"


def test_confident_deliverable_address_flows_into_recommendation():
    state = {"address_result": {"deliverable": True, "confidence": 0.95}}
    assert builder_module.route_after_address(state) == "recommend_ask"


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

    payload = ReviewDecisionCreate(
        action="modify", stage="recommendation", updated_ask_amount=500.0, reviewer="demo"
    )
    assert payload.model_dump()["updated_ask_amount"] == 500.0


# --- eligibility re-check on resume -------------------------------------------


def _rec_state(**extra):
    return {
        "workflow_run_id": "wf-1",
        "donor_id": "donor-1",
        "verification_result": {"eligible": True, "confidence": 0.9, "reason": "clean"},
        "recommendation_result": {"recommended_ask": 1500.0, "confidence": 0.7},
        **extra,
    }


async def test_clean_donor_passes_the_recheck_and_it_is_audited(monkeypatch, _mock_audit_log, _mock_crm):
    _patch_interrupt(monkeypatch, {"action": "approve", "reviewer": "demo"})
    result = await agent_module.human_review(_rec_state())

    assert "eligibility_revoked" not in result
    assert _mock_crm.calls == [{"donor_id": "donor-1"}]
    audit = _mock_audit_log[0]
    assert audit["output"]["eligibility_recheck"] == {"checked": True, "blocking_flags": []}
    assert audit["tool_calls"][0]["tool_name"] == "get_donor_profile"


@pytest.mark.parametrize("flag", ["do_not_contact", "is_suppressed"])
async def test_donor_who_opted_out_during_the_pause_revokes_eligibility(
    monkeypatch, _mock_audit_log, _mock_crm, flag
):
    _mock_crm.profile = {"do_not_contact": False, "is_suppressed": False, flag: True}
    _patch_interrupt(monkeypatch, {"action": "approve", "reviewer": "demo"})

    result = await agent_module.human_review(_rec_state())

    assert result["eligibility_revoked"]["blocking_flags"] == [flag]
    verdict = result["verification_result"]
    assert verdict["eligible"] is False and verdict["revoked_during_review"] is True
    assert flag in verdict["reason"]
    # The reviewer's decision is still recorded; the run just can't continue.
    assert result["human_review_decision"]["action"] == "approve"
    assert _mock_audit_log[0]["output"]["eligibility_recheck"]["blocking_flags"] == [flag]


async def test_reject_does_not_hit_the_crm_at_all(monkeypatch, _mock_audit_log, _mock_crm):
    """A reject ends the run anyway, and a CRM outage must not block it."""
    _patch_interrupt(monkeypatch, {"action": "reject", "reviewer": "demo"})
    await agent_module.human_review(_rec_state())
    assert _mock_crm.calls == []
    assert _mock_audit_log[0]["output"]["eligibility_recheck"] == {"checked": False}


def test_a_revoked_donor_ends_the_run_whatever_the_reviewer_decided():
    state = {
        "eligibility_revoked": {"blocking_flags": ["do_not_contact"]},
        "recommendation_result": {"recommended_ask": 1500.0},
    }
    assert builder_module.route_after_human_review(state) == END


def test_a_revoked_run_reads_as_completed_at_human_review():
    from app.core.config import get_settings
    from app.workers.tasks import _derive_terminal_status

    result = {
        "eligibility_revoked": {"blocking_flags": ["is_suppressed"]},
        "address_result": {"confidence": 0.5, "deliverable": True},  # would otherwise read needs_review
        "verification_result": {"eligible": False, "confidence": 0.9},
    }
    assert _derive_terminal_status(result, get_settings()) == ("completed", None, "human_review")


def test_reconcile_is_skipped_for_a_revoked_donor():
    from app.agents.human_review.reconcile import should_reconcile

    state = {
        "eligibility_revoked": {"blocking_flags": ["do_not_contact"]},
        "recommendation_result": {"segment": "major"},
        "human_review_decision": {"action": "approve", "notes": "be gentle"},
    }
    assert not should_reconcile(state)


def test_the_review_request_requires_a_stage():
    from pydantic import ValidationError

    from app.schemas.workflow import ReviewDecisionCreate

    with pytest.raises(ValidationError):
        ReviewDecisionCreate.model_validate({"action": "approve"})
