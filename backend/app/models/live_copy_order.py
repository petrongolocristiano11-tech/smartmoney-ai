from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import (
    Mapped,
    mapped_column,
)
from sqlalchemy.sql import func

from backend.app.database.base import Base


class LiveCopyOrder(Base):
    __tablename__ = "live_copy_orders"

    __table_args__ = (
        CheckConstraint(
            "source_side IN ('BUY', 'SELL')",
            name=(
                "ck_live_copy_orders_side"
            ),
        ),
        CheckConstraint(
            "mode IN ('DRY_RUN', 'LIVE')",
            name=(
                "ck_live_copy_orders_mode"
            ),
        ),
        CheckConstraint(
            "status IN ("
            "'RECEIVED', "
            "'REJECTED', "
            "'DRY_RUN', "
            "'QUOTED', "
            "'SUBMITTED', "
            "'FILLED', "
            "'FAILED'"
            ")",
            name=(
                "ck_live_copy_orders_status"
            ),
        ),
        CheckConstraint(
            "requested_input_amount_raw >= 0",
            name=(
                "ck_live_copy_orders_"
                "input_non_negative"
            ),
        ),
        CheckConstraint(
            "requested_value_sol >= 0",
            name=(
                "ck_live_copy_orders_"
                "value_non_negative"
            ),
        ),
        CheckConstraint(
            "slippage_bps BETWEEN 1 AND 5000",
            name=(
                "ck_live_copy_orders_"
                "slippage_range"
            ),
        ),
        Index(
            "ix_live_copy_orders_"
            "created_status",
            "created_at",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True,
    )

    idempotency_key: Mapped[str] = (
        mapped_column(
            String(64),
            unique=True,
            index=True,
        )
    )

    source_trade_id: Mapped[
        int | None
    ] = mapped_column(
        ForeignKey(
            "trades.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )

    source_signature: Mapped[str] = (
        mapped_column(
            String(128),
            index=True,
        )
    )

    source_wallet: Mapped[str] = (
        mapped_column(
            String(64),
            index=True,
        )
    )

    source_side: Mapped[str] = (
        mapped_column(
            String(10),
            index=True,
        )
    )

    source_token_mint: Mapped[str] = (
        mapped_column(
            String(64),
            index=True,
        )
    )

    source_sol_amount: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    source_token_amount: Mapped[
        float | None
    ] = mapped_column(
        Float,
        nullable=True,
    )

    mode: Mapped[str] = mapped_column(
        String(20),
        index=True,
    )

    status: Mapped[str] = (
        mapped_column(
            String(20),
            default="RECEIVED",
            index=True,
        )
    )

    input_mint: Mapped[str] = (
        mapped_column(
            String(64),
        )
    )

    output_mint: Mapped[str] = (
        mapped_column(
            String(64),
        )
    )

    requested_input_amount_raw: Mapped[
        Decimal
    ] = mapped_column(
        Numeric(38, 0),
        default=Decimal(0),
    )

    requested_value_sol: Mapped[float] = (
        mapped_column(
            Float,
            default=0.0,
        )
    )

    expected_output_amount_raw: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(38, 0),
        nullable=True,
    )

    actual_input_amount_raw: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(38, 0),
        nullable=True,
    )

    actual_output_amount_raw: Mapped[
        Decimal | None
    ] = mapped_column(
        Numeric(38, 0),
        nullable=True,
    )

    slippage_bps: Mapped[int] = (
        mapped_column(
            Integer,
        )
    )

    jupiter_request_id: Mapped[
        str | None
    ] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )

    router: Mapped[
        str | None
    ] = mapped_column(
        String(40),
        nullable=True,
    )

    transaction_signature: Mapped[
        str | None
    ] = mapped_column(
        String(128),
        nullable=True,
        index=True,
    )

    error_code: Mapped[
        str | None
    ] = mapped_column(
        String(80),
        nullable=True,
    )

    error_message: Mapped[
        str | None
    ] = mapped_column(
        Text,
        nullable=True,
    )

    order_response: Mapped[
        dict | None
    ] = mapped_column(
        JSON,
        nullable=True,
    )

    execute_response: Mapped[
        dict | None
    ] = mapped_column(
        JSON,
        nullable=True,
    )

    realized_pnl_sol: Mapped[float] = (
        mapped_column(
            Float,
            default=0.0,
        )
    )

    quoted_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    submitted_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    executed_at: Mapped[
        datetime | None
    ] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            index=True,
        )
    )

    updated_at: Mapped[datetime] = (
        mapped_column(
            DateTime(timezone=True),
            server_default=func.now(),
            onupdate=func.now(),
        )
    ) 