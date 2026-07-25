"""Wraps each LangGraph node in its own span, named after the node, nested
under whatever span is active when the graph runs (the Celery task span in
production, a bare root span under `uv run`/pytest). Applied uniformly in
builder.py rather than touching each agent module, so every node gets a span
the same way regardless of whether it's LLM-backed or deterministic."""

from collections.abc import Awaitable, Callable
from typing import Any

from app.core.telemetry import get_tracer
from app.graph.state import PipelineState

_tracer = get_tracer(__name__)

NodeFn = Callable[[PipelineState], Awaitable[dict[str, Any]]]


def traced_node(name: str, fn: NodeFn) -> NodeFn:
    async def wrapped(state: PipelineState) -> dict[str, Any]:
        with _tracer.start_as_current_span(f"agent.{name}") as span:
            span.set_attribute("workflow_run_id", state.get("workflow_run_id") or "")
            span.set_attribute("donor_id", state.get("donor_id") or "")
            return await fn(state)

    return wrapped
