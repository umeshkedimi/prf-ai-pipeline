from typing import Literal

from pydantic import BaseModel


class HumanReviewDecision(BaseModel):
    action: Literal["approve", "reject", "modify"]
    # A review decision can carry a correction for whichever stage paused: an
    # address fix (address stage) or a capped/adjusted ask (recommendation
    # stage). Only the field relevant to the paused stage is used.
    updated_address: str | None = None
    updated_ask_amount: float | None = None
    reviewer: str | None = None
    notes: str | None = None
