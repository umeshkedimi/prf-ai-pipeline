from pydantic import BaseModel, Field


class AddressResult(BaseModel):
    deliverable: bool
    confidence: float = Field(ge=0.0, le=1.0)
    updated_address: str | None = None
    moved: bool = False
    reasoning: list[str] = Field(default_factory=list)
