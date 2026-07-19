from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
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


class LiveTradingWorkerState(Base):
    __tablename__ = (
        "live_trading_worker_states"
    )

    __table_args__ = (
        CheckConstraint(
            "id = 1",
            name=(
                "ck_live_trading_worker_"
                "singleton"
            ),
        ),
        CheckConstraint(
            "status IN ("
            "'STOPPED', "
            "'STARTING', "
            "'IDLE', "
            "'CONNECTING', "
            "'RUNNING', "
            "'DEGRADED', "
            "'ERROR'"
            ")",
            name=(
                "ck_live_trading_worker_"
                "status"
            ),
        ),
        CheckConstraint(
            "monitored_wallets >= 0",
            name=(
                "ck_live_trading_worker_"
                "monitored_wallets"
            ),
        ),
        CheckConstraint(
            "active_subscriptions >= 0",
            name=(
                "ck_live_trading_worker_"
                "active_subscriptions"
            ),
        ),
        CheckConstraint(
            "queue_depth >= 0",
            name=(
                "ck_live_trading_worker_"
                "queue_depth"
            ),
        ),
        CheckConstraint(
            "reconnect_count >= 0",
            name=(
                "ck_live_trading_worker_"
                "reconnect_count"
            ),
        ),
        CheckConstraint(
            "signatures_received >= 0",
            name=(
                "ck_live_trading_worker_"
                "received"
            ),
        ),
        CheckConstraint(
            "signatures_processed >= 0",
            name=(
                "ck_live_trading_worker_"
                "processed"
            ),
        ),
        CheckConstraint(
            "signatures_failed >= 0",
            name=(
                "ck_live_trading_worker_"
                "failed"
            ),
        ),
        CheckConstraint(
            "signatures_dropped >= 0",
            name=(
                "ck_live_trading_worker_"
                "dropped"
            ),
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

    worker_id: Mapped[
        str | None
    ] = mapped_column(
        String(160),
        nullable=True,
    )

    lease_owner: Mapped[
        str | None
    ] = mapped_column(
        String(160),
        nullable=True,
        index=True,
    )

    lease_expires_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    active_wallets: Mapped[list] = (
        mapped_column(
            JSON,
            default=list,
        )
    )

    monitored_wallets: Mapped[int] = (
        mapped_column(
            Integer,
            default=0,
        )
    )

    active_subscriptions: Mapped[int] = (
        mapped_column(
            Integer,
            default=0,
        )
    )

    queue_depth: Mapped[int] = (
        mapped_column(
            Integer,
            default=0,
        )
    )

    reconnect_count: Mapped[int] = (
        mapped_column(
            Integer,
            default=0,
        )
    )

    signatures_received: Mapped[int] = (
        mapped_column(
            Integer,
            default=0,
        )
    )

    signatures_processed: Mapped[int] = (
        mapped_column(
            Integer,
            default=0,
        )
    )

    signatures_failed: Mapped[int] = (
        mapped_column(
            Integer,
            default=0,
        )
    )

    signatures_dropped: Mapped[int] = (
        mapped_column(
            Integer,
            default=0,
        )
    )

    last_latency_ms: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    config_fingerprint: Mapped[
        str | None
    ] = mapped_column(
        String(64),
        nullable=True,
    )

    last_signature: Mapped[
        str | None
    ] = mapped_column(
        String(128),
        nullable=True,
    )

    last_error_code: Mapped[
        str | None
    ] = mapped_column(
        String(100),
        nullable=True,
    )

    last_error_message: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    started_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    heartbeat_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    connected_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_message_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_trade_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    last_error_at: Mapped[
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