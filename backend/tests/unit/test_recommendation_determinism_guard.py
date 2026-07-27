"""The determinism boundary, enforced rather than instructed.

`RecommendationResult.recommended_ask` carried only a Field *description*
saying it must be a ladder value -- which Pydantic does not check -- and
nothing downstream verified it. The eval suite measured compliance but
measurement is not a guarantee, and `route_after_recommendation` routes the
blocking major-gift pause on this number. These tests pin the enforcement.
"""

from app.agents.donation_recommendation.rfm import (
    build_ask_ladder,
    enforce_deterministic_fields,
)

RFM = {
    "segment": "active",
    "rfm_score": 7.5,
    "recency_days": 90,
    "frequency": 3,
    "monetary_total": 450.0,
    "anchor_gift": 150.0,
    "outlier_gift_excluded": False,
    "ask_ladder": [150.0, 225.0, 375.0],
}


def _model_output(**overrides) -> dict:
    """A well-behaved model response, before any tampering."""
    return {
        **RFM,
        "recommended_ask": 225.0,
        "confidence": 0.8,
        "rationale": ["steady giving supports a modest step up"],
        "sources": ["Ask Strategy Guidelines"],
        **overrides,
    }


def test_compliant_output_passes_through_untouched():
    corrected, deviations = enforce_deterministic_fields(RFM, _model_output())
    assert deviations == []
    assert corrected == _model_output()


def test_off_ladder_ask_snaps_to_the_nearest_rung():
    corrected, deviations = enforce_deterministic_fields(
        RFM, _model_output(recommended_ask=240.0)
    )
    assert corrected["recommended_ask"] == 225.0
    assert any("recommended_ask" in d for d in deviations)


def test_a_fabricated_ask_cannot_cross_the_major_gift_gate():
    """The failure this guard exists for: an invented five-figure ask would
    otherwise route a blocking human-review pause off a model-produced float."""
    corrected, deviations = enforce_deterministic_fields(
        RFM, _model_output(recommended_ask=50_000.0)
    )
    assert corrected["recommended_ask"] == 375.0
    assert corrected["recommended_ask"] in RFM["ask_ladder"]
    assert deviations


def test_a_rewritten_ladder_is_restored_from_the_computation():
    corrected, deviations = enforce_deterministic_fields(
        RFM, _model_output(ask_ladder=[1000.0, 2000.0, 3000.0], recommended_ask=2000.0)
    )
    assert corrected["ask_ladder"] == RFM["ask_ladder"]
    # The ask is snapped against the restored ladder, not the invented one.
    assert corrected["recommended_ask"] in RFM["ask_ladder"]
    assert len(deviations) == 2


def test_outlier_exclusion_flag_cannot_be_flipped_by_the_model():
    """d-0006's protection: the flag records what the arithmetic did, so a model
    claiming otherwise must not be able to overwrite the record."""
    rfm = {**RFM, "outlier_gift_excluded": True}
    corrected, deviations = enforce_deterministic_fields(
        rfm, _model_output(outlier_gift_excluded=False)
    )
    assert corrected["outlier_gift_excluded"] is True
    assert any("outlier_gift_excluded" in d for d in deviations)


def test_judgment_fields_are_left_alone():
    """Enforcement covers computed values only -- the model's actual job
    (choosing, explaining, citing) must pass through untouched."""
    output = _model_output(confidence=0.42, rationale=["a"], sources=["b"])
    corrected, _ = enforce_deterministic_fields(RFM, output)
    assert corrected["confidence"] == 0.42
    assert corrected["rationale"] == ["a"]
    assert corrected["sources"] == ["b"]


def test_integer_ask_matching_a_float_rung_is_not_a_deviation():
    """225 == 225.0 in Python; flagging that would be noise in the audit trail."""
    _, deviations = enforce_deterministic_fields(RFM, _model_output(recommended_ask=225))
    assert deviations == []


def test_empty_ladder_degrades_instead_of_raising():
    rfm = {**RFM, "ask_ladder": []}
    corrected, _ = enforce_deterministic_fields(rfm, _model_output(recommended_ask=99.0))
    assert corrected["recommended_ask"] == 99.0


def test_guard_holds_against_a_real_built_ladder():
    """Guards against the ladder builder and the guard drifting apart."""
    rfm = {**RFM}
    rfm["ask_ladder"] = build_ask_ladder(rfm)
    corrected, deviations = enforce_deterministic_fields(
        rfm, _model_output(ask_ladder=rfm["ask_ladder"], recommended_ask=7.0)
    )
    assert corrected["recommended_ask"] in rfm["ask_ladder"]
    assert deviations
