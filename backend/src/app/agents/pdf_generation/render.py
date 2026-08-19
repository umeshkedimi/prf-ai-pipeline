"""Deterministic PDF layout for the print-ready letter — letterhead, dated
recipient block, salutation, drafted copy, a highlighted ask callout, a
signature block, a P.S. line, required disclosures, and a donation-tracking
QR code plus a Code128 mail-piece barcode. Pure rendering: the content itself
(letter, disclosures, ask amount) is assembled here, never generated — the
determinism boundary that already applies to every other agent's non-judgment
work applies here to the whole phase, since there's no LLM call in PDF
generation at all. The org identity below (name aside — "Prairie Rescue Fund"
is used throughout the project — address, phone, signer) is invented, synthetic
letterhead detail, the same fictional-but-consistent convention as the rest of
the seed data.

Letters in this domain are a single-page appeal — no pagination handling.
Wrapping is proportional-width-aware (via pdfmetrics.stringWidth), not a fixed
character count, since the body fonts below are not monospace."""

import hashlib
from datetime import date
from pathlib import Path

from reportlab.graphics import renderPDF
from reportlab.graphics.barcode.code128 import Code128
from reportlab.graphics.barcode.qr import QrCodeWidget
from reportlab.graphics.shapes import Drawing
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.units import inch
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

# backend/src/app/agents/pdf_generation/render.py -> parents[4] is backend/,
# matching core/config.py's repo-root resolution one level further up.
LETTER_STORAGE_DIR = Path(__file__).resolve().parents[4] / "storage" / "letters"
DONATION_TRACKING_BASE_URL = "https://give.prairierescuefund.org/r"

ORG_NAME = "Prairie Rescue Fund"
ORG_TAGLINE = "Animal Rescue & Rehabilitation"
ORG_ADDRESS_LINE = "118 Meadowlark Lane, Lincoln, NE 68508"
ORG_PHONE = "(402) 555-0134"
ORG_WEBSITE = "prairierescuefund.org"
SIGNER_NAME = "Renee Castellano"
SIGNER_TITLE = "Executive Director, Prairie Rescue Fund"

_ACCENT = HexColor("#2E5339")  # deep forest green — the one accent color used throughout
_ACCENT_TINT = HexColor("#EAF1EC")
_GRAY = HexColor("#5A5A5A")
_RULE_GRAY = HexColor("#B8B8B8")

_MARGIN = 0.75 * inch
_PAGE_WIDTH, _PAGE_HEIGHT = LETTER
_CONTENT_WIDTH = _PAGE_WIDTH - 2 * _MARGIN


def build_reference(workflow_run_id: str) -> str:
    """Short, deterministic mail-piece reference derived from the workflow
    run id — stable across re-renders of the same run, distinct across runs.
    Doubles as the print vendor's client reference (see agent.py)."""
    digest = hashlib.sha256(workflow_run_id.encode()).hexdigest()[:8].upper()
    return f"PRF-{digest}"


def _wrap(text: str, font_name: str, font_size: float, max_width: float) -> list[str]:
    """Greedy word-wrap by actual glyph width, not character count — these
    fonts are proportional, so a fixed-character wrap either overflows the
    margin or leaves the line short depending on which letters happen to
    land in it."""
    words = text.split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if stringWidth(candidate, font_name, font_size) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _draw_wrapped(
    c: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    *,
    font_name: str,
    font_size: float,
    leading: float,
    max_width: float,
    color=None,
) -> float:
    """Draws left-aligned wrapped text starting at y (top of first line) and
    returns the y position just below the last line drawn."""
    c.setFont(font_name, font_size)
    c.setFillColor(color or HexColor("#000000"))
    for line in _wrap(text, font_name, font_size, max_width):
        c.drawString(x, y, line)
        y -= leading
    return y


def _draw_qr_code(c: canvas.Canvas, data: str, x: float, y: float, size: float) -> None:
    widget = QrCodeWidget(data)
    x0, y0, x1, y1 = widget.getBounds()
    width, height = x1 - x0, y1 - y0
    drawing = Drawing(size, size, transform=[size / width, 0, 0, size / height, 0, 0])
    drawing.add(widget)
    renderPDF.draw(drawing, c, x, y)


def _draw_letterhead(c: canvas.Canvas, y: float) -> float:
    c.setFillColor(_ACCENT)
    c.setFont("Helvetica-Bold", 19)
    c.drawString(_MARGIN, y, ORG_NAME)
    y -= 15

    c.setFillColor(_GRAY)
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(_MARGIN, y, ORG_TAGLINE)
    y -= 12

    c.setFont("Helvetica", 8)
    c.drawString(_MARGIN, y, f"{ORG_WEBSITE}  |  {ORG_PHONE}  |  {ORG_ADDRESS_LINE}")
    y -= 10

    c.setStrokeColor(_ACCENT)
    c.setLineWidth(1.3)
    c.line(_MARGIN, y, _PAGE_WIDTH - _MARGIN, y)
    return y - 18


def _draw_ask_box(c: canvas.Canvas, y: float, *, amount: float, impact_reference: str) -> float:
    """A highlighted pull-quote box naming the ask — impact_reference is
    rendered as a standalone caption rather than spliced into a sentence,
    since PersonalizationResult doesn't guarantee it's a grammatical clause
    (eval/test fixtures show both full sentences and bare noun phrases)."""
    pad = 8
    label_h, amount_h, gap = 10, 20, 4
    caption_lines = _wrap(impact_reference, "Times-Italic", 9.5, _CONTENT_WIDTH - 2 * pad) if impact_reference else []
    box_h = pad * 2 + label_h + amount_h + gap + len(caption_lines) * 12
    top = y

    c.setFillColor(_ACCENT_TINT)
    c.rect(_MARGIN, top - box_h, _CONTENT_WIDTH, box_h, stroke=0, fill=1)
    c.setFillColor(_ACCENT)
    c.rect(_MARGIN, top - box_h, 3, box_h, stroke=0, fill=1)

    text_x = _MARGIN + pad + 3
    ty = top - pad - label_h
    c.setFillColor(_GRAY)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(text_x, ty, "YOUR GIFT TODAY")
    ty -= amount_h
    c.setFillColor(_ACCENT)
    c.setFont("Helvetica-Bold", 17)
    c.drawString(text_x, ty, f"${amount:,.0f}")
    ty -= gap
    for line in caption_lines:
        ty -= 12
        c.setFillColor(HexColor("#333333"))
        c.setFont("Times-Italic", 9.5)
        c.drawString(text_x, ty, line)

    return top - box_h - 14


def render_letter_pdf(
    *,
    workflow_run_id: str,
    reference: str,
    mailing_address: str,
    letter: dict,
    disclosures: list[str],
    recommended_ask: float | None = None,
) -> str:
    LETTER_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    pdf_path = LETTER_STORAGE_DIR / f"{workflow_run_id}.pdf"

    c = canvas.Canvas(str(pdf_path), pagesize=LETTER)
    y = _PAGE_HEIGHT - _MARGIN

    y = _draw_letterhead(c, y)

    c.setFillColor(HexColor("#000000"))
    c.setFont("Times-Roman", 9.5)
    c.drawString(_MARGIN, y, f"{date.today():%B} {date.today().day}, {date.today():%Y}")
    y -= 20

    c.setFont("Helvetica", 10)
    for line in mailing_address.split("\n"):
        c.drawString(_MARGIN, y, line)
        y -= 12.5
    y -= 16

    c.setFont("Times-Roman", 12)
    c.drawString(_MARGIN, y, letter.get("salutation", ""))
    y -= 20

    for paragraph in (letter.get("opening_line", ""), letter.get("body", "")):
        if not paragraph:
            continue
        y = _draw_wrapped(
            c, paragraph, _MARGIN, y, font_name="Times-Roman", font_size=10.5, leading=14.5, max_width=_CONTENT_WIDTH
        )
        y -= 10

    if recommended_ask:
        y = _draw_ask_box(c, y, amount=recommended_ask, impact_reference=letter.get("impact_reference", ""))

    closing_line = letter.get("closing_line", "")
    if closing_line:
        y = _draw_wrapped(
            c,
            closing_line,
            _MARGIN,
            y,
            font_name="Times-Roman",
            font_size=10.5,
            leading=14.5,
            max_width=_CONTENT_WIDTH,
        )
        y -= 10

    c.setFillColor(HexColor("#000000"))
    c.setFont("Times-Roman", 11)
    c.drawString(_MARGIN, y, "With gratitude,")
    y -= 34
    c.setFont("Times-Italic", 14)
    c.drawString(_MARGIN, y, SIGNER_NAME)
    y -= 13
    c.setFillColor(_GRAY)
    c.setFont("Helvetica", 9)
    c.drawString(_MARGIN, y, SIGNER_TITLE)
    y -= 22

    if recommended_ask:
        ps_prefix = "P.S. "
        prefix_width = stringWidth(ps_prefix, "Times-Bold", 10)
        ps_text = (
            f"Every gift, at any level, helps an animal like the ones on the "
            f"other side of this letter — but ${recommended_ask:,.0f} today "
            f"makes an outsized difference before the month is out."
        )
        c.setFillColor(HexColor("#000000"))
        c.setFont("Times-Bold", 10)
        c.drawString(_MARGIN, y, ps_prefix)
        lines = _wrap(ps_text, "Times-Roman", 10, _CONTENT_WIDTH - prefix_width)
        c.setFont("Times-Roman", 10)
        c.drawString(_MARGIN + prefix_width, y, lines[0] if lines else "")
        y -= 13.5
        for line in lines[1:]:
            c.drawString(_MARGIN, y, line)
            y -= 13.5
        y -= 10

    c.setStrokeColor(_RULE_GRAY)
    c.setLineWidth(0.5)
    c.line(_MARGIN, y, _PAGE_WIDTH - _MARGIN, y)
    y -= 12

    for disclosure in disclosures:
        y = _draw_wrapped(
            c, disclosure, _MARGIN, y, font_name="Helvetica", font_size=7.5, leading=9.5, max_width=_CONTENT_WIDTH, color=_GRAY
        )
        y -= 6

    code_size = 0.62 * inch
    code_y = _MARGIN
    c.setFillColor(_GRAY)
    c.setFont("Helvetica", 6.5)
    c.drawString(_PAGE_WIDTH - _MARGIN - code_size, code_y + code_size + 3, "Scan to give online")
    _draw_qr_code(
        c,
        f"{DONATION_TRACKING_BASE_URL}/{reference}",
        _PAGE_WIDTH - _MARGIN - code_size,
        code_y,
        code_size,
    )
    c.drawString(_MARGIN, code_y + 0.3 * inch + 4, f"Mail piece ref: {reference}")
    Code128(reference, barHeight=0.3 * inch, barWidth=0.9).drawOn(c, _MARGIN, code_y)

    c.showPage()
    c.save()
    return str(pdf_path)
