"""Console rendering and the JSON artifact.

The JSON is the point as much as the console output: a committed baseline makes
"did that prompt change help?" a diff rather than a memory exercise. Metrics are
reported with a delta against baseline so movement is visible at a glance.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.evals.store import current_git_sha
from app.evals.types import SuiteReport

RESULTS_DIR = Path(__file__).resolve().parents[3] / "evals" / "results"
LATEST_PATH = RESULTS_DIR / "latest.json"
BASELINE_PATH = RESULTS_DIR / "baseline.json"

# Metrics where a bigger number is worse, so the delta arrow must invert.
LOWER_IS_BETTER = {"expected_calibration_error", "latency_ms_mean", "latency_ms_max"}


def build_payload(reports: list[SuiteReport]) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "git_sha": current_git_sha(),
        "suites": {report.suite: report.to_dict() for report in reports},
    }


def write_latest(reports: list[SuiteReport]) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    payload = build_payload(reports)
    LATEST_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return LATEST_PATH


def promote_to_baseline(reports: list[SuiteReport]) -> Path:
    """Only overwrites the suites that were actually run, so a partial sweep
    can't silently erase the baseline for suites it skipped."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    baseline = load_baseline() or {"suites": {}}
    baseline["suites"].update({r.suite: r.to_dict() for r in reports})
    baseline["generated_at"] = datetime.now(UTC).isoformat()
    baseline["git_sha"] = current_git_sha()
    BASELINE_PATH.write_text(json.dumps(baseline, indent=2) + "\n", encoding="utf-8")
    return BASELINE_PATH


def load_baseline() -> dict[str, Any] | None:
    if not BASELINE_PATH.exists():
        return None
    try:
        return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _baseline_value(baseline: dict | None, suite: str, metric: str) -> float | None:
    if not baseline:
        return None
    for entry in baseline.get("suites", {}).get(suite, {}).get("metrics", []):
        if entry.get("name") == metric:
            return entry.get("value")
    return None


def _format_delta(metric_name: str, current: float, previous: float | None) -> str:
    if previous is None:
        return "     —"
    delta = current - previous
    if abs(delta) < 1e-9:
        return "     ="
    improved = delta < 0 if metric_name in LOWER_IS_BETTER else delta > 0
    return f"{'+' if delta > 0 else ''}{delta:.3f} {'▲' if improved else '▼'}"


def _render_detail(detail: dict[str, Any], indent: str) -> list[str]:
    lines: list[str] = []

    if "per_class" in detail:
        lines.append(f"{indent}per class:")
        lines.append(f"{indent}  {'label':<10}{'precision':>10}{'recall':>9}{'f1':>8}{'n':>5}")
        for label, stats in sorted(detail["per_class"].items()):
            lines.append(
                f"{indent}  {label:<10}{stats['precision']:>10.3f}{stats['recall']:>9.3f}"
                f"{stats['f1']:>8.3f}{stats['support']:>5}"
            )

    if "confusion" in detail and detail["confusion"]:
        pairs = ", ".join(f"{k}={v}" for k, v in sorted(detail["confusion"].items()))
        lines.append(f"{indent}confusion: {pairs}")

    if "buckets" in detail:
        if not detail["buckets"]:
            lines.append(f"{indent}(no confidence samples)")
        else:
            lines.append(f"{indent}reliability:")
            lines.append(
                f"{indent}  {'conf range':<12}{'n':>4}{'stated':>9}{'actual':>9}{'gap':>8}"
            )
            for row in detail["buckets"]:
                lines.append(
                    f"{indent}  {row['range']:<12}{row['count']:>4}{row['mean_confidence']:>9.3f}"
                    f"{row['accuracy']:>9.3f}{row['gap']:>8.3f}"
                )
    return lines


def render_console(reports: list[SuiteReport], baseline: dict | None = None) -> str:
    lines: list[str] = []
    width = 74

    for report in reports:
        lines.append("")
        lines.append("═" * width)
        lines.append(f"  {report.suite.upper()}")
        lines.append(f"  {report.description}")
        lines.append(
            f"  {report.case_count} cases × {report.runs_per_case} runs · {report.duration_s:.1f}s"
        )
        lines.append("═" * width)
        lines.append(f"  {'METRIC':<38}{'VALUE':>10}{'vs BASE':>14}")
        lines.append("  " + "─" * (width - 4))

        for metric in report.metrics:
            previous = _baseline_value(baseline, report.suite, metric.name)
            delta = _format_delta(metric.name, metric.value, previous)
            lines.append(f"  {metric.name:<38}{metric.value:>10.3f}{delta:>14}")
            if metric.note:
                lines.append(f"      ↳ {metric.note}")
            if metric.detail:
                lines.extend(_render_detail(metric.detail, "      "))

        if report.scorer_errors:
            lines.append("")
            lines.append(
                f"  ‼ BROKEN SCORERS ({len(report.scorer_errors)}) — the metrics above are "
                "not measurements:"
            )
            seen: set[str] = set()
            for err in report.scorer_errors:
                signature = f"{err['scorer']}|{err['error'][:80]}"
                if signature in seen:
                    continue
                seen.add(signature)
                lines.append(f"      {err['scorer']}: {err['error'][:160]}")

        if report.flaky_case_ids:
            lines.append("")
            lines.append(
                f"  ⚠ flaky across runs ({len(report.flaky_case_ids)}): "
                f"{', '.join(report.flaky_case_ids)}"
            )
            lines.append("      ↳ score varied between identical runs — model non-determinism")

        if report.failures:
            lines.append("")
            lines.append(f"  failures ({len(report.failures)} shown):")
            for failure in report.failures:
                lines.append(
                    f"      {failure['case_id']:<14} {failure['scorer']:<22}"
                    f" mean={failure['mean_score']:.2f} runs={failure['run_scores']}"
                )

        if report.errors:
            lines.append("")
            lines.append(f"  ✗ errors ({len(report.errors)}):")
            for err in report.errors[:5]:
                lines.append(f"      {err['case_id']} run {err['run_index']}: {err['error']}")

    lines.append("")
    if baseline is None:
        lines.append("  (no baseline yet — run with --set-baseline to record one)")
    lines.append("")
    return "\n".join(lines)
