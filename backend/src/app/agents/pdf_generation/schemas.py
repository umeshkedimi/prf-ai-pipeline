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
    vendor_order_id: str
    tracking_number: str
    postage_class: str
    turnaround_days: int
    cost: float
