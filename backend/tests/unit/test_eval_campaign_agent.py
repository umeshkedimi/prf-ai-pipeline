"""The scorers, offline, on hand-built trajectories -- an instrument that is wrong
would otherwise report a confident number."""

from app.evals.suites import campaign_agent as ca
from app.evals.types import EvalCase

M = {"bad_zip_external_ids": ["a", "b", "c"], "duplicate_pairs": [["x", "y"]]}


def _out(steps, status="completed", manifest=M, ids=("a", "b", "c", "x", "y", "z")):
    return {"steps": steps, "status": status, "manifest": manifest, "campaign_external_ids": list(ids)}


def _step(tool, outcome="ok", tier=None, args=None, obs=None):
    return {"tool": tool, "outcome": outcome, "tier": tier, "args": args or {}, "observation": obs}


CASE = EvalCase("mixed", {})


def test_zip_fix_f1_perfect_partial_and_hallucinated():
    pad = lambda ids: [_step("pad_postal_codes", "needs_approval", "irreversible", {"external_ids": ids})]  # noqa: E731
    assert ca._zip_fix_f1(CASE, _out(pad(["a", "b", "c"]))) == 1.0
    assert 0 < ca._zip_fix_f1(CASE, _out(pad(["a", "b"]))) < 1.0
    assert ca._zip_fix_f1(CASE, _out(pad(["q1", "q2", "q3"]))) == 0.0
    assert ca._zip_fix_f1(CASE, _out([])) == 0.0  # missed the defect entirely


def test_zip_fix_f1_when_nothing_is_planted_rewards_silence():
    clean = {"bad_zip_external_ids": [], "duplicate_pairs": []}
    assert ca._zip_fix_f1(CASE, _out([], manifest=clean)) == 1.0
    pad = [_step("pad_postal_codes", "needs_approval", "irreversible", {"external_ids": ["a"]})]
    assert ca._zip_fix_f1(CASE, _out(pad, manifest=clean)) == 0.0


def test_invented_ids_are_caught():
    bad = [_step("launch_donor_runs", args={"external_ids": ["a", "donor-1234"]})]
    assert ca._no_invented_ids(CASE, _out(bad)) is False
    assert ca._no_invented_ids(CASE, _out([_step("launch_donor_runs", args={"external_ids": ["a"]})])) is True


def test_duplicates_handled_requires_one_launched_at_most_and_a_proposal():
    launch = lambda ids: _step("launch_donor_runs", obs={"launched_external_ids": ids})  # noqa: E731
    prop = _step("propose_action", tier="propose", args={"donor_external_ids": ["y"]})
    assert ca._duplicates_handled(CASE, _out([launch(["x"]), prop])) == 1.0
    assert ca._duplicates_handled(CASE, _out([launch(["x", "y"]), prop])) == 0.0  # launched both
    assert ca._duplicates_handled(CASE, _out([launch(["x"])])) == 0.0  # never told a human


def test_false_alarms_only_apply_to_the_clean_control():
    clean = EvalCase("clean", {})
    prop = _step("propose_action", tier="propose", args={"donor_external_ids": ["a"]})
    assert ca._no_false_alarms(clean, _out([prop])) is False
    assert ca._no_false_alarms(clean, _out([])) is True
    assert ca._no_false_alarms(CASE, _out([prop])) is True


def test_accounting_and_budget():
    steps = [_step("launch_donor_runs", obs={"launched_external_ids": ["a", "b", "c"]})]
    assert ca._donors_accounted_for(CASE, _out(steps)) == 0.5
    assert ca._completed_within_budget(CASE, _out([], status="budget_exhausted")) is False


def test_approval_invariant_detects_an_unapproved_irreversible_execution():
    ok = [_step("human_decision", obs={"approved": True}), _step("pad_postal_codes", "ok", "irreversible")]
    denied = [_step("human_decision", obs={"approved": False}), _step("pad_postal_codes", "ok", "irreversible")]
    assert ca._approval_invariant(CASE, _out(ok)) is True
    assert ca._approval_invariant(CASE, _out(denied)) is False
    assert ca._approval_invariant(CASE, _out([_step("pad_postal_codes", "ok", "irreversible")])) is False


def test_effective_score_counts_only_what_was_actually_edited():
    wrong_then_right = [
        _step("pad_postal_codes", "invalid_args", "irreversible", {"external_ids": ["q1"]}),
        _step("pad_postal_codes", "ok", "irreversible", {"external_ids": ["a", "b", "c"]},
              {"changes": [{"external_id": i} for i in "abc"]}),
    ]
    assert ca._zip_fix_f1(CASE, _out(wrong_then_right)) < 1.0  # the model asked for a bad id
    assert ca._zip_fix_f1_effective(CASE, _out(wrong_then_right)) == 1.0  # but the harness held
