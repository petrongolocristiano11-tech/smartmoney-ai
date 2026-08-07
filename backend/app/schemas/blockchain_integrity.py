from datetime import datetime
from typing import Literal

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


class CanonicalParserPromotionApproveRequest(BaseModel):
    confirmation: str = Field(default="", max_length=120)
    assessment_id: str | None = Field(
        default=None,
        min_length=36,
        max_length=36,
    )
    scope: str = Field(default="SHADOW_ONLY", max_length=32)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserPromotionRevokeRequest(BaseModel):
    promotion_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=120)
    reason: str = Field(min_length=3, max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)

class CanonicalParserRuntimeBindRequest(BaseModel):
    promotion_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=180)
    scope: str = Field(default="SHADOW_ONLY", max_length=32)
    channel: str = Field(default="CANONICAL_SHADOW", max_length=32)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserRuntimeUnbindRequest(BaseModel):
    binding_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=160)
    reason: str = Field(min_length=3, max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)


class CanonicalParserRuntimeAdmissionRequest(BaseModel):
    confirmation: str = Field(default="", max_length=180)
    binding_id: str | None = Field(default=None, min_length=36, max_length=36)
    raw_event_ids: list[int] = Field(default_factory=list, max_length=100)
    limit: int = Field(default=10, ge=1, le=100)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserRuntimeCertificationRequest(BaseModel):
    confirmation: str = Field(default="", max_length=180)
    binding_id: str | None = Field(default=None, min_length=36, max_length=36)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserRuntimeCertificationRevokeRequest(BaseModel):
    certification_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=180)
    reason: str = Field(min_length=3, max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)

class CanonicalParserShadowRuntimeLeaseIssueRequest(BaseModel):
    confirmation: str = Field(default="", max_length=180)
    certification_id: str | None = Field(
        default=None, min_length=36, max_length=36
    )
    validity_minutes: int = Field(default=30, ge=5, le=1440)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserShadowRuntimeLeaseRevokeRequest(BaseModel):
    lease_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=180)
    reason: str = Field(min_length=3, max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)


class CanonicalParserShadowConsumerRunRequest(BaseModel):
    confirmation: str = Field(default="", max_length=180)
    lease_id: str | None = Field(default=None, min_length=36, max_length=36)
    raw_event_ids: list[int] = Field(default_factory=list, max_length=100)
    limit: int = Field(default=10, ge=1, le=100)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserShadowReadinessAssessmentRequest(BaseModel):
    confirmation: str = Field(default="", max_length=180)
    lease_id: str | None = Field(default=None, min_length=36, max_length=36)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserShadowAutomationPermitIssueRequest(BaseModel):
    confirmation: str = Field(default="", max_length=220)
    assessment_id: str | None = Field(
        default=None, min_length=36, max_length=36
    )
    validity_minutes: int = Field(default=5, ge=1, le=1440)
    run_budget: int = Field(default=3, ge=1, le=1000)
    event_budget: int = Field(default=50, ge=1, le=100000)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserShadowAutomationPermitRevokeRequest(BaseModel):
    permit_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=220)
    reason: str = Field(min_length=3, max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)


class CanonicalParserShadowExecutionTicketReserveRequest(BaseModel):
    confirmation: str = Field(default="", max_length=240)
    permit_id: str | None = Field(default=None, min_length=36, max_length=36)
    validity_seconds: int = Field(default=120, ge=1, le=3600)
    event_reservation: int = Field(default=10, ge=1, le=100000)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserShadowExecutionTicketReleaseRequest(BaseModel):
    ticket_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=240)
    reason: str = Field(min_length=3, max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)


class CanonicalParserShadowTicketExecutionRunRequest(BaseModel):
    confirmation: str = Field(default="", max_length=240)
    ticket_id: str = Field(min_length=36, max_length=36)
    raw_event_ids: list[int] | None = None
    limit: int = Field(default=10, ge=1, le=100)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserShadowAutomationCycleRunRequest(BaseModel):
    confirmation: str = Field(default="", max_length=260)
    permit_id: str | None = Field(default=None, min_length=36, max_length=36)
    raw_event_ids: list[int] | None = None
    event_reservation: int = Field(default=10, ge=1, le=100)
    limit: int = Field(default=10, ge=1, le=100)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserShadowSchedulerStartRequest(BaseModel):
    confirmation: str = Field(default="", max_length=280)
    permit_id: str = Field(min_length=36, max_length=36)
    interval_seconds: int = Field(default=300, ge=1, le=86400)
    event_reservation: int = Field(default=10, ge=1, le=100)
    limit: int = Field(default=10, ge=1, le=100)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserShadowSchedulerControlRequest(BaseModel):
    confirmation: str = Field(default="", max_length=280)
    reason: str = Field(min_length=3, max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)


class CanonicalParserShadowSchedulerHeartbeatRequest(BaseModel):
    confirmation: str = Field(default="", max_length=280)
    actor_label: str | None = Field(default=None, max_length=80)


class CanonicalParserShadowSchedulerTickRequest(BaseModel):
    confirmation: str = Field(default="", max_length=280)
    raw_event_ids: list[int] | None = None
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserShadowWorkerStartRequest(BaseModel):
    confirmation: str = Field(default="", max_length=320)
    owner_id: str = Field(min_length=3, max_length=80)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserShadowWorkerControlRequest(BaseModel):
    confirmation: str = Field(default="", max_length=320)
    owner_id: str = Field(min_length=3, max_length=80)
    reason: str = Field(min_length=3, max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)


class CanonicalParserShadowWorkerHeartbeatRequest(BaseModel):
    confirmation: str = Field(default="", max_length=320)
    owner_id: str = Field(min_length=3, max_length=80)
    actor_label: str | None = Field(default=None, max_length=80)


class CanonicalParserShadowWorkerIterationRequest(BaseModel):
    confirmation: str = Field(default="", max_length=320)
    owner_id: str = Field(min_length=3, max_length=80)
    raw_event_ids: list[int] | None = None
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserShadowWorkerLoopRunRequest(BaseModel):
    confirmation: str = Field(default="", max_length=320)
    owner_id: str = Field(min_length=3, max_length=80)
    iterations: int = Field(default=3, ge=1, le=50)
    raw_event_ids: list[int] | None = None
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserShadowWorkerRecoveryRunRequest(BaseModel):
    confirmation: str = Field(default="", max_length=320)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserShadowReliabilityAssessmentRequest(BaseModel):
    confirmation: str = Field(default="", max_length=320)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)

class CanonicalParserShadowReliabilityCertificationRequest(BaseModel):
    confirmation: str = Field(default="", max_length=320)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserShadowReliabilityCertificationRevokeRequest(BaseModel):
    certification_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=320)
    reason: str = Field(min_length=3, max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)


class CanonicalParserPaperProjectionRunRequest(BaseModel):
    confirmation: str = Field(default="", max_length=320)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserPaperProjectionReadinessAssessmentRequest(BaseModel):
    confirmation: str = Field(default="", max_length=320)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserPaperAdmissionCertificationRequest(BaseModel):
    confirmation: str = Field(default="", max_length=320)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserPaperAdmissionCertificationRevokeRequest(BaseModel):
    certification_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=320)
    reason: str = Field(min_length=3, max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)


class CanonicalParserPaperRuntimeBindRequest(BaseModel):
    paper_account_id: int = Field(ge=1)
    confirmation: str = Field(default="", max_length=320)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserPaperRuntimeUnbindRequest(BaseModel):
    binding_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=320)
    reason: str = Field(min_length=3, max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)


class CanonicalParserPaperAdmissionCanaryRunRequest(BaseModel):
    confirmation: str = Field(default="", max_length=320)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)

class CanonicalParserPaperCanaryReadinessAssessmentRequest(BaseModel):
    confirmation: str = Field(default="", max_length=320)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserPaperExecutionPermitIssueRequest(BaseModel):
    readiness_assessment_id: str | None = Field(default=None, min_length=36, max_length=36)
    validity_minutes: int = Field(default=15, ge=1, le=1440)
    total_budget_sol: float = Field(default=0.5, gt=0, le=1000000)
    max_order_budget_sol: float = Field(default=0.1, gt=0, le=1000000)
    max_order_count: int = Field(default=5, ge=1, le=100000)
    confirmation: str = Field(default="", max_length=320)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserPaperExecutionPermitRevokeRequest(BaseModel):
    permit_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=320)
    reason: str = Field(min_length=3, max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)


class CanonicalParserUnifiedDecisionRunRequest(BaseModel):
    confirmation: str = Field(default="", max_length=320)
    lookback_minutes: int | None = Field(default=None, ge=1, le=10080)
    max_results: int | None = Field(default=None, ge=1, le=1000)
    source_trade_ids: list[int] | None = Field(default=None, max_length=1000)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)

class CanonicalParserGen4ProfitabilityRunRequest(BaseModel):
    confirmation: str = Field(default="", max_length=320)
    training_days: int | None = Field(default=None, ge=3, le=365)
    test_days: int | None = Field(default=None, ge=1, le=90)
    step_days: int | None = Field(default=None, ge=1, le=90)
    max_windows: int | None = Field(default=None, ge=1, le=24)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)

class CanonicalParserGen4ForwardCampaignStartRequest(BaseModel):
    confirmation: str = Field(default="", max_length=320)
    candidate_wallets: list[str] | None = Field(default=None, max_length=100)
    anchor_at: datetime | None = None
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserGen4ForwardCycleRequest(BaseModel):
    campaign_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=320)
    observed_at: datetime | None = None


class CanonicalParserGen4ForwardCampaignStopRequest(BaseModel):
    campaign_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=320)
    observed_at: datetime | None = None
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


# BEGIN M56-M57 GEN4 FORWARD AUTOMATIC FEED
class CanonicalParserGen4ForwardFeedConfigureRequest(BaseModel):
    campaign_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=320)
    enabled: bool = True
    interval_seconds: int | None = Field(default=None, ge=30, le=3600)
    max_requests_per_run: int | None = Field(default=None, ge=1, le=20)
    page_size: int | None = Field(default=None, ge=10, le=100)
    overlap_seconds: int | None = Field(default=None, ge=0, le=300)


class CanonicalParserGen4ForwardFeedPollRequest(BaseModel):
    campaign_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=320)
    observed_at: datetime | None = None


# END M56-M57 GEN4 FORWARD AUTOMATIC FEED


# BEGIN M58-M60 GEN4 REAL-TIME COPYABILITY
class CanonicalParserGen4CopyabilityStartRequest(BaseModel):
    confirmation: str = Field(default="", max_length=320)
    anchor_at: datetime | None = None
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserGen4QualifiedCandidateStartRequest(BaseModel):
    confirmation: str = Field(default="", max_length=320)
    candidate_wallets: list[str] = Field(min_length=1, max_length=20)
    selection_snapshot: dict = Field(default_factory=dict)
    anchor_at: datetime | None = None
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserGen4CopyabilityStopRequest(BaseModel):
    campaign_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=320)
    observed_at: datetime | None = None


class CanonicalParserGen4CopyabilityWebhookConfigureRequest(BaseModel):
    campaign_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=320)
    webhook_id: str = Field(min_length=1, max_length=80)
    webhook_url: str = Field(min_length=8, max_length=500)
    active: bool = True
    observed_at: datetime | None = None


class CanonicalParserGen4CopyabilityProcessRequest(BaseModel):
    confirmation: str = Field(default="", max_length=320)
    batch_size: int | None = Field(default=None, ge=1, le=100)
    observed_at: datetime | None = None
# END M58-M60 GEN4 REAL-TIME COPYABILITY


class CanonicalParserPermitBoundPaperExecutionRequest(BaseModel):
    permit_id: str = Field(min_length=36, max_length=36)
    decision_result_id: str = Field(min_length=36, max_length=36)
    side: Literal["BUY", "SELL"]
    market_price_sol: float = Field(gt=0, le=1000000000)
    idempotency_token: str = Field(min_length=8, max_length=200)
    confirmation: str = Field(default="", max_length=500)
    quantity: float | None = Field(default=None, gt=0)
    slippage_percent: float = Field(default=0.5, ge=0, le=50)
    fee_percent: float = Field(default=0.25, ge=0, le=20)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserPermitBoundPaperReconcileRequest(BaseModel):
    execution_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)


class CanonicalParserPaperCalibrationRunRequest(BaseModel):
    paper_account_id: int = Field(ge=1)
    permit_id: str | None = Field(default=None, min_length=36, max_length=36)
    lookback_days: int | None = Field(default=None, ge=1, le=3650)
    window_started_at: datetime | None = None
    window_ended_at: datetime | None = None
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserPaperCampaignItemRequest(BaseModel):
    decision_result_id: str = Field(min_length=36, max_length=36)
    side: Literal["BUY", "SELL"] = "BUY"
    market_price_sol: float = Field(gt=0, le=1_000_000_000)
    quantity: float | None = Field(default=None, gt=0)
    slippage_percent: float = Field(default=0.5, ge=0, le=50)
    fee_percent: float = Field(default=0.25, ge=0, le=20)
    idempotency_token: str = Field(min_length=8, max_length=200)


class CanonicalParserPaperCampaignRunRequest(BaseModel):
    permit_id: str = Field(min_length=36, max_length=36)
    items: list[CanonicalParserPaperCampaignItemRequest] = Field(min_length=1, max_length=100)
    confirmation: str = Field(default="", max_length=260)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserPaperCampaignRecoveryRequest(BaseModel):
    campaign_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=260)
    actor_label: str | None = Field(default=None, max_length=80)


class CanonicalParserPaperOperationalAssessmentRequest(BaseModel):
    paper_account_id: int = Field(ge=1)
    calibration_campaign_id: str | None = Field(default=None, min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=260)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserMicroLiveCanaryPermitIssueRequest(BaseModel):
    operational_assessment_id: str = Field(min_length=36, max_length=36)
    validity_minutes: int = Field(default=10, ge=1, le=60)
    total_budget_sol: float = Field(default=0.03, gt=0, le=10)
    max_order_budget_sol: float = Field(default=0.01, gt=0, le=1)
    max_order_count: int = Field(default=3, ge=1, le=20)
    confirmation: str = Field(default="", max_length=300)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserMicroLiveCanaryPermitRevokeRequest(BaseModel):
    permit_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=300)
    reason: str = Field(min_length=3, max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)


class CanonicalParserMicroLiveCanarySimulationRequest(BaseModel):
    permit_id: str = Field(min_length=36, max_length=36)
    decision_result_id: str = Field(min_length=36, max_length=36)
    governed_exit_intent_id: str | None = Field(default=None, min_length=36, max_length=36)
    side: Literal["BUY", "SELL"] = "BUY"
    market_price_sol: float = Field(gt=0, le=1_000_000_000)
    requested_budget_sol: float = Field(default=0.01, ge=0, le=10)
    idempotency_token: str = Field(min_length=8, max_length=200)
    confirmation: str = Field(default="", max_length=320)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserIsolatedSignerProfileIssueRequest(BaseModel):
    wallet_address: str = Field(min_length=32, max_length=64)
    validity_minutes: int = Field(default=30, ge=1, le=1440)
    allowed_program_ids: list[str] = Field(min_length=1, max_length=64)
    max_transaction_bytes: int = Field(default=1232, ge=1, le=4096)
    max_required_signers: int = Field(default=1, ge=1, le=16)
    allow_address_lookup_tables: bool = False
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserIsolatedSignerProfileRevokeRequest(BaseModel):
    profile_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=500)
    reason: str = Field(min_length=3, max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)


class CanonicalParserLiveTransactionBuildPreviewRequest(BaseModel):
    signer_profile_id: str = Field(min_length=36, max_length=36)
    micro_live_simulation_id: str = Field(min_length=36, max_length=36)
    amount_raw: int | None = Field(default=None, ge=1)
    slippage_bps: int | None = Field(default=None, ge=1, le=5000)
    idempotency_token: str = Field(min_length=8, max_length=200)


class CanonicalParserLiveTransactionDryRunRequest(BaseModel):
    signer_profile_id: str = Field(min_length=36, max_length=36)
    micro_live_simulation_id: str = Field(min_length=36, max_length=36)
    transaction_source: Literal["JUPITER_ORDER", "PROVIDED_TRANSACTION"] = "JUPITER_ORDER"
    unsigned_transaction_base64: str = Field(min_length=8, max_length=10000)
    input_mint: str = Field(min_length=32, max_length=64)
    output_mint: str = Field(min_length=32, max_length=64)
    amount_raw: int = Field(ge=1)
    jupiter_request_id: str | None = Field(default=None, max_length=160)
    jupiter_router: str | None = Field(default=None, max_length=160)
    jupiter_price_impact_percent: float | None = Field(default=None, ge=0, le=100)
    jupiter_slippage_bps: int | None = Field(default=None, ge=0, le=5000)
    idempotency_token: str = Field(min_length=8, max_length=200)
    run_rpc_simulation: bool = True
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)

class CanonicalParserExternalSigningApprovalRequest(BaseModel):
    dry_run_id: str = Field(min_length=36, max_length=36)
    signed_transaction_base64: str = Field(min_length=8, max_length=10000)
    idempotency_token: str = Field(min_length=8, max_length=200)
    run_rpc_simulation: bool = True
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserExternalSigningApprovalRevokeRequest(BaseModel):
    approval_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=500)
    reason: str = Field(min_length=3, max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)


class CanonicalParserControlledLiveSubmissionRequest(BaseModel):
    approval_id: str = Field(min_length=36, max_length=36)
    signed_transaction_base64: str = Field(min_length=8, max_length=10000)
    idempotency_token: str = Field(min_length=8, max_length=200)
    portfolio_risk_permit_id: str | None = Field(default=None, min_length=36, max_length=36)
    preproduction_release_approval_id: str | None = Field(default=None, min_length=36, max_length=36)
    assisted_micro_live_pilot_id: str | None = Field(default=None, min_length=36, max_length=36)
    progressive_automation_lease_id: str | None = Field(default=None, min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserControlledLiveReconcileRequest(BaseModel):
    submission_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)

class CanonicalParserLiveOnchainSettlementRequest(BaseModel):
    submission_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserGovernedLivePositionAssessmentRequest(BaseModel):
    position_id: str = Field(min_length=36, max_length=36)
    quoted_output_sol: float = Field(gt=0, le=1_000_000_000)
    price_impact_percent: float = Field(default=0, ge=0, le=100)
    sell_route_available: bool = True
    token_safety_status: Literal["SAFE", "REVIEW", "UNSAFE", "UNKNOWN"] = "SAFE"
    source_wallet_sell_detected: bool = False
    emergency_exit_requested: bool = False
    quote_observed_at: datetime
    idempotency_token: str = Field(min_length=8, max_length=200)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserGovernedLiveExitIntentIssueRequest(BaseModel):
    assessment_id: str = Field(min_length=36, max_length=36)
    percentage: float = Field(default=100, gt=0, le=100)
    validity_minutes: int = Field(default=5, ge=1, le=1440)
    idempotency_token: str = Field(min_length=8, max_length=200)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserGovernedLiveExitIntentRevokeRequest(BaseModel):
    intent_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=500)
    reason: str = Field(min_length=3, max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)

class CanonicalParserLiveIncidentDeclareRequest(BaseModel):
    source_type: Literal["SUBMISSION", "SETTLEMENT", "POSITION", "MANUAL"]
    source_id: str = Field(min_length=1, max_length=96)
    category: str | None = Field(default=None, max_length=80)
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None = None
    freeze_new_submissions: bool | None = None
    reason_codes: list[str] = Field(default_factory=list, max_length=20)
    idempotency_token: str = Field(min_length=8, max_length=200)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserLiveIncidentAcknowledgeRequest(BaseModel):
    incident_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserLiveRecoveryAuthorizationRequest(BaseModel):
    incident_id: str = Field(min_length=36, max_length=36)
    action: Literal["RECONCILE_SUBMISSION", "RETRY_SETTLEMENT_READ", "MANUAL_POSITION_REVIEW", "FREEZE_NEW_SUBMISSIONS", "UNFREEZE_NEW_SUBMISSIONS"]
    validity_minutes: int = Field(default=10, ge=1, le=1440)
    idempotency_token: str = Field(min_length=8, max_length=200)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserLiveRecoveryRevokeRequest(BaseModel):
    recovery_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=500)
    reason: str = Field(min_length=3, max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)


class CanonicalParserLiveIncidentResolveRequest(BaseModel):
    incident_id: str = Field(min_length=36, max_length=36)
    resolution_evidence: str = Field(min_length=8, max_length=500)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserLivePortfolioRiskAssessmentRequest(BaseModel):
    wallet_address: str = Field(min_length=32, max_length=64)
    side: Literal["BUY", "SELL"]
    requested_token_mint: str = Field(min_length=32, max_length=64)
    requested_budget_sol: float = Field(default=0, ge=0, le=1_000_000)
    as_of: datetime
    idempotency_token: str = Field(min_length=8, max_length=200)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserLivePortfolioRiskPermitIssueRequest(BaseModel):
    assessment_id: str = Field(min_length=36, max_length=36)
    validity_minutes: int = Field(default=5, ge=1, le=1440)
    idempotency_token: str = Field(min_length=8, max_length=200)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserLivePortfolioRiskPermitRevokeRequest(BaseModel):
    permit_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=500)
    reason: str = Field(min_length=3, max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)

class CanonicalParserLiveOperationalObservationRequest(BaseModel):
    idempotency_token: str = Field(min_length=8, max_length=200)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserLiveOperationalAlertIssueRequest(BaseModel):
    snapshot_id: str = Field(min_length=36, max_length=36)
    reason_code: str = Field(min_length=3, max_length=96)
    idempotency_token: str = Field(min_length=8, max_length=200)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserLiveOperationalAlertAcknowledgeRequest(BaseModel):
    alert_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserLiveOperationalAlertResolveRequest(BaseModel):
    alert_id: str = Field(min_length=36, max_length=36)
    resolution_evidence: str = Field(min_length=8, max_length=500)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserPreproductionCertificationRequest(BaseModel):
    observability_snapshot_id: str = Field(min_length=36, max_length=36)
    git_commit_sha: str = Field(min_length=40, max_length=40)
    clean_worktree_attested: bool
    full_test_count: int = Field(ge=1, le=1_000_000)
    full_test_failures: int = Field(default=0, ge=0, le=1_000_000)
    test_evidence_hash: str = Field(min_length=64, max_length=64)
    idempotency_token: str = Field(min_length=8, max_length=200)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserPreproductionCertificationRevokeRequest(BaseModel):
    certification_id: str = Field(min_length=36, max_length=36)
    reason: str = Field(min_length=3, max_length=500)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)


class CanonicalParserPreproductionReleaseIssueRequest(BaseModel):
    certification_id: str = Field(min_length=36, max_length=36)
    wallet_address: str = Field(min_length=32, max_length=64)
    side: Literal["BUY", "SELL"]
    token_mint: str = Field(min_length=32, max_length=64)
    max_budget_sol: float = Field(default=0, ge=0, le=1_000_000)
    validity_minutes: int = Field(default=5, ge=1, le=1440)
    idempotency_token: str = Field(min_length=8, max_length=200)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserPreproductionReleaseRevokeRequest(BaseModel):
    release_id: str = Field(min_length=36, max_length=36)
    reason: str = Field(min_length=3, max_length=500)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)


class CanonicalParserAssistedMicroLivePilotIssueRequest(BaseModel):
    certification_id: str = Field(min_length=36, max_length=36)
    wallet_address: str = Field(min_length=32, max_length=64)
    token_mint: str = Field(min_length=32, max_length=64)
    max_entry_budget_sol: float = Field(gt=0, le=1)
    max_total_fee_sol: float = Field(default=0.001, ge=0, le=1)
    max_position_duration_minutes: int = Field(default=30, ge=1, le=1440)
    validity_minutes: int = Field(default=60, ge=5, le=1440)
    idempotency_token: str = Field(min_length=8, max_length=200)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserAssistedMicroLiveChecklistAttestRequest(BaseModel):
    pilot_id: str = Field(min_length=36, max_length=36)
    item_code: str = Field(min_length=3, max_length=80)
    status: Literal["PASS", "FAIL"]
    evidence: str = Field(min_length=8, max_length=500)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)


class CanonicalParserAssistedMicroLivePilotArmRequest(BaseModel):
    pilot_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserAssistedMicroLivePilotCheckpointRequest(BaseModel):
    pilot_id: str = Field(min_length=36, max_length=36)
    checkpoint_type: Literal[
        "ENTRY_RECONCILED",
        "ENTRY_SETTLED",
        "EXIT_INTENT_VERIFIED",
        "EXIT_RECONCILED",
        "EXIT_SETTLED",
        "POST_PILOT_HEALTH",
    ]
    source_id: str = Field(min_length=1, max_length=96)
    idempotency_token: str = Field(min_length=8, max_length=200)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserAssistedMicroLivePilotCompleteRequest(BaseModel):
    pilot_id: str = Field(min_length=36, max_length=36)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserAssistedMicroLivePilotAbortRequest(BaseModel):
    pilot_id: str = Field(min_length=36, max_length=36)
    reason: str = Field(min_length=3, max_length=500)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)

class CanonicalParserProductionHardeningAssessmentRequest(BaseModel):
    wallet_address: str = Field(min_length=32, max_length=64)
    token_mint: str = Field(min_length=32, max_length=64)
    requested_stage: Literal["OBSERVE_ONLY", "ASSISTED", "SUPERVISED", "AUTOMATION_CANDIDATE"]
    requested_max_budget_sol: float = Field(default=0, ge=0, le=1)
    requested_max_submissions: int = Field(default=0, ge=0, le=100)
    idempotency_token: str = Field(min_length=8, max_length=200)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserProgressiveAutomationLeaseIssueRequest(BaseModel):
    assessment_id: str = Field(min_length=36, max_length=36)
    validity_minutes: int = Field(default=15, ge=1, le=1440)
    idempotency_token: str = Field(min_length=8, max_length=200)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserProgressiveAutomationLeaseRevokeRequest(BaseModel):
    lease_id: str = Field(min_length=36, max_length=36)
    reason: str = Field(min_length=3, max_length=500)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)


class CanonicalParserProductionCircuitBreakerTripRequest(BaseModel):
    wallet_address: str = Field(min_length=32, max_length=64)
    reason_codes: list[str] = Field(default_factory=list, max_length=20)
    source_type: Literal["MANUAL", "INCIDENT", "OBSERVABILITY", "SUBMISSION"] = "MANUAL"
    source_id: str | None = Field(default=None, max_length=96)
    idempotency_token: str = Field(min_length=8, max_length=200)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)


class CanonicalParserProductionCircuitBreakerResetRequest(BaseModel):
    breaker_id: str = Field(min_length=36, max_length=36)
    resolution_evidence: str = Field(min_length=8, max_length=500)
    confirmation: str = Field(default="", max_length=500)
    actor_label: str | None = Field(default=None, max_length=80)
    note: str | None = Field(default=None, max_length=500)
