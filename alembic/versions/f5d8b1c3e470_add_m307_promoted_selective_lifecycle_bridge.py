"""add M307 promoted selective lifecycle bridge tables

Revision ID: f5d8b1c3e470
Revises: e4c7a9d1b268
Create Date: 2026-09-01
"""

from alembic import op
import sqlalchemy as sa

revision = "f5d8b1c3e470"
down_revision = "e4c7a9d1b268"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canonical_parser_gen4_promoted_selective_activations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("activation_id", sa.String(length=36), nullable=False),
        sa.Column("wallet_address", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("activation_anchor_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_envelope_sha256", sa.String(length=64), nullable=False),
        sa.Column("formal_m306_report_sha256", sa.String(length=64), nullable=False),
        sa.Column("policy_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("decision_envelope", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("draining_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stopped_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('ACTIVE','DRAINING','STOPPED')",
            name="ck_gen4_promoted_selective_activation_status",
        ),
        sa.CheckConstraint(
            "length(decision_envelope_sha256) = 64",
            name="ck_gen4_promoted_selective_activation_decision_sha",
        ),
        sa.CheckConstraint(
            "length(formal_m306_report_sha256) = 64",
            name="ck_gen4_promoted_selective_activation_m306_sha",
        ),
        sa.CheckConstraint(
            "length(policy_hash) = 64",
            name="ck_gen4_promoted_selective_activation_policy_hash",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "activation_id",
            name="uq_gen4_promoted_selective_activation_id",
        ),
    )
    op.create_index(
        "uq_gen4_promoted_selective_active_wallet",
        "canonical_parser_gen4_promoted_selective_activations",
        ["wallet_address"],
        unique=True,
        postgresql_where=sa.text("status IN ('ACTIVE','DRAINING')"),
        sqlite_where=sa.text("status IN ('ACTIVE','DRAINING')"),
    )
    op.create_index(
        "ix_gen4_promoted_selective_activation_status_anchor",
        "canonical_parser_gen4_promoted_selective_activations",
        ["status", "activation_anchor_at"],
        unique=False,
    )

    op.create_table(
        "canonical_parser_gen4_promoted_selective_positions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("position_id", sa.String(length=36), nullable=False),
        sa.Column("scope", sa.String(length=48), nullable=False),
        sa.Column("activation_db_id", sa.Integer(), nullable=False),
        sa.Column("activation_id", sa.String(length=36), nullable=False),
        sa.Column("entry_fast_event_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("wallet_address", sa.String(length=64), nullable=False),
        sa.Column("token_mint", sa.String(length=64), nullable=False),
        sa.Column("token_decimals", sa.Integer(), nullable=False),
        sa.Column("entry_signature", sa.String(length=128), nullable=False),
        sa.Column("entry_source", sa.String(length=48), nullable=False),
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
        sa.Column(
            "realized_output_lamports",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "allocated_exit_fee_lamports",
            sa.BigInteger(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("pnl_lamports", sa.BigInteger(), nullable=True),
        sa.Column("return_percent", sa.Float(), nullable=True),
        sa.Column("last_exit_signature", sa.String(length=128), nullable=True),
        sa.Column("exit_quote_latency_ms", sa.Integer(), nullable=True),
        sa.Column("exit_price_impact_bps", sa.Float(), nullable=True),
        sa.Column(
            "exit_transaction_built",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "exit_copyable",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("close_reason", sa.String(length=80), nullable=True),
        sa.Column("entry_quote", sa.JSON(), nullable=False),
        sa.Column("exit_quotes", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
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
            "status IN ('OPEN','OPEN_PARTIAL','CLOSED')",
            name="ck_gen4_promoted_selective_position_status",
        ),
        sa.CheckConstraint(
            "scope = 'PROMOTED_CANDIDATE_FASTPATH_SELECTIVE'",
            name="ck_gen4_promoted_selective_position_scope",
        ),
        sa.CheckConstraint(
            "entry_input_lamports > 0 AND entry_output_token_raw > 0 "
            "AND remaining_token_raw >= 0 AND realized_output_lamports >= 0 "
            "AND allocated_entry_fee_lamports >= 0 "
            "AND allocated_exit_fee_lamports >= 0",
            name="ck_gen4_promoted_selective_position_amounts",
        ),
        sa.ForeignKeyConstraint(
            ["activation_db_id"],
            ["canonical_parser_gen4_promoted_selective_activations.id"],
            name="fk_gen4_promoted_selective_position_activation",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "position_id",
            name="uq_gen4_promoted_selective_position_id",
        ),
        sa.UniqueConstraint(
            "wallet_address",
            "entry_signature",
            name="uq_gen4_promoted_selective_wallet_entry_signature",
        ),
        sa.UniqueConstraint(
            "entry_fast_event_id",
            name="uq_gen4_promoted_selective_entry_event",
        ),
    )
    op.create_index(
        "ix_gen4_promoted_selective_open_wallet_token",
        "canonical_parser_gen4_promoted_selective_positions",
        ["status", "wallet_address", "token_mint"],
        unique=False,
    )
    op.create_index(
        "ix_gen4_promoted_selective_closed_at",
        "canonical_parser_gen4_promoted_selective_positions",
        ["closed_at"],
        unique=False,
    )
    op.create_index(
        "ix_gen4_promoted_selective_activation_wallet",
        "canonical_parser_gen4_promoted_selective_positions",
        ["activation_id", "wallet_address"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_gen4_promoted_selective_activation_wallet",
        table_name="canonical_parser_gen4_promoted_selective_positions",
    )
    op.drop_index(
        "ix_gen4_promoted_selective_closed_at",
        table_name="canonical_parser_gen4_promoted_selective_positions",
    )
    op.drop_index(
        "ix_gen4_promoted_selective_open_wallet_token",
        table_name="canonical_parser_gen4_promoted_selective_positions",
    )
    op.drop_table("canonical_parser_gen4_promoted_selective_positions")
    op.drop_index(
        "ix_gen4_promoted_selective_activation_status_anchor",
        table_name="canonical_parser_gen4_promoted_selective_activations",
    )
    op.drop_index(
        "uq_gen4_promoted_selective_active_wallet",
        table_name="canonical_parser_gen4_promoted_selective_activations",
    )
    op.drop_table("canonical_parser_gen4_promoted_selective_activations")
