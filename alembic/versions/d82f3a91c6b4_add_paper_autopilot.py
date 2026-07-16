"""add paper autopilot

Revision ID: d82f3a91c6b4
Revises: c7e1b4f5a902
Create Date: 2026-07-16
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "d82f3a91c6b4"

down_revision: str | None = (
    "c7e1b4f5a902"
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
        "paper_autopilot_policies",
        sa.Column(
            "id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "min_signal_score",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "min_evidence_score",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "min_buyers",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "minimum_confidence",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "max_signal_age_hours",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "min_smart_volume_share_percent",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "max_volume_concentration_percent",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "blocked_risk_flags",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column(
            "excluded_token_mints",
            sa.JSON(),
            nullable=False,
        ),
        sa.Column(
            "max_signals_per_run",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "max_entries_per_run",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "max_entries_per_day",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "token_cooldown_hours",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "max_position_percent_of_equity",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "max_total_exposure_percent",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "minimum_cash_reserve_percent",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "minimum_order_size_sol",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "stop_loss_percent",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "take_profit_percent",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "trailing_stop_enabled",
            sa.Boolean(),
            nullable=False,
        ),
        sa.Column(
            "trailing_stop_percent",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "max_holding_hours",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "slippage_percent",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "fee_percent",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "max_consecutive_errors",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "consecutive_errors",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "paused_reason",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "last_run_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_error_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN "
            "('DISABLED', 'ENABLED', 'PAUSED')",
            name=(
                "ck_paper_autopilot_"
                "policies_status"
            ),
        ),
        sa.CheckConstraint(
            "minimum_confidence IN "
            "('LOW', 'MEDIUM', 'HIGH')",
            name=(
                "ck_paper_autopilot_"
                "policies_confidence"
            ),
        ),
        sa.CheckConstraint(
            "min_signal_score "
            "BETWEEN 0 AND 100",
            name=(
                "ck_paper_autopilot_"
                "min_signal_score"
            ),
        ),
        sa.CheckConstraint(
            "min_evidence_score "
            "BETWEEN 0 AND 100",
            name=(
                "ck_paper_autopilot_"
                "min_evidence_score"
            ),
        ),
        sa.CheckConstraint(
            "min_buyers > 0",
            name=(
                "ck_paper_autopilot_"
                "min_buyers_positive"
            ),
        ),
        sa.CheckConstraint(
            "max_signal_age_hours > 0",
            name=(
                "ck_paper_autopilot_"
                "signal_age_positive"
            ),
        ),
        sa.CheckConstraint(
            "min_smart_volume_share_percent "
            "BETWEEN 0 AND 100",
            name=(
                "ck_paper_autopilot_"
                "smart_volume_share"
            ),
        ),
        sa.CheckConstraint(
            "max_volume_concentration_percent "
            "BETWEEN 0 AND 100",
            name=(
                "ck_paper_autopilot_"
                "volume_concentration"
            ),
        ),
        sa.CheckConstraint(
            "max_signals_per_run > 0",
            name=(
                "ck_paper_autopilot_"
                "signals_per_run"
            ),
        ),
        sa.CheckConstraint(
            "max_entries_per_run > 0",
            name=(
                "ck_paper_autopilot_"
                "entries_per_run"
            ),
        ),
        sa.CheckConstraint(
            "max_entries_per_day > 0",
            name=(
                "ck_paper_autopilot_"
                "entries_per_day"
            ),
        ),
        sa.CheckConstraint(
            "token_cooldown_hours >= 0",
            name=(
                "ck_paper_autopilot_"
                "cooldown_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "max_position_percent_of_equity "
            "> 0 AND "
            "max_position_percent_of_equity "
            "<= 100",
            name=(
                "ck_paper_autopilot_"
                "position_equity_percent"
            ),
        ),
        sa.CheckConstraint(
            "max_total_exposure_percent "
            "> 0 AND "
            "max_total_exposure_percent "
            "<= 100",
            name=(
                "ck_paper_autopilot_"
                "total_exposure_percent"
            ),
        ),
        sa.CheckConstraint(
            "minimum_cash_reserve_percent "
            "BETWEEN 0 AND 100",
            name=(
                "ck_paper_autopilot_"
                "cash_reserve_percent"
            ),
        ),
        sa.CheckConstraint(
            "minimum_order_size_sol > 0",
            name=(
                "ck_paper_autopilot_"
                "minimum_order_positive"
            ),
        ),
        sa.CheckConstraint(
            "stop_loss_percent "
            "> 0 AND "
            "stop_loss_percent <= 100",
            name=(
                "ck_paper_autopilot_"
                "stop_loss_percent"
            ),
        ),
        sa.CheckConstraint(
            "take_profit_percent > 0",
            name=(
                "ck_paper_autopilot_"
                "take_profit_percent"
            ),
        ),
        sa.CheckConstraint(
            "trailing_stop_percent "
            "> 0 AND "
            "trailing_stop_percent <= 100",
            name=(
                "ck_paper_autopilot_"
                "trailing_stop_percent"
            ),
        ),
        sa.CheckConstraint(
            "max_holding_hours > 0",
            name=(
                "ck_paper_autopilot_"
                "max_holding_hours"
            ),
        ),
        sa.CheckConstraint(
            "slippage_percent "
            "BETWEEN 0 AND 50",
            name=(
                "ck_paper_autopilot_"
                "slippage_percent"
            ),
        ),
        sa.CheckConstraint(
            "fee_percent BETWEEN 0 AND 20",
            name=(
                "ck_paper_autopilot_"
                "fee_percent"
            ),
        ),
        sa.CheckConstraint(
            "max_consecutive_errors > 0",
            name=(
                "ck_paper_autopilot_"
                "max_errors_positive"
            ),
        ),
        sa.CheckConstraint(
            "consecutive_errors >= 0",
            name=(
                "ck_paper_autopilot_"
                "errors_non_negative"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["paper_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "account_id",
            name=(
                "uq_paper_autopilot_"
                "policies_account"
            ),
        ),
    )

    op.create_index(
        op.f(
            "ix_paper_autopilot_"
            "policies_id"
        ),
        "paper_autopilot_policies",
        ["id"],
        unique=False,
    )

    op.create_index(
        op.f(
            "ix_paper_autopilot_"
            "policies_account_id"
        ),
        "paper_autopilot_policies",
        ["account_id"],
        unique=False,
    )

    op.create_index(
        op.f(
            "ix_paper_autopilot_"
            "policies_status"
        ),
        "paper_autopilot_policies",
        ["status"],
        unique=False,
    )

    op.create_table(
        "paper_autopilot_runs",
        sa.Column(
            "id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "policy_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "trigger",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "signals_evaluated",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "entries_opened",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "exits_closed",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "decisions_count",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "errors_count",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "error_message",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "finished_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "trigger IN "
            "('MANUAL', 'AUTOMATION')",
            name=(
                "ck_paper_autopilot_"
                "runs_trigger"
            ),
        ),
        sa.CheckConstraint(
            "status IN "
            "('RUNNING', 'COMPLETED', "
            "'PARTIAL', 'FAILED', 'SKIPPED')",
            name=(
                "ck_paper_autopilot_"
                "runs_status"
            ),
        ),
        sa.CheckConstraint(
            "signals_evaluated >= 0",
            name=(
                "ck_paper_autopilot_"
                "signals_evaluated"
            ),
        ),
        sa.CheckConstraint(
            "entries_opened >= 0",
            name=(
                "ck_paper_autopilot_"
                "entries_opened"
            ),
        ),
        sa.CheckConstraint(
            "exits_closed >= 0",
            name=(
                "ck_paper_autopilot_"
                "exits_closed"
            ),
        ),
        sa.CheckConstraint(
            "decisions_count >= 0",
            name=(
                "ck_paper_autopilot_"
                "decisions_count"
            ),
        ),
        sa.CheckConstraint(
            "errors_count >= 0",
            name=(
                "ck_paper_autopilot_"
                "errors_count"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["paper_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["policy_id"],
            [
                "paper_autopilot_"
                "policies.id"
            ],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        op.f(
            "ix_paper_autopilot_runs_id"
        ),
        "paper_autopilot_runs",
        ["id"],
        unique=False,
    )

    op.create_index(
        op.f(
            "ix_paper_autopilot_"
            "runs_account_id"
        ),
        "paper_autopilot_runs",
        ["account_id"],
        unique=False,
    )

    op.create_index(
        op.f(
            "ix_paper_autopilot_"
            "runs_policy_id"
        ),
        "paper_autopilot_runs",
        ["policy_id"],
        unique=False,
    )

    op.create_index(
        op.f(
            "ix_paper_autopilot_"
            "runs_status"
        ),
        "paper_autopilot_runs",
        ["status"],
        unique=False,
    )

    op.create_index(
        op.f(
            "ix_paper_autopilot_"
            "runs_started_at"
        ),
        "paper_autopilot_runs",
        ["started_at"],
        unique=False,
    )

    op.create_index(
        "ix_paper_autopilot_runs_"
        "account_started",
        "paper_autopilot_runs",
        [
            "account_id",
            "started_at",
        ],
        unique=False,
    )

    op.create_table(
        "paper_autopilot_managed_positions",
        sa.Column(
            "id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "paper_position_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "entry_order_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "exit_order_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "entry_run_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "exit_run_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "token_mint",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "entry_price_sol",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "peak_price_sol",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "stop_loss_price_sol",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "take_profit_price_sol",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "trailing_stop_enabled",
            sa.Boolean(),
            nullable=False,
        ),
        sa.Column(
            "trailing_stop_percent",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "entry_signal_score",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "entry_evidence_score",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "entry_confidence",
            sa.String(length=20),
            nullable=True,
        ),
        sa.Column(
            "exit_reason",
            sa.String(length=80),
            nullable=True,
        ),
        sa.Column(
            "max_holding_until",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "closed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'CLOSED')",
            name=(
                "ck_paper_autopilot_"
                "managed_status"
            ),
        ),
        sa.CheckConstraint(
            "entry_price_sol > 0",
            name=(
                "ck_paper_autopilot_"
                "entry_price_positive"
            ),
        ),
        sa.CheckConstraint(
            "peak_price_sol > 0",
            name=(
                "ck_paper_autopilot_"
                "peak_price_positive"
            ),
        ),
        sa.CheckConstraint(
            "stop_loss_price_sol > 0",
            name=(
                "ck_paper_autopilot_"
                "stop_price_positive"
            ),
        ),
        sa.CheckConstraint(
            "take_profit_price_sol > 0",
            name=(
                "ck_paper_autopilot_"
                "take_price_positive"
            ),
        ),
        sa.CheckConstraint(
            "trailing_stop_percent "
            "> 0 AND "
            "trailing_stop_percent <= 100",
            name=(
                "ck_paper_autopilot_"
                "managed_trailing_percent"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["paper_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["paper_position_id"],
            ["paper_positions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entry_order_id"],
            ["paper_orders.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["exit_order_id"],
            ["paper_orders.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["entry_run_id"],
            ["paper_autopilot_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["exit_run_id"],
            ["paper_autopilot_runs.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "entry_order_id",
            name=(
                "uq_paper_autopilot_"
                "managed_entry_order"
            ),
        ),
    )

    managed_index_columns = {
        "id": ["id"],
        "account_id": ["account_id"],
        "paper_position_id": [
            "paper_position_id"
        ],
        "entry_order_id": [
            "entry_order_id"
        ],
        "exit_order_id": [
            "exit_order_id"
        ],
        "entry_run_id": ["entry_run_id"],
        "exit_run_id": ["exit_run_id"],
        "token_mint": ["token_mint"],
        "status": ["status"],
        "max_holding_until": [
            "max_holding_until"
        ],
    }

    for name, columns in (
        managed_index_columns.items()
    ):
        op.create_index(
            op.f(
                "ix_paper_autopilot_"
                f"managed_positions_{name}"
            ),
            (
                "paper_autopilot_"
                "managed_positions"
            ),
            columns,
            unique=False,
        )

    op.create_index(
        "ix_paper_autopilot_managed_"
        "account_status",
        (
            "paper_autopilot_"
            "managed_positions"
        ),
        [
            "account_id",
            "status",
        ],
        unique=False,
    )

    op.create_index(
        "ix_paper_autopilot_managed_"
        "token_status",
        (
            "paper_autopilot_"
            "managed_positions"
        ),
        [
            "token_mint",
            "status",
        ],
        unique=False,
    )

    op.create_table(
        "paper_autopilot_decisions",
        sa.Column(
            "id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "account_id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "managed_position_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "paper_position_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "paper_order_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "token_mint",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "action",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column(
            "reason_code",
            sa.String(length=80),
            nullable=False,
        ),
        sa.Column(
            "reason",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "signal_score",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "evidence_score",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "buyers",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "confidence",
            sa.String(length=20),
            nullable=True,
        ),
        sa.Column(
            "market_price_sol",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "quantity",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "value_sol",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "signal_snapshot",
            sa.JSON(),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "action IN "
            "('BUY', 'SELL', 'HOLD', "
            "'SKIP', 'ERROR')",
            name=(
                "ck_paper_autopilot_"
                "decisions_action"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["paper_autopilot_runs.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["paper_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["managed_position_id"],
            [
                "paper_autopilot_"
                "managed_positions.id"
            ],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["paper_position_id"],
            ["paper_positions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["paper_order_id"],
            ["paper_orders.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    decision_index_columns = {
        "id": ["id"],
        "run_id": ["run_id"],
        "account_id": ["account_id"],
        "managed_position_id": [
            "managed_position_id"
        ],
        "paper_position_id": [
            "paper_position_id"
        ],
        "paper_order_id": [
            "paper_order_id"
        ],
        "token_mint": ["token_mint"],
        "action": ["action"],
        "reason_code": ["reason_code"],
        "created_at": ["created_at"],
    }

    for name, columns in (
        decision_index_columns.items()
    ):
        op.create_index(
            op.f(
                "ix_paper_autopilot_"
                f"decisions_{name}"
            ),
            "paper_autopilot_decisions",
            columns,
            unique=False,
        )

    op.create_index(
        "ix_paper_autopilot_decisions_"
        "account_created",
        "paper_autopilot_decisions",
        [
            "account_id",
            "created_at",
        ],
        unique=False,
    )

    op.create_index(
        "ix_paper_autopilot_decisions_"
        "token_created",
        "paper_autopilot_decisions",
        [
            "token_mint",
            "created_at",
        ],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table(
        "paper_autopilot_decisions"
    )

    op.drop_table(
        "paper_autopilot_managed_positions"
    )

    op.drop_table(
        "paper_autopilot_runs"
    )

    op.drop_table(
        "paper_autopilot_policies"
    ) 