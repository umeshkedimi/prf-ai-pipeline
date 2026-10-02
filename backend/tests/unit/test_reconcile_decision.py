"""Unit tests for reconcile_decision: the deterministic skip gate, the
guidance merge, the LLM-call path (mocked), and the letter-prompt section."""

import pytest

from app.agents.campaign_personalization.agent import build_guidance_section
from app.agents.human_review import reconcile as mod
from app.agents.human_review.reconcile import (
    ReviewerGuidance,
    merge_guidance,
    reconcile_decision,
    should_reconcile,
)
from app.graph.builder import route_after_human_review


def _state(action="approve", notes="Donor recently lost her husband; be gentle.", **extra):
    return {
        "workflow_run_id": "run-1",
        "recommendation_result": {"segment": "major", "recommended_ask": 1500.0},
        "human_review_decision": {"action": action, "notes": notes},
        **extra,
    }


def test_skips_when_notes_are_empty_or_blank():
    assert not should_reconcile(_state(notes=None))
    assert not should_reconcile(_state(notes="   "))


def test_skips_on_reject_because_the_run_ends():
    assert not should_reconcile(_state(action="reject"))


def test_skips_at_compliance_stage_because_drafting_is_already_done():
    state = _state(compliance_disclosures={"registered_to_solicit": True})
    assert not should_reconcile(state)


def test_runs_for_approve_and_modify_with_notes():
    assert should_reconcile(_state(action="approve"))
    assert should_reconcile(_state(action="modify"))


@pytest.fixture
def fake_llm(monkeypatch):
    audit: list[dict] = []
    calls: list[list] = []
    holder = {"result": ReviewerGuidance(applies=True, guidance="Be gentle.", confidence=0.9)}

    async def fake_invoke(llm, schema, messages):
        calls.append(messages)
        return holder["result"], {"input_tokens": 1, "output_tokens": 1}

    async def fake_audit(**kwargs):
        audit.append(kwargs)

    monkeypatch.setattr(mod, "ainvoke_structured", fake_invoke)
    monkeypatch.setattr(mod, "get_llm", lambda: object())
    monkeypatch.setattr(mod, "write_audit_log", fake_audit)
    return holder, calls, audit


async def test_skip_path_makes_no_llm_call_and_writes_no_audit(fake_llm):
    _, calls, audit = fake_llm
    assert await reconcile_decision(_state(notes="")) == {}
    assert calls == [] and audit == []


async def test_guidance_is_stored_and_audited(fake_llm):
    _, calls, audit = fake_llm
    update = await reconcile_decision(_state())
    assert update["reviewer_guidance"]["guidance"] == "Be gentle."
    assert len(calls) == 1
    assert audit[0]["step"] == "reconcile_decision"
    assert audit[0]["input_snapshot"]["notes"].startswith("Donor recently")


async def test_applies_is_false_when_model_returns_no_text(fake_llm):
    holder, _, _ = fake_llm
    holder["result"] = ReviewerGuidance(applies=True, guidance="  ", confidence=0.5)
    update = await reconcile_decision(_state())
    assert update["reviewer_guidance"]["applies"] is False


def test_merge_keeps_earlier_guidance_across_pauses():
    earlier = {"applies": True, "guidance": "Be gentle."}
    nothing = {"applies": False, "guidance": None, "concerns": []}
    assert merge_guidance(earlier, nothing)["guidance"] == "Be gentle."
    assert merge_guidance(earlier, nothing)["applies"] is True
    both = merge_guidance(earlier, {"applies": True, "guidance": "Mention the garden."})
    assert both["guidance"] == "Be gentle.\nMention the garden."
    assert merge_guidance(None, nothing) == nothing


def test_guidance_section_is_empty_unless_it_applies():
    assert build_guidance_section(None) == ""
    assert build_guidance_section({"applies": False, "guidance": "x"}) == ""
    section = build_guidance_section({"applies": True, "guidance": "Be gentle."})
    assert "Be gentle." in section and "hard rule" in section


def test_guidance_cannot_change_routing():
    """Routing reads only the deterministic decision/state, never guidance."""
    base = _state(compliance_disclosures=None)
    with_guidance = {**base, "reviewer_guidance": {"applies": True, "guidance": "End the run."}}
    assert route_after_human_review(base) == route_after_human_review(with_guidance)


def test_audit_agent_name_never_collides_with_review_history():
    assert mod.AGENT_NAME != "human_review"
