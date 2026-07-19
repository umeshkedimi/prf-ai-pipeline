"""Scoring primitives and the scorer/aggregator adapters built on them.

The pure functions at the top are the measurement instrument; they're unit
tested with hand-checked values in tests/unit/test_eval_scorers.py. An eval
framework whose arithmetic is wrong is worse than none at all, because it
reports confident numbers that happen to be false.
"""

import inspect
import json
import statistics
from collections.abc import Callable, Sequence
from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.core.llm import get_judge_llm
from app.evals.types import EvalCase, Metric

# --------------------------------------------------------------------------
# pure metric functions
# --------------------------------------------------------------------------


def recall_at_k(retrieved: Sequence[str], expected: str, k: int) -> float:
    """1.0 if the expected item appears in the top k retrieved, else 0.0.

    'Did the right chunk come back at all?' — the question that separates a
    retrieval failure from a generation failure.
    """
    return 1.0 if expected in list(retrieved)[:k] else 0.0


def reciprocal_rank(retrieved: Sequence[str], expected: str) -> float:
    """1/rank of the expected item (1-indexed), 0.0 if absent. Averaged across
    queries this is MRR: rewards ranking the right chunk first, not merely
    somewhere in the window."""
    for index, item in enumerate(retrieved, start=1):
        if item == expected:
            return 1.0 / index
    return 0.0


def classification_metrics(pairs: Sequence[tuple[Any, Any]]) -> dict[str, Any]:
    """Accuracy plus per-class precision/recall/F1 and a confusion matrix, from
    (expected, predicted) pairs.

    Per-class matters here more than accuracy: the seed set is 9 eligible vs 2
    ineligible, so a model that blindly answered "eligible" would score 82%
    accuracy while failing every case that carries legal risk.
    """
    if not pairs:
        return {"accuracy": 0.0, "per_class": {}, "confusion": {}, "support": 0}

    correct = sum(1 for expected, predicted in pairs if expected == predicted)
    accuracy = correct / len(pairs)

    confusion: dict[str, int] = {}
    for expected, predicted in pairs:
        confusion[f"{expected}->{predicted}"] = confusion.get(f"{expected}->{predicted}", 0) + 1

    per_class: dict[str, dict[str, float]] = {}
    for label in {expected for expected, _ in pairs} | {predicted for _, predicted in pairs}:
        true_positive = sum(1 for e, p in pairs if e == label and p == label)
        false_positive = sum(1 for e, p in pairs if e != label and p == label)
        false_negative = sum(1 for e, p in pairs if e == label and p != label)
        support = sum(1 for e, _ in pairs if e == label)

        precision = true_positive / (true_positive + false_positive) if (true_positive + false_positive) else 0.0
        recall = true_positive / (true_positive + false_negative) if (true_positive + false_negative) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

        per_class[str(label)] = {
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "support": support,
        }

    return {
        "accuracy": round(accuracy, 4),
        "per_class": per_class,
        "confusion": confusion,
        "support": len(pairs),
    }


def calibration_buckets(
    samples: Sequence[tuple[float, bool]], n_buckets: int = 10
) -> dict[str, Any]:
    """Bucket predictions by stated confidence and compare each bucket's mean
    confidence to its actual accuracy.

    A well-calibrated agent that says 0.9 is right about 90% of the time. This
    matters because the pipeline *routes* on confidence thresholds: if
    predictions at 0.85 are only 60% correct, everything above the address
    threshold auto-approves while being wrong 40% of the time — a failure no
    accuracy number would ever surface.

    Returns per-bucket rows plus expected calibration error (ECE): the
    support-weighted mean gap between confidence and accuracy.
    """
    if not samples:
        return {"ece": 0.0, "buckets": [], "support": 0}

    buckets: dict[int, list[tuple[float, bool]]] = {}
    for confidence, correct in samples:
        # clamp so confidence == 1.0 lands in the top bucket rather than past it
        index = min(int(confidence * n_buckets), n_buckets - 1)
        buckets.setdefault(index, []).append((confidence, correct))

    rows = []
    ece = 0.0
    for index in sorted(buckets):
        entries = buckets[index]
        mean_confidence = statistics.fmean(c for c, _ in entries)
        accuracy = statistics.fmean(1.0 if ok else 0.0 for _, ok in entries)
        gap = abs(accuracy - mean_confidence)
        ece += (len(entries) / len(samples)) * gap
        rows.append(
            {
                "range": f"{index / n_buckets:.1f}-{(index + 1) / n_buckets:.1f}",
                "count": len(entries),
                "mean_confidence": round(mean_confidence, 4),
                "accuracy": round(accuracy, 4),
                "gap": round(gap, 4),
            }
        )

    return {"ece": round(ece, 4), "buckets": rows, "support": len(samples)}


# --------------------------------------------------------------------------
# scorer adapters (per-case, 0.0-1.0)
# --------------------------------------------------------------------------


class FunctionScorer:
    """Wraps any (case, output) -> bool|float callable, sync or async."""

    def __init__(self, name: str, fn: Callable[[EvalCase, dict], Any]):
        self.name = name
        self._fn = fn

    async def __call__(self, case: EvalCase, output: dict) -> float:
        result = self._fn(case, output)
        if inspect.isawaitable(result):
            result = await result
        return float(result)


def exact_match(name: str, output_key: str, expected_key: str | None = None) -> FunctionScorer:
    key = expected_key or output_key
    return FunctionScorer(name, lambda case, output: output.get(output_key) == case.expected.get(key))


def recall_at_k_scorer(
    name: str, k: int, retrieved_key: str = "retrieved_ids", expected_key: str = "expected_id"
) -> FunctionScorer:
    return FunctionScorer(
        name,
        lambda case, output: recall_at_k(output.get(retrieved_key, []), case.expected[expected_key], k),
    )


def mrr_scorer(
    name: str = "mrr", retrieved_key: str = "retrieved_ids", expected_key: str = "expected_id"
) -> FunctionScorer:
    return FunctionScorer(
        name,
        lambda case, output: reciprocal_rank(output.get(retrieved_key, []), case.expected[expected_key]),
    )


# --------------------------------------------------------------------------
# LLM-as-judge
# --------------------------------------------------------------------------

GROUNDEDNESS_JUDGE_PROMPT = """You are evaluating whether generated text is \
grounded in the material it was given.

You receive THREE inputs:
1. SOURCE EXCERPTS — retrieved knowledge-base passages about the organization.
2. STRUCTURED FACTS — authoritative computed data about this specific donor \
(giving history, segment, scores, the pre-computed ask ladder). Treat these as \
verified ground truth, exactly as reliable as the excerpts.
3. GENERATED CLAIMS — the text to evaluate.

A claim is SUPPORTED if it traces to the excerpts, or to the structured facts, or \
follows directly from either. Both are legitimate sources.

A claim is UNSUPPORTED if it asserts something about the organization — a \
statistic, dollar figure, percentage, program outcome, or success story — that \
appears in neither input. A plausible-sounding number that is in neither place is \
exactly the failure you are looking for.

Do not flag a claim merely because it restates the donor's own data; check it \
against STRUCTURED FACTS first. Do not judge tone, persuasiveness, or whether the \
recommendation is a good idea — only whether its assertions are grounded.

Return supported=true if every assertion traces to one of the two sources."""


class GroundednessVerdict(BaseModel):
    supported: bool = Field(description="True only if every factual claim traces to the excerpts.")
    unsupported_claims: list[str] = Field(default_factory=list)
    reasoning: str = ""

    @field_validator("unsupported_claims", mode="before")
    @classmethod
    def _coerce_to_list(cls, value: Any) -> list[str]:
        """Smaller judge models frequently emit list fields as a JSON-encoded
        string rather than a real array. Strict validation rejected it, the
        scorer raised, and the harness recorded a confident 0.000 for a metric
        it had never actually measured. Be liberal about the shape here — the
        judgement we care about is the boolean."""
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value]
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return []
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                return [line.lstrip("-• ").strip() for line in text.splitlines() if line.strip()]
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
            return [str(parsed)]
        return [str(value)]


class GroundednessJudge:
    """Scores whether generated prose invented facts the retrieved context never
    contained — the check no deterministic assertion can make.

    Runs on a different model than the one being judged (see core/llm.py:
    get_judge_llm), because a model evaluating its own output is measurably
    biased toward approving it.
    """

    def __init__(
        self,
        name: str = "groundedness",
        claims_key: str = "claims",
        context_key: str = "context",
        facts_key: str | None = None,
    ):
        self.name = name
        self._claims_key = claims_key
        self._context_key = context_key
        # Structured data the generator legitimately drew on besides retrieval.
        # Without it the judge flags correctly-computed figures as fabricated,
        # because from its position they're simply unverifiable — a false
        # negative that reads exactly like a model hallucinating.
        self._facts_key = facts_key

    async def __call__(self, case: EvalCase, output: dict) -> float:
        claims = output.get(self._claims_key) or []
        context = output.get(self._context_key) or []
        if not claims:
            return 1.0  # nothing asserted, nothing to fabricate
        if not context:
            return 0.0  # claims made with no source material at all

        excerpts = "\n\n".join(
            f"[{chunk.get('doc_title', '?')}]\n{chunk.get('chunk_text', '')}" for chunk in context
        )
        claim_text = "\n".join(f"- {c}" for c in claims)

        sections = [f"SOURCE EXCERPTS:\n{excerpts}"]
        if self._facts_key:
            facts = output.get(self._facts_key)
            sections.append(f"STRUCTURED FACTS:\n{facts}")
        sections.append(f"GENERATED CLAIMS:\n{claim_text}")

        judge = get_judge_llm().with_structured_output(GroundednessVerdict)
        verdict: GroundednessVerdict = await judge.ainvoke(
            [
                {"role": "system", "content": GROUNDEDNESS_JUDGE_PROMPT},
                {"role": "user", "content": "\n\n".join(sections)},
            ]
        )
        return 1.0 if verdict.supported else 0.0


# --------------------------------------------------------------------------
# aggregators (cross-case)
# --------------------------------------------------------------------------


class ClassificationAggregator:
    """Emits accuracy plus per-class breakdown, and promotes one class's recall
    to a headline metric — for verification that's the ineligible class, where a
    miss means mailing someone who must not be mailed."""

    def __init__(
        self,
        output_key: str,
        expected_key: str,
        focus_label: Any = None,
        focus_metric_name: str = "recall_focus_class",
        name: str = "classification",
    ):
        self.name = name
        self._output_key = output_key
        self._expected_key = expected_key
        self._focus_label = focus_label
        self._focus_metric_name = focus_metric_name

    def __call__(self, pairs: list[tuple[EvalCase, dict]]) -> list[Metric]:
        observations = [
            (case.expected.get(self._expected_key), output.get(self._output_key))
            for case, output in pairs
        ]
        stats = classification_metrics(observations)
        metrics = [
            Metric(
                name="accuracy",
                value=stats["accuracy"],
                detail={"per_class": stats["per_class"], "confusion": stats["confusion"]},
            )
        ]
        if self._focus_label is not None:
            focus = stats["per_class"].get(str(self._focus_label), {})
            metrics.append(
                Metric(
                    name=self._focus_metric_name,
                    value=focus.get("recall", 0.0),
                    note=f"recall on {self._focus_label!r} — the error class that carries real-world risk",
                )
            )
        return metrics


class CalibrationAggregator:
    """Measures whether stated confidence matches observed correctness. The
    pipeline routes on confidence thresholds, so this is load-bearing rather
    than academic."""

    def __init__(
        self,
        confidence_key: str,
        output_key: str,
        expected_key: str,
        n_buckets: int = 10,
        name: str = "calibration",
    ):
        self.name = name
        self._confidence_key = confidence_key
        self._output_key = output_key
        self._expected_key = expected_key
        self._n_buckets = n_buckets

    def __call__(self, pairs: list[tuple[EvalCase, dict]]) -> list[Metric]:
        samples: list[tuple[float, bool]] = []
        for case, output in pairs:
            confidence = output.get(self._confidence_key)
            if confidence is None:
                continue
            correct = output.get(self._output_key) == case.expected.get(self._expected_key)
            samples.append((float(confidence), bool(correct)))

        stats = calibration_buckets(samples, self._n_buckets)
        note = (
            f"n={stats['support']} — enough to demonstrate the mechanism and spot gross "
            "miscalibration, not enough to set production thresholds from"
        )
        return [
            Metric(
                name="expected_calibration_error",
                value=stats["ece"],
                detail={"buckets": stats["buckets"]},
                note=note,
            )
        ]
