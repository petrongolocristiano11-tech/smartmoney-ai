from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
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
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.app.database.base import Base


class CanonicalParserGen4CopyabilityCampaign(Base):
    __tablename__ = "canonical_parser_gen4_copyability_campaigns"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ACTIVE','PAUSED','COMPLETED','FAILED')",
            name="ck_gen4_copy_campaign_status",
        ),
        CheckConstraint(
            "verdict IN ('COLLECTING','NOT_EVALUABLE','NEGATIVE_EVIDENCE','PROMISING_NOT_PROVEN','PROFITABLE_EVIDENCE')",
            name="ck_gen4_copy_campaign_verdict",
        ),
        CheckConstraint(
            "minimum_observation_days >= 1 AND minimum_closed_trades >= 1 "
            "AND proof_closed_trades >= minimum_closed_trades",
            name="ck_gen4_copy_campaign_thresholds",
        ),
        CheckConstraint(
            "simulated_input_lamports > 0 AND slippage_bps BETWEEN 1 AND 10000 "
            "AND max_signal_age_ms >= 1000 AND max_quote_latency_ms >= 100 "
            "AND max_price_impact_bps BETWEEN 1 AND 10000 "
            "AND max_price_deterioration_bps BETWEEN 1 AND 50000 "
            "AND estimated_network_fee_lamports >= 0",
            name="ck_gen4_copy_campaign_policy",
        ),
        CheckConstraint(
            "receipt_count >= 0 AND duplicate_receipt_count >= 0 "
            "AND recovery_receipt_count >= 0 AND processed_receipt_count >= 0 "
            "AND failed_receipt_count >= 0 AND ignored_receipt_count >= 0 "
            "AND buy_signal_count >= 0 AND sell_signal_count >= 0 "
            "AND executable_entry_count >= 0 AND rejected_entry_count >= 0 "
            "AND open_position_count >= 0 AND closed_trade_count >= 0",
            name="ck_gen4_copy_campaign_counts",
        ),
        UniqueConstraint("campaign_id", name="uq_gen4_copy_campaign_id"),
        UniqueConstraint(
            "forward_campaign_db_id",
            name="uq_gen4_copy_campaign_forward",
        ),
        Index("ix_gen4_copy_campaign_status_anchor", "status", "anchor_at"),
        Index("ix_gen4_copy_campaign_verdict_updated", "verdict", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    campaign_id: Mapped[str] = mapped_column(String(36), nullable=False)
    forward_campaign_db_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canonical_parser_gen4_forward_campaigns.id",
            ondelete="CASCADE",
            name="fk_gen4_copy_campaign_forward",
        ),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    verdict: Mapped[str] = mapped_column(String(40), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(120), nullable=False)
    policy_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_snapshot: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    frozen_wallets: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    anchor_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    minimum_complete_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    latest_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    minimum_observation_days: Mapped[int] = mapped_column(Integer, nullable=False)
    minimum_closed_trades: Mapped[int] = mapped_column(Integer, nullable=False)
    proof_closed_trades: Mapped[int] = mapped_column(Integer, nullable=False)
    simulated_input_lamports: Mapped[int] = mapped_column(BigInteger, nullable=False)
    slippage_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    max_signal_age_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    max_quote_latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    max_price_impact_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    max_price_deterioration_bps: Mapped[int] = mapped_column(Integer, nullable=False)
    estimated_network_fee_lamports: Mapped[int] = mapped_column(BigInteger, nullable=False)
    minimum_webhook_coverage_percent: Mapped[float] = mapped_column(Float, nullable=False)
    minimum_profit_factor: Mapped[float] = mapped_column(Float, nullable=False)
    maximum_drawdown_percent: Mapped[float] = mapped_column(Float, nullable=False)

    webhook_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    webhook_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    webhook_configured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_webhook_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    receipt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duplicate_receipt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    recovery_receipt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    processed_receipt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_receipt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    ignored_receipt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    buy_signal_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sell_signal_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    executable_entry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    rejected_entry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    open_position_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    closed_trade_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    metrics: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    evidence_gaps: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    safety: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    actor_label: Mapped[str] = mapped_column(String(80), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    technical_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CanonicalParserGen4WebhookReceipt(Base):
    __tablename__ = "canonical_parser_gen4_webhook_receipts"
    __table_args__ = (
        CheckConstraint(
            "source IN ('WEBHOOK','RECOVERY_ONLY')",
            name="ck_gen4_copy_receipt_source",
        ),
        CheckConstraint(
            "status IN ('RECEIVED','PROCESSING','PROCESSED','IGNORED','FAILED','EXCLUDED_RECOVERY')",
            name="ck_gen4_copy_receipt_status",
        ),
        CheckConstraint(
            "delivery_count >= 1 AND processing_attempts >= 0",
            name="ck_gen4_copy_receipt_counts",
        ),
        UniqueConstraint("receipt_id", name="uq_gen4_copy_receipt_id"),
        UniqueConstraint(
            "campaign_db_id",
            "signature",
            name="uq_gen4_copy_receipt_signature",
        ),
        Index("ix_gen4_copy_receipt_status_received", "status", "received_at"),
        Index("ix_gen4_copy_receipt_campaign_wallet", "campaign_db_id", "wallet_address"),
        Index("ix_gen4_copy_receipt_signature", "signature"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    receipt_id: Mapped[str] = mapped_column(String(36), nullable=False)
    campaign_db_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canonical_parser_gen4_copyability_campaigns.id",
            ondelete="CASCADE",
            name="fk_gen4_copy_receipt_campaign",
        ),
        nullable=False,
    )
    signature: Mapped[str] = mapped_column(String(128), nullable=False)
    event_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    auth_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    wallet_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    matched_wallets: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    slot: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    block_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    processing_attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(96), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    parsed_summary: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CanonicalParserGen4CopyabilityPosition(Base):
    __tablename__ = "canonical_parser_gen4_copyability_positions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('OPEN','OPEN_PARTIAL','CLOSED','REJECTED')",
            name="ck_gen4_copy_position_status",
        ),
        CheckConstraint(
            "entry_source IN ('WEBHOOK','RECOVERY_ONLY')",
            name="ck_gen4_copy_position_source",
        ),
        CheckConstraint(
            "entry_input_lamports >= 0 AND entry_output_token_raw >= 0 "
            "AND remaining_token_raw >= 0 AND realized_output_lamports >= 0",
            name="ck_gen4_copy_position_amounts",
        ),
        UniqueConstraint("position_id", name="uq_gen4_copy_position_id"),
        UniqueConstraint(
            "campaign_db_id",
            "entry_signature",
            name="uq_gen4_copy_position_entry_signature",
        ),
        Index("ix_gen4_copy_position_open_wallet_token", "status", "wallet_address", "token_mint"),
        Index("ix_gen4_copy_position_closed_at", "closed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    position_id: Mapped[str] = mapped_column(String(36), nullable=False)
    campaign_db_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canonical_parser_gen4_copyability_campaigns.id",
            ondelete="CASCADE",
            name="fk_gen4_copy_position_campaign",
        ),
        nullable=False,
    )
    entry_receipt_db_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canonical_parser_gen4_webhook_receipts.id",
            ondelete="CASCADE",
            name="fk_gen4_copy_position_receipt",
        ),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    wallet_address: Mapped[str] = mapped_column(String(64), nullable=False)
    token_mint: Mapped[str] = mapped_column(String(64), nullable=False)
    token_decimals: Mapped[int] = mapped_column(Integer, nullable=False)
    entry_signature: Mapped[str] = mapped_column(String(128), nullable=False)
    entry_source: Mapped[str] = mapped_column(String(20), nullable=False)
    entry_signal_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    entry_quote_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    entry_quote_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opened_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    chain_age_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entry_quote_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entry_end_to_quote_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    entry_price_deterioration_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_price_impact_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_transaction_built: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    entry_copyable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    entry_rejection_reason: Mapped[str | None] = mapped_column(String(120), nullable=True)

    wallet_token_delta_raw: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    wallet_sol_equivalent_delta_lamports: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    wallet_effective_price_sol: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_input_lamports: Mapped[int] = mapped_column(BigInteger, nullable=False)
    entry_output_token_raw: Mapped[int] = mapped_column(BigInteger, nullable=False)
    remaining_token_raw: Mapped[int] = mapped_column(BigInteger, nullable=False)
    realized_output_lamports: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    allocated_entry_fee_lamports: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    allocated_exit_fee_lamports: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)

    pnl_lamports: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    return_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    close_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    exit_source: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_exit_signature: Mapped[str | None] = mapped_column(String(128), nullable=True)
    exit_quote_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exit_price_impact_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    exit_transaction_built: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    exit_copyable: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    entry_quote: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    exit_quotes: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CanonicalParserGen4CopyabilityWorkerState(Base):
    __tablename__ = "canonical_parser_gen4_copyability_worker_states"
    __table_args__ = (
        CheckConstraint(
            "poll_interval_seconds BETWEEN 1 AND 60 AND batch_size BETWEEN 1 AND 100",
            name="ck_gen4_copy_worker_policy",
        ),
        CheckConstraint(
            "total_iterations >= 0 AND total_receipts_processed >= 0 "
            "AND total_quotes >= 0 AND total_failures >= 0",
            name="ck_gen4_copy_worker_counts",
        ),
        UniqueConstraint("state_id", name="uq_gen4_copy_worker_state_id"),
        Index("ix_gen4_copy_worker_lease", "lease_expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    state_id: Mapped[str] = mapped_column(String(36), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    poll_interval_seconds: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    batch_size: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_iteration_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_iteration_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(96), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    total_iterations: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_receipts_processed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_quotes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    technical_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
