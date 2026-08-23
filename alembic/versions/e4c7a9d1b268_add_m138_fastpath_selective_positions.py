"""add M138 fastpath selective position shadow

Revision ID: e4c7a9d1b268
Revises: d9b2e4f7a153
Create Date: 2026-08-23
"""

from alembic import op
import sqlalchemy as sa

revision = "e4c7a9d1b268"
down_revision = "d9b2e4f7a153"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canonical_parser_gen4_fastpath_selective_positions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("position_id", sa.String(length=36), nullable=False),
        sa.Column("scope", sa.String(length=40), nullable=False),
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("entry_fast_event_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("wallet_address", sa.String(length=64), nullable=False),
        sa.Column("token_mint", sa.String(length=64), nullable=False),
        sa.Column("token_decimals", sa.Integer(), nullable=False),
        sa.Column("entry_signature", sa.String(length=128), nullable=False),
        sa.Column("entry_source", sa.String(length=40), nullable=False),
        sa.Column("entry_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entry_quote_latency_ms", sa.Integer(), nullable=False),
        sa.Column("entry_price_deterioration_bps", sa.Float(), nullable=True),
        sa.Column("entry_price_impact_bps", sa.Float(), nullable=False),
        sa.Column("entry_transaction_built", sa.Boolean(), nullable=False),
        sa.Column("entry_input_lamports", sa.BigInteger(), nullable=False),
        sa.Column("entry_output_token_raw", sa.BigInteger(), nullable=False),
        sa.Column("remaining_token_raw", sa.BigInteger(), nullable=False),
        sa.Column("allocated_entry_fee_lamports", sa.BigInteger(), nullable=False),
        sa.Column("realized_output_lamports", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("allocated_exit_fee_lamports", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("pnl_lamports", sa.BigInteger(), nullable=True),
        sa.Column("return_percent", sa.Float(), nullable=True),
        sa.Column("last_exit_signature", sa.String(length=128), nullable=True),
        sa.Column("exit_quote_latency_ms", sa.Integer(), nullable=True),
        sa.Column("exit_price_impact_bps", sa.Float(), nullable=True),
        sa.Column("exit_transaction_built", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("exit_copyable", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("close_reason", sa.String(length=80), nullable=True),
        sa.Column("entry_quote", sa.JSON(), nullable=False),
        sa.Column("exit_quotes", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('OPEN','OPEN_PARTIAL','CLOSED')",
            name="ck_gen4_fastpath_selective_position_status",
        ),
        sa.CheckConstraint(
            "scope = 'OFFICIAL_FASTPATH_SELECTIVE'",
            name="ck_gen4_fastpath_selective_position_scope",
        ),
        sa.CheckConstraint(
            "entry_input_lamports > 0 AND entry_output_token_raw > 0 "
            "AND remaining_token_raw >= 0 AND realized_output_lamports >= 0 "
            "AND allocated_entry_fee_lamports >= 0 AND allocated_exit_fee_lamports >= 0",
            name="ck_gen4_fastpath_selective_position_amounts",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("position_id", name="uq_gen4_fastpath_selective_position_id"),
        sa.UniqueConstraint(
            "wallet_address",
            "entry_signature",
            name="uq_gen4_fastpath_selective_wallet_entry_signature",
        ),
        sa.UniqueConstraint(
            "entry_fast_event_id",
            name="uq_gen4_fastpath_selective_entry_event",
        ),
    )
    op.create_index(
        "ix_gen4_fastpath_selective_open_wallet_token",
        "canonical_parser_gen4_fastpath_selective_positions",
        ["status", "wallet_address", "token_mint"],
        unique=False,
    )
    op.create_index(
        "ix_gen4_fastpath_selective_closed_at",
        "canonical_parser_gen4_fastpath_selective_positions",
        ["closed_at"],
        unique=False,
    )
    op.create_index(
        "ix_gen4_fastpath_selective_campaign_wallet",
        "canonical_parser_gen4_fastpath_selective_positions",
        ["campaign_id", "wallet_address"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_gen4_fastpath_selective_campaign_wallet",
        table_name="canonical_parser_gen4_fastpath_selective_positions",
    )
    op.drop_index(
        "ix_gen4_fastpath_selective_closed_at",
        table_name="canonical_parser_gen4_fastpath_selective_positions",
    )
    op.drop_index(
        "ix_gen4_fastpath_selective_open_wallet_token",
        table_name="canonical_parser_gen4_fastpath_selective_positions",
    )
    op.drop_table("canonical_parser_gen4_fastpath_selective_positions")
