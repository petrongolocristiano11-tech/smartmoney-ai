from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)
from sqlalchemy.sql import func

from backend.app.database.base import Base


class PaperOrder(Base):
    __tablename__ = "paper_orders"

    __table_args__ = (
        CheckConstraint(
            "side IN ('BUY', 'SELL')",
            name="ck_paper_orders_side",
        ),
        CheckConstraint(
            "status IN "
            "('PENDING', 'FILLED', 'REJECTED')",
            name="ck_paper_orders_status",
        ),
        CheckConstraint(
            "requested_value_sol >= 0",
            name=(
                "ck_paper_orders_"
                "requested_value_non_negative"
            ),
        ),
        CheckConstraint(
            "quantity >= 0",
            name=(
                "ck_paper_orders_"
                "quantity_non_negative"
            ),
        ),
        CheckConstraint(
            "execution_price_sol >= 0",
            name=(
                "ck_paper_orders_"
                "execution_price_non_negative"
            ),
        ),
        CheckConstraint(
            "gross_value_sol >= 0",
            name=(
                "ck_paper_orders_"
                "gross_value_non_negative"
            ),
        ),
        CheckConstraint(
            "fee_sol >= 0",
            name=(
                "ck_paper_orders_"
                "fee_non_negative"
            ),
        ),
        CheckConstraint(
            "slippage_percent >= 0",
            name=(
                "ck_paper_orders_"
                "slippage_non_negative"
            ),
        ),
        CheckConstraint(
            "signal_score IS NULL OR "
            "(signal_score >= 0 "
            "AND signal_score <= 100)",
            name=(
                "ck_paper_orders_"
                "signal_score_range"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    account_id: Mapped[int] = mapped_column(
        ForeignKey(
            "paper_accounts.id",
            ondelete="CASCADE",
        ),
        index=True,
    )

    position_id: Mapped[
        int | None
    ] = mapped_column(
        ForeignKey(
            "paper_positions.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    token_mint: Mapped[str] = mapped_column(
        String(64),
        index=True,
    )

    side: Mapped[str] = mapped_column(
        String(10),
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="PENDING",
        index=True,
    )

    requested_value_sol: Mapped[float] = (
        mapped_column(
            Float,
            default=0.0,
        )
    )

    quantity: Mapped[float] = mapped_column(
        Float,
        default=0.0,
    )

    execution_price_sol: Mapped[float] = (
        mapped_column(
            Float,
            default=0.0,
        )
    )

    gross_value_sol: Mapped[float] = (
        mapped_column(
            Float,
            default=0.0,
        )
    )

    fee_sol: Mapped[float] = mapped_column(
        Float,
        default=0.0,
    )

    slippage_percent: Mapped[float] = (
        mapped_column(
            Float,
            default=0.0,
        )
    )

    realized_pnl_sol: Mapped[float] = (
        mapped_column(
            Float,
            default=0.0,
        )
    )

    signal_score: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    reason: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    executed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    created_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
        )
    ) 