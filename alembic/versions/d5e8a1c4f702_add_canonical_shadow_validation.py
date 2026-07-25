"""add canonical normalization and shadow validation

Revision ID: d5e8a1c4f702
Revises: c3a7f9e2b4d1
Create Date: 2026-07-25
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "d5e8a1c4f702"
down_revision: str | None = "c3a7f9e2b4d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "canonical_normalized_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("canonical_event_id", sa.String(length=36), nullable=False),
        sa.Column("canonical_event_key", sa.String(length=64), nullable=False),
        sa.Column("normalization_artifact_id", sa.BigInteger(), nullable=False),
        sa.Column("normalization_run_id", sa.BigInteger(), nullable=False),
        sa.Column("raw_event_id", sa.BigInteger(), nullable=False),
        sa.Column("parser_name", sa.String(length=80), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column(
            "parser_implementation_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("canonical_type", sa.String(length=32), nullable=False),
        sa.Column(
            "transaction_signature",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column("observed_wallet", sa.String(length=64), nullable=True),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=True),
        sa.Column("token_mint", sa.String(length=64), nullable=True),
        sa.Column("token_amount", sa.Numeric(38, 18), nullable=True),
        sa.Column("sol_amount", sa.Numeric(38, 18), nullable=True),
        sa.Column("fee_lamports", sa.BigInteger(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("block_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("quality_status", sa.String(length=16), nullable=False),
        sa.Column(
            "quality_flags",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("canonical_payload", sa.JSON(), nullable=False),
        sa.Column("canonical_payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "technical_metadata",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
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
            "quality_status IN ('PASS', 'WARN', 'FAIL')",
            name="ck_canonical_normalized_events_quality_status",
        ),
        sa.CheckConstraint(
            "side IN ('BUY', 'SELL', 'UNKNOWN')",
            name="ck_canonical_normalized_events_side",
        ),
        sa.CheckConstraint(
            "length(canonical_event_key) = 64",
            name="ck_canonical_normalized_events_key_length",
        ),
        sa.CheckConstraint(
            "length(canonical_payload_hash) = 64",
            name="ck_canonical_normalized_events_payload_hash_length",
        ),
        sa.CheckConstraint(
            "length(parser_implementation_hash) = 64",
            name="ck_canonical_normalized_events_implementation_hash_length",
        ),
        sa.ForeignKeyConstraint(
            ["normalization_artifact_id"],
            ["normalization_artifacts.id"],
            name="fk_canonical_normalized_events_artifact_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["normalization_run_id"],
            ["normalization_runs.id"],
            name="fk_canonical_normalized_events_run_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["raw_event_id"],
            ["raw_blockchain_events.id"],
            name="fk_canonical_normalized_events_raw_event_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "canonical_event_id",
            name="uq_canonical_normalized_events_canonical_event_id",
        ),
        sa.UniqueConstraint(
            "normalization_artifact_id",
            name="uq_canonical_normalized_events_artifact_id",
        ),
        sa.UniqueConstraint(
            "canonical_event_key",
            name="uq_canonical_normalized_events_event_key",
        ),
    )
    op.create_index(
        "ix_canonical_normalized_events_signature_wallet",
        "canonical_normalized_events",
        ["transaction_signature", "observed_wallet"],
        unique=False,
    )
    op.create_index(
        "ix_canonical_normalized_events_parser_version",
        "canonical_normalized_events",
        ["parser_name", "parser_version"],
        unique=False,
    )
    op.create_index(
        "ix_canonical_normalized_events_block_time",
        "canonical_normalized_events",
        ["block_time"],
        unique=False,
    )
    op.create_index(
        "ix_canonical_normalized_events_quality_created",
        "canonical_normalized_events",
        ["quality_status", "created_at"],
        unique=False,
    )

    op.create_table(
        "canonical_shadow_validation_batches",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("validation_id", sa.String(length=36), nullable=False),
        sa.Column("comparator_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column(
            "request_filters",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("requested_limit", sa.Integer(), nullable=False),
        sa.Column("selected_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("processed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("match_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("mismatch_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "missing_trade_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "not_comparable_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("failed_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "technical_metadata",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
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
            "status IN ('RUNNING', 'COMPLETED', 'PARTIAL', 'FAILED')",
            name="ck_canonical_shadow_validation_batches_status",
        ),
        sa.CheckConstraint(
            "requested_limit >= 1",
            name="ck_canonical_shadow_validation_batches_limit_positive",
        ),
        sa.CheckConstraint(
            "selected_count >= 0 AND processed_count >= 0 "
            "AND match_count >= 0 AND mismatch_count >= 0 "
            "AND missing_trade_count >= 0 AND not_comparable_count >= 0 "
            "AND failed_count >= 0",
            name="ck_canonical_shadow_validation_batches_counts_nonnegative",
        ),
        sa.UniqueConstraint(
            "validation_id",
            name="uq_canonical_shadow_validation_batches_validation_id",
        ),
    )
    op.create_index(
        "ix_canonical_shadow_validation_batches_status_created",
        "canonical_shadow_validation_batches",
        ["status", "created_at"],
        unique=False,
    )

    op.create_table(
        "canonical_shadow_validation_results",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("validation_batch_id", sa.BigInteger(), nullable=False),
        sa.Column("canonical_event_id", sa.BigInteger(), nullable=False),
        sa.Column("trade_id", sa.Integer(), nullable=True),
        sa.Column(
            "transaction_signature",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column("comparator_version", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column(
            "mismatch_fields",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("canonical_snapshot", sa.JSON(), nullable=False),
        sa.Column("trade_snapshot", sa.JSON(), nullable=True),
        sa.Column("canonical_snapshot_hash", sa.String(length=64), nullable=False),
        sa.Column("trade_snapshot_hash", sa.String(length=64), nullable=True),
        sa.Column(
            "technical_metadata",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('MATCH', 'MISMATCH', 'MISSING_TRADE', 'NOT_COMPARABLE')",
            name="ck_canonical_shadow_validation_results_status",
        ),
        sa.CheckConstraint(
            "length(canonical_snapshot_hash) = 64",
            name="ck_canonical_shadow_validation_results_canonical_hash_length",
        ),
        sa.CheckConstraint(
            "trade_snapshot_hash IS NULL OR length(trade_snapshot_hash) = 64",
            name="ck_canonical_shadow_validation_results_trade_hash_length",
        ),
        sa.ForeignKeyConstraint(
            ["validation_batch_id"],
            ["canonical_shadow_validation_batches.id"],
            name="fk_canonical_shadow_validation_results_batch_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["canonical_event_id"],
            ["canonical_normalized_events.id"],
            name="fk_canonical_shadow_validation_results_event_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["trade_id"],
            ["trades.id"],
            name="fk_canonical_shadow_validation_results_trade_id",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint(
            "validation_batch_id",
            "canonical_event_id",
            name="uq_canonical_shadow_validation_results_batch_event",
        ),
    )
    op.create_index(
        "ix_canonical_shadow_validation_results_status_created",
        "canonical_shadow_validation_results",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_canonical_shadow_validation_results_signature",
        "canonical_shadow_validation_results",
        ["transaction_signature"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_canonical_shadow_validation_results_signature",
        table_name="canonical_shadow_validation_results",
    )
    op.drop_index(
        "ix_canonical_shadow_validation_results_status_created",
        table_name="canonical_shadow_validation_results",
    )
    op.drop_table("canonical_shadow_validation_results")

    op.drop_index(
        "ix_canonical_shadow_validation_batches_status_created",
        table_name="canonical_shadow_validation_batches",
    )
    op.drop_table("canonical_shadow_validation_batches")

    op.drop_index(
        "ix_canonical_normalized_events_quality_created",
        table_name="canonical_normalized_events",
    )
    op.drop_index(
        "ix_canonical_normalized_events_block_time",
        table_name="canonical_normalized_events",
    )
    op.drop_index(
        "ix_canonical_normalized_events_parser_version",
        table_name="canonical_normalized_events",
    )
    op.drop_index(
        "ix_canonical_normalized_events_signature_wallet",
        table_name="canonical_normalized_events",
    )
    op.drop_table("canonical_normalized_events")
