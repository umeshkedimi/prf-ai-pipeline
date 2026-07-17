import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AgentAuditLog(Base):
    """One row per agent-node decision — the explainability/audit trail.

    source_refs captures which tool calls backed the decision (tool_name/args/result
    summary); tool_calls stores the raw tool_use/tool_result pairs for full replay.
    """

    __tablename__ = "agent_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    workflow_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=False, index=True
    )
    agent_name: Mapped[str] = mapped_column(String(50), nullable=False)
    step: Mapped[str] = mapped_column(String(50), nullable=False)
    input_snapshot: Mapped[dict | None] = mapped_column(JSONB)
    output: Mapped[dict | None] = mapped_column(JSONB)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    reasoning: Mapped[str | None] = mapped_column(Text)
    source_refs: Mapped[list | None] = mapped_column(JSONB)
    tool_calls: Mapped[list | None] = mapped_column(JSONB)
    model: Mapped[str | None] = mapped_column(String(100))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
