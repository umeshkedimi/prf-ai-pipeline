import time

from app.agents.pdf_generation.render import (
    DONATION_TRACKING_BASE_URL,
    build_reference,
    render_letter_pdf,
)
from app.agents.pdf_generation.schemas import PdfGenerationResult
from app.core.audit import write_audit_log
from app.graph.state import PipelineState
from app.mcp_clients.print_vendor_client import get_print_vendor_tools, parse_single

AGENT_NAME = "pdf_generation"
PAGE_COUNT = 1  # letters in this domain are a single-page appeal


def _format_mailing_address(profile: dict, address_result: dict) -> str:
    """A move-corrected address (from Address Intelligence) always wins over
    the donor's address on file — it's the one that's actually deliverable."""
    if updated := address_result.get("updated_address"):
        return updated
    city_state = ", ".join(p for p in (profile.get("city"), profile.get("state")) if p)
    city_line = f"{city_state} {profile.get('postal_code') or ''}".strip()
    lines = [profile.get("address_line1"), profile.get("address_line2"), city_line]
    return "\n".join(line for line in lines if line)


async def generate_pdf(state: PipelineState) -> dict:
    """Deterministic: assembles the print-ready PDF from the drafted letter
    and its legally required disclosures, then submits it to the (mocked)
    Print Vendor for fulfillment. No LLM call — every judgment call the
    letter needed already happened upstream (personalization, compliance
    review); what's left is mechanical layout and a vendor order."""
    started = time.monotonic()
    workflow_run_id = state["workflow_run_id"]
    profile = state.get("donor_profile") or {}
    letter = state.get("personalization_result") or {}
    compliance = state.get("compliance_result") or {}
    address_result = state.get("address_result") or {}
    disclosures = compliance.get("required_disclosures", [])

    reference = build_reference(workflow_run_id)
    mailing_address = _format_mailing_address(profile, address_result)
    pdf_path = render_letter_pdf(
        workflow_run_id=workflow_run_id,
        reference=reference,
        mailing_address=mailing_address,
        letter=letter,
        disclosures=disclosures,
    )

    tools = await get_print_vendor_tools()
    args = {"reference": reference, "page_count": PAGE_COUNT}
    result = await tools["submit_print_order"].ainvoke(args)
    order = parse_single(result)

    pdf_result = PdfGenerationResult(
        reference=reference,
        pdf_path=pdf_path,
        page_count=PAGE_COUNT,
        qr_code_data=f"{DONATION_TRACKING_BASE_URL}/{reference}",
        required_disclosures=disclosures,
        **order,
    ).model_dump()

    await write_audit_log(
        workflow_run_id=workflow_run_id,
        agent_name=AGENT_NAME,
        step="generate_pdf",
        input_snapshot={"reference": reference, "mailing_address": mailing_address},
        output=pdf_result,
        tool_calls=[{"tool_name": "submit_print_order", "args": args, "result": order}],
        latency_ms=int((time.monotonic() - started) * 1000),
    )
    return {"pdf_result": pdf_result}
