"""Retrieval eval — scores the RAG index independently of any generation.

This separation is the point. When a RAG answer is wrong there are two very
different causes: the right chunk never came back (retrieval), or it came back
and the model mishandled it (generation). The final output cannot distinguish
them, so retrieval is measured on its own against known-correct answers.

Cheap to run — embedding calls only, no chat model — which makes it the fastest
regression signal for any change to chunking, corpus content, or embedding model.
"""

from app.evals.scorers import mrr_scorer, recall_at_k_scorer
from app.evals.types import EvalCase, EvalSuite
from app.rag.retriever import retrieve

RETRIEVE_K = 5

# Each case: a question a fundraiser might genuinely need answered, paired with
# the document that actually contains the answer. Spans all five corpus docs so
# a regression isolated to one document still surfaces.
_CASES: list[tuple[str, str, str]] = [
    (
        "cost-of-care",
        "How much does it cost to care for one animal for a month?",
        "2025 Impact Report — Key Statistics",
    ),
    (
        "program-spend-ratio",
        "What percentage of donations actually goes to programs rather than overhead?",
        "2025 Impact Report — Key Statistics",
    ),
    (
        "animals-rehomed",
        "How many animals did we rehome last year and what was the placement rate?",
        "2025 Impact Report — Key Statistics",
    ),
    (
        "spay-neuter-cost",
        "How much does a single spay or neuter procedure cost to fund?",
        "Program Outcomes and Effectiveness",
    ),
    (
        "foster-network",
        "Does placing animals in foster homes reduce our costs?",
        "Program Outcomes and Effectiveness",
    ),
    (
        "lapsed-donor-ask",
        "How should I set the ask amount for a donor who has not given in a long time?",
        "Ask Strategy Guidelines",
    ),
    (
        "escalation-rules",
        "When should a recommended ask be escalated to a human reviewer?",
        "Ask Strategy Guidelines",
    ),
    # Known-ambiguous, retained deliberately: the aggregate "animals rescued and
    # rehomed" statistics chunk outranks the narrative story here, which is a
    # defensible reading of a query containing "rescued" and "animal". It is left
    # unsharpened so recall@1 stays honest — an eval tuned until every case passes
    # has no discriminating power left to detect a real regression.
    (
        "adoption-story",
        "Tell me about an animal that was rescued, treated, and then adopted.",
        "Donor-Funded Success Stories",
    ),
    (
        "major-donor-thanks",
        "How quickly should we acknowledge a major gift?",
        "Donor Stewardship Principles",
    ),
    (
        "honesty-in-appeals",
        "Is it acceptable to exaggerate need in an appeal to raise more money?",
        "Donor Stewardship Principles",
    ),
]

CASES = [
    EvalCase(case_id=case_id, inputs={"query": query}, expected={"expected_id": doc_title})
    for case_id, query, doc_title in _CASES
]


async def run_case(case: EvalCase) -> dict:
    chunks = await retrieve(case.inputs["query"], k=RETRIEVE_K)
    return {
        # ranked doc titles — the unit recall/MRR are scored against
        "retrieved_ids": [chunk["doc_title"] for chunk in chunks],
        "top_distance": chunks[0]["distance"] if chunks else None,
        "chunks": chunks,
    }


SUITE = EvalSuite(
    name="retrieval",
    description="Semantic search over campaign knowledge, scored apart from generation",
    cases=CASES,
    run=run_case,
    scorers=[
        recall_at_k_scorer("recall@1", k=1),
        recall_at_k_scorer("recall@3", k=3),
        recall_at_k_scorer("recall@5", k=5),
        mrr_scorer("mrr"),
    ],
)
