"""add live portfolio risk governance

Revision ID: e7b9c2d5f631
Revises: d6a8b1c4e520
Create Date: 2026-07-29 15:20:00.000000
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "e7b9c2d5f631"
down_revision: str | Sequence[str] | None = "d6a8b1c4e520"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_live_portfolio_risk_assessments",
        sa.Column("id", pk, primary_key=True),
        sa.Column("assessment_id", sa.String(36), nullable=False),
        sa.Column("assessment_key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(48), nullable=False),
        sa.Column("wallet_address", sa.String(64), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("requested_token_mint", sa.String(64), nullable=False),
        sa.Column("requested_budget_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("open_position_count", sa.Integer(), nullable=False),
        sa.Column("stale_position_count", sa.Integer(), nullable=False),
        sa.Column("active_incident_count", sa.Integer(), nullable=False),
        sa.Column("total_cost_basis_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("current_value_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("unrealized_pnl_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("pending_buy_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("gross_exposure_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("max_token_concentration_percent", sa.Numeric(12, 6), nullable=False),
        sa.Column("largest_token_mint", sa.String(64), nullable=True),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("position_breakdown", sa.JSON(), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope = 'M42_AGGREGATED_LIVE_PORTFOLIO_RISK'", name="ck_m42_assessment_scope"),
        sa.CheckConstraint("status IN ('READY','REVIEW','BLOCKED','INSUFFICIENT_DATA')", name="ck_m42_assessment_status"),
        sa.CheckConstraint("side IN ('BUY','SELL')", name="ck_m42_assessment_side"),
        sa.CheckConstraint("open_position_count >= 0 AND stale_position_count >= 0 AND active_incident_count >= 0", name="ck_m42_assessment_counts"),
        sa.CheckConstraint("total_cost_basis_sol >= 0 AND current_value_sol >= 0 AND pending_buy_sol >= 0 AND gross_exposure_sol >= 0 AND requested_budget_sol >= 0", name="ck_m42_assessment_values"),
        sa.CheckConstraint("max_token_concentration_percent >= 0 AND max_token_concentration_percent <= 100", name="ck_m42_assessment_concentration"),
        sa.CheckConstraint("length(assessment_key) = 64 AND length(evidence_hash) = 64", name="ck_m42_assessment_hashes"),
        sa.UniqueConstraint("assessment_id", name="uq_m42_assessment_id"),
        sa.UniqueConstraint("assessment_key", name="uq_m42_assessment_key"),
    )
    op.create_index("ix_m42_assessment_wallet_time", "canonical_parser_live_portfolio_risk_assessments", ["wallet_address", "assessed_at"])
    op.create_index("ix_m42_assessment_status_expiry", "canonical_parser_live_portfolio_risk_assessments", ["status", "expires_at"])

    op.create_table(
        "canonical_parser_live_portfolio_risk_permits",
        sa.Column("id", pk, primary_key=True),
        sa.Column("permit_id", sa.String(36), nullable=False),
        sa.Column("permit_key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(48), nullable=False),
        sa.Column("assessment_db_id", pk, nullable=False),
        sa.Column("assessment_id", sa.String(36), nullable=False),
        sa.Column("wallet_address", sa.String(64), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("token_mint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("requested_budget_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("max_additional_exposure_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("permit_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_submission_id", sa.String(36), nullable=True),
        sa.Column("latest_event_sequence", sa.Integer(), nullable=False),
        sa.Column("latest_event_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope = 'M42_MANUAL_PORTFOLIO_RISK_PERMIT'", name="ck_m42_permit_scope"),
        sa.CheckConstraint("side IN ('BUY','SELL')", name="ck_m42_permit_side"),
        sa.CheckConstraint("status IN ('ACTIVE','REVOKED','EXPIRED','CONSUMED')", name="ck_m42_permit_status"),
        sa.CheckConstraint("requested_budget_sol >= 0 AND max_additional_exposure_sol >= 0", name="ck_m42_permit_values"),
        sa.CheckConstraint("latest_event_sequence >= 1", name="ck_m42_permit_event_sequence"),
        sa.CheckConstraint("length(permit_key) = 64 AND length(evidence_hash) = 64 AND length(latest_event_hash) = 64", name="ck_m42_permit_hashes"),
        sa.ForeignKeyConstraint(["assessment_db_id"], ["canonical_parser_live_portfolio_risk_assessments.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("permit_id", name="uq_m42_permit_id"),
        sa.UniqueConstraint("permit_key", name="uq_m42_permit_key"),
    )
    op.create_index("ix_m42_permit_wallet_status", "canonical_parser_live_portfolio_risk_permits", ["wallet_address", "status"])
    op.create_index("ix_m42_permit_status_expiry", "canonical_parser_live_portfolio_risk_permits", ["status", "expires_at"])

    op.create_table(
        "canonical_parser_live_portfolio_risk_permit_events",
        sa.Column("id", pk, primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("permit_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column("previous_event_hash", sa.String(64), nullable=True),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_m42_permit_event_sequence"),
        sa.CheckConstraint("event_type IN ('ISSUED','REVOKED','EXPIRED','CONSUMED')", name="ck_m42_permit_event_type"),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_m42_permit_event_hash"),
        sa.ForeignKeyConstraint(["permit_db_id"], ["canonical_parser_live_portfolio_risk_permits.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("event_id", name="uq_m42_permit_event_id"),
        sa.UniqueConstraint("permit_db_id", "sequence", name="uq_m42_permit_event_sequence"),
    )
    op.create_index("ix_m42_permit_event_time", "canonical_parser_live_portfolio_risk_permit_events", ["permit_db_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_m42_permit_event_time", table_name="canonical_parser_live_portfolio_risk_permit_events")
    op.drop_table("canonical_parser_live_portfolio_risk_permit_events")
    op.drop_index("ix_m42_permit_status_expiry", table_name="canonical_parser_live_portfolio_risk_permits")
    op.drop_index("ix_m42_permit_wallet_status", table_name="canonical_parser_live_portfolio_risk_permits")
    op.drop_table("canonical_parser_live_portfolio_risk_permits")
    op.drop_index("ix_m42_assessment_status_expiry", table_name="canonical_parser_live_portfolio_risk_assessments")
    op.drop_index("ix_m42_assessment_wallet_time", table_name="canonical_parser_live_portfolio_risk_assessments")
    op.drop_table("canonical_parser_live_portfolio_risk_assessments")
