from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.app.database.base import Base


class DiscoveredWallet(Base):
    __tablename__ = "discovered_wallets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    wallet_address: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    discovered_from_token: Mapped[str | None] = mapped_column(String(64), nullable=True)

    smart_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    ranking_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    roi_percent: Mapped[float] = mapped_column(Float, default=0.0)
    win_rate_percent: Mapped[float] = mapped_column(Float, default=0.0)
    profit_loss_sol: Mapped[float] = mapped_column(Float, default=0.0)
    reliable_positions: Mapped[int] = mapped_column(Integer, default=0)

    last_swap_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    swaps_24h: Mapped[int] = mapped_column(Integer, default=0)
    swaps_7d: Mapped[int] = mapped_column(Integer, default=0)
    buys_24h: Mapped[int] = mapped_column(Integer, default=0)
    sells_24h: Mapped[int] = mapped_column(Integer, default=0)
    buys_7d: Mapped[int] = mapped_column(Integer, default=0)
    sells_7d: Mapped[int] = mapped_column(Integer, default=0)
    volume_24h_sol: Mapped[float] = mapped_column(Float, default=0.0)
    volume_7d_sol: Mapped[float] = mapped_column(Float, default=0.0)
    active_days_7d: Mapped[int] = mapped_column(Integer, default=0)
    average_swaps_per_active_day_7d: Mapped[float] = mapped_column(Float, default=0.0)
    average_minutes_between_swaps_7d: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )
    activity_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    activity_classification: Mapped[str] = mapped_column(
        String(24),
        default="NON_ANALIZZATO",
        index=True,
    )
    activity_eligible: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    activity_reasons: Mapped[list] = mapped_column(JSON, default=list)
    activity_calculated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    eligible: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    eligibility_reasons: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(20), default="DISCOVERED")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )
