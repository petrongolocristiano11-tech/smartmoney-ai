from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from backend.app.database.base import Base


class LivePositionMonitorState(Base):
    __tablename__ = "live_position_monitor_states"

    __table_args__ = (
        CheckConstraint(
            "id = 1",
            name="ck_live_position_monitor_singleton",
        ),
        CheckConstraint(
            "status IN ("
            "'STOPPED', "
            "'IDLE', "
            "'RUNNING', "
            "'DEGRADED', "
            "'ERROR'"
            ")",
            name="ck_live_position_monitor_status",
        ),
        CheckConstraint(
            "total_runs >= 0",
            name="ck_live_position_monitor_runs",
        ),
        CheckConstraint(
            "positions_scanned >= 0",
            name="ck_live_position_monitor_positions",
        ),
        CheckConstraint(
            "quotes_succeeded >= 0",
            name="ck_live_position_monitor_quotes_ok",
        ),
        CheckConstraint(
            "quotes_failed >= 0",
            name="ck_live_position_monitor_quotes_failed",
        ),
        CheckConstraint(
            "exits_triggered >= 0",
            name="ck_live_position_monitor_exits_triggered",
        ),
        CheckConstraint(
            "exits_completed >= 0",
            name="ck_live_position_monitor_exits_completed",
        ),
        CheckConstraint(
            "exits_failed >= 0",
            name="ck_live_position_monitor_exits_failed",
        ),
        CheckConstraint(
            "orders_reconciled >= 0",
            name="ck_live_position_monitor_reconciled",
        ),
        CheckConstraint(
            "reconciliation_failed >= 0",
            name="ck_live_position_monitor_reconcile_failed",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        default=1,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="STOPPED",
        index=True,
    )

    worker_id: Mapped[str | None] = mapped_column(
        String(160),
        nullable=True,
    )

    lease_owner: Mapped[str | None] = mapped_column(
        String(160),
        nullable=True,
        index=True,
    )

    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    last_run_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_run_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    total_runs: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    positions_scanned: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    quotes_succeeded: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    quotes_failed: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    exits_triggered: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    exits_completed: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    exits_failed: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    orders_reconciled: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    reconciliation_failed: Mapped[int] = mapped_column(
        Integer,
        default=0,
    )

    last_error_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    last_error_message: Mapped[str | None] = mapped_column(
        Text,
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
