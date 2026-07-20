from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.app.database.base import Base


class LiveRiskState(Base):
    __tablename__ = "live_risk_states"

    __table_args__ = (
        UniqueConstraint(
            "mode",
            "generation",
            name="uq_live_risk_states_mode_generation",
        ),
        CheckConstraint(
            "mode IN ('DRY_RUN', 'LIVE')",
            name="ck_live_risk_states_mode",
        ),
        CheckConstraint(
            "generation >= 1",
            name="ck_live_risk_states_generation",
        ),
        CheckConstraint(
            "starting_equity_sol > 0",
            name="ck_live_risk_states_starting_equity",
        ),
        CheckConstraint(
            "peak_equity_sol > 0",
            name="ck_live_risk_states_peak_equity",
        ),
        CheckConstraint(
            "loss_streak >= 0",
            name="ck_live_risk_states_loss_streak",
        ),
        CheckConstraint(
            "drawdown_percent >= 0",
            name="ck_live_risk_states_drawdown",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    mode: Mapped[str] = mapped_column(
        String(20),
        index=True,
    )

    generation: Mapped[int] = mapped_column(
        Integer,
        default=1,
        index=True,
    )

    starting_equity_sol: Mapped[float] = mapped_column(
        Float,
        default=1.0,
    )

    current_equity_sol: Mapped[float] = mapped_column(
        Float,
        default=1.0,
    )

    peak_equity_sol: Mapped[float] = mapped_column(
        Float,
        default=1.0,
    )

    realized_pnl_sol: Mapped[float] = mapped_column(
        Float,
        default=0.0,
    )

    drawdown_percent: Mapped[float] = mapped_column(
        Float,
        default=0.0,
    )

    loss_streak: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    cooldown_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    blocked_reason: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    last_loss_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_fill_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
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
