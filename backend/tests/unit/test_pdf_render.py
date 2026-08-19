"""Covers the layout logic in agents/pdf_generation/render.py directly (not
mocked, unlike test_pdf_generation_agent.py's node-level tests) — the actual
word-wrap math and the letter-writing entrypoint, since those never had
coverage of their own before this file existed."""

from pathlib import Path

from pypdf import PdfReader
from reportlab.pdfbase.pdfmetrics import stringWidth

from app.agents.pdf_generation.render import _wrap, render_letter_pdf


def test_wrap_never_exceeds_the_requested_width():
    text = (
        "Your leadership-level support over the past three years has been the "
        "backbone of our winter shelter expansion and emergency intake program."
    )
    max_width = 300
    for line in _wrap(text, "Times-Roman", 10.5, max_width):
        assert stringWidth(line, "Times-Roman", 10.5) <= max_width


def test_wrap_reassembles_to_the_original_words():
    text = "A short sentence that still needs to wrap across two or three lines."
    lines = _wrap(text, "Helvetica", 10, 120)
    assert " ".join(lines).split() == text.split()


def test_wrap_handles_empty_text_without_crashing():
    assert _wrap("", "Helvetica", 10, 200) == [""]


def test_render_letter_pdf_writes_a_readable_single_page_pdf(tmp_path, monkeypatch):
    monkeypatch.setattr("app.agents.pdf_generation.render.LETTER_STORAGE_DIR", tmp_path)
    letter = {
        "salutation": "Dear Eleanor,",
        "opening_line": "Thank you for your gift.",
        "body": "Your support made a real difference for animals in our care.",
        "closing_line": "With thanks.",
        "impact_reference": "one month of care for a rescued animal",
    }
    path = render_letter_pdf(
        workflow_run_id="test-run",
        reference="PRF-TEST0001",
        mailing_address="123 Maple St\nSpringfield, IL 62704",
        letter=letter,
        disclosures=["No goods or services were provided."],
        recommended_ask=225.0,
    )
    reader = PdfReader(Path(path))
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    assert "Prairie Rescue Fund" in text
    assert "$225" in text


def test_render_letter_pdf_without_a_recommended_ask_does_not_crash(tmp_path, monkeypatch):
    """recommend_ask should always be present by the time generate_pdf runs
    (see agent.py), but the ask box is still optional defensively — this
    covers that the None branch doesn't raise."""
    monkeypatch.setattr("app.agents.pdf_generation.render.LETTER_STORAGE_DIR", tmp_path)
    path = render_letter_pdf(
        workflow_run_id="test-run-no-ask",
        reference="PRF-TEST0002",
        mailing_address="123 Maple St\nSpringfield, IL 62704",
        letter={"salutation": "Dear Eleanor,", "body": "Thank you."},
        disclosures=[],
        recommended_ask=None,
    )
    assert Path(path).exists()
