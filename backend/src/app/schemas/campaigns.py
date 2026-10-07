import uuid
from datetime import date

from pydantic import BaseModel, ConfigDict


class CampaignCreate(BaseModel):
    name: str
    appeal_code: str | None = None
    start_date: date | None = None
    end_date: date | None = None


class CampaignRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    appeal_code: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: str


class CampaignSummary(CampaignRead):
    donor_counts: dict[str, int]
    total_donors: int
