from pydantic import BaseModel, Field


class RecommendationResult(BaseModel):
    """The LLM's structured recommendation. The RFM/ladder fields are carried
    through from the deterministic computation (the model must not alter them);
    recommended_ask must be one of the ask_ladder values; rationale and sources
    ground the choice in retrieved campaign knowledge."""

    segment: str
    rfm_score: float
    recency_days: int | None = None
    frequency: int
    monetary_total: float
    anchor_gift: float = Field(description="The gift amount the ask ladder was anchored on.")
    outlier_gift_excluded: bool = Field(
        default=False,
        description="True when an anomalous top gift was excluded from the anchor.",
    )
    ask_ladder: list[float]
    recommended_ask: float = Field(description="Must be one of the ask_ladder amounts.")
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: list[str]
    sources: list[str] = Field(description="Titles of the campaign-knowledge documents cited.")
