"""add shadow worker recovery and reconciliation

Revision ID: b9f2d6a4c713
Revises: a7e4c2d9b631
Create Date: 2026-07-26 19:15:00.000000
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "b9f2d6a4c713"
down_revision: str | Sequence[str] | None = "a7e4c2d9b631"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_shadow_worker_recovery_runs",
        sa.Column("id", pk, primary_key=True),
        sa.Column("recovery_id", sa.String(36), nullable=False),
        sa.Column("recovery_key", sa.String(64), nullable=False),
        sa.Column("worker_state_db_id", pk, nullable=True),
        sa.Column("worker_generation", sa.Integer(), nullable=False),
        sa.Column("lease_epoch", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.String(80), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("detected_worker_count", sa.Integer(), nullable=False),
        sa.Column("detected_iteration_count", sa.Integer(), nullable=False),
        sa.Column("detected_loop_count", sa.Integer(), nullable=False),
        sa.Column("recovered_worker_count", sa.Integer(), nullable=False),
        sa.Column("recovered_iteration_count", sa.Integer(), nullable=False),
        sa.Column("recovered_loop_count", sa.Integer(), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("target_snapshot", sa.JSON(), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('RUNNING', 'COMPLETED', 'PARTIAL', 'FAILED', 'NOOP')", name="ck_shadow_worker_recovery_runs_status"),
        sa.CheckConstraint("detected_worker_count >= 0 AND detected_iteration_count >= 0 AND detected_loop_count >= 0 AND recovered_worker_count >= 0 AND recovered_iteration_count >= 0 AND recovered_loop_count >= 0", name="ck_shadow_worker_recovery_runs_counts"),
        sa.CheckConstraint("length(recovery_key) = 64", name="ck_shadow_worker_recovery_runs_key"),
        sa.CheckConstraint("length(policy_hash) = 64", name="ck_shadow_worker_recovery_runs_policy_hash"),
        sa.ForeignKeyConstraint(["worker_state_db_id"], ["canonical_parser_shadow_scheduler_worker_states.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("recovery_id", name="uq_shadow_worker_recovery_runs_id"),
        sa.UniqueConstraint("recovery_key", name="uq_shadow_worker_recovery_runs_key"),
    )
    op.create_index("ix_shadow_worker_recovery_runs_status_started", "canonical_parser_shadow_worker_recovery_runs", ["status", "started_at"])
    op.create_table(
        "canonical_parser_shadow_worker_recovery_actions",
        sa.Column("id", pk, primary_key=True),
        sa.Column("recovery_run_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("target_type", sa.String(24), nullable=False),
        sa.Column("target_id", sa.String(80), nullable=False),
        sa.Column("action_type", sa.String(32), nullable=False),
        sa.Column("previous_status", sa.String(20), nullable=True),
        sa.Column("new_status", sa.String(20), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("snapshot_before", sa.JSON(), nullable=False),
        sa.Column("snapshot_after", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_shadow_worker_recovery_actions_sequence"),
        sa.CheckConstraint("target_type IN ('WORKER_STATE', 'WORKER_ITERATION', 'WORKER_LOOP')", name="ck_shadow_worker_recovery_actions_target_type"),
        sa.CheckConstraint("action_type IN ('STOP_STALE_WORKER', 'FAIL_STALE_ITERATION', 'STOP_STALE_LOOP')", name="ck_shadow_worker_recovery_actions_type"),
        sa.ForeignKeyConstraint(["recovery_run_db_id"], ["canonical_parser_shadow_worker_recovery_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("recovery_run_db_id", "sequence", name="uq_shadow_worker_recovery_actions_sequence"),
        sa.UniqueConstraint("recovery_run_db_id", "target_type", "target_id", name="uq_shadow_worker_recovery_actions_target"),
    )
    op.create_index("ix_shadow_worker_recovery_actions_run_sequence", "canonical_parser_shadow_worker_recovery_actions", ["recovery_run_db_id", "sequence"])


def downgrade() -> None:
    op.drop_index("ix_shadow_worker_recovery_actions_run_sequence", table_name="canonical_parser_shadow_worker_recovery_actions")
    op.drop_table("canonical_parser_shadow_worker_recovery_actions")
    op.drop_index("ix_shadow_worker_recovery_runs_status_started", table_name="canonical_parser_shadow_worker_recovery_runs")
    op.drop_table("canonical_parser_shadow_worker_recovery_runs")
