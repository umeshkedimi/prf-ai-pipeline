"""enforce_eligibility: the CRM's do_not_contact / suppression flags force
ineligibility in code, whatever the model said."""

import pytest

from app.agents.donor_verification import agent as agent_module
from app.agents.donor_verification.eligibility import blocking_flags, enforce_eligibility
from app.agents.donor_verification.schemas import VerificationResult
from app.graph.builder import route_after_verification
from langgraph.graph import END


def _verdict(eligible=True, confidence=0.95):
    return {"eligible": eligible, "confidence": confidence, "reason": "looks fine", "reasoning": []}


@pytest.mark.parametrize("flag", ["do_not_contact", "is_suppressed"])
def test_a_blocking_flag_forces_ineligible_even_if_the_model_said_eligible(flag):
    verdict, corrections = enforce_eligibility({flag: True}, _verdict(eligible=True))
    assert verdict["eligible"] is False
    assert flag in verdict["reason"] and "looks fine" in verdict["reason"]
    assert len(corrections) == 1 and flag in corrections[0]


def test_confidence_is_not_changed_by_the_correction():
    verdict, _ = enforce_eligibility({"do_not_contact": True}, _verdict(confidence=0.95))
    assert verdict["confidence"] == 0.95


def test_no_correction_when_the_model_already_complied():
    original = _verdict(eligible=False)
    verdict, corrections = enforce_eligibility({"do_not_contact": True}, original)
    assert verdict == original and corrections == []


def test_the_guard_never_promotes_an_ineligible_verdict():
    """Only the two flags are hard rules; any other model ineligibility stands."""
    original = _verdict(eligible=False)
    verdict, corrections = enforce_eligibility({"do_not_contact": False}, original)
    assert verdict["eligible"] is False and corrections == []


def test_clean_donor_is_untouched():
    original = _verdict(eligible=True)
    assert enforce_eligibility({}, original) == (original, [])
    assert blocking_flags({"do_not_contact": False, "is_suppressed": False}) == []


def test_original_verdict_is_not_mutated():
    original = _verdict(eligible=True)
    enforce_eligibility({"is_suppressed": True}, original)
    assert original["eligible"] is True


def test_forced_ineligible_routes_to_end():
    verdict, _ = enforce_eligibility({"do_not_contact": True}, _verdict(eligible=True))
    assert route_after_verification({"verification_result": verdict}) == END


async def test_synthesize_verdict_applies_the_guard_and_audits_the_raw_output(monkeypatch):
    audit: list[dict] = []

    async def fake_invoke(llm, schema, messages):
        return VerificationResult(eligible=True, confidence=0.9, reason="clean"), {}

    async def fake_audit(**kwargs):
        audit.append(kwargs)

    monkeypatch.setattr(agent_module, "ainvoke_structured", fake_invoke)
    monkeypatch.setattr(agent_module, "get_llm", lambda: object())
    monkeypatch.setattr(agent_module, "write_audit_log", fake_audit)

    state = {"workflow_run_id": "r", "donor_profile": {"do_not_contact": True}}
    update = await agent_module.synthesize_verdict(state)

    assert update["verification_result"]["eligible"] is False
    out = audit[0]["output"]
    assert out["model_output_raw"]["eligible"] is True  # what the eval scores
    assert out["deterministic_corrections"]


async def test_synthesize_verdict_records_no_raw_output_when_nothing_was_corrected(monkeypatch):
    audit: list[dict] = []

    async def fake_invoke(llm, schema, messages):
        return VerificationResult(eligible=True, confidence=0.9, reason="clean"), {}

    async def fake_audit(**kwargs):
        audit.append(kwargs)

    monkeypatch.setattr(agent_module, "ainvoke_structured", fake_invoke)
    monkeypatch.setattr(agent_module, "get_llm", lambda: object())
    monkeypatch.setattr(agent_module, "write_audit_log", fake_audit)

    await agent_module.synthesize_verdict({"workflow_run_id": "r", "donor_profile": {}})
    assert "model_output_raw" not in audit[0]["output"]
