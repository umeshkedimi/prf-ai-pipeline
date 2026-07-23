"""Suite registry. Adding an eval for a new agent means adding one module here
and registering it — the runner, scorers, reporting, and persistence are shared."""

from dataclasses import replace

from app.evals.suites import (
    campaign_personalization,
    compliance,
    judge_control,
    pdf_generation,
    recommendation,
    retrieval,
    trajectory,
    verification,
)
from app.evals.types import EvalSuite

ALL_SUITES: dict[str, EvalSuite] = {
    suite.name: suite
    for suite in (
        # judge_control runs first: if the judge itself is broken, the
        # groundedness number from the recommendation suite is meaningless.
        judge_control.SUITE,
        retrieval.SUITE,
        verification.SUITE,
        recommendation.SUITE,
        campaign_personalization.SUITE,
        compliance.SUITE,
        pdf_generation.SUITE,
        trajectory.SUITE,
    )
}

# Suites that run by default — the expensive ones (full-pipeline sweeps) are
# opt-in so the common case stays cheap enough to run on every prompt change.
DEFAULT_SUITES = [name for name, suite in ALL_SUITES.items() if not suite.expensive]


def resolve(names: list[str] | None, include_expensive: bool) -> list[EvalSuite]:
    if names:
        unknown = [n for n in names if n not in ALL_SUITES]
        if unknown:
            raise SystemExit(
                f"unknown suite(s): {', '.join(unknown)}. available: {', '.join(ALL_SUITES)}"
            )
        return [ALL_SUITES[n] for n in names]

    selected = list(DEFAULT_SUITES)
    if include_expensive:
        selected = list(ALL_SUITES)
    return [ALL_SUITES[n] for n in selected]


def select_cases(suites: list[EvalSuite], case_ids: list[str] | None) -> list[EvalSuite]:
    """Narrow suites to specific cases, so debugging one scorer costs one case
    rather than a whole suite. Suites with no matching case drop out entirely."""
    if not case_ids:
        return suites

    wanted = set(case_ids)
    narrowed = [
        replace(suite, cases=[c for c in suite.cases if c.case_id in wanted])
        for suite in suites
        if any(c.case_id in wanted for c in suite.cases)
    ]
    # A typo'd case id would otherwise run nothing and report a clean sweep.
    found = {c.case_id for suite in narrowed for c in suite.cases}
    if missing := wanted - found:
        raise SystemExit(f"unknown case id(s): {', '.join(sorted(missing))}")
    return narrowed
