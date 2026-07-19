from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.address_intelligence.agent import assess_and_normalize, verify_address
from app.agents.donation_recommendation.agent import compute_rfm, recommend_ask
from app.agents.donor_verification.agent import fetch_core_data, gather_context, synthesize_verdict
from app.agents.human_review.agent import human_review
from app.core.config import get_settings
from app.graph.checkpointer import get_checkpointer
from app.graph.state import PipelineState


def route_after_verification(state: PipelineState) -> str:
    """Donor Verification's own low-confidence outcomes (duplicate/suspicious)
    are advisory only — they don't block. Only an ineligible donor (do-not-
    contact/suppressed, both enforced deterministically upstream) skips the
    rest of the pipeline entirely; there's no point address-checking someone
    we're not going to mail."""
    verdict = state.get("verification_result") or {}
    return "verify_address" if verdict.get("eligible") else END


def route_after_address(state: PipelineState) -> str:
    """The platform's first pause point. Below-threshold address confidence
    pauses for review; an above-threshold, deliverable address flows on to the
    recommendation. A confident-but-undeliverable address ends here — there's
    nothing to mail."""
    settings = get_settings()
    result = state.get("address_result") or {}
    confidence = result.get("confidence", 0)
    if confidence < settings.confidence_threshold_address_intelligence:
        return "human_review"
    return "compute_rfm" if result.get("deliverable") else END


def route_after_human_review(state: PipelineState) -> str:
    """After a human decision, resume where it makes sense. An address-stage
    decision (recommendation not computed yet) continues into the recommendation
    if the address is now deliverable, else stops (rejected/undeliverable → can't
    mail). A recommendation-stage decision is the last step for now."""
    if state.get("recommendation_result") is not None:
        return END  # recommendation stage — nothing further until Phase 4
    address_result = state.get("address_result") or {}
    return "compute_rfm" if address_result.get("deliverable") else END


def route_after_recommendation(state: PipelineState) -> str:
    """The graph's second interrupt trigger: a major-gift-sized ask pauses for
    human approval ("ask amount" is on the spec's human-review trigger list).

    Deliberately keyed on the ask amount alone, which is *deterministic* (it
    comes from the computed ask ladder), not on the model's confidence. Two
    reasons: routing a blocking pause off a non-deterministic float would let
    the same donor take different paths on identical data — unacceptable when
    the output is a physical letter — and a recommendation's confidence is a
    prediction about a future gift, not a factual assessment, so it runs
    honestly low (~0.5) for the thin giving histories that are entirely normal
    in this dataset. Low confidence still isn't ignored: it marks the run
    `needs_review` (advisory, non-blocking) in workers/tasks.py, the same way
    Donor Verification's duplicate/suspicious flags do."""
    settings = get_settings()
    rec = state.get("recommendation_result") or {}
    if rec.get("recommended_ask", 0) >= settings.major_gift_ask_threshold:
        return "human_review"
    return END


def _build_graph() -> StateGraph:
    graph = StateGraph(PipelineState)
    graph.add_node("fetch_core_data", fetch_core_data)
    graph.add_node("gather_context", gather_context)
    graph.add_node("synthesize_verdict", synthesize_verdict)
    graph.add_node("verify_address", verify_address)
    graph.add_node("assess_and_normalize", assess_and_normalize)
    graph.add_node("compute_rfm", compute_rfm)
    graph.add_node("recommend_ask", recommend_ask)
    graph.add_node("human_review", human_review)

    graph.add_edge(START, "fetch_core_data")
    graph.add_edge("fetch_core_data", "gather_context")
    graph.add_edge("gather_context", "synthesize_verdict")
    graph.add_conditional_edges(
        "synthesize_verdict", route_after_verification, {"verify_address": "verify_address", END: END}
    )
    graph.add_edge("verify_address", "assess_and_normalize")
    graph.add_conditional_edges(
        "assess_and_normalize",
        route_after_address,
        {"human_review": "human_review", "compute_rfm": "compute_rfm", END: END},
    )
    graph.add_edge("compute_rfm", "recommend_ask")
    graph.add_conditional_edges(
        "recommend_ask", route_after_recommendation, {"human_review": "human_review", END: END}
    )
    graph.add_conditional_edges(
        "human_review", route_after_human_review, {"compute_rfm": "compute_rfm", END: END}
    )
    return graph


@asynccontextmanager
async def build_graph() -> AsyncIterator[CompiledStateGraph]:
    """Compiled graph is only valid within this context — it's bound to the
    checkpointer's connection pool."""
    async with get_checkpointer() as checkpointer:
        yield _build_graph().compile(checkpointer=checkpointer)
