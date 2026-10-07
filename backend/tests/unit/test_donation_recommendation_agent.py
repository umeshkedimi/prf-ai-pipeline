"""recommend_ask is deterministic end to end -- RFM, ladder and rung -- so these tests
mock only the audit log and the CRM tool. No LLM and no retriever are involved."""

import json

import pytest

from app.agents.donation_recommendation import agent as agent_module


@pytest.fixture(autouse=True)
def _mock_audit_log(monkeypatch):
    calls: list[dict] = []

    async def fake_write_audit_log(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(agent_module, "write_audit_log", fake_write_audit_log)
    return calls


class FakeTool:
    def __init__(self, result):
        self._result = result
        self.calls: list[dict] = []

    async def ainvoke(self, args):
        self.calls.append(args)
        return self._result


HISTORY = [
    {"donation_date": "2026-08-01", "amount": 150.0},
    {"donation_date": "2025-12-01", "amount": 100.0},
]


async def test_recommend_ask_reuses_history_from_state_and_never_calls_the_crm(monkeypatch, _mock_audit_log):
    async def boom():
        raise AssertionError("CRM must not be re-queried when state already has the history")

    monkeypatch.setattr(agent_module, "get_crm_tools", boom)
    result = await agent_module.recommend_ask(
        {"workflow_run_id": "wf", "donor_id": "d", "donation_history": HISTORY}
    )
    rec = result["recommendation_result"]
    assert rec["recommended_ask"] in rec["ask_ladder"]
    assert rec["sources"] == [] and rec["rationale"]
    audit = _mock_audit_log[0]
    assert audit["step"] == "recommend_ask" and "model" not in audit and audit["confidence"] == rec["confidence"]


async def test_recommend_ask_falls_back_to_the_crm_when_history_is_absent(monkeypatch):
    tool = FakeTool(json.dumps([{"donation_date": "2026-08-01", "amount": 200.0}]))

    async def tools():
        return {"get_donation_history": tool}

    monkeypatch.setattr(agent_module, "get_crm_tools", tools)
    result = await agent_module.recommend_ask({"workflow_run_id": "wf", "donor_id": "d-9"})
    assert tool.calls == [{"donor_id": "d-9"}]
    assert result["recommendation_result"]["frequency"] == 1


async def test_recommend_ask_is_identical_on_every_run(monkeypatch):
    state = {"workflow_run_id": "wf", "donor_id": "d", "donation_history": HISTORY}
    first = await agent_module.recommend_ask(state)
    second = await agent_module.recommend_ask(state)
    assert first == second  # the property the LLM version could not offer
