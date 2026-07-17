from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage

from app.agents.donor_verification.prompts import (
    GATHER_CONTEXT_SYSTEM_PROMPT,
    SYNTHESIZE_VERDICT_SYSTEM_PROMPT,
)
from app.agents.donor_verification.schemas import VerificationResult
from app.core.llm import get_llm
from app.graph.state import PipelineState
from app.mcp_clients.crm_client import get_crm_tools, parse_list, parse_single

MAX_TOOL_ITERATIONS = 4


async def fetch_core_data(state: PipelineState) -> dict:
    """Deterministic: get_donor_profile via the CRM MCP tool, no LLM involved.
    do_not_contact / suppression flags are read as-is here, never inferred."""
    tools = await get_crm_tools()
    result = await tools["get_donor_profile"].ainvoke({"donor_id": state["donor_id"]})
    return {"donor_profile": parse_single(result)}


async def gather_context(state: PipelineState) -> dict:
    """LLM bound to donation-history + duplicate-lookup tools, bounded tool loop."""
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

    for _ in range(MAX_TOOL_ITERATIONS):
        response = await llm.ainvoke(messages)
        messages.append(response)
        if not response.tool_calls:
            break

        for call in response.tool_calls:
            tool_result = await tools[call["name"]].ainvoke(call["args"])
            parsed = parse_list(tool_result)
            if call["name"] == "get_donation_history":
                donation_history = parsed
            elif call["name"] == "find_potential_duplicate_donors":
                duplicate_candidates = parsed
            messages.append(ToolMessage(content=str(parsed), tool_call_id=call["id"]))

    return {"donation_history": donation_history, "duplicate_candidates": duplicate_candidates}


async def synthesize_verdict(state: PipelineState) -> dict:
    """Structured-output LLM call, no tools — produces the final VerificationResult."""
    llm = get_llm().with_structured_output(VerificationResult)

    prompt = (
        f"Donor profile:\n{state.get('donor_profile')}\n\n"
        f"Donation history:\n{state.get('donation_history')}\n\n"
        f"Potential duplicate candidates:\n{state.get('duplicate_candidates')}\n"
    )
    messages = [
        SystemMessage(content=SYNTHESIZE_VERDICT_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    result: VerificationResult = await llm.ainvoke(messages)
    return {"verification_result": result.model_dump()}
