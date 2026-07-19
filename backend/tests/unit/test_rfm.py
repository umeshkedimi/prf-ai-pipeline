"""Tests for the deterministic RFM scoring and ask-ladder construction.

Pure functions — no DB, no LLM, no network. This is the money math, so it's
pinned down precisely: these amounts end up on a letter asking a real person
for a specific number of dollars.
"""

from datetime import date

from app.agents.donation_recommendation.rfm import (
    SEGMENT_ACTIVE,
    SEGMENT_LAPSED,
    SEGMENT_LOYAL,
    SEGMENT_MAJOR,
    SEGMENT_PROSPECT,
    build_ask_ladder,
    compute_rfm,
)

TODAY = date(2026, 7, 19)


def _gift(amount: float, on: str) -> dict:
    return {"amount": amount, "donation_date": on}


def test_no_history_is_a_prospect_with_default_ladder():
    rfm = compute_rfm([], today=TODAY)
    assert rfm["segment"] == SEGMENT_PROSPECT
    assert rfm["frequency"] == 0
    assert rfm["recency_days"] is None
    assert rfm["rfm_score"] == 0.0
    assert build_ask_ladder(rfm) == [25.0, 50.0, 100.0]


def test_single_recent_gift_anchors_the_ladder_on_that_gift():
    rfm = compute_rfm([_gift(150.0, "2026-02-14")], today=TODAY)
    assert rfm["segment"] == SEGMENT_ACTIVE
    assert rfm["anchor_gift"] == 150.0
    assert rfm["frequency"] == 1
    assert rfm["recency_days"] == 155
    # typical -> step-up -> aspirational
    assert build_ask_ladder(rfm) == [150.0, 225.0, 375.0]


def test_long_lapsed_donor_gets_a_gentle_reconnecting_ladder():
    rfm = compute_rfm([_gift(100.0, "2024-01-05")], today=TODAY)
    assert rfm["segment"] == SEGMENT_LAPSED
    # gentler multipliers than an active donor's 1.5x/2.5x
    assert build_ask_ladder(rfm) == [100.0, 125.0, 175.0]


def test_frequent_recent_donor_is_loyal_and_invited_to_step_up():
    history = [
        _gift(40.0, "2025-10-01"),
        _gift(40.0, "2026-01-01"),
        _gift(40.0, "2026-04-01"),
        _gift(40.0, "2026-06-01"),
    ]
    rfm = compute_rfm(history, today=TODAY)
    assert rfm["segment"] == SEGMENT_LOYAL
    assert rfm["frequency"] == 4
    # loyal ladder starts above the usual gift rather than at it
    assert build_ask_ladder(rfm) == [50.0, 80.0, 120.0]


def test_sustained_high_value_giving_is_a_major_donor():
    history = [
        _gift(1000.0, "2024-05-01"),
        _gift(1500.0, "2025-05-01"),
        _gift(2000.0, "2026-05-01"),
    ]
    rfm = compute_rfm(history, today=TODAY, major_gift_threshold=1000.0)
    assert rfm["segment"] == SEGMENT_MAJOR
    assert rfm["outlier_gift_excluded"] is False
    ladder = build_ask_ladder(rfm)
    assert ladder == [2000.0, 3000.0, 5000.0]
    # every rung is major-gift sized, so this donor routes to human review
    assert all(amount >= 1000.0 for amount in ladder)


def test_anomalous_top_gift_is_excluded_from_the_anchor():
    """A donor whose history is $60/$75 plus one $50,000 outlier must not be
    promoted into the major-gift track — anchoring on that gift would turn a
    likely data-entry error or one-off windfall into a five-figure ask."""
    history = [
        _gift(60.0, "2024-03-01"),
        _gift(75.0, "2024-09-15"),
        _gift(50000.0, "2026-01-20"),
    ]
    rfm = compute_rfm(history, today=TODAY, major_gift_threshold=1000.0)

    assert rfm["outlier_gift_excluded"] is True
    assert rfm["highest_gift"] == 50000.0  # still recorded, for transparency
    assert rfm["anchor_gift"] == 75.0  # but the median is what we anchor on
    assert rfm["segment"] == SEGMENT_ACTIVE
    assert build_ask_ladder(rfm) == [75.0, 110.0, 190.0]


def test_genuine_growth_is_not_mistaken_for_an_outlier():
    """Steadily increasing gifts must keep their real anchor — the outlier rule
    should only fire on a gift that dwarfs the rest of the history."""
    history = [
        _gift(100.0, "2025-01-01"),
        _gift(150.0, "2025-07-01"),
        _gift(200.0, "2026-01-01"),
    ]
    rfm = compute_rfm(history, today=TODAY)
    assert rfm["outlier_gift_excluded"] is False
    assert rfm["anchor_gift"] == 200.0


def test_outlier_rule_needs_enough_history_to_judge():
    """With only two gifts a median is meaningless, so no exclusion happens."""
    history = [_gift(50.0, "2025-01-01"), _gift(9000.0, "2026-01-01")]
    rfm = compute_rfm(history, today=TODAY, major_gift_threshold=1000.0)
    assert rfm["outlier_gift_excluded"] is False
    assert rfm["anchor_gift"] == 9000.0


def test_ladder_amounts_are_rounded_to_tidy_figures():
    rfm = compute_rfm([_gift(137.0, "2026-06-01")], today=TODAY)
    ladder = build_ask_ladder(rfm)
    # nearest $5 below $500 (137*2.5 = 342.5 is an exact tie, resolved down to
    # 340 by banker's rounding), nearest $25 above
    assert ladder == [135.0, 205.0, 340.0]
    assert all(a % 5 == 0 for a in ladder)


def test_large_ladder_amounts_round_to_the_nearest_25():
    rfm = compute_rfm([_gift(1130.0, "2026-06-01")], today=TODAY, major_gift_threshold=1000.0)
    assert rfm["segment"] == SEGMENT_MAJOR
    ladder = build_ask_ladder(rfm)
    assert ladder == [1125.0, 1700.0, 2825.0]
    assert all(a % 25 == 0 for a in ladder)


def test_monetary_and_recency_feed_the_rfm_score():
    recent_big = compute_rfm([_gift(500.0, "2026-07-01")], today=TODAY)
    old_small = compute_rfm([_gift(10.0, "2023-01-01")], today=TODAY)
    assert recent_big["rfm_score"] > old_small["rfm_score"]
    assert 0.0 <= old_small["rfm_score"] <= 1.0
    assert 0.0 <= recent_big["rfm_score"] <= 1.0


def test_unparseable_or_incomplete_gifts_are_skipped():
    history = [_gift(100.0, "2026-01-01"), {"amount": None, "donation_date": "2026-02-01"}, {}]
    rfm = compute_rfm(history, today=TODAY)
    assert rfm["frequency"] == 1
    assert rfm["monetary_total"] == 100.0
