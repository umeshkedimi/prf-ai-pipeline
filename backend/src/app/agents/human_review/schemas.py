from typing import Literal

from pydantic import BaseModel


class HumanReviewDecision(BaseModel):
    action: Literal["approve", "reject", "modify"]
    updated_address: str | None = None
    reviewer: str | None = None
    notes: str | None = None
