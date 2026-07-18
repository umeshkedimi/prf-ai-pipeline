import time

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.address_intelligence.prompts import ASSESS_AND_NORMALIZE_SYSTEM_PROMPT
from app.agents.address_intelligence.schemas import AddressResult
from app.core.audit import write_audit_log
from app.core.config import get_settings
from app.core.llm import get_llm
from app.graph.state import PipelineState
from app.mcp_clients.address_client import get_address_tools, parse_single

AGENT_NAME = "address_intelligence"

_EMPTY_VERIFICATION = {
    "valid": False,
    "deliverable": False,
    "standardized_address": None,
    "moved": False,
    "vacant": False,
    "po_box": False,
}


async def verify_address(state: PipelineState) -> dict:
    """Deterministic: verify_address via the Address MCP tool. Donors with no
    address on file skip the tool call entirely rather than calling it with
    empty strings."""
    started = time.monotonic()
    profile = state.get("donor_profile") or {}
    address_line1 = profile.get("address_line1")

    source_refs = []
    if not address_line1:
        raw = dict(_EMPTY_VERIFICATION)
    else:
        tools = await get_address_tools()
        args = {
            "address_line1": address_line1,
            "city": profile.get("city") or "",
            "state": profile.get("state") or "",
            "postal_code": profile.get("postal_code") or "",
        }
        result = await tools["verify_address"].ainvoke(args)
        raw = parse_single(result)
        source_refs = [{"tool_name": "verify_address", "args": args, "result_summary": raw}]

    await write_audit_log(
        workflow_run_id=state["workflow_run_id"],
        agent_name=AGENT_NAME,
        step="verify_address",
        input_snapshot={"address_line1": address_line1},
        output=raw,
        source_refs=source_refs,
        latency_ms=int((time.monotonic() - started) * 1000),
    )
    return {"address_verification": raw}


async def assess_and_normalize(state: PipelineState) -> dict:
    """Deterministically fetches a forwarding address when verify_address
    flagged `moved` (that lookup isn't a judgment call — it's a business rule),
    then asks the LLM for the final structured assessment: confidence, which
    address to use, and why."""
    started = time.monotonic()
    settings = get_settings()
    raw = state.get("address_verification") or {}
    profile = state.get("donor_profile") or {}

    tool_calls = []
    forwarding = None
    if raw.get("moved"):
        tools = await get_address_tools()
        args = {
            "address_line1": profile.get("address_line1") or "",
            "city": profile.get("city") or "",
            "state": profile.get("state") or "",
            "postal_code": profile.get("postal_code") or "",
        }
        result = await tools["lookup_new_address"].ainvoke(args)
        forwarding = parse_single(result)
        tool_calls = [{"tool_name": "lookup_new_address", "args": args, "result": forwarding}]

    llm = get_llm().with_structured_output(AddressResult)
    prompt = f"Raw address verification:\n{raw}\n\nForwarding lookup (only relevant if moved=true):\n{forwarding}\n"
    messages = [
        SystemMessage(content=ASSESS_AND_NORMALIZE_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    result: AddressResult = await llm.ainvoke(messages)
    address_result = result.model_dump()

    await write_audit_log(
        workflow_run_id=state["workflow_run_id"],
        agent_name=AGENT_NAME,
        step="assess_and_normalize",
        input_snapshot={"address_verification": raw, "forwarding": forwarding},
        output=address_result,
        confidence=address_result["confidence"],
        reasoning="; ".join(address_result["reasoning"]),
        tool_calls=tool_calls,
        model=settings.llm_model,
        latency_ms=int((time.monotonic() - started) * 1000),
    )
    return {"address_result": address_result}
