"""add micro live canary governance

Revision ID: d0a2b5c8e964
Revises: c9f1a4b7d853
Create Date: 2026-07-28 23:40:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "d0a2b5c8e964"
down_revision: str | Sequence[str] | None = "c9f1a4b7d853"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_micro_live_canary_permits",
        sa.Column("id", pk, primary_key=True),
        sa.Column("permit_id", sa.String(36), nullable=False),
        sa.Column("permit_key", sa.String(64), nullable=False),
        sa.Column("operational_assessment_db_id", pk, nullable=False),
        sa.Column("operational_assessment_id", sa.String(36), nullable=False),
        sa.Column("assessment_evidence_hash", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(48), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("requested_validity_minutes", sa.Integer(), nullable=False),
        sa.Column("total_budget_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("max_order_budget_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("max_order_count", sa.Integer(), nullable=False),
        sa.Column("simulated_budget_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("simulated_order_count", sa.Integer(), nullable=False),
        sa.Column("live_policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("live_platform_snapshot", sa.JSON(), nullable=False),
        sa.Column("policy_version", sa.String(80), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
        sa.Column("latest_event_sequence", sa.Integer(), nullable=False),
        sa.Column("latest_event_hash", sa.String(64), nullable=True),
        sa.Column("technical_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope = 'MICRO_LIVE_GOVERNANCE_SIMULATION_ONLY'", name="ck_m35_permit_scope"),
        sa.CheckConstraint("status IN ('ACTIVE','REVOKED','EXPIRED','EXHAUSTED')", name="ck_m35_permit_status"),
        sa.CheckConstraint("total_budget_sol > 0 AND max_order_budget_sol > 0 AND max_order_budget_sol <= total_budget_sol", name="ck_m35_permit_budgets"),
        sa.CheckConstraint("max_order_count >= 1 AND simulated_order_count >= 0 AND simulated_budget_sol >= 0", name="ck_m35_permit_counts"),
        sa.CheckConstraint("length(permit_key) = 64 AND length(assessment_evidence_hash) = 64 AND length(policy_hash) = 64", name="ck_m35_permit_hashes"),
        sa.ForeignKeyConstraint(["operational_assessment_db_id"], ["canonical_parser_paper_operational_assessments.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("permit_id", name="uq_m35_permit_id"),
        sa.UniqueConstraint("permit_key", name="uq_m35_permit_key"),
    )
    op.create_index("ix_m35_permit_status_expiry", "canonical_parser_micro_live_canary_permits", ["status", "expires_at"])

    op.create_table(
        "canonical_parser_micro_live_canary_permit_events",
        sa.Column("id", pk, primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("permit_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column("previous_event_hash", sa.String(64), nullable=True),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_m35_event_sequence"),
        sa.CheckConstraint("event_type IN ('ISSUED','SIMULATED','REVOKED','EXPIRED','EXHAUSTED')", name="ck_m35_event_type"),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_m35_event_hash"),
        sa.ForeignKeyConstraint(["permit_db_id"], ["canonical_parser_micro_live_canary_permits.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("event_id", name="uq_m35_event_id"),
        sa.UniqueConstraint("permit_db_id", "sequence", name="uq_m35_event_sequence"),
    )
    op.create_index("ix_m35_event_permit_time", "canonical_parser_micro_live_canary_permit_events", ["permit_db_id", "occurred_at"])

    op.create_table(
        "canonical_parser_micro_live_canary_simulations",
        sa.Column("id", pk, primary_key=True),
        sa.Column("simulation_id", sa.String(36), nullable=False),
        sa.Column("simulation_key", sa.String(64), nullable=False),
        sa.Column("permit_db_id", pk, nullable=False),
        sa.Column("permit_id", sa.String(36), nullable=False),
        sa.Column("decision_result_db_id", pk, nullable=False),
        sa.Column("decision_result_id", sa.String(36), nullable=False),
        sa.Column("decision_hash", sa.String(64), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("token_mint", sa.String(64), nullable=False),
        sa.Column("requested_budget_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("simulated_budget_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("market_price_sol", sa.Numeric(36, 18), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("evidence_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("simulated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("side IN ('BUY','SELL')", name="ck_m35_sim_side"),
        sa.CheckConstraint("status IN ('READY','REVIEW','BLOCKED','INSUFFICIENT_DATA')", name="ck_m35_sim_status"),
        sa.CheckConstraint("requested_budget_sol >= 0 AND simulated_budget_sol >= 0 AND market_price_sol > 0", name="ck_m35_sim_values"),
        sa.CheckConstraint("length(simulation_key) = 64 AND length(decision_hash) = 64 AND length(evidence_hash) = 64", name="ck_m35_sim_hashes"),
        sa.ForeignKeyConstraint(["permit_db_id"], ["canonical_parser_micro_live_canary_permits.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["decision_result_db_id"], ["canonical_parser_unified_decision_results.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("simulation_id", name="uq_m35_sim_id"),
        sa.UniqueConstraint("simulation_key", name="uq_m35_sim_key"),
    )
    op.create_index("ix_m35_sim_permit_created", "canonical_parser_micro_live_canary_simulations", ["permit_db_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_m35_sim_permit_created", table_name="canonical_parser_micro_live_canary_simulations")
    op.drop_table("canonical_parser_micro_live_canary_simulations")
    op.drop_index("ix_m35_event_permit_time", table_name="canonical_parser_micro_live_canary_permit_events")
    op.drop_table("canonical_parser_micro_live_canary_permit_events")
    op.drop_index("ix_m35_permit_status_expiry", table_name="canonical_parser_micro_live_canary_permits")
    op.drop_table("canonical_parser_micro_live_canary_permits")
