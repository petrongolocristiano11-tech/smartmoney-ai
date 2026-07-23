from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.app.database.base import Base


class DiscoveredWallet(Base):
    __tablename__ = "discovered_wallets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    wallet_address: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    discovered_from_token: Mapped[str | None] = mapped_column(String(64), nullable=True)

    smart_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    ranking_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    roi_percent: Mapped[float] = mapped_column(Float, default=0.0)
    win_rate_percent: Mapped[float] = mapped_column(Float, default=0.0)
    profit_loss_sol: Mapped[float] = mapped_column(Float, default=0.0)
    reliable_positions: Mapped[int] = mapped_column(Integer, default=0)

    last_swap_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    swaps_24h: Mapped[int] = mapped_column(Integer, default=0)
    swaps_7d: Mapped[int] = mapped_column(Integer, default=0)
    buys_24h: Mapped[int] = mapped_column(Integer, default=0)
    sells_24h: Mapped[int] = mapped_column(Integer, default=0)
    buys_7d: Mapped[int] = mapped_column(Integer, default=0)
    sells_7d: Mapped[int] = mapped_column(Integer, default=0)
    volume_24h_sol: Mapped[float] = mapped_column(Float, default=0.0)
    volume_7d_sol: Mapped[float] = mapped_column(Float, default=0.0)
    active_days_7d: Mapped[int] = mapped_column(Integer, default=0)
    average_swaps_per_active_day_7d: Mapped[float] = mapped_column(Float, default=0.0)
    average_minutes_between_swaps_7d: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    activity_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    activity_classification: Mapped[str] = mapped_column(
        String(24),
        default="NON_ANALIZZATO",
        index=True,
    )
    activity_eligible: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    activity_reasons: Mapped[list] = mapped_column(JSON, default=list)
    activity_calculated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    quality_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    quality_classification: Mapped[str] = mapped_column(
        String(24),
        default="NON_ANALIZZATO",
        index=True,
    )
    quality_eligible: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        index=True,
    )
    quality_reasons: Mapped[list] = mapped_column(JSON, default=list)
    quality_calculated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    quality_sample_swaps_7d: Mapped[int] = mapped_column(Integer, default=0)
    meaningful_swaps_7d: Mapped[int] = mapped_column(Integer, default=0)
    dust_swaps_7d: Mapped[int] = mapped_column(Integer, default=0)
    dust_ratio_7d: Mapped[float] = mapped_column(Float, default=0.0)
    average_swap_sol_7d: Mapped[float] = mapped_column(Float, default=0.0)
    median_swap_sol_7d: Mapped[float] = mapped_column(Float, default=0.0)
    size_compatible_swaps_7d: Mapped[int] = mapped_column(Integer, default=0)
    size_compatibility_ratio_7d: Mapped[float] = mapped_column(Float, default=0.0)
    average_size_compatibility_score_7d: Mapped[float] = mapped_column(
        Float,
        default=0.0,
    )
    buy_sell_balance_score_7d: Mapped[float] = mapped_column(Float, default=0.0)
    unique_tokens_7d: Mapped[int] = mapped_column(Integer, default=0)
    top_token_concentration_7d: Mapped[float] = mapped_column(Float, default=0.0)
    completed_token_pairs_7d: Mapped[int] = mapped_column(Integer, default=0)
    round_trip_token_ratio_7d: Mapped[float] = mapped_column(Float, default=0.0)
    invalid_amount_swaps_7d: Mapped[int] = mapped_column(Integer, default=0)

    hydration_status: Mapped[str] = mapped_column(
        String(24),
        default="NEVER",
        index=True,
    )
    hydration_run_id: Mapped[str | None] = mapped_column(
        String(36),
        nullable=True,
    )
    hydration_last_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    hydration_last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    hydration_lookback_days: Mapped[int] = mapped_column(Integer, default=0)
    hydration_transactions_found: Mapped[int] = mapped_column(Integer, default=0)
    hydration_swaps_found: Mapped[int] = mapped_column(Integer, default=0)
    hydration_trades_imported: Mapped[int] = mapped_column(Integer, default=0)
    hydration_trades_updated: Mapped[int] = mapped_column(Integer, default=0)
    hydration_parse_failures: Mapped[int] = mapped_column(Integer, default=0)
    hydration_helius_requests: Mapped[int] = mapped_column(Integer, default=0)
    hydration_error_code: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
    )
    hydration_error_message: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    promotion_status: Mapped[str] = mapped_column(
        String(24),
        default="NON_ANALIZZATO",
        index=True,
    )
    promotion_eligible: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        index=True,
    )
    promotion_reasons: Mapped[list] = mapped_column(JSON, default=list)
    promotion_calculated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    latest_backtest_run_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True
    )
    backtest_score: Mapped[float] = mapped_column(Float, default=0.0)
    backtest_total_return_percent: Mapped[float] = mapped_column(Float, default=0.0)
    backtest_net_pnl_sol: Mapped[float] = mapped_column(Float, default=0.0)
    backtest_win_rate_percent: Mapped[float] = mapped_column(Float, default=0.0)
    backtest_profit_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    backtest_max_drawdown_percent: Mapped[float] = mapped_column(Float, default=0.0)
    backtest_completed_positions: Mapped[int] = mapped_column(Integer, default=0)
    backtest_open_positions: Mapped[int] = mapped_column(Integer, default=0)
    backtest_execution_coverage_percent: Mapped[float] = mapped_column(Float, default=0.0)
    backtest_jupiter_status: Mapped[str] = mapped_column(
        String(24), default="NOT_CHECKED"
    )
    backtest_jupiter_compatibility_percent: Mapped[float] = mapped_column(
        Float, default=0.0
    )

    eligible: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    eligibility_reasons: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="DISCOVERED")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
