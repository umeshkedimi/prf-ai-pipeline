"""Tests for the deterministic tone lookup — a pure function, no LLM."""

from app.agents.campaign_personalization.rules import (
    TONE_ACTIVE,
    TONE_LAPSED,
    TONE_LOYAL,
    TONE_MAJOR,
    TONE_PROSPECT,
    tone_for_segment,
)
from app.agents.donation_recommendation.rfm import (
    SEGMENT_ACTIVE,
    SEGMENT_LAPSED,
    SEGMENT_LOYAL,
    SEGMENT_MAJOR,
    SEGMENT_PROSPECT,
)


def test_tone_for_each_known_segment():
    assert tone_for_segment(SEGMENT_PROSPECT) == TONE_PROSPECT
    assert tone_for_segment(SEGMENT_LAPSED) == TONE_LAPSED
    assert tone_for_segment(SEGMENT_ACTIVE) == TONE_ACTIVE
    assert tone_for_segment(SEGMENT_LOYAL) == TONE_LOYAL
    assert tone_for_segment(SEGMENT_MAJOR) == TONE_MAJOR


def test_unknown_segment_falls_back_to_active_tone():
    assert tone_for_segment("not_a_real_segment") == TONE_ACTIVE
