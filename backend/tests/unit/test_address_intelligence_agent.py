"""Fast, deterministic tests for the Address Intelligence agent's node logic —
mocks the LLM and Address MCP tools entirely, so no network/API calls are made."""

import json

import pytest
from langchain_core.messages import AIMessage

from app.agents.address_intelligence import agent as agent_module
from app.agents.address_intelligence.schemas import AddressResult


@pytest.fixture(autouse=True)
def _mock_audit_log(monkeypatch):
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
    """Mirrors include_raw=True: the parsed object alongside the AIMessage that
    carries usage_metadata, which is what token accounting reads."""

    def __init__(self, result: AddressResult):
        self._result = result

    async def ainvoke(self, messages):
        raw = AIMessage(
            content="",
            usage_metadata={"input_tokens": 90, "output_tokens": 30, "total_tokens": 120},
        )
        return {"raw": raw, "parsed": self._result, "parsing_error": None}


class FakeLLM:
    def __init__(self, structured_result: AddressResult):
        self._structured_result = structured_result

    def with_structured_output(self, schema, include_raw=False):
        return FakeStructuredLLM(self._structured_result)


async def test_verify_address_calls_tool_with_profile_fields(monkeypatch, _mock_audit_log):
    verify_result = json.dumps(
        {
            "valid": True,
            "deliverable": True,
            "standardized_address": "123 Maple St, Springfield, IL 62704",
            "moved": False,
            "vacant": False,
            "po_box": False,
        }
    )
    verify_tool = FakeTool("verify_address", verify_result)

    async def fake_get_address_tools():
        return {"verify_address": verify_tool}

    monkeypatch.setattr(agent_module, "get_address_tools", fake_get_address_tools)

    state = {
        "workflow_run_id": "wf-1",
        "donor_profile": {
            "address_line1": "123 Maple St",
            "city": "Springfield",
            "state": "IL",
            "postal_code": "62704",
        },
    }
    result = await agent_module.verify_address(state)

    assert result["address_verification"]["deliverable"] is True
    assert verify_tool.calls == [
        {"address_line1": "123 Maple St", "city": "Springfield", "state": "IL", "postal_code": "62704"}
    ]
    assert _mock_audit_log[0]["step"] == "verify_address"


async def test_verify_address_skips_tool_call_when_no_address(monkeypatch, _mock_audit_log):
    verify_tool = FakeTool("verify_address", "{}")

    async def fake_get_address_tools():
        return {"verify_address": verify_tool}

    monkeypatch.setattr(agent_module, "get_address_tools", fake_get_address_tools)

    state = {"workflow_run_id": "wf-1", "donor_profile": {"address_line1": None}}
    result = await agent_module.verify_address(state)

    assert result["address_verification"]["deliverable"] is False
    assert verify_tool.calls == []  # never called — no address to check


async def test_assess_and_normalize_calls_forwarding_lookup_when_moved(monkeypatch, _mock_audit_log):
    forwarding_result = json.dumps({"found": True, "new_address": "1225 Pine St", "confidence": 0.6})
    forwarding_tool = FakeTool("lookup_new_address", forwarding_result)

    async def fake_get_address_tools():
        return {"lookup_new_address": forwarding_tool}

    monkeypatch.setattr(agent_module, "get_address_tools", fake_get_address_tools)

    expected = AddressResult(
        deliverable=True, confidence=0.55, updated_address="1225 Pine St", moved=True, reasoning=["moved"]
    )
    monkeypatch.setattr(agent_module, "get_llm", lambda: FakeLLM(expected))

    state = {
        "workflow_run_id": "wf-1",
        "donor_profile": {"address_line1": "410 Willow St", "city": "Denver", "state": "CO", "postal_code": "80203"},
        "address_verification": {"moved": True, "valid": True, "deliverable": False},
    }
    result = await agent_module.assess_and_normalize(state)

    assert result["address_result"] == expected.model_dump()
    assert len(forwarding_tool.calls) == 1
    assert _mock_audit_log[0]["tool_calls"][0]["tool_name"] == "lookup_new_address"


async def test_assess_and_normalize_skips_forwarding_lookup_when_not_moved(monkeypatch, _mock_audit_log):
    forwarding_tool = FakeTool("lookup_new_address", "{}")

    async def fake_get_address_tools():
        return {"lookup_new_address": forwarding_tool}

    monkeypatch.setattr(agent_module, "get_address_tools", fake_get_address_tools)

    expected = AddressResult(deliverable=True, confidence=0.97, updated_address="123 Maple St", moved=False)
    monkeypatch.setattr(agent_module, "get_llm", lambda: FakeLLM(expected))

    state = {
        "workflow_run_id": "wf-1",
        "donor_profile": {"address_line1": "123 Maple St"},
        "address_verification": {"moved": False, "valid": True, "deliverable": True},
    }
    result = await agent_module.assess_and_normalize(state)

    assert result["address_result"] == expected.model_dump()
    assert forwarding_tool.calls == []
    assert _mock_audit_log[0]["tool_calls"] == []
