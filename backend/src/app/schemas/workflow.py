import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class WorkflowRunCreate(BaseModel):
    donor_id: str  # our internal donor UUID, or the CRM's external_id (e.g. "d-0006")
    campaign_id: str | None = None


class AuditLogEntry(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    step: str
    output: dict | None = None
    confidence: Decimal | None = None
    reasoning: str | None = None
    source_refs: list | None = None
    tool_calls: list | None = None
    model: str | None = None
    latency_ms: int | None = None
    created_at: datetime


class WorkflowRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    donor_id: uuid.UUID
    campaign_id: uuid.UUID | None = None
    status: str
    current_agent: str | None = None
    result: dict | None = None
    confidence: Decimal | None = None
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    audit_log: list[AuditLogEntry] = []
