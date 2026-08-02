from __future__ import annotations

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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.app.database.base import Base


class CanonicalParserGen4ForwardCampaign(Base):
    __tablename__ = "canonical_parser_gen4_forward_campaigns"
    __table_args__ = (
        CheckConstraint(
            "scope = 'GEN4_STRICT_FORWARD_SHADOW'",
            name="ck_gen4_forward_campaigns_scope",
        ),
        CheckConstraint(
            "status IN ('ACTIVE','PAUSED','COMPLETED','FAILED')",
            name="ck_gen4_forward_campaigns_status",
        ),
        CheckConstraint(
            "verdict IN ('COLLECTING','NOT_EVALUABLE','NEGATIVE_EVIDENCE','PROMISING_NOT_PROVEN','PROFITABLE_EVIDENCE')",
            name="ck_gen4_forward_campaigns_verdict",
        ),
        CheckConstraint(
            "strict_evidence_status IN ('COLLECTING','INSUFFICIENT','EVALUABLE','SUFFICIENT')",
            name="ck_gen4_forward_campaigns_strict_status",
        ),
        CheckConstraint(
            "frozen_wallet_count >= 0 AND cycle_count >= 0 AND decision_count >= 0 AND strict_signal_count >= 0 AND proxy_signal_count >= 0 AND baseline_signal_count >= 0 AND strict_closed_trade_count >= 0 AND proxy_closed_trade_count >= 0 AND baseline_closed_trade_count >= 0 AND rejected_decision_count >= 0",
            name="ck_gen4_forward_campaigns_counts",
        ),
        CheckConstraint(
            "minimum_observation_days >= 1 AND minimum_closed_trades >= 1 AND proof_closed_trades >= minimum_closed_trades",
            name="ck_gen4_forward_campaigns_thresholds",
        ),
        CheckConstraint(
            "length(campaign_key) = 64 AND length(policy_hash) = 64 AND length(evidence_hash) = 64",
            name="ck_gen4_forward_campaigns_hashes",
        ),
        UniqueConstraint("campaign_id", name="uq_gen4_forward_campaigns_campaign_id"),
        UniqueConstraint("campaign_key", name="uq_gen4_forward_campaigns_campaign_key"),
        Index("ix_gen4_forward_campaigns_status_anchor", "status", "anchor_at"),
        Index("ix_gen4_forward_campaigns_verdict_updated", "verdict", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    campaign_key: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    verdict: Mapped[str] = mapped_column(String(40), nullable=False)
    strict_evidence_status: Mapped[str] = mapped_column(String(24), nullable=False)

    policy_version: Mapped[str] = mapped_column(String(120), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    frozen_wallets: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    frozen_wallet_metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    frozen_wallet_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    anchor_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    minimum_complete_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latest_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    minimum_observation_days: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_closed_trades: Mapped[int] = mapped_column(Integer, nullable=False)
    proof_closed_trades: Mapped[int] = mapped_column(Integer, nullable=False)

    cycle_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    decision_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    strict_signal_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    proxy_signal_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    baseline_signal_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    strict_closed_trade_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    proxy_closed_trade_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    baseline_closed_trade_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_decision_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    strict_metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    proxy_metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    baseline_metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    evidence_gaps: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    safety: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    technical_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CanonicalParserGen4ForwardCycle(Base):
    __tablename__ = "canonical_parser_gen4_forward_cycles"
    __table_args__ = (
        CheckConstraint(
            "status IN ('COMPLETED','NOOP','FAILED')",
            name="ck_gen4_forward_cycles_status",
        ),
        CheckConstraint("sequence >= 1", name="ck_gen4_forward_cycles_sequence"),
        CheckConstraint(
            "source_trade_count >= 0 AND accepted_price_point_count >= 0 AND new_decision_count >= 0 AND updated_decision_count >= 0 AND strict_signal_count >= 0 AND proxy_signal_count >= 0 AND baseline_signal_count >= 0 AND closed_decision_count >= 0",
            name="ck_gen4_forward_cycles_counts",
        ),
        CheckConstraint(
            "observed_from_at <= observed_to_at",
            name="ck_gen4_forward_cycles_dates",
        ),
        CheckConstraint(
            "length(cycle_key) = 64 AND length(report_hash) = 64",
            name="ck_gen4_forward_cycles_hashes",
        ),
        UniqueConstraint("cycle_id", name="uq_gen4_forward_cycles_cycle_id"),
        UniqueConstraint("campaign_db_id", "sequence", name="uq_gen4_forward_cycles_sequence"),
        UniqueConstraint("cycle_key", name="uq_gen4_forward_cycles_cycle_key"),
        Index("ix_gen4_forward_cycles_campaign_time", "campaign_db_id", "observed_to_at"),
        Index("ix_gen4_forward_cycles_status_completed", "status", "completed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    cycle_id: Mapped[str] = mapped_column(String(36), nullable=False)
    cycle_key: Mapped[str] = mapped_column(String(64), nullable=False)
    campaign_db_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canonical_parser_gen4_forward_campaigns.id",
            ondelete="CASCADE",
            name="fk_gen4_forward_cycles_campaign",
        ),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)

    observed_from_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_to_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_trade_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    accepted_price_point_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    new_decision_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_decision_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    strict_signal_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    proxy_signal_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    baseline_signal_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    closed_decision_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    safety: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    report_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class CanonicalParserGen4ForwardDecision(Base):
    __tablename__ = "canonical_parser_gen4_forward_decisions"
    __table_args__ = (
        CheckConstraint(
            "lane IN ('STRICT_GEN4_FORWARD','SIGNAL_ONLY_FORWARD','SIMPLE_COPY_FORWARD_BASELINE')",
            name="ck_gen4_forward_decisions_lane",
        ),
        CheckConstraint(
            "status IN ('WAITING_SAFETY','REJECTED','PENDING_ENTRY','OPEN','CLOSED','EXPIRED')",
            name="ck_gen4_forward_decisions_status",
        ),
        CheckConstraint("order_size_sol > 0", name="ck_gen4_forward_decisions_order_size"),
        CheckConstraint(
            "wallet_count >= 0 AND independent_cluster_count >= 0",
            name="ck_gen4_forward_decisions_counts",
        ),
        CheckConstraint(
            "length(decision_key) = 64 AND length(signal_hash) = 64 AND length(evidence_hash) = 64",
            name="ck_gen4_forward_decisions_hashes",
        ),
        UniqueConstraint("decision_id", name="uq_gen4_forward_decisions_decision_id"),
        UniqueConstraint("decision_key", name="uq_gen4_forward_decisions_decision_key"),
        Index("ix_gen4_forward_decisions_campaign_lane", "campaign_db_id", "lane", "status"),
        Index("ix_gen4_forward_decisions_token_signal", "token_mint", "signal_at"),
        Index("ix_gen4_forward_decisions_status_decision", "status", "decision_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    decision_id: Mapped[str] = mapped_column(String(36), nullable=False)
    decision_key: Mapped[str] = mapped_column(String(64), nullable=False)
    campaign_db_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canonical_parser_gen4_forward_campaigns.id",
            ondelete="CASCADE",
            name="fk_gen4_forward_decisions_campaign",
        ),
        nullable=False,
    )
    lane: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    token_mint: Mapped[str] = mapped_column(String(64), nullable=False)

    signal_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    signal_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decision_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    entry_price_sol: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_price_sol: Mapped[float | None] = mapped_column(Float, nullable=True)
    order_size_sol: Mapped[float] = mapped_column(Float, nullable=False)
    pnl_sol: Mapped[float | None] = mapped_column(Float, nullable=True)
    return_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(96), nullable=True)
    portfolio_accepted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    wallet_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    independent_cluster_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    contributing_wallets: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    source_trade_ids: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    source_signatures: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    signal_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    evidence_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    first_seen_cycle_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    last_updated_cycle_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
