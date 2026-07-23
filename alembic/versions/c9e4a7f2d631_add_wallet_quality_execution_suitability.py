"""add wallet quality and execution suitability

Revision ID: c9e4a7f2d631
Revises: b7d4e8f1c902
Create Date: 2026-07-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c9e4a7f2d631"
down_revision: str | None = "b7d4e8f1c902"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    columns = (
        sa.Column("quality_score", sa.Float(), server_default="0", nullable=False),
        sa.Column(
            "quality_classification",
            sa.String(length=24),
            server_default="NON_ANALIZZATO",
            nullable=False,
        ),
        sa.Column(
            "quality_eligible",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("quality_reasons", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("quality_calculated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "quality_sample_swaps_7d", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "meaningful_swaps_7d", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column("dust_swaps_7d", sa.Integer(), server_default="0", nullable=False),
        sa.Column("dust_ratio_7d", sa.Float(), server_default="0", nullable=False),
        sa.Column(
            "average_swap_sol_7d", sa.Float(), server_default="0", nullable=False
        ),
        sa.Column(
            "median_swap_sol_7d", sa.Float(), server_default="0", nullable=False
        ),
        sa.Column(
            "size_compatible_swaps_7d",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "size_compatibility_ratio_7d",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "average_size_compatibility_score_7d",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "buy_sell_balance_score_7d",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("unique_tokens_7d", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "top_token_concentration_7d",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "completed_token_pairs_7d",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "round_trip_token_ratio_7d",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "invalid_amount_swaps_7d",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    for column in columns:
        op.add_column("discovered_wallets", column)

    op.create_index(
        "ix_discovered_wallets_quality_score",
        "discovered_wallets",
        ["quality_score"],
        unique=False,
    )
    op.create_index(
        "ix_discovered_wallets_quality_classification",
        "discovered_wallets",
        ["quality_classification"],
        unique=False,
    )
    op.create_index(
        "ix_discovered_wallets_quality_eligible",
        "discovered_wallets",
        ["quality_eligible"],
        unique=False,
    )
    # Fail-closed: i wallet già idonei devono superare il nuovo controllo qualità.
    op.execute("UPDATE discovered_wallets SET eligible = false")

    op.add_column(
        "live_wallet_scores",
        sa.Column("quality_score", sa.Float(), server_default="0", nullable=False),
    )
    op.add_column(
        "live_wallet_scores",
        sa.Column(
            "quality_classification",
            sa.String(length=24),
            server_default="NON_ANALIZZATO",
            nullable=False,
        ),
    )
    op.add_column(
        "live_wallet_scores",
        sa.Column(
            "quality_eligible",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_live_wallet_scores_quality_classification",
        "live_wallet_scores",
        ["quality_classification"],
        unique=False,
    )
    op.execute("UPDATE live_wallet_scores SET eligible = false")


def downgrade() -> None:
    op.drop_index(
        "ix_live_wallet_scores_quality_classification",
        table_name="live_wallet_scores",
    )
    op.drop_column("live_wallet_scores", "quality_eligible")
    op.drop_column("live_wallet_scores", "quality_classification")
    op.drop_column("live_wallet_scores", "quality_score")

    op.drop_index(
        "ix_discovered_wallets_quality_eligible",
        table_name="discovered_wallets",
    )
    op.drop_index(
        "ix_discovered_wallets_quality_classification",
        table_name="discovered_wallets",
    )
    op.drop_index(
        "ix_discovered_wallets_quality_score",
        table_name="discovered_wallets",
    )
    for column_name in (
        "invalid_amount_swaps_7d",
        "round_trip_token_ratio_7d",
        "completed_token_pairs_7d",
        "top_token_concentration_7d",
        "unique_tokens_7d",
        "buy_sell_balance_score_7d",
        "average_size_compatibility_score_7d",
        "size_compatibility_ratio_7d",
        "size_compatible_swaps_7d",
        "median_swap_sol_7d",
        "average_swap_sol_7d",
        "dust_ratio_7d",
        "dust_swaps_7d",
        "meaningful_swaps_7d",
        "quality_sample_swaps_7d",
        "quality_calculated_at",
        "quality_reasons",
        "quality_eligible",
        "quality_classification",
        "quality_score",
    ):
        op.drop_column("discovered_wallets", column_name)
