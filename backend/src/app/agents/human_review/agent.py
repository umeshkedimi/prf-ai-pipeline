from langgraph.types import interrupt

from app.core.audit import write_audit_log
from app.graph.state import PipelineState

AGENT_NAME = "human_review"


async def human_review(state: PipelineState) -> dict:
    """Pauses the graph via a real LangGraph interrupt() until a decision is
    submitted through POST /workflow/{id}/review. Deliberately nothing runs
    before interrupt() — code placed before it re-executes every time this node
    is resumed until interrupt() actually returns a value (a documented
    LangGraph gotcha), so all side effects (the audit log write) live after.

    One node serves two review stages. Recommendation only exists once address
    is fully resolved, so its presence is a reliable, order-guaranteed
    discriminator of which stage paused — no explicit flag needed."""
    stage = "recommendation" if state.get("recommendation_result") is not None else "address"

    if stage == "recommendation":
        under_review = state.get("recommendation_result") or {}
        reason = "recommendation_requires_approval"
    else:
        under_review = state.get("address_result") or {}
        reason = "address_confidence_below_threshold"

    decision = interrupt(
        {
            "reason": reason,
            "stage": stage,
            "under_review": under_review,
            "donor_profile": state.get("donor_profile"),
        }
    )

    updated = dict(under_review)
    action = decision.get("action")

    if stage == "recommendation":
        if action == "modify" and decision.get("updated_ask_amount") is not None:
            updated["recommended_ask"] = float(decision["updated_ask_amount"])
        elif action == "reject":
            # Rejecting a recommendation means "do not mail this ask" — zero it
            # out rather than silently keeping the flagged amount.
            updated["recommended_ask"] = 0.0
        # "approve": accept the recommendation as-is; confidence is preserved
        # honestly (see below), not inflated by the fact a human signed off.
        updated["human_reviewed"] = True
        result_key = "recommendation_result"
    else:
        if action == "modify" and decision.get("updated_address"):
            updated["updated_address"] = decision["updated_address"]
            updated["deliverable"] = True
        elif action == "reject":
            updated["deliverable"] = False
        # "approve": leave the (low-confidence) address assessment exactly as
        # the agent produced it — the human accepts it, they don't assert new
        # certainty. Faking a higher confidence would misrepresent the record.
        updated["human_reviewed"] = True
        result_key = "address_result"

    await write_audit_log(
        workflow_run_id=state["workflow_run_id"],
        agent_name=AGENT_NAME,
        step="human_review",
        input_snapshot={"stage": stage, "under_review": under_review},
        output=updated,
        reasoning=decision.get("notes"),
        source_refs=[{"reviewer": decision.get("reviewer"), "action": action, "stage": stage}],
    )

    return {result_key: updated, "human_review_decision": decision}
