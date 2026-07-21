"""Fast, deterministic tests for the Campaign Personalization agent's node
logic — mocks the LLM and the RAG retriever entirely, so no network/API calls
are made."""

from langchain_core.messages import AIMessage

from app.agents.campaign_personalization import agent as agent_module
from app.agents.campaign_personalization.schemas import PersonalizationResult


class FakeStructuredLLM:
    """Mirrors include_raw=True: the parsed object alongside the AIMessage that
    carries usage_metadata, which is what token accounting reads."""

    def __init__(self, result):
        self._result = result
        self.messages = None

    async def ainvoke(self, messages):
        self.messages = messages
        raw = AIMessage(
            content="",
            usage_metadata={"input_tokens": 700, "output_tokens": 200, "total_tokens": 900},
        )
        return {"raw": raw, "parsed": self._result, "parsing_error": None}


class FakeLLM:
    def __init__(self, structured_result):
        self.structured = FakeStructuredLLM(structured_result)

    def with_structured_output(self, schema, include_raw=False):
        return self.structured


async def test_personalize_letter_grounds_the_prompt_in_retrieved_knowledge(monkeypatch):
    calls: list[dict] = []

    async def fake_write_audit_log(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(agent_module, "write_audit_log", fake_write_audit_log)

    chunks = [
        {
            "doc_title": "Donor Stewardship Principles",
            "doc_type": "guideline",
            "chunk_text": "Every appeal opens by acknowledging the donor's prior support.",
            "distance": 0.28,
        },
        {
            "doc_title": "2025 Impact Report — Key Statistics",
            "doc_type": "impact",
            "chunk_text": "It costs an average of $42 to provide one week of care.",
            "distance": 0.35,
        },
    ]

    async def fake_retrieve(query, k=4, doc_types=None):
        fake_retrieve.query = query
        return chunks

    monkeypatch.setattr(agent_module, "retrieve", fake_retrieve)

    expected = PersonalizationResult(
        segment="loyal",
        tone="warm, relationship-deepening, invites a step up",
        salutation="Dear Eleanor,",
        opening_line="Thank you for your continued support of our mission.",
        body="A gift of $225 provides over five weeks of care for animals in need.",
        closing_line="With gratitude,",
        impact_reference="It costs an average of $42 to provide one week of care.",
        confidence=0.85,
        rationale=["Loyal donor, clear step-up ask, concrete cost-of-care figure cited."],
        sources=["2025 Impact Report — Key Statistics"],
    )
    fake_llm = FakeLLM(expected)
    monkeypatch.setattr(agent_module, "get_llm", lambda: fake_llm)

    state = {
        "workflow_run_id": "wf-1",
        "donor_profile": {"first_name": "Eleanor"},
        "recommendation_result": {
            "segment": "loyal",
            "recommended_ask": 225.0,
            "rationale": ["Step up from their loyal giving history."],
        },
    }
    result = await agent_module.personalize_letter(state)

    assert result["personalization_result"] == expected.model_dump()

    # tone must actually reach the model, or "copy through unchanged" is unenforceable
    prompt = fake_llm.structured.messages[1].content
    assert "warm, relationship-deepening" in prompt
    assert "It costs an average of $42" in prompt
    assert "loyal" in fake_retrieve.query

    audit = calls[0]
    assert audit["step"] == "personalize_letter"
    assert audit["confidence"] == 0.85
    assert [ref["doc_title"] for ref in audit["source_refs"]] == [c["doc_title"] for c in chunks]
    assert audit["tool_calls"][0]["tool_name"] == "rag.retrieve"


async def test_personalize_letter_defaults_segment_when_missing(monkeypatch):
    async def fake_write_audit_log(**kwargs):
        pass

    monkeypatch.setattr(agent_module, "write_audit_log", fake_write_audit_log)

    async def fake_retrieve(query, k=4, doc_types=None):
        fake_retrieve.query = query
        return []

    monkeypatch.setattr(agent_module, "retrieve", fake_retrieve)

    expected = PersonalizationResult(
        segment="active",
        tone="appreciative, straightforward step-up",
        salutation="Dear Friend,",
        opening_line="Thank you for your support.",
        body="Consider a gift of $50.",
        closing_line="Sincerely,",
        impact_reference="",
        confidence=0.3,
        rationale=["No retrieved knowledge to ground the draft."],
        sources=[],
    )
    monkeypatch.setattr(agent_module, "get_llm", lambda: FakeLLM(expected))

    state = {"workflow_run_id": "wf-1", "donor_profile": {}, "recommendation_result": {}}
    result = await agent_module.personalize_letter(state)

    assert result["personalization_result"]["segment"] == "active"
    assert "active" in fake_retrieve.query
