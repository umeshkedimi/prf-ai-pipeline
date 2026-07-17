from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agents.donor_verification.agent import fetch_core_data, gather_context, synthesize_verdict
from app.graph.checkpointer import get_checkpointer
from app.graph.state import PipelineState


def _build_graph() -> StateGraph:
    graph = StateGraph(PipelineState)
    graph.add_node("fetch_core_data", fetch_core_data)
    graph.add_node("gather_context", gather_context)
    graph.add_node("synthesize_verdict", synthesize_verdict)
    graph.add_edge(START, "fetch_core_data")
    graph.add_edge("fetch_core_data", "gather_context")
    graph.add_edge("gather_context", "synthesize_verdict")
    graph.add_edge("synthesize_verdict", END)
    return graph


@asynccontextmanager
async def build_graph() -> AsyncIterator[CompiledStateGraph]:
    """Compiled graph is only valid within this context — it's bound to the
    checkpointer's connection pool."""
    async with get_checkpointer() as checkpointer:
        yield _build_graph().compile(checkpointer=checkpointer)
