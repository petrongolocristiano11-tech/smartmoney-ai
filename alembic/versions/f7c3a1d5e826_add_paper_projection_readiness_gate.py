"""add paper projection readiness gate

Revision ID: f7c3a1d5e826
Revises: e5b9d2c6f731
Create Date: 2026-07-26 21:10:00.000000
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "f7c3a1d5e826"
down_revision: str | Sequence[str] | None = "e5b9d2c6f731"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_paper_projection_readiness_assessments",
        sa.Column("id", pk, primary_key=True),
        sa.Column("assessment_id", sa.String(36), nullable=False),
        sa.Column("assessment_key", sa.String(64), nullable=False),
        sa.Column("certification_db_id", pk, nullable=False),
        sa.Column("certification_id", sa.String(36), nullable=False),
        sa.Column("certification_event_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("run_count", sa.Integer(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("projectable_count", sa.Integer(), nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("projectable_rate", sa.Numeric(7, 4), nullable=False),
        sa.Column("observation_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observation_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("evidence_snapshot", sa.JSON(), nullable=False),
        sa.Column("metrics_snapshot", sa.JSON(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('READY', 'REVIEW', 'BLOCKED', 'INSUFFICIENT_DATA')", name="ck_parser_paper_projection_readiness_status"),
        sa.CheckConstraint("run_count >= 0 AND result_count >= 0 AND projectable_count >= 0 AND review_count >= 0 AND rejected_count >= 0", name="ck_parser_paper_projection_readiness_counts"),
        sa.CheckConstraint("result_count = projectable_count + review_count + rejected_count", name="ck_parser_paper_projection_readiness_breakdown"),
        sa.CheckConstraint("projectable_rate >= 0 AND projectable_rate <= 100", name="ck_parser_paper_projection_readiness_rate"),
        sa.CheckConstraint("length(assessment_key) = 64", name="ck_parser_paper_projection_readiness_key"),
        sa.CheckConstraint("length(certification_event_hash) = 64", name="ck_parser_paper_projection_readiness_cert_hash"),
        sa.CheckConstraint("length(policy_hash) = 64", name="ck_parser_paper_projection_readiness_policy_hash"),
        sa.CheckConstraint("length(evidence_hash) = 64", name="ck_parser_paper_projection_readiness_evidence_hash"),
        sa.ForeignKeyConstraint(["certification_db_id"], ["canonical_parser_shadow_reliability_certifications.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("assessment_id", name="uq_parser_paper_projection_readiness_id"),
        sa.UniqueConstraint("assessment_key", name="uq_parser_paper_projection_readiness_key"),
    )
    op.create_index("ix_parser_paper_projection_readiness_status_valid", "canonical_parser_paper_projection_readiness_assessments", ["status", "valid_until"])
    op.create_index("ix_parser_paper_projection_readiness_cert", "canonical_parser_paper_projection_readiness_assessments", ["certification_db_id", "evaluated_at"])
    op.create_table(
        "canonical_parser_paper_projection_readiness_evidence_runs",
        sa.Column("id", pk, primary_key=True),
        sa.Column("assessment_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("projection_run_db_id", pk, nullable=False),
        sa.Column("projection_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source_result_count", sa.Integer(), nullable=False),
        sa.Column("projectable_count", sa.Integer(), nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("projection_key", sa.String(64), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("source_evidence_hash", sa.String(64), nullable=False),
        sa.Column("run_evidence_hash", sa.String(64), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_parser_paper_projection_readiness_evidence_sequence"),
        sa.CheckConstraint("status IN ('PASSED', 'PARTIAL', 'BLOCKED', 'INSUFFICIENT_DATA')", name="ck_parser_paper_projection_readiness_evidence_status"),
        sa.CheckConstraint("source_result_count >= 0 AND projectable_count >= 0 AND review_count >= 0 AND rejected_count >= 0", name="ck_parser_paper_projection_readiness_evidence_counts"),
        sa.CheckConstraint("source_result_count = projectable_count + review_count + rejected_count", name="ck_parser_paper_projection_readiness_evidence_breakdown"),
        sa.CheckConstraint("length(projection_key) = 64", name="ck_parser_paper_projection_readiness_evidence_projection_key"),
        sa.CheckConstraint("length(policy_hash) = 64", name="ck_parser_paper_projection_readiness_evidence_policy_hash"),
        sa.CheckConstraint("length(source_evidence_hash) = 64", name="ck_parser_paper_projection_readiness_evidence_source_hash"),
        sa.CheckConstraint("length(run_evidence_hash) = 64", name="ck_parser_paper_projection_readiness_evidence_run_hash"),
        sa.ForeignKeyConstraint(["assessment_db_id"], ["canonical_parser_paper_projection_readiness_assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["projection_run_db_id"], ["canonical_parser_paper_projection_runs.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("assessment_db_id", "sequence", name="uq_parser_paper_projection_readiness_evidence_sequence"),
        sa.UniqueConstraint("assessment_db_id", "projection_run_db_id", name="uq_parser_paper_projection_readiness_evidence_run"),
    )
    op.create_index("ix_parser_paper_projection_readiness_evidence_assessment", "canonical_parser_paper_projection_readiness_evidence_runs", ["assessment_db_id", "sequence"])


def downgrade() -> None:
    op.drop_index("ix_parser_paper_projection_readiness_evidence_assessment", table_name="canonical_parser_paper_projection_readiness_evidence_runs")
    op.drop_table("canonical_parser_paper_projection_readiness_evidence_runs")
    op.drop_index("ix_parser_paper_projection_readiness_cert", table_name="canonical_parser_paper_projection_readiness_assessments")
    op.drop_index("ix_parser_paper_projection_readiness_status_valid", table_name="canonical_parser_paper_projection_readiness_assessments")
    op.drop_table("canonical_parser_paper_projection_readiness_assessments")
