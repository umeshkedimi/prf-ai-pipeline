"""rfm.choose_ask: the segment -> rung policy and the evidence-based confidence."""

from datetime import date

import pytest

from app.agents.donation_recommendation.rfm import build_ask_ladder, choose_ask, compute_rfm

TODAY = date(2026, 9, 1)


def _rfm(history, **kw):
    rfm = compute_rfm(history, today=TODAY, **kw)
    rfm["ask_ladder"] = build_ask_ladder(rfm)
    return rfm


def _gift(amount, when):
    return {"donation_date": when, "amount": amount}


def test_the_ask_is_always_a_rung_of_the_ladder():
    for history in ([], [_gift(100, "2026-08-01")], [_gift(50, "2022-01-01")],
                    [_gift(g, f"2026-0{m}-01") for g, m in [(80, 1), (90, 3), (100, 5), (120, 7)]]):
        rfm = _rfm(history)
        assert choose_ask(rfm)["recommended_ask"] in rfm["ask_ladder"]


@pytest.mark.parametrize(
    "history, rung",
    [
        ([], 0),  # prospect: gentle
        ([_gift(100, "2022-01-01")], 0),  # lapsed: gentle
        ([_gift(100, "2026-08-01")], 1),  # active: step up
        ([_gift(g, f"2026-0{m}-01") for g, m in [(80, 1), (90, 3), (100, 5), (120, 7)]], 1),  # loyal
    ],
)
def test_segment_decides_the_rung(history, rung):
    rfm = _rfm(history)
    assert choose_ask(rfm)["recommended_ask"] == rfm["ask_ladder"][rung]


def test_the_aspirational_rung_is_never_led_with():
    for history in ([], [_gift(100, "2022-01-01")], [_gift(100, "2026-08-01")], [_gift(2000, "2026-08-01")]):
        rfm = _rfm(history, major_gift_threshold=1000.0)
        assert choose_ask(rfm)["recommended_ask"] != rfm["ask_ladder"][-1]


def test_confidence_tracks_the_strength_of_the_evidence():
    thin = choose_ask(_rfm([_gift(100, "2026-08-01")]))["confidence"]
    four = [_gift(g, f"2026-0{m}-01") for g, m in [(80, 1), (90, 3), (100, 5), (120, 7)]]
    assert choose_ask(_rfm(four))["confidence"] > thin
    assert choose_ask(_rfm([]))["confidence"] < thin  # no history at all


def test_an_excluded_outlier_caps_confidence_and_says_so():
    history = [_gift(100, "2026-07-01"), _gift(110, "2026-05-01"), _gift(120, "2026-03-01"),
               _gift(9000, "2026-01-01")]
    rfm = _rfm(history)
    assert rfm["outlier_gift_excluded"]
    out = choose_ask(rfm)
    assert out["confidence"] <= 0.65 and any("anomalous" in line for line in out["rationale"])


def test_same_input_same_output():
    rfm = _rfm([_gift(100, "2026-08-01")])
    assert choose_ask(rfm) == choose_ask(rfm)
