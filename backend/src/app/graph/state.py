from typing import Any, TypedDict


class PipelineState(TypedDict, total=False):
    """Shared state threaded through the full 7-agent graph."""

    # --- shared workflow context ---
    workflow_run_id: str
    donor_id: str
    campaign_id: str | None

    # --- 1. Donor Verification (Phase 1) ---
    donor_profile: dict[str, Any] | None
    donation_history: list[dict[str, Any]] | None
    duplicate_candidates: list[dict[str, Any]] | None
    verification_result: dict[str, Any] | None

    # --- 2. Address Intelligence (Phase 2) ---
    address_verification: dict[str, Any] | None  # raw verify_address MCP output
    address_result: dict[str, Any] | None  # final structured AddressResult

    # --- 3. Donation Recommendation (Phase 3) ---
    recommendation_result: dict[str, Any] | None

    # --- 4. Campaign Personalization (Phase 4) ---
    personalization_result: dict[str, Any] | None

    # --- 5. Compliance (Phase 5) ---
    compliance_disclosures: dict[str, Any] | None  # raw gather_disclosures MCP output
    compliance_result: dict[str, Any] | None  # final LetterComplianceAssessment + disclosures

    # --- 6. PDF Generation (Phase 6) ---
    pdf_result: dict[str, Any] | None

    # --- 7. Human Review (Phase 2+, interrupt-based) ---
    human_review_decision: dict[str, Any] | None
