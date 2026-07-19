import time
from datetime import date

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.donation_recommendation.prompts import RECOMMEND_ASK_SYSTEM_PROMPT
from app.agents.donation_recommendation.rfm import build_ask_ladder
from app.agents.donation_recommendation.rfm import compute_rfm as compute_rfm_scores
from app.agents.donation_recommendation.schemas import RecommendationResult
from app.core.audit import write_audit_log
from app.core.config import get_settings
from app.core.llm import get_llm
from app.graph.state import PipelineState
from app.mcp_clients.crm_client import get_crm_tools, parse_list
from app.rag.retriever import retrieve

AGENT_NAME = "donation_recommendation"
RETRIEVE_K = 4


async def compute_rfm(state: PipelineState) -> dict:
    """Deterministic: RFM scoring + ask ladder from the donor's giving history.
    Reuses donation_history already fetched by gather_context; only re-hits the
    CRM tool if it's somehow absent (e.g. the agent is run standalone). No LLM."""
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

    await write_audit_log(
        workflow_run_id=state["workflow_run_id"],
        agent_name=AGENT_NAME,
        step="compute_rfm",
        input_snapshot={"donation_history": history},
        output=rfm,
        latency_ms=int((time.monotonic() - started) * 1000),
    )
    return {"recommendation_result": rfm}


async def recommend_ask(state: PipelineState) -> dict:
    """LLM + RAG: retrieve campaign knowledge, then choose the recommended ask
    from the deterministic ladder and justify it, grounded in what was retrieved.
    The model judges and explains; it never computes or alters the amounts."""
    started = time.monotonic()
    settings = get_settings()
    rfm = state.get("recommendation_result") or {}
    profile = state.get("donor_profile") or {}
    segment = rfm.get("segment", "active")

    query = (
        f"Ask strategy, impact statistics, and success stories to motivate a "
        f"{segment} donor's next gift to our animal-rescue campaign — cost of "
        f"care and program outcomes that make the ask concrete."
    )
    chunks = await retrieve(query, k=RETRIEVE_K)
    knowledge = "\n\n".join(
        f"[{c['doc_title']} · {c['doc_type']}]\n{c['chunk_text']}" for c in chunks
    )

    llm = get_llm().with_structured_output(RecommendationResult)
    prompt = (
        f"Donor first name: {profile.get('first_name', '')}\n\n"
        f"Deterministic RFM summary and ask ladder (copy these fields through unchanged, "
        f"and pick recommended_ask from ask_ladder):\n{rfm}\n\n"
        f"Retrieved campaign knowledge:\n{knowledge}\n"
    )
    messages = [
        SystemMessage(content=RECOMMEND_ASK_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    result: RecommendationResult = await llm.ainvoke(messages)
    recommendation = result.model_dump()

    await write_audit_log(
        workflow_run_id=state["workflow_run_id"],
        agent_name=AGENT_NAME,
        step="recommend_ask",
        input_snapshot={"rfm": rfm, "query": query},
        output=recommendation,
        confidence=recommendation["confidence"],
        reasoning="; ".join(recommendation["rationale"]),
        source_refs=[
            {"doc_title": c["doc_title"], "doc_type": c["doc_type"], "distance": c["distance"]}
            for c in chunks
        ],
        tool_calls=[{"tool_name": "rag.retrieve", "args": {"query": query, "k": RETRIEVE_K},
                     "result": [c["doc_title"] for c in chunks]}],
        model=settings.llm_model,
        latency_ms=int((time.monotonic() - started) * 1000),
    )
    return {"recommendation_result": recommendation}
