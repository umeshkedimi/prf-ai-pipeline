import asyncio

import pytest
from pydantic import BaseModel, ConfigDict

from app.harness.budget import Budget
from app.harness.gateway import MAX_OBSERVATION_CHARS, AuditRecord, Outcome, ToolGateway
from app.harness.tools import Tier, ToolSpec


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")
    n: int = 1


class _Loose(BaseModel):
    n: int = 1


def _spec(name="t", tier=Tier.READ, fn=None, **kw):
    async def default(a):
        return {"n": a.n}

    return ToolSpec(name, "d", tier, _Args, fn or default, **kw)


def _gw(*specs, allow=None, budget=None, audit=None):
    return ToolGateway(list(specs), allow if allow is not None else {s.name for s in specs},
                       budget or Budget(), audit)


async def test_read_tool_runs_and_returns_observation():
    r = await _gw(_spec()).call("t", {"n": 3})
    assert r.outcome is Outcome.OK and r.observation == {"n": 3}


async def test_tool_not_on_allowlist_is_denied_and_lists_what_is_available():
    gw = _gw(_spec("a"), _spec("b"), allow={"a"})
    r = await gw.call("b", {})
    assert r.outcome is Outcome.DENIED and r.observation["available"] == ["a"]
    assert (await gw.call("nope", {})).outcome is Outcome.DENIED


async def test_describe_hides_tools_outside_the_allowlist():
    gw = _gw(_spec("a"), _spec("b"), allow={"a"})
    assert [t["name"] for t in gw.describe()] == ["a"]


async def test_invalid_and_unknown_args_are_rejected_not_ignored():
    gw = _gw(_spec())
    assert (await gw.call("t", {"n": "x"})).outcome is Outcome.INVALID_ARGS
    r = await gw.call("t", {"approved": True})  # a model cannot smuggle approval in
    assert r.outcome is Outcome.INVALID_ARGS


async def test_irreversible_tool_is_not_executed_without_approval():
    ran = []

    async def fn(a):
        ran.append(1)
        return "done"

    gw = _gw(_spec("mail", Tier.IRREVERSIBLE, fn))
    r = await gw.call("mail", {})
    assert r.outcome is Outcome.NEEDS_APPROVAL and ran == []
    r = await gw.call("mail", {}, approved=True)
    assert r.outcome is Outcome.OK and ran == [1]


async def test_tool_exception_becomes_an_observation():
    async def boom(a):
        raise RuntimeError("db down")

    r = await _gw(_spec(fn=boom)).call("t", {})
    assert r.outcome is Outcome.ERROR and "RuntimeError: db down" in r.observation["error"]


async def test_timeout_becomes_an_error_observation():
    async def slow(a):
        await asyncio.sleep(1)

    r = await _gw(_spec(fn=slow, timeout_s=0.01)).call("t", {})
    assert r.outcome is Outcome.ERROR and "timed out" in r.observation["error"]


async def test_step_budget_stops_even_a_looping_agent_hitting_denials():
    gw = _gw(_spec(), budget=Budget(max_steps=3))
    for _ in range(3):
        await gw.call("nope", {})  # denied calls still cost a step
    r = await gw.call("t", {})
    assert r.outcome is Outcome.BUDGET_EXHAUSTED and r.observation == {"limit": "max_steps"}


async def test_token_budget_is_enforced_once_charged():
    gw = _gw(_spec(), budget=Budget(max_tokens=100))
    gw.budget.charge_tokens(100)
    assert (await gw.call("t", {})).observation == {"limit": "max_tokens"}


async def test_run_budget_blocks_before_executing_and_charges_only_on_success():
    ran = []

    async def launch(a):
        ran.append(a.n)

    spec = _spec("launch", Tier.ACT, launch, run_cost=lambda a: a.n)
    gw = _gw(spec, budget=Budget(max_runs=10))
    assert (await gw.call("launch", {"n": 6})).outcome is Outcome.OK
    r = await gw.call("launch", {"n": 6})
    assert r.outcome is Outcome.BUDGET_EXHAUSTED and r.observation["remaining"] == 4
    assert ran == [6] and gw.budget.runs == 6


async def test_failed_act_call_does_not_consume_run_budget():
    async def boom(a):
        raise RuntimeError("x")

    gw = _gw(_spec("launch", Tier.ACT, boom, run_cost=lambda a: 5), budget=Budget(max_runs=10))
    await gw.call("launch", {})
    assert gw.budget.runs == 0


async def test_oversized_observation_is_truncated():
    async def big(a):
        return ["x" * 100] * 500

    r = await _gw(_spec(fn=big)).call("t", {})
    assert r.observation["truncated"] is True and r.observation["chars"] > MAX_OBSERVATION_CHARS


async def test_every_call_is_audited_including_denials():
    seen: list[AuditRecord] = []

    async def sink(rec):
        seen.append(rec)

    gw = _gw(_spec(), audit=sink)
    await gw.call("t", {})
    await gw.call("nope", {})
    assert [(r.seq, r.tool, r.outcome) for r in seen] == [(1, "t", Outcome.OK), (2, "nope", Outcome.DENIED)]


def test_tool_spec_refuses_an_args_model_that_ignores_unknown_keys():
    async def f(a):
        return None

    with pytest.raises(ValueError):
        ToolSpec("t", "d", Tier.READ, _Loose, f)


def test_budget_snapshot_round_trips():
    b = Budget(max_steps=5)
    b.charge_step()
    b.charge_tokens(7)
    assert Budget.from_snapshot(b.snapshot()) == b
