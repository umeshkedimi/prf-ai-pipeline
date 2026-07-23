"""Trajectory eval — does a donor route through the whole pipeline correctly?

Component evals score one node's output in isolation. They structurally cannot
catch a routing regression: every agent can be individually correct while the
graph sends a donor down the wrong branch, skips an agent, or fails to pause
where a human is legally required. This suite scores the *path*.

The dataset is the README's outcomes table — the same eleven donors, each with
the terminal state and node sequence it must produce. Expensive: a full pipeline
run per case per repeat, so it's opt-in via --include-expensive.
"""

import uuid

from sqlalchemy import select

from app.db.models import AgentAuditLog
from app.db.session import db_session
from app.evals.scorers import FunctionScorer
from app.evals.suites._common import create_workflow_run, resolve_donor_id
from app.evals.types import EvalCase, EvalSuite
from app.graph.builder import build_graph

VERIFICATION_ONLY = ["fetch_core_data", "gather_context", "synthesize_verdict"]
THROUGH_ADDRESS = [*VERIFICATION_ONLY, "verify_address", "assess_and_normalize"]
FULL_PIPELINE = [*THROUGH_ADDRESS, "compute_rfm", "recommend_ask"]
# A major-gift ask pauses at human_review before personalize_letter ever runs
# (see route_after_recommendation) — FULL_PIPELINE is that donor's real path.
# Everyone below the threshold continues one step further.
PERSONALIZED_PIPELINE = [*FULL_PIPELINE, "personalize_letter"]
# Not registered to solicit in the donor's state pauses right after the
# disclosure lookup (see route_after_disclosures) — review_letter_compliance
# never runs, since there's no point judging letter wording for a letter that
# can't legally mail regardless.
COMPLIANCE_BLOCKED_PIPELINE = [*PERSONALIZED_PIPELINE, "gather_disclosures"]
# Registered in-state: the letter-content review runs, then the PDF is
# assembled and submitted to the print vendor — the pipeline's actual terminus.
COMPLIANT_PIPELINE = [*COMPLIANCE_BLOCKED_PIPELINE, "review_letter_compliance", "generate_pdf"]

# (external_id, terminal state, expected node path, scenario)
# terminal state is one of: "end" (reached END) or "paused:<stage>".
_LABELS: list[tuple[str, str, list[str], str]] = [
    ("d-0001", "end", COMPLIANT_PIPELINE, "clean donor runs the full pipeline"),
    ("d-0002", "end", COMPLIANT_PIPELINE, "duplicate flag is advisory, must not block"),
    ("d-0003", "end", COMPLIANT_PIPELINE, "duplicate flag is advisory, must not block"),
    ("d-0004", "end", VERIFICATION_ONLY, "do-not-contact stops before address work"),
    ("d-0005", "end", VERIFICATION_ONLY, "suppressed donor stops before address work"),
    ("d-0006", "end", COMPLIANT_PIPELINE, "suspicious flag advisory; outlier keeps ask modest"),
    ("d-0007", "paused:address", THROUGH_ADDRESS, "no address on file pauses for review"),
    ("d-0008", "end", COMPLIANT_PIPELINE, "clean recurring donor"),
    ("d-0009", "paused:address", THROUGH_ADDRESS, "moved, uncertain forwarding address"),
    ("d-0010", "paused:address", THROUGH_ADDRESS, "vacant address, no forwarding found"),
    (
        "d-0011",
        "paused:recommendation",
        FULL_PIPELINE,
        "clean address but major-gift ask pauses on the second stage",
    ),
    (
        "d-0012",
        "paused:compliance",
        COMPLIANCE_BLOCKED_PIPELINE,
        "clean donor blocked on state solicitation registration — third stage",
    ),
]

CASES = [
    EvalCase(
        case_id=external_id,
        inputs={"external_id": external_id},
        expected={"terminal": terminal, "path": path, "scenario": scenario},
    )
    for external_id, terminal, path, scenario in _LABELS
]


async def _audit_steps(workflow_run_id: str) -> list[str]:
    async with db_session() as session:
        result = await session.execute(
            select(AgentAuditLog.step)
            .where(AgentAuditLog.workflow_run_id == uuid.UUID(workflow_run_id))
            .order_by(AgentAuditLog.created_at)
        )
        return list(result.scalars().all())


async def run_case(case: EvalCase) -> dict:
    donor_id = await resolve_donor_id(case.inputs["external_id"])
    workflow_run_id = await create_workflow_run(donor_id)

    async with build_graph() as graph:
        result = await graph.ainvoke(
            {
                "workflow_run_id": workflow_run_id,
                "donor_id": str(donor_id),
                "campaign_id": None,
            },
            config={"configurable": {"thread_id": workflow_run_id}},
            durability="sync",
        )

    if interrupts := result.get("__interrupt__"):
        payload = interrupts[0].value
        terminal = f"paused:{payload.get('stage')}"
    else:
        terminal = "end"

    return {
        "terminal": terminal,
        "path": await _audit_steps(workflow_run_id),
        "workflow_run_id": workflow_run_id,
    }


def _terminal_matches(case: EvalCase, output: dict) -> bool:
    return output.get("terminal") == case.expected["terminal"]


def _path_matches(case: EvalCase, output: dict) -> bool:
    return output.get("path") == case.expected["path"]


def _reached_recommendation_when_expected(case: EvalCase, output: dict) -> bool:
    """A narrower check that survives minor path churn: if this donor is supposed
    to get an ask recommended, the recommendation nodes must have actually run."""
    if "recommend_ask" not in case.expected["path"]:
        return True
    return "recommend_ask" in (output.get("path") or [])


SUITE = EvalSuite(
    name="trajectory",
    description="End-to-end routing: terminal state and node path across the whole graph",
    cases=CASES,
    run=run_case,
    scorers=[
        FunctionScorer("terminal_state_correct", _terminal_matches),
        FunctionScorer("node_path_exact", _path_matches),
        FunctionScorer("reached_recommendation", _reached_recommendation_when_expected),
    ],
    expensive=True,
    # The most expensive suite in the set, and the one with least to gain from
    # repeats: routing was deliberately keyed off deterministic values
    # (route_after_recommendation reads the ask amount, not a model-produced
    # confidence), so running it 3x re-verifies a path that barely varies.
    default_runs=1,
)
