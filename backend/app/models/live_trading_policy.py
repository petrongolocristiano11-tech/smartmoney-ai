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