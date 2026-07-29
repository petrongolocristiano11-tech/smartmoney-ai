"""add live incident response recovery

Revision ID: d6a8b1c4e520
Revises: c5f7a0b3d419
Create Date: 2026-07-29 15:10:00.000000
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "d6a8b1c4e520"
down_revision: str | Sequence[str] | None = "c5f7a0b3d419"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_live_incidents",
        sa.Column("id", pk, primary_key=True),
        sa.Column("incident_id", sa.String(36), nullable=False),
        sa.Column("incident_key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(40), nullable=False),
        sa.Column("source_type", sa.String(16), nullable=False),
        sa.Column("source_id", sa.String(96), nullable=False),
        sa.Column("category", sa.String(80), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("freeze_new_submissions", sa.Boolean(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("incident_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_event_sequence", sa.Integer(), nullable=False),
        sa.Column("latest_event_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope = 'M41_LIVE_INCIDENT_RESPONSE'", name="ck_m41_incident_scope"),
        sa.CheckConstraint("source_type IN ('SUBMISSION','SETTLEMENT','POSITION','MANUAL')", name="ck_m41_incident_source_type"),
        sa.CheckConstraint("severity IN ('LOW','MEDIUM','HIGH','CRITICAL')", name="ck_m41_incident_severity"),
        sa.CheckConstraint("status IN ('OPEN','ACKNOWLEDGED','RECOVERY_AUTHORIZED','RESOLVED')", name="ck_m41_incident_status"),
        sa.CheckConstraint("latest_event_sequence >= 1", name="ck_m41_incident_event_sequence"),
        sa.CheckConstraint("length(incident_key) = 64 AND length(evidence_hash) = 64 AND length(latest_event_hash) = 64", name="ck_m41_incident_hashes"),
        sa.UniqueConstraint("incident_id", name="uq_m41_incident_id"),
        sa.UniqueConstraint("incident_key", name="uq_m41_incident_key"),
    )
    op.create_index("ix_m41_incident_status_severity", "canonical_parser_live_incidents", ["status", "severity"])
    op.create_index("ix_m41_incident_source", "canonical_parser_live_incidents", ["source_type", "source_id"])

    op.create_table(
        "canonical_parser_live_incident_events",
        sa.Column("id", pk, primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("incident_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column("previous_event_hash", sa.String(64), nullable=True),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_m41_incident_event_sequence"),
        sa.CheckConstraint("event_type IN ('DECLARED','ACKNOWLEDGED','RECOVERY_AUTHORIZED','RECOVERY_REVOKED','RECOVERY_CONSUMED','RESOLVED')", name="ck_m41_incident_event_type"),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_m41_incident_event_hash"),
        sa.ForeignKeyConstraint(["incident_db_id"], ["canonical_parser_live_incidents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("event_id", name="uq_m41_incident_event_id"),
        sa.UniqueConstraint("incident_db_id", "sequence", name="uq_m41_incident_event_sequence"),
    )
    op.create_index("ix_m41_incident_event_time", "canonical_parser_live_incident_events", ["incident_db_id", "occurred_at"])

    op.create_table(
        "canonical_parser_live_recovery_authorizations",
        sa.Column("id", pk, primary_key=True),
        sa.Column("recovery_id", sa.String(36), nullable=False),
        sa.Column("recovery_key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(48), nullable=False),
        sa.Column("incident_db_id", pk, nullable=False),
        sa.Column("incident_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("target_type", sa.String(24), nullable=False),
        sa.Column("target_id", sa.String(96), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("recovery_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope = 'M41_MANUAL_LIVE_RECOVERY_AUTHORIZATION'", name="ck_m41_recovery_scope"),
        sa.CheckConstraint("action IN ('RECONCILE_SUBMISSION','RETRY_SETTLEMENT_READ','MANUAL_POSITION_REVIEW','FREEZE_NEW_SUBMISSIONS','UNFREEZE_NEW_SUBMISSIONS')", name="ck_m41_recovery_action"),
        sa.CheckConstraint("status IN ('ACTIVE','REVOKED','EXPIRED','CONSUMED')", name="ck_m41_recovery_status"),
        sa.CheckConstraint("length(recovery_key) = 64 AND length(evidence_hash) = 64", name="ck_m41_recovery_hashes"),
        sa.ForeignKeyConstraint(["incident_db_id"], ["canonical_parser_live_incidents.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("recovery_id", name="uq_m41_recovery_id"),
        sa.UniqueConstraint("recovery_key", name="uq_m41_recovery_key"),
    )
    op.create_index("ix_m41_recovery_incident_status", "canonical_parser_live_recovery_authorizations", ["incident_db_id", "status"])
    op.create_index("ix_m41_recovery_status_expiry", "canonical_parser_live_recovery_authorizations", ["status", "expires_at"])


def downgrade() -> None:
    op.drop_index("ix_m41_recovery_status_expiry", table_name="canonical_parser_live_recovery_authorizations")
    op.drop_index("ix_m41_recovery_incident_status", table_name="canonical_parser_live_recovery_authorizations")
    op.drop_table("canonical_parser_live_recovery_authorizations")
    op.drop_index("ix_m41_incident_event_time", table_name="canonical_parser_live_incident_events")
    op.drop_table("canonical_parser_live_incident_events")
    op.drop_index("ix_m41_incident_source", table_name="canonical_parser_live_incidents")
    op.drop_index("ix_m41_incident_status_severity", table_name="canonical_parser_live_incidents")
    op.drop_table("canonical_parser_live_incidents")
