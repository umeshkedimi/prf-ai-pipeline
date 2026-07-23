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
