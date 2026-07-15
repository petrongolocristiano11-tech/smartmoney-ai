from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)
from sqlalchemy.sql import func

from backend.app.database.base import Base


class PaperPosition(Base):
    __tablename__ = "paper_positions"

    __table_args__ = (
        UniqueConstraint(
            "account_id",
            "token_mint",
            name=(
                "uq_paper_positions_"
                "account_token"
            ),
        ),
        CheckConstraint(
            "status IN ('OPEN', 'CLOSED')",
            name="ck_paper_positions_status",
        ),
        CheckConstraint(
            "quantity >= 0",
            name=(
                "ck_paper_positions_"
                "quantity_non_negative"
            ),
        ),
        CheckConstraint(
            "average_entry_price_sol >= 0",
            name=(
                "ck_paper_positions_"
                "entry_price_non_negative"
            ),
        ),
        CheckConstraint(
            "cost_basis_sol >= 0",
            name=(
                "ck_paper_positions_"
                "cost_basis_non_negative"
            ),
        ),
        CheckConstraint(
            "last_price_sol >= 0",
            name=(
                "ck_paper_positions_"
                "last_price_non_negative"
            ),
        ),
        CheckConstraint(
            "market_value_sol >= 0",
            name=(
                "ck_paper_positions_"
                "market_value_non_negative"
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

    token_mint: Mapped[str] = mapped_column(
        String(64),
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="OPEN",
        index=True,
    )

    quantity: Mapped[float] = mapped_column(
        Float,
        default=0.0,
    )

    average_entry_price_sol: Mapped[float] = (
        mapped_column(
            Float,
            default=0.0,
        )
    )

    cost_basis_sol: Mapped[float] = (
        mapped_column(
            Float,
            default=0.0,
        )
    )

    last_price_sol: Mapped[float] = (
        mapped_column(
            Float,
            default=0.0,
        )
    )

    market_value_sol: Mapped[float] = (
        mapped_column(
            Float,
            default=0.0,
        )
    )

    unrealized_pnl_sol: Mapped[float] = (
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

    opened_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
        )
    )

    closed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
        )
    )

    updated_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
        )
    ) 