"""add live-grade integrity foundation

Revision ID: b1c9e4f7a2d6
Revises: e8a4c6d0f153
Create Date: 2026-07-25
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "b1c9e4f7a2d6"
down_revision: str | None = "e8a4c6d0f153"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_NORMALIZATION_STATUSES = (
    "'PENDING', 'RUNNING', 'COMPLETED', "
    "'PARTIAL', 'FAILED', 'SKIPPED'"
)


def upgrade() -> None:
    op.create_table(
        "raw_blockchain_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("chain", sa.String(length=32), nullable=False),
        sa.Column("network", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column(
            "transaction_signature",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column("slot", sa.BigInteger(), nullable=True),
        sa.Column(
            "block_time",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "observed_wallet",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "commitment",
            sa.String(length=32),
            nullable=True,
        ),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("payload_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "deduplication_key",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "event_metadata",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "observation_count",
            sa.Integer(),
            server_default="1",
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
            "observation_count >= 1",
            name="ck_raw_blockchain_events_observation_count_positive",
        ),
        sa.CheckConstraint(
            "slot IS NULL OR slot >= 0",
            name="ck_raw_blockchain_events_slot_nonnegative",
        ),
        sa.CheckConstraint(
            "length(payload_hash) = 64",
            name="ck_raw_blockchain_events_payload_hash_length",
        ),
        sa.CheckConstraint(
            "length(deduplication_key) = 64",
            name="ck_raw_blockchain_events_deduplication_key_length",
        ),
        sa.UniqueConstraint(
            "deduplication_key",
            name="uq_raw_blockchain_events_deduplication_key",
        ),
    )
    op.create_index(
        "ix_raw_blockchain_events_provider_chain_network",
        "raw_blockchain_events",
        ["provider", "chain", "network"],
        unique=False,
    )
    op.create_index(
        "ix_raw_blockchain_events_signature",
        "raw_blockchain_events",
        ["transaction_signature"],
        unique=False,
    )
    op.create_index(
        "ix_raw_blockchain_events_wallet_first_seen",
        "raw_blockchain_events",
        ["observed_wallet", "first_seen_at"],
        unique=False,
    )
    op.create_index(
        "ix_raw_blockchain_events_block_time",
        "raw_blockchain_events",
        ["block_time"],
        unique=False,
    )
    op.create_index(
        "ix_raw_blockchain_events_payload_hash",
        "raw_blockchain_events",
        ["payload_hash"],
        unique=False,
    )

    op.create_table(
        "normalization_runs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("raw_event_id", sa.BigInteger(), nullable=False),
        sa.Column("parser_name", sa.String(length=80), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default="PENDING",
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "produced_event_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "produced_trade_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "warnings",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
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
            f"status IN ({_NORMALIZATION_STATUSES})",
            name="ck_normalization_runs_status",
        ),
        sa.CheckConstraint(
            "produced_event_count >= 0",
            name="ck_normalization_runs_event_count_nonnegative",
        ),
        sa.CheckConstraint(
            "produced_trade_count >= 0",
            name="ck_normalization_runs_trade_count_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["raw_event_id"],
            ["raw_blockchain_events.id"],
            name="fk_normalization_runs_raw_event_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "run_id",
            name="uq_normalization_runs_run_id",
        ),
    )
    op.create_index(
        "ix_normalization_runs_raw_parser_version_status",
        "normalization_runs",
        ["raw_event_id", "parser_name", "parser_version", "status"],
        unique=False,
    )
    op.create_index(
        "ix_normalization_runs_parser_version",
        "normalization_runs",
        ["parser_name", "parser_version"],
        unique=False,
    )
    op.create_index(
        "ix_normalization_runs_status_created_at",
        "normalization_runs",
        ["status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_normalization_runs_status_created_at",
        table_name="normalization_runs",
    )
    op.drop_index(
        "ix_normalization_runs_parser_version",
        table_name="normalization_runs",
    )
    op.drop_index(
        "ix_normalization_runs_raw_parser_version_status",
        table_name="normalization_runs",
    )
    op.drop_table("normalization_runs")

    op.drop_index(
        "ix_raw_blockchain_events_payload_hash",
        table_name="raw_blockchain_events",
    )
    op.drop_index(
        "ix_raw_blockchain_events_block_time",
        table_name="raw_blockchain_events",
    )
    op.drop_index(
        "ix_raw_blockchain_events_wallet_first_seen",
        table_name="raw_blockchain_events",
    )
    op.drop_index(
        "ix_raw_blockchain_events_signature",
        table_name="raw_blockchain_events",
    )
    op.drop_index(
        "ix_raw_blockchain_events_provider_chain_network",
        table_name="raw_blockchain_events",
    )
    op.drop_table("raw_blockchain_events")
