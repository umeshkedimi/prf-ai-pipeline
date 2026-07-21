from pydantic import BaseModel, Field


class PersonalizationResult(BaseModel):
    """The LLM's structured letter draft. `segment` and `tone` are carried
    through unchanged from the deterministic lookup (the model must not alter
    them); the letter content must stay within that tone and be grounded in
    retrieved campaign knowledge."""

    segment: str
    tone: str
    salutation: str
    opening_line: str = Field(
        description="Acknowledges the donor's prior support before the ask."
    )
    body: str = Field(description="The ask paragraph, tied to a concrete cited impact.")
    closing_line: str
    impact_reference: str = Field(
        description="The specific cited outcome the ask is tied to."
    )
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: list[str]
    sources: list[str] = Field(description="Titles of the campaign-knowledge documents cited.")
