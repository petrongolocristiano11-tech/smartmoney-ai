"""add paper reliability calibration campaign

Revision ID: b8e5d0f3a742
Revises: a7d4c9e2f631
Create Date: 2026-07-28 21:30:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "b8e5d0f3a742"
down_revision: str | Sequence[str] | None = "a7d4c9e2f631"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_paper_calibration_campaigns",
        sa.Column("id", pk, primary_key=True),
        sa.Column("campaign_id", sa.String(36), nullable=False),
        sa.Column("campaign_key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("paper_account_id", sa.Integer(), nullable=False),
        sa.Column("permit_id", sa.String(36), nullable=True),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("settled_count", sa.Integer(), nullable=False),
        sa.Column("released_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("reconciliation_required_count", sa.Integer(), nullable=False),
        sa.Column("buy_count", sa.Integer(), nullable=False),
        sa.Column("sell_count", sa.Integer(), nullable=False),
        sa.Column("closed_outcome_count", sa.Integer(), nullable=False),
        sa.Column("winning_outcome_count", sa.Integer(), nullable=False),
        sa.Column("realized_pnl_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("total_fee_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("estimated_slippage_cost_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("win_rate_percent", sa.Numeric(7, 4), nullable=False),
        sa.Column("profit_factor", sa.Numeric(20, 9), nullable=True),
        sa.Column("brier_score", sa.Numeric(12, 9), nullable=True),
        sa.Column("calibration_gap_percent", sa.Numeric(7, 4), nullable=True),
        sa.Column("reliability_score", sa.Numeric(7, 4), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("segments", sa.JSON(), nullable=False),
        sa.Column("recommendations", sa.JSON(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_ended_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('READY', 'REVIEW', 'BLOCKED', 'INSUFFICIENT_DATA')", name="ck_parser_paper_calibration_campaigns_status"),
        sa.CheckConstraint("scope = 'PAPER_ANALYTICS_ONLY'", name="ck_parser_paper_calibration_campaigns_scope"),
        sa.CheckConstraint("attempt_count >= 0 AND settled_count >= 0 AND released_count >= 0 AND failed_count >= 0", name="ck_parser_paper_calibration_campaigns_attempt_counts"),
        sa.CheckConstraint("buy_count >= 0 AND sell_count >= 0 AND closed_outcome_count >= 0 AND winning_outcome_count >= 0", name="ck_parser_paper_calibration_campaigns_outcome_counts"),
        sa.CheckConstraint("length(campaign_key) = 64", name="ck_parser_paper_calibration_campaigns_key"),
        sa.CheckConstraint("length(policy_hash) = 64", name="ck_parser_paper_calibration_campaigns_policy_hash"),
        sa.CheckConstraint("length(evidence_hash) = 64", name="ck_parser_paper_calibration_campaigns_evidence_hash"),
        sa.ForeignKeyConstraint(["paper_account_id"], ["paper_accounts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("campaign_id", name="uq_parser_paper_calibration_campaigns_id"),
        sa.UniqueConstraint("campaign_key", name="uq_parser_paper_calibration_campaigns_key"),
    )
    op.create_index("ix_parser_paper_calibration_campaigns_account_completed", "canonical_parser_paper_calibration_campaigns", ["paper_account_id", "completed_at"])
    op.create_index("ix_parser_paper_calibration_campaigns_status_completed", "canonical_parser_paper_calibration_campaigns", ["status", "completed_at"])

    op.create_table(
        "canonical_parser_paper_calibration_evidence",
        sa.Column("id", pk, primary_key=True),
        sa.Column("campaign_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("execution_db_id", pk, nullable=False),
        sa.Column("execution_id", sa.String(36), nullable=False),
        sa.Column("execution_status", sa.String(32), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("token_mint", sa.String(64), nullable=False),
        sa.Column("signal_score", sa.Numeric(7, 4), nullable=False),
        sa.Column("confidence_score", sa.Numeric(7, 4), nullable=False),
        sa.Column("realized_pnl_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("evidence_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_parser_paper_calibration_evidence_sequence"),
        sa.CheckConstraint("length(evidence_hash) = 64", name="ck_parser_paper_calibration_evidence_hash"),
        sa.ForeignKeyConstraint(["campaign_db_id"], ["canonical_parser_paper_calibration_campaigns.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["execution_db_id"], ["canonical_parser_permit_bound_paper_executions.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("campaign_db_id", "sequence", name="uq_parser_paper_calibration_evidence_sequence"),
        sa.UniqueConstraint("campaign_db_id", "execution_db_id", name="uq_parser_paper_calibration_evidence_execution"),
    )
    op.create_index("ix_parser_paper_calibration_evidence_campaign_status", "canonical_parser_paper_calibration_evidence", ["campaign_db_id", "execution_status"])


def downgrade() -> None:
    op.drop_index("ix_parser_paper_calibration_evidence_campaign_status", table_name="canonical_parser_paper_calibration_evidence")
    op.drop_table("canonical_parser_paper_calibration_evidence")
    op.drop_index("ix_parser_paper_calibration_campaigns_status_completed", table_name="canonical_parser_paper_calibration_campaigns")
    op.drop_index("ix_parser_paper_calibration_campaigns_account_completed", table_name="canonical_parser_paper_calibration_campaigns")
    op.drop_table("canonical_parser_paper_calibration_campaigns")
