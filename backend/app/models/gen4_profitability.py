from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.app.database.base import Base


class CanonicalParserGen4ProfitabilityRun(Base):
    __tablename__ = "canonical_parser_gen4_profitability_runs"
    __table_args__ = (
        CheckConstraint("status IN ('COMPLETED', 'FAILED')", name="ck_gen4_profitability_runs_status"),
        CheckConstraint(
            "verdict IN ('NOT_EVALUABLE', 'NEGATIVE_EVIDENCE', 'PROXY_PROMISING_STRICT_EVIDENCE_MISSING', 'PROMISING_NOT_PROVEN', 'PROFITABLE_EVIDENCE')",
            name="ck_gen4_profitability_runs_verdict",
        ),
        CheckConstraint(
            "strict_evidence_status IN ('INSUFFICIENT', 'EVALUABLE', 'SUFFICIENT')",
            name="ck_gen4_profitability_runs_strict_status",
        ),
        CheckConstraint(
            "source_trade_count >= 0 AND source_wallet_count >= 0 AND source_token_count >= 0 AND window_count >= 0 AND strict_closed_trade_count >= 0 AND proxy_closed_trade_count >= 0",
            name="ck_gen4_profitability_runs_counts",
        ),
        CheckConstraint("length(run_key) = 64", name="ck_gen4_profitability_runs_key_len"),
        CheckConstraint("length(policy_hash) = 64", name="ck_gen4_profitability_runs_policy_hash_len"),
        CheckConstraint("length(report_hash) = 64", name="ck_gen4_profitability_runs_report_hash_len"),
        UniqueConstraint("run_id", name="uq_gen4_profitability_runs_run_id"),
        UniqueConstraint("run_key", name="uq_gen4_profitability_runs_run_key"),
        UniqueConstraint("report_hash", name="uq_gen4_profitability_runs_report_hash"),
        Index("ix_gen4_profitability_runs_verdict_completed", "verdict", "completed_at"),
        Index("ix_gen4_profitability_runs_policy", "policy_hash", "evaluated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    run_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    verdict: Mapped[str] = mapped_column(String(64), nullable=False)
    strict_evidence_status: Mapped[str] = mapped_column(String(32), nullable=False)

    policy_version: Mapped[str] = mapped_column(String(120), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    strict_metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    proxy_metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    baseline_metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    evidence_gaps: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    safety: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    source_trade_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_wallet_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    source_token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    window_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    strict_closed_trade_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    proxy_closed_trade_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    data_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    data_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    report_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    technical_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)


class CanonicalParserGen4ProfitabilityWindow(Base):
    __tablename__ = "canonical_parser_gen4_profitability_windows"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="ck_gen4_profitability_windows_sequence"),
        CheckConstraint(
            "strict_qualified_wallet_count >= 0 AND proxy_qualified_wallet_count >= 0 AND strict_signal_count >= 0 AND proxy_signal_count >= 0 AND baseline_signal_count >= 0",
            name="ck_gen4_profitability_windows_counts",
        ),
        CheckConstraint(
            "train_start_at < train_end_at AND train_end_at <= test_start_at AND test_start_at < test_end_at",
            name="ck_gen4_profitability_windows_dates",
        ),
        CheckConstraint("length(window_hash) = 64", name="ck_gen4_profitability_windows_hash_len"),
        UniqueConstraint("window_id", name="uq_gen4_profitability_windows_window_id"),
        UniqueConstraint("run_db_id", "sequence", name="uq_gen4_profitability_windows_sequence"),
        UniqueConstraint("window_hash", name="uq_gen4_profitability_windows_hash"),
        Index("ix_gen4_profitability_windows_run_sequence", "run_db_id", "sequence"),
        Index("ix_gen4_profitability_windows_test_period", "test_start_at", "test_end_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    window_id: Mapped[str] = mapped_column(String(36), nullable=False)
    run_db_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canonical_parser_gen4_profitability_runs.id",
            ondelete="CASCADE",
            name="fk_gen4_profitability_windows_run",
        ),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)

    train_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    train_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    test_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    test_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    strict_qualified_wallet_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    proxy_qualified_wallet_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    strict_signal_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    proxy_signal_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    baseline_signal_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    strict_metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    proxy_metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    baseline_metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    window_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CanonicalParserGen4ProfitabilityTrade(Base):
    __tablename__ = "canonical_parser_gen4_profitability_trades"
    __table_args__ = (
        CheckConstraint(
            "lane IN ('STRICT_GEN4', 'SIGNAL_ONLY_PROXY', 'SIMPLE_COPY_BASELINE')",
            name="ck_gen4_profitability_trades_lane",
        ),
        CheckConstraint("sequence >= 1", name="ck_gen4_profitability_trades_sequence"),
        CheckConstraint("order_size_sol > 0", name="ck_gen4_profitability_trades_order_size"),
        CheckConstraint(
            "wallet_count >= 0 AND independent_cluster_count >= 0",
            name="ck_gen4_profitability_trades_counts",
        ),
        CheckConstraint("length(trade_hash) = 64", name="ck_gen4_profitability_trades_hash_len"),
        UniqueConstraint("trade_id", name="uq_gen4_profitability_trades_trade_id"),
        UniqueConstraint("window_db_id", "lane", "sequence", name="uq_gen4_profitability_trades_sequence"),
        UniqueConstraint("trade_hash", name="uq_gen4_profitability_trades_hash"),
        Index("ix_gen4_profitability_trades_window_lane", "window_db_id", "lane", "sequence"),
        Index("ix_gen4_profitability_trades_token_signal", "token_mint", "signal_at"),
        Index("ix_gen4_profitability_trades_lane_exit_reason", "lane", "exit_reason"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    trade_id: Mapped[str] = mapped_column(String(36), nullable=False)
    window_db_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canonical_parser_gen4_profitability_windows.id",
            ondelete="CASCADE",
            name="fk_gen4_profitability_trades_window",
        ),
        nullable=False,
    )
    lane: Mapped[str] = mapped_column(String(32), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    token_mint: Mapped[str] = mapped_column(String(64), nullable=False)

    signal_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_price_sol: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_price_sol: Mapped[float | None] = mapped_column(Float, nullable=True)
    order_size_sol: Mapped[float] = mapped_column(Float, nullable=False)
    pnl_sol: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(48), nullable=True)

    wallet_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    independent_cluster_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    contributing_wallets: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    source_trade_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    trade_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
