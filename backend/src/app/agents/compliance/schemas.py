from pydantic import BaseModel, Field


class LetterComplianceAssessment(BaseModel):
    """The LLM's content-risk review of the drafted letter. Required
    disclosures are a separate, deterministic lookup (gather_disclosures) —
    the model is never given that legal text as something to reproduce, only
    the letter to judge, so a paraphrase of regulatory language can never slip
    through."""

    approved: bool
    confidence: float = Field(ge=0.0, le=1.0)
    flagged_issues: list[str] = Field(default_factory=list)
    reasoning: list[str] = Field(default_factory=list)
