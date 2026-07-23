from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DiscoveredWalletResponse(BaseModel):
    id: int
    wallet_address: str
    discovered_from_token: str | None

    smart_score: float
    ranking_score: float
    roi_percent: float
    win_rate_percent: float
    profit_loss_sol: float
    reliable_positions: int

    last_swap_at: datetime | None
    swaps_24h: int
    swaps_7d: int
    buys_24h: int
    sells_24h: int
    buys_7d: int
    sells_7d: int
    volume_24h_sol: float
    volume_7d_sol: float
    active_days_7d: int
    average_swaps_per_active_day_7d: float
    average_minutes_between_swaps_7d: float | None
    activity_score: float
    activity_classification: str
    activity_eligible: bool
    activity_reasons: list[str]
    activity_calculated_at: datetime | None

    quality_score: float
    quality_classification: str
    quality_eligible: bool
    quality_reasons: list[str]
    quality_calculated_at: datetime | None
    quality_sample_swaps_7d: int
    meaningful_swaps_7d: int
    dust_swaps_7d: int
    dust_ratio_7d: float
    average_swap_sol_7d: float
    median_swap_sol_7d: float
    size_compatible_swaps_7d: int
    size_compatibility_ratio_7d: float
    average_size_compatibility_score_7d: float
    buy_sell_balance_score_7d: float
    unique_tokens_7d: int
    top_token_concentration_7d: float
    completed_token_pairs_7d: int
    round_trip_token_ratio_7d: float
    invalid_amount_swaps_7d: int

    hydration_status: str
    hydration_run_id: str | None
    hydration_last_attempt_at: datetime | None
    hydration_last_success_at: datetime | None
    hydration_lookback_days: int
    hydration_transactions_found: int
    hydration_swaps_found: int
    hydration_trades_imported: int
    hydration_trades_updated: int
    hydration_parse_failures: int
    hydration_helius_requests: int
    hydration_error_code: str | None
    hydration_error_message: str | None

    extended_history_status: str
    extended_history_run_id: str | None
    extended_history_last_attempt_at: datetime | None
    extended_history_last_success_at: datetime | None
    extended_history_lookback_days: int
    extended_history_request_budget: int
    extended_history_helius_requests: int
    extended_history_pages_fetched: int
    extended_history_transactions_found: int
    extended_history_swaps_found: int
    extended_history_trades_imported: int
    extended_history_trades_updated: int
    extended_history_parse_failures: int
    extended_history_oldest_at: datetime | None
    extended_history_newest_at: datetime | None
    extended_history_stop_reason: str | None
    extended_history_error_code: str | None
    extended_history_error_message: str | None

    promotion_status: str
    promotion_eligible: bool
    promotion_reasons: list[str]
    promotion_calculated_at: datetime | None
    latest_backtest_run_id: str | None
    backtest_score: float
    backtest_total_return_percent: float
    backtest_net_pnl_sol: float
    backtest_win_rate_percent: float
    backtest_profit_factor: float | None
    backtest_max_drawdown_percent: float
    backtest_completed_positions: int
    backtest_open_positions: int
    backtest_execution_coverage_percent: float
    backtest_jupiter_status: str
    backtest_jupiter_compatibility_percent: float
    backtest_data_sufficient: bool
    backtest_data_sufficiency_score: float
    backtest_data_sufficiency_reasons: list[str]
    backtest_history_span_days: float
    backtest_bootstrap_positions: int
    backtest_matched_sell_ratio_percent: float

    exit_price_coverage_status: str
    exit_price_coverage_score: float
    exit_price_local_observable_percent: float
    exit_price_current_route_percent: float
    exit_price_temporal_execution_percent: float
    exit_price_audit_reasons: list[str]
    latest_exit_price_audit_run_id: str | None
    exit_price_audit_calculated_at: datetime | None
    exitability_gate_status: str
    exitability_gate_score: float
    exitability_gate_eligible: bool
    exitability_gate_reasons: list[str]
    exitability_gate_calculated_at: datetime | None
    discovery_funnel_status: str
    discovery_funnel_score: float
    discovery_funnel_priority: int
    discovery_funnel_action: str
    discovery_funnel_reasons: list[str]
    discovery_funnel_history_budget: int
    discovery_funnel_calculated_at: datetime | None

    eligible: bool
    eligibility_reasons: list[str]
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DiscoveredWalletActivityRefreshResponse(BaseModel):
    status: str
    wallets_refreshed: int
    helius_requests: int
    message: str


class DiscoveredWalletQualityRefreshResponse(BaseModel):
    status: str
    wallets_refreshed: int
    helius_requests: int
    copyable: int
    observation: int
    suspicious: int
    not_copyable: int
    not_analyzed: int
    message: str


class DiscoveryHydrationWalletResult(BaseModel):
    wallet_address: str
    status: str
    helius_requests: int
    helius_attempts_reported: int
    transactions_found: int
    swaps_found: int
    trades_imported: int
    trades_updated: int
    parse_failures: int
    activity_classification: str
    activity_score: float
    quality_classification: str
    quality_score: float
    quality_eligible: bool
    eligible: bool
    error_code: str | None
    error_message: str | None


class DiscoveryHydrationResponse(BaseModel):
    status: str
    run_id: str
    started_at: datetime
    completed_at: datetime
    requested_max_wallets: int
    effective_max_wallets: int
    request_budget: int
    helius_requests: int
    retry_attempts_enabled: bool
    lookback_days: int
    transaction_limit_per_wallet: int
    minimum_smart_score: float
    force: bool
    wallets_selected: int
    wallets_attempted: int
    wallets_completed: int
    wallets_empty: int
    wallets_partial: int
    wallets_failed: int
    wallets_skipped_cooldown: int
    swaps_found: int
    trades_imported: int
    trades_updated: int
    parse_failures: int
    activity_breakdown: dict[str, int]
    quality_breakdown: dict[str, int]
    results: list[DiscoveryHydrationWalletResult]
    safety: dict[str, bool]

class CandidateExitabilityGateResponse(BaseModel):
    id: int
    run_id: str
    status: str
    parameters: dict
    safety: dict
    summary: dict
    wallet_results: list[dict]
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)

class CandidateDiscoveryFunnelResponse(BaseModel):
    id: int
    run_id: str
    status: str
    parameters: dict
    safety: dict
    summary: dict
    wallet_results: list[dict]
    history_queue: list[dict]
    started_at: datetime
    completed_at: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
