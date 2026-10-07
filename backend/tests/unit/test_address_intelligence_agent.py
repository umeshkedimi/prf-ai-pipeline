"""Address Intelligence is deterministic end to end: the decision table in rules.py plus
two MCP tool calls in check_address. No LLM is mocked because none is involved."""

import json

import pytest

from app.agents.address_intelligence import agent as agent_module
from app.agents.address_intelligence.rules import (
    CONF_CERTAIN_UNDELIVERABLE,
    CONF_CLEAN,
    CONF_MOVED_UNKNOWN,
    CONF_NO_ADDRESS,
    CONF_PO_BOX,
    assess_address,
)

CLEAN = {"valid": True, "deliverable": True, "standardized_address": "1 Main St, X, TX 75001",
         "moved": False, "vacant": False, "po_box": False}


# --- the decision table ---------------------------------------------------------------


def test_clean_address_is_deliverable_and_confident():
    r = assess_address(CLEAN, None, has_address=True)
    assert r["deliverable"] and r["confidence"] == CONF_CLEAN
    assert r["updated_address"] == CLEAN["standardized_address"] and not r["moved"]


def test_po_box_is_deliverable_with_a_mild_caution():
    r = assess_address({**CLEAN, "po_box": True}, None, has_address=True)
    assert r["deliverable"] and r["confidence"] == CONF_PO_BOX
    assert any("PO box" in line for line in r["reasoning"])


def test_moved_with_a_forwarding_address_carries_the_forwarding_confidence():
    fwd = {"found": True, "new_address": "9 New St, Denver, CO 80218", "confidence": 0.6}
    r = assess_address({**CLEAN, "moved": True, "deliverable": False}, fwd, has_address=True)
    assert r["deliverable"] and r["moved"] and r["confidence"] == 0.6
    assert r["updated_address"] == "9 New St, Denver, CO 80218"


def test_moved_with_no_forwarding_goes_to_a_human():
    r = assess_address({**CLEAN, "moved": True}, {"found": False, "new_address": None, "confidence": 0.0}, True)
    assert not r["deliverable"] and r["confidence"] == CONF_MOVED_UNKNOWN and r["updated_address"] is None


def test_vacant_is_a_certain_undeliverable_so_the_run_ends_rather_than_pauses():
    raw = {**CLEAN, "valid": False, "deliverable": False, "vacant": True, "standardized_address": None}
    r = assess_address(raw, None, has_address=True)
    assert not r["deliverable"] and r["confidence"] == CONF_CERTAIN_UNDELIVERABLE


def test_no_address_on_file_is_unknown_and_pauses():
    r = assess_address({}, None, has_address=False)
    assert not r["deliverable"] and r["confidence"] == CONF_NO_ADDRESS


def test_forwarding_confidence_is_clamped_to_a_valid_range():
    fwd = {"found": True, "new_address": "x", "confidence": 7}
    assert assess_address({**CLEAN, "moved": True}, fwd, True)["confidence"] == 1.0


# --- the node -------------------------------------------------------------------------


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
        return json.dumps(self._result)


PROFILE = {"address_line1": "410 Willow St", "city": "Denver", "state": "CO", "postal_code": "80203"}


async def test_check_address_verifies_then_skips_the_forwarding_lookup_when_not_moved(monkeypatch, _mock_audit_log):
    verify, lookup = FakeTool(CLEAN), FakeTool({"found": False})

    async def tools():
        return {"verify_address": verify, "lookup_new_address": lookup}

    monkeypatch.setattr(agent_module, "get_address_tools", tools)
    result = await agent_module.check_address({"workflow_run_id": "wf", "donor_profile": PROFILE})

    assert result["address_result"]["deliverable"] is True
    assert verify.calls == [PROFILE] and lookup.calls == []
    audit = _mock_audit_log[0]
    assert audit["step"] == "check_address" and "model" not in audit  # no LLM was involved


async def test_check_address_looks_up_a_forwarding_address_only_when_moved(monkeypatch, _mock_audit_log):
    moved = {**CLEAN, "moved": True, "deliverable": False}
    fwd = {"found": True, "new_address": "9 New St", "confidence": 0.6}
    verify, lookup = FakeTool(moved), FakeTool(fwd)

    async def tools():
        return {"verify_address": verify, "lookup_new_address": lookup}

    monkeypatch.setattr(agent_module, "get_address_tools", tools)
    result = await agent_module.check_address({"workflow_run_id": "wf", "donor_profile": PROFILE})

    assert lookup.calls == [PROFILE]
    assert result["address_result"]["confidence"] == 0.6 and result["address_result"]["moved"] is True
    assert [c["tool_name"] for c in _mock_audit_log[0]["tool_calls"]] == ["verify_address", "lookup_new_address"]


async def test_check_address_skips_every_tool_when_there_is_no_address(monkeypatch, _mock_audit_log):
    verify = FakeTool(CLEAN)

    async def tools():
        raise AssertionError("no tool should be fetched without an address")

    monkeypatch.setattr(agent_module, "get_address_tools", tools)
    result = await agent_module.check_address({"workflow_run_id": "wf", "donor_profile": {"address_line1": None}})

    assert result["address_result"]["confidence"] == CONF_NO_ADDRESS and verify.calls == []
    assert result["address_verification"]["deliverable"] is False
