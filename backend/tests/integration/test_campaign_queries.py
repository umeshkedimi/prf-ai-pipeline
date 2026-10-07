"""Set-level campaign tools against a real DB with planted defects: a malformed-ZIP
cluster, a duplicate pair, unregistered-state donors and an opted-out donor."""

import uuid

import pytest
from sqlalchemy import delete

from app.campaigns.membership import attach_donors_by_external_id
from app.campaigns.queries import cluster_failures, find_duplicate_pairs, profile_campaign
from app.db.models import Campaign, CampaignDonor, Donor, WorkflowRun

pytestmark = pytest.mark.integration

_TAG = uuid.uuid4().hex[:6]


def _donor(n, first, last, addr, state="WA", zip_="98101", dnc=False):
    return Donor(
        external_id=f"cq-{_TAG}-{n}", first_name=first, last_name=last, address_line1=addr,
        state=state, postal_code=zip_, do_not_contact=dnc,
    )


@pytest.fixture
async def planted(db_session):
    campaign = Campaign(name=f"planted-{_TAG}")
    donors = [
        _donor(1, "Marguerite", "Fontaine", "14 Alder Court", zip_="9810"),  # bad ZIP x3
        _donor(2, "Tobias", "Wendell", "9 Birch Lane", zip_="9811"),
        _donor(3, "Imelda", "Okafor", "77 Cedar Row", zip_="9812"),
        _donor(4, "Marguerite", "Fontaine", "14 Alder Ct", zip_="98101"),  # dup of 1
        _donor(5, "Pavel", "Novak", "5 Elm Street", state="FL", zip_="33101"),  # unregistered
        _donor(6, "Sunita", "Rao", "30 Fir Avenue", dnc=True),
    ]
    db_session.add(campaign)
    db_session.add_all(donors)
    await db_session.commit()
    await attach_donors_by_external_id(db_session, campaign.id, [d.external_id for d in donors])
    for d in donors[:3]:
        db_session.add(WorkflowRun(donor_id=d.id, campaign_id=campaign.id, status="awaiting_review",
                                   pending_review={"reason": "address_confidence_below_threshold"}))
    db_session.add(WorkflowRun(donor_id=donors[4].id, campaign_id=campaign.id, status="completed",
                               result={"compliance": {"registered_to_solicit": False}}))
    await db_session.commit()
    yield campaign
    await db_session.execute(delete(WorkflowRun).where(WorkflowRun.campaign_id == campaign.id))
    await db_session.execute(delete(CampaignDonor).where(CampaignDonor.campaign_id == campaign.id))
    await db_session.execute(delete(Donor).where(Donor.external_id.like(f"cq-{_TAG}-%")))
    await db_session.execute(delete(Campaign).where(Campaign.id == campaign.id))
    await db_session.commit()


async def test_profile_surfaces_the_planted_defects(db_session, planted):
    p = await profile_campaign(db_session, planted.id, unregistered_states={"FL"})
    assert p["total"] == 6
    assert p["postal_shapes"]["9999"] == 3
    assert len(p["malformed_postal_codes"]) == 3  # ids, so an agent never has to guess
    assert {m["external_id"][-1] for m in p["malformed_postal_codes"]} == {"1", "2", "3"}
    assert p["do_not_contact"] == 1
    assert p["in_unregistered_states"] == 1


async def test_duplicate_pair_found_and_distinct_donors_not_paired(db_session, planted):
    pairs = await find_duplicate_pairs(db_session, planted.id)
    assert len(pairs) == 1
    assert {pairs[0]["a"][-1], pairs[0]["b"][-1]} == {"1", "4"}


async def test_cluster_failures_groups_the_shared_zip_defect(db_session, planted):
    clusters = await cluster_failures(db_session, planted.id)
    assert clusters[0]["reason"] == "paused:address_confidence_below_threshold"
    assert clusters[0]["signature"] == "postal_shape=9999"
    assert clusters[0]["count"] == 3
    assert {c["reason"] for c in clusters} == {
        "paused:address_confidence_below_threshold", "unregistered_state",
    }
