"""add paper admission canary

Revision ID: c4e1a7d9b625
Revises: b2d8f4a6c913
Create Date: 2026-07-27 16:30:00.000000
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "c4e1a7d9b625"
down_revision: str | Sequence[str] | None = "b2d8f4a6c913"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_paper_admission_canary_runs",
        sa.Column("id", pk, primary_key=True),
        sa.Column("canary_id", sa.String(36), nullable=False),
        sa.Column("canary_key", sa.String(64), nullable=False),
        sa.Column("binding_db_id", pk, nullable=False),
        sa.Column("binding_id", sa.String(36), nullable=False),
        sa.Column("binding_event_hash", sa.String(64), nullable=False),
        sa.Column("certification_id", sa.String(36), nullable=False),
        sa.Column("assessment_id", sa.String(36), nullable=False),
        sa.Column("paper_account_id", sa.Integer(), nullable=False),
        sa.Column("source_result_count", sa.Integer(), nullable=False),
        sa.Column("admissible_count", sa.Integer(), nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False),
        sa.Column("blocked_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("source_evidence_hash", sa.String(64), nullable=False),
        sa.Column("account_state_hash", sa.String(64), nullable=False),
        sa.Column("account_state_snapshot", sa.JSON(), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("metrics_snapshot", sa.JSON(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('PASSED', 'REVIEW', 'BLOCKED', 'INSUFFICIENT_DATA')", name="ck_parser_paper_admission_canary_runs_status"),
        sa.CheckConstraint("source_result_count >= 0 AND admissible_count >= 0 AND review_count >= 0 AND blocked_count >= 0", name="ck_parser_paper_admission_canary_runs_counts"),
        sa.CheckConstraint("source_result_count = admissible_count + review_count + blocked_count", name="ck_parser_paper_admission_canary_runs_breakdown"),
        sa.CheckConstraint("length(canary_key) = 64", name="ck_parser_paper_admission_canary_runs_key"),
        sa.CheckConstraint("length(binding_event_hash) = 64", name="ck_parser_paper_admission_canary_runs_binding_hash"),
        sa.CheckConstraint("length(source_evidence_hash) = 64", name="ck_parser_paper_admission_canary_runs_source_hash"),
        sa.CheckConstraint("length(account_state_hash) = 64", name="ck_parser_paper_admission_canary_runs_account_hash"),
        sa.CheckConstraint("length(policy_hash) = 64", name="ck_parser_paper_admission_canary_runs_policy_hash"),
        sa.ForeignKeyConstraint(["binding_db_id"], ["canonical_parser_paper_runtime_bindings.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["paper_account_id"], ["paper_accounts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("canary_id", name="uq_parser_paper_admission_canary_runs_id"),
        sa.UniqueConstraint("canary_key", name="uq_parser_paper_admission_canary_runs_key"),
    )
    op.create_index("ix_parser_paper_admission_canary_runs_status_completed", "canonical_parser_paper_admission_canary_runs", ["status", "completed_at"])
    op.create_index("ix_parser_paper_admission_canary_runs_binding", "canonical_parser_paper_admission_canary_runs", ["binding_db_id", "started_at"])
    op.create_table(
        "canonical_parser_paper_admission_canary_results",
        sa.Column("id", pk, primary_key=True),
        sa.Column("result_id", sa.String(36), nullable=False),
        sa.Column("canary_run_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("source_projection_result_db_id", pk, nullable=False),
        sa.Column("source_projection_result_id", sa.String(36), nullable=False),
        sa.Column("source_projection_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("token_mint", sa.String(64), nullable=True),
        sa.Column("token_amount", sa.String(120), nullable=True),
        sa.Column("sol_amount", sa.String(120), nullable=True),
        sa.Column("projected_cash_after_sol", sa.String(120), nullable=True),
        sa.Column("projected_open_positions", sa.Integer(), nullable=False),
        sa.Column("canary_payload", sa.JSON(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("canary_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_parser_paper_admission_canary_results_sequence"),
        sa.CheckConstraint("status IN ('ADMISSIBLE', 'REVIEW', 'BLOCKED')", name="ck_parser_paper_admission_canary_results_status"),
        sa.CheckConstraint("action IN ('BUY', 'SELL', 'UNKNOWN')", name="ck_parser_paper_admission_canary_results_action"),
        sa.CheckConstraint("length(source_projection_hash) = 64", name="ck_parser_paper_admission_canary_results_projection_hash"),
        sa.CheckConstraint("length(canary_hash) = 64", name="ck_parser_paper_admission_canary_results_hash"),
        sa.ForeignKeyConstraint(["canary_run_db_id"], ["canonical_parser_paper_admission_canary_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_projection_result_db_id"], ["canonical_parser_paper_projection_results.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("result_id", name="uq_parser_paper_admission_canary_results_id"),
        sa.UniqueConstraint("canary_run_db_id", "sequence", name="uq_parser_paper_admission_canary_results_sequence"),
        sa.UniqueConstraint("canary_run_db_id", "source_projection_result_db_id", name="uq_parser_paper_admission_canary_results_source"),
    )
    op.create_index("ix_parser_paper_admission_canary_results_run_status", "canonical_parser_paper_admission_canary_results", ["canary_run_db_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_parser_paper_admission_canary_results_run_status", table_name="canonical_parser_paper_admission_canary_results")
    op.drop_table("canonical_parser_paper_admission_canary_results")
    op.drop_index("ix_parser_paper_admission_canary_runs_binding", table_name="canonical_parser_paper_admission_canary_runs")
    op.drop_index("ix_parser_paper_admission_canary_runs_status_completed", table_name="canonical_parser_paper_admission_canary_runs")
    op.drop_table("canonical_parser_paper_admission_canary_runs")
