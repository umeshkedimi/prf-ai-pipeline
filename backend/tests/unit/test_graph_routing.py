"""Pure unit tests for the graph's routing functions — each is a plain
function of state, so these run with no DB/LLM/MCP involved. Focused on
route_after_human_review's compliance-stage branch, added in Phase 6 now
that there's something to continue into after a registration override."""

from langgraph.graph import END

from app.graph.builder import route_after_human_review


def test_compliance_stage_continues_to_content_review_when_registered():
    state = {"compliance_disclosures": {"registered_to_solicit": True}}
    assert route_after_human_review(state) == "review_letter_compliance"


def test_compliance_stage_ends_when_still_unregistered():
    state = {"compliance_disclosures": {"registered_to_solicit": False}}
    assert route_after_human_review(state) == END


def test_recommendation_stage_continues_to_personalization_for_positive_ask():
    state = {"recommendation_result": {"recommended_ask": 500.0}}
    assert route_after_human_review(state) == "personalize_letter"


def test_recommendation_stage_ends_for_zeroed_ask():
    state = {"recommendation_result": {"recommended_ask": 0.0}}
    assert route_after_human_review(state) == END


def test_address_stage_continues_when_deliverable():
    state = {"address_result": {"deliverable": True}}
    assert route_after_human_review(state) == "compute_rfm"


def test_address_stage_ends_when_not_deliverable():
    state = {"address_result": {"deliverable": False}}
    assert route_after_human_review(state) == END


# --- compliance revise loop ---------------------------------------------------

from app.agents.campaign_personalization.agent import build_revision_feedback  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.evals.suites.trajectory import collapse_revisions  # noqa: E402
from app.graph.builder import route_after_compliance  # noqa: E402


def test_approved_letter_goes_straight_to_pdf():
    assert route_after_compliance({"compliance_result": {"approved": True}}) == "generate_pdf"


def test_disapproved_letter_is_revised():
    state = {"compliance_result": {"approved": False}}
    assert route_after_compliance(state) == "revise_letter"


def test_revisions_are_capped_then_fall_through_to_pdf():
    cap = get_settings().max_letter_revisions
    state = {"compliance_result": {"approved": False}, "letter_revisions": cap}
    assert route_after_compliance(state) == "generate_pdf"
    assert route_after_compliance({**state, "letter_revisions": cap - 1}) == "revise_letter"


def test_revision_feedback_names_the_flagged_issues():
    text = build_revision_feedback(
        {"body": "Your gift guarantees a cure."},
        {"flagged_issues": ["implies outcome guarantee"]},
    )
    assert "implies outcome guarantee" in text and "guarantees a cure" in text


def test_revision_feedback_falls_back_to_reasoning():
    text = build_revision_feedback({}, {"flagged_issues": [], "reasoning": ["too pushy"]})
    assert "too pushy" in text


def test_collapse_revisions_removes_rewrite_cycles_only():
    steps = ["personalize_letter", "review_letter_compliance", "revise_letter",
             "review_letter_compliance", "revise_letter", "review_letter_compliance",
             "generate_pdf"]
    assert collapse_revisions(steps) == [
        "personalize_letter", "review_letter_compliance", "generate_pdf"
    ]
    assert collapse_revisions(["a", "review_letter_compliance"]) == ["a", "review_letter_compliance"]
