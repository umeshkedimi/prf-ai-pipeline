from langgraph.types import interrupt

from app.agents.donor_verification.eligibility import blocking_flags
from app.core.audit import write_audit_log
from app.graph.state import PipelineState
from app.mcp_clients.crm_client import get_crm_tools, parse_single

AGENT_NAME = "human_review"


async def human_review(state: PipelineState) -> dict:
    """Pauses the graph via a real LangGraph interrupt() until a decision is
    submitted through POST /workflow/{id}/review. Deliberately nothing runs
    before interrupt() — code placed before it re-executes every time this node
    is resumed until interrupt() actually returns a value (a documented
    LangGraph gotcha), so all side effects (the audit log write) live after.

    One node serves three review stages. Each later stage only exists once the
    one before it is fully resolved, so checking most-downstream-first is a
    reliable, order-guaranteed discriminator of which stage paused — no
    explicit flag needed."""
    if state.get("compliance_disclosures") is not None:
        stage = "compliance"
    elif state.get("recommendation_result") is not None:
        stage = "recommendation"
    else:
        stage = "address"

    if stage == "compliance":
        under_review = state.get("compliance_disclosures") or {}
        reason = "not_registered_to_solicit_in_state"
    elif stage == "recommendation":
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

    # A run can sit paused for hours or days, but donor_profile is a snapshot
    # from before the pause — so a donor who opted out (or was suppressed) in the
    # meantime would otherwise still be mailed. Re-read just the two hard
    # eligibility flags now that a human has decided. Deliberately not a full
    # refresh: the reviewer approved against the data they were shown, and
    # silently swapping other fields underneath that decision would make it a
    # decision about data they never saw. A reject needs no check — it ends the
    # run either way, and a CRM outage shouldn't be able to block a reject.
    recheck: dict = {"checked": False}
    revoked = None
    recheck_calls: list[dict] = []
    if action != "reject":
        tools = await get_crm_tools()
        args = {"donor_id": state.get("donor_id")}
        profile = parse_single(await tools["get_donor_profile"].ainvoke(args))
        flags = blocking_flags(profile)
        recheck = {"checked": True, "blocking_flags": flags}
        recheck_calls = [{"tool_name": "get_donor_profile", "args": args, "result": recheck}]
        if flags:
            revoked = {"blocking_flags": flags, "stage": stage}

    if stage == "compliance":
        # No numeric/address field applies here, so "modify" behaves like
        # "approve" — the reviewer's notes carry the reason (e.g. registration
        # was completed since this fixture was last updated). "reject" leaves
        # the state legally blocked.
        updated["registered_to_solicit"] = action != "reject"
        updated["human_reviewed"] = True
        result_key = "compliance_disclosures"
    elif stage == "recommendation":
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
        output={**updated, "eligibility_recheck": recheck},
        reasoning=decision.get("notes"),
        source_refs=[{"reviewer": decision.get("reviewer"), "action": action, "stage": stage}],
        tool_calls=recheck_calls,
    )

    update = {result_key: updated, "human_review_decision": decision}
    if revoked:
        verification = dict(state.get("verification_result") or {})
        verification.update(
            eligible=False,
            reason=(
                f"Became ineligible while the run was paused for review: CRM flag "
                f"{', '.join(revoked['blocking_flags'])} is now set."
            ),
            revoked_during_review=True,
        )
        update["verification_result"] = verification
        update["eligibility_revoked"] = revoked
    return update
