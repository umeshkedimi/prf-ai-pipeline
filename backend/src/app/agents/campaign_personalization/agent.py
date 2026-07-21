import time

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.campaign_personalization.prompts import PERSONALIZE_LETTER_SYSTEM_PROMPT
from app.agents.campaign_personalization.rules import tone_for_segment
from app.agents.campaign_personalization.schemas import PersonalizationResult
from app.core.audit import write_audit_log
from app.core.config import get_settings
from app.core.llm import ainvoke_structured, get_llm
from app.graph.state import PipelineState
from app.rag.retriever import retrieve

AGENT_NAME = "campaign_personalization"
RETRIEVE_K = 4


def build_retrieval_query(segment: str) -> str:
    """The RAG query this agent asks, as a function of donor segment — extracted
    for the same reason as donation_recommendation's: the eval suite needs to
    reconstruct exactly which chunks the node saw to grade groundedness."""
    return (
        f"Donor stewardship tone guidance and a concrete impact story or "
        f"cost-of-care figure to personalize an appeal letter for a {segment} donor."
    )


async def personalize_letter(state: PipelineState) -> dict:
    """Deterministic tone lookup from the donor's segment, then an LLM draft of
    the personalized letter grounded in retrieved stewardship/impact knowledge.
    The model drafts within a fixed tone and cited facts; it never chooses the
    tone or invents figures."""
    started = time.monotonic()
    settings = get_settings()
    rec = state.get("recommendation_result") or {}
    profile = state.get("donor_profile") or {}
    segment = rec.get("segment", "active")
    tone = tone_for_segment(segment)

    query = build_retrieval_query(segment)
    chunks = await retrieve(query, k=RETRIEVE_K)
    knowledge = "\n\n".join(
        f"[{c['doc_title']} · {c['doc_type']}]\n{c['chunk_text']}" for c in chunks
    )

    llm = get_llm()
    prompt = (
        f"Donor first name: {profile.get('first_name', '')}\n\n"
        f"Segment: {segment}\nTone (copy through unchanged): {tone}\n\n"
        f"Recommended ask: ${rec.get('recommended_ask', 0)}\n"
        f"Ask rationale: {rec.get('rationale', [])}\n\n"
        f"Retrieved campaign knowledge:\n{knowledge}\n"
    )
    messages = [
        SystemMessage(content=PERSONALIZE_LETTER_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    result, usage = await ainvoke_structured(llm, PersonalizationResult, messages)
    personalization = result.model_dump()

    await write_audit_log(
        workflow_run_id=state["workflow_run_id"],
        agent_name=AGENT_NAME,
        step="personalize_letter",
        input_snapshot={"segment": segment, "tone": tone, "query": query},
        output=personalization,
        confidence=personalization["confidence"],
        reasoning="; ".join(personalization["rationale"]),
        source_refs=[
            {"doc_title": c["doc_title"], "doc_type": c["doc_type"], "distance": c["distance"]}
            for c in chunks
        ],
        tool_calls=[
            {
                "tool_name": "rag.retrieve",
                "args": {"query": query, "k": RETRIEVE_K},
                "result": [c["doc_title"] for c in chunks],
            }
        ],
        model=settings.llm_model,
        latency_ms=int((time.monotonic() - started) * 1000),
        **usage,
    )
    return {"personalization_result": personalization}
