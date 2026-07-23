"""Deterministic PDF layout for the print-ready letter — salutation, drafted
copy, required disclosures, a donation-tracking QR code, and a Code128
mail-piece barcode. Pure rendering: the content itself (letter, disclosures)
is assembled here, never generated — the determinism boundary that already
applies to every other agent's non-judgment work applies here to the whole
phase, since there's no LLM call in PDF generation at all.

Letters in this domain are a single-page appeal — no pagination handling."""

import hashlib
import textwrap
from pathlib import Path

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.code128 import Code128
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

# backend/src/app/agents/pdf_generation/render.py -> parents[4] is backend/,
# matching core/config.py's repo-root resolution one level further up.
LETTER_STORAGE_DIR = Path(__file__).resolve().parents[4] / "storage" / "letters"
DONATION_TRACKING_BASE_URL = "https://give.prairierescuefund.org/r"

_MARGIN = 0.75 * inch
_BODY_WRAP_WIDTH = 90
_DISCLOSURE_WRAP_WIDTH = 110


def build_reference(workflow_run_id: str) -> str:
    """Short, deterministic mail-piece reference derived from the workflow
    run id — stable across re-renders of the same run, distinct across runs.
    Doubles as the print vendor's client reference (see agent.py)."""
    digest = hashlib.sha256(workflow_run_id.encode()).hexdigest()[:8].upper()
    return f"PRF-{digest}"


def _draw_qr_code(c: canvas.Canvas, data: str, x: float, y: float, size: float) -> None:
    widget = QrCodeWidget(data)
    x0, y0, x1, y1 = widget.getBounds()
    width, height = x1 - x0, y1 - y0
    drawing = Drawing(size, size, transform=[size / width, 0, 0, size / height, 0, 0])
    drawing.add(widget)
    renderPDF.draw(drawing, c, x, y)


def render_letter_pdf(
    *,
    workflow_run_id: str,
    reference: str,
    mailing_address: str,
    letter: dict,
    disclosures: list[str],
) -> str:
    LETTER_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = LETTER_STORAGE_DIR / f"{workflow_run_id}.pdf"

    c = canvas.Canvas(str(pdf_path), pagesize=LETTER)
    width, height = LETTER
    y = height - _MARGIN

    c.setFont("Helvetica", 10)
    for line in mailing_address.split("\n"):
        c.drawString(_MARGIN, y, line)
        y -= 0.16 * inch
    y -= 0.35 * inch

    c.setFont("Helvetica", 11)
    c.drawString(_MARGIN, y, letter.get("salutation", ""))
    y -= 0.3 * inch

    text = c.beginText(_MARGIN, y)
    text.setFont("Helvetica", 10)
    text.setLeading(14)
    paragraphs = [letter.get("opening_line", ""), letter.get("body", ""), letter.get("closing_line", "")]
    for i, paragraph in enumerate(paragraphs):
        for wrapped in textwrap.wrap(paragraph, _BODY_WRAP_WIDTH) or [""]:
            text.textLine(wrapped)
        if i < len(paragraphs) - 1:
            text.textLine("")
    c.drawText(text)
    y = text.getY() - 0.35 * inch

    c.setFont("Helvetica", 7)
    for disclosure in disclosures:
        for wrapped in textwrap.wrap(disclosure, _DISCLOSURE_WRAP_WIDTH):
            c.drawString(_MARGIN, y, wrapped)
            y -= 0.13 * inch
        y -= 0.05 * inch

    _draw_qr_code(
        c,
        f"{DONATION_TRACKING_BASE_URL}/{reference}",
        width - _MARGIN - 0.9 * inch,
        _MARGIN,
        0.9 * inch,
    )
    Code128(reference, barHeight=0.3 * inch, barWidth=0.9).drawOn(c, _MARGIN, _MARGIN)

    c.showPage()
    c.save()
    return str(pdf_path)
