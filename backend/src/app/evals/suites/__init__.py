"""Suite registry. Adding an eval for a new agent means adding one module here
and registering it — the runner, scorers, reporting, and persistence are shared."""

from app.evals.suites import judge_control, recommendation, retrieval, trajectory, verification
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
