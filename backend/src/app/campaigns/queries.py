"""Set-level, read-only campaign queries: the tools the campaign agent will call.
Each returns plain JSON-able data and never mutates anything."""

import uuid
from collections import Counter

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.campaigns.membership import status_counts
from app.campaigns.outcomes import group_failures, outcome_reason, postal_shape
from app.db.models import CampaignDonor, Donor, WorkflowRun

# Tunable. Both signals must be present: a shared surname alone (name only) or a
# shared building (address only) is not a duplicate. The per-record lookup in the CRM
# server uses a loose either/or at 0.3 because it returns candidates for a model to
# weigh; a set-level scan over thousands of pairs must be tighter or it drowns the
# reviewer.
NAME_SIM_MIN = 0.4
ADDR_SIM_MIN = 0.4
COMBINED_SIM_MIN = 1.3
MAX_PAIRS = 200


async def profile_campaign(
    session: AsyncSession, campaign_id: uuid.UUID, unregistered_states: set[str]
) -> dict:
    """`unregistered_states` is injected rather than looked up here: registration is
    the Compliance MCP server's fact, and this module must not import its fixtures."""
    donors = (
        await session.execute(
            select(Donor)
            .join(CampaignDonor, CampaignDonor.donor_id == Donor.id)
            .where(CampaignDonor.campaign_id == campaign_id)
        )
    ).scalars().all()
    unregistered = {s.upper() for s in unregistered_states}
    states = Counter((d.state or "").upper() or "missing" for d in donors)
    return {
        "total": len(donors),
        "status_counts": await status_counts(session, campaign_id),
        "missing": {
            "address_line1": sum(1 for d in donors if not d.address_line1),
            "email": sum(1 for d in donors if not d.email),
            "postal_code": sum(1 for d in donors if not d.postal_code),
            "state": sum(1 for d in donors if not d.state),
        },
        "postal_shapes": dict(Counter(postal_shape(d.postal_code) for d in donors).most_common()),
        "states": dict(states.most_common()),
        "do_not_contact": sum(1 for d in donors if d.do_not_contact),
        "in_unregistered_states": sum(1 for d in donors if (d.state or "").upper() in unregistered),
    }


async def find_duplicate_pairs(session: AsyncSession, campaign_id: uuid.UUID) -> list[dict]:
    """Probable duplicates *within* the campaign. a.id < b.id so each pair appears once."""
    a, b = aliased(Donor), aliased(Donor)
    ca, cb = aliased(CampaignDonor), aliased(CampaignDonor)
    name_sim = func.similarity(
        func.lower(a.first_name + " " + a.last_name), func.lower(b.first_name + " " + b.last_name)
    )
    addr_sim = func.similarity(
        func.lower(func.coalesce(a.address_line1, "")), func.lower(func.coalesce(b.address_line1, ""))
    )
    stmt = (
        select(a.external_id, b.external_id, name_sim, addr_sim)
        .select_from(ca)
        .join(a, a.id == ca.donor_id)
        .join(cb, cb.campaign_id == ca.campaign_id)
        .join(b, b.id == cb.donor_id)
        .where(
            ca.campaign_id == campaign_id,
            a.id < b.id,
            func.coalesce(a.address_line1, "") != "",
            func.coalesce(b.address_line1, "") != "",
            name_sim >= NAME_SIM_MIN,
            addr_sim >= ADDR_SIM_MIN,
            name_sim + addr_sim >= COMBINED_SIM_MIN,
        )
        .order_by((name_sim + addr_sim).desc())
        .limit(MAX_PAIRS)
    )
    rows = (await session.execute(stmt)).all()
    return [
        {"a": ea, "b": eb, "name_similarity": round(float(n), 3), "address_similarity": round(float(s), 3)}
        for ea, eb, n, s in rows
    ]


async def _latest_runs(session: AsyncSession, campaign_id: uuid.UUID):
    """Each campaign donor's most recent run (donors never run are absent)."""
    stmt = (
        select(WorkflowRun, Donor)
        .join(Donor, Donor.id == WorkflowRun.donor_id)
        .where(WorkflowRun.campaign_id == campaign_id)
        .distinct(WorkflowRun.donor_id)
        .order_by(WorkflowRun.donor_id, WorkflowRun.created_at.desc())
    )
    return (await session.execute(stmt)).all()


async def cluster_failures(session: AsyncSession, campaign_id: uuid.UUID) -> list[dict]:
    rows = [
        {
            "external_id": donor.external_id or str(donor.id),
            "reason": outcome_reason(run.status, run.result, run.pending_review, run.error),
            "state": donor.state,
            "postal_code": donor.postal_code,
        }
        for run, donor in await _latest_runs(session, campaign_id)
    ]
    return group_failures(rows)


async def list_donors_by_status(
    session: AsyncSession, campaign_id: uuid.UUID, status: str, limit: int = 50, offset: int = 0
) -> list[dict]:
    rows = (
        await session.execute(
            select(Donor, CampaignDonor.status_reason)
            .join(CampaignDonor, CampaignDonor.donor_id == Donor.id)
            .where(CampaignDonor.campaign_id == campaign_id, CampaignDonor.status == status)
            .order_by(Donor.external_id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [
        {
            "external_id": d.external_id,
            "name": f"{d.first_name} {d.last_name}",
            "state": d.state,
            "postal_code": d.postal_code,
            "status_reason": reason,
        }
        for d, reason in rows
    ]
