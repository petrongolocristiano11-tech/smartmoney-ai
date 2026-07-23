"""add controlled discovery hydration

Revision ID: b7d4e8f1c902
Revises: a3f7c9d2e641
Create Date: 2026-07-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "b7d4e8f1c902"
down_revision: str | None = "a3f7c9d2e641"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = (
        sa.Column(
            "hydration_status",
            sa.String(length=24),
            server_default="NEVER",
            nullable=False,
        ),
        sa.Column("hydration_run_id", sa.String(length=36), nullable=True),
        sa.Column(
            "hydration_last_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "hydration_last_success_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "hydration_lookback_days",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "hydration_transactions_found",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "hydration_swaps_found",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "hydration_trades_imported",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "hydration_trades_updated",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "hydration_parse_failures",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "hydration_helius_requests",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("hydration_error_code", sa.String(length=64), nullable=True),
        sa.Column("hydration_error_message", sa.String(length=500), nullable=True),
    )
    for column in columns:
        op.add_column("discovered_wallets", column)

    op.create_index(
        "ix_discovered_wallets_hydration_status",
        "discovered_wallets",
        ["hydration_status"],
        unique=False,
    )
    op.create_index(
        "ix_discovered_wallets_hydration_last_attempt_at",
        "discovered_wallets",
        ["hydration_last_attempt_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_discovered_wallets_hydration_last_attempt_at",
        table_name="discovered_wallets",
    )
    op.drop_index(
        "ix_discovered_wallets_hydration_status",
        table_name="discovered_wallets",
    )
    for column_name in (
        "hydration_error_message",
        "hydration_error_code",
        "hydration_helius_requests",
        "hydration_parse_failures",
        "hydration_trades_updated",
        "hydration_trades_imported",
        "hydration_swaps_found",
        "hydration_transactions_found",
        "hydration_lookback_days",
        "hydration_last_success_at",
        "hydration_last_attempt_at",
        "hydration_run_id",
        "hydration_status",
    ):
        op.drop_column("discovered_wallets", column_name)
