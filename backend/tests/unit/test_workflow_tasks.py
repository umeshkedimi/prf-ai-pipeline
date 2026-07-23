"""Pure unit tests for _derive_terminal_status — no DB/LLM/MCP involved.
Covers the Phase 7 fix: a disapproved compliance review must route to
needs_review even though generate_pdf ran anyway (advisory, not blocking)."""

from app.core.config import get_settings
from app.workers.tasks import _derive_terminal_status

settings = get_settings()


def test_pdf_stage_completes_when_compliance_approved():
    result = {
        "compliance_result": {"approved": True, "confidence": 0.9},
        "pdf_result": {"reference": "PRF-00000000"},
    }
    status, confidence, current_agent = _derive_terminal_status(result, settings)
    assert status == "completed"
    assert confidence is None
    assert current_agent == "pdf_generation"


def test_pdf_stage_needs_review_when_compliance_disapproved():
    # confidence is deliberately high, well above confidence_threshold_compliance,
    # to isolate that approved=False alone drives needs_review, not confidence.
    result = {
        "compliance_result": {"approved": False, "confidence": 0.95},
        "pdf_result": {"reference": "PRF-00000000"},
    }
    status, confidence, current_agent = _derive_terminal_status(result, settings)
    assert status == "needs_review"
    assert confidence == 0.95
    assert current_agent == "pdf_generation"


def test_pdf_stage_completes_when_compliance_never_ran_content_review():
    # comp_disclosures-only path (unregistered-to-solicit override) never
    # produces a compliance_result, so there's nothing to disapprove.
    result = {"pdf_result": {"reference": "PRF-00000000"}}
    status, confidence, current_agent = _derive_terminal_status(result, settings)
    assert status == "completed"
    assert confidence is None


def test_compliance_stage_needs_review_on_low_confidence_alone():
    result = {"compliance_result": {"approved": True, "confidence": 0.1}}
    status, confidence, current_agent = _derive_terminal_status(result, settings)
    assert status == "needs_review"
    assert current_agent == "compliance"
