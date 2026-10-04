"""Pure tests for the held-letter release pieces: the request schema and the
released pdf_result builder."""

import pytest
from pydantic import ValidationError

from app.agents.pdf_generation.agent import build_released_pdf_result
from app.schemas.workflow import HeldLetterDecision

_HELD = {
    "reference": "PRF-1",
    "page_count": 1,
    "held": True,
    "hold_reason": ["implies a guaranteed outcome"],
    "vendor_order_id": None,
    "tracking_number": None,
}
_ORDER = {"vendor_order_id": "PV-1", "tracking_number": "94000", "postage_class": "first_class"}


def test_release_requires_a_real_note():
    with pytest.raises(ValidationError):
        HeldLetterDecision(action="release", notes="")
    with pytest.raises(ValidationError):
        HeldLetterDecision(action="release", notes="ok")
    assert HeldLetterDecision(action="discard", notes="wording is unsalvageable").action == "discard"


def test_reviewer_cannot_be_supplied_in_the_body():
    # Extra fields are ignored by pydantic's default, so a client-sent
    # "reviewer" never reaches the decision; the endpoint sets it from the session.
    decision = HeldLetterDecision.model_validate(
        {"action": "release", "notes": "reviewed manually", "reviewer": "SPOOFED"}
    )
    assert "reviewer" not in decision.model_dump()


def test_released_result_fills_the_order_and_records_who_and_why():
    released = build_released_pdf_result(_HELD, _ORDER, "rev@prf.local", "wording is fine", "2026-10-03T00:00:00Z")
    assert released["held"] is False
    assert released["vendor_order_id"] == "PV-1"
    assert released["released_by"] == "rev@prf.local"
    assert released["release_notes"] == "wording is fine"
    # The record still shows what Compliance objected to.
    assert released["hold_reason"] == ["implies a guaranteed outcome"]
    # Input is not mutated.
    assert _HELD["held"] is True and _HELD["vendor_order_id"] is None


# --- claim staleness ---------------------------------------------------------

from datetime import UTC, datetime, timedelta  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.workers.release_claims import build_claim, is_stale  # noqa: E402


def _claim_age(seconds: int) -> dict:
    return {"claimed_at": (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()}


def test_a_claim_is_stale_only_after_the_ttl():
    ttl = get_settings().release_claim_ttl_seconds
    assert not is_stale(_claim_age(ttl - 30))
    assert is_stale(_claim_age(ttl + 30))


def test_no_claim_is_never_stale():
    assert not is_stale(None) and not is_stale({})


def test_build_claim_records_who_when_and_why():
    claim = build_claim({"reviewer": "r@prf.local", "notes": "fine"})
    assert claim["reviewer"] == "r@prf.local" and claim["notes"] == "fine"
    assert datetime.fromisoformat(claim["claimed_at"]).tzinfo is not None
