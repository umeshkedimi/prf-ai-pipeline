import uuid

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Donor
from app.db.models.campaign_donor import CAMPAIGN_DONOR_STATUSES, CampaignDonor


def zero_filled_counts(rows: list[tuple[str, int]]) -> dict[str, int]:
    """Every known status appears, with 0 when empty -- a consumer (dashboard or
    agent) should never have to distinguish 'no such key' from 'none'."""
    counts = {status: 0 for status in CAMPAIGN_DONOR_STATUSES}
    for status, n in rows:
        counts[status] = n
    return counts


async def attach_donors_by_external_id(
    session: AsyncSession,
    campaign_id: uuid.UUID,
    external_ids: list[str],
    import_id: uuid.UUID | None = None,
) -> int:
    """Adds donors to a campaign as `staged`. Idempotent: a donor already in the
    campaign keeps its current status (re-uploading a file must not reset a donor
    that has since been run). Returns the number of NEW memberships. Does not commit."""
    if not external_ids:
        return 0
    donor_ids = (
        await session.execute(select(Donor.id).where(Donor.external_id.in_(external_ids)))
    ).scalars().all()
    if not donor_ids:
        return 0
    stmt = (
        insert(CampaignDonor)
        .values([{"campaign_id": campaign_id, "donor_id": d, "import_id": import_id} for d in donor_ids])
        .on_conflict_do_nothing(index_elements=["campaign_id", "donor_id"])
        .returning(CampaignDonor.donor_id)
    )
    return len((await session.execute(stmt)).all())


async def status_counts(session: AsyncSession, campaign_id: uuid.UUID) -> dict[str, int]:
    rows = (
        await session.execute(
            select(CampaignDonor.status, func.count())
            .where(CampaignDonor.campaign_id == campaign_id)
            .group_by(CampaignDonor.status)
        )
    ).all()
    return zero_filled_counts([(s, n) for s, n in rows])
