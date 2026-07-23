from datetime import datetime

from sqlalchemy import DateTime, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.app.database.base import Base


class CandidateReconstructionAuditRun(Base):
    __tablename__ = "candidate_reconstruction_audit_runs"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )
    run_id: Mapped[str] = mapped_column(
        String(36),
        unique=True,
        index=True,
    )
    wallet_address: Mapped[str] = mapped_column(
        String(64),
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(24),
        default="COMPLETED",
        index=True,
    )

    parameters: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
    )
    safety: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
    )
    baseline_metrics: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
    )
    exclusion_summary: Mapped[dict] = mapped_column(
        JSON,
        default=dict,
    )
    excluded_trades: Mapped[list] = mapped_column(
        JSON,
        default=list,
    )
    scenario_results: Mapped[list] = mapped_column(
        JSON,
        default=list,
    )
    diagnoses: Mapped[list] = mapped_column(
        JSON,
        default=list,
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        index=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
