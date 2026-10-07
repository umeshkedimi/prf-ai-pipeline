import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AgentRunCreate(BaseModel):
    goal: str | None = Field(default=None, max_length=500)
    max_steps: int = Field(default=40, ge=1, le=100)
    max_tokens: int = Field(default=150_000, ge=1_000, le=1_000_000)
    max_runs: int = Field(default=200, ge=1, le=500)


class AgentStepRead(BaseModel):
    seq: int
    tool: str
    tier: str | None = None
    args: dict | None = None
    outcome: str
    observation: Any = None
    latency_ms: int | None = None
    created_at: datetime


class AgentRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    campaign_id: uuid.UUID
    goal: str
    status: str
    budget: dict
    pending_approval: dict | None = None
    final_report: dict | None = None
    created_at: datetime
    completed_at: datetime | None = None


class AgentRunDetail(AgentRunRead):
    steps: list[AgentStepRead]


class AgentApprovalDecision(BaseModel):
    tool: str  # must match the pending call, like /review's required `stage`
    approve: bool
    notes: str | None = Field(default=None, max_length=500)
