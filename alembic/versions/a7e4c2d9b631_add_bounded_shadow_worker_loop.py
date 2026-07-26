"""add bounded shadow worker loop

Revision ID: a7e4c2d9b631
Revises: f5a1c8e3d729
Create Date: 2026-07-26 18:45:00.000000
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "a7e4c2d9b631"
down_revision: str | Sequence[str] | None = "f5a1c8e3d729"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_shadow_worker_loop_runs",
        sa.Column("id", pk, primary_key=True),
        sa.Column("loop_id", sa.String(36), nullable=False),
        sa.Column("loop_key", sa.String(64), nullable=False),
        sa.Column("worker_state_db_id", pk, nullable=False),
        sa.Column("worker_generation", sa.Integer(), nullable=False),
        sa.Column("lease_epoch", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("requested_iterations", sa.Integer(), nullable=False),
        sa.Column("completed_iterations", sa.Integer(), nullable=False),
        sa.Column("passed_iterations", sa.Integer(), nullable=False),
        sa.Column("partial_iterations", sa.Integer(), nullable=False),
        sa.Column("idle_iterations", sa.Integer(), nullable=False),
        sa.Column("failed_iterations", sa.Integer(), nullable=False),
        sa.Column("skipped_iterations", sa.Integer(), nullable=False),
        sa.Column("max_consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("observed_consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("circuit_breaker_open", sa.Boolean(), nullable=False),
        sa.Column("kill_switch_enforced", sa.Boolean(), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("stop_reason", sa.Text(), nullable=True),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('RUNNING', 'COMPLETED', 'STOPPED', 'CIRCUIT_OPEN', 'FAILED', 'KILLED')", name="ck_shadow_worker_loop_runs_status"),
        sa.CheckConstraint("requested_iterations >= 1 AND completed_iterations >= 0 AND passed_iterations >= 0 AND partial_iterations >= 0 AND idle_iterations >= 0 AND failed_iterations >= 0 AND skipped_iterations >= 0 AND max_consecutive_failures >= 1", name="ck_shadow_worker_loop_runs_counts"),
        sa.CheckConstraint("length(loop_key) = 64", name="ck_shadow_worker_loop_runs_key"),
        sa.ForeignKeyConstraint(["worker_state_db_id"], ["canonical_parser_shadow_scheduler_worker_states.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("loop_id", name="uq_shadow_worker_loop_runs_id"),
        sa.UniqueConstraint("loop_key", name="uq_shadow_worker_loop_runs_key"),
    )
    op.create_index("ix_shadow_worker_loop_runs_state_started", "canonical_parser_shadow_worker_loop_runs", ["worker_state_db_id", "started_at"])
    op.create_index("ix_shadow_worker_loop_runs_status_completed", "canonical_parser_shadow_worker_loop_runs", ["status", "completed_at"])
    op.create_table(
        "canonical_parser_shadow_worker_loop_iterations",
        sa.Column("id", pk, primary_key=True),
        sa.Column("loop_run_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("worker_iteration_db_id", pk, nullable=False),
        sa.Column("iteration_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_shadow_worker_loop_iterations_sequence"),
        sa.ForeignKeyConstraint(["loop_run_db_id"], ["canonical_parser_shadow_worker_loop_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["worker_iteration_db_id"], ["canonical_parser_shadow_scheduler_worker_iterations.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("loop_run_db_id", "sequence", name="uq_shadow_worker_loop_iterations_sequence"),
        sa.UniqueConstraint("worker_iteration_db_id", name="uq_shadow_worker_loop_iterations_worker_iteration"),
    )
    op.create_index("ix_shadow_worker_loop_iterations_loop_sequence", "canonical_parser_shadow_worker_loop_iterations", ["loop_run_db_id", "sequence"])


def downgrade() -> None:
    op.drop_index("ix_shadow_worker_loop_iterations_loop_sequence", table_name="canonical_parser_shadow_worker_loop_iterations")
    op.drop_table("canonical_parser_shadow_worker_loop_iterations")
    op.drop_index("ix_shadow_worker_loop_runs_status_completed", table_name="canonical_parser_shadow_worker_loop_runs")
    op.drop_index("ix_shadow_worker_loop_runs_state_started", table_name="canonical_parser_shadow_worker_loop_runs")
    op.drop_table("canonical_parser_shadow_worker_loop_runs")
