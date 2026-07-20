"""add autonomous exit risk and operations

Revision ID: d8a4f7c2e915
Revises: c7d9e1f2a603
Create Date: 2026-07-20
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "d8a4f7c2e915"
down_revision: str | None = "c7d9e1f2a603"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    policy_columns = (
        sa.Column(
            "automatic_exits_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "take_profit_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "take_profit_percent",
            sa.Float(),
            server_default="25",
            nullable=False,
        ),
        sa.Column(
            "stop_loss_enabled",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
        sa.Column(
            "stop_loss_percent",
            sa.Float(),
            server_default="15",
            nullable=False,
        ),
        sa.Column(
            "trailing_stop_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "trailing_stop_percent",
            sa.Float(),
            server_default="10",
            nullable=False,
        ),
        sa.Column(
            "time_exit_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "max_position_age_minutes",
            sa.Integer(),
            server_default="1440",
            nullable=False,
        ),
        sa.Column(
            "auto_exit_position_percentage",
            sa.Float(),
            server_default="100",
            nullable=False,
        ),
        sa.Column(
            "max_open_positions",
            sa.Integer(),
            server_default="5",
            nullable=False,
        ),
        sa.Column(
            "max_token_exposure_sol",
            sa.Float(),
            server_default="0.10",
            nullable=False,
        ),
        sa.Column(
            "max_daily_orders",
            sa.Integer(),
            server_default="50",
            nullable=False,
        ),
        sa.Column(
            "max_portfolio_drawdown_percent",
            sa.Float(),
            server_default="20",
            nullable=False,
        ),
        sa.Column(
            "loss_streak_cooldown_threshold",
            sa.Integer(),
            server_default="3",
            nullable=False,
        ),
        sa.Column(
            "cooldown_after_loss_minutes",
            sa.Integer(),
            server_default="30",
            nullable=False,
        ),
    )

    for column in policy_columns:
        op.add_column(
            "live_trading_policies",
            column,
        )

    op.create_index(
        "ix_live_trading_policies_automatic_exits_enabled",
        "live_trading_policies",
        ["automatic_exits_enabled"],
        unique=False,
    )

    policy_constraints = (
        (
            "ck_live_policy_take_profit",
            "take_profit_percent > 0 AND take_profit_percent <= 10000",
        ),
        (
            "ck_live_policy_stop_loss",
            "stop_loss_percent > 0 AND stop_loss_percent <= 100",
        ),
        (
            "ck_live_policy_trailing_stop",
            "trailing_stop_percent > 0 AND trailing_stop_percent <= 100",
        ),
        (
            "ck_live_policy_position_age",
            "max_position_age_minutes BETWEEN 1 AND 525600",
        ),
        (
            "ck_live_policy_auto_exit_percentage",
            "auto_exit_position_percentage > 0 "
            "AND auto_exit_position_percentage <= 100",
        ),
        (
            "ck_live_policy_max_open_positions",
            "max_open_positions BETWEEN 1 AND 1000",
        ),
        (
            "ck_live_policy_token_exposure",
            "max_token_exposure_sol > 0",
        ),
        (
            "ck_live_policy_daily_orders",
            "max_daily_orders BETWEEN 1 AND 10000",
        ),
        (
            "ck_live_policy_drawdown",
            "max_portfolio_drawdown_percent > 0 "
            "AND max_portfolio_drawdown_percent <= 100",
        ),
        (
            "ck_live_policy_loss_streak_threshold",
            "loss_streak_cooldown_threshold BETWEEN 1 AND 100",
        ),
        (
            "ck_live_policy_cooldown_minutes",
            "cooldown_after_loss_minutes BETWEEN 1 AND 10080",
        ),
    )

    for name, condition in policy_constraints:
        op.create_check_constraint(
            name,
            "live_trading_policies",
            condition,
        )

    position_columns = (
        sa.Column(
            "source_wallet",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "current_value_sol",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "unrealized_pnl_sol",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "unrealized_roi_percent",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "high_watermark_value_sol",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "high_watermark_roi_percent",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "trailing_stop_value_sol",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "exit_pending",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "exit_attempts",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "last_exit_reason",
            sa.String(length=80),
            nullable=True,
        ),
        sa.Column(
            "next_exit_retry_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_quote_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_exit_evaluation_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    for column in position_columns:
        op.add_column(
            "live_positions",
            column,
        )

    op.create_check_constraint(
        "ck_live_positions_exit_attempts",
        "live_positions",
        "exit_attempts >= 0",
    )

    for index_name, column in (
        (
            "ix_live_positions_source_wallet",
            "source_wallet",
        ),
        (
            "ix_live_positions_exit_pending",
            "exit_pending",
        ),
        (
            "ix_live_positions_next_exit_retry_at",
            "next_exit_retry_at",
        ),
        (
            "ix_live_positions_last_quote_at",
            "last_quote_at",
        ),
    ):
        op.create_index(
            index_name,
            "live_positions",
            [column],
            unique=False,
        )

    order_columns = (
        sa.Column(
            "execution_origin",
            sa.String(length=30),
            server_default="SOURCE_TRADE",
            nullable=False,
        ),
        sa.Column(
            "exit_reason",
            sa.String(length=80),
            nullable=True,
        ),
        sa.Column(
            "reconciliation_status",
            sa.String(length=20),
            server_default="NOT_REQUIRED",
            nullable=False,
        ),
        sa.Column(
            "reconciliation_attempts",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "confirmation_status",
            sa.String(length=40),
            nullable=True,
        ),
        sa.Column(
            "on_chain_error",
            sa.JSON(),
            nullable=True,
        ),
        sa.Column(
            "last_reconciled_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "confirmed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    for column in order_columns:
        op.add_column(
            "live_copy_orders",
            column,
        )

    op.create_check_constraint(
        "ck_live_copy_orders_execution_origin",
        "live_copy_orders",
        "execution_origin IN "
        "('SOURCE_TRADE', 'MANUAL_CLOSE', 'AUTO_EXIT')",
    )
    op.create_check_constraint(
        "ck_live_copy_orders_reconciliation_status",
        "live_copy_orders",
        "reconciliation_status IN "
        "('NOT_REQUIRED', 'PENDING', 'CONFIRMED', 'FAILED', 'UNKNOWN')",
    )
    op.create_check_constraint(
        "ck_live_copy_orders_reconciliation_attempts",
        "live_copy_orders",
        "reconciliation_attempts >= 0",
    )

    for index_name, column in (
        (
            "ix_live_copy_orders_execution_origin",
            "execution_origin",
        ),
        (
            "ix_live_copy_orders_exit_reason",
            "exit_reason",
        ),
        (
            "ix_live_copy_orders_reconciliation_status",
            "reconciliation_status",
        ),
        (
            "ix_live_copy_orders_last_reconciled_at",
            "last_reconciled_at",
        ),
    ):
        op.create_index(
            index_name,
            "live_copy_orders",
            [column],
            unique=False,
        )

    op.execute(
        sa.text(
            """
            UPDATE live_positions AS position
            SET source_wallet = source.source_wallet
            FROM (
                SELECT DISTINCT ON (
                    mode,
                    generation,
                    source_token_mint
                )
                    mode,
                    generation,
                    source_token_mint,
                    source_wallet
                FROM live_copy_orders
                WHERE source_side = 'BUY'
                  AND status IN ('DRY_RUN', 'FILLED')
                ORDER BY
                    mode,
                    generation,
                    source_token_mint,
                    executed_at DESC NULLS LAST,
                    id DESC
            ) AS source
            WHERE position.mode = source.mode
              AND position.generation = source.generation
              AND position.token_mint = source.source_token_mint
            """
        )
    )

    op.create_table(
        "live_risk_states",
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
            "generation",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column(
            "starting_equity_sol",
            sa.Float(),
            server_default="1",
            nullable=False,
        ),
        sa.Column(
            "current_equity_sol",
            sa.Float(),
            server_default="1",
            nullable=False,
        ),
        sa.Column(
            "peak_equity_sol",
            sa.Float(),
            server_default="1",
            nullable=False,
        ),
        sa.Column(
            "realized_pnl_sol",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "drawdown_percent",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "loss_streak",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "cooldown_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "blocked_reason",
            sa.String(length=255),
            nullable=True,
        ),
        sa.Column(
            "last_loss_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_fill_at",
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
            "mode IN ('DRY_RUN', 'LIVE')",
            name="ck_live_risk_states_mode",
        ),
        sa.CheckConstraint(
            "generation >= 1",
            name="ck_live_risk_states_generation",
        ),
        sa.CheckConstraint(
            "starting_equity_sol > 0",
            name="ck_live_risk_states_starting_equity",
        ),
        sa.CheckConstraint(
            "peak_equity_sol > 0",
            name="ck_live_risk_states_peak_equity",
        ),
        sa.CheckConstraint(
            "loss_streak >= 0",
            name="ck_live_risk_states_loss_streak",
        ),
        sa.CheckConstraint(
            "drawdown_percent >= 0",
            name="ck_live_risk_states_drawdown",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "mode",
            "generation",
            name="uq_live_risk_states_mode_generation",
        ),
    )
    op.create_index(
        "ix_live_risk_states_id",
        "live_risk_states",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_live_risk_states_mode",
        "live_risk_states",
        ["mode"],
        unique=False,
    )
    op.create_index(
        "ix_live_risk_states_generation",
        "live_risk_states",
        ["generation"],
        unique=False,
    )
    op.create_index(
        "ix_live_risk_states_cooldown_until",
        "live_risk_states",
        ["cooldown_until"],
        unique=False,
    )

    op.create_table(
        "live_position_monitor_states",
        sa.Column(
            "id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="STOPPED",
            nullable=False,
        ),
        sa.Column(
            "worker_id",
            sa.String(length=160),
            nullable=True,
        ),
        sa.Column(
            "lease_owner",
            sa.String(length=160),
            nullable=True,
        ),
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_run_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_run_completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "total_runs",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "positions_scanned",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "quotes_succeeded",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "quotes_failed",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "exits_triggered",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "exits_completed",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "exits_failed",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "orders_reconciled",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "reconciliation_failed",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "last_error_code",
            sa.String(length=100),
            nullable=True,
        ),
        sa.Column(
            "last_error_message",
            sa.Text(),
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
            "id = 1",
            name="ck_live_position_monitor_singleton",
        ),
        sa.CheckConstraint(
            "status IN "
            "('STOPPED', 'IDLE', 'RUNNING', 'DEGRADED', 'ERROR')",
            name="ck_live_position_monitor_status",
        ),
        sa.CheckConstraint(
            "total_runs >= 0",
            name="ck_live_position_monitor_runs",
        ),
        sa.CheckConstraint(
            "positions_scanned >= 0",
            name="ck_live_position_monitor_positions",
        ),
        sa.CheckConstraint(
            "quotes_succeeded >= 0",
            name="ck_live_position_monitor_quotes_ok",
        ),
        sa.CheckConstraint(
            "quotes_failed >= 0",
            name="ck_live_position_monitor_quotes_failed",
        ),
        sa.CheckConstraint(
            "exits_triggered >= 0",
            name="ck_live_position_monitor_exits_triggered",
        ),
        sa.CheckConstraint(
            "exits_completed >= 0",
            name="ck_live_position_monitor_exits_completed",
        ),
        sa.CheckConstraint(
            "exits_failed >= 0",
            name="ck_live_position_monitor_exits_failed",
        ),
        sa.CheckConstraint(
            "orders_reconciled >= 0",
            name="ck_live_position_monitor_reconciled",
        ),
        sa.CheckConstraint(
            "reconciliation_failed >= 0",
            name="ck_live_position_monitor_reconcile_failed",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_live_position_monitor_states_status",
        "live_position_monitor_states",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_live_position_monitor_states_lease_owner",
        "live_position_monitor_states",
        ["lease_owner"],
        unique=False,
    )
    op.create_index(
        "ix_live_position_monitor_states_lease_expires_at",
        "live_position_monitor_states",
        ["lease_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_live_position_monitor_states_heartbeat_at",
        "live_position_monitor_states",
        ["heartbeat_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table(
        "live_position_monitor_states"
    )
    op.drop_table(
        "live_risk_states"
    )

    for index_name in (
        "ix_live_copy_orders_last_reconciled_at",
        "ix_live_copy_orders_reconciliation_status",
        "ix_live_copy_orders_exit_reason",
        "ix_live_copy_orders_execution_origin",
    ):
        op.drop_index(
            index_name,
            table_name="live_copy_orders",
        )

    for constraint_name in (
        "ck_live_copy_orders_reconciliation_attempts",
        "ck_live_copy_orders_reconciliation_status",
        "ck_live_copy_orders_execution_origin",
    ):
        op.drop_constraint(
            constraint_name,
            "live_copy_orders",
            type_="check",
        )

    for column in (
        "confirmed_at",
        "last_reconciled_at",
        "on_chain_error",
        "confirmation_status",
        "reconciliation_attempts",
        "reconciliation_status",
        "exit_reason",
        "execution_origin",
    ):
        op.drop_column(
            "live_copy_orders",
            column,
        )

    for index_name in (
        "ix_live_positions_last_quote_at",
        "ix_live_positions_next_exit_retry_at",
        "ix_live_positions_exit_pending",
        "ix_live_positions_source_wallet",
    ):
        op.drop_index(
            index_name,
            table_name="live_positions",
        )

    op.drop_constraint(
        "ck_live_positions_exit_attempts",
        "live_positions",
        type_="check",
    )

    for column in (
        "last_exit_evaluation_at",
        "last_quote_at",
        "next_exit_retry_at",
        "last_exit_reason",
        "exit_attempts",
        "exit_pending",
        "trailing_stop_value_sol",
        "high_watermark_roi_percent",
        "high_watermark_value_sol",
        "unrealized_roi_percent",
        "unrealized_pnl_sol",
        "current_value_sol",
        "source_wallet",
    ):
        op.drop_column(
            "live_positions",
            column,
        )

    for constraint_name in (
        "ck_live_policy_cooldown_minutes",
        "ck_live_policy_loss_streak_threshold",
        "ck_live_policy_drawdown",
        "ck_live_policy_daily_orders",
        "ck_live_policy_token_exposure",
        "ck_live_policy_max_open_positions",
        "ck_live_policy_auto_exit_percentage",
        "ck_live_policy_position_age",
        "ck_live_policy_trailing_stop",
        "ck_live_policy_stop_loss",
        "ck_live_policy_take_profit",
    ):
        op.drop_constraint(
            constraint_name,
            "live_trading_policies",
            type_="check",
        )

    op.drop_index(
        "ix_live_trading_policies_automatic_exits_enabled",
        table_name="live_trading_policies",
    )

    for column in (
        "cooldown_after_loss_minutes",
        "loss_streak_cooldown_threshold",
        "max_portfolio_drawdown_percent",
        "max_daily_orders",
        "max_token_exposure_sol",
        "max_open_positions",
        "auto_exit_position_percentage",
        "max_position_age_minutes",
        "time_exit_enabled",
        "trailing_stop_percent",
        "trailing_stop_enabled",
        "stop_loss_percent",
        "stop_loss_enabled",
        "take_profit_percent",
        "take_profit_enabled",
        "automatic_exits_enabled",
    ):
        op.drop_column(
            "live_trading_policies",
            column,
        )
