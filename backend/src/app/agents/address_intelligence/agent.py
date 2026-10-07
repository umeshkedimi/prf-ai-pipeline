import time

from app.agents.address_intelligence.rules import assess_address
from app.agents.address_intelligence.schemas import AddressResult
from app.core.audit import write_audit_log
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


async def check_address(state: PipelineState) -> dict:
    """Deterministic end to end: verify the address through the Address MCP tool, look
    up a forwarding address if (and only if) the donor moved, then apply the decision
    table in rules.py. No LLM call. Donors with no address on file skip the tools
    entirely rather than calling them with empty strings."""
    started = time.monotonic()
    profile = state.get("donor_profile") or {}
    address_line1 = profile.get("address_line1")

    tool_calls: list[dict] = []
    forwarding = None
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
        raw = parse_single(await tools["verify_address"].ainvoke(args))
        tool_calls.append({"tool_name": "verify_address", "args": args, "result": raw})
        if raw.get("moved"):
            forwarding = parse_single(await tools["lookup_new_address"].ainvoke(args))
            tool_calls.append({"tool_name": "lookup_new_address", "args": args, "result": forwarding})

    address_result = AddressResult(**assess_address(raw, forwarding, bool(address_line1))).model_dump()

    await write_audit_log(
        workflow_run_id=state["workflow_run_id"],
        agent_name=AGENT_NAME,
        step="check_address",
        input_snapshot={"address_line1": address_line1},
        output=address_result,
        confidence=address_result["confidence"],
        reasoning="; ".join(address_result["reasoning"]),
        tool_calls=tool_calls,
        latency_ms=int((time.monotonic() - started) * 1000),
    )
    return {"address_verification": raw, "address_result": address_result}
