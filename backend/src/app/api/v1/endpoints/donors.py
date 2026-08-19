from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.deps_auth import get_current_user, require_role
from app.db.models import Donor, DonorImport, User, WorkflowRun
from app.donors.csv_ingest import ingest_donors, parse_csv_rows
from app.schemas.donors import DonorIngestResult, DonorUnrunRead

router = APIRouter()


@router.post(
    "/donors/ingest",
    response_model=DonorIngestResult,
    status_code=201,
    dependencies=[Depends(require_role("admin"))],
)
async def ingest_donors_csv(
    file: UploadFile, session: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)
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

    result = await ingest_donors(session, rows)

    record = DonorImport(
        uploaded_by_user_id=user.id,
        filename=file.filename,
        rows_inserted=result["inserted"],
        rows_updated=result["updated"],
        rows_rejected=len(result["rejected"]),
        rejected_rows=result["rejected"],
    )
    session.add(record)
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
