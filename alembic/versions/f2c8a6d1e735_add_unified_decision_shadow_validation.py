"""add unified decision shadow validation

Revision ID: f2c8a6d1e735
Revises: e3b8d5f1a942
Create Date: 2026-07-28 19:30:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "f2c8a6d1e735"
down_revision: str | Sequence[str] | None = "e3b8d5f1a942"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_unified_decision_runs",
        sa.Column("id", pk, primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("run_key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(40), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source_trade_count", sa.Integer(), nullable=False),
        sa.Column("source_token_count", sa.Integer(), nullable=False),
        sa.Column("source_wallet_count", sa.Integer(), nullable=False),
        sa.Column("qualified_wallet_count", sa.Integer(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("approve_count", sa.Integer(), nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False),
        sa.Column("reject_count", sa.Integer(), nullable=False),
        sa.Column("insufficient_data_count", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("safety", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("data_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("technical_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('COMPLETED', 'PARTIAL', 'FAILED')", name="ck_parser_unified_decision_runs_status"),
        sa.CheckConstraint("scope = 'SHADOW_DECISION_ONLY'", name="ck_parser_unified_decision_runs_scope"),
        sa.CheckConstraint("source_trade_count >= 0 AND source_token_count >= 0 AND source_wallet_count >= 0 AND qualified_wallet_count >= 0", name="ck_parser_unified_decision_runs_source_counts"),
        sa.CheckConstraint("result_count >= 0 AND approve_count >= 0 AND review_count >= 0 AND reject_count >= 0 AND insufficient_data_count >= 0", name="ck_parser_unified_decision_runs_decision_counts"),
        sa.CheckConstraint("result_count = approve_count + review_count + reject_count + insufficient_data_count", name="ck_parser_unified_decision_runs_decision_breakdown"),
        sa.CheckConstraint("length(run_key) = 64", name="ck_parser_unified_decision_runs_key"),
        sa.CheckConstraint("length(policy_hash) = 64", name="ck_parser_unified_decision_runs_policy_hash"),
        sa.CheckConstraint("length(evidence_hash) = 64", name="ck_parser_unified_decision_runs_evidence_hash"),
        sa.UniqueConstraint("run_id", name="uq_parser_unified_decision_runs_id"),
        sa.UniqueConstraint("run_key", name="uq_parser_unified_decision_runs_key"),
    )
    op.create_index("ix_parser_unified_decision_runs_status_completed", "canonical_parser_unified_decision_runs", ["status", "completed_at"])
    op.create_index("ix_parser_unified_decision_runs_valid_until", "canonical_parser_unified_decision_runs", ["valid_until"])

    op.create_table(
        "canonical_parser_unified_decision_results",
        sa.Column("id", pk, primary_key=True),
        sa.Column("result_id", sa.String(36), nullable=False),
        sa.Column("run_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(24), nullable=False),
        sa.Column("token_mint", sa.String(64), nullable=False),
        sa.Column("source_trade_ids", sa.JSON(), nullable=False),
        sa.Column("source_signatures", sa.JSON(), nullable=False),
        sa.Column("source_event_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_wallet_count", sa.Integer(), nullable=False),
        sa.Column("qualified_wallet_count", sa.Integer(), nullable=False),
        sa.Column("independent_cluster_count", sa.Integer(), nullable=False),
        sa.Column("follower_wallet_count", sa.Integer(), nullable=False),
        sa.Column("leader_wallet", sa.String(64), nullable=True),
        sa.Column("signal_score", sa.Numeric(7, 4), nullable=False),
        sa.Column("confidence_score", sa.Numeric(7, 4), nullable=False),
        sa.Column("uncertainty_score", sa.Numeric(7, 4), nullable=False),
        sa.Column("requested_size_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("approved_size_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("token_safety_status", sa.String(24), nullable=False),
        sa.Column("timing_status", sa.String(24), nullable=False),
        sa.Column("market_regime", sa.String(24), nullable=False),
        sa.Column("confidence_calibration_status", sa.String(32), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("positive_factors", sa.JSON(), nullable=False),
        sa.Column("evidence_snapshot", sa.JSON(), nullable=False),
        sa.Column("exit_plan", sa.JSON(), nullable=False),
        sa.Column("counterfactuals", sa.JSON(), nullable=False),
        sa.Column("decision_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("decision IN ('APPROVE', 'REVIEW', 'REJECT', 'INSUFFICIENT_DATA')", name="ck_parser_unified_decision_results_decision"),
        sa.CheckConstraint("token_safety_status IN ('SAFE', 'REVIEW', 'UNSAFE', 'INSUFFICIENT_DATA')", name="ck_parser_unified_decision_results_token_status"),
        sa.CheckConstraint("timing_status IN ('COPYABLE', 'LATE', 'STALE', 'INSUFFICIENT_DATA')", name="ck_parser_unified_decision_results_timing_status"),
        sa.CheckConstraint("raw_wallet_count >= 0 AND qualified_wallet_count >= 0 AND independent_cluster_count >= 0 AND follower_wallet_count >= 0", name="ck_parser_unified_decision_results_counts"),
        sa.CheckConstraint("signal_score >= 0 AND signal_score <= 100 AND confidence_score >= 0 AND confidence_score <= 100 AND uncertainty_score >= 0 AND uncertainty_score <= 100", name="ck_parser_unified_decision_results_scores"),
        sa.CheckConstraint("requested_size_sol >= 0 AND approved_size_sol >= 0 AND approved_size_sol <= requested_size_sol", name="ck_parser_unified_decision_results_sizes"),
        sa.CheckConstraint("sequence >= 1", name="ck_parser_unified_decision_results_sequence"),
        sa.CheckConstraint("length(decision_hash) = 64", name="ck_parser_unified_decision_results_hash"),
        sa.ForeignKeyConstraint(["run_db_id"], ["canonical_parser_unified_decision_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("result_id", name="uq_parser_unified_decision_results_id"),
        sa.UniqueConstraint("run_db_id", "sequence", name="uq_parser_unified_decision_results_sequence"),
        sa.UniqueConstraint("run_db_id", "token_mint", name="uq_parser_unified_decision_results_token"),
    )
    op.create_index("ix_parser_unified_decision_results_run_decision", "canonical_parser_unified_decision_results", ["run_db_id", "decision"])
    op.create_index("ix_parser_unified_decision_results_token_created", "canonical_parser_unified_decision_results", ["token_mint", "created_at"])

    op.create_table(
        "canonical_parser_unified_decision_wallet_evidence",
        sa.Column("id", pk, primary_key=True),
        sa.Column("evidence_id", sa.String(36), nullable=False),
        sa.Column("result_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("wallet_address", sa.String(64), nullable=False),
        sa.Column("cluster_key", sa.String(64), nullable=False),
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column("qualification_status", sa.String(24), nullable=False),
        sa.Column("final_score", sa.Numeric(7, 4), nullable=False),
        sa.Column("confidence_score", sa.Numeric(7, 4), nullable=False),
        sa.Column("freshness_status", sa.String(24), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("positive_factors", sa.JSON(), nullable=False),
        sa.Column("evidence_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_parser_unified_decision_wallet_evidence_sequence"),
        sa.CheckConstraint("qualification_status IN ('QUALIFIED', 'REVIEW', 'REJECTED', 'INSUFFICIENT_DATA', 'EXPIRED')", name="ck_parser_unified_decision_wallet_evidence_status"),
        sa.CheckConstraint("role IN ('EARLY_LEADER', 'CONFIRMING_LEADER', 'FOLLOWER', 'LATE_FOLLOWER', 'UNQUALIFIED')", name="ck_parser_unified_decision_wallet_evidence_role"),
        sa.CheckConstraint("final_score >= 0 AND final_score <= 100 AND confidence_score >= 0 AND confidence_score <= 100", name="ck_parser_unified_decision_wallet_evidence_scores"),
        sa.CheckConstraint("length(cluster_key) = 64", name="ck_parser_unified_decision_wallet_evidence_cluster"),
        sa.CheckConstraint("length(evidence_hash) = 64", name="ck_parser_unified_decision_wallet_evidence_hash"),
        sa.ForeignKeyConstraint(["result_db_id"], ["canonical_parser_unified_decision_results.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("evidence_id", name="uq_parser_unified_decision_wallet_evidence_id"),
        sa.UniqueConstraint("result_db_id", "wallet_address", name="uq_parser_unified_decision_wallet_evidence_wallet"),
        sa.UniqueConstraint("result_db_id", "sequence", name="uq_parser_unified_decision_wallet_evidence_sequence"),
    )
    op.create_index("ix_parser_unified_decision_wallet_evidence_result_status", "canonical_parser_unified_decision_wallet_evidence", ["result_db_id", "qualification_status"])
    op.create_index("ix_parser_unified_decision_wallet_evidence_wallet_created", "canonical_parser_unified_decision_wallet_evidence", ["wallet_address", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_parser_unified_decision_wallet_evidence_wallet_created", table_name="canonical_parser_unified_decision_wallet_evidence")
    op.drop_index("ix_parser_unified_decision_wallet_evidence_result_status", table_name="canonical_parser_unified_decision_wallet_evidence")
    op.drop_table("canonical_parser_unified_decision_wallet_evidence")
    op.drop_index("ix_parser_unified_decision_results_token_created", table_name="canonical_parser_unified_decision_results")
    op.drop_index("ix_parser_unified_decision_results_run_decision", table_name="canonical_parser_unified_decision_results")
    op.drop_table("canonical_parser_unified_decision_results")
    op.drop_index("ix_parser_unified_decision_runs_valid_until", table_name="canonical_parser_unified_decision_runs")
    op.drop_index("ix_parser_unified_decision_runs_status_completed", table_name="canonical_parser_unified_decision_runs")
    op.drop_table("canonical_parser_unified_decision_runs")
