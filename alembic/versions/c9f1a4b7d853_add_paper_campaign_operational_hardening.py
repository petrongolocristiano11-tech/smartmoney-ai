"""add paper campaign operational hardening

Revision ID: c9f1a4b7d853
Revises: b8e5d0f3a742
Create Date: 2026-07-28 23:20:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "c9f1a4b7d853"
down_revision: str | Sequence[str] | None = "b8e5d0f3a742"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_paper_campaign_runs",
        sa.Column("id", pk, primary_key=True),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("campaign_key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(40), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("paper_account_id", sa.Integer(), nullable=False),
        sa.Column("permit_id", sa.String(36), nullable=False),
        sa.Column("requested_count", sa.Integer(), nullable=False),
        sa.Column("selected_count", sa.Integer(), nullable=False),
        sa.Column("settled_count", sa.Integer(), nullable=False),
        sa.Column("released_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("reconciliation_required_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("requested_budget_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("settled_budget_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("policy_version", sa.String(80), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("safety", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope = 'PAPER_MANUAL_ORCHESTRATION'", name="ck_m34_campaign_scope"),
        sa.CheckConstraint("status IN ('COMPLETED','PARTIAL','BLOCKED','FAILED','NOOP','RECONCILIATION_REQUIRED')", name="ck_m34_campaign_status"),
        sa.CheckConstraint("requested_count >= 0 AND selected_count >= 0 AND settled_count >= 0 AND released_count >= 0 AND failed_count >= 0 AND reconciliation_required_count >= 0 AND skipped_count >= 0", name="ck_m34_campaign_counts"),
        sa.CheckConstraint("requested_budget_sol >= 0 AND settled_budget_sol >= 0", name="ck_m34_campaign_budget"),
        sa.CheckConstraint("length(campaign_key) = 64 AND length(policy_hash) = 64 AND length(evidence_hash) = 64", name="ck_m34_campaign_hashes"),
        sa.ForeignKeyConstraint(["paper_account_id"], ["paper_accounts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("campaign_id", name="uq_m34_campaign_id"),
        sa.UniqueConstraint("campaign_key", name="uq_m34_campaign_key"),
    )
    op.create_index("ix_m34_campaign_account_created", "canonical_parser_paper_campaign_runs", ["paper_account_id", "created_at"])
    op.create_index("ix_m34_campaign_status_created", "canonical_parser_paper_campaign_runs", ["status", "created_at"])

    op.create_table(
        "canonical_parser_paper_campaign_items",
        sa.Column("id", pk, primary_key=True),
        sa.Column("campaign_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("decision_result_id", sa.String(36), nullable=False),
        sa.Column("execution_id", sa.String(36), nullable=True),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("token_mint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("market_price_sol", sa.Numeric(36, 18), nullable=False),
        sa.Column("requested_budget_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("settled_budget_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=True),
        sa.Column("item_snapshot", sa.JSON(), nullable=False),
        sa.Column("item_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_m34_item_sequence"),
        sa.CheckConstraint("side IN ('BUY','SELL')", name="ck_m34_item_side"),
        sa.CheckConstraint("status IN ('SETTLED','RELEASED','FAILED','RECONCILIATION_REQUIRED','SKIPPED')", name="ck_m34_item_status"),
        sa.CheckConstraint("market_price_sol > 0 AND requested_budget_sol >= 0 AND settled_budget_sol >= 0", name="ck_m34_item_values"),
        sa.CheckConstraint("length(idempotency_key) = 64 AND length(item_hash) = 64", name="ck_m34_item_hashes"),
        sa.ForeignKeyConstraint(["campaign_db_id"], ["canonical_parser_paper_campaign_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("campaign_db_id", "sequence", name="uq_m34_item_sequence"),
        sa.UniqueConstraint("campaign_db_id", "decision_result_id", "side", name="uq_m34_item_decision_side"),
    )
    op.create_index("ix_m34_item_campaign_status", "canonical_parser_paper_campaign_items", ["campaign_db_id", "status"])

    op.create_table(
        "canonical_parser_paper_operational_assessments",
        sa.Column("id", pk, primary_key=True),
        sa.Column("assessment_id", sa.String(36), nullable=False),
        sa.Column("assessment_key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(40), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("paper_account_id", sa.Integer(), nullable=False),
        sa.Column("calibration_campaign_db_id", pk, nullable=True),
        sa.Column("calibration_campaign_id", sa.String(36), nullable=True),
        sa.Column("settled_count", sa.Integer(), nullable=False),
        sa.Column("reconciliation_required_count", sa.Integer(), nullable=False),
        sa.Column("stale_reservation_count", sa.Integer(), nullable=False),
        sa.Column("budget_drift_count", sa.Integer(), nullable=False),
        sa.Column("reliability_score", sa.Numeric(7, 4), nullable=True),
        sa.Column("calibration_gap_percent", sa.Numeric(7, 4), nullable=True),
        sa.Column("policy_version", sa.String(80), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('READY','REVIEW','BLOCKED','INSUFFICIENT_DATA')", name="ck_m34_assessment_status"),
        sa.CheckConstraint("scope = 'PAPER_OPERATIONAL_READINESS'", name="ck_m34_assessment_scope"),
        sa.CheckConstraint("settled_count >= 0 AND reconciliation_required_count >= 0 AND stale_reservation_count >= 0 AND budget_drift_count >= 0", name="ck_m34_assessment_counts"),
        sa.CheckConstraint("length(assessment_key) = 64 AND length(policy_hash) = 64 AND length(evidence_hash) = 64", name="ck_m34_assessment_hashes"),
        sa.ForeignKeyConstraint(["paper_account_id"], ["paper_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["calibration_campaign_db_id"], ["canonical_parser_paper_calibration_campaigns.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("assessment_id", name="uq_m34_assessment_id"),
        sa.UniqueConstraint("assessment_key", name="uq_m34_assessment_key"),
    )
    op.create_index("ix_m34_assessment_account_completed", "canonical_parser_paper_operational_assessments", ["paper_account_id", "completed_at"])


def downgrade() -> None:
    op.drop_index("ix_m34_assessment_account_completed", table_name="canonical_parser_paper_operational_assessments")
    op.drop_table("canonical_parser_paper_operational_assessments")
    op.drop_index("ix_m34_item_campaign_status", table_name="canonical_parser_paper_campaign_items")
    op.drop_table("canonical_parser_paper_campaign_items")
    op.drop_index("ix_m34_campaign_status_created", table_name="canonical_parser_paper_campaign_runs")
    op.drop_index("ix_m34_campaign_account_created", table_name="canonical_parser_paper_campaign_runs")
    op.drop_table("canonical_parser_paper_campaign_runs")
