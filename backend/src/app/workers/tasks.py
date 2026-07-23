import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from langgraph.types import Command

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.base import reset_engine
from app.db.models import WorkflowRun
from app.db.session import db_session
from app.graph.builder import build_graph
from app.workers.celery_app import celery_app

log = get_logger(__name__)


@celery_app.task(name="run_workflow")
def run_workflow(workflow_run_id: str) -> None:
    """Sync Celery entrypoint (default prefork pool) bridging into the async
    graph. Each call gets a fresh event loop via asyncio.run(), so the cached
    DB engine must be reset around it — see db/base.py:reset_engine()."""
    asyncio.run(_run(workflow_run_id, resume_command=None))


@celery_app.task(name="resume_workflow_after_review")
def resume_workflow_after_review(workflow_run_id: str, decision: dict) -> None:
    asyncio.run(_run(workflow_run_id, resume_command=Command(resume=decision)))


async def _run(workflow_run_id: str, resume_command: Command | None) -> None:
    await reset_engine()
    try:
        run_uuid = uuid.UUID(workflow_run_id)

        async with db_session() as session:
            run = await session.get(WorkflowRun, run_uuid)
            if run is None:
                log.warning("workflow_run.not_found", workflow_run_id=workflow_run_id)
                return
            run.status = "running"
            run.started_at = run.started_at or datetime.now(UTC)
            run.pending_review = None
            await session.commit()
            donor_id = str(run.donor_id)
            campaign_id = str(run.campaign_id) if run.campaign_id else None

        log.info(
            "workflow_run.started",
            workflow_run_id=workflow_run_id,
            donor_id=donor_id,
            resuming=resume_command is not None,
        )

        try:
            graph_input: Any = (
                resume_command
                if resume_command is not None
                else {
                    "workflow_run_id": workflow_run_id,
                    "donor_id": donor_id,
                    "campaign_id": campaign_id,
                }
            )
            async with build_graph() as graph:
                # durability="sync" persists each checkpoint before the next
                # step starts, not while it executes (the default). Matters
                # far more here than in a single-agent graph: an interrupted
                # workflow's paused state might not resume for hours or days
                # and absolutely cannot be lost.
                result = await graph.ainvoke(
                    graph_input,
                    config={"configurable": {"thread_id": workflow_run_id}},
                    durability="sync",
                )

            await _handle_result(run_uuid, workflow_run_id, result)

        except Exception as exc:
            async with db_session() as session:
                run = await session.get(WorkflowRun, run_uuid)
                run.status = "failed"
                run.error = str(exc)
                run.completed_at = datetime.now(UTC)
                await session.commit()
            log.error("workflow_run.failed", workflow_run_id=workflow_run_id, error=str(exc))
            raise
    finally:
        await reset_engine()


async def _handle_result(run_uuid: uuid.UUID, workflow_run_id: str, result: dict) -> None:
    """Interprets the graph's output and updates workflow_runs. Shared by the
    initial run and the post-review resume, since both end up here via the
    same ainvoke() call in _run()."""
    settings = get_settings()

    if interrupts := result.get("__interrupt__"):
        payload = interrupts[0].value
        async with db_session() as session:
            run = await session.get(WorkflowRun, run_uuid)
            run.status = "awaiting_review"
            run.current_agent = "human_review"
            run.pending_review = payload
            await session.commit()
        log.info("workflow_run.awaiting_review", workflow_run_id=workflow_run_id)
        return

    aggregate: dict[str, Any] = {}
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

    status, confidence, current_agent = _derive_terminal_status(result, settings)

    async with db_session() as session:
        run = await session.get(WorkflowRun, run_uuid)
        run.status = status
        run.current_agent = current_agent
        run.result = aggregate
        run.confidence = confidence
        run.completed_at = datetime.now(UTC)
        await session.commit()

    log.info(
        "workflow_run.finished",
        workflow_run_id=workflow_run_id,
        status=status,
        confidence=confidence,
    )


def _derive_terminal_status(result: dict, settings) -> tuple[str, float | None, str]:
    """Status/confidence are driven by the *terminal* stage this run reached, not
    by whether any human decision happened along the way — an address-stage
    review is no longer terminal now that recommendation runs after it. A
    result carries `human_reviewed=True` when a human authoritatively signed
    off on that specific stage (no further confidence gating applies to it)."""
    pdf = result.get("pdf_result")
    comp = result.get("compliance_result")
    comp_disclosures = result.get("compliance_disclosures")
    pers = result.get("personalization_result")
    rec = result.get("recommendation_result")
    addr = result.get("address_result")
    if pdf is not None:
        # generate_pdf itself is deterministic — no LLM assessment of the PDF,
        # so no confidence of its own. But it runs even when the upstream
        # compliance review disapproved the letter (advisory, not blocking —
        # see route_after_disclosures for the one gate that actually is
        # blocking), so a disapproved letter that still got mailed needs to
        # surface in the review queue rather than read as unremarkable.
        if comp is not None and comp.get("approved") is False:
            confidence = comp.get("confidence")
            status = "needs_review"
        else:
            confidence = None
            status = "completed"
        current_agent = "pdf_generation"
    elif comp is not None:
        # review_letter_compliance ran: a genuine LLM risk assessment exists,
        # advisory only (needs_review), same role as personalization's gate.
        confidence = comp.get("confidence")
        status = (
            "completed"
            if confidence >= settings.confidence_threshold_compliance
            else "needs_review"
        )
        current_agent = "compliance"
    elif comp_disclosures is not None:
        # Blocked on state solicitation registration before any letter-content
        # review ran (route_after_disclosures). No LLM assessment exists for
        # this run, so there's no confidence to report; by the time this
        # branch is reached the interrupt above has already been resolved.
        confidence = None
        status = "completed"
        current_agent = "human_review"
    elif pers is not None:
        # personalize_letter has no interrupt of its own — low confidence here
        # is advisory only, exactly like the stages below.
        confidence = pers.get("confidence")
        status = (
            "completed"
            if confidence >= settings.confidence_threshold_campaign_personalization
            else "needs_review"
        )
        current_agent = "campaign_personalization"
    elif rec is not None:
        confidence = rec.get("confidence")
        if rec.get("human_reviewed"):
            status = "completed"
            current_agent = "human_review"
        else:
            # The ask cleared the major-gift gate (that's the only blocking
            # trigger — see route_after_recommendation). Low confidence here is
            # advisory: flag it for a human's eventual glance without stalling
            # the run, exactly as Donor Verification's flags behave.
            status = (
                "completed"
                if confidence >= settings.confidence_threshold_donation_recommendation
                else "needs_review"
            )
            current_agent = "donation_recommendation"
    elif addr is not None:
        # Address is terminal only when we won't mail (undeliverable/rejected).
        confidence = addr.get("confidence")
        if addr.get("human_reviewed"):
            status = "completed"
            current_agent = "human_review"
        else:
            status = "completed" if confidence >= settings.confidence_threshold_address_intelligence else "needs_review"
            current_agent = "address_intelligence"
    else:
        vr = result["verification_result"]
        confidence = vr["confidence"]
        status = "completed" if confidence >= settings.confidence_threshold_donor_verification else "needs_review"
        current_agent = "donor_verification"

    return status, confidence, current_agent
