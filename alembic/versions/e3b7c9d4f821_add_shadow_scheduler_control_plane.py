"""add shadow scheduler control plane

Revision ID: e3b7c9d4f821
Revises: d1f5a8c3e927
Create Date: 2026-07-26 17:30:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "e3b7c9d4f821"
down_revision: str | Sequence[str] | None = "d1f5a8c3e927"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_shadow_scheduler_states",
        sa.Column("id", pk, primary_key=True),
        sa.Column("scheduler_name", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("kill_switch_engaged", sa.Boolean(), nullable=False),
        sa.Column("kill_reason", sa.Text(), nullable=True),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("event_reservation", sa.Integer(), nullable=False),
        sa.Column("execution_limit", sa.Integer(), nullable=False),
        sa.Column("permit_id", sa.String(36), nullable=True),
        sa.Column("scheduler_policy_version", sa.String(64), nullable=False),
        sa.Column("scheduler_policy_hash", sa.String(64), nullable=False),
        sa.Column("scheduler_policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("lock_owner", sa.String(80), nullable=True),
        sa.Column("lock_token_hash", sa.String(64), nullable=True),
        sa.Column("lock_acquired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lock_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_not_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_tick_id", sa.String(36), nullable=True),
        sa.Column("latest_cycle_id", sa.String(36), nullable=True),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("latest_event_sequence", sa.Integer(), nullable=False),
        sa.Column("latest_event_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('STOPPED', 'RUNNING', 'KILLED')", name="ck_shadow_scheduler_states_status"),
        sa.CheckConstraint("generation >= 0 AND interval_seconds >= 1 AND event_reservation >= 1 AND execution_limit >= 1", name="ck_shadow_scheduler_states_values_positive"),
        sa.CheckConstraint("lock_token_hash IS NULL OR length(lock_token_hash) = 64", name="ck_shadow_scheduler_states_lock_hash_len"),
        sa.CheckConstraint("length(scheduler_policy_hash) = 64", name="ck_shadow_scheduler_states_policy_hash_len"),
        sa.CheckConstraint("latest_event_hash IS NULL OR length(latest_event_hash) = 64", name="ck_shadow_scheduler_states_event_hash_len"),
        sa.UniqueConstraint("scheduler_name", name="uq_shadow_scheduler_states_name"),
    )
    op.create_table(
        "canonical_parser_shadow_scheduler_events",
        sa.Column("id", pk, primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("scheduler_state_db_id", pk, nullable=False),
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
        sa.CheckConstraint("event_type IN ('STARTED', 'STOPPED', 'KILLED', 'RESET', 'HEARTBEAT', 'TICK_ACQUIRED', 'TICK_COMPLETED', 'TICK_FAILED', 'TICK_SKIPPED')", name="ck_shadow_scheduler_events_type"),
        sa.CheckConstraint("sequence >= 1", name="ck_shadow_scheduler_events_sequence_positive"),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_shadow_scheduler_events_hash_len"),
        sa.CheckConstraint("previous_event_hash IS NULL OR length(previous_event_hash) = 64", name="ck_shadow_scheduler_events_previous_hash_len"),
        sa.ForeignKeyConstraint(["scheduler_state_db_id"], ["canonical_parser_shadow_scheduler_states.id"], name="fk_shadow_scheduler_events_state", ondelete="CASCADE"),
        sa.UniqueConstraint("event_id", name="uq_shadow_scheduler_events_id"),
        sa.UniqueConstraint("scheduler_state_db_id", "sequence", name="uq_shadow_scheduler_events_sequence"),
    )
    op.create_index("ix_shadow_scheduler_events_state_occurred", "canonical_parser_shadow_scheduler_events", ["scheduler_state_db_id", "occurred_at"])
    op.create_table(
        "canonical_parser_shadow_scheduler_ticks",
        sa.Column("id", pk, primary_key=True),
        sa.Column("tick_id", sa.String(36), nullable=False),
        sa.Column("tick_key", sa.String(64), nullable=False),
        sa.Column("scheduler_state_db_id", pk, nullable=False),
        sa.Column("scheduler_generation", sa.Integer(), nullable=False),
        sa.Column("cycle_db_id", pk, nullable=True),
        sa.Column("cycle_id", sa.String(36), nullable=True),
        sa.Column("permit_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("lock_token_hash", sa.String(64), nullable=False),
        sa.Column("requested_event_reservation", sa.Integer(), nullable=False),
        sa.Column("requested_limit", sa.Integer(), nullable=False),
        sa.Column("raw_event_ids", sa.JSON(), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("cycle_snapshot", sa.JSON(), nullable=False),
        sa.Column("technical_metadata", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('RUNNING', 'PASSED', 'PARTIAL', 'FAILED', 'SKIPPED', 'KILLED')", name="ck_shadow_scheduler_ticks_status"),
        sa.CheckConstraint("requested_event_reservation >= 1 AND requested_limit >= 1", name="ck_shadow_scheduler_ticks_requests_positive"),
        sa.CheckConstraint("length(tick_key) = 64", name="ck_shadow_scheduler_ticks_key_len"),
        sa.CheckConstraint("length(lock_token_hash) = 64", name="ck_shadow_scheduler_ticks_lock_hash_len"),
        sa.ForeignKeyConstraint(["scheduler_state_db_id"], ["canonical_parser_shadow_scheduler_states.id"], name="fk_shadow_scheduler_ticks_state", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["cycle_db_id"], ["canonical_parser_shadow_automation_cycles.id"], name="fk_shadow_scheduler_ticks_cycle", ondelete="RESTRICT"),
        sa.UniqueConstraint("tick_id", name="uq_shadow_scheduler_ticks_id"),
        sa.UniqueConstraint("tick_key", name="uq_shadow_scheduler_ticks_key"),
    )
    op.create_index("ix_shadow_scheduler_ticks_state_started", "canonical_parser_shadow_scheduler_ticks", ["scheduler_state_db_id", "started_at"])
    op.create_index("ix_shadow_scheduler_ticks_status_completed", "canonical_parser_shadow_scheduler_ticks", ["status", "completed_at"])


def downgrade() -> None:
    op.drop_index("ix_shadow_scheduler_ticks_status_completed", table_name="canonical_parser_shadow_scheduler_ticks")
    op.drop_index("ix_shadow_scheduler_ticks_state_started", table_name="canonical_parser_shadow_scheduler_ticks")
    op.drop_table("canonical_parser_shadow_scheduler_ticks")
    op.drop_index("ix_shadow_scheduler_events_state_occurred", table_name="canonical_parser_shadow_scheduler_events")
    op.drop_table("canonical_parser_shadow_scheduler_events")
    op.drop_table("canonical_parser_shadow_scheduler_states")
