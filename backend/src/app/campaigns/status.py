"""Keeps campaign_donors.status in step with what actually happened to each donor.
Derived data: status is always recomputed from the donor's latest run, never set by
a model, so calling this is idempotent and safe from any read path."""

import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.campaigns.outcomes import campaign_donor_status, outcome_reason
from app.campaigns.queries import latest_runs
from app.db.models import CampaignDonor


async def sync_statuses(session: AsyncSession, campaign_id: uuid.UUID) -> int:
    """Returns how many donors were examined. Does not commit. `excluded` is a human
    decision and is never overwritten; donors with no run keep their status."""
    count = 0
    for run, donor in await latest_runs(session, campaign_id):
        reason = outcome_reason(run.status, run.result, run.pending_review, run.error)
        await session.execute(
            update(CampaignDonor)
            .where(
                CampaignDonor.campaign_id == campaign_id,
                CampaignDonor.donor_id == donor.id,
                CampaignDonor.status != "excluded",
            )
            .values(status=campaign_donor_status(reason), status_reason=None if reason == "ok" else reason)
        )
        count += 1
    return count
