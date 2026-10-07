"""The gateway end to end over a real campaign: a read tool returns real data, and the
trajectory lands in agent_steps."""

import uuid

import pytest
from sqlalchemy import delete, select

from app.campaigns.membership import attach_donors_by_external_id
from app.db.models import AgentRun, AgentStep, Campaign, CampaignDonor, Donor
from app.db.session import db_session
from app.harness import store
from app.harness.budget import Budget
from app.harness.campaign_tools import CAMPAIGN_AGENT_ALLOWLIST, build_campaign_tools
from app.harness.gateway import Outcome, ToolGateway

pytestmark = pytest.mark.integration

_EXT = f"ht-{uuid.uuid4().hex[:6]}"


async def test_gateway_reads_real_data_and_persists_the_trajectory():
    async with db_session() as s:
        c = Campaign(name="harness-e2e")
        d = Donor(external_id=_EXT, first_name="Ada", last_name="Lovelace", state="FL", postal_code="3310")
        s.add_all([c, d])
        await s.commit()
        await attach_donors_by_external_id(s, c.id, [_EXT])
        await s.commit()
        cid, did = c.id, d.id
    budget = Budget()
    rid = await store.create_agent_run(cid, "prepare", budget)
    try:
        gw = ToolGateway(build_campaign_tools(cid, {"FL"}), set(CAMPAIGN_AGENT_ALLOWLIST), budget,
                         store.make_audit_sink(rid))
        profile = await gw.call("profile_campaign")
        await gw.call("delete_everything")
        assert profile.outcome is Outcome.OK
        assert profile.observation["total"] == 1 and profile.observation["in_unregistered_states"] == 1
        assert profile.observation["postal_shapes"] == {"9999": 1}
        async with db_session() as s:
            steps = (await s.execute(select(AgentStep).where(AgentStep.agent_run_id == rid)
                                     .order_by(AgentStep.seq))).scalars().all()
        assert [(x.tool, x.outcome) for x in steps] == [("profile_campaign", "ok"), ("delete_everything", "denied")]
    finally:
        async with db_session() as s:
            await s.execute(delete(AgentStep).where(AgentStep.agent_run_id == rid))
            await s.execute(delete(AgentRun).where(AgentRun.id == rid))
            await s.execute(delete(CampaignDonor).where(CampaignDonor.campaign_id == cid))
            await s.execute(delete(Donor).where(Donor.id == did))
            await s.execute(delete(Campaign).where(Campaign.id == cid))
            await s.commit()
