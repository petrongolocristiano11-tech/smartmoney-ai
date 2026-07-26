"""add shadow automation reliability evidence gate

Revision ID: c1a8e5d3f924
Revises: b9f2d6a4c713
Create Date: 2026-07-26 19:30:00.000000
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "c1a8e5d3f924"
down_revision: str | Sequence[str] | None = "b9f2d6a4c713"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_shadow_reliability_assessments",
        sa.Column("id", pk, primary_key=True),
        sa.Column("assessment_id", sa.String(36), nullable=False),
        sa.Column("assessment_key", sa.String(64), nullable=False),
        sa.Column("worker_state_db_id", pk, nullable=True),
        sa.Column("worker_generation", sa.Integer(), nullable=False),
        sa.Column("lease_epoch", sa.Integer(), nullable=False),
        sa.Column("worker_event_hash", sa.String(64), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("loop_count", sa.Integer(), nullable=False),
        sa.Column("completed_iteration_count", sa.Integer(), nullable=False),
        sa.Column("passed_iteration_count", sa.Integer(), nullable=False),
        sa.Column("partial_iteration_count", sa.Integer(), nullable=False),
        sa.Column("idle_iteration_count", sa.Integer(), nullable=False),
        sa.Column("failed_iteration_count", sa.Integer(), nullable=False),
        sa.Column("skipped_iteration_count", sa.Integer(), nullable=False),
        sa.Column("circuit_open_count", sa.Integer(), nullable=False),
        sa.Column("recovery_run_count", sa.Integer(), nullable=False),
        sa.Column("recovery_action_count", sa.Integer(), nullable=False),
        sa.Column("pass_rate", sa.Numeric(7, 4), nullable=False),
        sa.Column("observation_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observation_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("evidence_snapshot", sa.JSON(), nullable=False),
        sa.Column("metrics_snapshot", sa.JSON(), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('READY', 'REVIEW', 'BLOCKED', 'INSUFFICIENT_DATA')", name="ck_shadow_reliability_assessments_status"),
        sa.CheckConstraint("loop_count >= 0 AND completed_iteration_count >= 0 AND passed_iteration_count >= 0 AND partial_iteration_count >= 0 AND idle_iteration_count >= 0 AND failed_iteration_count >= 0 AND skipped_iteration_count >= 0 AND circuit_open_count >= 0 AND recovery_run_count >= 0 AND recovery_action_count >= 0", name="ck_shadow_reliability_assessments_counts"),
        sa.CheckConstraint("pass_rate >= 0 AND pass_rate <= 100", name="ck_shadow_reliability_assessments_pass_rate"),
        sa.CheckConstraint("length(assessment_key) = 64", name="ck_shadow_reliability_assessments_key"),
        sa.CheckConstraint("length(policy_hash) = 64", name="ck_shadow_reliability_assessments_policy_hash"),
        sa.CheckConstraint("length(evidence_hash) = 64", name="ck_shadow_reliability_assessments_evidence_hash"),
        sa.ForeignKeyConstraint(["worker_state_db_id"], ["canonical_parser_shadow_scheduler_worker_states.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("assessment_id", name="uq_shadow_reliability_assessments_id"),
        sa.UniqueConstraint("assessment_key", name="uq_shadow_reliability_assessments_key"),
    )
    op.create_index("ix_shadow_reliability_assessments_status_valid", "canonical_parser_shadow_reliability_assessments", ["status", "valid_until"])
    op.create_index("ix_shadow_reliability_assessments_worker_time", "canonical_parser_shadow_reliability_assessments", ["worker_state_db_id", "evaluated_at"])
    op.create_table(
        "canonical_parser_shadow_reliability_evidence_loops",
        sa.Column("id", pk, primary_key=True),
        sa.Column("assessment_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("loop_run_db_id", pk, nullable=False),
        sa.Column("loop_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("completed_iterations", sa.Integer(), nullable=False),
        sa.Column("passed_iterations", sa.Integer(), nullable=False),
        sa.Column("partial_iterations", sa.Integer(), nullable=False),
        sa.Column("idle_iterations", sa.Integer(), nullable=False),
        sa.Column("failed_iterations", sa.Integer(), nullable=False),
        sa.Column("skipped_iterations", sa.Integer(), nullable=False),
        sa.Column("circuit_breaker_open", sa.Boolean(), nullable=False),
        sa.Column("loop_evidence_hash", sa.String(64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_shadow_reliability_evidence_loops_sequence"),
        sa.CheckConstraint("length(loop_evidence_hash) = 64", name="ck_shadow_reliability_evidence_loops_hash"),
        sa.ForeignKeyConstraint(["assessment_db_id"], ["canonical_parser_shadow_reliability_assessments.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["loop_run_db_id"], ["canonical_parser_shadow_worker_loop_runs.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("assessment_db_id", "sequence", name="uq_shadow_reliability_evidence_loops_sequence"),
        sa.UniqueConstraint("assessment_db_id", "loop_run_db_id", name="uq_shadow_reliability_evidence_loops_run"),
    )
    op.create_index("ix_shadow_reliability_evidence_loops_assessment", "canonical_parser_shadow_reliability_evidence_loops", ["assessment_db_id", "sequence"])


def downgrade() -> None:
    op.drop_index("ix_shadow_reliability_evidence_loops_assessment", table_name="canonical_parser_shadow_reliability_evidence_loops")
    op.drop_table("canonical_parser_shadow_reliability_evidence_loops")
    op.drop_index("ix_shadow_reliability_assessments_worker_time", table_name="canonical_parser_shadow_reliability_assessments")
    op.drop_index("ix_shadow_reliability_assessments_status_valid", table_name="canonical_parser_shadow_reliability_assessments")
    op.drop_table("canonical_parser_shadow_reliability_assessments")
