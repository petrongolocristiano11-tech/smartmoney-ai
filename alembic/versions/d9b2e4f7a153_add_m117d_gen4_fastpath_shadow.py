"""add M117D Gen4 processed WSS fastpath shadow audit

Revision ID: d9b2e4f7a153
Revises: c8a1f3d6e942
Create Date: 2026-08-19
"""

from alembic import op
import sqlalchemy as sa

revision = "d9b2e4f7a153"
down_revision = "c8a1f3d6e942"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canonical_parser_gen4_fastpath_shadow_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("signature", sa.String(length=128), nullable=False),
        sa.Column("slot", sa.BigInteger(), nullable=True),
        sa.Column("wallet_address", sa.String(length=64), nullable=False),
        sa.Column("matched_wallets", sa.JSON(), nullable=False),
        sa.Column("campaign_id", sa.String(length=36), nullable=True),
        sa.Column("commitment", sa.String(length=16), nullable=False),
        sa.Column("fast_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fast_parse_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fast_quote_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fast_quote_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fast_prequote_ms", sa.Integer(), nullable=True),
        sa.Column("fast_quote_latency_ms", sa.Integer(), nullable=True),
        sa.Column("fast_end_to_quote_ms", sa.Integer(), nullable=True),
        sa.Column("side", sa.String(length=8), nullable=True),
        sa.Column("token_mint", sa.String(length=64), nullable=True),
        sa.Column("token_decimals", sa.Integer(), nullable=True),
        sa.Column("wallet_effective_price_sol", sa.Float(), nullable=True),
        sa.Column("fast_price_deterioration_bps", sa.Float(), nullable=True),
        sa.Column("fast_price_impact_bps", sa.Float(), nullable=True),
        sa.Column("fast_out_amount", sa.BigInteger(), nullable=True),
        sa.Column("fast_transaction_built", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fast_provisional_copyable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fast_provisional_rejection_reason", sa.String(length=120), nullable=True),
        sa.Column("parse_error_code", sa.String(length=120), nullable=True),
        sa.Column("quote_error_code", sa.String(length=120), nullable=True),
        sa.Column("webhook_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("webhook_block_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("webhook_reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fast_lead_vs_webhook_ms", sa.Integer(), nullable=True),
        sa.Column("confirmed_path_quote_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_path_end_to_quote_ms", sa.Integer(), nullable=True),
        sa.Column("fast_reconciled_copyable", sa.Boolean(), nullable=True),
        sa.Column("fast_reconciled_rejection_reason", sa.String(length=120), nullable=True),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("delivery_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", name="uq_gen4_fastpath_event_id"),
        sa.UniqueConstraint("signature", "wallet_address", name="uq_gen4_fastpath_signature_wallet"),
    )
    op.create_index("ix_gen4_fastpath_received", "canonical_parser_gen4_fastpath_shadow_events", ["fast_received_at"], unique=False)
    op.create_index("ix_gen4_fastpath_reconciled", "canonical_parser_gen4_fastpath_shadow_events", ["webhook_reconciled_at"], unique=False)
    op.create_index("ix_gen4_fastpath_wallet_received", "canonical_parser_gen4_fastpath_shadow_events", ["wallet_address", "fast_received_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_gen4_fastpath_wallet_received", table_name="canonical_parser_gen4_fastpath_shadow_events")
    op.drop_index("ix_gen4_fastpath_reconciled", table_name="canonical_parser_gen4_fastpath_shadow_events")
    op.drop_index("ix_gen4_fastpath_received", table_name="canonical_parser_gen4_fastpath_shadow_events")
    op.drop_table("canonical_parser_gen4_fastpath_shadow_events")
