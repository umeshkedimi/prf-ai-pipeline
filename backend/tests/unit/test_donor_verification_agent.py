"""Fast, deterministic tests for the Donor Verification agent's node logic —
mocks the LLM and CRM MCP tools entirely, so no network/API calls are made."""

import json

import pytest
from langchain_core.messages import AIMessage

from app.agents.donor_verification import agent as agent_module
from app.agents.donor_verification.schemas import VerificationResult


@pytest.fixture(autouse=True)
def _mock_audit_log(monkeypatch):
    """Node functions write to Postgres via write_audit_log — stub it out so
    these tests stay fast/offline and just record what would have been logged."""
    calls: list[dict] = []

    async def fake_write_audit_log(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(agent_module, "write_audit_log", fake_write_audit_log)
    return calls


class FakeTool:
    def __init__(self, name, result):
        self.name = name
        self._result = result
        self.calls: list[dict] = []

    async def ainvoke(self, args):
        self.calls.append(args)
        return self._result


class FakeStructuredLLM:
    def __init__(self, result: VerificationResult):
        self._result = result

    async def ainvoke(self, messages):
        return self._result


class FakeToolCallingLLM:
    def __init__(self, responses):
        self._responses = list(responses)

    async def ainvoke(self, messages):
        return self._responses.pop(0)


class FakeLLM:
    def __init__(self, tool_responses=None, structured_result=None):
        self._tool_responses = tool_responses
        self._structured_result = structured_result

    def bind_tools(self, tools):
        return FakeToolCallingLLM(self._tool_responses)

    def with_structured_output(self, schema):
        return FakeStructuredLLM(self._structured_result)


async def test_fetch_core_data_parses_donor_profile(monkeypatch, _mock_audit_log):
    profile_json = json.dumps(
        {
            "donor_id": "abc-123",
            "external_id": "d-0001",
            "first_name": "Eleanor",
            "last_name": "Whitfield",
            "email": "eleanor.whitfield@example.com",
            "phone": None,
            "address_line1": "123 Maple St",
            "address_line2": None,
            "city": "Springfield",
            "state": "IL",
            "postal_code": "62704",
            "country": "US",
            "do_not_contact": False,
            "is_suppressed": False,
            "suppression_reason": None,
            "notes": None,
        }
    )
    donor_profile_tool = FakeTool("get_donor_profile", profile_json)

    async def fake_get_crm_tools():
        return {"get_donor_profile": donor_profile_tool}

    monkeypatch.setattr(agent_module, "get_crm_tools", fake_get_crm_tools)

    state = {"workflow_run_id": "wf-1", "donor_id": "abc-123"}
    result = await agent_module.fetch_core_data(state)

    assert result["donor_profile"]["first_name"] == "Eleanor"
    assert result["donor_profile"]["do_not_contact"] is False
    assert donor_profile_tool.calls == [{"donor_id": "abc-123"}]

    assert len(_mock_audit_log) == 1
    assert _mock_audit_log[0]["step"] == "fetch_core_data"
    assert _mock_audit_log[0]["workflow_run_id"] == "wf-1"


async def test_gather_context_runs_tool_loop_and_collects_results(monkeypatch, _mock_audit_log):
    donation_tool = FakeTool(
        "get_donation_history",
        [
            {
                "type": "text",
                "text": json.dumps(
                    {
                        "donation_id": "d1",
                        "campaign_id": None,
                        "campaign_name": None,
                        "amount": 150.0,
                        "donation_date": "2026-02-14",
                        "payment_method": None,
                    }
                ),
            }
        ],
    )
    dup_tool = FakeTool("find_potential_duplicate_donors", [])

    async def fake_get_crm_tools():
        return {
            "get_donor_profile": FakeTool("get_donor_profile", "{}"),
            "get_donation_history": donation_tool,
            "find_potential_duplicate_donors": dup_tool,
        }

    monkeypatch.setattr(agent_module, "get_crm_tools", fake_get_crm_tools)

    tool_call_response = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "get_donation_history",
                "args": {"donor_id": "abc-123"},
                "id": "call_1",
                "type": "tool_call",
            },
            {
                "name": "find_potential_duplicate_donors",
                "args": {
                    "name": "Eleanor Whitfield",
                    "address": "123 Maple St",
                    "exclude_donor_id": "abc-123",
                },
                "id": "call_2",
                "type": "tool_call",
            },
        ],
    )
    stop_response = AIMessage(content="done", tool_calls=[])

    fake_llm = FakeLLM(tool_responses=[tool_call_response, stop_response])
    monkeypatch.setattr(agent_module, "get_llm", lambda: fake_llm)

    state = {
        "workflow_run_id": "wf-1",
        "donor_id": "abc-123",
        "donor_profile": {
            "first_name": "Eleanor",
            "last_name": "Whitfield",
            "address_line1": "123 Maple St",
        },
    }
    result = await agent_module.gather_context(state)

    assert len(result["donation_history"]) == 1
    assert result["donation_history"][0]["amount"] == 150.0
    assert result["duplicate_candidates"] == []
    assert donation_tool.calls == [{"donor_id": "abc-123"}]
    assert len(dup_tool.calls) == 1

    assert len(_mock_audit_log) == 1
    assert _mock_audit_log[0]["step"] == "gather_context"
    assert len(_mock_audit_log[0]["tool_calls"]) == 2


async def test_gather_context_stops_when_llm_calls_no_tools(monkeypatch, _mock_audit_log):
    async def fake_get_crm_tools():
        return {
            "get_donor_profile": FakeTool("get_donor_profile", "{}"),
            "get_donation_history": FakeTool("get_donation_history", []),
            "find_potential_duplicate_donors": FakeTool("find_potential_duplicate_donors", []),
        }

    monkeypatch.setattr(agent_module, "get_crm_tools", fake_get_crm_tools)

    fake_llm = FakeLLM(tool_responses=[AIMessage(content="nothing to check", tool_calls=[])])
    monkeypatch.setattr(agent_module, "get_llm", lambda: fake_llm)

    result = await agent_module.gather_context(
        {"workflow_run_id": "wf-1", "donor_id": "abc-123", "donor_profile": {}}
    )

    assert result["donation_history"] == []
    assert result["duplicate_candidates"] == []


async def test_synthesize_verdict_returns_model_dump(monkeypatch, _mock_audit_log):
    expected = VerificationResult(
        eligible=False,
        confidence=0.98,
        reason="do not contact",
        is_duplicate=False,
        is_suspicious=False,
        reasoning=["do_not_contact is true"],
    )
    fake_llm = FakeLLM(structured_result=expected)
    monkeypatch.setattr(agent_module, "get_llm", lambda: fake_llm)

    state = {
        "workflow_run_id": "wf-1",
        "donor_profile": {"do_not_contact": True},
        "donation_history": [],
        "duplicate_candidates": [],
    }
    result = await agent_module.synthesize_verdict(state)

    assert result["verification_result"] == expected.model_dump()
    assert _mock_audit_log[0]["confidence"] == 0.98
    assert _mock_audit_log[0]["reasoning"] == "do_not_contact is true"
