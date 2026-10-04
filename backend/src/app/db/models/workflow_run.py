import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class WorkflowRun(Base):
    """id doubles as the LangGraph checkpointer `thread_id`.

    status values: pending | running | awaiting_review | completed | needs_review | failed |
    discarded. `discarded` is terminal: a human decided a letter held back from print
    (see pdf_result.held) should never be mailed. A held letter a human *releases*
    becomes `completed` once its print order is placed.
    `awaiting_review` means the graph is genuinely paused mid-execution on a real
    LangGraph interrupt() and cannot proceed without a decision via POST
    .../review (see pending_review). `needs_review` is a purely advisory
    terminal flag — the graph already reached END, nothing is blocked, it just
    means the outcome is worth a human glance. Which stage set it is decided by
    `workers/tasks.py:_derive_terminal_status`, from whichever stage the run
    actually terminated at: a below-threshold confidence at verification,
    address, recommendation, personalization, or compliance — or, the case
    worth knowing about, a run that reached `generate_pdf` while compliance
    returned `approved: false`, so a letter held back from print after a failed
    risk review surfaces in the queue instead of reading as unremarkable.
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
    # Last sign of life from whatever is executing the graph: stamped when a run
    # starts/resumes and at the start of every node. A `running` run whose heartbeat
    # has gone quiet is stalled (worker died) — see workers/run_recovery.py.
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
