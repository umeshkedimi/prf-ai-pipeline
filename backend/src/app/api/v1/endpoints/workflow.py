import uuid
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import write_audit_log
from app.core.config import get_settings
from app.workers.release_claims import build_claim, claim_release, reclaim_stale_release
from app.api.deps import get_db
from app.api.deps_auth import get_current_user
from app.db.models import AgentAuditLog, Campaign, Donor, User, WorkflowRun
from app.schemas.donors import WorkflowRunBatchCreate, WorkflowRunBatchItem
from app.schemas.workflow import (
    AuditLogEntry,
    HeldLetterDecision,
    ReviewDecisionCreate,
    ReviewHistoryEntry,
    WorkflowRunCreate,
    WorkflowRunRead,
    WorkflowRunSummary,
)

from app.workers.tasks import release_held_letter, resume_workflow_after_review
from app.workers.tasks import run_workflow as run_workflow_task

RunStatus = Literal[
    "pending", "running", "awaiting_review", "completed", "needs_review", "failed", "discarded"
]

router = APIRouter()


async def _resolve_donor_id(session: AsyncSession, donor_id: str) -> uuid.UUID:
    """Accepts either our internal donor UUID or the CRM's external_id."""
    try:
        candidate = uuid.UUID(donor_id)
    except ValueError:
        candidate = None
    else:
        donor = await session.get(Donor, candidate)
        if donor is not None:
            return donor.id

    result = await session.execute(select(Donor).where(Donor.external_id == donor_id))
    donor = result.scalars().first()
    if donor is None:
        raise HTTPException(status_code=404, detail=f"donor {donor_id!r} not found")
    return donor.id


async def _list_run_summaries(
    session: AsyncSession,
    *,
    statuses: list[str] | None,
    limit: int,
    offset: int,
    newest_first: bool,
) -> list[WorkflowRunSummary]:
    """Shared by GET /workflow/reviews (oldest-first, so a FIFO queue triages
    correctly) and GET /workflow/runs (newest-first, the natural default for
    a history browser). statuses=None means no filter at all."""
    stmt = (
        select(WorkflowRun, Donor, Campaign)
        .join(Donor, WorkflowRun.donor_id == Donor.id)
        .outerjoin(Campaign, WorkflowRun.campaign_id == Campaign.id)
    )
    if statuses:
        stmt = stmt.where(WorkflowRun.status.in_(statuses))
    order_col = WorkflowRun.created_at.desc() if newest_first else WorkflowRun.created_at.asc()
    stmt = stmt.order_by(order_col).limit(limit).offset(offset)

    result = await session.execute(stmt)
    return [
        WorkflowRunSummary(
            id=run.id,
            donor_id=run.donor_id,
            donor_name=f"{donor.first_name} {donor.last_name}",
            donor_external_id=donor.external_id,
            campaign_id=run.campaign_id,
            campaign_name=campaign.name if campaign else None,
            status=run.status,
            current_agent=run.current_agent,
            confidence=run.confidence,
            pending_review=run.pending_review,
            created_at=run.created_at,
        )
        for run, donor, campaign in result.all()
    ]


@router.post("/workflow/run", response_model=WorkflowRunRead, status_code=202)
async def run_workflow(
    payload: WorkflowRunCreate,
    session: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> WorkflowRun:
    """Enqueues the pipeline and returns immediately — the API never invokes
    the LangGraph graph itself, Celery does (see workers/tasks.py). Poll
    GET /workflow/{id} for status."""
    donor_uuid = await _resolve_donor_id(session, payload.donor_id)
    campaign_uuid = uuid.UUID(payload.campaign_id) if payload.campaign_id else None

    run = WorkflowRun(donor_id=donor_uuid, campaign_id=campaign_uuid)
    session.add(run)
    await session.commit()
    await session.refresh(run)

    run_workflow_task.delay(str(run.id))
    return run


@router.post("/workflow/run/batch", response_model=list[WorkflowRunBatchItem], status_code=202)
async def run_workflow_batch(
    payload: WorkflowRunBatchCreate,
    session: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[WorkflowRunBatchItem]:
    """Triggers one run per donor_id -- the explicit action that turns a
    staged (CSV-ingested or otherwise never-run) donor into a real run. Reuses
    the exact same per-donor path as POST /workflow/run in a loop, so a bad
    donor_id in the batch is reported per-item rather than sinking the rest."""
    campaign_uuid = uuid.UUID(payload.campaign_id) if payload.campaign_id else None
    results: list[WorkflowRunBatchItem] = []

    for donor_id in payload.donor_ids:
        try:
            donor_uuid = await _resolve_donor_id(session, donor_id)
        except HTTPException as exc:
            results.append(WorkflowRunBatchItem(donor_id=donor_id, status="error", error=str(exc.detail)))
            continue

        run = WorkflowRun(donor_id=donor_uuid, campaign_id=campaign_uuid)
        session.add(run)
        await session.commit()
        await session.refresh(run)
        run_workflow_task.delay(str(run.id))
        results.append(WorkflowRunBatchItem(donor_id=donor_id, status="enqueued", workflow_run_id=run.id))

    return results


@router.get("/workflow/reviews", response_model=list[WorkflowRunSummary])
async def list_reviews(
    status: Literal["awaiting_review", "needs_review"] | None = Query(
        None, description="Restrict to one queue; omit for both"
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[WorkflowRunSummary]:
    """Everything a human has reason to look at: `awaiting_review` runs are
    genuinely paused on a LangGraph interrupt() and block on a decision;
    `needs_review` runs already reached END but flagged a low-confidence or
    disapproved outcome for an eventual glance. Declared ahead of
    GET /workflow/{workflow_run_id} so "reviews" doesn't get routed there and
    fail UUID conversion. Oldest-first — a queue triages FIFO."""
    statuses = [status] if status else ["awaiting_review", "needs_review"]
    return await _list_run_summaries(session, statuses=statuses, limit=limit, offset=offset, newest_first=False)


@router.get("/workflow/runs", response_model=list[WorkflowRunSummary])
async def list_runs(
    status: RunStatus | None = Query(None, description="Restrict to one status; omit for all"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[WorkflowRunSummary]:
    """The full run history, any status — unlike /workflow/reviews (which is
    scoped to what a human needs to act on), this is a general browser, e.g.
    for finding a `completed` run without knowing its id ahead of time.
    Declared ahead of GET /workflow/{workflow_run_id} for the same UUID-path
    reason /workflow/reviews already is. Newest-first, the natural default
    for a history view."""
    statuses = [status] if status else None
    return await _list_run_summaries(session, statuses=statuses, limit=limit, offset=offset, newest_first=True)


@router.get("/workflow/{workflow_run_id}", response_model=WorkflowRunRead)
async def get_workflow(
    workflow_run_id: uuid.UUID,
    verbose: bool = Query(False, description="Include the full per-agent audit trail"),
    session: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> WorkflowRunRead:
    run = await session.get(WorkflowRun, workflow_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="workflow run not found")

    response = WorkflowRunRead.model_validate(run)
    donor = await session.get(Donor, run.donor_id)
    response.donor_external_id = donor.external_id if donor else None
    review_rows = (
        (
            await session.execute(
                select(AgentAuditLog)
                .where(
                    AgentAuditLog.workflow_run_id == workflow_run_id,
                    AgentAuditLog.agent_name == "human_review",
                )
                .order_by(AgentAuditLog.created_at)
            )
        )
        .scalars()
        .all()
    )
    response.review_history = [ReviewHistoryEntry.from_audit_row(row) for row in review_rows]
    if verbose:
        rows = (
            (
                await session.execute(
                    select(AgentAuditLog)
                    .where(AgentAuditLog.workflow_run_id == workflow_run_id)
                    .order_by(AgentAuditLog.created_at)
                )
            )
            .scalars()
            .all()
        )
        response.audit_log = [AuditLogEntry.model_validate(row) for row in rows]
    return response


@router.post("/workflow/{workflow_run_id}/review", response_model=WorkflowRunRead, status_code=202)
async def submit_review(
    workflow_run_id: uuid.UUID,
    payload: ReviewDecisionCreate,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkflowRun:
    """Submits a human decision for a workflow paused on a real LangGraph
    interrupt() and re-enqueues it to resume from exactly where it stopped.

    The run is claimed with one conditional UPDATE (`awaiting_review` ->
    `running`) that also requires the decision's `stage` to match the stage the
    run is paused at. Two reviewers acting on the same pause therefore cannot
    both win: the loser matches no row and gets a 409. Without the claim both
    would be enqueued, and the second resume would be consumed by whichever
    interrupt the graph reached *next* — applying a decision to the wrong stage."""
    claimed = await session.execute(
        update(WorkflowRun)
        .where(
            WorkflowRun.id == workflow_run_id,
            WorkflowRun.status == "awaiting_review",
            WorkflowRun.pending_review["stage"].astext == payload.stage,
        )
        .values(status="running")
        .returning(WorkflowRun.id)
    )
    if claimed.scalar_one_or_none() is None:
        await session.rollback()
        run = await session.get(WorkflowRun, workflow_run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="workflow run not found")
        if run.status != "awaiting_review":
            raise HTTPException(
                status_code=409,
                detail=(
                    f"workflow run is '{run.status}', not awaiting_review — nothing to resume "
                    "(another reviewer may already have decided)"
                ),
            )
        paused_at = (run.pending_review or {}).get("stage")
        raise HTTPException(
            status_code=409,
            detail=f"workflow run is paused at stage '{paused_at}', but the decision was for '{payload.stage}'",
        )
    await session.commit()

    # reviewer is set from the authenticated session, not the request body --
    # the field still exists on ReviewDecisionCreate for API-shape parity with
    # HumanReviewDecision (see that schema's docstring), but any client-supplied
    # value is overwritten here so the audit trail can't be spoofed.
    decision = payload.model_dump()
    decision["reviewer"] = user.email
    try:
        resume_workflow_after_review.delay(str(workflow_run_id), decision)
    except Exception:
        # Broker down: give the pause back rather than strand the run in `running`.
        await session.execute(
            update(WorkflowRun)
            .where(WorkflowRun.id == workflow_run_id, WorkflowRun.status == "running")
            .values(status="awaiting_review")
        )
        await session.commit()
        raise HTTPException(status_code=503, detail="could not enqueue the decision; try again")

    run = await session.get(WorkflowRun, workflow_run_id)
    await session.refresh(run)
    return run


@router.post("/workflow/{workflow_run_id}/release", response_model=WorkflowRunRead, status_code=202)
async def release_held(
    workflow_run_id: uuid.UUID,
    payload: HeldLetterDecision,
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkflowRun:
    """A human decision on a letter held back from print because Compliance
    disapproved it. Not /review: that endpoint resumes a graph paused on an
    interrupt(), whereas this run already reached END — there is nothing to
    resume, only one irreversible side effect (the vendor order) to allow or
    forbid.

    The run is claimed with a single conditional UPDATE, so two concurrent
    requests cannot both win — the loser matches zero rows and gets a 409,
    and no second order is placed. A release whose claim has gone stale
    (worker or API died mid-release) is retried by calling this again: the
    stale claim is taken over by compare-and-swap, and re-running is safe
    because the order is keyed on the run's deterministic reference."""
    # reviewer comes from the session, never the body (same rule as /review).
    decision = {"action": payload.action, "notes": payload.notes, "reviewer": user.email}

    if payload.action == "release":
        claim = build_claim(decision)
        claimed = await claim_release(session, workflow_run_id, claim) or (
            await reclaim_stale_release(session, workflow_run_id, claim)
        )
    else:
        discarded = await session.execute(
            update(WorkflowRun)
            .where(
                WorkflowRun.id == workflow_run_id,
                WorkflowRun.status == "needs_review",
                WorkflowRun.result["pdf_generation"]["held"].astext == "true",
            )
            .values(status="discarded")
            .returning(WorkflowRun.id)
        )
        claimed = discarded.scalar_one_or_none() is not None
    if not claimed:
        await session.rollback()
        run = await session.get(WorkflowRun, workflow_run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="workflow run not found")
        if run.status == "running":
            raise HTTPException(
                status_code=409,
                detail=(
                    "a release is already in progress; it can be retried if it is still "
                    f"running after {get_settings().release_claim_ttl_seconds}s"
                ),
            )
        raise HTTPException(
            status_code=409,
            detail=f"workflow run is '{run.status}' and has no held letter to decide on",
        )
    await session.commit()

    if payload.action == "release":
        try:
            release_held_letter.delay(str(workflow_run_id), decision)
        except Exception:
            # Broker down: undo the claim rather than strand the run in `running`.
            await session.execute(
                update(WorkflowRun).where(WorkflowRun.id == workflow_run_id).values(status="needs_review")
            )
            await session.commit()
            raise HTTPException(status_code=503, detail="could not enqueue the release; try again")
    else:
        run = await session.get(WorkflowRun, workflow_run_id)
        pdf_result = {**run.result["pdf_generation"], "discarded_by": user.email}
        run.result = {**run.result, "pdf_generation": pdf_result}
        run.current_agent = "human_review"
        run.completed_at = datetime.now(UTC)
        await session.commit()
        await write_audit_log(
            workflow_run_id=str(workflow_run_id),
            agent_name="human_review",
            step="discard_held_letter",
            input_snapshot={"hold_reason": pdf_result.get("hold_reason")},
            output=pdf_result,
            reasoning=payload.notes,
            source_refs=[{"reviewer": user.email, "action": "discard", "stage": "print_release"}],
        )

    run = await session.get(WorkflowRun, workflow_run_id)
    await session.refresh(run)
    return run


@router.get("/workflow/{workflow_run_id}/pdf")
async def get_workflow_pdf(
    workflow_run_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> FileResponse:
    """Serves the generated letter. generate_pdf writes to disk (see
    render.py's LETTER_STORAGE_DIR) and only records the path in
    pdf_result — there was previously no way to retrieve the file itself
    over HTTP, so a dashboard had nowhere to link to."""
    run = await session.get(WorkflowRun, workflow_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="workflow run not found")
    pdf_result = (run.result or {}).get("pdf_generation")
    if pdf_result is None:
        raise HTTPException(status_code=404, detail="no PDF generated for this run")
    pdf_path = Path(pdf_result["pdf_path"])
    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found on disk")
    return FileResponse(pdf_path, media_type="application/pdf", filename=f"{workflow_run_id}.pdf")
