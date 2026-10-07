"""Pure functions that turn a workflow run's scattered outcome (status, stage,
nested result dicts) into one machine-readable reason, and group runs by shared
cause. No DB, no LLM: a model asked 'why did these fail?' would be inventing
patterns, so the clustering is done here and the model only decides what to do
about the result."""

from collections import defaultdict
from typing import Any

SAMPLE_LIMIT = 20

# Reasons whose root cause can sit in the address data, so the postal-code shape is
# worth grouping on (a malformed ZIP column shows up as one shape across many donors).
_ADDRESS_REASONS = {"address_undeliverable", "paused:address_confidence_below_threshold"}


def postal_shape(code: str | None) -> str:
    """'98101' -> '99999', 'K1A 0B1' -> 'A9A 9A9', '' / None -> 'missing'. Cheap,
    deterministic fingerprint for 'these ZIPs are all malformed the same way'."""
    code = (code or "").strip()
    if not code:
        return "missing"
    return "".join("9" if c.isdigit() else "A" if c.isalpha() else c for c in code)


def outcome_reason(
    status: str, result: dict | None, pending_review: dict | None, error: str | None
) -> str:
    """One stable string per cause. `ok` means nothing to explain."""
    result = result or {}
    if status == "failed":
        head = (error or "unknown").strip().splitlines()[0] if (error or "").strip() else "unknown"
        return f"failed:{head[:60]}"
    if status == "awaiting_review":
        return f"paused:{(pending_review or {}).get('reason', 'unknown')}"
    if status == "discarded":
        return "discarded"
    verification = result.get("donor_verification") or {}
    if verification.get("eligible") is False:
        return "ineligible"
    compliance = result.get("compliance") or {}
    if compliance.get("registered_to_solicit") is False:
        return "unregistered_state"
    address = result.get("address_intelligence") or {}
    if address.get("deliverable") is False:
        return "address_undeliverable"
    if (result.get("pdf_generation") or {}).get("held"):
        return "letter_held:compliance_disapproved"
    if status == "needs_review":
        return "low_confidence"
    if status == "completed":
        return "ok"
    return status  # pending / running: not an outcome yet


def campaign_donor_status(reason: str) -> str:
    """Map a run's reason to the campaign_donors.status it implies."""
    if reason == "ok":
        return "ready"
    if reason == "pending":
        return "queued"
    if reason == "running":
        return "running"
    if reason in {"ineligible", "unregistered_state", "discarded"}:
        return "blocked"
    return "held"


def cluster_signature(reason: str, state: str | None, postal_code: str | None) -> str | None:
    if reason == "unregistered_state":
        return f"state={(state or '?').upper()}"
    if reason in _ADDRESS_REASONS:
        return f"postal_shape={postal_shape(postal_code)}"
    return None


def group_failures(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """rows: {external_id, reason, state, postal_code}. Skips `ok`. Largest cluster first."""
    groups: dict[tuple[str, str | None], list[str]] = defaultdict(list)
    for row in rows:
        if row["reason"] == "ok":
            continue
        key = (row["reason"], cluster_signature(row["reason"], row.get("state"), row.get("postal_code")))
        groups[key].append(row["external_id"])
    clusters = [
        {
            "reason": reason,
            "signature": signature,
            "count": len(ids),
            "sample_external_ids": sorted(ids)[:SAMPLE_LIMIT],
        }
        for (reason, signature), ids in groups.items()
    ]
    return sorted(clusters, key=lambda c: (-c["count"], c["reason"], c["signature"] or ""))
