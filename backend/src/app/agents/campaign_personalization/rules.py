"""Deterministic tone selection — a business rule, not a judgment call, so it
lives in plain Python and the LLM only drafts within the tone it's given."""

from app.agents.donation_recommendation.rfm import (
    SEGMENT_ACTIVE,
    SEGMENT_LAPSED,
    SEGMENT_LOYAL,
    SEGMENT_MAJOR,
    SEGMENT_PROSPECT,
)

TONE_PROSPECT = "warm and inviting, first-time, no pressure"
TONE_LAPSED = "gentle and reconnecting, no guilt"
TONE_ACTIVE = "appreciative, straightforward step-up"
TONE_LOYAL = "warm, relationship-deepening, invites a step up"
TONE_MAJOR = "personal, relationship-based, high-touch"

_TONE_BY_SEGMENT = {
    SEGMENT_PROSPECT: TONE_PROSPECT,
    SEGMENT_LAPSED: TONE_LAPSED,
    SEGMENT_ACTIVE: TONE_ACTIVE,
    SEGMENT_LOYAL: TONE_LOYAL,
    SEGMENT_MAJOR: TONE_MAJOR,
}


def tone_for_segment(segment: str) -> str:
    """Per knowledge/ask_strategy_guidelines.md and donor_stewardship.md:
    lapsed donors get a gentle reconnecting tone, loyal donors an invitation to
    step up, major donors a personal relationship-based posture. Falls back to
    the active-donor tone for an unrecognized segment rather than raising —
    the letter still needs to draft with *some* tone."""
    return _TONE_BY_SEGMENT.get(segment, TONE_ACTIVE)
