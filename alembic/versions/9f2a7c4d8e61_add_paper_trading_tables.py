"""Add paper trading tables

Revision ID: 9f2a7c4d8e61
Revises: 43d107b1734a
Create Date: 2026-07-15
"""

from typing import (
    Sequence,
    Union,
)

from alembic import op
import sqlalchemy as sa


revision: str = "9f2a7c4d8e61"

down_revision: Union[
    str,
    Sequence[str],
    None,
] = "43d107b1734a"

branch_labels: Union[
    str,
    Sequence[str],
    None,
] = None

depends_on: Union[
    str,
    Sequence[str],
    None,
] = None


def upgrade() -> None:
    op.create_table(
        "paper_accounts",
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
            "status",
            sa.String(length=20),
            server_default="ACTIVE",
            nullable=False,
        ),
        sa.Column(
            "starting_balance_sol",
            sa.Float(),
            server_default="10",
            nullable=False,
        ),
        sa.Column(
            "cash_balance_sol",
            sa.Float(),
            server_default="10",
            nullable=False,
        ),
        sa.Column(
            "realized_pnl_sol",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "max_position_size_sol",
            sa.Float(),
            server_default="0.5",
            nullable=False,
        ),
        sa.Column(
            "max_open_positions",
            sa.Integer(),
            server_default="3",
            nullable=False,
        ),
        sa.Column(
            "daily_loss_limit_sol",
            sa.Float(),
            server_default="1",
            nullable=False,
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
            "('ACTIVE', 'PAUSED', 'STOPPED')",
            name="ck_paper_accounts_status",
        ),
        sa.CheckConstraint(
            "starting_balance_sol > 0",
            name=(
                "ck_paper_accounts_"
                "starting_balance_positive"
            ),
        ),
        sa.CheckConstraint(
            "cash_balance_sol >= 0",
            name=(
                "ck_paper_accounts_"
                "cash_balance_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "max_position_size_sol > 0",
            name=(
                "ck_paper_accounts_"
                "max_position_positive"
            ),
        ),
        sa.CheckConstraint(
            "max_open_positions > 0",
            name=(
                "ck_paper_accounts_"
                "max_open_positions_positive"
            ),
        ),
        sa.CheckConstraint(
            "daily_loss_limit_sol > 0",
            name=(
                "ck_paper_accounts_"
                "daily_loss_limit_positive"
            ),
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_paper_accounts_id",
        "paper_accounts",
        ["id"],
        unique=False,
    )

    op.create_index(
        "ix_paper_accounts_name",
        "paper_accounts",
        ["name"],
        unique=True,
    )

    op.create_index(
        "ix_paper_accounts_status",
        "paper_accounts",
        ["status"],
        unique=False,
    )

    op.create_table(
        "paper_positions",
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
            "quantity",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "average_entry_price_sol",
            sa.Float(),
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
            "last_price_sol",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "market_value_sol",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "unrealized_pnl_sol",
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
            "status IN ('OPEN', 'CLOSED')",
            name="ck_paper_positions_status",
        ),
        sa.CheckConstraint(
            "quantity >= 0",
            name=(
                "ck_paper_positions_"
                "quantity_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "average_entry_price_sol >= 0",
            name=(
                "ck_paper_positions_"
                "entry_price_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "cost_basis_sol >= 0",
            name=(
                "ck_paper_positions_"
                "cost_basis_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "last_price_sol >= 0",
            name=(
                "ck_paper_positions_"
                "last_price_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "market_value_sol >= 0",
            name=(
                "ck_paper_positions_"
                "market_value_non_negative"
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
            "token_mint",
            name=(
                "uq_paper_positions_"
                "account_token"
            ),
        ),
    )

    op.create_index(
        "ix_paper_positions_id",
        "paper_positions",
        ["id"],
        unique=False,
    )

    op.create_index(
        "ix_paper_positions_account_id",
        "paper_positions",
        ["account_id"],
        unique=False,
    )

    op.create_index(
        "ix_paper_positions_token_mint",
        "paper_positions",
        ["token_mint"],
        unique=False,
    )

    op.create_index(
        "ix_paper_positions_status",
        "paper_positions",
        ["status"],
        unique=False,
    )

    op.create_table(
        "paper_orders",
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
            "position_id",
            sa.Integer(),
            nullable=True,
        ),
        sa.Column(
            "token_mint",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "side",
            sa.String(length=10),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column(
            "requested_value_sol",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "quantity",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "execution_price_sol",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "gross_value_sol",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "fee_sol",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "slippage_percent",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "signal_score",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "reason",
            sa.Text(),
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
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "side IN ('BUY', 'SELL')",
            name="ck_paper_orders_side",
        ),
        sa.CheckConstraint(
            "status IN "
            "('PENDING', 'FILLED', 'REJECTED')",
            name="ck_paper_orders_status",
        ),
        sa.CheckConstraint(
            "requested_value_sol >= 0",
            name=(
                "ck_paper_orders_"
                "requested_value_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "quantity >= 0",
            name=(
                "ck_paper_orders_"
                "quantity_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "execution_price_sol >= 0",
            name=(
                "ck_paper_orders_"
                "execution_price_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "gross_value_sol >= 0",
            name=(
                "ck_paper_orders_"
                "gross_value_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "fee_sol >= 0",
            name=(
                "ck_paper_orders_"
                "fee_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "slippage_percent >= 0",
            name=(
                "ck_paper_orders_"
                "slippage_non_negative"
            ),
        ),
        sa.CheckConstraint(
            "signal_score IS NULL OR "
            "(signal_score >= 0 "
            "AND signal_score <= 100)",
            name=(
                "ck_paper_orders_"
                "signal_score_range"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["paper_accounts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["position_id"],
            ["paper_positions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_index(
        "ix_paper_orders_id",
        "paper_orders",
        ["id"],
        unique=False,
    )

    op.create_index(
        "ix_paper_orders_account_id",
        "paper_orders",
        ["account_id"],
        unique=False,
    )

    op.create_index(
        "ix_paper_orders_position_id",
        "paper_orders",
        ["position_id"],
        unique=False,
    )

    op.create_index(
        "ix_paper_orders_token_mint",
        "paper_orders",
        ["token_mint"],
        unique=False,
    )

    op.create_index(
        "ix_paper_orders_side",
        "paper_orders",
        ["side"],
        unique=False,
    )

    op.create_index(
        "ix_paper_orders_status",
        "paper_orders",
        ["status"],
        unique=False,
    )

    op.create_index(
        "ix_paper_orders_executed_at",
        "paper_orders",
        ["executed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_paper_orders_executed_at",
        table_name="paper_orders",
    )

    op.drop_index(
        "ix_paper_orders_status",
        table_name="paper_orders",
    )

    op.drop_index(
        "ix_paper_orders_side",
        table_name="paper_orders",
    )

    op.drop_index(
        "ix_paper_orders_token_mint",
        table_name="paper_orders",
    )

    op.drop_index(
        "ix_paper_orders_position_id",
        table_name="paper_orders",
    )

    op.drop_index(
        "ix_paper_orders_account_id",
        table_name="paper_orders",
    )

    op.drop_index(
        "ix_paper_orders_id",
        table_name="paper_orders",
    )

    op.drop_table("paper_orders")

    op.drop_index(
        "ix_paper_positions_status",
        table_name="paper_positions",
    )

    op.drop_index(
        "ix_paper_positions_token_mint",
        table_name="paper_positions",
    )

    op.drop_index(
        "ix_paper_positions_account_id",
        table_name="paper_positions",
    )

    op.drop_index(
        "ix_paper_positions_id",
        table_name="paper_positions",
    )

    op.drop_table("paper_positions")

    op.drop_index(
        "ix_paper_accounts_status",
        table_name="paper_accounts",
    )

    op.drop_index(
        "ix_paper_accounts_name",
        table_name="paper_accounts",
    )

    op.drop_index(
        "ix_paper_accounts_id",
        table_name="paper_accounts",
    )

    op.drop_table("paper_accounts") 