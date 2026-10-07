"""The campaign agent's tool registry. Every tool is bound to ONE campaign at build
time: no argument model has a campaign_id, so the agent cannot read or touch another
campaign no matter what it is told. Read tools wrap the deterministic set-level
queries; the agent never counts, groups or derives status itself.

A PROPOSE call has no side effect of its own: the gateway's audit row (tier=propose)
IS the record, and the final report is built from those rows. ACT tools are charged
against the run budget; the IRREVERSIBLE tool cannot execute without a human."""

import asyncio
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.campaigns import queries
from app.campaigns.membership import status_counts
from app.campaigns.outcomes import postal_shape
from app.campaigns.status import sync_statuses
from app.db.models import CampaignDonor, Donor, WorkflowRun
from app.db.session import db_session
from app.harness.tools import Tier, ToolSpec

MAX_LAUNCH_BATCH = 100
_VALID_SHAPES = {"99999", "99999-9999"}
_FOUR_DIGITS = re.compile(r"^\d{4}$")


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


class _LaunchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    external_ids: list[str] = Field(min_length=1, max_length=MAX_LAUNCH_BATCH)


class _PadZipArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    external_ids: list[str] = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=10, max_length=500)


class _WaitArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_seconds: int = Field(default=60, ge=5, le=120)


Launcher = Callable[[list[uuid.UUID]], Awaitable[None]]


async def enqueue_celery_runs(run_ids: list[uuid.UUID]) -> None:
    from app.workers.tasks import run_workflow  # lazy: tasks imports the whole graph

    for rid in run_ids:
        run_workflow.delay(str(rid))


def build_campaign_tools(
    campaign_id: uuid.UUID, unregistered_states: set[str], launcher: Launcher = enqueue_celery_runs
) -> list[ToolSpec]:
    """`launcher` starts the per-donor workflow for the given run ids. Production
    enqueues Celery; the agent eval swaps in a simulator so it measures the agent's
    judgment without paying for the pipeline."""
    async def refreshed():
        """Brings campaign_donors.status up to date before a read (idempotent)."""
        async with db_session() as s:
            await sync_statuses(s, campaign_id)
            await s.commit()

    async def profile(_: _NoArgs):
        await refreshed()
        async with db_session() as s:
            return await queries.profile_campaign(s, campaign_id, unregistered_states)

    async def duplicates(_: _NoArgs):
        async with db_session() as s:
            return await queries.find_duplicate_pairs(s, campaign_id)

    async def clusters(_: _NoArgs):
        await refreshed()
        async with db_session() as s:
            return await queries.cluster_failures(s, campaign_id)

    async def by_status(a: _ListArgs):
        await refreshed()
        async with db_session() as s:
            return await queries.list_donors_by_status(s, campaign_id, a.status, a.limit, a.offset)

    async def launch(a: _LaunchArgs):
        wanted = list(dict.fromkeys(a.external_ids))
        launched: list[str] = []
        skipped: list[dict] = []
        run_ids: list[uuid.UUID] = []
        async with db_session() as s:
            rows = (
                await s.execute(
                    select(Donor, CampaignDonor)
                    .join(CampaignDonor, CampaignDonor.donor_id == Donor.id)
                    .where(CampaignDonor.campaign_id == campaign_id, Donor.external_id.in_(wanted))
                )
            ).all()
            found = {d.external_id: (d, cd) for d, cd in rows}
            # Hard rule, enforced here and not left to the prompt: the second member of a
            # probable-duplicate pair is never launched by the agent. (A live run flagged
            # both pairs correctly, then launched both members anyway a few steps later.)
            secondary = {p["b"]: p["a"] for p in await queries.find_duplicate_pairs(s, campaign_id)}
            for ext in wanted:
                if ext in secondary and ext in found:
                    # Not just refused: recorded. The donor is held with its cause so it
                    # shows up as needing a person whether or not the model ever says so
                    # (a live run lost this pair when the model's proposal call was malformed).
                    if found[ext][1].status == "staged":
                        found[ext][1].status = "held"
                        found[ext][1].status_reason = f"probable_duplicate_of_{secondary[ext]}"
                    skipped.append({
                        "external_id": ext,
                        "reason": f"probable_duplicate_of_{secondary[ext]}",
                        "hint": "use propose_action(kind='needs_human_decision') for this donor",
                    })
                elif ext not in found:
                    skipped.append({"external_id": ext, "reason": "not_in_campaign"})
                elif found[ext][0].postal_code and postal_shape(found[ext][0].postal_code) not in _VALID_SHAPES:
                    # Another hard rule: a live run requested a fix for 2 of 4 malformed codes
                    # and launched the other two as they were. Launching dirty data is what the
                    # agent exists to prevent, so it cannot be skipped by omission.
                    skipped.append({
                        "external_id": ext,
                        "reason": "malformed_postal_code",
                        "postal_code": found[ext][0].postal_code,
                        "hint": "fix it with pad_postal_codes (needs approval) or propose_action to hold it",
                    })
                elif found[ext][1].status != "staged":
                    skipped.append({"external_id": ext, "reason": f"status_is_{found[ext][1].status}"})
                else:
                    donor, member = found[ext]
                    run = WorkflowRun(donor_id=donor.id, campaign_id=campaign_id)
                    s.add(run)
                    await s.flush()
                    member.status = "queued"
                    run_ids.append(run.id)
                    launched.append(ext)
            await s.commit()
        await launcher(run_ids)
        return {"launched": len(launched), "skipped": skipped, "launched_external_ids": launched}

    async def wait(a: _WaitArgs):
        deadline = time.monotonic() + a.max_seconds
        while True:
            await refreshed()
            async with db_session() as s:
                counts = await status_counts(s, campaign_id)
            in_flight = counts["queued"] + counts["running"]
            if in_flight == 0 or time.monotonic() >= deadline:
                return {"in_flight": in_flight, "status_counts": counts, "timed_out": in_flight > 0}
            await asyncio.sleep(5)

    async def pad_zips(a: _PadZipArgs):
        changed: list[dict] = []
        skipped: list[dict] = []
        async with db_session() as s:
            rows = (
                await s.execute(
                    select(Donor)
                    .join(CampaignDonor, CampaignDonor.donor_id == Donor.id)
                    .where(CampaignDonor.campaign_id == campaign_id, Donor.external_id.in_(a.external_ids))
                )
            ).scalars().all()
            found = {d.external_id: d for d in rows}
            for ext in dict.fromkeys(a.external_ids):
                donor = found.get(ext)
                if donor is None:
                    skipped.append({"external_id": ext, "reason": "not_in_campaign"})
                elif not _FOUR_DIGITS.match(donor.postal_code or ""):
                    skipped.append({"external_id": ext, "reason": "postal_code_not_4_digits"})
                else:
                    before, donor.postal_code = donor.postal_code, "0" + donor.postal_code
                    changed.append({"external_id": ext, "before": before, "after": donor.postal_code})
            await s.commit()
        return {"changed": len(changed), "changes": changed, "skipped": skipped}

    async def pad_precheck(a: _PadZipArgs) -> str | None:
        wanted = list(dict.fromkeys(a.external_ids))
        async with db_session() as s:
            rows = (
                await s.execute(
                    select(Donor.external_id, Donor.postal_code)
                    .join(CampaignDonor, CampaignDonor.donor_id == Donor.id)
                    .where(CampaignDonor.campaign_id == campaign_id, Donor.external_id.in_(wanted))
                )
            ).all()
        ok = {ext for ext, zip_ in rows if _FOUR_DIGITS.match(zip_ or "")}
        bad = [i for i in wanted if i not in ok]
        if bad:
            return (f"not eligible (not in this campaign, or postal code is not 4 digits): {bad[:10]}. "
                    "Use only ids listed in profile_campaign's malformed_postal_codes.")
        return None

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
        ToolSpec("wait_for_runs", "Wait (up to max_seconds) for launched donor runs to finish, then return "
                 "the campaign's status counts (max_seconds 5-120). Use after launching a batch, before reading outcomes.",
                 Tier.READ, _WaitArgs, wait, timeout_s=150),
        ToolSpec("launch_donor_runs", f"Start the donor workflow for up to {MAX_LAUNCH_BATCH} staged donors "
                 "(by external_id). Each donor counts against the run budget. Only 'staged' donors launch.",
                 Tier.ACT, _LaunchArgs, launch, run_cost=lambda a: len(set(a.external_ids))),
        ToolSpec("pad_postal_codes", "Fix postal codes that lost a leading zero (4 digits -> 5) for the given "
                 "donors. Edits donor records permanently, so it requires human approval.",
                 Tier.IRREVERSIBLE, _PadZipArgs, pad_zips, precheck=pad_precheck),
        ToolSpec("propose_action", "Record a proposed action (hold/skip/bulk_fix/needs_human_decision) with a "
                 "reason for a human to review. Changes nothing.", Tier.PROPOSE, _ProposeArgs, propose),
    ]


# What the campaign agent may call. Anything not listed here is DENIED by the gateway.
CAMPAIGN_AGENT_ALLOWLIST = frozenset(
    {
        "profile_campaign", "find_duplicate_pairs", "cluster_failures", "list_donors_by_status",
        "wait_for_runs", "launch_donor_runs", "pad_postal_codes", "propose_action",
    }
)
