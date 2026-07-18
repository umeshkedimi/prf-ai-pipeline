from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.address_intelligence.agent import assess_and_normalize, verify_address
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
    """The platform's first genuine pause point: address deliverability is on
    the original spec's human-review trigger list, unlike verification-level
    concerns."""
    settings = get_settings()
    result = state.get("address_result") or {}
    confidence = result.get("confidence", 0)
    return END if confidence >= settings.confidence_threshold_address_intelligence else "human_review"


def route_after_human_review(state: PipelineState) -> str:
    """Nothing further until Phase 3+ chains in Donation Recommendation."""
    return END


def _build_graph() -> StateGraph:
    graph = StateGraph(PipelineState)
    graph.add_node("fetch_core_data", fetch_core_data)
    graph.add_node("gather_context", gather_context)
    graph.add_node("synthesize_verdict", synthesize_verdict)
    graph.add_node("verify_address", verify_address)
    graph.add_node("assess_and_normalize", assess_and_normalize)
    graph.add_node("human_review", human_review)

    graph.add_edge(START, "fetch_core_data")
    graph.add_edge("fetch_core_data", "gather_context")
    graph.add_edge("gather_context", "synthesize_verdict")
    graph.add_conditional_edges(
        "synthesize_verdict", route_after_verification, {"verify_address": "verify_address", END: END}
    )
    graph.add_edge("verify_address", "assess_and_normalize")
    graph.add_conditional_edges(
        "assess_and_normalize", route_after_address, {"human_review": "human_review", END: END}
    )
    graph.add_conditional_edges("human_review", route_after_human_review, {END: END})
    return graph


@asynccontextmanager
async def build_graph() -> AsyncIterator[CompiledStateGraph]:
    """Compiled graph is only valid within this context — it's bound to the
    checkpointer's connection pool."""
    async with get_checkpointer() as checkpointer:
        yield _build_graph().compile(checkpointer=checkpointer)
