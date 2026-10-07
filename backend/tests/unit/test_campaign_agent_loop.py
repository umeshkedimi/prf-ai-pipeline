"""The loop, offline: a scripted model drives the real gateway and graph through
LangGraph's real interrupt/resume, with in-memory hooks."""

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import Command
from pydantic import BaseModel, ConfigDict

from app.campaign_agent.loop import build_agent_graph
from app.campaign_agent.report import summarize_steps
from app.harness.budget import Budget
from app.harness.gateway import ToolGateway
from app.harness.tools import Tier, ToolSpec


class _A(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: int = 0


class _Script:
    """Stands in for the chat model: returns the next scripted AIMessage."""

    def __init__(self, *msgs):
        self.msgs, self.seen = list(msgs), []

    async def ainvoke(self, messages):
        self.seen.append(list(messages))
        return self.msgs.pop(0)


class _Hooks:
    def __init__(self):
        self.approvals, self.finished, self.saves = [], None, 0

    async def save_budget(self):
        self.saves += 1

    async def request_approval(self, pending):
        self.approvals.append(pending)

    async def finish(self, status, summary):
        self.finished = (status, summary)


def _call(name, args=None, id="c1", content=""):
    return AIMessage(content=content, tool_calls=[{"name": name, "args": args or {}, "id": id}])


def _setup(script, *, budget=None):
    ran = []

    async def read(a):
        ran.append(("read", a.x))
        return {"v": a.x}

    async def edit(a):
        ran.append(("edit", a.x))
        return {"changed": a.x}

    gw = ToolGateway(
        [ToolSpec("read", "d", Tier.READ, _A, read), ToolSpec("edit", "d", Tier.IRREVERSIBLE, _A, edit)],
        {"read", "edit"}, budget or Budget(),
    )
    hooks = _Hooks()
    graph = build_agent_graph(_Script(*script), gw, hooks).compile(checkpointer=MemorySaver())
    return graph, gw, hooks, ran


def _cfg():
    return {"configurable": {"thread_id": "t"}, "recursion_limit": 50}


async def test_reads_then_finishes_with_the_models_summary():
    graph, _, hooks, ran = _setup([_call("read", {"x": 2}), AIMessage(content="all done")])
    await graph.ainvoke({"messages": [HumanMessage("go")]}, _cfg())
    assert ran == [("read", 2)] and hooks.finished == ("completed", "all done")


async def test_irreversible_call_pauses_and_executes_only_after_approval():
    graph, _, hooks, ran = _setup([_call("edit", {"x": 5}, content="zip defect"), AIMessage(content="fixed")])
    out = await graph.ainvoke({"messages": [HumanMessage("go")]}, _cfg())
    assert "__interrupt__" in out and ran == [] and hooks.finished is None
    assert hooks.approvals[0]["tool"] == "edit" and hooks.approvals[0]["rationale"] == "zip defect"

    await graph.ainvoke(Command(resume={"approved": True, "reviewer": "admin@x"}), _cfg())
    assert ran == [("edit", 5)] and hooks.finished == ("completed", "fixed")
    assert len(hooks.approvals) == 1  # resume must not re-request approval


async def test_denial_means_the_tool_never_runs_and_the_agent_can_continue():
    graph, _, hooks, ran = _setup([_call("edit"), AIMessage(content="skipped the fix")])
    await graph.ainvoke({"messages": [HumanMessage("go")]}, _cfg())
    await graph.ainvoke(Command(resume={"approved": False, "reviewer": "a", "notes": "not now"}), _cfg())
    assert ran == [] and hooks.finished == ("completed", "skipped the fix")


async def test_only_one_tool_call_per_step_is_executed():
    two = AIMessage(content="", tool_calls=[
        {"name": "read", "args": {"x": 1}, "id": "a"}, {"name": "read", "args": {"x": 2}, "id": "b"}])
    graph, _, _, ran = _setup([two, AIMessage(content="ok")])
    await graph.ainvoke({"messages": [HumanMessage("go")]}, _cfg())
    assert ran == [("read", 1)]


async def test_a_looping_agent_is_stopped_by_the_step_budget():
    graph, _, hooks, ran = _setup([_call("read", id=str(i)) for i in range(10)], budget=Budget(max_steps=3))
    await graph.ainvoke({"messages": [HumanMessage("go")]}, _cfg())
    assert len(ran) == 3 and hooks.finished[0] == "budget_exhausted"


async def test_token_budget_stops_before_another_model_call():
    msg = _call("read")
    msg.usage_metadata = {"input_tokens": 90, "output_tokens": 20, "total_tokens": 110}
    graph, gw, hooks, _ = _setup([msg, AIMessage(content="never reached")], budget=Budget(max_tokens=100))
    await graph.ainvoke({"messages": [HumanMessage("go")]}, _cfg())
    assert gw.budget.tokens == 110 and hooks.finished[0] == "budget_exhausted"


async def test_tool_errors_are_fed_back_not_raised():
    graph, _, hooks, _ = _setup([_call("nope"), AIMessage(content="gave up")])
    await graph.ainvoke({"messages": [HumanMessage("go")]}, _cfg())
    assert hooks.finished == ("completed", "gave up")


def test_summarize_steps_reports_facts_from_the_trail():
    steps = [
        {"tool": "propose_action", "tier": "propose", "outcome": "ok",
         "args": {"kind": "hold", "donor_external_ids": ["a"], "reason": "r"}},
        {"tool": "launch_donor_runs", "tier": "act", "outcome": "ok", "observation": {"launched": 9}},
        {"tool": "human_decision", "tier": None, "outcome": "ok", "args": {"tool": "pad_postal_codes"},
         "observation": {"approved": True, "reviewer": "admin"}},
        {"tool": "pad_postal_codes", "tier": "irreversible", "outcome": "ok", "observation": {"changed": 8}},
        {"tool": "x", "tier": None, "outcome": "denied"},
    ]
    s = summarize_steps(steps)
    assert s["proposals"][0]["kind"] == "hold" and s["refused_calls"]["denied"] == 1
    assert [a.get("launched") or a.get("changed") for a in s["actions"]] == [9, 8]
    assert s["human_decisions"][0]["approved"] is True and s["steps"] == 5

