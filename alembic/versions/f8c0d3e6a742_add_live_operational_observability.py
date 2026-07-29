"""add live operational observability

Revision ID: f8c0d3e6a742
Revises: e7b9c2d5f631
Create Date: 2026-07-29 16:05:00.000000
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "f8c0d3e6a742"
down_revision: str | Sequence[str] | None = "e7b9c2d5f631"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_live_observability_snapshots",
        sa.Column("id", pk, primary_key=True),
        sa.Column("snapshot_id", sa.String(36), nullable=False),
        sa.Column("snapshot_key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(48), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("uncertain_submission_count", sa.Integer(), nullable=False),
        sa.Column("stale_submission_count", sa.Integer(), nullable=False),
        sa.Column("unsettled_count", sa.Integer(), nullable=False),
        sa.Column("review_position_count", sa.Integer(), nullable=False),
        sa.Column("active_incident_count", sa.Integer(), nullable=False),
        sa.Column("open_alert_count", sa.Integer(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("metric_snapshot", sa.JSON(), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope = 'M43_LIVE_OPERATIONAL_OBSERVABILITY'", name="ck_m43_snapshot_scope"),
        sa.CheckConstraint("status IN ('HEALTHY','DEGRADED','CRITICAL','INSUFFICIENT_DATA')", name="ck_m43_snapshot_status"),
        sa.CheckConstraint("uncertain_submission_count >= 0 AND stale_submission_count >= 0 AND unsettled_count >= 0 AND review_position_count >= 0 AND active_incident_count >= 0 AND open_alert_count >= 0", name="ck_m43_snapshot_counts"),
        sa.CheckConstraint("length(snapshot_key) = 64 AND length(evidence_hash) = 64", name="ck_m43_snapshot_hashes"),
        sa.UniqueConstraint("snapshot_id", name="uq_m43_snapshot_id"),
        sa.UniqueConstraint("snapshot_key", name="uq_m43_snapshot_key"),
    )
    op.create_index("ix_m43_snapshot_status_time", "canonical_parser_live_observability_snapshots", ["status", "observed_at"])
    op.create_index("ix_m43_snapshot_expiry", "canonical_parser_live_observability_snapshots", ["expires_at"])

    op.create_table(
        "canonical_parser_live_operational_alerts",
        sa.Column("id", pk, primary_key=True),
        sa.Column("alert_id", sa.String(36), nullable=False),
        sa.Column("alert_key", sa.String(64), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(48), nullable=False),
        sa.Column("snapshot_db_id", pk, nullable=False),
        sa.Column("snapshot_id", sa.String(36), nullable=False),
        sa.Column("reason_code", sa.String(96), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(96), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("alert_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_event_sequence", sa.Integer(), nullable=False),
        sa.Column("latest_event_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope = 'M43_MANUAL_OPERATIONAL_ALERT'", name="ck_m43_alert_scope"),
        sa.CheckConstraint("severity IN ('LOW','MEDIUM','HIGH','CRITICAL')", name="ck_m43_alert_severity"),
        sa.CheckConstraint("status IN ('OPEN','ACKNOWLEDGED','RESOLVED')", name="ck_m43_alert_status"),
        sa.CheckConstraint("latest_event_sequence >= 1", name="ck_m43_alert_event_sequence"),
        sa.CheckConstraint("length(alert_key) = 64 AND length(fingerprint) = 64 AND length(evidence_hash) = 64 AND length(latest_event_hash) = 64", name="ck_m43_alert_hashes"),
        sa.ForeignKeyConstraint(["snapshot_db_id"], ["canonical_parser_live_observability_snapshots.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("alert_id", name="uq_m43_alert_id"),
        sa.UniqueConstraint("alert_key", name="uq_m43_alert_key"),
    )
    op.create_index("ix_m43_alert_fingerprint_status", "canonical_parser_live_operational_alerts", ["fingerprint", "status"])
    op.create_index("ix_m43_alert_severity_status", "canonical_parser_live_operational_alerts", ["severity", "status"])
    op.create_index("ix_m43_alert_last_seen", "canonical_parser_live_operational_alerts", ["last_seen_at"])

    op.create_table(
        "canonical_parser_live_operational_alert_events",
        sa.Column("id", pk, primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("alert_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column("previous_event_hash", sa.String(64), nullable=True),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_m43_alert_event_sequence"),
        sa.CheckConstraint("event_type IN ('OPENED','ACKNOWLEDGED','RESOLVED')", name="ck_m43_alert_event_type"),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_m43_alert_event_hash"),
        sa.ForeignKeyConstraint(["alert_db_id"], ["canonical_parser_live_operational_alerts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("event_id", name="uq_m43_alert_event_id"),
        sa.UniqueConstraint("alert_db_id", "sequence", name="uq_m43_alert_event_sequence"),
    )
    op.create_index("ix_m43_alert_event_time", "canonical_parser_live_operational_alert_events", ["alert_db_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_m43_alert_event_time", table_name="canonical_parser_live_operational_alert_events")
    op.drop_table("canonical_parser_live_operational_alert_events")
    op.drop_index("ix_m43_alert_last_seen", table_name="canonical_parser_live_operational_alerts")
    op.drop_index("ix_m43_alert_severity_status", table_name="canonical_parser_live_operational_alerts")
    op.drop_index("ix_m43_alert_fingerprint_status", table_name="canonical_parser_live_operational_alerts")
    op.drop_table("canonical_parser_live_operational_alerts")
    op.drop_index("ix_m43_snapshot_expiry", table_name="canonical_parser_live_observability_snapshots")
    op.drop_index("ix_m43_snapshot_status_time", table_name="canonical_parser_live_observability_snapshots")
    op.drop_table("canonical_parser_live_observability_snapshots")
