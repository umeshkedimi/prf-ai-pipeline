from pydantic import BaseModel, Field


class RecommendationResult(BaseModel):
    """The recommendation: the RFM summary and ladder from rfm.compute_rfm /
    build_ask_ladder, plus the rung rfm.choose_ask picked and why. Every field is
    computed by code; this model is the typed contract the rest of the pipeline reads."""

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
    recommended_ask: float = Field(description="Always one of the ask_ladder amounts.")
    confidence: float = Field(ge=0.0, le=1.0, description="Strength of the giving evidence, not a model's opinion.")
    rationale: list[str]
    sources: list[str] = Field(default_factory=list, description="Always empty: no retrieval is involved.")
