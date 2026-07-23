"""PDF Generation eval — deterministic assembly and vendor-order correctness.

No LLM runs in this phase at all, so unlike every other agent suite this one
has no groundedness/judge scorer — it's entirely `FunctionScorer`s pinning
the deterministic contract: a real PDF file lands on disk, the reference
code is stable for a given workflow run, disclosures pass through unchanged
from the compliance result, and the vendor's mocked postage-class/cost
selection matches its own fixture rule.
"""

from pathlib import Path

from app.agents.donor_verification.agent import fetch_core_data
from app.agents.pdf_generation.agent import generate_pdf
from app.agents.pdf_generation.render import build_reference
from app.evals.scorers import FunctionScorer
from app.evals.suites._common import create_workflow_run, resolve_donor_id
from app.evals.types import EvalCase, EvalSuite
from app.mcp_servers.print_vendor.fixtures import FIRST_CLASS_MAX_PAGES

_LETTER = {
    "segment": "active",
    "tone": "appreciative, straightforward step-up",
    "salutation": "Dear Eleanor,",
    "opening_line": "Thank you for your generous support last spring.",
    "body": (
        "Your gift of $150 helped feed 12 rescued dogs for a month. A gift of "
        "$200 today would extend that same care to more animals waiting for homes."
    ),
    "closing_line": "With gratitude,",
}
_DISCLOSURES = [
    "No goods or services were provided in exchange for this contribution.",
    "Additional information may be obtained from the Washington Secretary of "
    "State's Charities Program.",
]

_LABELS = ["d-0001", "d-0006", "d-0008"]

CASES = [EvalCase(case_id=external_id, inputs={"external_id": external_id}) for external_id in _LABELS]


async def run_case(case: EvalCase) -> dict:
    donor_id = await resolve_donor_id(case.inputs["external_id"])
    workflow_run_id = await create_workflow_run(donor_id)

    state: dict = {
        "workflow_run_id": workflow_run_id,
        "donor_id": str(donor_id),
        "campaign_id": None,
    }
    state.update(await fetch_core_data(state))
    state["personalization_result"] = _LETTER
    state["compliance_result"] = {"required_disclosures": _DISCLOSURES}

    state.update(await generate_pdf(state))
    return {"workflow_run_id": workflow_run_id, "pdf_result": state["pdf_result"]}


# --- deterministic rule checks -------------------------------------------------


def _pdf_file_exists(case: EvalCase, output: dict) -> bool:
    return Path(output["pdf_result"]["pdf_path"]).is_file()


def _reference_matches_deterministic_build(case: EvalCase, output: dict) -> bool:
    expected = build_reference(output["workflow_run_id"])
    return output["pdf_result"]["reference"] == expected


def _disclosures_pass_through_unchanged(case: EvalCase, output: dict) -> bool:
    return output["pdf_result"]["required_disclosures"] == _DISCLOSURES


def _postage_class_matches_page_count(case: EvalCase, output: dict) -> bool:
    pdf_result = output["pdf_result"]
    expected = "first_class" if pdf_result["page_count"] <= FIRST_CLASS_MAX_PAGES else "standard"
    return pdf_result["postage_class"] == expected


def _vendor_confirmation_present(case: EvalCase, output: dict) -> bool:
    pdf_result = output["pdf_result"]
    return bool(pdf_result.get("vendor_order_id")) and bool(pdf_result.get("tracking_number"))


SUITE = EvalSuite(
    name="pdf_generation",
    description="Deterministic PDF assembly (file written, disclosures pass through) + vendor order correctness",
    cases=CASES,
    run=run_case,
    scorers=[
        FunctionScorer("pdf_file_exists", _pdf_file_exists),
        FunctionScorer("reference_matches_deterministic_build", _reference_matches_deterministic_build),
        FunctionScorer("disclosures_pass_through_unchanged", _disclosures_pass_through_unchanged),
        FunctionScorer("postage_class_matches_page_count", _postage_class_matches_page_count),
        FunctionScorer("vendor_confirmation_present", _vendor_confirmation_present),
    ],
)
