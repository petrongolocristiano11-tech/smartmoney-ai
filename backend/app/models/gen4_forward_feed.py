from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
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


class CanonicalParserGen4ForwardFeedState(Base):
    __tablename__ = "canonical_parser_gen4_forward_feed_states"
    __table_args__ = (
        CheckConstraint("interval_seconds BETWEEN 30 AND 3600", name="ck_gen4_forward_feed_states_interval"),
        CheckConstraint("max_requests_per_run BETWEEN 1 AND 20", name="ck_gen4_forward_feed_states_requests"),
        CheckConstraint("page_size BETWEEN 10 AND 100", name="ck_gen4_forward_feed_states_page_size"),
        CheckConstraint("overlap_seconds BETWEEN 0 AND 300", name="ck_gen4_forward_feed_states_overlap"),
        CheckConstraint(
            "total_runs >= 0 AND successful_runs >= 0 AND failed_runs >= 0 "
            "AND total_helius_requests >= 0 AND total_transactions_found >= 0 "
            "AND total_swaps_found >= 0 AND total_trades_imported >= 0 "
            "AND total_trades_updated >= 0 AND total_parse_failures >= 0 "
            "AND total_stale_transactions_filtered >= 0",
            name="ck_gen4_forward_feed_states_counts",
        ),
        UniqueConstraint("state_id", name="uq_gen4_forward_feed_states_state_id"),
        UniqueConstraint("campaign_db_id", name="uq_gen4_forward_feed_states_campaign"),
        Index("ix_gen4_forward_feed_states_enabled_next", "enabled", "next_poll_at"),
        Index("ix_gen4_forward_feed_states_lease", "lease_expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    state_id: Mapped[str] = mapped_column(String(36), nullable=False)
    campaign_db_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canonical_parser_gen4_forward_campaigns.id",
            ondelete="CASCADE",
            name="fk_gen4_forward_feed_states_campaign",
        ),
        nullable=False,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    interval_seconds: Mapped[int] = mapped_column(Integer, default=120, nullable=False)
    max_requests_per_run: Mapped[int] = mapped_column(Integer, default=4, nullable=False)
    page_size: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    overlap_seconds: Mapped[int] = mapped_column(Integer, default=90, nullable=False)

    feed_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_poll_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_poll_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    lease_owner: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    last_status: Mapped[str | None] = mapped_column(String(24), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    total_runs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    successful_runs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_runs: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_helius_requests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_transactions_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_swaps_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_trades_imported: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_trades_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_parse_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_stale_transactions_filtered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    technical_metadata: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CanonicalParserGen4ForwardFeedRun(Base):
    __tablename__ = "canonical_parser_gen4_forward_feed_runs"
    __table_args__ = (
        CheckConstraint(
            "trigger IN ('MANUAL','SCHEDULER','STARTUP')",
            name="ck_gen4_forward_feed_runs_trigger",
        ),
        CheckConstraint(
            "status IN ('COMPLETED','NOOP','PARTIAL','FAILED','SKIPPED_LOCKED','SKIPPED_BUDGET')",
            name="ck_gen4_forward_feed_runs_status",
        ),
        CheckConstraint(
            "wallet_count >= 0 AND request_budget >= 0 AND helius_requests >= 0 "
            "AND transactions_found >= 0 AND swaps_found >= 0 "
            "AND trades_imported >= 0 AND trades_updated >= 0 "
            "AND parse_failures >= 0 AND stale_transactions_filtered >= 0 "
            "AND new_decisions >= 0 AND updated_decisions >= 0",
            name="ck_gen4_forward_feed_runs_counts",
        ),
        UniqueConstraint("run_id", name="uq_gen4_forward_feed_runs_run_id"),
        Index("ix_gen4_forward_feed_runs_campaign_started", "campaign_db_id", "started_at"),
        Index("ix_gen4_forward_feed_runs_status_completed", "status", "completed_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, nullable=False)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    state_db_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canonical_parser_gen4_forward_feed_states.id",
            ondelete="CASCADE",
            name="fk_gen4_forward_feed_runs_state",
        ),
        nullable=False,
    )
    campaign_db_id: Mapped[int] = mapped_column(
        ForeignKey(
            "canonical_parser_gen4_forward_campaigns.id",
            ondelete="CASCADE",
            name="fk_gen4_forward_feed_runs_campaign",
        ),
        nullable=False,
    )
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(120), nullable=False)

    observed_from_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_to_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    wallet_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    request_budget: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    helius_requests: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    transactions_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    swaps_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    trades_imported: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    trades_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    parse_failures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    stale_transactions_filtered: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    cycle_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    cycle_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cycle_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    new_decisions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    updated_decisions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    details: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    safety: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
