"""add live platform phases 1 2 3

Revision ID: b6f2e8c9d401
Revises: a8d4c2e7f901
Create Date: 2026-07-20
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "b6f2e8c9d401"
down_revision: str | None = "a8d4c2e7f901"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "live_platform_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("analytics_starting_equity_sol", sa.Float(), server_default="1.0", nullable=False),
        sa.Column("auto_wallet_selection_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("max_source_wallets", sa.Integer(), server_default="20", nullable=False),
        sa.Column("min_wallet_smart_score", sa.Float(), server_default="60", nullable=False),
        sa.Column("token_safety_enabled", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("token_safety_fail_closed", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("token_allowlist_mode", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("token_allowlist", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("token_blocklist", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("min_token_liquidity_usd", sa.Float(), server_default="10000", nullable=False),
        sa.Column("min_token_market_cap_usd", sa.Float(), server_default="0", nullable=False),
        sa.Column("min_token_volume_24h_usd", sa.Float(), server_default="5000", nullable=False),
        sa.Column("max_top_holder_percent", sa.Float(), server_default="35", nullable=False),
        sa.Column("max_token_risk_score", sa.Integer(), server_default="60", nullable=False),
        sa.Column("require_rugcheck_pass", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("reject_honeypot", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("require_disabled_mint_authority", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("require_disabled_freeze_authority", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("safety_snapshot_max_age_seconds", sa.Integer(), server_default="300", nullable=False),
        sa.Column("live_arm_ttl_minutes", sa.Integer(), server_default="15", nullable=False),
        sa.Column("live_armed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("max_source_wallets BETWEEN 1 AND 50", name="ck_live_platform_max_source_wallets"),
        sa.CheckConstraint("min_wallet_smart_score BETWEEN 0 AND 100", name="ck_live_platform_min_wallet_score"),
        sa.CheckConstraint("max_top_holder_percent BETWEEN 0 AND 100", name="ck_live_platform_max_holder"),
        sa.CheckConstraint("max_token_risk_score BETWEEN 0 AND 100", name="ck_live_platform_max_risk"),
        sa.CheckConstraint("live_arm_ttl_minutes BETWEEN 1 AND 60", name="ck_live_platform_arm_ttl"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_index("ix_live_platform_configs_id", "live_platform_configs", ["id"])
    op.create_index("ix_live_platform_configs_name", "live_platform_configs", ["name"])
    op.create_index("ix_live_platform_configs_live_armed_until", "live_platform_configs", ["live_armed_until"])

    op.create_table(
        "token_safety_snapshots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("token_mint", sa.String(length=64), nullable=False),
        sa.Column("liquidity_usd", sa.Float(), server_default="0", nullable=False),
        sa.Column("market_cap_usd", sa.Float(), server_default="0", nullable=False),
        sa.Column("volume_24h_usd", sa.Float(), server_default="0", nullable=False),
        sa.Column("top_holder_percent", sa.Float(), server_default="100", nullable=False),
        sa.Column("risk_score", sa.Integer(), server_default="100", nullable=False),
        sa.Column("honeypot", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("mint_authority_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("freeze_authority_enabled", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("rugged", sa.Boolean(), nullable=True),
        sa.Column("rugcheck_passed", sa.Boolean(), nullable=True),
        sa.Column("source", sa.String(length=120), nullable=False),
        sa.Column("reasons", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_mint"),
    )
    op.create_index("ix_token_safety_snapshots_id", "token_safety_snapshots", ["id"])
    op.create_index("ix_token_safety_snapshots_token_mint", "token_safety_snapshots", ["token_mint"])
    op.create_index("ix_token_safety_snapshots_fetched_at", "token_safety_snapshots", ["fetched_at"])

    op.create_table(
        "live_wallet_scores",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("wallet_address", sa.String(length=64), nullable=False),
        sa.Column("smart_score", sa.Float(), server_default="0", nullable=False),
        sa.Column("profile_score", sa.Float(), server_default="0", nullable=False),
        sa.Column("live_performance_score", sa.Float(), server_default="50", nullable=False),
        sa.Column("win_rate_percent", sa.Float(), server_default="0", nullable=False),
        sa.Column("roi_percent", sa.Float(), server_default="0", nullable=False),
        sa.Column("realized_pnl_sol", sa.Float(), server_default="0", nullable=False),
        sa.Column("closed_trades", sa.Integer(), server_default="0", nullable=False),
        sa.Column("rank", sa.Integer(), server_default="0", nullable=False),
        sa.Column("eligible", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("reasons", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("wallet_address"),
    )
    op.create_index("ix_live_wallet_scores_id", "live_wallet_scores", ["id"])
    op.create_index("ix_live_wallet_scores_wallet_address", "live_wallet_scores", ["wallet_address"])
    op.create_index("ix_live_wallet_scores_smart_score", "live_wallet_scores", ["smart_score"])
    op.create_index("ix_live_wallet_scores_rank", "live_wallet_scores", ["rank"])
    op.create_index("ix_live_wallet_scores_eligible", "live_wallet_scores", ["eligible"])
    op.create_index("ix_live_wallet_scores_calculated_at", "live_wallet_scores", ["calculated_at"])


def downgrade() -> None:
    op.drop_table("live_wallet_scores")
    op.drop_table("token_safety_snapshots")
    op.drop_table("live_platform_configs")
