"""--case exists because --suite was the finest granularity available, so
debugging one scorer meant paying for a whole suite of LLM calls."""

import pytest

from app.evals.suites import ALL_SUITES, select_cases
from app.evals.types import EvalCase, EvalSuite


async def _noop(case):
    return {}


def _suite(name: str, case_ids: list[str]) -> EvalSuite:
    return EvalSuite(
        name=name,
        description=name,
        cases=[EvalCase(case_id=cid, inputs={}, expected={}) for cid in case_ids],
        run=_noop,
    )


SUITES = [_suite("alpha", ["a-1", "a-2", "a-3"]), _suite("beta", ["b-1", "b-2"])]


def test_no_filter_returns_every_suite_untouched():
    assert select_cases(SUITES, None) is SUITES
    assert select_cases(SUITES, []) is SUITES


def test_filters_to_the_named_case():
    [suite] = select_cases(SUITES, ["a-2"])
    assert suite.name == "alpha"
    assert [c.case_id for c in suite.cases] == ["a-2"]


def test_suites_with_no_matching_case_drop_out():
    """Otherwise a filtered run would still pay for every other suite's setup
    and report them as zero-case sweeps."""
    selected = select_cases(SUITES, ["b-1"])
    assert [s.name for s in selected] == ["beta"]


def test_selecting_across_suites_keeps_both():
    selected = select_cases(SUITES, ["a-1", "b-2"])
    assert [(s.name, [c.case_id for c in s.cases]) for s in selected] == [
        ("alpha", ["a-1"]),
        ("beta", ["b-2"]),
    ]


def test_unknown_case_id_fails_loudly():
    """A typo would otherwise run nothing and report a clean sweep — the exact
    confidently-wrong result this framework exists to prevent."""
    with pytest.raises(SystemExit, match="a-9"):
        select_cases(SUITES, ["a-9"])


def test_filtering_does_not_mutate_the_registered_suite():
    """The suites are module-level singletons; narrowing one in place would
    silently shrink it for every later run in the same process."""
    before = len(SUITES[0].cases)
    select_cases(SUITES, ["a-1"])
    assert len(SUITES[0].cases) == before


def test_trajectory_defaults_to_a_single_run():
    """Routing is keyed off deterministic values, so repeats on the most
    expensive suite re-verify a path that barely varies."""
    assert ALL_SUITES["trajectory"].default_runs == 1
    assert ALL_SUITES["retrieval"].default_runs is None
