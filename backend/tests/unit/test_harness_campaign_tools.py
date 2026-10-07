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


def test_the_only_irreversible_tool_is_the_data_edit_and_it_needs_approval():
    tools, _ = _gw()
    assert {t.name for t in tools if t.tier is Tier.IRREVERSIBLE} == {"pad_postal_codes"}
    assert {t.name for t in tools if t.tier is Tier.ACT} == {"launch_donor_runs"}


async def test_irreversible_edit_is_not_executed_without_approval():
    _, gw = _gw()
    r = await gw.call("pad_postal_codes", {"external_ids": ["a"], "reason": "leading zeros dropped"})
    assert r.outcome is Outcome.NEEDS_APPROVAL


async def test_launch_cost_is_the_number_of_distinct_donors():
    tools, gw = _gw()
    gw.budget.max_runs = 2
    r = await gw.call("launch_donor_runs", {"external_ids": ["a", "b", "c"]})
    assert r.outcome is Outcome.BUDGET_EXHAUSTED and r.observation["requested"] == 3


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
