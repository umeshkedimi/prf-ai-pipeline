import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

CAMPAIGN_DONOR_STATUSES = (
    "staged",  # attached to the campaign, nothing run yet
    "queued",  # a workflow run has been enqueued
    "running",
    "ready",  # run completed and the letter is cleared to mail
    "held",  # needs a human before it can mail
    "blocked",  # cannot mail (ineligible, unregistered state, discarded)
    "excluded",  # deliberately left out of this campaign
)


class CampaignDonor(Base):
    """Membership of a donor in a campaign, plus that donor's campaign-level state.

    A join table rather than a campaign_id on donors: one donor can sit in several
    campaigns. `status` is *derived* from run outcomes and eligibility by code, never
    set freely by a model, and `status_reason` carries the machine-readable cause
    (e.g. `unregistered_state:FL`) that set-level tools cluster on."""

    __tablename__ = "campaign_donors"

    campaign_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id"), primary_key=True
    )
    donor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("donors.id"), primary_key=True, index=True
    )
    import_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("donor_imports.id"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="staged", server_default="staged")
    status_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
