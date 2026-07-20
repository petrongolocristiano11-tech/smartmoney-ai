from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    Integer,
    JSON,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.app.database.base import Base


class LiveWalletScore(Base):
    __tablename__ = "live_wallet_scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    wallet_address: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    smart_score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    profile_score: Mapped[float] = mapped_column(Float, default=0.0)
    live_performance_score: Mapped[float] = mapped_column(Float, default=50.0)
    win_rate_percent: Mapped[float] = mapped_column(Float, default=0.0)
    roi_percent: Mapped[float] = mapped_column(Float, default=0.0)
    realized_pnl_sol: Mapped[float] = mapped_column(Float, default=0.0)
    closed_trades: Mapped[int] = mapped_column(Integer, default=0)
    rank: Mapped[int] = mapped_column(Integer, default=0, index=True)
    eligible: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    reasons: Mapped[list] = mapped_column(JSON, default=list)

    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
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
