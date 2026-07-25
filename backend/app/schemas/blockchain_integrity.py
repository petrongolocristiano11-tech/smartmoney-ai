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


class NormalizationReplayExecuteRequest(BaseModel):
    parser_name: str = Field(min_length=3, max_length=80)
    parser_version: str = Field(min_length=5, max_length=64)
    selection_mode: str = Field(default="REPROCESS", max_length=16)
    confirmation: str = Field(default="", max_length=80)
    provider: str | None = Field(default=None, min_length=1, max_length=64)
    event_type: str | None = Field(default=None, min_length=1, max_length=80)
    transaction_signature: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    observed_wallet: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
    )
    observed_from: str | None = None
    observed_to: str | None = None
    limit: int = Field(default=100, ge=1, le=1000)


class CanonicalMaterializationExecuteRequest(BaseModel):
    confirmation: str = Field(default="", max_length=80)
    provider: str | None = Field(default=None, min_length=1, max_length=64)
    observed_wallet: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
    )
    transaction_signature: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    limit: int = Field(default=100, ge=1, le=1000)


class CanonicalShadowValidationExecuteRequest(BaseModel):
    confirmation: str = Field(default="", max_length=80)
    transaction_signature: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
    )
    observed_wallet: str | None = Field(
        default=None,
        min_length=1,
        max_length=64,
    )
    quality_status: str | None = Field(
        default=None,
        min_length=4,
        max_length=8,
    )
    limit: int = Field(default=200, ge=1, le=5000)


class CanonicalQualityAssessmentRequest(BaseModel):
    confirmation: str = Field(default="", max_length=80)
    validation_id: str | None = Field(
        default=None,
        min_length=36,
        max_length=36,
    )
