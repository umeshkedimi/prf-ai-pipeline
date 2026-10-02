import time

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.core.audit import write_audit_log
from app.core.config import get_settings
from app.core.llm import ainvoke_structured, get_llm
from app.graph.state import PipelineState

# Deliberately NOT "human_review": GET /workflow/{id} builds review_history from
# that agent name, and a reconciliation row is not a human decision.
AGENT_NAME = "decision_reconciliation"
STEP = "reconcile_decision"

RECONCILE_SYSTEM_PROMPT = """You read the free-text notes a human reviewer left on a \
fundraising pipeline decision and extract anything that should shape how the donor's \
appeal letter is WRITTEN (sensitivity, a personal circumstance to acknowledge or avoid, \
a topic to mention or leave out, a relationship detail).

Hard rules:
1. You only extract writing guidance. You never decide routing, approval, or what runs next.
2. Never include dollar amounts, the tone label, or any legal/tax/disclosure wording — those \
are fixed by deterministic business rules and are not yours to change.
3. Guidance must come from the reviewer's notes. Do not invent circumstances.
4. If the notes contain nothing relevant to the letter's content (for example only "looks \
fine" or an address correction), set `applies` to false and `guidance` to null.
5. List in `concerns` anything in the notes that conflicts with the decision taken or that \
a later reader should double-check. Empty is fine.

Confidence (0-1) reflects how clearly the notes translate into letter guidance."""


class ReviewerGuidance(BaseModel):
    applies: bool
    guidance: str | None = None
    concerns: list[str] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


def should_reconcile(state: PipelineState) -> bool:
    """Deterministic gate: only call the model when there is something to
    interpret AND a letter still to write. A reject ends the run, the
    compliance stage resumes past drafting, and empty notes carry no
    information — none of those spend an LLM call."""
    decision = state.get("human_review_decision") or {}
    if state.get("compliance_disclosures") is not None:
        return False
    if decision.get("action") == "reject":
        return False
    return bool((decision.get("notes") or "").strip())


def merge_guidance(earlier: dict | None, new: dict) -> dict:
    """A run can pause more than once (address, then recommendation). Guidance
    from an earlier pause still applies to the letter, so a later pause adds to
    it rather than silently replacing it."""
    if not earlier or not earlier.get("applies"):
        return new
    if not new["applies"]:
        return {**new, "applies": True, "guidance": earlier["guidance"]}
    return {**new, "guidance": f"{earlier['guidance']}\n{new['guidance']}"}


async def reconcile_decision(state: PipelineState) -> dict:
    """Turns a reviewer's free-text notes into structured letter guidance.

    Runs after human_review and before the resume routing. It cannot change
    where the run goes — route_after_human_review still reads only the
    reviewer's deterministic decision — and it cannot touch the ask, tone or
    disclosures. The guidance it produces reaches the letter prompt, and the
    drafted letter still passes Compliance (including the revise loop), so
    human-influenced text is reviewed exactly like any other draft."""
    if not should_reconcile(state):
        return {}

    started = time.monotonic()
    settings = get_settings()
    decision = state.get("human_review_decision") or {}
    notes = decision["notes"].strip()

    prompt = (
        f"Reviewer action: {decision.get('action')}\n"
        f"Reviewer notes: {notes}\n"
        f"Donor segment: {(state.get('recommendation_result') or {}).get('segment', 'unknown')}\n"
    )
    messages = [SystemMessage(content=RECONCILE_SYSTEM_PROMPT), HumanMessage(content=prompt)]
    result, usage = await ainvoke_structured(get_llm(), ReviewerGuidance, messages)
    guidance = result.model_dump()
    # An "applies" with no text (or text with applies false) carries nothing usable.
    guidance["applies"] = bool(guidance["applies"] and (guidance["guidance"] or "").strip())
    guidance = merge_guidance(state.get("reviewer_guidance"), guidance)

    await write_audit_log(
        workflow_run_id=state["workflow_run_id"],
        agent_name=AGENT_NAME,
        step=STEP,
        input_snapshot={"action": decision.get("action"), "notes": notes},
        output=guidance,
        confidence=guidance["confidence"],
        reasoning="; ".join(guidance["rationale"]),
        model=settings.llm_model,
        latency_ms=int((time.monotonic() - started) * 1000),
        **usage,
    )
    return {"reviewer_guidance": guidance}
