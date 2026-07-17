import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.db.models import AgentAuditLog, Donor, WorkflowRun
from app.schemas.workflow import AuditLogEntry, WorkflowRunCreate, WorkflowRunRead
from app.workers.tasks import run_donor_verification_workflow

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
    """Enqueues the Donor Verification workflow and returns immediately —
    the API never invokes the LangGraph graph itself, Celery does (see
    workers/tasks.py). Poll GET /workflow/{id} for status."""
    donor_uuid = await _resolve_donor_id(session, payload.donor_id)
    campaign_uuid = uuid.UUID(payload.campaign_id) if payload.campaign_id else None

    run = WorkflowRun(donor_id=donor_uuid, campaign_id=campaign_uuid)
    session.add(run)
    await session.commit()
    await session.refresh(run)

    run_donor_verification_workflow.delay(str(run.id))
    return run


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
