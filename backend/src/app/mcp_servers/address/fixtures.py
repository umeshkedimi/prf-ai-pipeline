from pydantic import BaseModel


class AddressVerification(BaseModel):
    valid: bool
    deliverable: bool
    standardized_address: str | None
    moved: bool
    vacant: bool
    po_box: bool


class ForwardingLookup(BaseModel):
    found: bool
    new_address: str | None
    confidence: float


def _normalize_key(address_line1: str, city: str, state: str, postal_code: str) -> str:
    return "|".join(part.strip().lower() for part in (address_line1, city, state, postal_code))


# Deterministic fixtures for the seed donors that need a specific, controllable
# scenario. Anything not listed here falls through to the heuristic default below
# — real address-verification vendor sandboxes work the same way (a handful of
# documented test addresses, benign defaults otherwise).
VERIFY_FIXTURES: dict[str, dict] = {
    _normalize_key("410 Willow St", "Denver", "CO", "80203"): {
        "valid": True,
        "deliverable": False,
        "standardized_address": "410 Willow St, Denver, CO 80203",
        "moved": True,
        "vacant": False,
        "po_box": False,
    },
    _normalize_key("999 Ghost Ave", "Detroit", "MI", "48201"): {
        "valid": False,
        "deliverable": False,
        "standardized_address": None,
        "moved": False,
        "vacant": True,
        "po_box": False,
    },
    _normalize_key("PO Box 9911", "Reno", "NV", "89501"): {
        "valid": True,
        "deliverable": True,
        "standardized_address": "PO Box 9911, Reno, NV 89501",
        "moved": False,
        "vacant": False,
        "po_box": True,
    },
}

FORWARDING_FIXTURES: dict[str, dict] = {
    _normalize_key("410 Willow St", "Denver", "CO", "80203"): {
        "found": True,
        "new_address": "1225 Pine St, Denver, CO 80218",
        "confidence": 0.6,
    },
    _normalize_key("999 Ghost Ave", "Detroit", "MI", "48201"): {
        "found": False,
        "new_address": None,
        "confidence": 0.0,
    },
}


def verify_address(address_line1: str, city: str, state: str, postal_code: str) -> dict:
    if not address_line1:
        return {
            "valid": False,
            "deliverable": False,
            "standardized_address": None,
            "moved": False,
            "vacant": False,
            "po_box": False,
        }

    key = _normalize_key(address_line1, city, state, postal_code)
    if key in VERIFY_FIXTURES:
        return VERIFY_FIXTURES[key]

    is_po_box = "po box" in address_line1.lower() or "p.o. box" in address_line1.lower()
    standardized = ", ".join(part for part in (address_line1, city, f"{state} {postal_code}".strip()) if part)
    return {
        "valid": True,
        "deliverable": True,
        "standardized_address": standardized,
        "moved": False,
        "vacant": False,
        "po_box": is_po_box,
    }


def lookup_new_address(address_line1: str, city: str, state: str, postal_code: str) -> dict:
    key = _normalize_key(address_line1 or "", city, state, postal_code)
    return FORWARDING_FIXTURES.get(key, {"found": False, "new_address": None, "confidence": 0.0})
