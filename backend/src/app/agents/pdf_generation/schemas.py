from pydantic import BaseModel


class PdfGenerationResult(BaseModel):
    """Output of the deterministic PDF-assembly step: layout facts plus the
    print vendor's mocked order confirmation. No LLM runs in this phase —
    every judgment call the letter needed (copy, compliance risk) already
    happened upstream; what's left is mechanical assembly and a vendor order,
    the same reasoning that keeps gather_disclosures LLM-free."""

    reference: str
    pdf_path: str
    page_count: int
    qr_code_data: str
    required_disclosures: list[str]
    # Order confirmation fields are None when the letter was held: Compliance
    # disapproved it, so nothing was submitted to the print vendor.
    vendor_order_id: str | None = None
    tracking_number: str | None = None
    postage_class: str | None = None
    turnaround_days: int | None = None
    cost: float | None = None
    held: bool = False
    hold_reason: list[str] = []
    # Set only when a human releases (or discards) a held letter — see
    # POST /workflow/{id}/release.
    released_by: str | None = None
    released_at: str | None = None
    release_notes: str | None = None
    discarded_by: str | None = None
