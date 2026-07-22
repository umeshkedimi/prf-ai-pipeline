import time

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.compliance.prompts import REVIEW_LETTER_COMPLIANCE_SYSTEM_PROMPT
from app.agents.compliance.schemas import LetterComplianceAssessment
from app.core.audit import write_audit_log
from app.core.config import get_settings
from app.core.llm import ainvoke_structured, get_llm
from app.graph.state import PipelineState
from app.mcp_clients.compliance_client import get_compliance_tools, parse_single
from app.rag.retriever import retrieve

AGENT_NAME = "compliance"
RETRIEVE_K = 4


async def gather_disclosures(state: PipelineState) -> dict:
    """Deterministic: a nonprofit must be registered to solicit in a donor's
    state before mailing there at all — that's a legal fact, looked up via
    the Compliance MCP tool, not a judgment call. The standard tax-
    deductibility statement is always required and returned alongside it."""
    started = time.monotonic()
    profile = state.get("donor_profile") or {}
    donor_state = profile.get("state") or ""

    tools = await get_compliance_tools()
    args = {"state": donor_state}
    result = await tools["get_disclosure_requirements"].ainvoke(args)
    raw = parse_single(result)

    await write_audit_log(
        workflow_run_id=state["workflow_run_id"],
        agent_name=AGENT_NAME,
        step="gather_disclosures",
        input_snapshot={"state": donor_state},
        output=raw,
        tool_calls=[{"tool_name": "get_disclosure_requirements", "args": args, "result": raw}],
        latency_ms=int((time.monotonic() - started) * 1000),
    )
    return {"compliance_disclosures": raw}


def build_retrieval_query() -> str:
    """Extracted for the same reason as the other RAG agents' — the eval
    suite needs to reconstruct exactly which guidance chunks the node saw."""
    return (
        "Donor rights, prohibited claims, and tax-language rules for reviewing "
        "a fundraising appeal letter before it is mailed."
    )


async def review_letter_compliance(state: PipelineState) -> dict:
    """The judgment step: does the drafted letter violate donor-rights/tax-
    language guidance? Required disclosures are merged in from
    gather_disclosures' deterministic output, never routed through the LLM."""
    started = time.monotonic()
    settings = get_settings()
    disclosures = state.get("compliance_disclosures") or {}
    letter = state.get("personalization_result") or {}
    required_disclosures = disclosures.get("required_disclosures", [])

    query = build_retrieval_query()
    chunks = await retrieve(query, k=RETRIEVE_K, doc_types=["compliance"])
    guidance = "\n\n".join(f"[{c['doc_title']}]\n{c['chunk_text']}" for c in chunks)

    llm = get_llm()
    prompt = (
        f"Drafted letter:\n"
        f"Salutation: {letter.get('salutation', '')}\n"
        f"Opening: {letter.get('opening_line', '')}\n"
        f"Body: {letter.get('body', '')}\n"
        f"Closing: {letter.get('closing_line', '')}\n\n"
        f"Disclosures that will be attached separately (for context only — do not restate "
        f"or evaluate these): {required_disclosures}\n\n"
        f"Retrieved compliance guidance:\n{guidance}\n"
    )
    messages = [
        SystemMessage(content=REVIEW_LETTER_COMPLIANCE_SYSTEM_PROMPT),
        HumanMessage(content=prompt),
    ]

    result, usage = await ainvoke_structured(llm, LetterComplianceAssessment, messages)
    assessment = result.model_dump()
    compliance_result = {**assessment, "required_disclosures": required_disclosures}

    await write_audit_log(
        workflow_run_id=state["workflow_run_id"],
        agent_name=AGENT_NAME,
        step="review_letter_compliance",
        input_snapshot={"letter": letter, "disclosures": disclosures, "query": query},
        output=compliance_result,
        confidence=compliance_result["confidence"],
        reasoning="; ".join(compliance_result["reasoning"]),
        source_refs=[
            {"doc_title": c["doc_title"], "doc_type": c["doc_type"], "distance": c["distance"]}
            for c in chunks
        ],
        tool_calls=[
            {
                "tool_name": "rag.retrieve",
                "args": {"query": query, "k": RETRIEVE_K, "doc_types": ["compliance"]},
                "result": [c["doc_title"] for c in chunks],
            }
        ],
        model=settings.llm_model,
        latency_ms=int((time.monotonic() - started) * 1000),
        **usage,
    )
    return {"compliance_result": compliance_result}
