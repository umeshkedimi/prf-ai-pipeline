import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, String, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import get_settings
from app.db.base import Base

# Embedding dimensionality is fixed at the table level (pgvector columns are
# typed by dimension). Read from settings so the model and the migration stay
# in lockstep with the configured embedding model.
_EMBEDDING_DIM = get_settings().embedding_dim


class KnowledgeChunk(Base):
    """One embedded chunk of *campaign knowledge* — impact stats, success
    stories, ask-strategy guidelines. Deliberately never stores donor PII;
    the data boundary is that structured donor data lives in the relational
    tables and only unstructured, org-wide campaign knowledge is embedded."""

    __tablename__ = "knowledge_chunks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    doc_title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    doc_type: Mapped[str] = mapped_column(String(50), nullable=False)  # impact | success_story | guideline
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(_EMBEDDING_DIM), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
