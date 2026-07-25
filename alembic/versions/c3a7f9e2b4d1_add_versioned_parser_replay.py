"""add versioned parser registry replay foundation

Revision ID: c3a7f9e2b4d1
Revises: b1c9e4f7a2d6
Create Date: 2026-07-25
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c3a7f9e2b4d1"
down_revision: str | None = "b1c9e4f7a2d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_REPLAY_STATUSES = "'RUNNING', 'COMPLETED', 'PARTIAL', 'FAILED'"
_SELECTION_MODES = "'UNNORMALIZED', 'OUTDATED', 'REPROCESS'"


def upgrade() -> None:
    op.create_table(
        "normalization_replay_batches",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("replay_id", sa.String(length=36), nullable=False),
        sa.Column("parser_name", sa.String(length=80), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column(
            "parser_implementation_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("selection_mode", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="RUNNING",
            nullable=False,
        ),
        sa.Column(
            "request_filters",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column("requested_limit", sa.Integer(), nullable=False),
        sa.Column(
            "selected_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "processed_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "completed_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "failed_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "skipped_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
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
            f"status IN ({_REPLAY_STATUSES})",
            name="ck_normalization_replay_batches_status",
        ),
        sa.CheckConstraint(
            f"selection_mode IN ({_SELECTION_MODES})",
            name="ck_normalization_replay_batches_selection_mode",
        ),
        sa.CheckConstraint(
            "requested_limit >= 1",
            name="ck_normalization_replay_batches_limit_positive",
        ),
        sa.CheckConstraint(
            "length(parser_implementation_hash) = 64",
            name="ck_normalization_replay_batches_implementation_hash_length",
        ),
        sa.CheckConstraint(
            "selected_count >= 0 AND processed_count >= 0 "
            "AND completed_count >= 0 AND failed_count >= 0 "
            "AND skipped_count >= 0",
            name="ck_normalization_replay_batches_counts_nonnegative",
        ),
        sa.UniqueConstraint(
            "replay_id",
            name="uq_normalization_replay_batches_replay_id",
        ),
    )
    op.create_index(
        "ix_normalization_replay_batches_parser_version_status",
        "normalization_replay_batches",
        ["parser_name", "parser_version", "status"],
        unique=False,
    )
    op.create_index(
        "ix_normalization_replay_batches_status_created_at",
        "normalization_replay_batches",
        ["status", "created_at"],
        unique=False,
    )

    op.create_table(
        "normalization_artifacts",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("normalization_run_id", sa.BigInteger(), nullable=False),
        sa.Column("raw_event_id", sa.BigInteger(), nullable=False),
        sa.Column("parser_name", sa.String(length=80), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column(
            "parser_implementation_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("artifact_type", sa.String(length=80), nullable=False),
        sa.Column("artifact_index", sa.Integer(), nullable=False),
        sa.Column("schema_version", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "artifact_metadata",
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
            "artifact_index >= 0",
            name="ck_normalization_artifacts_index_nonnegative",
        ),
        sa.CheckConstraint(
            "length(payload_hash) = 64",
            name="ck_normalization_artifacts_payload_hash_length",
        ),
        sa.CheckConstraint(
            "length(parser_implementation_hash) = 64",
            name="ck_normalization_artifacts_implementation_hash_length",
        ),
        sa.ForeignKeyConstraint(
            ["normalization_run_id"],
            ["normalization_runs.id"],
            name="fk_normalization_artifacts_run_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["raw_event_id"],
            ["raw_blockchain_events.id"],
            name="fk_normalization_artifacts_raw_event_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "raw_event_id",
            "parser_name",
            "parser_version",
            "artifact_type",
            "artifact_index",
            name="uq_normalization_artifacts_event_parser_output",
        ),
    )
    op.create_index(
        "ix_normalization_artifacts_run_index",
        "normalization_artifacts",
        ["normalization_run_id", "artifact_index"],
        unique=False,
    )
    op.create_index(
        "ix_normalization_artifacts_event_parser_version",
        "normalization_artifacts",
        ["raw_event_id", "parser_name", "parser_version"],
        unique=False,
    )
    op.create_index(
        "ix_normalization_artifacts_payload_hash",
        "normalization_artifacts",
        ["payload_hash"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_normalization_artifacts_payload_hash",
        table_name="normalization_artifacts",
    )
    op.drop_index(
        "ix_normalization_artifacts_event_parser_version",
        table_name="normalization_artifacts",
    )
    op.drop_index(
        "ix_normalization_artifacts_run_index",
        table_name="normalization_artifacts",
    )
    op.drop_table("normalization_artifacts")

    op.drop_index(
        "ix_normalization_replay_batches_status_created_at",
        table_name="normalization_replay_batches",
    )
    op.drop_index(
        "ix_normalization_replay_batches_parser_version_status",
        table_name="normalization_replay_batches",
    )
    op.drop_table("normalization_replay_batches")
