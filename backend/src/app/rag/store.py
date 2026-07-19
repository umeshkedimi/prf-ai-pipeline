from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

# Re-export so callers treat app.rag as the single entry point for the RAG
# store; the ORM model itself lives in db/models so Alembic's metadata sees it.
from app.db.models.knowledge_chunk import KnowledgeChunk

__all__ = ["KnowledgeChunk", "replace_document"]


async def replace_document(
    session: AsyncSession,
    doc_title: str,
    doc_type: str,
    chunks: list[str],
    embeddings: list[list[float]],
) -> int:
    """Idempotently (re)ingest one document: delete any existing chunks for this
    doc_title, then insert the freshly embedded ones. Delete-and-reinsert keeps
    re-runs clean without needing a natural key per chunk. Caller commits."""
    if len(chunks) != len(embeddings):
        raise ValueError("chunks and embeddings must be the same length")

    await session.execute(delete(KnowledgeChunk).where(KnowledgeChunk.doc_title == doc_title))
    session.add_all(
        KnowledgeChunk(
            doc_title=doc_title,
            doc_type=doc_type,
            chunk_text=chunk,
            embedding=embedding,
        )
        for chunk, embedding in zip(chunks, embeddings, strict=True)
    )
    return len(chunks)
