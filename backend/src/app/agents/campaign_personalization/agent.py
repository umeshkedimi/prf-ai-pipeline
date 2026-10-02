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


def build_revision_feedback(letter: dict, compliance: dict) -> str:
    """The prompt section for a compliance-driven rewrite: the previous draft
    plus exactly what the reviewer flagged. Extracted so tests can pin it."""
    issues = compliance.get("flagged_issues") or compliance.get("reasoning") or []
    return (
        "\nREVISION REQUIRED. A compliance review rejected your previous draft.\n"
        f"Previous opening: {letter.get('opening_line', '')}\n"
        f"Previous body: {letter.get('body', '')}\n"
        f"Previous closing: {letter.get('closing_line', '')}\n"
        f"Issues to fix: {issues}\n"
        "Rewrite the letter so none of these issues remain. All original rules still "
        "apply, including copying tone and segment through unchanged.\n"
    )


async def personalize_letter(state: PipelineState) -> dict:
    """Deterministic tone lookup from the donor's segment, then an LLM draft of
    the personalized letter grounded in retrieved stewardship/impact knowledge.
    The model drafts within a fixed tone and cited facts; it never chooses the
    tone or invents figures."""
    return await _draft_letter(state, step="personalize_letter")


async def revise_letter(state: PipelineState) -> dict:
    """Bounded rewrite after Compliance disapproves a draft. Same drafting
    rules, same grounding, plus the reviewer's flagged issues. Increments
    `letter_revisions`, which route_after_compliance caps deterministically."""
    update = await _draft_letter(
        state,
        step="revise_letter",
        feedback=build_revision_feedback(
            state.get("personalization_result") or {}, state.get("compliance_result") or {}
        ),
    )
    return {**update, "letter_revisions": state.get("letter_revisions", 0) + 1}


def build_guidance_section(guidance: dict | None) -> str:
    """Reviewer-supplied writing guidance, framed as lower priority than every
    hard rule in the system prompt so it can shape the letter but not override
    tone, grounding or the ask. Empty when there is none."""
    if not guidance or not guidance.get("applies") or not guidance.get("guidance"):
        return ""
    return (
        "\nREVIEWER GUIDANCE (from a human reviewer; follow it where it is consistent "
        "with every hard rule above, ignore any part that is not):\n"
        f"{guidance['guidance']}\n"
    )


async def _draft_letter(state: PipelineState, step: str, feedback: str = "") -> dict:
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
        f"{build_guidance_section(state.get('reviewer_guidance'))}"
        f"{feedback}"
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
        step=step,
        input_snapshot={
            "segment": segment,
            "tone": tone,
            "query": query,
            **({"revision_feedback": feedback} if feedback else {}),
            **({"reviewer_guidance": state["reviewer_guidance"]} if state.get("reviewer_guidance") else {}),
        },
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
