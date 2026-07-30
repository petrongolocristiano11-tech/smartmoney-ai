"""add progressive automation production hardening

Revision ID: c1f3a6b9d075
Revises: b0e2f5a8c964
Create Date: 2026-07-29 20:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c1f3a6b9d075"
down_revision: Union[str, Sequence[str], None] = "b0e2f5a8c964"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_production_hardening_assessments",
        sa.Column("id", pk, primary_key=True),
        sa.Column("assessment_id", sa.String(36), nullable=False),
        sa.Column("assessment_key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("wallet_address", sa.String(64), nullable=False),
        sa.Column("network", sa.String(32), nullable=False),
        sa.Column("token_mint", sa.String(64), nullable=False),
        sa.Column("requested_stage", sa.String(32), nullable=False),
        sa.Column("eligible_stage", sa.String(32), nullable=False),
        sa.Column("completed_pilot_count", sa.Integer(), nullable=False),
        sa.Column("aborted_pilot_count", sa.Integer(), nullable=False),
        sa.Column("expired_pilot_count", sa.Integer(), nullable=False),
        sa.Column("unresolved_submission_count", sa.Integer(), nullable=False),
        sa.Column("active_incident_count", sa.Integer(), nullable=False),
        sa.Column("open_critical_alert_count", sa.Integer(), nullable=False),
        sa.Column("latest_observability_snapshot_id", sa.String(36), nullable=True),
        sa.Column("requested_max_budget_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("recommended_max_budget_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("requested_max_submissions", sa.Integer(), nullable=False),
        sa.Column("recommended_max_submissions", sa.Integer(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("evidence_snapshot", sa.JSON(), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope = 'M46_PRODUCTION_HARDENING_ASSESSMENT'", name="ck_m46_assessment_scope"),
        sa.CheckConstraint("network = 'mainnet-beta'", name="ck_m46_assessment_network"),
        sa.CheckConstraint("status IN ('READY','BLOCKED','INSUFFICIENT_DATA')", name="ck_m46_assessment_status"),
        sa.CheckConstraint("requested_stage IN ('OBSERVE_ONLY','ASSISTED','SUPERVISED','AUTOMATION_CANDIDATE')", name="ck_m46_assessment_requested_stage"),
        sa.CheckConstraint("eligible_stage IN ('OBSERVE_ONLY','ASSISTED','SUPERVISED','AUTOMATION_CANDIDATE')", name="ck_m46_assessment_eligible_stage"),
        sa.CheckConstraint("completed_pilot_count >= 0 AND aborted_pilot_count >= 0 AND expired_pilot_count >= 0", name="ck_m46_assessment_pilot_counts"),
        sa.CheckConstraint("unresolved_submission_count >= 0 AND active_incident_count >= 0 AND open_critical_alert_count >= 0", name="ck_m46_assessment_risk_counts"),
        sa.CheckConstraint("requested_max_budget_sol >= 0 AND recommended_max_budget_sol >= 0", name="ck_m46_assessment_budgets"),
        sa.CheckConstraint("requested_max_submissions >= 0 AND recommended_max_submissions >= 0", name="ck_m46_assessment_submission_counts"),
        sa.CheckConstraint("length(assessment_key) = 64 AND length(evidence_hash) = 64", name="ck_m46_assessment_hashes"),
        sa.UniqueConstraint("assessment_id", name="uq_m46_assessment_id"),
        sa.UniqueConstraint("assessment_key", name="uq_m46_assessment_key"),
    )
    op.create_index("ix_m46_assessment_wallet_time", "canonical_parser_production_hardening_assessments", ["wallet_address", "assessed_at"])
    op.create_index("ix_m46_assessment_token_status", "canonical_parser_production_hardening_assessments", ["token_mint", "status"])

    op.create_table(
        "canonical_parser_progressive_automation_leases",
        sa.Column("id", pk, primary_key=True),
        sa.Column("lease_id", sa.String(36), nullable=False),
        sa.Column("lease_key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("assessment_db_id", pk, nullable=False),
        sa.Column("assessment_id", sa.String(36), nullable=False),
        sa.Column("wallet_address", sa.String(64), nullable=False),
        sa.Column("network", sa.String(32), nullable=False),
        sa.Column("token_mint", sa.String(64), nullable=False),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("max_budget_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("max_submission_count", sa.Integer(), nullable=False),
        sa.Column("used_submission_count", sa.Integer(), nullable=False),
        sa.Column("automatic_dispatch_permitted", sa.Boolean(), nullable=False),
        sa.Column("lease_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tripped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exhausted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_event_sequence", sa.Integer(), nullable=False),
        sa.Column("latest_event_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope = 'M46_PROGRESSIVE_AUTOMATION_LEASE'", name="ck_m46_lease_scope"),
        sa.CheckConstraint("network = 'mainnet-beta'", name="ck_m46_lease_network"),
        sa.CheckConstraint("stage IN ('OBSERVE_ONLY','ASSISTED','SUPERVISED','AUTOMATION_CANDIDATE')", name="ck_m46_lease_stage"),
        sa.CheckConstraint("status IN ('ACTIVE','REVOKED','EXPIRED','EXHAUSTED','TRIPPED')", name="ck_m46_lease_status"),
        sa.CheckConstraint("max_budget_sol >= 0", name="ck_m46_lease_budget"),
        sa.CheckConstraint("max_submission_count >= 0 AND used_submission_count >= 0 AND used_submission_count <= max_submission_count", name="ck_m46_lease_submission_counts"),
        sa.CheckConstraint("automatic_dispatch_permitted = false", name="ck_m46_lease_no_auto_dispatch"),
        sa.CheckConstraint("latest_event_sequence >= 1", name="ck_m46_lease_event_sequence"),
        sa.CheckConstraint("length(lease_key) = 64 AND length(evidence_hash) = 64 AND length(latest_event_hash) = 64", name="ck_m46_lease_hashes"),
        sa.ForeignKeyConstraint(["assessment_db_id"], ["canonical_parser_production_hardening_assessments.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("lease_id", name="uq_m46_lease_id"),
        sa.UniqueConstraint("lease_key", name="uq_m46_lease_key"),
    )
    op.create_index("ix_m46_lease_wallet_status", "canonical_parser_progressive_automation_leases", ["wallet_address", "status"])
    op.create_index("ix_m46_lease_token_status", "canonical_parser_progressive_automation_leases", ["token_mint", "status"])
    op.create_index("ix_m46_lease_expiry", "canonical_parser_progressive_automation_leases", ["status", "expires_at"])

    op.create_table(
        "canonical_parser_progressive_automation_lease_events",
        sa.Column("id", pk, primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("lease_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column("previous_event_hash", sa.String(64), nullable=True),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_m46_lease_event_sequence"),
        sa.CheckConstraint("event_type IN ('ISSUED','CONSUMED','EXHAUSTED','REVOKED','TRIPPED','EXPIRED')", name="ck_m46_lease_event_type"),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_m46_lease_event_hash"),
        sa.ForeignKeyConstraint(["lease_db_id"], ["canonical_parser_progressive_automation_leases.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("event_id", name="uq_m46_lease_event_id"),
        sa.UniqueConstraint("lease_db_id", "sequence", name="uq_m46_lease_event_sequence"),
    )
    op.create_index("ix_m46_lease_event_time", "canonical_parser_progressive_automation_lease_events", ["lease_db_id", "occurred_at"])

    op.create_table(
        "canonical_parser_production_circuit_breakers",
        sa.Column("id", pk, primary_key=True),
        sa.Column("breaker_id", sa.String(36), nullable=False),
        sa.Column("breaker_key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("wallet_address", sa.String(64), nullable=False),
        sa.Column("network", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("source_type", sa.String(24), nullable=False),
        sa.Column("source_id", sa.String(96), nullable=True),
        sa.Column("trip_count", sa.Integer(), nullable=False),
        sa.Column("reset_count", sa.Integer(), nullable=False),
        sa.Column("breaker_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("tripped_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reset_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_event_sequence", sa.Integer(), nullable=False),
        sa.Column("latest_event_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope = 'M46_PRODUCTION_CIRCUIT_BREAKER'", name="ck_m46_breaker_scope"),
        sa.CheckConstraint("network = 'mainnet-beta'", name="ck_m46_breaker_network"),
        sa.CheckConstraint("status IN ('CLEAR','TRIPPED')", name="ck_m46_breaker_status"),
        sa.CheckConstraint("source_type IN ('MANUAL','INCIDENT','OBSERVABILITY','SUBMISSION')", name="ck_m46_breaker_source"),
        sa.CheckConstraint("trip_count >= 1 AND reset_count >= 0", name="ck_m46_breaker_counts"),
        sa.CheckConstraint("latest_event_sequence >= 1", name="ck_m46_breaker_event_sequence"),
        sa.CheckConstraint("length(breaker_key) = 64 AND length(evidence_hash) = 64 AND length(latest_event_hash) = 64", name="ck_m46_breaker_hashes"),
        sa.UniqueConstraint("breaker_id", name="uq_m46_breaker_id"),
        sa.UniqueConstraint("wallet_address", name="uq_m46_breaker_wallet"),
    )
    op.create_index("ix_m46_breaker_status", "canonical_parser_production_circuit_breakers", ["status", "tripped_at"])

    op.create_table(
        "canonical_parser_production_circuit_breaker_events",
        sa.Column("id", pk, primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("breaker_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column("previous_event_hash", sa.String(64), nullable=True),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_m46_breaker_event_sequence"),
        sa.CheckConstraint("event_type IN ('TRIPPED','RESET')", name="ck_m46_breaker_event_type"),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_m46_breaker_event_hash"),
        sa.ForeignKeyConstraint(["breaker_db_id"], ["canonical_parser_production_circuit_breakers.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("event_id", name="uq_m46_breaker_event_id"),
        sa.UniqueConstraint("breaker_db_id", "sequence", name="uq_m46_breaker_event_sequence"),
    )
    op.create_index("ix_m46_breaker_event_time", "canonical_parser_production_circuit_breaker_events", ["breaker_db_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_m46_breaker_event_time", table_name="canonical_parser_production_circuit_breaker_events")
    op.drop_table("canonical_parser_production_circuit_breaker_events")
    op.drop_index("ix_m46_breaker_status", table_name="canonical_parser_production_circuit_breakers")
    op.drop_table("canonical_parser_production_circuit_breakers")
    op.drop_index("ix_m46_lease_event_time", table_name="canonical_parser_progressive_automation_lease_events")
    op.drop_table("canonical_parser_progressive_automation_lease_events")
    op.drop_index("ix_m46_lease_expiry", table_name="canonical_parser_progressive_automation_leases")
    op.drop_index("ix_m46_lease_token_status", table_name="canonical_parser_progressive_automation_leases")
    op.drop_index("ix_m46_lease_wallet_status", table_name="canonical_parser_progressive_automation_leases")
    op.drop_table("canonical_parser_progressive_automation_leases")
    op.drop_index("ix_m46_assessment_token_status", table_name="canonical_parser_production_hardening_assessments")
    op.drop_index("ix_m46_assessment_wallet_time", table_name="canonical_parser_production_hardening_assessments")
    op.drop_table("canonical_parser_production_hardening_assessments")
