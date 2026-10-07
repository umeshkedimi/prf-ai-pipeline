import time
from datetime import date

from app.agents.donation_recommendation.rfm import build_ask_ladder, choose_ask
from app.agents.donation_recommendation.rfm import compute_rfm as compute_rfm_scores
from app.agents.donation_recommendation.schemas import RecommendationResult
from app.core.audit import write_audit_log
from app.core.config import get_settings
from app.graph.state import PipelineState
from app.mcp_clients.crm_client import get_crm_tools, parse_list

AGENT_NAME = "donation_recommendation"


async def recommend_ask(state: PipelineState) -> dict:
    """Deterministic end to end: RFM scoring, the ask ladder, and the rung chosen for the
    donor's segment. Reuses donation_history already fetched by gather_context and only
    re-hits the CRM tool if it is absent (e.g. the node is run standalone). No LLM call:
    the ask is money, so it is code, and the major-gift gate that routes on it reads a
    value no model ever touched."""
    started = time.monotonic()
    settings = get_settings()

    history = state.get("donation_history")
    if history is None:
        tools = await get_crm_tools()
        result = await tools["get_donation_history"].ainvoke({"donor_id": state["donor_id"]})
        history = parse_list(result)

    rfm = compute_rfm_scores(
        history, today=date.today(), major_gift_threshold=settings.major_gift_ask_threshold
    )
    rfm["ask_ladder"] = build_ask_ladder(rfm)
    recommendation = RecommendationResult(**rfm, **choose_ask(rfm)).model_dump()

    await write_audit_log(
        workflow_run_id=state["workflow_run_id"],
        agent_name=AGENT_NAME,
        step="recommend_ask",
        input_snapshot={"donation_history": history},
        output=recommendation,
        confidence=recommendation["confidence"],
        reasoning="; ".join(recommendation["rationale"]),
        latency_ms=int((time.monotonic() - started) * 1000),
    )
    return {"recommendation_result": recommendation}
