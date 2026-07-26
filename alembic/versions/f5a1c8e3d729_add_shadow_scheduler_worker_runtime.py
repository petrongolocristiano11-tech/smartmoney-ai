"""add shadow scheduler worker runtime

Revision ID: f5a1c8e3d729
Revises: e3b7c9d4f821
Create Date: 2026-07-26 18:30:00.000000
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "f5a1c8e3d729"
down_revision: str | Sequence[str] | None = "e3b7c9d4f821"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_shadow_scheduler_worker_states",
        sa.Column("id", pk, primary_key=True),
        sa.Column("worker_name", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.String(80), nullable=True),
        sa.Column("lease_token_hash", sa.String(64), nullable=True),
        sa.Column("lease_epoch", sa.Integer(), nullable=False),
        sa.Column("lease_acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("latest_iteration_id", sa.String(36), nullable=True),
        sa.Column("latest_tick_id", sa.String(36), nullable=True),
        sa.Column("worker_policy_version", sa.String(64), nullable=False),
        sa.Column("worker_policy_hash", sa.String(64), nullable=False),
        sa.Column("worker_policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("kill_reason", sa.Text(), nullable=True),
        sa.Column("latest_event_sequence", sa.Integer(), nullable=False),
        sa.Column("latest_event_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('STOPPED', 'ACTIVE', 'KILLED')", name="ck_shadow_scheduler_worker_states_status"),
        sa.CheckConstraint("generation >= 0 AND lease_epoch >= 0 AND consecutive_failures >= 0", name="ck_shadow_scheduler_worker_states_counters"),
        sa.CheckConstraint("lease_token_hash IS NULL OR length(lease_token_hash) = 64", name="ck_shadow_scheduler_worker_states_lease_hash"),
        sa.CheckConstraint("length(worker_policy_hash) = 64", name="ck_shadow_scheduler_worker_states_policy_hash"),
        sa.CheckConstraint("latest_event_hash IS NULL OR length(latest_event_hash) = 64", name="ck_shadow_scheduler_worker_states_event_hash"),
        sa.UniqueConstraint("worker_name", name="uq_shadow_scheduler_worker_states_name"),
    )
    op.create_table(
        "canonical_parser_shadow_scheduler_worker_events",
        sa.Column("id", pk, primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("worker_state_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("previous_status", sa.String(16), nullable=True),
        sa.Column("new_status", sa.String(16), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column("previous_event_hash", sa.String(64), nullable=True),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("event_type IN ('STARTED', 'STOPPED', 'KILLED', 'RESET', 'HEARTBEAT', 'ITERATION_STARTED', 'ITERATION_COMPLETED', 'ITERATION_FAILED', 'ITERATION_IDLE')", name="ck_shadow_scheduler_worker_events_type"),
        sa.CheckConstraint("sequence >= 1", name="ck_shadow_scheduler_worker_events_sequence"),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_shadow_scheduler_worker_events_hash"),
        sa.CheckConstraint("previous_event_hash IS NULL OR length(previous_event_hash) = 64", name="ck_shadow_scheduler_worker_events_previous_hash"),
        sa.ForeignKeyConstraint(["worker_state_db_id"], ["canonical_parser_shadow_scheduler_worker_states.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("event_id", name="uq_shadow_scheduler_worker_events_id"),
        sa.UniqueConstraint("worker_state_db_id", "sequence", name="uq_shadow_scheduler_worker_events_sequence"),
    )
    op.create_index("ix_shadow_scheduler_worker_events_state_time", "canonical_parser_shadow_scheduler_worker_events", ["worker_state_db_id", "occurred_at"])
    op.create_table(
        "canonical_parser_shadow_scheduler_worker_iterations",
        sa.Column("id", pk, primary_key=True),
        sa.Column("iteration_id", sa.String(36), nullable=False),
        sa.Column("iteration_key", sa.String(64), nullable=False),
        sa.Column("worker_state_db_id", pk, nullable=False),
        sa.Column("worker_generation", sa.Integer(), nullable=False),
        sa.Column("lease_epoch", sa.Integer(), nullable=False),
        sa.Column("owner_id", sa.String(80), nullable=False),
        sa.Column("scheduler_generation", sa.Integer(), nullable=False),
        sa.Column("tick_db_id", pk, nullable=True),
        sa.Column("tick_id", sa.String(36), nullable=True),
        sa.Column("cycle_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("raw_event_ids", sa.JSON(), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("scheduler_preview", sa.JSON(), nullable=False),
        sa.Column("tick_snapshot", sa.JSON(), nullable=False),
        sa.Column("technical_metadata", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('RUNNING', 'IDLE', 'PASSED', 'PARTIAL', 'FAILED', 'SKIPPED', 'KILLED')", name="ck_shadow_scheduler_worker_iterations_status"),
        sa.CheckConstraint("worker_generation >= 1 AND lease_epoch >= 1", name="ck_shadow_scheduler_worker_iterations_fencing"),
        sa.CheckConstraint("length(iteration_key) = 64", name="ck_shadow_scheduler_worker_iterations_key"),
        sa.ForeignKeyConstraint(["worker_state_db_id"], ["canonical_parser_shadow_scheduler_worker_states.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["tick_db_id"], ["canonical_parser_shadow_scheduler_ticks.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("iteration_id", name="uq_shadow_scheduler_worker_iterations_id"),
        sa.UniqueConstraint("iteration_key", name="uq_shadow_scheduler_worker_iterations_key"),
    )
    op.create_index("ix_shadow_scheduler_worker_iterations_state_started", "canonical_parser_shadow_scheduler_worker_iterations", ["worker_state_db_id", "started_at"])
    op.create_index("ix_shadow_scheduler_worker_iterations_status_completed", "canonical_parser_shadow_scheduler_worker_iterations", ["status", "completed_at"])


def downgrade() -> None:
    op.drop_index("ix_shadow_scheduler_worker_iterations_status_completed", table_name="canonical_parser_shadow_scheduler_worker_iterations")
    op.drop_index("ix_shadow_scheduler_worker_iterations_state_started", table_name="canonical_parser_shadow_scheduler_worker_iterations")
    op.drop_table("canonical_parser_shadow_scheduler_worker_iterations")
    op.drop_index("ix_shadow_scheduler_worker_events_state_time", table_name="canonical_parser_shadow_scheduler_worker_events")
    op.drop_table("canonical_parser_shadow_scheduler_worker_events")
    op.drop_table("canonical_parser_shadow_scheduler_worker_states")
