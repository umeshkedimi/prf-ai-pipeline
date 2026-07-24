import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.models import AgentAuditLog, Campaign, Donor, WorkflowRun
from app.schemas.workflow import (
    AuditLogEntry,
    ReviewDecisionCreate,
    ReviewHistoryEntry,
    WorkflowRunCreate,
    WorkflowRunRead,
    WorkflowReviewSummary,
)
from app.workers.tasks import resume_workflow_after_review
from app.workers.tasks import run_workflow as run_workflow_task

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


@router.post("/workflow/run", response_model=WorkflowRunRead, status_code=202)
async def run_workflow(
    payload: WorkflowRunCreate, session: AsyncSession = Depends(get_db)
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


@router.get("/workflow/reviews", response_model=list[WorkflowReviewSummary])
async def list_reviews(
    status: Literal["awaiting_review", "needs_review"] | None = Query(
        None, description="Restrict to one queue; omit for both"
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> list[WorkflowReviewSummary]:
    """Everything a human has reason to look at: `awaiting_review` runs are
    genuinely paused on a LangGraph interrupt() and block on a decision;
    `needs_review` runs already reached END but flagged a low-confidence or
    disapproved outcome for an eventual glance. Declared ahead of
    GET /workflow/{workflow_run_id} so "reviews" doesn't get routed there and
    fail UUID conversion.

    Joins in donor/campaign name — a reviewer scanning the queue needs to know
    who they'd be mailing, not a bare donor UUID."""
    statuses = [status] if status else ["awaiting_review", "needs_review"]
    result = await session.execute(
        select(WorkflowRun, Donor, Campaign)
        .join(Donor, WorkflowRun.donor_id == Donor.id)
        .outerjoin(Campaign, WorkflowRun.campaign_id == Campaign.id)
        .where(WorkflowRun.status.in_(statuses))
        .order_by(WorkflowRun.created_at)
        .limit(limit)
        .offset(offset)
    )
    return [
        WorkflowReviewSummary(
            id=run.id,
            donor_id=run.donor_id,
            donor_name=f"{donor.first_name} {donor.last_name}",
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


@router.get("/workflow/{workflow_run_id}", response_model=WorkflowRunRead)
async def get_workflow(
    workflow_run_id: uuid.UUID,
    verbose: bool = Query(False, description="Include the full per-agent audit trail"),
    session: AsyncSession = Depends(get_db),
) -> WorkflowRunRead:
    run = await session.get(WorkflowRun, workflow_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="workflow run not found")

    response = WorkflowRunRead.model_validate(run)
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
) -> WorkflowRun:
    """Submits a human decision for a workflow paused on a real LangGraph
    interrupt() and re-enqueues it to resume from exactly where it stopped."""
    run = await session.get(WorkflowRun, workflow_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="workflow run not found")
    if run.status != "awaiting_review":
        raise HTTPException(
            status_code=409,
            detail=f"workflow run is '{run.status}', not awaiting_review — nothing to resume",
        )

    resume_workflow_after_review.delay(str(run.id), payload.model_dump())
    return run
