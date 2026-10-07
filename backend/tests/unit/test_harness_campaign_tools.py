import uuid

from app.harness.budget import Budget
from app.harness.campaign_tools import CAMPAIGN_AGENT_ALLOWLIST, build_campaign_tools
from app.harness.gateway import Outcome, ToolGateway
from app.harness.tools import Tier


def _gw():
    tools = build_campaign_tools(uuid.uuid4(), {"FL"})
    return tools, ToolGateway(tools, set(CAMPAIGN_AGENT_ALLOWLIST), Budget())


def test_allowlist_matches_the_registry_exactly():
    tools, _ = _gw()
    assert {t.name for t in tools} == set(CAMPAIGN_AGENT_ALLOWLIST)


def test_only_read_and_propose_tiers_are_registered_so_far():
    tools, _ = _gw()
    assert {t.tier for t in tools} <= {Tier.READ, Tier.PROPOSE}


async def test_no_tool_accepts_a_campaign_id_so_scope_cannot_be_escaped():
    tools, gw = _gw()
    for t in tools:
        assert "campaign_id" not in t.args_model.model_fields
        assert (await gw.call(t.name, {"campaign_id": str(uuid.uuid4())})).outcome is Outcome.INVALID_ARGS


async def test_propose_validates_and_changes_nothing():
    _, gw = _gw()
    ok = await gw.call("propose_action", {"kind": "hold", "donor_external_ids": ["a"], "reason": "shared ZIP defect"})
    assert ok.outcome is Outcome.OK and "nothing was changed" in ok.observation["note"]
    bad = await gw.call("propose_action", {"kind": "mail_everyone", "donor_external_ids": ["a"], "reason": "x" * 20})
    assert bad.outcome is Outcome.INVALID_ARGS


async def test_list_limit_is_capped():
    _, gw = _gw()
    r = await gw.call("list_donors_by_status", {"status": "held", "limit": 5000})
    assert r.outcome is Outcome.INVALID_ARGS
