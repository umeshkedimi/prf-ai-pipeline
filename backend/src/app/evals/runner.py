"""Executes an eval suite: every case, N times, scored and aggregated.

Repeating each case is not redundancy — `get_llm()` deliberately doesn't pin
temperature, so the same input genuinely produces different output run to run. A
single pass would report noise as signal. Scores are averaged across runs, and
any case whose score moved between runs is reported as flaky.
"""

import statistics
import time
from typing import Any

from app.core.logging import get_logger
from app.evals.types import EvalCase, EvalSuite, Metric, RunOutput, SuiteReport

log = get_logger(__name__)

MAX_FAILURES_RECORDED = 20


async def _execute(suite: EvalSuite, case: EvalCase, run_index: int) -> RunOutput:
    started = time.monotonic()
    try:
        output = await suite.run(case)
        return RunOutput(
            case_id=case.case_id,
            run_index=run_index,
            output=output,
            latency_ms=int((time.monotonic() - started) * 1000),
        )
    except Exception as exc:  # a broken case shouldn't abort the whole sweep
        log.warning("eval.case_failed", suite=suite.name, case=case.case_id, error=str(exc))
        return RunOutput(
            case_id=case.case_id,
            run_index=run_index,
            output=None,
            latency_ms=int((time.monotonic() - started) * 1000),
            error=f"{type(exc).__name__}: {exc}",
        )


async def run_suite(suite: EvalSuite, runs_per_case: int = 3) -> SuiteReport:
    started = time.monotonic()
    outputs: list[RunOutput] = []

    for case in suite.cases:
        for run_index in range(runs_per_case):
            outputs.append(await _execute(suite, case, run_index))

    by_case: dict[str, list[RunOutput]] = {}
    for out in outputs:
        by_case.setdefault(out.case_id, []).append(out)

    cases_by_id = {c.case_id: c for c in suite.cases}
    metrics: list[Metric] = []
    flaky: list[str] = []
    failures: list[dict[str, Any]] = []
    scorer_errors: list[dict[str, Any]] = []
    errors = [
        {"case_id": o.case_id, "run_index": o.run_index, "error": o.error}
        for o in outputs
        if o.error
    ]

    # --- per-case scorers, averaged over runs ---
    for scorer in suite.scorers:
        per_case_means: list[float] = []
        for case_id, case_runs in by_case.items():
            case = cases_by_id[case_id]
            run_scores: list[float] = []
            for out in case_runs:
                if not out.ok:
                    run_scores.append(0.0)  # an error is a failure, not a gap
                    continue
                try:
                    run_scores.append(float(await scorer(case, out.output)))
                except Exception as exc:
                    log.warning(
                        "eval.scorer_failed",
                        suite=suite.name,
                        scorer=scorer.name,
                        case=case_id,
                        error=str(exc),
                    )
                    scorer_errors.append(
                        {
                            "case_id": case_id,
                            "scorer": scorer.name,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    run_scores.append(0.0)

            mean = statistics.fmean(run_scores) if run_scores else 0.0
            per_case_means.append(mean)

            if len(set(run_scores)) > 1 and case_id not in flaky:
                flaky.append(case_id)
            if mean < 1.0 and len(failures) < MAX_FAILURES_RECORDED:
                failures.append(
                    {
                        "case_id": case_id,
                        "scorer": scorer.name,
                        "mean_score": round(mean, 3),
                        "run_scores": run_scores,
                        "expected": case.expected,
                    }
                )

        broken = sum(1 for e in scorer_errors if e["scorer"] == scorer.name)
        metrics.append(
            Metric(
                name=scorer.name,
                value=round(statistics.fmean(per_case_means), 4) if per_case_means else 0.0,
                note=(
                    f"UNRELIABLE — the scorer itself raised on {broken} run(s); "
                    "this number is not a measurement"
                    if broken
                    else None
                ),
            )
        )

    # --- cross-case aggregators ---
    pairs = [(cases_by_id[o.case_id], o.output) for o in outputs if o.ok]
    for aggregator in suite.aggregators:
        try:
            metrics.extend(aggregator(pairs))
        except Exception as exc:
            log.warning(
                "eval.aggregator_failed", suite=suite.name, aggregator=aggregator.name, error=str(exc)
            )

    latencies = [o.latency_ms for o in outputs if o.ok]
    if latencies:
        metrics.append(Metric(name="latency_ms_mean", value=round(statistics.fmean(latencies), 1)))
        metrics.append(Metric(name="latency_ms_max", value=float(max(latencies))))

    return SuiteReport(
        suite=suite.name,
        description=suite.description,
        runs_per_case=runs_per_case,
        case_count=len(suite.cases),
        duration_s=time.monotonic() - started,
        metrics=metrics,
        flaky_case_ids=sorted(flaky),
        failures=failures,
        errors=errors,
        scorer_errors=scorer_errors,
    )
