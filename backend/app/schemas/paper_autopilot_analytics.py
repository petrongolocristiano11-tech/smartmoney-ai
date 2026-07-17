from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class AnalyticsResponseModel(BaseModel):
    model_config = ConfigDict(
        from_attributes=True,
    )


class AutopilotAnalyticsWindow(
    AnalyticsResponseModel
):
    days: int
    started_at: datetime
    finished_at: datetime


class AutopilotHealthAnalytics(
    AnalyticsResponseModel
):
    status: str
    policy_status: str
    last_run_status: str | None
    last_run_at: datetime | None
    hours_since_last_run: float | None
    last_error_message: str | None


class AutopilotRunAnalytics(
    AnalyticsResponseModel
):
    total_runs: int
    completed_runs: int
    partial_runs: int
    failed_runs: int
    skipped_runs: int
    running_runs: int
    operational_success_rate_percent: float
    signals_evaluated: int
    entries_opened: int
    exits_closed: int
    decisions_recorded: int
    errors_recorded: int


class AutopilotDecisionAnalytics(
    AnalyticsResponseModel
):
    total_decisions: int
    buy_decisions: int
    sell_decisions: int
    hold_decisions: int
    skip_decisions: int
    error_decisions: int
    entry_acceptance_rate_percent: float


class AutopilotTradingAnalytics(
    AnalyticsResponseModel
):
    closed_trades: int
    winning_trades: int
    losing_trades: int
    breakeven_trades: int
    win_rate_percent: float
    net_realized_pnl_sol: float
    gross_profit_sol: float
    gross_loss_sol: float
    profit_factor: float | None
    average_trade_pnl_sol: float
    best_trade_pnl_sol: float
    worst_trade_pnl_sol: float
    average_holding_hours: float


class AutopilotOpenPositionAnalytics(
    AnalyticsResponseModel
):
    active_managed_positions: int
    cost_basis_sol: float
    market_value_sol: float
    unrealized_pnl_sol: float


class AutopilotBreakdownItem(
    AnalyticsResponseModel
):
    code: str
    count: int
    percentage: float


class AutopilotDailyAnalytics(
    AnalyticsResponseModel
):
    date: date
    runs: int
    entries: int
    exits: int
    decisions: int
    realized_pnl_sol: float
    cumulative_realized_pnl_sol: float


class AutopilotClosedTradeAnalytics(
    AnalyticsResponseModel
):
    managed_position_id: int
    token_mint: str
    exit_reason: str | None
    realized_pnl_sol: float
    return_percent: float | None
    holding_hours: float
    entry_signal_score: float | None
    opened_at: datetime
    closed_at: datetime


class PaperAutopilotAnalyticsResponse(
    AnalyticsResponseModel
):
    account_id: int
    account_name: str
    generated_at: datetime

    window: AutopilotAnalyticsWindow
    health: AutopilotHealthAnalytics
    runs: AutopilotRunAnalytics
    decisions: AutopilotDecisionAnalytics
    trading: AutopilotTradingAnalytics
    open_positions: AutopilotOpenPositionAnalytics

    decision_reasons: list[
        AutopilotBreakdownItem
    ]

    exit_reasons: list[
        AutopilotBreakdownItem
    ]

    daily: list[
        AutopilotDailyAnalytics
    ]

    recent_closed_trades: list[
        AutopilotClosedTradeAnalytics
    ] 