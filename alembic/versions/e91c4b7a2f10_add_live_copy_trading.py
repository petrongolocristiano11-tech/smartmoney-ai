"""add live copy trading

Revision ID: e91c4b7a2f10
Revises: d82f3a91c6b4
Create Date: 2026-07-18
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "e91c4b7a2f10"

down_revision: str | None = (
    "d82f3a91c6b4"
)

branch_labels: (
    str
    | Sequence[str]
    | None
) = None

depends_on: (
    str
    | Sequence[str]
    | None
) = None


def upgrade() -> None:
    op.create_table(
        "live_trading_policies",
        sa.Column(
            "id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "name",
            sa.String(length=80),
            nullable=False,
        ),
        sa.Column(
            "mode",
            sa.String(length=20),
            server_default="DISABLED",
            nullable=False,
        ),
        sa.Column(
            "kill_switch",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "stream_execution_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "source_wallets",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column(
            "buy_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "sell_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "sizing_mode",
            sa.String(length=30),
            server_default="FIXED",
            nullable=False,
        ),
        sa.Column(
            "fixed_buy_size_sol",
            sa.Float(),
            server_default="0.05",
            nullable=False,
        ),
        sa.Column(
            "source_trade_percentage",
            sa.Float(),
            server_default="10",
            nullable=False,
        ),
        sa.Column(
            "sell_position_percentage",
            sa.Float(),
            server_default="100",
            nullable=False,
        ),
        sa.Column(
            "max_order_size_sol",
            sa.Float(),
            server_default="0.10",
            nullable=False,
        ),
        sa.Column(
            "max_daily_buy_sol",
            sa.Float(),
            server_default="0.50",
            nullable=False,
        ),
        sa.Column(
            "max_daily_loss_sol",
            sa.Float(),
            server_default="0.20",
            nullable=False,
        ),
        sa.Column(
            "max_total_exposure_sol",
            sa.Float(),
            server_default="0.50",
            nullable=False,
        ),
        sa.Column(
            "min_wallet_reserve_sol",
            sa.Float(),
            server_default="0.05",
            nullable=False,
        ),
        sa.Column(
            "max_slippage_bps",
            sa.Integer(),
            server_default="300",
            nullable=False,
        ),
        sa.Column(
            "max_price_impact_percent",
            sa.Float(),
            server_default="5",
            nullable=False,
        ),
        sa.Column(
            "min_source_trade_sol",
            sa.Float(),
            server_default="0.01",
            nullable=False,
        ),
        sa.Column(
            "max_source_trade_age_seconds",
            sa.Integer(),
            server_default="120",
            nullable=False,
        ),
        sa.Column(
            "max_consecutive_failures",
            sa.Integer(),
            server_default="3",
            nullable=False,
        ),
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "mode IN "
            "('DISABLED', 'DRY_RUN', 'LIVE')",
            name=(
                "ck_live_trading_policies_mode"
            ),
        ),
        sa.CheckConstraint(
            "sizing_mode IN "
            "('FIXED', 'SOURCE_PERCENTAGE')",
            name=(
                "ck_live_trading_policies_"
                "sizing_mode"
            ),
        ),
        sa.CheckConstraint(
            "fixed_buy_size_sol > 0",
            name=(
                "ck_live_trading_policies_"
                "fixed_buy_positive"
            ),
        ),
        sa.CheckConstraint(
            "source_trade_percentage > 0 "
            "AND source_trade_percentage <= 100",
            name=(
                "ck_live_trading_policies_"
                "source_percentage"
            ),
        ),
        sa.CheckConstraint(
            "sell_position_percentage > 0 "
            "AND sell_position_percentage <= 100",
            name=(
                "ck_live_trading_policies_"
                "sell_percentage"
            ),
        ),
        sa.CheckConstraint(
            "max_order_size_sol > 0",
            name=(
                "ck_live_trading_policies_"
                "max_order_positive"
            ),
        ),
        sa.CheckConstraint(
            "max_daily_buy_sol > 0",
            name=(
                "ck_live_trading_policies_"
                "daily_buy_positive"
            ),
        ),
        sa.CheckConstraint(
            "max_daily_loss_sol > 0",
            name=(
                "ck_live_trading_policies_"
                "daily_loss_positive"
            ),
        ),
        sa.CheckConstraint(
            "max_total_exposure_sol > 0",
            name=(
                "ck_live_trading_policies_"
                "exposure_positive"
            ),
        ),
        sa.CheckConstraint(
            "min_wallet_reserve_sol >= 0",
            name=(
                "ck_live_trading_policies_"
                "reserve_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "max_slippage_bps "
            "BETWEEN 1 AND 5000",
            name=(
                "ck_live_trading_policies_"
                "slippage_range"
            ),
        ),
        sa.CheckConstraint(
            "max_price_impact_percent > 0 "
            "AND max_price_impact_percent <= 100",
            name=(
                "ck_live_trading_policies_"
                "price_impact_range"
            ),
        ),
        sa.CheckConstraint(
            "min_source_trade_sol >= 0",
            name=(
                "ck_live_trading_policies_"
                "min_source_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "max_source_trade_age_seconds "
            "BETWEEN 1 AND 86400",
            name=(
                "ck_live_trading_policies_"
                "trade_age_range"
            ),
        ),
        sa.CheckConstraint(
            "max_consecutive_failures "
            "BETWEEN 1 AND 100",
            name=(
                "ck_live_trading_policies_"
                "failure_limit_range"
            ),
        ),
        sa.CheckConstraint(
            "consecutive_failures >= 0",
            name=(
                "ck_live_trading_policies_"
                "failures_non_negative"
            ),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    op.create_index(
        op.f(
            "ix_live_trading_policies_id"
        ),
        "live_trading_policies",
        ["id"],
        unique=False,
    )

    op.create_index(
        op.f(
            "ix_live_trading_policies_name"
        ),
        "live_trading_policies",
        ["name"],
        unique=True,
    )

    op.create_index(
        op.f(
            "ix_live_trading_policies_mode"
        ),
        "live_trading_policies",
        ["mode"],
        unique=False,
    )

    op.create_index(
        op.f(
            "ix_live_trading_policies_"
            "kill_switch"
        ),
        "live_trading_policies",
        ["kill_switch"],
        unique=False,
    )

    op.create_table(
        "live_positions",
        sa.Column(
            "id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "mode",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "token_mint",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="OPEN",
            nullable=False,
        ),
        sa.Column(
            "quantity_raw",
            sa.Numeric(
                precision=38,
                scale=0,
            ),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "cost_basis_sol",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "realized_pnl_sol",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "last_buy_signature",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "last_sell_signature",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "closed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "mode IN ('DRY_RUN', 'LIVE')",
            name="ck_live_positions_mode",
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'CLOSED')",
            name="ck_live_positions_status",
        ),
        sa.CheckConstraint(
            "quantity_raw >= 0",
            name=(
                "ck_live_positions_"
                "quantity_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "cost_basis_sol >= 0",
            name=(
                "ck_live_positions_"
                "cost_non_negative"
            ),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "mode",
            "token_mint",
            name=(
                "uq_live_positions_mode_token"
            ),
        ),
    )

    op.create_index(
        op.f("ix_live_positions_id"),
        "live_positions",
        ["id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_live_positions_mode"),
        "live_positions",
        ["mode"],
        unique=False,
    )

    op.create_index(
        op.f(
            "ix_live_positions_token_mint"
        ),
        "live_positions",
        ["token_mint"],
        unique=False,
    )

    op.create_index(
        op.f(
            "ix_live_positions_status"
        ),
        "live_positions",
        ["status"],
        unique=False,
    )

    op.create_table(
        "live_copy_orders",
        sa.Column(
            "id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "idempotency_key",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "source_trade_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "source_signature",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "source_wallet",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "source_side",
            sa.String(length=10),
            nullable=False,
        ),
        sa.Column(
            "source_token_mint",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "source_sol_amount",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "source_token_amount",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "mode",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="RECEIVED",
            nullable=False,
        ),
        sa.Column(
            "input_mint",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "output_mint",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "requested_input_amount_raw",
            sa.Numeric(
                precision=38,
                scale=0,
            ),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "requested_value_sol",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "expected_output_amount_raw",
            sa.Numeric(
                precision=38,
                scale=0,
            ),
            nullable=True,
        ),
        sa.Column(
            "actual_input_amount_raw",
            sa.Numeric(
                precision=38,
                scale=0,
            ),
            nullable=True,
        ),
        sa.Column(
            "actual_output_amount_raw",
            sa.Numeric(
                precision=38,
                scale=0,
            ),
            nullable=True,
        ),
        sa.Column(
            "slippage_bps",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "jupiter_request_id",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "router",
            sa.String(length=40),
            nullable=True,
        ),
        sa.Column(
            "transaction_signature",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "error_code",
            sa.String(length=80),
            nullable=True,
        ),
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "order_response",
            sa.JSON(),
            nullable=True,
        ),
        sa.Column(
            "execute_response",
            sa.JSON(),
            nullable=True,
        ),
        sa.Column(
            "realized_pnl_sol",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "quoted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "executed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source_side IN ('BUY', 'SELL')",
            name="ck_live_copy_orders_side",
        ),
        sa.CheckConstraint(
            "mode IN ('DRY_RUN', 'LIVE')",
            name="ck_live_copy_orders_mode",
        ),
        sa.CheckConstraint(
            "status IN ("
            "'RECEIVED', "
            "'REJECTED', "
            "'DRY_RUN', "
            "'QUOTED', "
            "'SUBMITTED', "
            "'FILLED', "
            "'FAILED'"
            ")",
            name="ck_live_copy_orders_status",
        ),
        sa.CheckConstraint(
            "requested_input_amount_raw >= 0",
            name=(
                "ck_live_copy_orders_"
                "input_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "requested_value_sol >= 0",
            name=(
                "ck_live_copy_orders_"
                "value_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "slippage_bps BETWEEN 1 AND 5000",
            name=(
                "ck_live_copy_orders_"
                "slippage_range"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["source_trade_id"],
            ["trades.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key"
        ),
    )

    for index_name, columns, unique in (
        (
            "ix_live_copy_orders_id",
            ["id"],
            False,
        ),
        (
            "ix_live_copy_orders_"
            "idempotency_key",
            ["idempotency_key"],
            True,
        ),
        (
            "ix_live_copy_orders_"
            "source_trade_id",
            ["source_trade_id"],
            False,
        ),
        (
            "ix_live_copy_orders_"
            "source_signature",
            ["source_signature"],
            False,
        ),
        (
            "ix_live_copy_orders_"
            "source_wallet",
            ["source_wallet"],
            False,
        ),
        (
            "ix_live_copy_orders_"
            "source_side",
            ["source_side"],
            False,
        ),
        (
            "ix_live_copy_orders_"
            "source_token_mint",
            ["source_token_mint"],
            False,
        ),
        (
            "ix_live_copy_orders_mode",
            ["mode"],
            False,
        ),
        (
            "ix_live_copy_orders_status",
            ["status"],
            False,
        ),
        (
            "ix_live_copy_orders_"
            "jupiter_request_id",
            ["jupiter_request_id"],
            False,
        ),
        (
            "ix_live_copy_orders_"
            "transaction_signature",
            ["transaction_signature"],
            False,
        ),
        (
            "ix_live_copy_orders_created_at",
            ["created_at"],
            False,
        ),
    ):
        op.create_index(
            index_name,
            "live_copy_orders",
            columns,
            unique=unique,
        )

    op.create_index(
        "ix_live_copy_orders_created_status",
        "live_copy_orders",
        [
            "created_at",
            "status",
        ],
        unique=False,
    )

    op.create_table(
        "live_trading_events",
        sa.Column(
            "id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "order_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "event_type",
            sa.String(length=80),
            nullable=False,
        ),
        sa.Column(
            "severity",
            sa.String(length=20),
            server_default="INFO",
            nullable=False,
        ),
        sa.Column(
            "message",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "payload",
            sa.JSON(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "severity IN "
            "('INFO', 'WARNING', "
            "'ERROR', 'CRITICAL')",
            name=(
                "ck_live_trading_events_"
                "severity"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["live_copy_orders.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    for index_name, columns in (
        (
            "ix_live_trading_events_id",
            ["id"],
        ),
        (
            "ix_live_trading_events_order_id",
            ["order_id"],
        ),
        (
            "ix_live_trading_events_event_type",
            ["event_type"],
        ),
        (
            "ix_live_trading_events_severity",
            ["severity"],
        ),
        (
            "ix_live_trading_events_created_at",
            ["created_at"],
        ),
    ):
        op.create_index(
            index_name,
            "live_trading_events",
            columns,
            unique=False,
        )


def downgrade() -> None:
    op.drop_table(
        "live_trading_events"
    )

    op.drop_table(
        "live_copy_orders"
    )

    op.drop_table(
        "live_positions"
    )

    op.drop_table(
        "live_trading_policies"
    ) 