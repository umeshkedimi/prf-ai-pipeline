import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

class AgentRun(Base):
    """One campaign-agent run: the durable record of a long-lived loop. The loop's own
    resumable state lives in the LangGraph checkpointer (keyed by this id); this row
    carries what operators and the dashboard need -- status, budget usage, the call
    awaiting a human, and the final report.

    status: running | awaiting_approval (paused on an irreversible call, see
    pending_approval) | completed | completed_with_gaps (it stopped, but donors were
    still in flight or unaddressed) | budget_exhausted | stopped (a human stopped it) |
    failed."""

    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=False, index=True
    )
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", server_default="running")
    budget: Mapped[dict] = mapped_column(JSONB, nullable=False)  # Budget.snapshot(): limits + usage
    pending_approval: Mapped[dict | None] = mapped_column(JSONB)
    final_report: Mapped[dict | None] = mapped_column(JSONB)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Stamped on every loop step; a `running` run whose heartbeat has gone quiet lost
    # its worker (see workers/agent_recovery.py). `awaiting_approval` is a legitimate
    # pause and is never considered stalled.
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AgentStep(Base):
    """One gateway call, including denied and invalid ones -- the replayable
    trajectory. (agent_run_id, seq) is unique so a retried write cannot duplicate."""

    __tablename__ = "agent_steps"
    __table_args__ = (UniqueConstraint("agent_run_id", "seq", name="uq_agent_steps_run_seq"),)

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    agent_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("agent_runs.id"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    tool: Mapped[str] = mapped_column(String(80), nullable=False)
    tier: Mapped[str | None] = mapped_column(String(20))
    args: Mapped[dict | None] = mapped_column(JSONB)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    observation: Mapped[dict | list | None] = mapped_column(JSONB)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
