import json
from typing import Annotated, Any, Protocol, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.types import interrupt

from app.harness.gateway import Outcome, ToolGateway


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    pending: dict | None  # an irreversible call waiting on a human
    stop_reason: str | None  # None | "budget_exhausted"
    nudges: int  # times the completion check sent the agent back to work


MAX_NUDGES = 4


class Hooks(Protocol):
    """What the loop needs from the outside world. Production implements these
    against Postgres; tests pass in-memory fakes."""

    async def save_budget(self) -> None: ...
    async def request_approval(self, pending: dict) -> None: ...
    async def finish(self, status: str, summary: str) -> None: ...
    async def completion_blockers(self) -> list[str]: ...


def _tool_message(call_id: str, name: str, outcome: str, result: Any) -> ToolMessage:
    return ToolMessage(content=json.dumps({"outcome": outcome, "result": result}, default=str),
                       tool_call_id=call_id, name=name)


def _tokens(response: AIMessage) -> int:
    usage = getattr(response, "usage_metadata", None) or {}
    return int(usage.get("input_tokens") or 0) + int(usage.get("output_tokens") or 0)


def build_agent_graph(model: Any, gateway: ToolGateway, hooks: Hooks) -> StateGraph:
    """`model` is a chat model already bound to the gateway's tool schemas. The graph
    is the loop; the gateway is the only way it touches the world."""

    async def think(state: AgentState) -> dict:
        reason = gateway.budget.exhausted()
        if reason:
            return {"stop_reason": "budget_exhausted"}
        response = await model.ainvoke(state["messages"])
        gateway.budget.charge_tokens(_tokens(response))
        await hooks.save_budget()
        return {"messages": [response]}

    def after_think(state: AgentState) -> str:
        if state.get("stop_reason"):
            return "finish"
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None):
            return "act"
        # The model wants to stop. A small model will sometimes stop mid-plan, so the
        # decision to accept "done" is checked against facts, not taken on its word.
        return "check" if (state.get("nudges") or 0) < MAX_NUDGES else "finish"

    async def check(state: AgentState) -> dict:
        blockers = await hooks.completion_blockers()
        if not blockers:
            return {}
        text = ("You replied without a tool call, but the work is not finished: "
                + "; ".join(blockers) + ". Reply with the next tool call itself (not text describing one).")
        return {"messages": [HumanMessage(text)], "nudges": (state.get("nudges") or 0) + 1}

    async def act(state: AgentState) -> dict:
        calls = state["messages"][-1].tool_calls
        first, extras = calls[0], calls[1:]
        out: list[ToolMessage] = [
            _tool_message(c["id"], c["name"], "skipped", "one tool call per step; repeat it if still needed")
            for c in extras
        ]
        result = await gateway.call(first["name"], first["args"])
        await hooks.save_budget()
        if result.outcome is Outcome.NEEDS_APPROVAL:
            rationale = state["messages"][-1].content
            pending = {"tool_call_id": first["id"], "tool": first["name"], "args": first["args"],
                       "rationale": rationale if isinstance(rationale, str) else ""}
            await hooks.request_approval(pending)
            return {"messages": out, "pending": pending}
        out.append(_tool_message(first["id"], first["name"], result.outcome.value, result.observation))
        update: dict = {"messages": out}
        if result.outcome is Outcome.BUDGET_EXHAUSTED:
            update["stop_reason"] = "budget_exhausted"
        return update

    def after_act(state: AgentState) -> str:
        if state.get("pending"):
            return "approval"
        return "finish" if state.get("stop_reason") else "think"

    async def approval(state: AgentState) -> dict:
        # Everything before interrupt() re-runs on resume, so nothing with side effects
        # (DB status, audit) happens above it -- that was done once, in `act`.
        pending = state["pending"]
        decision = interrupt({"type": "tool_approval", **pending})
        approved = bool(decision.get("approved"))
        await gateway.log_event(
            "human_decision",
            {"approved": approved, "reviewer": decision.get("reviewer"), "notes": decision.get("notes")},
            args={"tool": pending["tool"]},
        )
        if approved:
            result = await gateway.call(pending["tool"], pending["args"], approved=True)
            message = _tool_message(pending["tool_call_id"], pending["tool"], result.outcome.value,
                                    {"approved_by": decision.get("reviewer"), **(
                                        result.observation if isinstance(result.observation, dict)
                                        else {"value": result.observation})})
        else:
            message = _tool_message(pending["tool_call_id"], pending["tool"], "denied_by_human",
                                    {"notes": decision.get("notes")})
        await hooks.save_budget()
        return {"messages": [message], "pending": None}

    async def finish(state: AgentState) -> dict:
        if state.get("stop_reason") == "budget_exhausted":
            await hooks.finish("budget_exhausted", "Stopped: the run budget was exhausted before the work was complete.")
        else:
            text = state["messages"][-1].content
            await hooks.finish("completed", text if isinstance(text, str) else json.dumps(text))
        return {}

    graph = StateGraph(AgentState)
    graph.add_node("think", think)
    graph.add_node("act", act)
    graph.add_node("approval", approval)
    graph.add_node("check", check)
    graph.add_node("finish", finish)
    graph.add_edge(START, "think")
    graph.add_conditional_edges("think", after_think, {"act": "act", "check": "check", "finish": "finish"})
    graph.add_conditional_edges(
        "check", lambda st: "think" if isinstance(st["messages"][-1], HumanMessage) else "finish",
        {"think": "think", "finish": "finish"},
    )
    graph.add_conditional_edges("act", after_act, {"approval": "approval", "finish": "finish", "think": "think"})
    graph.add_edge("approval", "think")
    graph.add_edge("finish", END)
    return graph
