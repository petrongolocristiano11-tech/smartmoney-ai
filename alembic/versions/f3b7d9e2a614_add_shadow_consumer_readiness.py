"""add shadow consumer readiness assessment

Revision ID: f3b7d9e2a614
Revises: e1a4c7b9f205
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f3b7d9e2a614"
down_revision: Union[str, Sequence[str], None] = "e1a4c7b9f205"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "canonical_parser_shadow_readiness_assessments",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
        ),
        sa.Column("assessment_id", sa.String(36), nullable=False),
        sa.Column("assessment_key", sa.String(64), nullable=False),
        sa.Column(
            "lease_db_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("lease_id", sa.String(36), nullable=False),
        sa.Column("certification_id", sa.String(36), nullable=False),
        sa.Column("binding_id", sa.String(36), nullable=False),
        sa.Column("promotion_id", sa.String(36), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("consumer", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("parser_name", sa.String(80), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("parser_implementation_hash", sa.String(64), nullable=False),
        sa.Column("output_schema_version", sa.String(64), nullable=False),
        sa.Column("release_manifest_hash", sa.String(64), nullable=False),
        sa.Column("lease_event_hash", sa.String(64), nullable=False),
        sa.Column("certification_event_hash", sa.String(64), nullable=False),
        sa.Column("readiness_policy_version", sa.String(64), nullable=False),
        sa.Column("readiness_policy_hash", sa.String(64), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("run_ids", sa.JSON(), nullable=False),
        sa.Column("run_count", sa.Integer(), nullable=False),
        sa.Column("total_processed_count", sa.Integer(), nullable=False),
        sa.Column("total_passed_count", sa.Integer(), nullable=False),
        sa.Column("total_failed_count", sa.Integer(), nullable=False),
        sa.Column("total_skipped_count", sa.Integer(), nullable=False),
        sa.Column("total_artifact_count", sa.Integer(), nullable=False),
        sa.Column("unique_event_count", sa.Integer(), nullable=False),
        sa.Column("pass_rate", sa.Numeric(7, 4), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_snapshot", sa.JSON(), nullable=False),
        sa.Column("metrics_snapshot", sa.JSON(), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("evidence_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evidence_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("technical_metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('READY', 'REVIEW', 'BLOCKED', 'INSUFFICIENT_DATA')",
            name="ck_shadow_readiness_assessments_status",
        ),
        sa.CheckConstraint(
            "scope IN ('SHADOW_ONLY')",
            name="ck_shadow_readiness_assessments_scope",
        ),
        sa.CheckConstraint(
            "channel IN ('CANONICAL_SHADOW')",
            name="ck_shadow_readiness_assessments_channel",
        ),
        sa.CheckConstraint(
            "consumer IN ('CERTIFIED_SHADOW_RUNTIME')",
            name="ck_shadow_readiness_assessments_consumer",
        ),
        sa.CheckConstraint(
            "run_count >= 0 AND total_processed_count >= 0 "
            "AND total_passed_count >= 0 AND total_failed_count >= 0 "
            "AND total_skipped_count >= 0 AND total_artifact_count >= 0 "
            "AND unique_event_count >= 0",
            name="ck_shadow_readiness_assessments_counts",
        ),
        sa.CheckConstraint(
            "total_processed_count = total_passed_count + "
            "total_failed_count + total_skipped_count",
            name="ck_shadow_readiness_assessments_breakdown",
        ),
        sa.CheckConstraint(
            "pass_rate >= 0 AND pass_rate <= 100",
            name="ck_shadow_readiness_assessments_pass_rate",
        ),
        sa.CheckConstraint(
            "length(assessment_key) = 64",
            name="ck_shadow_readiness_assessments_key_len",
        ),
        sa.CheckConstraint(
            "length(parser_implementation_hash) = 64",
            name="ck_shadow_readiness_assessments_parser_hash_len",
        ),
        sa.CheckConstraint(
            "length(release_manifest_hash) = 64",
            name="ck_shadow_readiness_assessments_release_hash_len",
        ),
        sa.CheckConstraint(
            "length(lease_event_hash) = 64",
            name="ck_shadow_readiness_assessments_lease_hash_len",
        ),
        sa.CheckConstraint(
            "length(certification_event_hash) = 64",
            name="ck_shadow_readiness_assessments_cert_hash_len",
        ),
        sa.CheckConstraint(
            "length(readiness_policy_hash) = 64",
            name="ck_shadow_readiness_assessments_policy_hash_len",
        ),
        sa.CheckConstraint(
            "length(evidence_hash) = 64",
            name="ck_shadow_readiness_assessments_evidence_hash_len",
        ),
        sa.ForeignKeyConstraint(
            ["lease_db_id"],
            ["canonical_parser_shadow_runtime_leases.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "assessment_id", name="uq_shadow_readiness_assessments_id"
        ),
        sa.UniqueConstraint(
            "assessment_key", name="uq_shadow_readiness_assessments_key"
        ),
    )
    op.create_index(
        "ix_shadow_readiness_assessments_lease_time",
        "canonical_parser_shadow_readiness_assessments",
        ["lease_db_id", "evaluated_at"],
    )
    op.create_index(
        "ix_shadow_readiness_assessments_status_valid",
        "canonical_parser_shadow_readiness_assessments",
        ["status", "valid_until"],
    )
    op.create_index(
        "ix_shadow_readiness_assessments_parser",
        "canonical_parser_shadow_readiness_assessments",
        ["parser_name", "parser_version"],
    )

    op.create_table(
        "canonical_parser_shadow_readiness_evidence_runs",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
        ),
        sa.Column("evidence_id", sa.String(36), nullable=False),
        sa.Column(
            "assessment_db_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "consumer_run_db_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("run_key", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("processed_count", sa.Integer(), nullable=False),
        sa.Column("passed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("artifact_count", sa.Integer(), nullable=False),
        sa.Column("run_evidence_hash", sa.String(64), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'PASSED', 'PARTIAL', 'FAILED')",
            name="ck_shadow_readiness_evidence_runs_status",
        ),
        sa.CheckConstraint(
            "result_count >= 0 AND processed_count >= 0 "
            "AND passed_count >= 0 AND failed_count >= 0 "
            "AND skipped_count >= 0 AND artifact_count >= 0",
            name="ck_shadow_readiness_evidence_runs_counts",
        ),
        sa.CheckConstraint(
            "processed_count = passed_count + failed_count + skipped_count",
            name="ck_shadow_readiness_evidence_runs_breakdown",
        ),
        sa.CheckConstraint(
            "length(run_key) = 64",
            name="ck_shadow_readiness_evidence_runs_key_len",
        ),
        sa.CheckConstraint(
            "length(run_evidence_hash) = 64",
            name="ck_shadow_readiness_evidence_runs_hash_len",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_db_id"],
            ["canonical_parser_shadow_readiness_assessments.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["consumer_run_db_id"],
            ["canonical_parser_shadow_consumer_runs.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "evidence_id", name="uq_shadow_readiness_evidence_runs_id"
        ),
        sa.UniqueConstraint(
            "assessment_db_id",
            "consumer_run_db_id",
            name="uq_shadow_readiness_evidence_runs_assessment_run",
        ),
    )
    op.create_index(
        "ix_shadow_readiness_evidence_runs_assessment",
        "canonical_parser_shadow_readiness_evidence_runs",
        ["assessment_db_id", "completed_at"],
    )
    op.create_index(
        "ix_shadow_readiness_evidence_runs_consumer_run",
        "canonical_parser_shadow_readiness_evidence_runs",
        ["consumer_run_db_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_shadow_readiness_evidence_runs_consumer_run",
        table_name="canonical_parser_shadow_readiness_evidence_runs",
    )
    op.drop_index(
        "ix_shadow_readiness_evidence_runs_assessment",
        table_name="canonical_parser_shadow_readiness_evidence_runs",
    )
    op.drop_table("canonical_parser_shadow_readiness_evidence_runs")
    op.drop_index(
        "ix_shadow_readiness_assessments_parser",
        table_name="canonical_parser_shadow_readiness_assessments",
    )
    op.drop_index(
        "ix_shadow_readiness_assessments_status_valid",
        table_name="canonical_parser_shadow_readiness_assessments",
    )
    op.drop_index(
        "ix_shadow_readiness_assessments_lease_time",
        table_name="canonical_parser_shadow_readiness_assessments",
    )
    op.drop_table("canonical_parser_shadow_readiness_assessments")
