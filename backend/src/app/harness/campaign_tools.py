"""The campaign agent's tool registry. Every tool is bound to ONE campaign at build
time: no argument model has a campaign_id, so the agent cannot read or touch another
campaign no matter what it is told. Read tools wrap the deterministic set-level
queries; the agent never counts, groups or derives status itself.

Act and irreversible tools (launching runs, approving mail) are added with the agent
loop. A PROPOSE call has no side effect of its own: the gateway's audit row
(tier=propose) IS the record, and the final report is built from those rows."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.campaigns import queries
from app.db.session import db_session
from app.harness.tools import Tier, ToolSpec


class _NoArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _ListArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["staged", "queued", "running", "ready", "held", "blocked", "excluded"]
    limit: int = Field(default=25, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class _ProposeArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["hold", "skip", "bulk_fix", "needs_human_decision"]
    donor_external_ids: list[str] = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=10, max_length=500)


def build_campaign_tools(campaign_id: uuid.UUID, unregistered_states: set[str]) -> list[ToolSpec]:
    async def profile(_: _NoArgs):
        async with db_session() as s:
            return await queries.profile_campaign(s, campaign_id, unregistered_states)

    async def duplicates(_: _NoArgs):
        async with db_session() as s:
            return await queries.find_duplicate_pairs(s, campaign_id)

    async def clusters(_: _NoArgs):
        async with db_session() as s:
            return await queries.cluster_failures(s, campaign_id)

    async def by_status(a: _ListArgs):
        async with db_session() as s:
            return await queries.list_donors_by_status(s, campaign_id, a.status, a.limit, a.offset)

    async def propose(a: _ProposeArgs):
        return {"recorded": True, "kind": a.kind, "donors": len(a.donor_external_ids),
                "note": "proposal recorded for human review; nothing was changed"}

    return [
        ToolSpec("profile_campaign", "Aggregate data-quality profile of this campaign's donors: counts, "
                 "missing fields, ZIP-format distribution, states, opt-outs.", Tier.READ, _NoArgs, profile),
        ToolSpec("find_duplicate_pairs", "Probable duplicate donor pairs within this campaign.",
                 Tier.READ, _NoArgs, duplicates),
        ToolSpec("cluster_failures", "Group failed/held/blocked donors by shared cause (reason + signature "
                 "such as a ZIP shape or state). Use this to find systemic problems.", Tier.READ, _NoArgs, clusters),
        ToolSpec("list_donors_by_status", "Page through donors in a given campaign status.",
                 Tier.READ, _ListArgs, by_status),
        ToolSpec("propose_action", "Record a proposed action (hold/skip/bulk_fix/needs_human_decision) with a "
                 "reason for a human to review. Changes nothing.", Tier.PROPOSE, _ProposeArgs, propose),
    ]


# What the campaign agent may call. Anything not listed here is DENIED by the gateway.
CAMPAIGN_AGENT_ALLOWLIST = frozenset(
    {"profile_campaign", "find_duplicate_pairs", "cluster_failures", "list_donors_by_status", "propose_action"}
)
