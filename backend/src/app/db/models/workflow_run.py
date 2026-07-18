import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkflowRun(Base):
    """id doubles as the LangGraph checkpointer `thread_id`.

    status values: pending | running | awaiting_review | completed | needs_review | failed.
    `awaiting_review` means the graph is genuinely paused mid-execution on a real
    LangGraph interrupt() and cannot proceed without a decision via POST
    .../review (see pending_review). `needs_review` (from Phase 1) is a purely
    advisory terminal flag — the graph already reached END, nothing is blocked,
    it just means a low-confidence verification outcome is worth a human glance.
    """

    __tablename__ = "workflow_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    donor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("donors.id"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("campaigns.id"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")
    current_agent: Mapped[str | None] = mapped_column(String(50))
    result: Mapped[dict | None] = mapped_column(JSONB)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    pending_review: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
