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
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.app.database.base import Base


class LivePlatformConfig(Base):
    __tablename__ = "live_platform_configs"

    __table_args__ = (
        CheckConstraint(
            "max_source_wallets BETWEEN 1 AND 50",
            name="ck_live_platform_max_source_wallets",
        ),
        CheckConstraint(
            "min_wallet_smart_score BETWEEN 0 AND 100",
            name="ck_live_platform_min_wallet_score",
        ),
        CheckConstraint(
            "min_wallet_closed_trades BETWEEN 1 AND 100",
            name="ck_live_platform_min_wallet_sample",
        ),
        CheckConstraint(
            "max_top_holder_percent BETWEEN 0 AND 100",
            name="ck_live_platform_max_holder",
        ),
        CheckConstraint(
            "max_token_risk_score BETWEEN 0 AND 100",
            name="ck_live_platform_max_risk",
        ),
        CheckConstraint(
            "live_arm_ttl_minutes BETWEEN 1 AND 60",
            name="ck_live_platform_arm_ttl",
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

    analytics_starting_equity_sol: Mapped[float] = mapped_column(
        Float,
        default=1.0,
    )

    auto_wallet_selection_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )

    max_source_wallets: Mapped[int] = mapped_column(
        Integer,
        default=20,
    )

    min_wallet_smart_score: Mapped[float] = mapped_column(
        Float,
        default=60.0,
    )

    min_wallet_closed_trades: Mapped[int] = mapped_column(
        Integer,
        default=3,
    )

    token_safety_enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )

    token_safety_fail_closed: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
    )

    token_allowlist_mode: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )

    token_allowlist: Mapped[list] = mapped_column(
        JSON,
        default=list,
    )

    token_blocklist: Mapped[list] = mapped_column(
        JSON,
        default=list,
    )

    min_token_liquidity_usd: Mapped[float] = mapped_column(
        Float,
        default=10_000.0,
    )

    min_token_market_cap_usd: Mapped[float] = mapped_column(
        Float,
        default=0.0,
    )

    min_token_volume_24h_usd: Mapped[float] = mapped_column(
        Float,
        default=5_000.0,
    )

    max_top_holder_percent: Mapped[float] = mapped_column(
        Float,
        default=35.0,
    )

    max_token_risk_score: Mapped[int] = mapped_column(
        Integer,
        default=60,
    )

    require_rugcheck_pass: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )

    reject_honeypot: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
    )

    require_disabled_mint_authority: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )

    require_disabled_freeze_authority: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
    )

    safety_snapshot_max_age_seconds: Mapped[int] = mapped_column(
        Integer,
        default=300,
    )

    live_arm_ttl_minutes: Mapped[int] = mapped_column(
        Integer,
        default=15,
    )

    live_armed_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
