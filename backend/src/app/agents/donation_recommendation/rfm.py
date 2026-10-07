"""RFM scoring, the ask ladder, and the rung-choosing policy.

Pure functions — no DB, no LLM, no I/O — so the money math is reproducible and
unit-testable in isolation. No model is involved anywhere in deciding what a donor
is asked for."""

import statistics
from datetime import date

# A top gift this many times the median is treated as an anomaly rather than a
# capacity signal — see compute_rfm's anchor logic.
OUTLIER_MULTIPLE = 5.0

# Segment names are stable identifiers used by the ask-ladder and prompts.
SEGMENT_PROSPECT = "prospect"  # no usable giving history
SEGMENT_LAPSED = "lapsed"      # gave before, but not recently
SEGMENT_ACTIVE = "active"      # recent, modest cadence
SEGMENT_LOYAL = "loyal"        # frequent, recent
SEGMENT_MAJOR = "major"        # a major-gift-sized prior gift


def _parse(donation_history: list[dict]) -> list[tuple[date, float]]:
    parsed: list[tuple[date, float]] = []
    for d in donation_history or []:
        raw_date = d.get("donation_date")
        raw_amount = d.get("amount")
        if raw_date is None or raw_amount is None:
            continue
        parsed.append((date.fromisoformat(str(raw_date)[:10]), float(raw_amount)))
    return parsed


def _round_to(amount: float) -> float:
    """Round asks to tidy figures: nearest $5 under $500, nearest $25 above."""
    step = 5 if amount < 500 else 25
    return float(round(amount / step) * step)


def compute_rfm(
    donation_history: list[dict],
    today: date,
    major_gift_threshold: float = 1000.0,
) -> dict:
    """Recency / Frequency / Monetary summary plus a derived donor segment.

    Returns recency_days (None if no history), frequency, monetary_total,
    last_gift, highest_gift, the anchor_gift the ask ladder is built from, an
    interpretable 0-1 rfm_score, and the segment.

    The ladder anchors on `anchor_gift`, not blindly on the largest gift: if the
    top gift is an extreme outlier against the rest of the history (the pattern
    Donor Verification separately flags as suspicious), anchoring on it would
    turn one anomalous or fraudulent donation into a wildly inflated ask. In
    that case we fall back to the median gift and record the fact in
    `outlier_gift_excluded` so the decision stays visible in the audit trail.
    """
    gifts = _parse(donation_history)
    frequency = len(gifts)

    if frequency == 0:
        return {
            "recency_days": None,
            "frequency": 0,
            "monetary_total": 0.0,
            "last_gift": 0.0,
            "highest_gift": 0.0,
            "anchor_gift": 0.0,
            "outlier_gift_excluded": False,
            "rfm_score": 0.0,
            "segment": SEGMENT_PROSPECT,
        }

    gifts.sort(key=lambda g: g[0], reverse=True)
    last_date, last_gift = gifts[0]
    recency_days = (today - last_date).days
    monetary_total = round(sum(amount for _, amount in gifts), 2)
    highest_gift = max(amount for _, amount in gifts)

    # Sub-scores on a 1-5 scale, higher = stronger.
    if recency_days <= 90:
        r = 5
    elif recency_days <= 180:
        r = 4
    elif recency_days <= 365:
        r = 3
    elif recency_days <= 540:
        r = 2
    else:
        r = 1
    f = min(5, frequency)
    if highest_gift >= major_gift_threshold:
        m = 5
    elif highest_gift >= 250:
        m = 4
    elif highest_gift >= 100:
        m = 3
    elif highest_gift >= 50:
        m = 2
    else:
        m = 1
    rfm_score = round((r + f + m) / 15, 3)

    # Robust anchor: ignore a lone extreme top gift (needs >=3 gifts to judge a
    # median meaningfully). Segment is derived from the anchor, not the raw max,
    # so an anomaly can't promote a modest donor into the major-gift track.
    median_gift = statistics.median(amount for _, amount in gifts)
    outlier_gift_excluded = frequency >= 3 and highest_gift > OUTLIER_MULTIPLE * median_gift
    anchor_gift = median_gift if outlier_gift_excluded else last_gift

    if anchor_gift >= major_gift_threshold:
        segment = SEGMENT_MAJOR
    elif recency_days > 540:
        segment = SEGMENT_LAPSED
    elif frequency >= 4 and recency_days <= 365:
        segment = SEGMENT_LOYAL
    else:
        segment = SEGMENT_ACTIVE

    return {
        "recency_days": recency_days,
        "frequency": frequency,
        "monetary_total": monetary_total,
        "last_gift": round(last_gift, 2),
        "highest_gift": round(highest_gift, 2),
        "anchor_gift": round(anchor_gift, 2),
        "outlier_gift_excluded": outlier_gift_excluded,
        "rfm_score": rfm_score,
        "segment": segment,
    }


def build_ask_ladder(rfm: dict) -> list[float]:
    """A 3-rung ask ladder anchored on prior giving, shaped by segment.

    Ordering per the ask-strategy guidelines: typical → step-up → aspirational.
    Never leads with the aspirational figure alone.
    """
    segment = rfm["segment"]
    # Always the (outlier-robust) anchor — never the raw highest gift.
    base = rfm.get("anchor_gift") or 25.0

    if segment == SEGMENT_PROSPECT:
        base = 25.0
        rungs = [base, base * 2, base * 4]
    elif segment == SEGMENT_LAPSED:
        rungs = [base, base * 1.25, base * 1.75]
    elif segment == SEGMENT_LOYAL:
        rungs = [base * 1.25, base * 2, base * 3]
    else:  # SEGMENT_ACTIVE and SEGMENT_MAJOR share the standard step-up shape
        rungs = [base, base * 1.5, base * 2.5]

    return [_round_to(r) for r in rungs]


# Which rung of the ask ladder each segment is asked at. The ladder runs typical ->
# step-up -> aspirational and is never led with the aspirational figure: donors who
# have drifted away or have no history are asked gently at the typical rung; everyone
# else is invited to step up.
_RUNG_BY_SEGMENT = {
    SEGMENT_PROSPECT: 0,
    SEGMENT_LAPSED: 0,
    SEGMENT_ACTIVE: 1,
    SEGMENT_LOYAL: 1,
    SEGMENT_MAJOR: 1,
}

# Confidence is the strength of the giving evidence behind the ask, not a model's
# self-assessment: the more gifts there are to anchor on, the surer the figure.
_CONF_BY_FREQUENCY = {0: 0.50, 1: 0.65, 2: 0.80, 3: 0.80}
_CONF_FREQUENT = 0.90
_CONF_OUTLIER_CAP = 0.65  # the donor's true capacity is genuinely uncertain
_CONF_LAPSED_CAP = 0.75


def choose_ask(rfm: dict) -> dict:
    """The recommendation as a policy over the ladder: pick the rung, state why.

    This was an LLM call that chose a rung and justified it from retrieved guidelines.
    The choice follows a fixed segment -> rung rule, and a measurement of the model
    doing it showed what it added besides cost: it dropped `recency_days` on 15 of 15
    runs and flipped the outlier flag on 3 of 15 (both then patched by a guard). The
    judgment the model contributed is in the letter and the compliance review, where
    it belongs; the ask is money, so it is code."""
    ladder = rfm["ask_ladder"]
    segment = rfm["segment"]
    index = min(_RUNG_BY_SEGMENT.get(segment, 1), len(ladder) - 1)
    ask = ladder[index]

    frequency = rfm["frequency"]
    confidence = _CONF_FREQUENT if frequency >= 4 else _CONF_BY_FREQUENCY.get(frequency, _CONF_FREQUENT)
    rationale = [
        f"Segment '{segment}' (RFM score {rfm['rfm_score']}); the ladder is anchored on "
        f"${rfm['anchor_gift']:.0f} across {frequency} gift(s).",
        f"Policy: {segment} donors are asked at the {'typical' if index == 0 else 'step-up'} rung "
        f"of the ladder {ladder}.",
    ]
    if rfm.get("outlier_gift_excluded"):
        confidence = min(confidence, _CONF_OUTLIER_CAP)
        rationale.append(
            "An anomalous top gift was excluded from the anchor, so the donor's true capacity "
            "is uncertain and confidence is capped."
        )
    if segment == SEGMENT_LAPSED:
        confidence = min(confidence, _CONF_LAPSED_CAP)
        rationale.append("The donor has not given recently; the ask is gentle and confidence is capped.")
    if frequency < 2:
        rationale.append("Thin giving history: the figure rests on a single gift or none.")
    return {"recommended_ask": ask, "confidence": round(confidence, 3), "rationale": rationale}
