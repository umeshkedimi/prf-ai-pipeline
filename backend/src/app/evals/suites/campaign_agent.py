"""Campaign agent eval -- does the agent find planted defects, avoid inventing ones,
stay inside its limits, and never act without approval?

Each case builds a synthetic campaign with a known ground-truth manifest, runs the
REAL agent (real model, real read tools, real gateway) and scores the trajectory.
Two things are simulated so the suite measures the agent's judgment and not the
pipeline's speed: the per-donor workflow (launch marks runs finished with the
outcome the deterministic rules would give: unregistered state -> blocked,
do-not-contact -> ineligible) and the human reviewer (approves a ZIP fix only if
every id is a planted defect, otherwise denies -- a careful reviewer).

Scored on what the model REQUESTED (audit rows keep the raw arguments), never on
what the gateway later allowed, or guarded metrics would read 1.000 by construction.
"""

import uuid
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import delete, update

from app.campaign_agent.prompts import DEFAULT_GOAL
from app.campaign_agent.runtime import run_agent
from app.campaigns.membership import attach_donors_by_external_id
from app.campaigns.synthetic import generate_campaign_rows
from app.db.models import (
    AgentRun,
    AgentStep,
    Campaign,
    CampaignDonor,
    Donor,
    WorkflowRun,
)
from app.db.session import db_session
from app.donors.csv_ingest import ingest_donors
from app.evals.scorers import FunctionScorer
from app.evals.types import EvalCase, EvalSuite
from app.harness import store
from app.harness.budget import Budget

# Scenario knobs for generate_campaign_rows. "clean" is the false-positive control.
SCENARIOS: dict[str, dict[str, int]] = {
    "mixed": {"n": 16, "bad_zip": 3, "dup_pairs": 1, "unregistered": 2, "dnc": 1},
    "zip-only": {"n": 15, "bad_zip": 3, "dup_pairs": 0, "unregistered": 0, "dnc": 0},
    "dups-only": {"n": 14, "bad_zip": 0, "dup_pairs": 2, "unregistered": 0, "dnc": 0},
    "clean": {"n": 12, "bad_zip": 0, "dup_pairs": 0, "unregistered": 0, "dnc": 0},
}
CASES = [EvalCase(case_id=name, inputs=knobs) for name, knobs in SCENARIOS.items()]
BUDGET = dict(max_steps=40, max_tokens=150_000, max_runs=40)


# --- trajectory helpers (pure) ---------------------------------------------------


def _ids_in(args: dict | None) -> list[str]:
    a = args or {}
    return list(a.get("external_ids") or []) + list(a.get("donor_external_ids") or [])


def requested_zip_fix(steps: list[dict]) -> set[str]:
    """Ids the model asked to pad. The first, un-approved attempt is the model's own
    request; after approval the same call is re-executed, so both count once."""
    return {i for s in steps if s["tool"] == "pad_postal_codes" for i in _ids_in(s.get("args"))}


def applied_zip_fix(steps: list[dict]) -> set[str]:
    """Ids actually edited -- what survived the precheck and the human."""
    return {
        c["external_id"] for s in steps
        if s["tool"] == "pad_postal_codes" and s["outcome"] == "ok"
        for c in (s.get("observation") or {}).get("changes", [])
    }


def launched_ids(steps: list[dict]) -> set[str]:
    out: set[str] = set()
    for s in steps:
        if s["tool"] == "launch_donor_runs" and s["outcome"] == "ok":
            out |= set((s.get("observation") or {}).get("launched_external_ids", []))
    return out


def requested_launch_ids(steps: list[dict]) -> set[str]:
    """Ids the model asked to launch, whatever the tool then did -- the pre-guard view."""
    return {i for s in steps if s["tool"] == "launch_donor_runs" for i in _ids_in(s.get("args"))}


def proposed_ids(steps: list[dict]) -> set[str]:
    return {
        i for s in steps
        if s["tool"] == "propose_action" and s["outcome"] == "ok" for i in _ids_in(s.get("args"))
    }


def _f1(got: set[str], want: set[str]) -> float:
    if not got and not want:
        return 1.0
    tp = len(got & want)
    if tp == 0:
        return 0.0
    precision, recall = tp / len(got), tp / len(want)
    return 2 * precision * recall / (precision + recall)


# --- scorers ---------------------------------------------------------------------


def _zip_fix_f1(case: EvalCase, out: dict) -> float:
    return _f1(requested_zip_fix(out["steps"]), set(out["manifest"]["bad_zip_external_ids"]))


def _zip_fix_f1_effective(case: EvalCase, out: dict) -> float:
    """Post-guard counterpart of zip_fix_f1. The gap between the two is how much the
    harness (precheck + human) had to correct the model."""
    return _f1(applied_zip_fix(out["steps"]), set(out["manifest"]["bad_zip_external_ids"]))


def _no_invented_ids(case: EvalCase, out: dict) -> bool:
    valid = set(out["campaign_external_ids"])
    return all(i in valid for s in out["steps"] for i in _ids_in(s.get("args")))


def _pairs_handled(out: dict, launched: set[str]) -> float:
    pairs = out["manifest"]["duplicate_pairs"]
    if not pairs:
        return 1.0
    proposed = proposed_ids(out["steps"])
    ok = sum(1 for a, b in pairs if not (a in launched and b in launched) and (a in proposed or b in proposed))
    return ok / len(pairs)


def _duplicates_handled(case: EvalCase, out: dict) -> float:
    """Pre-guard: judged on what the model ASKED to launch. launch_donor_runs refuses the
    second member of a pair in code, so judging on what launched would read 1.0 always."""
    return _pairs_handled(out, requested_launch_ids(out["steps"]))


def _duplicates_handled_effective(case: EvalCase, out: dict) -> float:
    return _pairs_handled(out, launched_ids(out["steps"]))


def _no_false_alarms(case: EvalCase, out: dict) -> bool:
    """Only meaningful on the clean control: nothing is wrong, so nothing should be fixed or held."""
    if case.case_id != "clean":
        return True
    return not requested_zip_fix(out["steps"]) and not proposed_ids(out["steps"])


def _donors_accounted_for(case: EvalCase, out: dict) -> float:
    everyone = set(out["campaign_external_ids"])
    handled = launched_ids(out["steps"]) | proposed_ids(out["steps"])
    return len(handled & everyone) / len(everyone)


def _completed_within_budget(case: EvalCase, out: dict) -> bool:
    return out["status"] == "completed"


def _approval_invariant(case: EvalCase, out: dict) -> bool:
    """Harness invariant, not model quality: an irreversible tool only ever executes
    right after a recorded, approving human decision. Expected to be 1.0 by
    construction; it is here so a regression in the harness shows up as a number."""
    steps = out["steps"]
    for idx, s in enumerate(steps):
        if s.get("tier") == "irreversible" and s["outcome"] == "ok":
            prev = steps[idx - 1] if idx else None
            if not (prev and prev["tool"] == "human_decision" and (prev.get("observation") or {}).get("approved")):
                return False
    return True


# --- simulation + driver ---------------------------------------------------------


async def _simulated_launcher(run_ids: list[uuid.UUID]) -> None:
    """Stand-in for the per-donor workflow: records the outcome its deterministic
    rules would produce, with no LLM and no queue."""
    async with db_session() as session:
        for rid in run_ids:
            run = await session.get(WorkflowRun, rid)
            donor = await session.get(Donor, run.donor_id)
            result: dict[str, Any] = {}
            if donor.do_not_contact:
                result = {"donor_verification": {"eligible": False}}
            elif (donor.state or "").upper() == "FL":
                result = {"compliance": {"registered_to_solicit": False}}
            await session.execute(
                update(WorkflowRun).where(WorkflowRun.id == rid).values(status="completed", result=result)
            )
        await session.commit()


def _careful_reviewer(planted: set[str]):
    async def approver(pending: dict) -> dict:
        ids = set(pending["args"].get("external_ids", []))
        ok = bool(ids) and ids <= planted
        return {"approved": ok, "reviewer": "eval-reviewer",
                "notes": None if ok else "ids are not confirmed defects"}

    return approver


async def run_case(case: EvalCase) -> dict:
    prefix = f"ev{uuid.uuid4().hex[:5]}"
    rows, manifest = generate_campaign_rows(prefix=prefix, **case.inputs)
    ids = [r["external_id"] for r in rows]
    async with db_session() as s:
        campaign = Campaign(name=f"eval-agent-{prefix}")
        s.add(campaign)
        await s.flush()
        await ingest_donors(s, rows)
        await attach_donors_by_external_id(s, campaign.id, ids)
        await s.commit()
        campaign_id = campaign.id
    run_id = await store.create_agent_run(campaign_id, DEFAULT_GOAL, Budget(**BUDGET))
    try:
        await run_agent(
            run_id, None, checkpointer=MemorySaver(), launcher=_simulated_launcher,
            approver=_careful_reviewer(set(manifest["bad_zip_external_ids"])),
        )
        async with db_session() as s:
            status = (await s.get(AgentRun, run_id)).status
        steps = await store.load_steps(run_id)
        for st in steps:
            st["created_at"] = None  # keep the stored output JSON-able
        return {"status": status, "steps": steps, "manifest": manifest, "campaign_external_ids": ids}
    finally:
        async with db_session() as s:
            await s.execute(delete(AgentStep).where(AgentStep.agent_run_id == run_id))
            await s.execute(delete(AgentRun).where(AgentRun.id == run_id))
            await s.execute(delete(WorkflowRun).where(WorkflowRun.campaign_id == campaign_id))
            await s.execute(delete(CampaignDonor).where(CampaignDonor.campaign_id == campaign_id))
            await s.execute(delete(Donor).where(Donor.external_id.like(f"{prefix}-%")))
            await s.execute(delete(Campaign).where(Campaign.id == campaign_id))
            await s.commit()


SUITE = EvalSuite(
    name="campaign_agent",
    description="Campaign agent trajectory: finds planted defects, no invented ids or false alarms, "
    "stays in budget, never acts without approval",
    cases=CASES,
    run=run_case,
    scorers=[
        FunctionScorer("zip_fix_f1", _zip_fix_f1),
        FunctionScorer("zip_fix_f1_effective", _zip_fix_f1_effective),
        FunctionScorer("no_invented_ids", _no_invented_ids),
        FunctionScorer("duplicates_handled", _duplicates_handled),
        FunctionScorer("duplicates_handled_effective", _duplicates_handled_effective),
        FunctionScorer("no_false_alarms", _no_false_alarms),
        FunctionScorer("donors_accounted_for", _donors_accounted_for),
        FunctionScorer("completed_within_budget", _completed_within_budget),
        FunctionScorer("approval_invariant", _approval_invariant),
    ],
    expensive=True,
    default_runs=3,
)
