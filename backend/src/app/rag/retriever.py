from sqlalchemy import select

from app.db.models.knowledge_chunk import KnowledgeChunk
from app.db.session import db_session
from app.rag.embeddings import get_embeddings


async def retrieve(
    query: str,
    k: int = 4,
    doc_types: list[str] | None = None,
) -> list[dict]:
    """Semantic search over campaign knowledge: embed the query, return the k
    nearest chunks by cosine distance (the same metric the HNSW index is built
    for, via pgvector's <=> operator). Optionally filter by doc_type.

    Returns lightweight dicts (not ORM objects) so callers/agents can log and
    serialize them freely without a live session.
    """
    embeddings = get_embeddings()
    query_vector = await embeddings.aembed_query(query)

    distance = KnowledgeChunk.embedding.cosine_distance(query_vector)
    stmt = select(
        KnowledgeChunk.doc_title,
        KnowledgeChunk.doc_type,
        KnowledgeChunk.chunk_text,
        distance.label("distance"),
    )
    if doc_types:
        stmt = stmt.where(KnowledgeChunk.doc_type.in_(doc_types))
    stmt = stmt.order_by(distance).limit(k)

    async with db_session() as session:
        rows = (await session.execute(stmt)).all()

    return [
        {
            "doc_title": row.doc_title,
            "doc_type": row.doc_type,
            "chunk_text": row.chunk_text,
            "distance": float(row.distance),
        }
        for row in rows
    ]
