"""Deterministic RFM scoring and ask-ladder construction.

Pure functions — no DB, no LLM, no I/O — so the money math is reproducible and
unit-testable in isolation. The LLM downstream only *chooses* from the ladder
these functions produce and explains why; it never computes dollar amounts.
"""

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


# Fields this module computes and therefore owns. The prompt asks the model to
# copy them through unchanged, but asking is not enforcing.
DETERMINISTIC_FIELDS = (
    "segment",
    "rfm_score",
    "recency_days",
    "frequency",
    "monetary_total",
    "anchor_gift",
    "outlier_gift_excluded",
    "ask_ladder",
)


def enforce_deterministic_fields(rfm: dict, recommendation: dict) -> tuple[dict, list[str]]:
    """Restore the computed fields and snap the ask back onto the ladder.

    The determinism boundary was previously enforced only by instruction: the
    schema's `recommended_ask` field carried a *description* saying it must be a
    ladder value, which Pydantic does not check, and nothing downstream verified
    it. The eval suite appeared to measure compliance and reported a clean
    1.000 — but it checked five of the eight fields below, and widening it to
    all eight dropped `fields_unchanged` to 0.000 on every case, every run: the
    model had been dropping `recency_days` the whole time, and flipping
    d-0006's `outlier_gift_excluded` in a fifth of runs. So the measurement was
    not merely insufficient as a guarantee, it was incomplete as a measurement.
    The major-gift human-review gate routes on `recommended_ask`, so without
    this an off-ladder value would let a model-produced float decide whether a
    human sees the letter at all.

    Rather than fail the run, deviations are corrected and reported: the ladder
    is the source of truth, so the nearest rung is always a defensible answer,
    and the deviation itself is signal worth keeping in the audit trail rather
    than an error worth discarding a whole pipeline run over.
    """
    corrected = dict(recommendation)
    deviations: list[str] = []

    for field in DETERMINISTIC_FIELDS:
        if field not in rfm:
            continue
        authoritative = rfm[field]
        if corrected.get(field) != authoritative:
            deviations.append(
                f"{field}: model returned {corrected.get(field)!r}, restored {authoritative!r}"
            )
            corrected[field] = authoritative

    ladder = rfm.get("ask_ladder") or []
    ask = corrected.get("recommended_ask")
    # An empty ladder can't happen via build_ask_ladder (it always returns three
    # rungs), but snapping against nothing would raise rather than degrade.
    if ladder and ask not in ladder:
        nearest = min(ladder, key=lambda rung: abs(rung - (ask or 0.0)))
        deviations.append(
            f"recommended_ask: model returned {ask!r}, snapped to nearest rung {nearest!r}"
        )
        corrected["recommended_ask"] = nearest

    return corrected, deviations
