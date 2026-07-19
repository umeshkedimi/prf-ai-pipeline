"""Tests for the evaluation framework's own arithmetic.

The eval harness is a measuring instrument. If its metrics are wrong it doesn't
fail loudly — it reports confident numbers that happen to be false, and every
decision made from them is wrong too. So the pure scoring functions get real
tests with hand-computed expected values.
"""

import math

from app.evals.scorers import (
    calibration_buckets,
    classification_metrics,
    recall_at_k,
    reciprocal_rank,
)

# --- recall@k ---


def test_recall_at_k_hit_within_window():
    retrieved = ["doc-a", "doc-b", "doc-c"]
    assert recall_at_k(retrieved, "doc-a", k=1) == 1.0
    assert recall_at_k(retrieved, "doc-c", k=3) == 1.0


def test_recall_at_k_miss_outside_window():
    """The expected doc is retrieved, but ranked below the cutoff — that's a
    miss at k=2, and conflating it with a hit would hide real degradation."""
    retrieved = ["doc-a", "doc-b", "doc-c"]
    assert recall_at_k(retrieved, "doc-c", k=2) == 0.0


def test_recall_at_k_absent_entirely():
    assert recall_at_k(["doc-a", "doc-b"], "doc-z", k=5) == 0.0


def test_recall_at_k_on_empty_retrieval():
    assert recall_at_k([], "doc-a", k=3) == 0.0


# --- reciprocal rank / MRR ---


def test_reciprocal_rank_is_one_over_position():
    retrieved = ["doc-a", "doc-b", "doc-c", "doc-d"]
    assert reciprocal_rank(retrieved, "doc-a") == 1.0
    assert reciprocal_rank(retrieved, "doc-b") == 0.5
    assert reciprocal_rank(retrieved, "doc-d") == 0.25


def test_reciprocal_rank_zero_when_absent():
    assert reciprocal_rank(["doc-a"], "doc-z") == 0.0


# --- classification ---


def test_classification_accuracy_and_confusion():
    pairs = [(True, True), (True, True), (False, False), (True, False)]
    stats = classification_metrics(pairs)

    assert stats["accuracy"] == 0.75
    assert stats["support"] == 4
    assert stats["confusion"]["True->True"] == 2
    assert stats["confusion"]["False->False"] == 1
    assert stats["confusion"]["True->False"] == 1


def test_per_class_precision_recall_hand_checked():
    # 3 actually-True (2 predicted True, 1 predicted False), 2 actually-False
    # (both predicted False, plus 1 True wrongly predicted False)
    pairs = [(True, True), (True, True), (True, False), (False, False), (False, False)]
    stats = classification_metrics(pairs)

    true_stats = stats["per_class"]["True"]
    assert true_stats["precision"] == 1.0  # 2 predicted True, both correct
    assert round(true_stats["recall"], 4) == round(2 / 3, 4)  # 2 of 3 actual Trues found
    assert true_stats["support"] == 3

    false_stats = stats["per_class"]["False"]
    assert round(false_stats["precision"], 4) == round(2 / 3, 4)  # 3 predicted False, 2 correct
    assert false_stats["recall"] == 1.0  # both actual Falses found
    assert false_stats["support"] == 2


def test_accuracy_alone_hides_the_dangerous_error():
    """The exact failure mode this framework exists to catch: a model that always
    answers 'eligible' scores well on accuracy while missing every case that
    carries legal risk. Accuracy 0.82, recall on the risky class 0.0."""
    pairs = [(True, True)] * 9 + [(False, True)] * 2  # 9 eligible, 2 ineligible, all predicted eligible
    stats = classification_metrics(pairs)

    assert round(stats["accuracy"], 4) == round(9 / 11, 4)  # looks respectable
    assert stats["per_class"]["False"]["recall"] == 0.0  # catches nothing that matters


def test_classification_on_empty_input():
    stats = classification_metrics([])
    assert stats["accuracy"] == 0.0
    assert stats["per_class"] == {}


# --- calibration ---


def test_perfect_calibration_has_zero_error():
    """10 samples at confidence 0.9, exactly 9 correct — stated confidence
    matches observed accuracy, so ECE is 0."""
    samples = [(0.9, True)] * 9 + [(0.9, False)]
    stats = calibration_buckets(samples)

    assert stats["ece"] == 0.0
    assert len(stats["buckets"]) == 1
    bucket = stats["buckets"][0]
    assert bucket["count"] == 10
    assert bucket["mean_confidence"] == 0.9
    assert bucket["accuracy"] == 0.9


def test_overconfidence_is_measured():
    """Claims 0.9, right only half the time — a 0.4 gap. This is the production
    bug shape: everything above the routing threshold auto-approves while being
    wrong far more often than the confidence implies."""
    samples = [(0.9, True)] * 5 + [(0.9, False)] * 5
    stats = calibration_buckets(samples)

    assert math.isclose(stats["ece"], 0.4, abs_tol=1e-9)
    assert stats["buckets"][0]["gap"] == 0.4


def test_ece_is_weighted_by_bucket_support():
    """A badly-calibrated bucket holding 2 samples must not outweigh a
    well-calibrated one holding 8."""
    samples = [(0.9, True)] * 9 + [(0.9, False)]  # 10 samples, gap 0.0
    samples += [(0.1, True)] * 10  # 10 samples, conf 0.1 but always right -> gap 0.9
    stats = calibration_buckets(samples)

    # (10/20)*0.0 + (10/20)*0.9 = 0.45
    assert math.isclose(stats["ece"], 0.45, abs_tol=1e-9)


def test_confidence_of_one_lands_in_the_top_bucket():
    """Guards the clamp: conf == 1.0 would otherwise index past the last bucket."""
    stats = calibration_buckets([(1.0, True), (1.0, True)], n_buckets=10)
    assert len(stats["buckets"]) == 1
    assert stats["buckets"][0]["range"] == "0.9-1.0"
    assert stats["ece"] == 0.0


def test_calibration_on_empty_input():
    stats = calibration_buckets([])
    assert stats["ece"] == 0.0
    assert stats["buckets"] == []


# --- judge output robustness ---
# The judge runs on a smaller/cheaper model, which is less reliable at emitting
# well-formed structured output. Strict validation here once turned a broken
# scorer into a confident 0.000 for a metric that was never actually measured.


def test_judge_verdict_accepts_a_json_encoded_list():
    from app.evals.scorers import GroundednessVerdict

    verdict = GroundednessVerdict(supported=False, unsupported_claims='["claim one", "claim two"]')
    assert verdict.unsupported_claims == ["claim one", "claim two"]


def test_judge_verdict_accepts_a_newline_bulleted_string():
    from app.evals.scorers import GroundednessVerdict

    verdict = GroundednessVerdict(supported=False, unsupported_claims="- first\n- second")
    assert verdict.unsupported_claims == ["first", "second"]


def test_judge_verdict_accepts_a_real_list_unchanged():
    from app.evals.scorers import GroundednessVerdict

    verdict = GroundednessVerdict(supported=True, unsupported_claims=["a", "b"])
    assert verdict.unsupported_claims == ["a", "b"]


def test_judge_verdict_handles_empty_and_null():
    from app.evals.scorers import GroundednessVerdict

    assert GroundednessVerdict(supported=True, unsupported_claims="").unsupported_claims == []
    assert GroundednessVerdict(supported=True, unsupported_claims=None).unsupported_claims == []
