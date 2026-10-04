from typing import Literal

from pydantic import BaseModel


class HumanReviewDecision(BaseModel):
    action: Literal["approve", "reject", "modify"]
    # The review stage this decision was made for. The API requires it and checks
    # it against the stage the run is actually paused at; optional here only
    # because the graph is also driven directly (CLI, integration tests).
    stage: Literal["address", "recommendation", "compliance"] | None = None
    # A review decision can carry a correction for whichever stage paused: an
    # address fix (address stage) or a capped/adjusted ask (recommendation
    # stage). Only the field relevant to the paused stage is used.
    updated_address: str | None = None
    updated_ask_amount: float | None = None
    reviewer: str | None = None
    notes: str | None = None
