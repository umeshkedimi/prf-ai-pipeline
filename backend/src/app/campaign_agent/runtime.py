"""Wires the loop to the real world: Postgres-backed hooks, the LLM, the checkpointer.
Runs inside a Celery worker (see workers/agent_tasks.py); the API never calls this."""

import uuid

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.types import Command
from sqlalchemy import distinct, select

from app.campaign_agent.loop import build_agent_graph
from app.campaign_agent.prompts import SYSTEM_PROMPT, goal_message
from app.campaign_agent.report import summarize_steps
from app.campaigns.membership import status_counts
from app.campaigns.status import sync_statuses
from app.core.llm import get_llm
from app.core.logging import get_logger
from app.db.models import AgentRun, CampaignDonor, Donor
from app.db.session import db_session
from app.graph.checkpointer import get_checkpointer
from app.harness import store
from app.harness.budget import Budget
from app.harness.campaign_tools import CAMPAIGN_AGENT_ALLOWLIST, build_campaign_tools
from app.harness.gateway import ToolGateway
from app.mcp_clients.compliance_client import get_compliance_tools, parse_single

log = get_logger(__name__)


async def unregistered_states(campaign_id: uuid.UUID) -> set[str]:
    """Registration is the Compliance MCP server's fact: ask it, state by state,
    rather than importing its fixtures."""
    async with db_session() as session:
        states = (
            await session.execute(
                select(distinct(Donor.state))
                .join(CampaignDonor, CampaignDonor.donor_id == Donor.id)
                .where(CampaignDonor.campaign_id == campaign_id, Donor.state.is_not(None))
            )
        ).scalars().all()
    tools = await get_compliance_tools()
    out: set[str] = set()
    for state in states:
        raw = parse_single(await tools["get_disclosure_requirements"].ainvoke({"state": state}))
        if raw.get("registered_to_solicit") is False:
            out.add(state.upper())
    return out


def openai_tool_schemas(gateway: ToolGateway) -> list[dict]:
    return [
        {"type": "function", "function": {"name": t["name"], "description": t["description"],
                                          "parameters": t["parameters"]}}
        for t in gateway.describe()
    ]


class StoreHooks:
    def __init__(self, agent_run_id: uuid.UUID, campaign_id: uuid.UUID, gateway: ToolGateway) -> None:
        self.run_id, self.campaign_id, self.gateway = agent_run_id, campaign_id, gateway

    async def save_budget(self) -> None:
        await store.save_budget(self.run_id, self.gateway.budget)

    async def request_approval(self, pending: dict) -> None:
        await store.request_approval(self.run_id, pending)

    async def finish(self, status: str, summary: str) -> None:
        async with db_session() as session:
            await sync_statuses(session, self.campaign_id)
            await session.commit()
            counts = await status_counts(session, self.campaign_id)
        steps = await store.load_steps(self.run_id)
        report = {
            "agent_summary": summary,  # the model's words, verbatim
            "campaign_status_counts": counts,  # facts from the database
            **summarize_steps(steps),
            "budget": self.gateway.budget.snapshot(),
        }
        await store.finish_run(self.run_id, status, report)


async def run_agent(agent_run_id: uuid.UUID, resume: dict | None) -> None:
    async with db_session() as session:
        run = await session.get(AgentRun, agent_run_id)
        campaign_id, goal, budget = run.campaign_id, run.goal, Budget.from_snapshot(run.budget)

    tools = build_campaign_tools(campaign_id, await unregistered_states(campaign_id))
    gateway = ToolGateway(
        tools, set(CAMPAIGN_AGENT_ALLOWLIST), budget, store.make_audit_sink(agent_run_id),
        start_seq=await store.max_seq(agent_run_id),
    )
    model = get_llm().bind_tools(openai_tool_schemas(gateway))
    hooks = StoreHooks(agent_run_id, campaign_id, gateway)

    async with get_checkpointer() as checkpointer:
        graph = build_agent_graph(model, gateway, hooks).compile(checkpointer=checkpointer)
        config = {"configurable": {"thread_id": f"agent-{agent_run_id}"},
                  "recursion_limit": budget.max_steps * 3 + 10}
        if resume is not None:
            await graph.ainvoke(Command(resume=resume), config)
        else:
            await graph.ainvoke(
                {"messages": [SystemMessage(SYSTEM_PROMPT), HumanMessage(goal_message(goal))]}, config
            )
