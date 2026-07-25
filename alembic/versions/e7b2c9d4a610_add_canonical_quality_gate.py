"""add canonical quality gate assessments

Revision ID: e7b2c9d4a610
Revises: d5e8a1c4f702
Create Date: 2026-07-25
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "e7b2c9d4a610"
down_revision: str | None = "d5e8a1c4f702"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "canonical_quality_assessments",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("assessment_id", sa.String(length=36), nullable=False),
        sa.Column("assessment_key", sa.String(length=64), nullable=False),
        sa.Column("validation_batch_id", sa.BigInteger(), nullable=False),
        sa.Column("validation_id", sa.String(length=36), nullable=False),
        sa.Column("policy_version", sa.String(length=64), nullable=False),
        sa.Column("policy_hash", sa.String(length=64), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("parser_name", sa.String(length=80), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column(
            "parser_implementation_hash",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column("comparator_version", sa.String(length=32), nullable=False),
        sa.Column("sample_size", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "comparable_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("match_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "mismatch_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
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
        sa.Column(
            "quality_pass_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "quality_warn_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "quality_fail_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "match_rate",
            sa.Numeric(7, 4),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "mismatch_rate",
            sa.Numeric(7, 4),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "missing_trade_rate",
            sa.Numeric(7, 4),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "not_comparable_rate",
            sa.Numeric(7, 4),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "failed_rate",
            sa.Numeric(7, 4),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "quality_pass_rate",
            sa.Numeric(7, 4),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "reason_codes",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column(
            "mismatch_field_counts",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "threshold_snapshot",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "metrics_snapshot",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "technical_metadata",
            sa.JSON(),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
        sa.Column(
            "evidence_completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
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
            "status IN ('READY', 'REVIEW', 'BLOCKED', 'INSUFFICIENT_DATA')",
            name="ck_canonical_quality_assessments_status",
        ),
        sa.CheckConstraint(
            "sample_size >= 0 AND comparable_count >= 0 "
            "AND match_count >= 0 AND mismatch_count >= 0 "
            "AND missing_trade_count >= 0 AND not_comparable_count >= 0 "
            "AND failed_count >= 0 AND quality_pass_count >= 0 "
            "AND quality_warn_count >= 0 AND quality_fail_count >= 0",
            name="ck_canonical_quality_assessments_counts_nonnegative",
        ),
        sa.CheckConstraint(
            "match_rate >= 0 AND match_rate <= 100 "
            "AND mismatch_rate >= 0 AND mismatch_rate <= 100 "
            "AND missing_trade_rate >= 0 AND missing_trade_rate <= 100 "
            "AND not_comparable_rate >= 0 AND not_comparable_rate <= 100 "
            "AND failed_rate >= 0 AND failed_rate <= 100 "
            "AND quality_pass_rate >= 0 AND quality_pass_rate <= 100",
            name="ck_canonical_quality_assessments_rates_range",
        ),
        sa.CheckConstraint(
            "length(assessment_key) = 64",
            name="ck_canonical_quality_assessments_key_length",
        ),
        sa.CheckConstraint(
            "length(policy_hash) = 64",
            name="ck_canonical_quality_assessments_policy_hash_length",
        ),
        sa.CheckConstraint(
            "length(evidence_hash) = 64",
            name="ck_canonical_quality_assessments_evidence_hash_length",
        ),
        sa.CheckConstraint(
            "length(parser_implementation_hash) = 64",
            name="ck_canonical_quality_assessments_parser_hash_length",
        ),
        sa.ForeignKeyConstraint(
            ["validation_batch_id"],
            ["canonical_shadow_validation_batches.id"],
            name="fk_canonical_quality_assessments_validation_batch_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "assessment_id",
            name="uq_canonical_quality_assessments_assessment_id",
        ),
        sa.UniqueConstraint(
            "assessment_key",
            name="uq_canonical_quality_assessments_assessment_key",
        ),
    )
    op.create_index(
        "ix_canonical_quality_assessments_status_evaluated",
        "canonical_quality_assessments",
        ["status", "evaluated_at"],
        unique=False,
    )
    op.create_index(
        "ix_canonical_quality_assessments_validation_batch",
        "canonical_quality_assessments",
        ["validation_batch_id"],
        unique=False,
    )
    op.create_index(
        "ix_canonical_quality_assessments_parser_version",
        "canonical_quality_assessments",
        ["parser_name", "parser_version"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_canonical_quality_assessments_parser_version",
        table_name="canonical_quality_assessments",
    )
    op.drop_index(
        "ix_canonical_quality_assessments_validation_batch",
        table_name="canonical_quality_assessments",
    )
    op.drop_index(
        "ix_canonical_quality_assessments_status_evaluated",
        table_name="canonical_quality_assessments",
    )
    op.drop_table("canonical_quality_assessments")
