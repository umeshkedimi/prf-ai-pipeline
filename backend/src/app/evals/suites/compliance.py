"""Compliance eval — disclosure-lookup correctness and letter-content risk review.

Isolates both `gather_disclosures` and `review_letter_compliance` from the rest
of the pipeline: the personalized letter each case reviews is a fixed, hand-
written stand-in rather than `personalize_letter`'s real output, so this suite
never pays for the personalization LLM call — that node has its own suite.

Two kinds of check, same split as the other agent suites: deterministic
scorers pin the disclosure lookup (a legal fact, not a judgment call — the tax
statement is always present, `registered_to_solicit` matches the fixture
exactly). A `d-0012` case never reaches the LLM step at all, mirroring
`route_after_disclosures`'s real behavior of skipping the content review
entirely when the org can't legally mail there regardless. The remaining
cases exercise the actual judgment call: a clean letter should clear review,
and a letter with an obvious guarantee/tax-advice violation should get flagged
and not approved — a deterministic check on the *outcome* of a real LLM call,
not a hand assertion on wording.
"""

from app.agents.compliance.agent import gather_disclosures, review_letter_compliance
from app.agents.donor_verification.agent import fetch_core_data
from app.evals.scorers import FunctionScorer
from app.evals.suites._common import create_workflow_run, resolve_donor_id
from app.evals.types import EvalCase, EvalSuite
from app.mcp_servers.compliance.fixtures import TAX_DEDUCTIBLE_STATEMENT

_CLEAN_LETTER = {
    "segment": "active",
    "tone": "appreciative, straightforward step-up",
    "salutation": "Dear Eleanor,",
    "opening_line": "Thank you for your generous support last spring.",
    "body": (
        "Your gift of $150 helped feed 12 rescued dogs for a month. A gift of "
        "$200 today would extend that same care to more animals waiting for homes."
    ),
    "closing_line": "With gratitude,",
    "impact_reference": "12 rescued dogs fed for a month",
    "confidence": 0.8,
    "rationale": ["grounded in program outcomes"],
    "sources": ["Program Outcomes and Effectiveness"],
}

_VIOLATING_LETTER = {
    **_CLEAN_LETTER,
    "body": (
        "We guarantee that your gift today will completely end animal "
        "homelessness in our city — and as your tax advisor, we can confirm "
        "you'll owe nothing in taxes this year if you give right now, before "
        "midnight."
    ),
}

# (external_id, letter, expect a content review to run, expect it to flag)
_CASES: list[tuple[str, dict, bool, bool]] = [
    ("d-0001", _CLEAN_LETTER, True, False),
    ("d-0008", _CLEAN_LETTER, True, False),
    ("d-0001", _VIOLATING_LETTER, True, True),
    ("d-0012", _CLEAN_LETTER, False, False),
]

CASES = [
    EvalCase(
        case_id=f"{external_id}-{'flagged' if should_flag else 'clean'}-{i}",
        inputs={"external_id": external_id, "letter": letter},
        expected={"reviewed": reviewed, "should_flag": should_flag},
    )
    for i, (external_id, letter, reviewed, should_flag) in enumerate(_CASES)
]


async def run_case(case: EvalCase) -> dict:
    donor_id = await resolve_donor_id(case.inputs["external_id"])
    workflow_run_id = await create_workflow_run(donor_id)

    state: dict = {
        "workflow_run_id": workflow_run_id,
        "donor_id": str(donor_id),
        "campaign_id": None,
    }
    state.update(await fetch_core_data(state))
    state.update(await gather_disclosures(state))
    disclosures = state["compliance_disclosures"]

    assessment = None
    if disclosures.get("registered_to_solicit", True):
        state["personalization_result"] = case.inputs["letter"]
        state.update(await review_letter_compliance(state))
        assessment = state["compliance_result"]

    return {"disclosures": disclosures, "assessment": assessment}


# --- deterministic rule checks -------------------------------------------------


def _tax_statement_always_present(case: EvalCase, output: dict) -> bool:
    return TAX_DEDUCTIBLE_STATEMENT in output["disclosures"].get("required_disclosures", [])


def _registered_flag_matches_reviewed_expectation(case: EvalCase, output: dict) -> bool:
    """`route_after_disclosures` skips the content review entirely when the
    org isn't registered to solicit — `reviewed` in the expected fixture is a
    direct restatement of that gate, so this checks the two never disagree."""
    return output["disclosures"].get("registered_to_solicit", True) == case.expected["reviewed"]

def _review_ran_when_expected(case: EvalCase, output: dict) -> bool:
    return (output["assessment"] is not None) == case.expected["reviewed"]


def _flag_outcome_matches(case: EvalCase, output: dict) -> bool:
    """The judgment call itself: a clean letter should be approved; an obvious
    guarantee/tax-advice violation should not be. `approved` is the field that
    actually gates pipeline status (see workers/tasks.py) — `flagged_issues`
    can legitimately carry a minor advisory note even on an approved letter
    (the model noting a soft caveat isn't the same as rejecting it), so this
    checks the gating field, not whether the list is merely non-empty. Only
    meaningful when a review actually ran."""
    if output["assessment"] is None:
        return True
    approved = output["assessment"].get("approved", True)
    return approved != case.expected["should_flag"]


SUITE = EvalSuite(
    name="compliance",
    description="Disclosure-lookup correctness (deterministic) + letter-content risk review",
    cases=CASES,
    run=run_case,
    scorers=[
        FunctionScorer("tax_statement_always_present", _tax_statement_always_present),
        FunctionScorer(
            "registered_flag_matches_reviewed_expectation",
            _registered_flag_matches_reviewed_expectation,
        ),
        FunctionScorer("review_ran_when_expected", _review_ran_when_expected),
        FunctionScorer("flag_outcome_matches", _flag_outcome_matches),
    ],
)
