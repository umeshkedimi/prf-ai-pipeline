"""Core types for the evaluation framework.

Evals are not tests. A test asks "does the code do what I wrote?" and answers
yes or no, permanently. An eval asks "does the system make good decisions?" and
answers with a score you track across prompt and model changes. Nothing here
raises on a bad result — it reports a number.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class EvalCase:
    """One labeled example: what to feed the system, and what we expect back."""

    case_id: str
    inputs: dict[str, Any]
    expected: dict[str, Any] = field(default_factory=dict)


@dataclass
class RunOutput:
    """The result of executing one case once. Cases run repeatedly because the
    models are non-deterministic, so `run_index` distinguishes attempts."""

    case_id: str
    run_index: int
    output: dict[str, Any] | None
    latency_ms: int
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.output is not None


@dataclass
class Metric:
    """A single reported number. `detail` carries structure that doesn't reduce
    to a scalar — a confusion matrix, a calibration table — for the report to
    render underneath the headline value."""

    name: str
    value: float
    detail: dict[str, Any] | None = None
    note: str | None = None


class Scorer(Protocol):
    """Per-case scoring, always normalized to 0.0-1.0 so unrelated scorers can
    share a report. Async because some scorers (LLM-as-judge) make model calls.

    This is the extension point: adding an agent means adding scorers, not
    touching the runner.
    """

    name: str

    async def __call__(self, case: EvalCase, output: dict[str, Any]) -> float: ...


class Aggregator(Protocol):
    """Cross-case metrics that can't be derived one case at a time — a confusion
    matrix needs every prediction, calibration needs the whole confidence
    distribution."""

    name: str

    def __call__(self, pairs: list[tuple[EvalCase, dict[str, Any]]]) -> list[Metric]: ...


@dataclass
class EvalSuite:
    """A dataset plus the way to run it and the ways to score it."""

    name: str
    description: str
    cases: list[EvalCase]
    run: Callable[[EvalCase], Awaitable[dict[str, Any]]]
    scorers: list[Scorer] = field(default_factory=list)
    aggregators: list[Aggregator] = field(default_factory=list)
    # Expensive suites (full-pipeline runs) are opt-in so the default sweep
    # stays cheap enough to run often.
    expensive: bool = False


@dataclass
class SuiteReport:
    suite: str
    description: str
    runs_per_case: int
    case_count: int
    duration_s: float
    metrics: list[Metric] = field(default_factory=list)
    # Cases whose score varied across repeat runs — the signal that a result is
    # sensitive to model non-determinism rather than genuinely stable.
    flaky_case_ids: list[str] = field(default_factory=list)
    # Cases that scored below 1.0, kept for eyeballing what actually went wrong.
    failures: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    # Scorers that raised rather than returning a score. Tracked separately from
    # `failures` on purpose: a crashed scorer contributes 0.0 to its metric and
    # is otherwise indistinguishable from a genuine low score, which silently
    # turns a broken instrument into a confident measurement.
    scorer_errors: list[dict[str, Any]] = field(default_factory=list)

    def metric(self, name: str) -> Metric | None:
        return next((m for m in self.metrics if m.name == name), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "suite": self.suite,
            "description": self.description,
            "runs_per_case": self.runs_per_case,
            "case_count": self.case_count,
            "duration_s": round(self.duration_s, 2),
            "metrics": [
                {"name": m.name, "value": m.value, "detail": m.detail, "note": m.note}
                for m in self.metrics
            ],
            "flaky_case_ids": self.flaky_case_ids,
            "failures": self.failures,
            "errors": self.errors,
            "scorer_errors": self.scorer_errors,
        }
