"""Fast, deterministic tests for the PDF Generation agent's node logic — mocks
the Print Vendor MCP tool and the PDF renderer entirely, so no file I/O or
network calls are made. There is no LLM to mock: generate_pdf has no
judgment call of its own."""

import json

import pytest

from app.agents.pdf_generation import agent as agent_module
from app.agents.pdf_generation.render import build_reference


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


def _mock_vendor(monkeypatch, result: dict) -> FakeTool:
    tool = FakeTool(json.dumps(result))

    async def fake_get_print_vendor_tools():
        return {"submit_print_order": tool}

    monkeypatch.setattr(agent_module, "get_print_vendor_tools", fake_get_print_vendor_tools)
    return tool


def _mock_render(monkeypatch) -> list[dict]:
    calls: list[dict] = []

    def fake_render_letter_pdf(**kwargs):
        calls.append(kwargs)
        return "/tmp/fake-letter.pdf"

    monkeypatch.setattr(agent_module, "render_letter_pdf", fake_render_letter_pdf)
    return calls


_VENDOR_RESULT = {
    "vendor_order_id": "PV-TEST0001",
    "tracking_number": "94000000000000000001",
    "postage_class": "first_class",
    "turnaround_days": 3,
    "cost": 0.68,
}


async def test_generate_pdf_merges_vendor_confirmation(monkeypatch, _mock_audit_log):
    vendor_tool = _mock_vendor(monkeypatch, _VENDOR_RESULT)
    render_calls = _mock_render(monkeypatch)

    state = {
        "workflow_run_id": "wf-1",
        "donor_profile": {"first_name": "Eleanor", "last_name": "Whitfield"},
        "personalization_result": {"salutation": "Dear Eleanor,", "body": "Thank you."},
        "compliance_result": {"required_disclosures": ["tax statement"]},
        "address_result": {},
    }
    result = await agent_module.generate_pdf(state)

    pdf_result = result["pdf_result"]
    assert pdf_result["reference"] == build_reference("wf-1")
    assert pdf_result["vendor_order_id"] == "PV-TEST0001"
    assert pdf_result["tracking_number"] == "94000000000000000001"
    assert pdf_result["required_disclosures"] == ["tax statement"]
    assert vendor_tool.calls == [{"reference": build_reference("wf-1"), "page_count": 1}]
    assert render_calls[0]["disclosures"] == ["tax statement"]
    assert _mock_audit_log[0]["step"] == "generate_pdf"


async def test_recommended_ask_flows_from_recommendation_result_to_render(monkeypatch, _mock_audit_log):
    _mock_vendor(monkeypatch, _VENDOR_RESULT)
    render_calls = _mock_render(monkeypatch)

    state = {
        "workflow_run_id": "wf-4",
        "donor_profile": {"first_name": "Eleanor", "last_name": "Whitfield"},
        "personalization_result": {},
        "compliance_result": {"required_disclosures": []},
        "address_result": {},
        "recommendation_result": {"recommended_ask": 225.0},
    }
    await agent_module.generate_pdf(state)

    assert render_calls[0]["recommended_ask"] == 225.0


async def test_mailing_address_prefers_updated_address_over_profile(monkeypatch, _mock_audit_log):
    _mock_vendor(monkeypatch, _VENDOR_RESULT)
    render_calls = _mock_render(monkeypatch)

    state = {
        "workflow_run_id": "wf-2",
        "donor_profile": {
            "address_line1": "123 Maple St",
            "city": "Springfield",
            "state": "IL",
            "postal_code": "62704",
        },
        "personalization_result": {},
        "compliance_result": {"required_disclosures": []},
        "address_result": {"updated_address": "1225 Pine St, Denver, CO 80218"},
    }
    await agent_module.generate_pdf(state)

    assert render_calls[0]["mailing_address"] == "1225 Pine St, Denver, CO 80218"


async def test_mailing_address_falls_back_to_profile_fields(monkeypatch, _mock_audit_log):
    _mock_vendor(monkeypatch, _VENDOR_RESULT)
    render_calls = _mock_render(monkeypatch)

    state = {
        "workflow_run_id": "wf-3",
        "donor_profile": {
            "address_line1": "123 Maple St",
            "address_line2": None,
            "city": "Springfield",
            "state": "IL",
            "postal_code": "62704",
        },
        "personalization_result": {},
        "compliance_result": {"required_disclosures": []},
        "address_result": {},
    }
    await agent_module.generate_pdf(state)

    assert render_calls[0]["mailing_address"] == "123 Maple St\nSpringfield, IL 62704"


def _state(compliance: dict) -> dict:
    return {
        "workflow_run_id": "wf-held",
        "donor_profile": {"first_name": "Eleanor"},
        "personalization_result": {"salutation": "Dear Eleanor,", "body": "Thank you."},
        "compliance_result": compliance,
        "address_result": {},
    }


async def test_disapproved_letter_is_rendered_but_not_ordered(monkeypatch, _mock_audit_log):
    vendor_tool = _mock_vendor(monkeypatch, _VENDOR_RESULT)
    render_calls = _mock_render(monkeypatch)

    compliance = {"approved": False, "flagged_issues": ["implies a guaranteed outcome"]}
    result = await agent_module.generate_pdf(_state(compliance))

    pdf_result = result["pdf_result"]
    assert vendor_tool.calls == []  # nothing submitted to the print vendor
    assert len(render_calls) == 1  # but the PDF exists for a reviewer to read
    assert pdf_result["held"] is True
    assert pdf_result["hold_reason"] == ["implies a guaranteed outcome"]
    assert pdf_result["vendor_order_id"] is None and pdf_result["tracking_number"] is None
    assert _mock_audit_log[0]["tool_calls"] == []


async def test_held_letter_without_flagged_issues_still_records_a_reason(monkeypatch, _mock_audit_log):
    _mock_vendor(monkeypatch, _VENDOR_RESULT)
    _mock_render(monkeypatch)
    result = await agent_module.generate_pdf(_state({"approved": False, "flagged_issues": []}))
    assert result["pdf_result"]["hold_reason"] == ["Compliance disapproved the letter"]


@pytest.mark.parametrize("compliance", [{"approved": True}, {}])
async def test_approved_or_unjudged_letter_is_ordered(monkeypatch, _mock_audit_log, compliance):
    """Only an explicit disapproval holds the letter — a missing verdict does not."""
    vendor_tool = _mock_vendor(monkeypatch, _VENDOR_RESULT)
    _mock_render(monkeypatch)
    result = await agent_module.generate_pdf(_state(compliance))
    assert len(vendor_tool.calls) == 1
    assert result["pdf_result"]["held"] is False
    assert result["pdf_result"]["vendor_order_id"] == "PV-TEST0001"
