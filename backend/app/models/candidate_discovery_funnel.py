from datetime import datetime

from sqlalchemy import DateTime, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.app.database.base import Base


class CandidateDiscoveryFunnelRun(Base):
    __tablename__ = "candidate_discovery_funnel_runs"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    run_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    status: Mapped[str] = mapped_column(
        String(24),
        default="COMPLETED",
        index=True,
    )
    parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    safety: Mapped[dict] = mapped_column(JSON, default=dict)
    summary: Mapped[dict] = mapped_column(JSON, default=dict)
    wallet_results: Mapped[list] = mapped_column(JSON, default=list)
    history_queue: Mapped[list] = mapped_column(JSON, default=list)
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
