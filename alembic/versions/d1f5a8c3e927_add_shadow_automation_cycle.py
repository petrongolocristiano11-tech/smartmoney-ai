"""add shadow automation cycle coordinator

Revision ID: d1f5a8c3e927
Revises: c9e3a7f2d418
Create Date: 2026-07-26 17:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "d1f5a8c3e927"
down_revision: str | Sequence[str] | None = "c9e3a7f2d418"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_shadow_automation_cycles",
        sa.Column("id", pk, primary_key=True),
        sa.Column("cycle_id", sa.String(36), nullable=False),
        sa.Column("cycle_key", sa.String(64), nullable=False),
        sa.Column("permit_db_id", pk, nullable=False),
        sa.Column("permit_id", sa.String(36), nullable=False),
        sa.Column("ticket_db_id", pk, nullable=True),
        sa.Column("ticket_id", sa.String(36), nullable=True),
        sa.Column("execution_run_db_id", pk, nullable=True),
        sa.Column("execution_run_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("cycle_policy_version", sa.String(64), nullable=False),
        sa.Column("cycle_policy_hash", sa.String(64), nullable=False),
        sa.Column("cycle_policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("requested_event_reservation", sa.Integer(), nullable=False),
        sa.Column("requested_limit", sa.Integer(), nullable=False),
        sa.Column("raw_event_ids", sa.JSON(), nullable=False),
        sa.Column("processed_count", sa.Integer(), nullable=False),
        sa.Column("passed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("artifact_count", sa.Integer(), nullable=False),
        sa.Column("budget_settled", sa.Boolean(), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("preview_snapshot", sa.JSON(), nullable=False),
        sa.Column("execution_snapshot", sa.JSON(), nullable=False),
        sa.Column("technical_metadata", sa.JSON(), nullable=False),
        sa.Column("latest_event_sequence", sa.Integer(), nullable=False),
        sa.Column("latest_event_hash", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('RUNNING', 'PASSED', 'PARTIAL', 'FAILED')", name="ck_shadow_automation_cycles_status"),
        sa.CheckConstraint("requested_event_reservation >= 1 AND requested_limit >= 1", name="ck_shadow_automation_cycles_requests_positive"),
        sa.CheckConstraint("processed_count >= 0 AND passed_count >= 0 AND failed_count >= 0 AND skipped_count >= 0 AND artifact_count >= 0", name="ck_shadow_automation_cycles_counts_nonnegative"),
        sa.CheckConstraint("processed_count = passed_count + failed_count + skipped_count", name="ck_shadow_automation_cycles_processed_breakdown"),
        sa.CheckConstraint("length(cycle_key) = 64", name="ck_shadow_automation_cycles_key_len"),
        sa.CheckConstraint("length(cycle_policy_hash) = 64", name="ck_shadow_automation_cycles_policy_hash_len"),
        sa.CheckConstraint("latest_event_hash IS NULL OR length(latest_event_hash) = 64", name="ck_shadow_automation_cycles_event_hash_len"),
        sa.ForeignKeyConstraint(["permit_db_id"], ["canonical_parser_shadow_automation_permits.id"], name="fk_shadow_automation_cycles_permit", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["ticket_db_id"], ["canonical_parser_shadow_execution_tickets.id"], name="fk_shadow_automation_cycles_ticket", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["execution_run_db_id"], ["canonical_parser_shadow_ticket_execution_runs.id"], name="fk_shadow_automation_cycles_execution_run", ondelete="RESTRICT"),
        sa.UniqueConstraint("cycle_id", name="uq_shadow_automation_cycles_id"),
        sa.UniqueConstraint("cycle_key", name="uq_shadow_automation_cycles_key"),
    )
    op.create_index("ix_shadow_automation_cycles_permit_started", "canonical_parser_shadow_automation_cycles", ["permit_db_id", "started_at"])
    op.create_index("ix_shadow_automation_cycles_status_completed", "canonical_parser_shadow_automation_cycles", ["status", "completed_at"])

    op.create_table(
        "canonical_parser_shadow_automation_cycle_events",
        sa.Column("id", pk, primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("cycle_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("previous_status", sa.String(16), nullable=True),
        sa.Column("new_status", sa.String(16), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column("previous_event_hash", sa.String(64), nullable=True),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("event_type IN ('STARTED', 'COMPLETED', 'FAILED')", name="ck_shadow_automation_cycle_events_type"),
        sa.CheckConstraint("sequence >= 1", name="ck_shadow_automation_cycle_events_sequence_positive"),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_shadow_automation_cycle_events_hash_len"),
        sa.CheckConstraint("previous_event_hash IS NULL OR length(previous_event_hash) = 64", name="ck_shadow_automation_cycle_events_previous_hash_len"),
        sa.ForeignKeyConstraint(["cycle_db_id"], ["canonical_parser_shadow_automation_cycles.id"], name="fk_shadow_automation_cycle_events_cycle", ondelete="CASCADE"),
        sa.UniqueConstraint("event_id", name="uq_shadow_automation_cycle_events_id"),
        sa.UniqueConstraint("cycle_db_id", "sequence", name="uq_shadow_automation_cycle_events_sequence"),
    )
    op.create_index("ix_shadow_automation_cycle_events_cycle_occurred", "canonical_parser_shadow_automation_cycle_events", ["cycle_db_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_shadow_automation_cycle_events_cycle_occurred", table_name="canonical_parser_shadow_automation_cycle_events")
    op.drop_table("canonical_parser_shadow_automation_cycle_events")
    op.drop_index("ix_shadow_automation_cycles_status_completed", table_name="canonical_parser_shadow_automation_cycles")
    op.drop_index("ix_shadow_automation_cycles_permit_started", table_name="canonical_parser_shadow_automation_cycles")
    op.drop_table("canonical_parser_shadow_automation_cycles")
