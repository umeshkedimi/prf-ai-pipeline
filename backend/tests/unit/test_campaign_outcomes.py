from app.campaigns.outcomes import (
    campaign_donor_status,
    cluster_signature,
    group_failures,
    outcome_reason,
    postal_shape,
)


def test_postal_shape_fingerprints_malformed_codes():
    assert postal_shape("98101") == "99999"
    assert postal_shape("9810") == "9999"  # leading zero lost by a spreadsheet
    assert postal_shape("K1A 0B1") == "A9A 9A9"
    assert postal_shape(None) == "missing"
    assert postal_shape("  ") == "missing"


def test_reason_for_a_paused_run_names_the_trigger():
    r = outcome_reason("awaiting_review", None, {"reason": "address_confidence_below_threshold"}, None)
    assert r == "paused:address_confidence_below_threshold"


def test_reason_precedence_ineligible_beats_everything():
    result = {"donor_verification": {"eligible": False}, "compliance": {"registered_to_solicit": False}}
    assert outcome_reason("completed", result, None, None) == "ineligible"


def test_reason_unregistered_state_and_held_letter():
    assert (
        outcome_reason("completed", {"compliance": {"registered_to_solicit": False}}, None, None)
        == "unregistered_state"
    )
    held = {"pdf_generation": {"held": True}}
    assert outcome_reason("needs_review", held, None, None) == "letter_held:compliance_disapproved"


def test_reason_ok_low_confidence_and_failed():
    assert outcome_reason("completed", {}, None, None) == "ok"
    assert outcome_reason("needs_review", {}, None, None) == "low_confidence"
    assert outcome_reason("failed", None, None, "JSONDecodeError: boom\ntrace") == "failed:JSONDecodeError: boom"


def test_campaign_donor_status_mapping():
    assert campaign_donor_status("ok") == "ready"
    assert campaign_donor_status("pending") == "queued"
    assert campaign_donor_status("running") == "running"
    assert campaign_donor_status("unregistered_state") == "blocked"
    assert campaign_donor_status("paused:recommendation_requires_approval") == "held"


def test_signature_only_for_reasons_with_a_data_root_cause():
    assert cluster_signature("unregistered_state", "fl", None) == "state=FL"
    assert cluster_signature("address_undeliverable", "WA", "9810") == "postal_shape=9999"
    assert cluster_signature("low_confidence", "WA", "98101") is None


def test_group_failures_finds_the_shared_cause_and_skips_ok():
    rows = [
        {"external_id": f"d-{i}", "reason": "address_undeliverable", "state": "WA", "postal_code": "9810"}
        for i in range(3)
    ] + [
        {"external_id": "d-9", "reason": "address_undeliverable", "state": "WA", "postal_code": "98101"},
        {"external_id": "d-10", "reason": "ok", "state": "WA", "postal_code": "98101"},
        {"external_id": "d-11", "reason": "unregistered_state", "state": "FL", "postal_code": "33101"},
    ]
    clusters = group_failures(rows)
    assert clusters[0] == {
        "reason": "address_undeliverable",
        "signature": "postal_shape=9999",
        "count": 3,
        "sample_external_ids": ["d-0", "d-1", "d-2"],
    }
    assert {c["reason"] for c in clusters} == {"address_undeliverable", "unregistered_state"}
    assert sum(c["count"] for c in clusters) == 5  # the ok row is excluded


def test_in_flight_runs_are_not_failure_clusters():
    rows = [{"external_id": "a", "reason": "pending", "state": None, "postal_code": None},
            {"external_id": "b", "reason": "running", "state": None, "postal_code": None}]
    assert group_failures(rows) == []
