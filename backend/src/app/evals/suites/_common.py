"""Shared helpers for the donor-driven suites (verification, trajectory)."""

import uuid

from sqlalchemy import select

from app.db.models import Donor, WorkflowRun
from app.db.session import db_session


async def resolve_donor_id(external_id: str) -> uuid.UUID:
    """Look the donor up by its CRM external_id rather than re-deriving the seed
    UUID, so evals stay correct against whatever is actually in the database."""
    async with db_session() as session:
        donor_id = (
            await session.execute(select(Donor.id).where(Donor.external_id == external_id))
        ).scalar_one_or_none()
    if donor_id is None:
        raise LookupError(f"donor {external_id!r} not found — run scripts/seed_db.py")
    return donor_id


async def create_workflow_run(donor_id: uuid.UUID) -> str:
    """Eval runs are real workflow runs: agent nodes write audit rows against
    this id, so an eval result stays traceable to the reasoning that produced it."""
    async with db_session() as session:
        run = WorkflowRun(donor_id=donor_id)
        session.add(run)
        await session.commit()
        await session.refresh(run)
        return str(run.id)
