"""Campaign Personalization eval — prompt-rule compliance and groundedness.

Isolates `personalize_letter` from ask-selection: the recommended ask is a
deterministic stand-in (a fixed rung off the real ask ladder), not the output
of `recommend_ask`'s LLM call — that logic already has its own suite
(recommendation.py). Running it here too would double this suite's LLM cost
for no new signal.

Same two-kind-of-check split as recommendation.py: deterministic scorers pin
the rules the prompt states as absolute (tone/segment copied through
unchanged, cited sources real, the ask amount actually mentioned); the
LLM-as-judge scorer catches what no assertion can — an invented impact figure
or story beat not in the retrieved context.
"""

from app.agents.campaign_personalization.agent import (
    RETRIEVE_K,
    build_retrieval_query,
    personalize_letter,
)
from app.agents.campaign_personalization.rules import tone_for_segment
from app.agents.donation_recommendation.agent import compute_rfm
from app.agents.donor_verification.agent import fetch_core_data
from app.evals.scorers import FunctionScorer, GroundednessJudge
from app.evals.suites._common import create_workflow_run, resolve_donor_id
from app.evals.types import EvalCase, EvalSuite
from app.rag.retriever import retrieve

# Same donors as recommendation.py's suite, for the same reason: chosen to
# span distinct RFM segments rather than exercising one path five times.
_LABELS: list[tuple[str, str]] = [
    ("d-0001", "active donor, single clean gift"),
    ("d-0006", "active donor with a multi-gift history"),
    ("d-0008", "small-dollar recurring donor"),
    ("d-0009", "single modest gift"),
    ("d-0011", "major donor — personal, relationship-based tone"),
]

CASES = [
    EvalCase(case_id=external_id, inputs={"external_id": external_id}, expected={"scenario": scenario})
    for external_id, scenario in _LABELS
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
    state.update(await compute_rfm(state))
    rfm = state["recommendation_result"]

    # Deterministic stand-in for recommend_ask's output — see module docstring.
    ladder = rfm["ask_ladder"]
    recommended_ask = ladder[min(1, len(ladder) - 1)]
    state["recommendation_result"] = {
        **rfm,
        "recommended_ask": recommended_ask,
        "rationale": [f"Anchored on prior giving of ${rfm['anchor_gift']:.0f}."],
    }

    segment = rfm["segment"]
    expected_tone = tone_for_segment(segment)

    # Same query the node builds, so groundedness is judged against the context
    # the model actually received.
    context = await retrieve(build_retrieval_query(segment), k=RETRIEVE_K)

    state.update(await personalize_letter(state))
    personalization = state["personalization_result"]

    return {
        "personalization": personalization,
        "segment": segment,
        "expected_tone": expected_tone,
        "recommended_ask": recommended_ask,
        "context": context,
        "claims": personalization.get("rationale", []),
        "retrieved_titles": [chunk["doc_title"] for chunk in context],
        "facts": {"segment": segment, "tone": expected_tone, "recommended_ask": recommended_ask},
    }


# --- deterministic rule checks -------------------------------------------------


def _tone_and_segment_unchanged(case: EvalCase, output: dict) -> bool:
    """The prompt requires segment/tone be copied through verbatim from the
    deterministic lookup — the model judges the draft, not the tone."""
    p = output["personalization"]
    return p.get("segment") == output["segment"] and p.get("tone") == output["expected_tone"]


def _sources_valid(case: EvalCase, output: dict) -> bool:
    """Every cited title must be one that was actually retrieved — a citation
    to a real document the model was never shown is still a fabricated citation."""
    cited = output["personalization"].get("sources") or []
    if not cited:
        return True  # nothing cited is handled by groundedness, not here
    retrieved = set(output["retrieved_titles"])
    return all(title in retrieved for title in cited)


def _references_recommended_ask(case: EvalCase, output: dict) -> bool:
    """Hard rule 4: the letter must reference the recommended ask amount,
    tied to a concrete outcome — not an abstract appeal."""
    body = output["personalization"].get("body", "")
    return str(int(output["recommended_ask"])) in body


def _has_salutation_and_closing(case: EvalCase, output: dict) -> bool:
    p = output["personalization"]
    return bool(p.get("salutation")) and bool(p.get("closing_line"))


SUITE = EvalSuite(
    name="campaign_personalization",
    description="Letter-draft rule compliance (tone/segment fidelity, ask reference) + RAG groundedness",
    cases=CASES,
    run=run_case,
    scorers=[
        FunctionScorer("tone_and_segment_unchanged", _tone_and_segment_unchanged),
        FunctionScorer("sources_valid", _sources_valid),
        FunctionScorer("references_recommended_ask", _references_recommended_ask),
        FunctionScorer("has_salutation_and_closing", _has_salutation_and_closing),
        GroundednessJudge(
            "groundedness",
            claims_key="claims",
            context_key="context",
            facts_key="facts",
        ),
    ],
)
