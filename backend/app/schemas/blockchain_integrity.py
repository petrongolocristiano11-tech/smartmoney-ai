from pydantic import BaseModel, Field


class RawCaptureRetentionPruneRequest(BaseModel):
    dry_run: bool = True
    confirmation: str = Field(
        default="",
        max_length=80,
    )
    provider: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
    )
    batch_size: int | None = Field(
        default=None,
        ge=1,
        le=10_000,
    )
