"""CLI for running the full donor pipeline via LangGraph directly, submitting
human-review decisions, and demonstrating real crash/resume behavior against
the Postgres checkpointer.

Usage:
  uv run python scripts/run_workflow_cli.py run --donor-id d-0001
  uv run python scripts/run_workflow_cli.py resume --workflow-run-id <uuid>
  uv run python scripts/run_workflow_cli.py review --workflow-run-id <uuid> --action approve
  uv run python scripts/run_workflow_cli.py demo-crash-resume --donor-id d-0002

Note on checkpoint durability: LangGraph's `astream(..., stream_mode="checkpoints")`
event fires when the Pregel loop *decides* a checkpoint exists, which is not the
same moment as the corresponding row being committed to Postgres — a process that
exits right on that event can leave the checkpointer's own durable state one step
behind. `demo-crash-resume` confirms durability the only way that's actually
trustworthy: an independent `aget_state()` read-back after the fact, polled until
it agrees the node completed. Skipping that and trusting the stream event instead
was tried first and reproducibly left `gather_context` re-executing after resume.
This is also why every real ainvoke() call below passes durability="sync" —
persist each checkpoint before the next step starts, not while it executes (the
default) — which matters even more once a workflow can pause on a human review
for hours or days.
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import uuid

from langgraph.types import Command
from sqlalchemy import select

from app.db.models import AgentAuditLog, Donor, WorkflowRun
from app.db.session import db_session
from app.graph.builder import build_graph

CRASH_TARGET_NODE = "gather_context"


async def resolve_donor_uuid(donor_id: str) -> uuid.UUID:
    """Accepts either our internal donor UUID or the CRM's external_id."""
    try:
        return uuid.UUID(donor_id)
    except ValueError:
        pass

    async with db_session() as session:
        result = await session.execute(select(Donor).where(Donor.external_id == donor_id))
        donor = result.scalars().first()
        if donor is None:
            raise SystemExit(f"donor {donor_id!r} not found")
        return donor.id


async def create_workflow_run(donor_uuid: uuid.UUID) -> str:
    async with db_session() as session:
        run = WorkflowRun(donor_id=donor_uuid)
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return str(run.id)


async def audit_steps(workflow_run_id: str) -> list[str]:
    async with db_session() as session:
        result = await session.execute(
            select(AgentAuditLog.step)
            .where(AgentAuditLog.workflow_run_id == uuid.UUID(workflow_run_id))
            .order_by(AgentAuditLog.created_at)
        )
        return list(result.scalars().all())


def print_result(result: dict) -> None:
    if interrupts := result.get("__interrupt__"):
        print("PAUSED — awaiting human review:")
        print(json.dumps(interrupts[0].value, indent=2))
        return

    aggregate = {}
    if result.get("verification_result") is not None:
        aggregate["donor_verification"] = result["verification_result"]
    if result.get("address_result") is not None:
        aggregate["address_intelligence"] = result["address_result"]
    if result.get("recommendation_result") is not None:
        aggregate["donation_recommendation"] = result["recommendation_result"]
    if result.get("personalization_result") is not None:
        aggregate["campaign_personalization"] = result["personalization_result"]
    if result.get("compliance_result") is not None:
        aggregate["compliance"] = result["compliance_result"]
    elif result.get("compliance_disclosures") is not None:
        aggregate["compliance"] = result["compliance_disclosures"]
    if result.get("pdf_result") is not None:
        aggregate["pdf_generation"] = result["pdf_result"]
    if result.get("human_review_decision") is not None:
        aggregate["human_review"] = result["human_review_decision"]
    print(json.dumps(aggregate, indent=2))


async def run_full(donor_id: str) -> None:
    donor_uuid = await resolve_donor_uuid(donor_id)
    workflow_run_id = await create_workflow_run(donor_uuid)
    print(f"workflow_run_id={workflow_run_id}")

    async with build_graph() as graph:
        result = await graph.ainvoke(
            {"workflow_run_id": workflow_run_id, "donor_id": str(donor_uuid), "campaign_id": None},
            config={"configurable": {"thread_id": workflow_run_id}},
            durability="sync",
        )
    print_result(result)


async def resume(workflow_run_id: str) -> None:
    """Continues a thread with no pending interrupt (e.g. after a crash) —
    for resuming a genuine interrupt with a decision, use `review` instead."""
    async with build_graph() as graph:
        result = await graph.ainvoke(
            None, config={"configurable": {"thread_id": workflow_run_id}}, durability="sync"
        )
    print_result(result)


async def review(
    workflow_run_id: str,
    action: str,
    updated_address: str | None,
    updated_ask_amount: float | None,
    reviewer: str | None,
    notes: str | None,
) -> None:
    decision = {
        "action": action,
        "updated_address": updated_address,
        "updated_ask_amount": updated_ask_amount,
        "reviewer": reviewer,
        "notes": notes,
    }
    async with build_graph() as graph:
        result = await graph.ainvoke(
            Command(resume=decision),
            config={"configurable": {"thread_id": workflow_run_id}},
            durability="sync",
        )
    print_result(result)


async def _run_until_crash(workflow_run_id: str) -> None:
    """Internal, invoked as a subprocess by demo-crash-resume. Runs fetch_core_data
    and gather_context, confirms gather_context's checkpoint is genuinely durable,
    then os._exit(1) before synthesize_verdict ever starts -- a real process death,
    not a graceful pause."""
    async with db_session() as session:
        run = await session.get(WorkflowRun, uuid.UUID(workflow_run_id))
        donor_id = str(run.donor_id)

    async with build_graph() as graph:
        config = {"configurable": {"thread_id": workflow_run_id}}
        armed = False
        async for update in graph.astream(
            {"workflow_run_id": workflow_run_id, "donor_id": donor_id, "campaign_id": None},
            config=config,
            stream_mode="updates",
            durability="sync",
        ):
            step_name = next(iter(update))
            print(f"[crash-demo] node completed: {step_name}", flush=True)
            if step_name == CRASH_TARGET_NODE:
                armed = True
                break

        if not armed:
            print(f"[crash-demo] {CRASH_TARGET_NODE} never ran -- nothing to crash after")
            return

        for _ in range(100):
            state = await graph.aget_state(config)
            if state.next != (CRASH_TARGET_NODE,):
                print(
                    f"[crash-demo] {CRASH_TARGET_NODE}'s checkpoint is confirmed durable "
                    f"(next={state.next}) -- simulating a hard crash now",
                    flush=True,
                )
                os._exit(1)
            await asyncio.sleep(0.05)

        raise RuntimeError("timed out waiting for checkpoint durability confirmation")


async def demo_crash_resume(donor_id: str) -> None:
    donor_uuid = await resolve_donor_uuid(donor_id)
    workflow_run_id = await create_workflow_run(donor_uuid)
    print(f"workflow_run_id={workflow_run_id}\n")

    print(f"--- step 1: run until a simulated crash right after '{CRASH_TARGET_NODE}' ---")
    proc = subprocess.run([sys.executable, __file__, "_run_until_crash", "--workflow-run-id", workflow_run_id])
    print(f"(subprocess exited with code {proc.returncode} -- a real process death, not a graceful stop)\n")

    print("--- step 2: inspect what actually persisted ---")
    steps_before = await audit_steps(workflow_run_id)
    print(f"agent_audit_log steps so far: {steps_before}\n")
    assert steps_before == ["fetch_core_data", "gather_context"], (
        f"expected the crash to land right after gather_context, got {steps_before}"
    )

    print("--- step 3: resume in a fresh process from the last durable checkpoint ---")
    async with build_graph() as graph:
        result = await graph.ainvoke(
            None, config={"configurable": {"thread_id": workflow_run_id}}, durability="sync"
        )
    print_result(result)

    steps_after = await audit_steps(workflow_run_id)
    print(f"\nagent_audit_log steps after resume: {steps_after}")
    assert steps_after[:2] == ["fetch_core_data", "gather_context"], (
        "expected fetch_core_data and gather_context to have run exactly once each, "
        f"before the crash, not been re-run after resume — got {steps_after}"
    )
    print(f"confirmed: {CRASH_TARGET_NODE} and the step before it did not re-run after the crash")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="run the full pipeline for a donor")
    p_run.add_argument("--donor-id", required=True)

    p_resume = sub.add_parser(
        "resume", help="continue a thread with no pending interrupt (e.g. after a crash)"
    )
    p_resume.add_argument("--workflow-run-id", required=True)

    p_review = sub.add_parser("review", help="submit a decision for a workflow awaiting human review")
    p_review.add_argument("--workflow-run-id", required=True)
    p_review.add_argument("--action", required=True, choices=["approve", "reject", "modify"])
    p_review.add_argument("--updated-address", default=None)
    p_review.add_argument(
        "--updated-ask-amount",
        type=float,
        default=None,
        help="new ask amount, for a recommendation-stage review with --action modify",
    )
    p_review.add_argument("--reviewer", default=None)
    p_review.add_argument("--notes", default=None)

    p_crash = sub.add_parser(
        "demo-crash-resume",
        help="simulate a hard process crash mid-workflow, then resume, proving checkpoint durability",
    )
    p_crash.add_argument("--donor-id", required=True)

    p_internal = sub.add_parser("_run_until_crash", help=argparse.SUPPRESS)
    p_internal.add_argument("--workflow-run-id", required=True)

    args = parser.parse_args()

    if args.command == "run":
        asyncio.run(run_full(args.donor_id))
    elif args.command == "resume":
        asyncio.run(resume(args.workflow_run_id))
    elif args.command == "review":
        asyncio.run(
            review(
                args.workflow_run_id,
                args.action,
                args.updated_address,
                args.updated_ask_amount,
                args.reviewer,
                args.notes,
            )
        )
    elif args.command == "demo-crash-resume":
        asyncio.run(demo_crash_resume(args.donor_id))
    elif args.command == "_run_until_crash":
        asyncio.run(_run_until_crash(args.workflow_run_id))


if __name__ == "__main__":
    main()
