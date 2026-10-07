"""ACT and IRREVERSIBLE tools against a real DB. Celery's .delay is patched out:
launching must create the run rows and mark donors queued without starting an LLM run."""

import uuid

import pytest
from sqlalchemy import delete, select

from app.campaigns.membership import attach_donors_by_external_id
from app.campaigns.status import sync_statuses
from app.db.models import Campaign, CampaignDonor, Donor, WorkflowRun
from app.db.session import db_session
from app.harness.budget import Budget
from app.harness.campaign_tools import CAMPAIGN_AGENT_ALLOWLIST, build_campaign_tools
from app.harness.gateway import Outcome, ToolGateway

pytestmark = pytest.mark.integration
_TAG = uuid.uuid4().hex[:6]


@pytest.fixture
async def campaign(monkeypatch):
    launched = []
    from app.workers import tasks

    monkeypatch.setattr(tasks.run_workflow, "delay", lambda rid: launched.append(rid))
    async with db_session() as s:
        c = Campaign(name=f"act-{_TAG}")
        donors = [
            Donor(external_id=f"at-{_TAG}-1", first_name="A", last_name="One", state="MA", postal_code="2134"),
            Donor(external_id=f"at-{_TAG}-2", first_name="B", last_name="Two", state="WA", postal_code="98101"),
        ]
        s.add(c)
        s.add_all(donors)
        await s.commit()
        await attach_donors_by_external_id(s, c.id, [d.external_id for d in donors])
        await s.commit()
        cid = c.id
    yield cid, launched
    async with db_session() as s:
        await s.execute(delete(WorkflowRun).where(WorkflowRun.campaign_id == cid))
        await s.execute(delete(CampaignDonor).where(CampaignDonor.campaign_id == cid))
        await s.execute(delete(Donor).where(Donor.external_id.like(f"at-{_TAG}-%")))
        await s.execute(delete(Campaign).where(Campaign.id == cid))
        await s.commit()


def _gw(cid, **kw):
    return ToolGateway(build_campaign_tools(cid, set()), set(CAMPAIGN_AGENT_ALLOWLIST), Budget(**kw))


async def test_pad_zip_refuses_ineligible_ids_before_any_human_is_asked(campaign):
    cid, _ = campaign
    gw = _gw(cid)
    mixed = {"external_ids": [f"at-{_TAG}-1", f"at-{_TAG}-2", "invented-1"], "reason": "leading zero dropped"}
    r = await gw.call("pad_postal_codes", mixed)
    assert r.outcome is Outcome.INVALID_ARGS  # never reaches NEEDS_APPROVAL
    assert f"at-{_TAG}-2" in r.observation["errors"][0] and "invented-1" in r.observation["errors"][0]


async def test_pad_zip_needs_approval_then_edits_exactly_the_requested_donors(campaign):
    cid, _ = campaign
    gw = _gw(cid)
    args = {"external_ids": [f"at-{_TAG}-1"], "reason": "leading zero dropped by spreadsheet"}
    assert (await gw.call("pad_postal_codes", args)).outcome is Outcome.NEEDS_APPROVAL
    async with db_session() as s:
        d = (await s.execute(select(Donor).where(Donor.external_id == f"at-{_TAG}-1"))).scalar_one()
        assert d.postal_code == "2134"  # untouched without approval
    r = await gw.call("pad_postal_codes", args, approved=True)
    assert r.observation["changes"] == [{"external_id": f"at-{_TAG}-1", "before": "2134", "after": "02134"}]


async def test_launch_creates_runs_marks_queued_and_refuses_a_second_launch(campaign):
    cid, launched = campaign
    gw = _gw(cid)
    r = await gw.call("launch_donor_runs", {"external_ids": [f"at-{_TAG}-2", "not-a-donor"]})
    assert r.observation["launched"] == 1 and len(launched) == 1
    assert r.observation["skipped"] == [{"external_id": "not-a-donor", "reason": "not_in_campaign"}]
    again = await gw.call("launch_donor_runs", {"external_ids": [f"at-{_TAG}-2"]})
    assert again.observation["skipped"][0]["reason"] == "status_is_queued" and len(launched) == 1


async def test_launch_refuses_the_second_member_of_a_probable_duplicate_pair(campaign):
    cid, launched = campaign
    async with db_session() as s:
        twins = [
            Donor(external_id=f"at-{_TAG}-t{i}", first_name="Marguerite", last_name="Fontaine",
                  address_line1="14 Alder Court", state="WA", postal_code="98101")
            for i in (1, 2)
        ]
        s.add_all(twins)
        await s.commit()
        await attach_donors_by_external_id(s, cid, [t.external_id for t in twins])
        await s.commit()
    r = await _gw(cid).call("launch_donor_runs", {"external_ids": [f"at-{_TAG}-t1", f"at-{_TAG}-t2"]})
    assert r.observation["launched"] == 1 and len(launched) == 1
    assert r.observation["skipped"][0]["reason"].startswith("probable_duplicate_of_")
    # recorded, not just refused: the donor is held with its cause, deterministically
    async with db_session() as s:
        held = (await s.execute(select(CampaignDonor).where(
            CampaignDonor.campaign_id == cid, CampaignDonor.status == "held"))).scalars().all()
    assert len(held) == 1 and held[0].status_reason.startswith("probable_duplicate_of_")


async def test_launch_refuses_a_donor_whose_postal_code_is_still_malformed_until_it_is_fixed(campaign):
    cid, launched = campaign
    gw = _gw(cid)
    # at-..-1 has "2134" (4 digits); at-..-2 has a valid 5-digit code
    r = await gw.call("launch_donor_runs", {"external_ids": [f"at-{_TAG}-1", f"at-{_TAG}-2"]})
    assert r.observation["launched"] == 1 and len(launched) == 1
    assert r.observation["skipped"][0]["reason"] == "malformed_postal_code"
    # after the approved fix it launches
    await gw.call("pad_postal_codes", {"external_ids": [f"at-{_TAG}-1"], "reason": "leading zero dropped"}, approved=True)
    again = await gw.call("launch_donor_runs", {"external_ids": [f"at-{_TAG}-1"]})
    assert again.observation["launched"] == 1


async def test_sync_marks_a_completed_run_ready_and_an_unregistered_one_blocked(campaign):
    cid, _ = campaign
    async with db_session() as s:
        d1, d2 = (await s.execute(select(Donor).where(Donor.external_id.like(f"at-{_TAG}-%"))
                                  .order_by(Donor.external_id))).scalars().all()
        s.add(WorkflowRun(donor_id=d1.id, campaign_id=cid, status="completed", result={}))
        s.add(WorkflowRun(donor_id=d2.id, campaign_id=cid, status="completed",
                          result={"compliance": {"registered_to_solicit": False}}))
        await s.commit()
        await sync_statuses(s, cid)
        await s.commit()
        rows = {r.donor_id: (r.status, r.status_reason) for r in
                (await s.execute(select(CampaignDonor).where(CampaignDonor.campaign_id == cid))).scalars()}
    assert rows[d1.id] == ("ready", None) and rows[d2.id] == ("blocked", "unregistered_state")
