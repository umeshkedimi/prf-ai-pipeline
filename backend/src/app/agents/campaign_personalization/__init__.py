"""Campaign Personalization Agent (Phase 4): deterministic tone selection from
the donor's RFM segment, then an LLM that drafts the letter within that tone,
grounded in RAG-retrieved campaign knowledge. The tone is copied through
unchanged rather than asked for — a judgment the segment already decided."""
