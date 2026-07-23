from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.app.database.base import Base


class CandidateHistoryBackfillRun(Base):
    __tablename__ = "candidate_history_backfill_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    run_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    wallet_address: Mapped[str] = mapped_column(String(64), index=True)

    status: Mapped[str] = mapped_column(String(24), default="COMPLETED", index=True)
    stop_reason: Mapped[str] = mapped_column(String(64), default="COMPLETED")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    requested_lookback_days: Mapped[int] = mapped_column(Integer, default=30)
    page_size: Mapped[int] = mapped_column(Integer, default=100)
    request_budget: Mapped[int] = mapped_column(Integer, default=5)
    helius_requests: Mapped[int] = mapped_column(Integer, default=0)
    pages_fetched: Mapped[int] = mapped_column(Integer, default=0)
    transactions_found: Mapped[int] = mapped_column(Integer, default=0)
    swaps_found: Mapped[int] = mapped_column(Integer, default=0)
    trades_imported: Mapped[int] = mapped_column(Integer, default=0)
    trades_updated: Mapped[int] = mapped_column(Integer, default=0)
    parse_failures: Mapped[int] = mapped_column(Integer, default=0)
    duplicate_transactions: Mapped[int] = mapped_column(Integer, default=0)

    oldest_transaction_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    newest_transaction_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_before_signature: Mapped[str | None] = mapped_column(
        String(128), nullable=True
    )

    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    safety: Mapped[dict] = mapped_column(JSON, default=dict)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
