"""Embeds the campaign-knowledge corpus (backend/knowledge/*.md) into the
pgvector-backed knowledge_chunks table.

Idempotent: each document is delete-and-reinserted by title, so re-running
after editing a doc simply refreshes it. Requires OPENAI_API_KEY (or whichever
EMBEDDING_PROVIDER is configured).

Usage: uv run python scripts/ingest_knowledge.py
"""

import asyncio
from pathlib import Path

from app.db.session import db_session
from app.rag.embeddings import get_embeddings
from app.rag.store import replace_document

KNOWLEDGE_DIR = Path(__file__).resolve().parents[1] / "knowledge"

# filename -> (human-readable doc title, doc_type). doc_type drives the
# retriever's optional filter: impact | success_story | guideline.
DOCS: dict[str, tuple[str, str]] = {
    "impact_stats_2025.md": ("2025 Impact Report — Key Statistics", "impact"),
    "program_outcomes.md": ("Program Outcomes and Effectiveness", "impact"),
    "success_stories.md": ("Donor-Funded Success Stories", "success_story"),
    "ask_strategy_guidelines.md": ("Ask Strategy Guidelines", "guideline"),
    "donor_stewardship.md": ("Donor Stewardship Principles", "guideline"),
    "compliance_guidelines.md": ("Compliance Guidelines for Fundraising Appeals", "compliance"),
}


def chunk_markdown(text: str) -> list[str]:
    """Split on markdown '## ' headings so each chunk is one self-contained
    section (heading + its body) — small, topically coherent units that embed
    and retrieve cleanly. Content before the first '## ' (the H1 + intro) is
    kept as its own chunk."""
    chunks: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("## ") and current:
            chunk = "\n".join(current).strip()
            if chunk:
                chunks.append(chunk)
            current = [line]
        else:
            current.append(line)
    tail = "\n".join(current).strip()
    if tail:
        chunks.append(tail)
    return chunks


async def ingest() -> None:
    embeddings = get_embeddings()
    total = 0
    async with db_session() as session:
        for filename, (doc_title, doc_type) in DOCS.items():
            path = KNOWLEDGE_DIR / filename
            chunks = chunk_markdown(path.read_text(encoding="utf-8"))
            vectors = await embeddings.aembed_documents(chunks)
            n = await replace_document(session, doc_title, doc_type, chunks, vectors)
            total += n
            print(f"  {doc_title}: {n} chunks")
        await session.commit()
    print(f"Ingested {total} chunks from {len(DOCS)} documents.")


if __name__ == "__main__":
    asyncio.run(ingest())
