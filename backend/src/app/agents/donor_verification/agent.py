import json
import time

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from app.agents.donor_verification.prompts import (
    GATHER_CONTEXT_SYSTEM_PROMPT,
    SYNTHESIZE_VERDICT_SYSTEM_PROMPT,
)
from app.agents.donor_verification.schemas import VerificationResult
from app.core.audit import write_audit_log
from app.core.config import get_settings
from app.core.llm import ainvoke_structured, get_llm, token_usage
from app.graph.state import PipelineState
from app.mcp_clients.crm_client import get_crm_tools, parse_list, parse_single

MAX_TOOL_ITERATIONS = 4
AGENT_NAME = "donor_verification"
# The CRM MCP tool occasionally returns an empty/non-JSON body on a bind_tools
# call — a transient hiccup (see CLAUDE.local.md item 3), not a fixed broken
# case: repeat sweeps hit a different donor each time and clear on a bare
# re-run. Re-invoking the tool call itself (not just re-parsing) is bounded so
# a genuinely broken response still fails loudly.
TOOL_RESULT_MAX_ATTEMPTS = 3


async def fetch_core_data(state: PipelineState) -> dict:
    """Deterministic: get_donor_profile via the CRM MCP tool, no LLM involved.
    do_not_contact / suppression flags are read as-is here, never inferred."""
    started = time.monotonic()
    tools = await get_crm_tools()
    args = {"donor_id": state["donor_id"]}
    result = await tools["get_donor_profile"].ainvoke(args)
    profile = parse_single(result)

    await write_audit_log(
        workflow_run_id=state["workflow_run_id"],
        agent_name=AGENT_NAME,
        step="fetch_core_data",
        input_snapshot={"donor_id": state["donor_id"]},
        output=profile,
        source_refs=[{"tool_name": "get_donor_profile", "args": args, "result_summary": profile}],
        latency_ms=int((time.monotonic() - started) * 1000),
    )
    return {"donor_profile": profile}


async def gather_context(state: PipelineState) -> dict:
    """LLM bound to donation-history + duplicate-lookup tools, bounded tool loop."""
    started = time.monotonic()
    settings = get_settings()
    tools = await get_crm_tools()
    bindable = [tools["get_donation_history"], tools["find_potential_duplicate_donors"]]
    llm = get_llm().bind_tools(bindable)

    profile = state.get("donor_profile") or {}
    messages: list = [
        SystemMessage(content=GATHER_CONTEXT_SYSTEM_PROMPT),
        HumanMessage(
            content=(
                f"Donor profile:\n{profile}\n\n"
                f"donor_id (use for get_donation_history): {state['donor_id']}\n"
                f"name (use for find_potential_duplicate_donors): "
                f"{profile.get('first_name', '')} {profile.get('last_name', '')}\n"
                f"address (use for find_potential_duplicate_donors): "
                f"{profile.get('address_line1') or ''}\n"
                f"exclude_donor_id (use for find_potential_duplicate_donors): {state['donor_id']}"
            )
        ),
    ]

    donation_history: list[dict] = []
    duplicate_candidates: list[dict] = []
    tool_call_log: list[dict] = []
    # This loop is the most expensive step in the pipeline: each iteration is a
    # full LLM call over a message list that grows every time. Accumulate so the
    # audit row reflects the whole step, not just its final call.
    responses = []

    for _ in range(MAX_TOOL_ITERATIONS):
        response = await llm.ainvoke(messages)
        responses.append(response)
        messages.append(response)
        if not response.tool_calls:
            break

        for call in response.tool_calls:
            last_error: json.JSONDecodeError | None = None
            for _ in range(TOOL_RESULT_MAX_ATTEMPTS):
                tool_result = await tools[call["name"]].ainvoke(call["args"])
                try:
                    parsed = parse_list(tool_result)
                    last_error = None
                    break
                except json.JSONDecodeError as exc:
                    last_error = exc
            if last_error is not None:
                raise last_error
            if call["name"] == "get_donation_history":
                donation_history = parsed
            elif call["name"] == "find_potential_duplicate_donors":
                duplicate_candidates = parsed
            tool_call_log.append({"tool_name": call["name"], "args": call["args"], "result": parsed})
            messages.append(ToolMessage(content=str(parsed), tool_call_id=call["id"]))

    await write_audit_log(
        workflow_run_id=state["workflow_run_id"],
        agent_name=AGENT_NAME,
        step="gather_context",
        input_snapshot={"donor_id": state["donor_id"], "donor_profile": profile},
        output={"donation_history": donation_history, "duplicate_candidates": duplicate_candidates},
        source_refs=[{"tool_name": c["tool_name"], "args": c["args"]} for c in tool_call_log],
        tool_calls=tool_call_log,
        model=settings.llm_model,
        latency_ms=int((time.monotonic() - started) * 1000),
        **token_usage(*responses),
    )
    return {"donation_history": donation_history, "duplicate_candidates": duplicate_candidates}


async def synthesize_verdict(state: PipelineState) -> dict:
    """Structured-output LLM call, no tools — produces the final VerificationResult."""
    started = time.monotonic()
    settings = get_settings()
    llm = get_llm()

    input_snapshot = {
        "donor_profile": state.get("donor_profile"),
        "donation_history": state.get("donation_history"),
        "duplicate_candidates": state.get("duplicate_candidates"),
    }
    prompt = (
        f"Donor profile:\n{input_snapshot['donor_profile']}\n\n"
        f"Donation history:\n{input_snapshot['donation_history']}\n\n"
        f"Potential duplicate candidates:\n{input_snapshot['duplicate_candidates']}\n"
    )
    messages = [
        SystemMessage(content=SYNTHESIZE_VERDICT_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    result, usage = await ainvoke_structured(llm, VerificationResult, messages)
    verdict = result.model_dump()

    await write_audit_log(
        workflow_run_id=state["workflow_run_id"],
        agent_name=AGENT_NAME,
        step="synthesize_verdict",
        input_snapshot=input_snapshot,
        output=verdict,
        confidence=verdict["confidence"],
        reasoning="; ".join(verdict["reasoning"]),
        model=settings.llm_model,
        latency_ms=int((time.monotonic() - started) * 1000),
        **usage,
    )
    return {"verification_result": verdict}
