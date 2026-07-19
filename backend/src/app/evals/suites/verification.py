"""Donor Verification eval — classification accuracy and confidence calibration.

The seed dataset is already labeled: every donor was constructed to exercise a
specific eligibility scenario, so ground truth is known. 9 of 11 are eligible
and only 2 must be blocked, and that imbalance is exactly why accuracy is
reported alongside per-class recall rather than alone — a model that answered
"eligible" every time would score 82% while failing both cases that carry legal
consequences.

Runs the three verification nodes directly rather than through the graph:
cheaper, and it isolates this agent from downstream routing.
"""

from app.agents.donor_verification.agent import fetch_core_data, gather_context, synthesize_verdict
from app.evals.scorers import CalibrationAggregator, ClassificationAggregator, exact_match
from app.evals.suites._common import create_workflow_run, resolve_donor_id
from app.evals.types import EvalCase, EvalSuite

# (external_id, expected eligible, why — the label's justification, so a
# disagreement can be argued about rather than just noticed)
_LABELS: list[tuple[str, bool, str]] = [
    ("d-0001", True, "clean donor, no flags"),
    ("d-0002", True, "duplicate pair member — advisory only, does not block mailing"),
    ("d-0003", True, "duplicate pair member — advisory only"),
    ("d-0004", False, "do_not_contact flag set — a hard compliance rule"),
    ("d-0005", False, "on the suppression list (deceased)"),
    ("d-0006", True, "anomalous donation is suspicious, but the record is still mailable"),
    ("d-0007", True, "missing address is Address Intelligence's concern, not an eligibility bar"),
    ("d-0008", True, "clean recurring small-dollar donor"),
    ("d-0009", True, "clean record; the address problem is downstream"),
    ("d-0010", True, "clean record; the address problem is downstream"),
    ("d-0011", True, "long-tenured major donor, no flags"),
]

CASES = [
    EvalCase(
        case_id=external_id,
        inputs={"external_id": external_id},
        expected={"eligible": eligible, "rationale": rationale},
    )
    for external_id, eligible, rationale in _LABELS
]


async def run_case(case: EvalCase) -> dict:
    donor_id = await resolve_donor_id(case.inputs["external_id"])
    workflow_run_id = await create_workflow_run(donor_id)

    state = {
        "workflow_run_id": workflow_run_id,
        "donor_id": str(donor_id),
        "campaign_id": None,
    }
    state.update(await fetch_core_data(state))
    state.update(await gather_context(state))
    state.update(await synthesize_verdict(state))

    verdict = state["verification_result"]
    return {
        "eligible": verdict["eligible"],
        "confidence": verdict["confidence"],
        "is_duplicate": verdict.get("is_duplicate"),
        "is_suspicious": verdict.get("is_suspicious"),
        "reason": verdict.get("reason"),
        "workflow_run_id": workflow_run_id,
    }


SUITE = EvalSuite(
    name="verification",
    description="Donor eligibility classification + confidence calibration",
    cases=CASES,
    run=run_case,
    scorers=[exact_match("eligible_correct", "eligible")],
    aggregators=[
        ClassificationAggregator(
            output_key="eligible",
            expected_key="eligible",
            focus_label=False,
            focus_metric_name="recall_ineligible",
        ),
        CalibrationAggregator(
            confidence_key="confidence",
            output_key="eligible",
            expected_key="eligible",
        ),
    ],
)
