"""Donation Recommendation eval — prompt-rule compliance and groundedness.

Two kinds of check, deliberately separated:

Deterministic scorers verify the rules the prompt states as absolute — the ask
must come from the computed ladder, the deterministic fields must survive
untouched, cited sources must be real. These should sit at 1.000; anything less
is a live prompt violation shipping real dollar amounts, not a soft quality
signal.

The LLM-as-judge scorer covers what no assertion can: whether the rationale
invented an impact statistic that was never in the retrieved context. It runs on
a different model than the one that generated the text (see core/llm.py), since
a model grading its own output is measurably biased toward approving it.
"""

from app.agents.donation_recommendation.agent import (
    RETRIEVE_K,
    build_retrieval_query,
    compute_rfm,
    recommend_ask,
)
from app.core.config import get_settings
from app.evals.scorers import FunctionScorer, GroundednessJudge
from app.evals.suites._common import create_workflow_run, resolve_donor_id
from app.evals.types import EvalCase, EvalSuite
from app.rag.retriever import retrieve

# Donors chosen to span distinct RFM segments, so the suite exercises different
# ask-ladder shapes rather than the same path five times.
_LABELS: list[tuple[str, str]] = [
    ("d-0001", "active donor, single clean gift"),
    ("d-0006", "anomalous $50k outlier that must stay excluded from the anchor"),
    ("d-0008", "small-dollar recurring donor"),
    ("d-0009", "single modest gift"),
    ("d-0011", "major donor, ladder in major-gift range"),
]

CASES = [
    EvalCase(case_id=external_id, inputs={"external_id": external_id}, expected={"scenario": scenario})
    for external_id, scenario in _LABELS
]


async def run_case(case: EvalCase) -> dict:
    donor_id = await resolve_donor_id(case.inputs["external_id"])
    workflow_run_id = await create_workflow_run(donor_id)

    # gather_context normally supplies donation_history; compute_rfm falls back to
    # the CRM tool when it's absent, which is what we want for an isolated run.
    state: dict = {
        "workflow_run_id": workflow_run_id,
        "donor_id": str(donor_id),
        "campaign_id": None,
        "donor_profile": {},
    }
    state.update(await compute_rfm(state))
    rfm = dict(state["recommendation_result"])  # snapshot before the LLM touches it

    # Same query the node builds, so groundedness is judged against the context
    # the model actually received.
    context = await retrieve(build_retrieval_query(rfm["segment"]), k=RETRIEVE_K)

    state.update(await recommend_ask(state))
    recommendation = state["recommendation_result"]

    return {
        "recommendation": recommendation,
        "deterministic_rfm": rfm,
        "context": context,
        "claims": recommendation.get("rationale", []),
        "retrieved_titles": [chunk["doc_title"] for chunk in context],
    }


# --- deterministic rule checks -------------------------------------------------


def _ask_in_ladder(case: EvalCase, output: dict) -> bool:
    rec = output["recommendation"]
    return rec.get("recommended_ask") in (rec.get("ask_ladder") or [])


def _fields_unchanged(case: EvalCase, output: dict) -> bool:
    """The prompt requires the deterministic fields be copied through verbatim.
    If the model edits them, the 'money is computed, not generated' guarantee is
    silently broken even though the output still validates."""
    rec, rfm = output["recommendation"], output["deterministic_rfm"]
    return all(
        rec.get(field) == rfm.get(field)
        for field in ("segment", "ask_ladder", "anchor_gift", "rfm_score", "frequency")
    )


def _sources_valid(case: EvalCase, output: dict) -> bool:
    """Every cited title must be one that was actually retrieved — a citation to
    a real document the model was never shown is still a fabricated citation."""
    cited = output["recommendation"].get("sources") or []
    if not cited:
        return True  # nothing cited is handled by groundedness, not here
    retrieved = set(output["retrieved_titles"])
    return all(title in retrieved for title in cited)


def _outlier_respected(case: EvalCase, output: dict) -> bool:
    """d-0006 specifically: the $50,000 anomaly must stay out of the anchor and
    the ladder must remain below the major-gift threshold. Pins the regression
    that once produced a $125,000 ask."""
    if case.case_id != "d-0006":
        return True
    rec = output["recommendation"]
    threshold = get_settings().major_gift_ask_threshold
    return bool(rec.get("outlier_gift_excluded")) and max(rec.get("ask_ladder") or [0]) < threshold


def _ask_is_positive(case: EvalCase, output: dict) -> bool:
    return (output["recommendation"].get("recommended_ask") or 0) > 0


SUITE = EvalSuite(
    name="recommendation",
    description="Ask-selection rule compliance + RAG groundedness (judged by a separate model)",
    cases=CASES,
    run=run_case,
    scorers=[
        FunctionScorer("ask_in_ladder", _ask_in_ladder),
        FunctionScorer("fields_unchanged", _fields_unchanged),
        FunctionScorer("sources_valid", _sources_valid),
        FunctionScorer("outlier_respected", _outlier_respected),
        FunctionScorer("ask_is_positive", _ask_is_positive),
        # The rationale legitimately draws on two sources — retrieved knowledge
        # AND the deterministic RFM record — so the judge is given both.
        GroundednessJudge(
            "groundedness",
            claims_key="claims",
            context_key="context",
            facts_key="deterministic_rfm",
        ),
    ],
)
