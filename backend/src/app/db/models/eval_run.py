import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EvalRun(Base):
    """One execution of one eval suite. Kept as history so metric movement is
    queryable over time — "did that prompt change improve groundedness?" is a
    SQL question, not a guess. `git_sha` ties a score to the code that produced
    it, and `llm_model`/`judge_model` to the models that produced it — a
    provider swap moves every metric at once, and without those columns the
    trend line reads it as a code regression."""

    __tablename__ = "eval_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    suite: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    git_sha: Mapped[str | None] = mapped_column(String(40))
    llm_model: Mapped[str | None] = mapped_column(String(100))
    judge_model: Mapped[str | None] = mapped_column(String(100))
    runs_per_case: Mapped[int] = mapped_column(Integer, nullable=False)
    case_count: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_s: Mapped[float] = mapped_column(Float, nullable=False)
    # Full report payload: metrics with their detail tables, flaky cases, failures.
    report: Mapped[dict] = mapped_column(JSONB, nullable=False)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
