"""add active wallet discovery and ranking

Revision ID: a3f7c9d2e641
Revises: e2f9a6b4c731
Create Date: 2026-07-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "a3f7c9d2e641"
down_revision: str | None = "e2f9a6b4c731"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    discovered_columns = (
        sa.Column("ranking_score", sa.Float(), server_default="0", nullable=False),
        sa.Column("last_swap_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("swaps_24h", sa.Integer(), server_default="0", nullable=False),
        sa.Column("swaps_7d", sa.Integer(), server_default="0", nullable=False),
        sa.Column("buys_24h", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sells_24h", sa.Integer(), server_default="0", nullable=False),
        sa.Column("buys_7d", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sells_7d", sa.Integer(), server_default="0", nullable=False),
        sa.Column("volume_24h_sol", sa.Float(), server_default="0", nullable=False),
        sa.Column("volume_7d_sol", sa.Float(), server_default="0", nullable=False),
        sa.Column("active_days_7d", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "average_swaps_per_active_day_7d",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("average_minutes_between_swaps_7d", sa.Float(), nullable=True),
        sa.Column("activity_score", sa.Float(), server_default="0", nullable=False),
        sa.Column(
            "activity_classification",
            sa.String(length=24),
            server_default="NON_ANALIZZATO",
            nullable=False,
        ),
        sa.Column(
            "activity_eligible",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("activity_reasons", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("activity_calculated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "eligible",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "eligibility_reasons",
            sa.JSON(),
            server_default="[]",
            nullable=False,
        ),
    )
    for column in discovered_columns:
        op.add_column("discovered_wallets", column)

    op.create_index(
        "ix_discovered_wallets_ranking_score",
        "discovered_wallets",
        ["ranking_score"],
        unique=False,
    )
    op.create_index(
        "ix_discovered_wallets_last_swap_at",
        "discovered_wallets",
        ["last_swap_at"],
        unique=False,
    )
    op.create_index(
        "ix_discovered_wallets_activity_score",
        "discovered_wallets",
        ["activity_score"],
        unique=False,
    )
    op.create_index(
        "ix_discovered_wallets_activity_classification",
        "discovered_wallets",
        ["activity_classification"],
        unique=False,
    )
    op.create_index(
        "ix_discovered_wallets_activity_eligible",
        "discovered_wallets",
        ["activity_eligible"],
        unique=False,
    )
    op.create_index(
        "ix_discovered_wallets_eligible",
        "discovered_wallets",
        ["eligible"],
        unique=False,
    )

    live_columns = (
        sa.Column("activity_score", sa.Float(), server_default="0", nullable=False),
        sa.Column(
            "activity_classification",
            sa.String(length=24),
            server_default="NON_ANALIZZATO",
            nullable=False,
        ),
        sa.Column("last_swap_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("swaps_24h", sa.Integer(), server_default="0", nullable=False),
        sa.Column("swaps_7d", sa.Integer(), server_default="0", nullable=False),
        sa.Column("buys_7d", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sells_7d", sa.Integer(), server_default="0", nullable=False),
        sa.Column("volume_7d_sol", sa.Float(), server_default="0", nullable=False),
        sa.Column("active_days_7d", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "average_swaps_per_active_day_7d",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("average_minutes_between_swaps_7d", sa.Float(), nullable=True),
    )
    for column in live_columns:
        op.add_column("live_wallet_scores", column)

    op.create_index(
        "ix_live_wallet_scores_activity_classification",
        "live_wallet_scores",
        ["activity_classification"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_live_wallet_scores_activity_classification",
        table_name="live_wallet_scores",
    )
    for column_name in (
        "average_minutes_between_swaps_7d",
        "average_swaps_per_active_day_7d",
        "active_days_7d",
        "volume_7d_sol",
        "sells_7d",
        "buys_7d",
        "swaps_7d",
        "swaps_24h",
        "last_swap_at",
        "activity_classification",
        "activity_score",
    ):
        op.drop_column("live_wallet_scores", column_name)

    for index_name in (
        "ix_discovered_wallets_eligible",
        "ix_discovered_wallets_activity_eligible",
        "ix_discovered_wallets_activity_classification",
        "ix_discovered_wallets_activity_score",
        "ix_discovered_wallets_last_swap_at",
        "ix_discovered_wallets_ranking_score",
    ):
        op.drop_index(index_name, table_name="discovered_wallets")

    for column_name in (
        "eligibility_reasons",
        "eligible",
        "activity_calculated_at",
        "activity_reasons",
        "activity_eligible",
        "activity_classification",
        "activity_score",
        "average_minutes_between_swaps_7d",
        "average_swaps_per_active_day_7d",
        "active_days_7d",
        "volume_7d_sol",
        "volume_24h_sol",
        "sells_7d",
        "buys_7d",
        "sells_24h",
        "buys_24h",
        "swaps_7d",
        "swaps_24h",
        "last_swap_at",
        "ranking_score",
    ):
        op.drop_column("discovered_wallets", column_name)
