from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.app.database.base import Base


class LivePosition(Base):
    __tablename__ = "live_positions"

    __table_args__ = (
        UniqueConstraint(
            "mode",
            "generation",
            "token_mint",
            name=(
                "uq_live_positions_"
                "mode_generation_token"
            ),
        ),
        CheckConstraint(
            "mode IN ('DRY_RUN', 'LIVE')",
            name="ck_live_positions_mode",
        ),
        CheckConstraint(
            "status IN ('OPEN', 'CLOSED')",
            name="ck_live_positions_status",
        ),
        CheckConstraint(
            "quantity_raw >= 0",
            name="ck_live_positions_quantity_non_negative",
        ),
        CheckConstraint(
            "cost_basis_sol >= 0",
            name="ck_live_positions_cost_non_negative",
        ),
        CheckConstraint(
            "generation >= 1",
            name=(
                "ck_live_positions_"
                "generation_positive"
            ),
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

    generation: Mapped[int] = (
        mapped_column(
            Integer,
            default=1,
            index=True,
        )
    )

    token_mint: Mapped[str] = mapped_column(
        String(64),
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="OPEN",
        index=True,
    )

    quantity_raw: Mapped[Decimal] = mapped_column(
        Numeric(38, 0),
        default=Decimal(0),
    )

    cost_basis_sol: Mapped[float] = mapped_column(
        Float,
        default=0.0,
    )

    realized_pnl_sol: Mapped[float] = mapped_column(
        Float,
        default=0.0,
    )

    last_buy_signature: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    last_sell_signature: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )

    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
    )

    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    ) 