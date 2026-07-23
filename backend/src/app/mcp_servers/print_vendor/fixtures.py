"""Deterministic fixtures standing in for a real print/mail fulfillment vendor
(e.g. Lob, PostGrid). Order attributes are derived from the mail-piece
reference alone, never wall-clock time, so the same run always mocks the same
vendor response — required for eval reproducibility, same convention as the
address/compliance fixtures."""

import hashlib

FIRST_CLASS_MAX_PAGES = 2
_FIRST_CLASS_COST = 0.68
_STANDARD_COST = 0.51
_FIRST_CLASS_TURNAROUND_DAYS = 3
_STANDARD_TURNAROUND_DAYS = 7


def submit_print_order(reference: str, page_count: int) -> dict:
    order_id = f"PV-{hashlib.sha256(reference.encode()).hexdigest()[:10].upper()}"
    tracking_digits = str(int(hashlib.sha256(f"track:{reference}".encode()).hexdigest(), 16))
    tracking_number = f"94{tracking_digits[:18]}"

    if page_count <= FIRST_CLASS_MAX_PAGES:
        postage_class = "first_class"
        cost = _FIRST_CLASS_COST
        turnaround_days = _FIRST_CLASS_TURNAROUND_DAYS
    else:
        postage_class = "standard"
        cost = _STANDARD_COST
        turnaround_days = _STANDARD_TURNAROUND_DAYS

    return {
        "vendor_order_id": order_id,
        "tracking_number": tracking_number,
        "postage_class": postage_class,
        "turnaround_days": turnaround_days,
        "cost": cost,
    }
