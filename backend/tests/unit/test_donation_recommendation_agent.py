"""Fast, deterministic tests for the Donation Recommendation agent's node logic
— mocks the LLM and the RAG retriever entirely, so no network/API calls are made."""

import json

import pytest

from app.agents.donation_recommendation import agent as agent_module
from app.agents.donation_recommendation.schemas import RecommendationResult


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
    def __init__(self, result):
        self._result = result
        self.messages = None

    async def ainvoke(self, messages):
        self.messages = messages
        return self._result


class FakeLLM:
    def __init__(self, structured_result):
        self.structured = FakeStructuredLLM(structured_result)

    def with_structured_output(self, schema):
        return self.structured


async def test_compute_rfm_reuses_donation_history_from_state(monkeypatch, _mock_audit_log):
    """gather_context already fetched the history — re-calling the CRM here
    would be a redundant round-trip."""
    crm_tool = FakeTool("get_donation_history", "[]")

    async def fake_get_crm_tools():
        return {"get_donation_history": crm_tool}

    monkeypatch.setattr(agent_module, "get_crm_tools", fake_get_crm_tools)

    state = {
        "workflow_run_id": "wf-1",
        "donor_id": "d-1",
        "donation_history": [{"amount": 150.0, "donation_date": "2026-02-14"}],
    }
    result = await agent_module.compute_rfm(state)

    rfm = result["recommendation_result"]
    assert rfm["frequency"] == 1
    assert rfm["ask_ladder"] == [150.0, 225.0, 375.0]
    assert crm_tool.calls == []  # never re-fetched
    assert _mock_audit_log[0]["step"] == "compute_rfm"
    assert _mock_audit_log[0].get("model") is None  # deterministic node, no LLM


async def test_compute_rfm_falls_back_to_crm_when_history_absent(monkeypatch, _mock_audit_log):
    history = json.dumps([{"amount": 80.0, "donation_date": "2026-01-10"}])
    crm_tool = FakeTool("get_donation_history", history)

    async def fake_get_crm_tools():
        return {"get_donation_history": crm_tool}

    monkeypatch.setattr(agent_module, "get_crm_tools", fake_get_crm_tools)

    state = {"workflow_run_id": "wf-1", "donor_id": "d-1"}  # no donation_history
    result = await agent_module.compute_rfm(state)

    assert crm_tool.calls == [{"donor_id": "d-1"}]
    assert result["recommendation_result"]["frequency"] == 1


async def test_recommend_ask_grounds_the_prompt_in_retrieved_knowledge(monkeypatch, _mock_audit_log):
    chunks = [
        {
            "doc_title": "2025 Impact Report — Key Statistics",
            "doc_type": "impact",
            "chunk_text": "It costs an average of $42 to provide one week of care.",
            "distance": 0.31,
        },
        {
            "doc_title": "Ask Strategy Guidelines",
            "doc_type": "guideline",
            "chunk_text": "Anchor on prior giving.",
            "distance": 0.42,
        },
    ]

    async def fake_retrieve(query, k=4, doc_types=None):
        fake_retrieve.query = query
        return chunks

    monkeypatch.setattr(agent_module, "retrieve", fake_retrieve)

    expected = RecommendationResult(
        segment="active",
        rfm_score=0.53,
        recency_days=155,
        frequency=1,
        monetary_total=150.0,
        anchor_gift=150.0,
        outlier_gift_excluded=False,
        ask_ladder=[150.0, 225.0, 375.0],
        recommended_ask=225.0,
        confidence=0.9,
        rationale=["Step up from their $150 gift."],
        sources=["2025 Impact Report — Key Statistics"],
    )
    fake_llm = FakeLLM(expected)
    monkeypatch.setattr(agent_module, "get_llm", lambda: fake_llm)

    state = {
        "workflow_run_id": "wf-1",
        "donor_profile": {"first_name": "Eleanor"},
        "recommendation_result": {
            "segment": "active",
            "ask_ladder": [150.0, 225.0, 375.0],
            "anchor_gift": 150.0,
        },
    }
    result = await agent_module.recommend_ask(state)

    assert result["recommendation_result"] == expected.model_dump()

    # the retrieved text must actually reach the model, or "grounded" is a lie
    prompt = fake_llm.structured.messages[1].content
    assert "It costs an average of $42" in prompt
    assert "Anchor on prior giving." in prompt
    assert "active" in fake_retrieve.query

    audit = _mock_audit_log[0]
    assert audit["step"] == "recommend_ask"
    assert audit["confidence"] == 0.9
    assert [ref["doc_title"] for ref in audit["source_refs"]] == [c["doc_title"] for c in chunks]
    assert audit["tool_calls"][0]["tool_name"] == "rag.retrieve"


async def test_recommend_ask_records_retrieval_even_when_nothing_matches(monkeypatch, _mock_audit_log):
    async def fake_retrieve(query, k=4, doc_types=None):
        return []

    monkeypatch.setattr(agent_module, "retrieve", fake_retrieve)

    expected = RecommendationResult(
        segment="prospect",
        rfm_score=0.0,
        recency_days=None,
        frequency=0,
        monetary_total=0.0,
        anchor_gift=0.0,
        ask_ladder=[25.0, 50.0, 100.0],
        recommended_ask=25.0,
        confidence=0.4,
        rationale=["No giving history to anchor on."],
        sources=[],
    )
    monkeypatch.setattr(agent_module, "get_llm", lambda: FakeLLM(expected))

    state = {
        "workflow_run_id": "wf-1",
        "donor_profile": {},
        "recommendation_result": {"segment": "prospect", "ask_ladder": [25.0, 50.0, 100.0]},
    }
    result = await agent_module.recommend_ask(state)

    assert result["recommendation_result"]["confidence"] == 0.4
    assert _mock_audit_log[0]["source_refs"] == []
