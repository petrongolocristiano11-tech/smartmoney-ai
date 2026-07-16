from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)
from sqlalchemy.sql import func

from backend.app.database.base import Base


DEFAULT_BLOCKED_RISK_FLAGS = [
    "HIGH_RISK_WALLETS",
    "HIGH_VOLUME_CONCENTRATION",
    "NEGATIVE_AVERAGE_ROI",
    "STALE_ACTIVITY",
    "LOW_EVIDENCE",
]

DEFAULT_EXCLUDED_TOKEN_MINTS = [
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
]


class PaperAutopilotPolicy(Base):
    __tablename__ = (
        "paper_autopilot_policies"
    )

    __table_args__ = (
        UniqueConstraint(
            "account_id",
            name=(
                "uq_paper_autopilot_"
                "policies_account"
            ),
        ),
        CheckConstraint(
            "status IN "
            "('DISABLED', 'ENABLED', 'PAUSED')",
            name=(
                "ck_paper_autopilot_"
                "policies_status"
            ),
        ),
        CheckConstraint(
            "minimum_confidence IN "
            "('LOW', 'MEDIUM', 'HIGH')",
            name=(
                "ck_paper_autopilot_"
                "policies_confidence"
            ),
        ),
        CheckConstraint(
            "min_signal_score "
            "BETWEEN 0 AND 100",
            name=(
                "ck_paper_autopilot_"
                "min_signal_score"
            ),
        ),
        CheckConstraint(
            "min_evidence_score "
            "BETWEEN 0 AND 100",
            name=(
                "ck_paper_autopilot_"
                "min_evidence_score"
            ),
        ),
        CheckConstraint(
            "min_buyers > 0",
            name=(
                "ck_paper_autopilot_"
                "min_buyers_positive"
            ),
        ),
        CheckConstraint(
            "max_signal_age_hours > 0",
            name=(
                "ck_paper_autopilot_"
                "signal_age_positive"
            ),
        ),
        CheckConstraint(
            "min_smart_volume_share_percent "
            "BETWEEN 0 AND 100",
            name=(
                "ck_paper_autopilot_"
                "smart_volume_share"
            ),
        ),
        CheckConstraint(
            "max_volume_concentration_percent "
            "BETWEEN 0 AND 100",
            name=(
                "ck_paper_autopilot_"
                "volume_concentration"
            ),
        ),
        CheckConstraint(
            "max_signals_per_run > 0",
            name=(
                "ck_paper_autopilot_"
                "signals_per_run"
            ),
        ),
        CheckConstraint(
            "max_entries_per_run > 0",
            name=(
                "ck_paper_autopilot_"
                "entries_per_run"
            ),
        ),
        CheckConstraint(
            "max_entries_per_day > 0",
            name=(
                "ck_paper_autopilot_"
                "entries_per_day"
            ),
        ),
        CheckConstraint(
            "token_cooldown_hours >= 0",
            name=(
                "ck_paper_autopilot_"
                "cooldown_non_negative"
            ),
        ),
        CheckConstraint(
            "max_position_percent_of_equity "
            "> 0 AND "
            "max_position_percent_of_equity "
            "<= 100",
            name=(
                "ck_paper_autopilot_"
                "position_equity_percent"
            ),
        ),
        CheckConstraint(
            "max_total_exposure_percent "
            "> 0 AND "
            "max_total_exposure_percent "
            "<= 100",
            name=(
                "ck_paper_autopilot_"
                "total_exposure_percent"
            ),
        ),
        CheckConstraint(
            "minimum_cash_reserve_percent "
            "BETWEEN 0 AND 100",
            name=(
                "ck_paper_autopilot_"
                "cash_reserve_percent"
            ),
        ),
        CheckConstraint(
            "minimum_order_size_sol > 0",
            name=(
                "ck_paper_autopilot_"
                "minimum_order_positive"
            ),
        ),
        CheckConstraint(
            "stop_loss_percent "
            "> 0 AND "
            "stop_loss_percent <= 100",
            name=(
                "ck_paper_autopilot_"
                "stop_loss_percent"
            ),
        ),
        CheckConstraint(
            "take_profit_percent > 0",
            name=(
                "ck_paper_autopilot_"
                "take_profit_percent"
            ),
        ),
        CheckConstraint(
            "trailing_stop_percent "
            "> 0 AND "
            "trailing_stop_percent <= 100",
            name=(
                "ck_paper_autopilot_"
                "trailing_stop_percent"
            ),
        ),
        CheckConstraint(
            "max_holding_hours > 0",
            name=(
                "ck_paper_autopilot_"
                "max_holding_hours"
            ),
        ),
        CheckConstraint(
            "slippage_percent "
            "BETWEEN 0 AND 50",
            name=(
                "ck_paper_autopilot_"
                "slippage_percent"
            ),
        ),
        CheckConstraint(
            "fee_percent BETWEEN 0 AND 20",
            name=(
                "ck_paper_autopilot_"
                "fee_percent"
            ),
        ),
        CheckConstraint(
            "max_consecutive_errors > 0",
            name=(
                "ck_paper_autopilot_"
                "max_errors_positive"
            ),
        ),
        CheckConstraint(
            "consecutive_errors >= 0",
            name=(
                "ck_paper_autopilot_"
                "errors_non_negative"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey(
            "paper_accounts.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="DISABLED",
        nullable=False,
        index=True,
    )

    # =========================
    # SIGNAL FILTERS
    # =========================

    min_signal_score: Mapped[float] = (
        mapped_column(
            Float,
            default=75.0,
            nullable=False,
        )
    )

    min_evidence_score: Mapped[float] = (
        mapped_column(
            Float,
            default=60.0,
            nullable=False,
        )
    )

    min_buyers: Mapped[int] = mapped_column(
        Integer,
        default=3,
        nullable=False,
    )

    minimum_confidence: Mapped[str] = (
        mapped_column(
            String(20),
            default="HIGH",
            nullable=False,
        )
    )

    max_signal_age_hours: Mapped[float] = (
        mapped_column(
            Float,
            default=24.0,
            nullable=False,
        )
    )

    min_smart_volume_share_percent: (
        Mapped[float]
    ) = mapped_column(
        Float,
        default=60.0,
        nullable=False,
    )

    max_volume_concentration_percent: (
        Mapped[float]
    ) = mapped_column(
        Float,
        default=65.0,
        nullable=False,
    )

    blocked_risk_flags: Mapped[list] = (
        mapped_column(
            JSON,
            default=lambda: list(
                DEFAULT_BLOCKED_RISK_FLAGS
            ),
            nullable=False,
        )
    )

    excluded_token_mints: Mapped[list] = (
        mapped_column(
            JSON,
            default=lambda: list(
                DEFAULT_EXCLUDED_TOKEN_MINTS
            ),
            nullable=False,
        )
    )

    # =========================
    # ENTRY LIMITS
    # =========================

    max_signals_per_run: Mapped[int] = (
        mapped_column(
            Integer,
            default=20,
            nullable=False,
        )
    )

    max_entries_per_run: Mapped[int] = (
        mapped_column(
            Integer,
            default=1,
            nullable=False,
        )
    )

    max_entries_per_day: Mapped[int] = (
        mapped_column(
            Integer,
            default=3,
            nullable=False,
        )
    )

    token_cooldown_hours: Mapped[int] = (
        mapped_column(
            Integer,
            default=72,
            nullable=False,
        )
    )

    # =========================
    # CAPITAL ALLOCATION
    # =========================

    max_position_percent_of_equity: (
        Mapped[float]
    ) = mapped_column(
        Float,
        default=5.0,
        nullable=False,
    )

    max_total_exposure_percent: (
        Mapped[float]
    ) = mapped_column(
        Float,
        default=40.0,
        nullable=False,
    )

    minimum_cash_reserve_percent: (
        Mapped[float]
    ) = mapped_column(
        Float,
        default=20.0,
        nullable=False,
    )

    minimum_order_size_sol: Mapped[float] = (
        mapped_column(
            Float,
            default=0.02,
            nullable=False,
        )
    )

    # =========================
    # EXIT MANAGEMENT
    # =========================

    stop_loss_percent: Mapped[float] = (
        mapped_column(
            Float,
            default=12.0,
            nullable=False,
        )
    )

    take_profit_percent: Mapped[float] = (
        mapped_column(
            Float,
            default=25.0,
            nullable=False,
        )
    )

    trailing_stop_enabled: Mapped[bool] = (
        mapped_column(
            Boolean,
            default=True,
            nullable=False,
        )
    )

    trailing_stop_percent: Mapped[float] = (
        mapped_column(
            Float,
            default=8.0,
            nullable=False,
        )
    )

    max_holding_hours: Mapped[int] = (
        mapped_column(
            Integer,
            default=72,
            nullable=False,
        )
    )

    # =========================
    # EXECUTION
    # =========================

    slippage_percent: Mapped[float] = (
        mapped_column(
            Float,
            default=0.5,
            nullable=False,
        )
    )

    fee_percent: Mapped[float] = (
        mapped_column(
            Float,
            default=0.25,
            nullable=False,
        )
    )

    # =========================
    # FAILURE PROTECTION
    # =========================

    max_consecutive_errors: Mapped[int] = (
        mapped_column(
            Integer,
            default=3,
            nullable=False,
        )
    )

    consecutive_errors: Mapped[int] = (
        mapped_column(
            Integer,
            default=0,
            nullable=False,
        )
    )

    paused_reason: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    last_run_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_error_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        )
    )

    updated_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )
    )


class PaperAutopilotRun(Base):
    __tablename__ = "paper_autopilot_runs"

    __table_args__ = (
        CheckConstraint(
            "trigger IN "
            "('MANUAL', 'AUTOMATION')",
            name=(
                "ck_paper_autopilot_"
                "runs_trigger"
            ),
        ),
        CheckConstraint(
            "status IN "
            "('RUNNING', 'COMPLETED', "
            "'PARTIAL', 'FAILED', 'SKIPPED')",
            name=(
                "ck_paper_autopilot_"
                "runs_status"
            ),
        ),
        CheckConstraint(
            "signals_evaluated >= 0",
            name=(
                "ck_paper_autopilot_"
                "signals_evaluated"
            ),
        ),
        CheckConstraint(
            "entries_opened >= 0",
            name=(
                "ck_paper_autopilot_"
                "entries_opened"
            ),
        ),
        CheckConstraint(
            "exits_closed >= 0",
            name=(
                "ck_paper_autopilot_"
                "exits_closed"
            ),
        ),
        CheckConstraint(
            "decisions_count >= 0",
            name=(
                "ck_paper_autopilot_"
                "decisions_count"
            ),
        ),
        CheckConstraint(
            "errors_count >= 0",
            name=(
                "ck_paper_autopilot_"
                "errors_count"
            ),
        ),
        Index(
            "ix_paper_autopilot_runs_"
            "account_started",
            "account_id",
            "started_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey(
            "paper_accounts.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    policy_id: Mapped[int] = mapped_column(
        ForeignKey(
            "paper_autopilot_policies.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    trigger: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="RUNNING",
        nullable=False,
        index=True,
    )

    signals_evaluated: Mapped[int] = (
        mapped_column(
            Integer,
            default=0,
            nullable=False,
        )
    )

    entries_opened: Mapped[int] = (
        mapped_column(
            Integer,
            default=0,
            nullable=False,
        )
    )

    exits_closed: Mapped[int] = (
        mapped_column(
            Integer,
            default=0,
            nullable=False,
        )
    )

    decisions_count: Mapped[int] = (
        mapped_column(
            Integer,
            default=0,
            nullable=False,
        )
    )

    errors_count: Mapped[int] = (
        mapped_column(
            Integer,
            default=0,
            nullable=False,
        )
    )

    error_message: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    started_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
            index=True,
        )
    )

    finished_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        )
    )


class PaperAutopilotManagedPosition(Base):
    __tablename__ = (
        "paper_autopilot_managed_positions"
    )

    __table_args__ = (
        UniqueConstraint(
            "entry_order_id",
            name=(
                "uq_paper_autopilot_"
                "managed_entry_order"
            ),
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'CLOSED')",
            name=(
                "ck_paper_autopilot_"
                "managed_status"
            ),
        ),
        CheckConstraint(
            "entry_price_sol > 0",
            name=(
                "ck_paper_autopilot_"
                "entry_price_positive"
            ),
        ),
        CheckConstraint(
            "peak_price_sol > 0",
            name=(
                "ck_paper_autopilot_"
                "peak_price_positive"
            ),
        ),
        CheckConstraint(
            "stop_loss_price_sol > 0",
            name=(
                "ck_paper_autopilot_"
                "stop_price_positive"
            ),
        ),
        CheckConstraint(
            "take_profit_price_sol > 0",
            name=(
                "ck_paper_autopilot_"
                "take_price_positive"
            ),
        ),
        CheckConstraint(
            "trailing_stop_percent "
            "> 0 AND "
            "trailing_stop_percent <= 100",
            name=(
                "ck_paper_autopilot_"
                "managed_trailing_percent"
            ),
        ),
        Index(
            "ix_paper_autopilot_managed_"
            "account_status",
            "account_id",
            "status",
        ),
        Index(
            "ix_paper_autopilot_managed_"
            "token_status",
            "token_mint",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey(
            "paper_accounts.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    paper_position_id: Mapped[int] = (
        mapped_column(
            ForeignKey(
                "paper_positions.id",
                ondelete="CASCADE",
            ),
            nullable=False,
            index=True,
        )
    )

    entry_order_id: Mapped[int] = (
        mapped_column(
            ForeignKey(
                "paper_orders.id",
                ondelete="CASCADE",
            ),
            nullable=False,
            index=True,
        )
    )

    exit_order_id: Mapped[
        int | None
    ] = mapped_column(
        ForeignKey(
            "paper_orders.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    entry_run_id: Mapped[int] = (
        mapped_column(
            ForeignKey(
                "paper_autopilot_runs.id",
                ondelete="CASCADE",
            ),
            nullable=False,
            index=True,
        )
    )

    exit_run_id: Mapped[
        int | None
    ] = mapped_column(
        ForeignKey(
            "paper_autopilot_runs.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    token_mint: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="ACTIVE",
        nullable=False,
        index=True,
    )

    entry_price_sol: Mapped[float] = (
        mapped_column(
            Float,
            nullable=False,
        )
    )

    peak_price_sol: Mapped[float] = (
        mapped_column(
            Float,
            nullable=False,
        )
    )

    stop_loss_price_sol: Mapped[float] = (
        mapped_column(
            Float,
            nullable=False,
        )
    )

    take_profit_price_sol: Mapped[float] = (
        mapped_column(
            Float,
            nullable=False,
        )
    )

    trailing_stop_enabled: Mapped[bool] = (
        mapped_column(
            Boolean,
            default=True,
            nullable=False,
        )
    )

    trailing_stop_percent: Mapped[float] = (
        mapped_column(
            Float,
            nullable=False,
        )
    )

    entry_signal_score: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    entry_evidence_score: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    entry_confidence: Mapped[
        str | None
    ] = mapped_column(
        String(20),
        nullable=True,
    )

    exit_reason: Mapped[
        str | None
    ] = mapped_column(
        String(80),
        nullable=True,
    )

    max_holding_until: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            nullable=False,
            index=True,
        )
    )

    opened_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        )
    )

    closed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
        )
    )

    updated_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
            nullable=False,
        )
    )


class PaperAutopilotDecision(Base):
    __tablename__ = (
        "paper_autopilot_decisions"
    )

    __table_args__ = (
        CheckConstraint(
            "action IN "
            "('BUY', 'SELL', 'HOLD', "
            "'SKIP', 'ERROR')",
            name=(
                "ck_paper_autopilot_"
                "decisions_action"
            ),
        ),
        Index(
            "ix_paper_autopilot_decisions_"
            "account_created",
            "account_id",
            "created_at",
        ),
        Index(
            "ix_paper_autopilot_decisions_"
            "token_created",
            "token_mint",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    run_id: Mapped[int] = mapped_column(
        ForeignKey(
            "paper_autopilot_runs.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey(
            "paper_accounts.id",
            ondelete="CASCADE",
        ),
        nullable=False,
        index=True,
    )

    managed_position_id: Mapped[
        int | None
    ] = mapped_column(
        ForeignKey(
            "paper_autopilot_managed_positions.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    paper_position_id: Mapped[
        int | None
    ] = mapped_column(
        ForeignKey(
            "paper_positions.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    paper_order_id: Mapped[
        int | None
    ] = mapped_column(
        ForeignKey(
            "paper_orders.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    token_mint: Mapped[
        str | None
    ] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )

    action: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        index=True,
    )

    reason_code: Mapped[str] = (
        mapped_column(
            String(80),
            nullable=False,
            index=True,
        )
    )

    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    signal_score: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    evidence_score: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    buyers: Mapped[
        int | None
    ] = mapped_column(
        Integer,
        nullable=True,
    )

    confidence: Mapped[
        str | None
    ] = mapped_column(
        String(20),
        nullable=True,
    )

    market_price_sol: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    quantity: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    value_sol: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    signal_snapshot: Mapped[
        dict | None
    ] = mapped_column(
        JSON,
        nullable=True,
    )

    created_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            nullable=False,
            index=True,
        )
    ) 