from datetime import datetime
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)

from backend.app.schemas.paper_trading import (
    PaperAccountResponse,
    PaperAccountSummaryResponse,
)


AutopilotStatus = Literal[
    "DISABLED",
    "ENABLED",
    "PAUSED",
]

AutopilotConfidence = Literal[
    "LOW",
    "MEDIUM",
    "HIGH",
]

AutopilotRunStatus = Literal[
    "RUNNING",
    "COMPLETED",
    "PARTIAL",
    "FAILED",
    "SKIPPED",
]

AutopilotTrigger = Literal[
    "MANUAL",
    "AUTOMATION",
]

AutopilotDecisionAction = Literal[
    "BUY",
    "SELL",
    "HOLD",
    "SKIP",
    "ERROR",
]

ManagedPositionStatus = Literal[
    "ACTIVE",
    "CLOSED",
]


class AutopilotRequestModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        allow_inf_nan=False,
    )


class PaperAutopilotPolicyUpdateRequest(
    AutopilotRequestModel
):
    status: AutopilotStatus | None = None

    min_signal_score: float | None = Field(
        default=None,
        ge=0,
        le=100,
    )

    min_evidence_score: float | None = Field(
        default=None,
        ge=0,
        le=100,
    )

    min_buyers: int | None = Field(
        default=None,
        ge=1,
        le=10_000,
    )

    minimum_confidence: (
        AutopilotConfidence | None
    ) = None

    max_signal_age_hours: float | None = Field(
        default=None,
        gt=0,
        le=720,
    )

    min_smart_volume_share_percent: (
        float | None
    ) = Field(
        default=None,
        ge=0,
        le=100,
    )

    max_volume_concentration_percent: (
        float | None
    ) = Field(
        default=None,
        ge=0,
        le=100,
    )

    blocked_risk_flags: list[str] | None = Field(
        default=None,
        max_length=100,
    )

    excluded_token_mints: list[str] | None = Field(
        default=None,
        max_length=500,
    )

    max_signals_per_run: int | None = Field(
        default=None,
        ge=1,
        le=1_000,
    )

    max_entries_per_run: int | None = Field(
        default=None,
        ge=1,
        le=100,
    )

    max_entries_per_day: int | None = Field(
        default=None,
        ge=1,
        le=1_000,
    )

    token_cooldown_hours: int | None = Field(
        default=None,
        ge=0,
        le=8_760,
    )

    max_position_percent_of_equity: (
        float | None
    ) = Field(
        default=None,
        gt=0,
        le=100,
    )

    max_total_exposure_percent: (
        float | None
    ) = Field(
        default=None,
        gt=0,
        le=100,
    )

    minimum_cash_reserve_percent: (
        float | None
    ) = Field(
        default=None,
        ge=0,
        le=100,
    )

    minimum_order_size_sol: float | None = Field(
        default=None,
        gt=0,
        le=1_000_000,
    )

    stop_loss_percent: float | None = Field(
        default=None,
        gt=0,
        le=100,
    )

    take_profit_percent: float | None = Field(
        default=None,
        gt=0,
        le=10_000,
    )

    trailing_stop_enabled: bool | None = None

    trailing_stop_percent: float | None = Field(
        default=None,
        gt=0,
        le=100,
    )

    max_holding_hours: int | None = Field(
        default=None,
        ge=1,
        le=8_760,
    )

    slippage_percent: float | None = Field(
        default=None,
        ge=0,
        le=50,
    )

    fee_percent: float | None = Field(
        default=None,
        ge=0,
        le=20,
    )

    max_consecutive_errors: int | None = Field(
        default=None,
        ge=1,
        le=100,
    )

    @field_validator(
        "blocked_risk_flags",
        mode="before",
    )
    @classmethod
    def normalize_risk_flags(
        cls,
        value,
    ):
        if value is None:
            return None

        normalized: list[str] = []
        seen: set[str] = set()

        for item in value:
            flag = str(
                item or ""
            ).strip().upper()

            if not flag:
                continue

            if len(flag) > 80:
                raise ValueError(
                    "Ogni risk flag può "
                    "contenere al massimo "
                    "80 caratteri."
                )

            if flag not in seen:
                seen.add(flag)
                normalized.append(flag)

        return normalized

    @field_validator(
        "excluded_token_mints",
        mode="before",
    )
    @classmethod
    def normalize_excluded_mints(
        cls,
        value,
    ):
        if value is None:
            return None

        normalized: list[str] = []
        seen: set[str] = set()

        for item in value:
            mint = str(
                item or ""
            ).strip()

            if not mint:
                continue

            if len(mint) > 64:
                raise ValueError(
                    "Ogni token mint può "
                    "contenere al massimo "
                    "64 caratteri."
                )

            if mint not in seen:
                seen.add(mint)
                normalized.append(mint)

        return normalized

    @model_validator(
        mode="after"
    )
    def require_update(
        self,
    ):
        if not self.model_fields_set:
            raise ValueError(
                "Specificare almeno "
                "una modifica."
            )

        return self


class AutopilotResponseModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )


class PaperAutopilotPolicyResponse(
    AutopilotResponseModel
):
    id: int
    account_id: int
    status: AutopilotStatus

    min_signal_score: float
    min_evidence_score: float
    min_buyers: int
    minimum_confidence: AutopilotConfidence
    max_signal_age_hours: float

    min_smart_volume_share_percent: float
    max_volume_concentration_percent: float

    blocked_risk_flags: list[str]
    excluded_token_mints: list[str]

    max_signals_per_run: int
    max_entries_per_run: int
    max_entries_per_day: int
    token_cooldown_hours: int

    max_position_percent_of_equity: float
    max_total_exposure_percent: float
    minimum_cash_reserve_percent: float
    minimum_order_size_sol: float

    stop_loss_percent: float
    take_profit_percent: float
    trailing_stop_enabled: bool
    trailing_stop_percent: float
    max_holding_hours: int

    slippage_percent: float
    fee_percent: float

    max_consecutive_errors: int
    consecutive_errors: int
    paused_reason: str | None

    last_run_at: datetime | None
    last_error_at: datetime | None

    created_at: datetime
    updated_at: datetime


class PaperAutopilotRunResponse(
    AutopilotResponseModel
):
    id: int
    account_id: int
    policy_id: int

    trigger: AutopilotTrigger
    status: AutopilotRunStatus

    signals_evaluated: int
    entries_opened: int
    exits_closed: int
    decisions_count: int
    errors_count: int

    error_message: str | None

    started_at: datetime
    finished_at: datetime | None
    created_at: datetime


class PaperAutopilotManagedPositionResponse(
    AutopilotResponseModel
):
    id: int
    account_id: int

    paper_position_id: int
    entry_order_id: int
    exit_order_id: int | None

    entry_run_id: int
    exit_run_id: int | None

    token_mint: str
    status: ManagedPositionStatus

    entry_price_sol: float
    peak_price_sol: float

    stop_loss_price_sol: float
    take_profit_price_sol: float

    trailing_stop_enabled: bool
    trailing_stop_percent: float

    entry_signal_score: float | None
    entry_evidence_score: float | None
    entry_confidence: str | None

    exit_reason: str | None

    max_holding_until: datetime
    opened_at: datetime
    closed_at: datetime | None

    created_at: datetime
    updated_at: datetime


class PaperAutopilotDecisionResponse(
    AutopilotResponseModel
):
    id: int
    run_id: int
    account_id: int

    managed_position_id: int | None
    paper_position_id: int | None
    paper_order_id: int | None

    token_mint: str | None

    action: AutopilotDecisionAction
    reason_code: str
    reason: str

    signal_score: float | None
    evidence_score: float | None
    buyers: int | None
    confidence: str | None

    market_price_sol: float | None
    quantity: float | None
    value_sol: float | None

    signal_snapshot: dict | None

    created_at: datetime


class PaperAutopilotDashboardResponse(
    BaseModel
):
    account: PaperAccountResponse

    summary: (
        PaperAccountSummaryResponse
    )

    policy: (
        PaperAutopilotPolicyResponse
    )

    runs: list[
        PaperAutopilotRunResponse
    ]

    decisions: list[
        PaperAutopilotDecisionResponse
    ]

    managed_positions: list[
        PaperAutopilotManagedPositionResponse
    ]


class PaperAutopilotExecutionResponse(
    BaseModel
):
    account: PaperAccountResponse

    summary: (
        PaperAccountSummaryResponse
    )

    policy: (
        PaperAutopilotPolicyResponse
    )

    run: PaperAutopilotRunResponse

    decisions: list[
        PaperAutopilotDecisionResponse
    ]

    managed_positions: list[
        PaperAutopilotManagedPositionResponse
    ]


class PaperAutopilotAutomationItemResponse(
    BaseModel
):
    account_id: int
    success: bool

    run: (
        PaperAutopilotRunResponse
        | None
    ) = None

    error_code: str | None = None
    error_message: str | None = None


class PaperAutopilotAutomationResponse(
    BaseModel
):
    processed_accounts: int
    successful_runs: int
    failed_runs: int

    results: list[
        PaperAutopilotAutomationItemResponse
    ] 