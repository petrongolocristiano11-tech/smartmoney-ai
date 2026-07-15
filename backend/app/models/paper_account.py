from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    Integer,
    String,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)
from sqlalchemy.sql import func

from backend.app.database.base import Base


class PaperAccount(Base):
    __tablename__ = "paper_accounts"

    __table_args__ = (
        CheckConstraint(
            "status IN "
            "('ACTIVE', 'PAUSED', 'STOPPED')",
            name="ck_paper_accounts_status",
        ),
        CheckConstraint(
            "starting_balance_sol > 0",
            name=(
                "ck_paper_accounts_"
                "starting_balance_positive"
            ),
        ),
        CheckConstraint(
            "cash_balance_sol >= 0",
            name=(
                "ck_paper_accounts_"
                "cash_balance_non_negative"
            ),
        ),
        CheckConstraint(
            "max_position_size_sol > 0",
            name=(
                "ck_paper_accounts_"
                "max_position_positive"
            ),
        ),
        CheckConstraint(
            "max_open_positions > 0",
            name=(
                "ck_paper_accounts_"
                "max_open_positions_positive"
            ),
        ),
        CheckConstraint(
            "daily_loss_limit_sol > 0",
            name=(
                "ck_paper_accounts_"
                "daily_loss_limit_positive"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    name: Mapped[str] = mapped_column(
        String(80),
        unique=True,
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="ACTIVE",
        index=True,
    )

    starting_balance_sol: Mapped[float] = (
        mapped_column(
            Float,
            default=10.0,
        )
    )

    cash_balance_sol: Mapped[float] = (
        mapped_column(
            Float,
            default=10.0,
        )
    )

    realized_pnl_sol: Mapped[float] = (
        mapped_column(
            Float,
            default=0.0,
        )
    )

    max_position_size_sol: Mapped[float] = (
        mapped_column(
            Float,
            default=0.5,
        )
    )

    max_open_positions: Mapped[int] = (
        mapped_column(
            Integer,
            default=3,
        )
    )

    daily_loss_limit_sol: Mapped[float] = (
        mapped_column(
            Float,
            default=1.0,
        )
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