"""add paper canary readiness evidence gate

Revision ID: d2a7f4c9e831
Revises: c4e1a7d9b625
Create Date: 2026-07-27 18:45:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "d2a7f4c9e831"
down_revision: str | Sequence[str] | None = "c4e1a7d9b625"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_paper_canary_readiness_assessments",
        sa.Column("id", pk, primary_key=True),
        sa.Column("assessment_id", sa.String(36), nullable=False),
        sa.Column("assessment_key", sa.String(64), nullable=False),
        sa.Column("binding_db_id", pk, nullable=False),
        sa.Column("binding_id", sa.String(36), nullable=False),
        sa.Column("binding_event_hash", sa.String(64), nullable=False),
        sa.Column("certification_id", sa.String(36), nullable=False),
        sa.Column("paper_account_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("run_count", sa.Integer(), nullable=False),
        sa.Column("passed_run_count", sa.Integer(), nullable=False),
        sa.Column("review_run_count", sa.Integer(), nullable=False),
        sa.Column("blocked_run_count", sa.Integer(), nullable=False),
        sa.Column("insufficient_run_count", sa.Integer(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("admissible_count", sa.Integer(), nullable=False),
        sa.Column("review_result_count", sa.Integer(), nullable=False),
        sa.Column("blocked_result_count", sa.Integer(), nullable=False),
        sa.Column("observation_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observation_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_source_valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("freshness_cutoff_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.CheckConstraint(
            "status IN ('READY', 'REVIEW', 'BLOCKED', 'INSUFFICIENT_DATA')",
            name="ck_parser_paper_canary_readiness_status",
        ),
        sa.CheckConstraint(
            "run_count >= 0 AND passed_run_count >= 0 AND review_run_count >= 0 "
            "AND blocked_run_count >= 0 AND insufficient_run_count >= 0",
            name="ck_parser_paper_canary_readiness_run_counts",
        ),
        sa.CheckConstraint(
            "run_count = passed_run_count + review_run_count + blocked_run_count + insufficient_run_count",
            name="ck_parser_paper_canary_readiness_run_breakdown",
        ),
        sa.CheckConstraint(
            "result_count >= 0 AND admissible_count >= 0 AND review_result_count >= 0 AND blocked_result_count >= 0",
            name="ck_parser_paper_canary_readiness_result_counts",
        ),
        sa.CheckConstraint(
            "result_count = admissible_count + review_result_count + blocked_result_count",
            name="ck_parser_paper_canary_readiness_result_breakdown",
        ),
        sa.CheckConstraint("length(assessment_key) = 64", name="ck_parser_paper_canary_readiness_key"),
        sa.CheckConstraint("length(binding_event_hash) = 64", name="ck_parser_paper_canary_readiness_binding_hash"),
        sa.CheckConstraint("length(policy_hash) = 64", name="ck_parser_paper_canary_readiness_policy_hash"),
        sa.CheckConstraint("length(evidence_hash) = 64", name="ck_parser_paper_canary_readiness_evidence_hash"),
        sa.ForeignKeyConstraint(
            ["binding_db_id"], ["canonical_parser_paper_runtime_bindings.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["paper_account_id"], ["paper_accounts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("assessment_id", name="uq_parser_paper_canary_readiness_id"),
        sa.UniqueConstraint("assessment_key", name="uq_parser_paper_canary_readiness_key"),
    )
    op.create_index(
        "ix_parser_paper_canary_readiness_status_valid",
        "canonical_parser_paper_canary_readiness_assessments",
        ["status", "valid_until"],
    )
    op.create_index(
        "ix_parser_paper_canary_readiness_binding_evaluated",
        "canonical_parser_paper_canary_readiness_assessments",
        ["binding_db_id", "evaluated_at"],
    )

    op.create_table(
        "canonical_parser_paper_canary_readiness_evidence_runs",
        sa.Column("id", pk, primary_key=True),
        sa.Column("assessment_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("canary_run_db_id", pk, nullable=False),
        sa.Column("canary_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source_result_count", sa.Integer(), nullable=False),
        sa.Column("admissible_count", sa.Integer(), nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False),
        sa.Column("blocked_count", sa.Integer(), nullable=False),
        sa.Column("canary_key", sa.String(64), nullable=False),
        sa.Column("binding_event_hash", sa.String(64), nullable=False),
        sa.Column("source_evidence_hash", sa.String(64), nullable=False),
        sa.Column("account_state_hash", sa.String(64), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("run_evidence_hash", sa.String(64), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_parser_paper_canary_readiness_evidence_sequence"),
        sa.CheckConstraint(
            "status IN ('PASSED', 'REVIEW', 'BLOCKED', 'INSUFFICIENT_DATA')",
            name="ck_parser_paper_canary_readiness_evidence_status",
        ),
        sa.CheckConstraint(
            "source_result_count >= 0 AND admissible_count >= 0 AND review_count >= 0 AND blocked_count >= 0",
            name="ck_parser_paper_canary_readiness_evidence_counts",
        ),
        sa.CheckConstraint(
            "source_result_count = admissible_count + review_count + blocked_count",
            name="ck_parser_paper_canary_readiness_evidence_breakdown",
        ),
        sa.CheckConstraint("length(canary_key) = 64", name="ck_parser_paper_canary_readiness_evidence_key"),
        sa.CheckConstraint("length(binding_event_hash) = 64", name="ck_parser_paper_canary_readiness_evidence_binding_hash"),
        sa.CheckConstraint("length(source_evidence_hash) = 64", name="ck_parser_paper_canary_readiness_evidence_source_hash"),
        sa.CheckConstraint("length(account_state_hash) = 64", name="ck_parser_paper_canary_readiness_evidence_account_hash"),
        sa.CheckConstraint("length(policy_hash) = 64", name="ck_parser_paper_canary_readiness_evidence_policy_hash"),
        sa.CheckConstraint("length(run_evidence_hash) = 64", name="ck_parser_paper_canary_readiness_evidence_run_hash"),
        sa.ForeignKeyConstraint(
            ["assessment_db_id"], ["canonical_parser_paper_canary_readiness_assessments.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["canary_run_db_id"], ["canonical_parser_paper_admission_canary_runs.id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "assessment_db_id", "sequence", name="uq_parser_paper_canary_readiness_evidence_sequence"
        ),
        sa.UniqueConstraint(
            "assessment_db_id", "canary_run_db_id", name="uq_parser_paper_canary_readiness_evidence_source"
        ),
    )
    op.create_index(
        "ix_parser_paper_canary_readiness_evidence_assessment_status",
        "canonical_parser_paper_canary_readiness_evidence_runs",
        ["assessment_db_id", "status"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_parser_paper_canary_readiness_evidence_assessment_status",
        table_name="canonical_parser_paper_canary_readiness_evidence_runs",
    )
    op.drop_table("canonical_parser_paper_canary_readiness_evidence_runs")
    op.drop_index(
        "ix_parser_paper_canary_readiness_binding_evaluated",
        table_name="canonical_parser_paper_canary_readiness_assessments",
    )
    op.drop_index(
        "ix_parser_paper_canary_readiness_status_valid",
        table_name="canonical_parser_paper_canary_readiness_assessments",
    )
    op.drop_table("canonical_parser_paper_canary_readiness_assessments")
