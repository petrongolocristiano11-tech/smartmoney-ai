from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PlatformResponseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LivePlatformConfigUpdateRequest(BaseModel):
    analytics_starting_equity_sol: float | None = Field(default=None, gt=0)
    auto_wallet_selection_enabled: bool | None = None
    max_source_wallets: int | None = Field(default=None, ge=1, le=50)
    min_wallet_smart_score: float | None = Field(default=None, ge=0, le=100)
    min_wallet_closed_trades: int | None = Field(default=None, ge=1, le=100)

    token_safety_enabled: bool | None = None
    token_safety_fail_closed: bool | None = None
    token_allowlist_mode: bool | None = None
    token_allowlist: list[str] | None = None
    token_blocklist: list[str] | None = None
    min_token_liquidity_usd: float | None = Field(default=None, ge=0)
    min_token_market_cap_usd: float | None = Field(default=None, ge=0)
    min_token_volume_24h_usd: float | None = Field(default=None, ge=0)
    max_top_holder_percent: float | None = Field(default=None, ge=0, le=100)
    max_token_risk_score: int | None = Field(default=None, ge=0, le=100)
    require_rugcheck_pass: bool | None = None
    reject_honeypot: bool | None = None
    require_disabled_mint_authority: bool | None = None
    require_disabled_freeze_authority: bool | None = None
    safety_snapshot_max_age_seconds: int | None = Field(default=None, ge=30, le=86400)
    live_arm_ttl_minutes: int | None = Field(default=None, ge=1, le=60)

    @field_validator("token_allowlist", "token_blocklist")
    @classmethod
    def validate_mints(cls, values: list[str] | None):
        if values is None:
            return None
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            mint = str(value or "").strip()
            if not mint:
                continue
            if not 32 <= len(mint) <= 44:
                raise ValueError(f"Token mint non valido: {mint}")
            if mint not in seen:
                result.append(mint)
                seen.add(mint)
        return result

    @model_validator(mode="after")
    def validate_lists(self):
        if self.token_allowlist is not None and self.token_blocklist is not None:
            overlap = set(self.token_allowlist).intersection(self.token_blocklist)
            if overlap:
                raise ValueError("Allowlist e blocklist non possono contenere gli stessi token.")
        return self


class LivePlatformConfigResponse(PlatformResponseModel):
    id: int
    name: str
    analytics_starting_equity_sol: float
    auto_wallet_selection_enabled: bool
    max_source_wallets: int
    min_wallet_smart_score: float
    min_wallet_closed_trades: int
    token_safety_enabled: bool
    token_safety_fail_closed: bool
    token_allowlist_mode: bool
    token_allowlist: list[str]
    token_blocklist: list[str]
    min_token_liquidity_usd: float
    min_token_market_cap_usd: float
    min_token_volume_24h_usd: float
    max_top_holder_percent: float
    max_token_risk_score: int
    require_rugcheck_pass: bool
    reject_honeypot: bool
    require_disabled_mint_authority: bool
    require_disabled_freeze_authority: bool
    safety_snapshot_max_age_seconds: int
    live_arm_ttl_minutes: int
    live_armed_until: datetime | None
    created_at: datetime
    updated_at: datetime


class AnalyticsWindow(PlatformResponseModel):
    days: int
    started_at: datetime
    finished_at: datetime


class LiveAnalyticsSummary(PlatformResponseModel):
    orders_total: int
    orders_completed: int
    buy_orders: int
    sell_orders: int
    open_positions: int
    closed_positions: int
    open_exposure_sol: float
    invested_sol: float
    net_realized_pnl_sol: float
    roi_percent: float
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate_percent: float
    gross_profit_sol: float
    gross_loss_sol: float
    profit_factor: float | None
    average_trade_pnl_sol: float
    best_trade_pnl_sol: float
    worst_trade_pnl_sol: float
    max_drawdown_sol: float
    max_drawdown_percent: float
    starting_equity_sol: float
    ending_equity_sol: float


class LiveAnalyticsDaily(PlatformResponseModel):
    date: date
    buys: int
    sells: int
    realized_pnl_sol: float
    cumulative_pnl_sol: float
    equity_sol: float
    drawdown_sol: float
    drawdown_percent: float


class LiveWalletPerformance(PlatformResponseModel):
    source_wallet: str
    orders: int
    buys: int
    sells: int
    wins: int
    losses: int
    realized_pnl_sol: float
    invested_sol: float
    win_rate_percent: float
    roi_percent: float


class LiveTokenPerformance(PlatformResponseModel):
    token_mint: str
    orders: int
    buys: int
    sells: int
    wins: int
    losses: int
    realized_pnl_sol: float
    invested_sol: float
    win_rate_percent: float
    roi_percent: float


class LiveClosedPositionAnalytics(PlatformResponseModel):
    position_id: int
    token_mint: str
    realized_pnl_sol: float
    opened_at: datetime
    closed_at: datetime | None


class LiveTradingAnalyticsResponse(PlatformResponseModel):
    generated_at: datetime
    mode: Literal["DRY_RUN", "LIVE"]
    generation: int
    window: AnalyticsWindow
    summary: LiveAnalyticsSummary
    order_statuses: dict[str, int]
    daily: list[LiveAnalyticsDaily]
    wallet_performance: list[LiveWalletPerformance]
    token_performance: list[LiveTokenPerformance]
    recent_closed_positions: list[LiveClosedPositionAnalytics]


class LiveWalletScoreResponse(PlatformResponseModel):
    id: int
    wallet_address: str
    smart_score: float
    profile_score: float
    live_performance_score: float
    activity_score: float
    activity_classification: str
    quality_score: float
    quality_classification: str
    quality_eligible: bool
    promotion_status: str
    promotion_eligible: bool
    backtest_score: float
    backtest_total_return_percent: float
    backtest_profit_factor: float | None
    backtest_max_drawdown_percent: float
    backtest_jupiter_status: str
    backtest_data_sufficient: bool
    backtest_data_sufficiency_score: float
    last_swap_at: datetime | None
    swaps_24h: int
    swaps_7d: int
    buys_7d: int
    sells_7d: int
    volume_7d_sol: float
    active_days_7d: int
    average_swaps_per_active_day_7d: float
    average_minutes_between_swaps_7d: float | None
    win_rate_percent: float
    roi_percent: float
    realized_pnl_sol: float
    closed_trades: int
    rank: int
    eligible: bool
    reasons: list[str]
    calculated_at: datetime


class LiveWalletRankingResponse(BaseModel):
    count: int
    eligible_count: int
    ranking: list[LiveWalletScoreResponse]


class ApplySmartWalletsRequest(BaseModel):
    confirmation: str
    limit: int | None = Field(default=None, ge=1, le=50)


class ApplySmartWalletsResponse(BaseModel):
    selected_count: int
    source_wallets: list[str]
    policy: Any


class TokenSafetySnapshotResponse(PlatformResponseModel):
    id: int
    token_mint: str
    liquidity_usd: float
    market_cap_usd: float
    volume_24h_usd: float
    top_holder_percent: float
    risk_score: int
    honeypot: bool
    mint_authority_enabled: bool
    freeze_authority_enabled: bool
    rugged: bool | None
    rugcheck_passed: bool | None
    source: str
    reasons: list[str]
    fetched_at: datetime


class TokenSafetyListResponse(BaseModel):
    count: int
    snapshots: list[TokenSafetySnapshotResponse]


class LiveReadinessCheck(BaseModel):
    code: str
    label: str
    passed: bool
    blocking: bool
    message: str


class LiveReadinessResponse(BaseModel):
    ready: bool
    armed: bool
    armed_until: datetime | None
    checks: list[LiveReadinessCheck]


class LiveArmRequest(BaseModel):
    confirmation: str


class LiveArmResponse(BaseModel):
    armed: bool
    armed_until: datetime | None
    readiness: LiveReadinessResponse
