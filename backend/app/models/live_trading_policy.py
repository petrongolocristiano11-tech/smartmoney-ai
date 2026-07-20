from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Integer,
    JSON,
    String,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)
from sqlalchemy.sql import func

from backend.app.database.base import Base


class LiveTradingPolicy(Base):
    __tablename__ = (
        "live_trading_policies"
    )

    __table_args__ = (
        CheckConstraint(
            "mode IN "
            "('DISABLED', 'DRY_RUN', 'LIVE')",
            name=(
                "ck_live_trading_policies_mode"
            ),
        ),
        CheckConstraint(
            "sizing_mode IN "
            "('FIXED', 'SOURCE_PERCENTAGE')",
            name=(
                "ck_live_trading_policies_"
                "sizing_mode"
            ),
        ),
        CheckConstraint(
            "fixed_buy_size_sol > 0",
            name=(
                "ck_live_trading_policies_"
                "fixed_buy_positive"
            ),
        ),
        CheckConstraint(
            "source_trade_percentage > 0 "
            "AND source_trade_percentage <= 100",
            name=(
                "ck_live_trading_policies_"
                "source_percentage"
            ),
        ),
        CheckConstraint(
            "sell_position_percentage > 0 "
            "AND sell_position_percentage <= 100",
            name=(
                "ck_live_trading_policies_"
                "sell_percentage"
            ),
        ),
        CheckConstraint(
            "max_order_size_sol > 0",
            name=(
                "ck_live_trading_policies_"
                "max_order_positive"
            ),
        ),
        CheckConstraint(
            "max_daily_buy_sol > 0",
            name=(
                "ck_live_trading_policies_"
                "daily_buy_positive"
            ),
        ),
        CheckConstraint(
            "max_daily_loss_sol > 0",
            name=(
                "ck_live_trading_policies_"
                "daily_loss_positive"
            ),
        ),
        CheckConstraint(
            "max_total_exposure_sol > 0",
            name=(
                "ck_live_trading_policies_"
                "exposure_positive"
            ),
        ),
        CheckConstraint(
            "min_wallet_reserve_sol >= 0",
            name=(
                "ck_live_trading_policies_"
                "reserve_non_negative"
            ),
        ),
        CheckConstraint(
            "max_slippage_bps "
            "BETWEEN 1 AND 5000",
            name=(
                "ck_live_trading_policies_"
                "slippage_range"
            ),
        ),
        CheckConstraint(
            "max_price_impact_percent > 0 "
            "AND max_price_impact_percent <= 100",
            name=(
                "ck_live_trading_policies_"
                "price_impact_range"
            ),
        ),
        CheckConstraint(
            "min_source_trade_sol >= 0",
            name=(
                "ck_live_trading_policies_"
                "min_source_non_negative"
            ),
        ),
        CheckConstraint(
            "max_source_trade_age_seconds "
            "BETWEEN 1 AND 86400",
            name=(
                "ck_live_trading_policies_"
                "trade_age_range"
            ),
        ),
        CheckConstraint(
            "max_consecutive_failures "
            "BETWEEN 1 AND 100",
            name=(
                "ck_live_trading_policies_"
                "failure_limit_range"
            ),
        ),
        CheckConstraint(
            "consecutive_failures >= 0",
            name=(
                "ck_live_trading_policies_"
                "failures_non_negative"
            ),
        ),
        CheckConstraint(
            "dry_run_generation >= 1",
            name=(
                "ck_live_trading_policies_"
                "dry_run_generation_positive"
            ),
        ),
        CheckConstraint(
            "take_profit_percent > 0 "
            "AND take_profit_percent <= 10000",
            name="ck_live_policy_take_profit",
        ),
        CheckConstraint(
            "stop_loss_percent > 0 "
            "AND stop_loss_percent <= 100",
            name="ck_live_policy_stop_loss",
        ),
        CheckConstraint(
            "trailing_stop_percent > 0 "
            "AND trailing_stop_percent <= 100",
            name="ck_live_policy_trailing_stop",
        ),
        CheckConstraint(
            "max_position_age_minutes BETWEEN 1 AND 525600",
            name="ck_live_policy_position_age",
        ),
        CheckConstraint(
            "auto_exit_position_percentage > 0 "
            "AND auto_exit_position_percentage <= 100",
            name="ck_live_policy_auto_exit_percentage",
        ),
        CheckConstraint(
            "max_open_positions BETWEEN 1 AND 1000",
            name="ck_live_policy_max_open_positions",
        ),
        CheckConstraint(
            "max_token_exposure_sol > 0",
            name="ck_live_policy_token_exposure",
        ),
        CheckConstraint(
            "max_daily_orders BETWEEN 1 AND 10000",
            name="ck_live_policy_daily_orders",
        ),
        CheckConstraint(
            "max_portfolio_drawdown_percent > 0 "
            "AND max_portfolio_drawdown_percent <= 100",
            name="ck_live_policy_drawdown",
        ),
        CheckConstraint(
            "loss_streak_cooldown_threshold BETWEEN 1 AND 100",
            name="ck_live_policy_loss_streak_threshold",
        ),
        CheckConstraint(
            "cooldown_after_loss_minutes BETWEEN 1 AND 10080",
            name="ck_live_policy_cooldown_minutes",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(80),
        unique=True,
        default="default",
        index=True,
    )

    mode: Mapped[str] = mapped_column(
        String(20),
        default="DISABLED",
        index=True,
    )

    kill_switch: Mapped[bool] = (
        mapped_column(
            Boolean,
            default=False,
            index=True,
        )
    )

    stream_execution_enabled: Mapped[
        bool
    ] = mapped_column(
        Boolean,
        default=False,
    )

    source_wallets: Mapped[list] = (
        mapped_column(
            JSON,
            default=list,
        )
    )

    buy_enabled: Mapped[bool] = (
        mapped_column(
            Boolean,
            default=True,
        )
    )

    sell_enabled: Mapped[bool] = (
        mapped_column(
            Boolean,
            default=True,
        )
    )

    sizing_mode: Mapped[str] = (
        mapped_column(
            String(30),
            default="FIXED",
        )
    )

    fixed_buy_size_sol: Mapped[float] = (
        mapped_column(
            Float,
            default=0.05,
        )
    )

    source_trade_percentage: Mapped[
        float
    ] = mapped_column(
        Float,
        default=10.0,
    )

    sell_position_percentage: Mapped[
        float
    ] = mapped_column(
        Float,
        default=100.0,
    )

    max_order_size_sol: Mapped[float] = (
        mapped_column(
            Float,
            default=0.10,
        )
    )

    max_daily_buy_sol: Mapped[float] = (
        mapped_column(
            Float,
            default=0.50,
        )
    )

    max_daily_loss_sol: Mapped[float] = (
        mapped_column(
            Float,
            default=0.20,
        )
    )

    max_total_exposure_sol: Mapped[
        float
    ] = mapped_column(
        Float,
        default=0.50,
    )

    min_wallet_reserve_sol: Mapped[
        float
    ] = mapped_column(
        Float,
        default=0.05,
    )

    max_slippage_bps: Mapped[int] = (
        mapped_column(
            Integer,
            default=300,
        )
    )

    max_price_impact_percent: Mapped[
        float
    ] = mapped_column(
        Float,
        default=5.0,
    )

    min_source_trade_sol: Mapped[
        float
    ] = mapped_column(
        Float,
        default=0.01,
    )

    max_source_trade_age_seconds: Mapped[
        int
    ] = mapped_column(
        Integer,
        default=120,
    )

    max_consecutive_failures: Mapped[
        int
    ] = mapped_column(
        Integer,
        default=3,
    )

    consecutive_failures: Mapped[int] = (
        mapped_column(
            Integer,
            default=0,
        )
    )

    automatic_exits_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        index=True,
    )

    take_profit_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
    )

    take_profit_percent: Mapped[float] = mapped_column(
        Float,
        default=25.0,
    )

    stop_loss_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
    )

    stop_loss_percent: Mapped[float] = mapped_column(
        Float,
        default=15.0,
    )

    trailing_stop_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )

    trailing_stop_percent: Mapped[float] = mapped_column(
        Float,
        default=10.0,
    )

    time_exit_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )

    max_position_age_minutes: Mapped[int] = mapped_column(
        Integer,
        default=1440,
    )

    auto_exit_position_percentage: Mapped[float] = mapped_column(
        Float,
        default=100.0,
    )

    max_open_positions: Mapped[int] = mapped_column(
        Integer,
        default=5,
    )

    max_token_exposure_sol: Mapped[float] = mapped_column(
        Float,
        default=0.10,
    )

    max_daily_orders: Mapped[int] = mapped_column(
        Integer,
        default=50,
    )

    max_portfolio_drawdown_percent: Mapped[float] = mapped_column(
        Float,
        default=20.0,
    )

    loss_streak_cooldown_threshold: Mapped[int] = mapped_column(
        Integer,
        default=3,
    )

    cooldown_after_loss_minutes: Mapped[int] = mapped_column(
        Integer,
        default=30,
    )

    dry_run_generation: Mapped[int] = (
        mapped_column(
            Integer,
            default=1,
        )
    )

    dry_run_started_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
        )
    )

    updated_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
        )
    ) 