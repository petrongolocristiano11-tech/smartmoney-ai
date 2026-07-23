from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CandidateBacktestRequest(BaseModel):
    wallet_address: str = Field(min_length=32, max_length=64)
    lookback_days: int = Field(default=30, ge=1, le=90)
    warmup_days: int = Field(default=14, ge=0, le=60)
    starting_capital_sol: float = Field(default=1.0, gt=0, le=1000)
    fixed_buy_size_sol: float = Field(default=0.05, gt=0, le=100)
    slippage_bps: int = Field(default=100, ge=0, le=1000)
    fee_bps: int = Field(default=10, ge=0, le=500)
    copy_delay_seconds: int = Field(default=8, ge=0, le=3600)
    delay_penalty_bps_per_minute: float = Field(default=25.0, ge=0, le=500)
    max_open_positions: int = Field(default=5, ge=1, le=50)
    check_jupiter: bool = True
    jupiter_token_limit: int = Field(default=10, ge=1, le=20)
    jupiter_cache_ttl_hours: int = Field(default=6, ge=1, le=24)
    force_jupiter_refresh: bool = False

    @field_validator("wallet_address")
    @classmethod
    def normalize_wallet(cls, value: str) -> str:
        wallet = str(value or "").strip()
        if not 32 <= len(wallet) <= 64:
            raise ValueError("Wallet address non valido")
        return wallet


class CandidateBacktestResponse(BaseModel):
    id: int
    run_id: str
    wallet_address: str
    status: str
    decision: str
    score: float
    reasons: list[str]
    parameters: dict
    safety: dict

    source_trades: int
    warmup_source_trades: int
    analysis_source_trades: int
    bootstrap_positions: int
    bootstrap_positions_closed: int
    valid_priced_trades: int
    buy_signals: int
    sell_signals: int
    executed_buys: int
    completed_positions: int
    winning_positions: int
    losing_positions: int
    breakeven_positions: int
    open_positions: int
    skipped_invalid: int
    skipped_existing_position: int
    skipped_max_positions: int
    skipped_insufficient_capital: int
    unmatched_sells: int
    unique_tokens: int

    starting_capital_sol: float
    effective_starting_equity_sol: float
    ending_equity_sol: float
    realized_pnl_sol: float
    unrealized_pnl_sol: float
    net_pnl_sol: float
    total_return_percent: float
    win_rate_percent: float
    profit_factor: float | None
    max_drawdown_percent: float
    execution_coverage_percent: float
    matched_sell_ratio_percent: float
    open_position_ratio_percent: float
    history_span_days: float
    history_oldest_at: datetime | None
    history_newest_at: datetime | None
    data_sufficient: bool
    data_sufficiency_score: float
    data_sufficiency_reasons: list[str]

    jupiter_checked: bool
    jupiter_status: str
    jupiter_tokens_checked: int
    jupiter_tokens_compatible: int
    jupiter_requests: int
    jupiter_cache_hits: int
    jupiter_live_checks: int
    jupiter_compatibility_percent: float
    jupiter_results: list[dict]
    position_results: list[dict]

    started_at: datetime
    completed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CandidateReconstructionAuditRequest(BaseModel):
    wallet_address: str = Field(
        min_length=32,
        max_length=64,
    )
    lookback_days: int = Field(
        default=14,
        ge=1,
        le=90,
    )
    warmup_days: int = Field(
        default=14,
        ge=0,
        le=60,
    )
    fixed_buy_size_sol: float = Field(
        default=0.05,
        gt=0,
        le=100,
    )
    slippage_bps: int = Field(
        default=100,
        ge=0,
        le=1000,
    )
    fee_bps: int = Field(
        default=10,
        ge=0,
        le=500,
    )
    copy_delay_seconds: int = Field(
        default=8,
        ge=0,
        le=3600,
    )
    delay_penalty_bps_per_minute: float = Field(
        default=25.0,
        ge=0,
        le=500,
    )
    baseline_starting_capital_sol: float = Field(
        default=1.0,
        gt=0,
        le=1000,
    )
    baseline_max_open_positions: int = Field(
        default=5,
        ge=1,
        le=50,
    )
    max_excluded_trades: int = Field(
        default=500,
        ge=0,
        le=2000,
    )

    @field_validator("wallet_address")
    @classmethod
    def normalize_wallet(cls, value: str) -> str:
        wallet = str(value or "").strip()

        if not 32 <= len(wallet) <= 64:
            raise ValueError(
                "Wallet address non valido"
            )

        return wallet


class CandidateReconstructionAuditResponse(BaseModel):
    id: int
    run_id: str
    wallet_address: str
    status: str
    parameters: dict
    safety: dict
    baseline_metrics: dict
    exclusion_summary: dict
    excluded_trades: list[dict]
    scenario_results: list[dict]
    diagnoses: list[str]
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True
    )


class CandidatePositionLifecycleAuditRequest(
    BaseModel
):
    wallet_address: str = Field(
        min_length=32,
        max_length=64,
    )
    lookback_days: int = Field(
        default=14,
        ge=1,
        le=90,
    )
    warmup_days: int = Field(
        default=14,
        ge=0,
        le=60,
    )
    starting_capital_sol: float = Field(
        default=1.0,
        gt=0,
        le=1000,
    )
    fixed_buy_size_sol: float = Field(
        default=0.05,
        gt=0,
        le=100,
    )
    slippage_bps: int = Field(
        default=100,
        ge=0,
        le=1000,
    )
    fee_bps: int = Field(
        default=10,
        ge=0,
        le=500,
    )
    copy_delay_seconds: int = Field(
        default=8,
        ge=0,
        le=3600,
    )
    delay_penalty_bps_per_minute: float = Field(
        default=25.0,
        ge=0,
        le=500,
    )
    max_open_positions: int = Field(
        default=5,
        ge=1,
        le=50,
    )
    max_position_details: int = Field(
        default=200,
        ge=1,
        le=1000,
    )

    @field_validator("wallet_address")
    @classmethod
    def normalize_wallet(
        cls,
        value: str,
    ) -> str:
        wallet = str(value or "").strip()

        if not 32 <= len(wallet) <= 64:
            raise ValueError(
                "Wallet address non valido"
            )

        return wallet


class CandidatePositionLifecycleAuditResponse(
    BaseModel
):
    id: int
    run_id: str
    wallet_address: str
    status: str
    parameters: dict
    safety: dict
    baseline_metrics: dict
    lifecycle_summary: dict
    position_details: list[dict]
    scenario_results: list[dict]
    diagnoses: list[str]
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(
        from_attributes=True
    )


class CandidateExitPriceAuditRequest(BaseModel):
    wallet_address: str = Field(min_length=32, max_length=64)
    max_local_price_age_hours: int = Field(default=24, ge=1, le=720)

    @field_validator("wallet_address")
    @classmethod
    def normalize_wallet(cls, value: str) -> str:
        wallet = str(value or "").strip()
        if not 32 <= len(wallet) <= 64:
            raise ValueError("Wallet address non valido")
        return wallet


class CandidateExitPriceAuditResponse(BaseModel):
    id: int
    run_id: str
    wallet_address: str
    status: str
    readiness_status: str
    readiness_score: int
    parameters: dict
    safety: dict
    summary: dict
    scenario_results: list[dict]
    position_results: list[dict]
    diagnoses: list[str]
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CandidateHistoryBackfillRequest(BaseModel):
    wallet_address: str = Field(min_length=32, max_length=64)
    lookback_days: int = Field(default=30, ge=7, le=90)
    max_helius_requests: int = Field(default=5, ge=1, le=20)
    page_size: int = Field(default=100, ge=10, le=100)
    force: bool = False

    @field_validator("wallet_address")
    @classmethod
    def normalize_wallet(cls, value: str) -> str:
        wallet = str(value or "").strip()
        if not 32 <= len(wallet) <= 64:
            raise ValueError("Wallet address non valido")
        return wallet


class CandidateHistoryBackfillResponse(BaseModel):
    id: int
    run_id: str
    wallet_address: str
    status: str
    stop_reason: str
    error_code: str | None
    error_message: str | None

    requested_lookback_days: int
    page_size: int
    request_budget: int
    helius_requests: int
    pages_fetched: int
    transactions_found: int
    swaps_found: int
    trades_imported: int
    trades_updated: int
    parse_failures: int
    duplicate_transactions: int

    oldest_transaction_at: datetime | None
    newest_transaction_at: datetime | None
    next_before_signature: str | None
    parameters: dict
    safety: dict

    started_at: datetime
    completed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
