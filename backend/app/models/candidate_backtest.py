from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.app.database.base import Base


class CandidateBacktestRun(Base):
    __tablename__ = "candidate_backtest_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)

    status: Mapped[str] = mapped_column(String(24), default="COMPLETED", index=True)
    decision: Mapped[str] = mapped_column(
        String(24), default="NON_ANALIZZATO", index=True
    )
    score: Mapped[float] = mapped_column(Float, default=0.0)
    reasons: Mapped[list] = mapped_column(JSON, default=list)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    safety: Mapped[dict] = mapped_column(JSON, default=dict)

    source_trades: Mapped[int] = mapped_column(Integer, default=0)
    valid_priced_trades: Mapped[int] = mapped_column(Integer, default=0)
    buy_signals: Mapped[int] = mapped_column(Integer, default=0)
    sell_signals: Mapped[int] = mapped_column(Integer, default=0)
    executed_buys: Mapped[int] = mapped_column(Integer, default=0)
    completed_positions: Mapped[int] = mapped_column(Integer, default=0)
    winning_positions: Mapped[int] = mapped_column(Integer, default=0)
    losing_positions: Mapped[int] = mapped_column(Integer, default=0)
    breakeven_positions: Mapped[int] = mapped_column(Integer, default=0)
    open_positions: Mapped[int] = mapped_column(Integer, default=0)
    skipped_invalid: Mapped[int] = mapped_column(Integer, default=0)
    skipped_existing_position: Mapped[int] = mapped_column(Integer, default=0)
    skipped_max_positions: Mapped[int] = mapped_column(Integer, default=0)
    skipped_insufficient_capital: Mapped[int] = mapped_column(Integer, default=0)
    unmatched_sells: Mapped[int] = mapped_column(Integer, default=0)
    unique_tokens: Mapped[int] = mapped_column(Integer, default=0)

    starting_capital_sol: Mapped[float] = mapped_column(Float, default=0.0)
    ending_equity_sol: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl_sol: Mapped[float] = mapped_column(Float, default=0.0)
    unrealized_pnl_sol: Mapped[float] = mapped_column(Float, default=0.0)
    net_pnl_sol: Mapped[float] = mapped_column(Float, default=0.0)
    total_return_percent: Mapped[float] = mapped_column(Float, default=0.0)
    win_rate_percent: Mapped[float] = mapped_column(Float, default=0.0)
    profit_factor: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown_percent: Mapped[float] = mapped_column(Float, default=0.0)
    execution_coverage_percent: Mapped[float] = mapped_column(Float, default=0.0)

    jupiter_checked: Mapped[bool] = mapped_column(Boolean, default=False)
    jupiter_status: Mapped[str] = mapped_column(String(24), default="NOT_CHECKED")
    jupiter_tokens_checked: Mapped[int] = mapped_column(Integer, default=0)
    jupiter_tokens_compatible: Mapped[int] = mapped_column(Integer, default=0)
    jupiter_requests: Mapped[int] = mapped_column(Integer, default=0)
    jupiter_compatibility_percent: Mapped[float] = mapped_column(Float, default=0.0)
    jupiter_results: Mapped[list] = mapped_column(JSON, default=list)
    position_results: Mapped[list] = mapped_column(JSON, default=list)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
