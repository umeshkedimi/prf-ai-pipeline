"""Control suite for the LLM-as-judge scorer — who watches the watchmen.

A groundedness score of 1.000 means nothing unless the judge can still detect
fabrication. These synthetic cases have known-correct verdicts and run on every
sweep, so a judge that drifts lenient (or, as happened here, one that flags
correctly-computed figures because it was only shown half the evidence) shows up
as a failing control rather than a silently wrong score on the real suite.

Two of these pin real bugs:
- `fabricated-statistic` fails if the judge goes lenient and stops catching
  invented impact numbers, which is the entire reason the scorer exists.
- `donor-data-restatement` fails if the judge is again denied the structured
  facts and starts flagging the deterministic RFM record as unsupported.

Cheap: judge-model calls only, no pipeline, no retrieval.
"""

from app.evals.scorers import FunctionScorer, GroundednessJudge
from app.evals.types import EvalCase, EvalSuite

_CONTEXT = [
    {
        "doc_title": "2025 Impact Report — Key Statistics",
        "chunk_text": (
            "It costs an average of $42 to provide a rescued animal with one week of food, "
            "shelter, and basic veterinary care. 87 cents of every dollar donated goes "
            "directly to programs."
        ),
    }
]

_FACTS = {
    "segment": "active",
    "last_gift": 150.0,
    "frequency": 1,
    "recency_days": 155,
    "ask_ladder": [150.0, 225.0, 375.0],
}

# (case_id, claims, should the judge call this grounded?)
_CONTROLS: list[tuple[str, list[str], bool]] = [
    (
        "grounded-from-excerpts",
        [
            "A gift of $225 covers several weeks of care at the published $42 weekly cost.",
            "The organization directs 87 cents of every dollar to programs.",
        ],
        True,
    ),
    (
        "donor-data-restatement",
        [
            "This donor last gave $150 and has a single gift on record.",
            "With a recency of 155 days they remain active, so a step-up to $225 is reasonable.",
        ],
        True,  # comes from STRUCTURED FACTS, not the excerpts — must not be flagged
    ),
    (
        "fabricated-statistic",
        [
            "Your $225 gift will feed 87 dogs for an entire year and fund our new veterinary wing.",
            "We placed 99.7% of animals within three days last year.",
        ],
        False,
    ),
    (
        "fabricated-story",
        ["Last month we rescued 400 puppies from a burning building using donor funds."],
        False,
    ),
    (
        "invented-dollar-figure",
        ["It costs just $9 to shelter an animal for a full month, per our annual report."],
        False,  # contradicts the $42/week figure that is actually in the excerpt
    ),
]

CASES = [
    EvalCase(
        case_id=case_id,
        inputs={"claims": claims},
        expected={"should_be_grounded": grounded},
    )
    for case_id, claims, grounded in _CONTROLS
]

_judge = GroundednessJudge(facts_key="facts")


async def run_case(case: EvalCase) -> dict:
    score = await _judge(
        case,
        {"claims": case.inputs["claims"], "context": _CONTEXT, "facts": _FACTS},
    )
    return {"judged_grounded": score == 1.0}


def _verdict_correct(case: EvalCase, output: dict) -> bool:
    return output["judged_grounded"] is case.expected["should_be_grounded"]


SUITE = EvalSuite(
    name="judge_control",
    description="Does the groundedness judge still detect fabrication? (controls the scorer itself)",
    cases=CASES,
    run=run_case,
    scorers=[FunctionScorer("judge_verdict_correct", _verdict_correct)],
)
