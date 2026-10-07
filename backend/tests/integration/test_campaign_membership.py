"""Membership against a real DB: attaching is idempotent and never resets a donor's
status, and unknown external_ids are ignored rather than raising."""

import uuid

import pytest
from sqlalchemy import delete, select

from app.campaigns.membership import attach_donors_by_external_id, status_counts
from app.db.models import Campaign, CampaignDonor, Donor

pytestmark = pytest.mark.integration

_EXT = f"cm-{uuid.uuid4().hex[:6]}"


@pytest.fixture
async def campaign_with_donor(db_session):
    campaign = Campaign(name="membership-test")
    donor = Donor(external_id=_EXT, first_name="Ada", last_name="Lovelace")
    db_session.add_all([campaign, donor])
    await db_session.commit()
    yield campaign, donor
    await db_session.execute(delete(CampaignDonor).where(CampaignDonor.campaign_id == campaign.id))
    await db_session.execute(delete(Donor).where(Donor.id == donor.id))
    await db_session.execute(delete(Campaign).where(Campaign.id == campaign.id))
    await db_session.commit()


async def test_attach_is_idempotent_and_preserves_status(db_session, campaign_with_donor):
    campaign, donor = campaign_with_donor
    assert await attach_donors_by_external_id(db_session, campaign.id, [_EXT, "no-such-donor"]) == 1
    await db_session.commit()

    row = (await db_session.execute(select(CampaignDonor).where(CampaignDonor.donor_id == donor.id))).scalar_one()
    row.status = "ready"
    await db_session.commit()

    assert await attach_donors_by_external_id(db_session, campaign.id, [_EXT]) == 0
    await db_session.commit()
    await db_session.refresh(row)
    assert row.status == "ready"
    counts = await status_counts(db_session, campaign.id)
    assert counts["ready"] == 1 and counts["staged"] == 0
