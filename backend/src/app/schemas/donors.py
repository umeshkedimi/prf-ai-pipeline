import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class DonorIngestRowError(BaseModel):
    row_number: int
    reason: str
    external_id: str | None = None


class DonorIngestResult(BaseModel):
    import_id: uuid.UUID
    filename: str
    rows_inserted: int
    rows_updated: int
    rows_rejected: int
    rejected: list[DonorIngestRowError]


class DonorUnrunRead(BaseModel):
    """A donor with zero workflow runs -- from any source (seeded or
    CSV-imported), not just this session's uploads. Simpler than tracking
    per-donor provenance, and "never run" is the thing that actually matters
    for staging a batch trigger."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    external_id: str | None = None
    first_name: str
    last_name: str
    city: str | None = None
    state: str | None = None
    created_at: datetime


class WorkflowRunBatchCreate(BaseModel):
    donor_ids: list[str]  # internal UUIDs or CRM external_ids, same as WorkflowRunCreate.donor_id
    campaign_id: str | None = None


class WorkflowRunBatchItem(BaseModel):
    donor_id: str
    status: Literal["enqueued", "error"]
    workflow_run_id: uuid.UUID | None = None
    error: str | None = None
