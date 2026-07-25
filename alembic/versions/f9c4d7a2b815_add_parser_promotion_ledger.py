"""add canonical parser promotion ledger

Revision ID: f9c4d7a2b815
Revises: e7b2c9d4a610
Create Date: 2026-07-25
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "f9c4d7a2b815"
down_revision: str | None = "e7b2c9d4a610"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "canonical_parser_promotions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("promotion_id", sa.String(length=36), nullable=False),
        sa.Column("promotion_key", sa.String(length=64), nullable=False),
        sa.Column("assessment_db_id", sa.BigInteger(), nullable=False),
        sa.Column("assessment_id", sa.String(length=36), nullable=False),
        sa.Column(
            "scope",
            sa.String(length=32),
            server_default="SHADOW_ONLY",
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("parser_name", sa.String(length=80), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column(
            "parser_implementation_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "output_schema_version",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "assessment_policy_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "assessment_evidence_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "promotion_policy_version",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "promotion_policy_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "release_manifest",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "release_manifest_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "revoked_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
        sa.Column(
            "latest_event_sequence",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column("latest_event_hash", sa.String(length=64), nullable=False),
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
            "status IN ('APPROVED', 'REVOKED')",
            name="ck_canonical_parser_promotions_status",
        ),
        sa.CheckConstraint(
            "scope IN ('SHADOW_ONLY')",
            name="ck_canonical_parser_promotions_scope",
        ),
        sa.CheckConstraint(
            "latest_event_sequence >= 1",
            name="ck_canonical_parser_promotions_event_sequence_positive",
        ),
        sa.CheckConstraint(
            "length(promotion_key) = 64",
            name="ck_canonical_parser_promotions_key_length",
        ),
        sa.CheckConstraint(
            "length(parser_implementation_hash) = 64",
            name="ck_canonical_parser_promotions_parser_hash_length",
        ),
        sa.CheckConstraint(
            "length(assessment_policy_hash) = 64",
            name="ck_canonical_parser_promotions_assessment_policy_hash_length",
        ),
        sa.CheckConstraint(
            "length(assessment_evidence_hash) = 64",
            name="ck_canonical_parser_promotions_assessment_evidence_hash_length",
        ),
        sa.CheckConstraint(
            "length(promotion_policy_hash) = 64",
            name="ck_canonical_parser_promotions_policy_hash_length",
        ),
        sa.CheckConstraint(
            "length(release_manifest_hash) = 64",
            name="ck_canonical_parser_promotions_manifest_hash_length",
        ),
        sa.CheckConstraint(
            "length(latest_event_hash) = 64",
            name="ck_canonical_parser_promotions_latest_event_hash_length",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_db_id"],
            ["canonical_quality_assessments.id"],
            name="fk_canonical_parser_promotions_assessment_db_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "promotion_id",
            name="uq_canonical_parser_promotions_promotion_id",
        ),
        sa.UniqueConstraint(
            "promotion_key",
            name="uq_canonical_parser_promotions_promotion_key",
        ),
    )
    op.create_index(
        "ix_canonical_parser_promotions_status_scope",
        "canonical_parser_promotions",
        ["status", "scope"],
        unique=False,
    )
    op.create_index(
        "ix_canonical_parser_promotions_assessment",
        "canonical_parser_promotions",
        ["assessment_db_id"],
        unique=False,
    )
    op.create_index(
        "ix_canonical_parser_promotions_parser_version",
        "canonical_parser_promotions",
        ["parser_name", "parser_version"],
        unique=False,
    )
    op.create_index(
        "uq_canonical_parser_promotions_active_parser_scope",
        "canonical_parser_promotions",
        ["parser_name", "scope"],
        unique=True,
        postgresql_where=sa.text("status = 'APPROVED'"),
        sqlite_where=sa.text("status = 'APPROVED'"),
    )

    op.create_table(
        "canonical_parser_promotion_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("event_id", sa.String(length=36), nullable=False),
        sa.Column("promotion_db_id", sa.BigInteger(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("previous_status", sa.String(length=16), nullable=True),
        sa.Column("new_status", sa.String(length=16), nullable=False),
        sa.Column("actor_label", sa.String(length=80), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column("previous_event_hash", sa.String(length=64), nullable=True),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "sequence >= 1",
            name="ck_canonical_parser_promotion_events_sequence_positive",
        ),
        sa.CheckConstraint(
            "event_type IN ('APPROVED', 'REVOKED')",
            name="ck_canonical_parser_promotion_events_type",
        ),
        sa.CheckConstraint(
            "previous_status IS NULL OR previous_status IN ('APPROVED', 'REVOKED')",
            name="ck_canonical_parser_promotion_events_previous_status",
        ),
        sa.CheckConstraint(
            "new_status IN ('APPROVED', 'REVOKED')",
            name="ck_canonical_parser_promotion_events_new_status",
        ),
        sa.CheckConstraint(
            "previous_event_hash IS NULL OR length(previous_event_hash) = 64",
            name="ck_canonical_parser_promotion_events_previous_hash_length",
        ),
        sa.CheckConstraint(
            "length(event_hash) = 64",
            name="ck_canonical_parser_promotion_events_hash_length",
        ),
        sa.ForeignKeyConstraint(
            ["promotion_db_id"],
            ["canonical_parser_promotions.id"],
            name="fk_canonical_parser_promotion_events_promotion_db_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "event_id",
            name="uq_canonical_parser_promotion_events_event_id",
        ),
        sa.UniqueConstraint(
            "promotion_db_id",
            "sequence",
            name="uq_canonical_parser_promotion_events_promotion_sequence",
        ),
    )
    op.create_index(
        "ix_canonical_parser_promotion_events_type_occurred",
        "canonical_parser_promotion_events",
        ["event_type", "occurred_at"],
        unique=False,
    )
    op.create_index(
        "ix_canonical_parser_promotion_events_promotion_sequence",
        "canonical_parser_promotion_events",
        ["promotion_db_id", "sequence"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_canonical_parser_promotion_events_promotion_sequence",
        table_name="canonical_parser_promotion_events",
    )
    op.drop_index(
        "ix_canonical_parser_promotion_events_type_occurred",
        table_name="canonical_parser_promotion_events",
    )
    op.drop_table("canonical_parser_promotion_events")

    op.drop_index(
        "uq_canonical_parser_promotions_active_parser_scope",
        table_name="canonical_parser_promotions",
    )
    op.drop_index(
        "ix_canonical_parser_promotions_parser_version",
        table_name="canonical_parser_promotions",
    )
    op.drop_index(
        "ix_canonical_parser_promotions_assessment",
        table_name="canonical_parser_promotions",
    )
    op.drop_index(
        "ix_canonical_parser_promotions_status_scope",
        table_name="canonical_parser_promotions",
    )
    op.drop_table("canonical_parser_promotions")
