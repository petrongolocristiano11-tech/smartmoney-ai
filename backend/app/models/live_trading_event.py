from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)
from sqlalchemy.sql import func

from backend.app.database.base import Base


class LiveTradingEvent(Base):
    __tablename__ = (
        "live_trading_events"
    )

    __table_args__ = (
        CheckConstraint(
            "severity IN "
            "('INFO', 'WARNING', "
            "'ERROR', 'CRITICAL')",
            name=(
                "ck_live_trading_events_"
                "severity"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    order_id: Mapped[
        int | None
    ] = mapped_column(
        ForeignKey(
            "live_copy_orders.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    event_type: Mapped[str] = (
        mapped_column(
            String(80),
            index=True,
        )
    )

    severity: Mapped[str] = (
        mapped_column(
            String(20),
            default="INFO",
            index=True,
        )
    )

    message: Mapped[str] = (
        mapped_column(
            Text,
        )
    )

    payload: Mapped[
        dict | None
    ] = mapped_column(
        JSON,
        nullable=True,
    )

    created_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            index=True,
        )
    ) 