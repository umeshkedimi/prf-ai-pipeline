from pydantic import BaseModel, Field


class VerificationResult(BaseModel):
    eligible: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    is_duplicate: bool = False
    duplicate_of_donor_id: str | None = None
    is_suspicious: bool = False
    reasoning: list[str] = Field(default_factory=list)
