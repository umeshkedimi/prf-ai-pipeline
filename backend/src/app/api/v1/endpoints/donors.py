import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_auth import get_current_user, require_role
from app.campaigns.membership import attach_donors_by_external_id
from app.db.models import Campaign, Donor, DonorImport, User, WorkflowRun
from app.donors.csv_ingest import ingest_donors, parse_csv_rows, validate_row
from app.schemas.donors import DonorIngestResult, DonorUnrunRead

router = APIRouter()


@router.post(
    "/donors/ingest",
    response_model=DonorIngestResult,
    status_code=201,
    dependencies=[Depends(require_role("admin"))],
)
async def ingest_donors_csv(
    file: UploadFile,
    campaign_id: uuid.UUID | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DonorIngestResult:
    """Admin-only: bulk-modifying the donor dataset is a more privileged
    action than the reviewer role's trigger/review/view scope. Stages donor
    records only -- never starts a workflow run (see POST /workflow/run/batch
    for that, a separate explicit action)."""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="expected a .csv file")

    raw = (await file.read()).decode("utf-8-sig")  # utf-8-sig tolerates a BOM from Excel exports
    rows = parse_csv_rows(raw)
    if not rows:
        raise HTTPException(status_code=400, detail="CSV has no data rows")
    if campaign_id is not None and await session.get(Campaign, campaign_id) is None:
        raise HTTPException(status_code=404, detail="campaign not found")

    result = await ingest_donors(session, rows)

    record = DonorImport(
        uploaded_by_user_id=user.id,
        filename=file.filename,
        rows_inserted=result["inserted"],
        rows_updated=result["updated"],
        rows_rejected=len(result["rejected"]),
        rejected_rows=result["rejected"],
        campaign_id=campaign_id,
    )
    session.add(record)
    await session.flush()
    if campaign_id is not None:
        # Rejected rows never reach the donors table, so only valid rows can be members.
        valid_ids = [row["external_id"].strip() for row in rows if validate_row(row) is None]
        await attach_donors_by_external_id(session, campaign_id, valid_ids, record.id)
    await session.commit()
    await session.refresh(record)

    return DonorIngestResult(
        import_id=record.id,
        filename=record.filename,
        rows_inserted=record.rows_inserted,
        rows_updated=record.rows_updated,
        rows_rejected=record.rows_rejected,
        rejected=result["rejected"],
    )


@router.get("/donors/unrun", response_model=list[DonorUnrunRead])
async def list_unrun_donors(
    limit: int = Query(200, ge=1, le=1000),
    session: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),
) -> list[Donor]:
    """Donors with zero workflow_runs rows -- the staging list a reviewer
    picks from to trigger runs via POST /workflow/run/batch."""
    never_run = select(WorkflowRun.donor_id).distinct()
    stmt = select(Donor).where(Donor.id.not_in(never_run)).order_by(Donor.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())
