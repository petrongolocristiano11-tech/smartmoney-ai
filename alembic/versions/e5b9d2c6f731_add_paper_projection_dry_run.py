"""add paper projection dry run

Revision ID: e5b9d2c6f731
Revises: d3c7f1a5e824
Create Date: 2026-07-26 20:30:00.000000
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "e5b9d2c6f731"
down_revision: str | Sequence[str] | None = "d3c7f1a5e824"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_paper_projection_runs",
        sa.Column("id", pk, primary_key=True),
        sa.Column("projection_id", sa.String(36), nullable=False),
        sa.Column("projection_key", sa.String(64), nullable=False),
        sa.Column("certification_db_id", pk, nullable=False),
        sa.Column("certification_id", sa.String(36), nullable=False),
        sa.Column("certification_event_hash", sa.String(64), nullable=False),
        sa.Column("assessment_id", sa.String(36), nullable=False),
        sa.Column("source_run_count", sa.Integer(), nullable=False),
        sa.Column("source_result_count", sa.Integer(), nullable=False),
        sa.Column("projectable_count", sa.Integer(), nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("source_evidence_hash", sa.String(64), nullable=False),
        sa.Column("source_snapshot", sa.JSON(), nullable=False),
        sa.Column("metrics_snapshot", sa.JSON(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('PASSED', 'PARTIAL', 'BLOCKED', 'INSUFFICIENT_DATA')", name="ck_parser_paper_projection_runs_status"),
        sa.CheckConstraint("source_run_count >= 0 AND source_result_count >= 0 AND projectable_count >= 0 AND review_count >= 0 AND rejected_count >= 0", name="ck_parser_paper_projection_runs_counts"),
        sa.CheckConstraint("source_result_count = projectable_count + review_count + rejected_count", name="ck_parser_paper_projection_runs_breakdown"),
        sa.CheckConstraint("length(projection_key) = 64", name="ck_parser_paper_projection_runs_key"),
        sa.CheckConstraint("length(certification_event_hash) = 64", name="ck_parser_paper_projection_runs_cert_event_hash"),
        sa.CheckConstraint("length(policy_hash) = 64", name="ck_parser_paper_projection_runs_policy_hash"),
        sa.CheckConstraint("length(source_evidence_hash) = 64", name="ck_parser_paper_projection_runs_evidence_hash"),
        sa.ForeignKeyConstraint(["certification_db_id"], ["canonical_parser_shadow_reliability_certifications.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("projection_id", name="uq_parser_paper_projection_runs_id"),
        sa.UniqueConstraint("projection_key", name="uq_parser_paper_projection_runs_key"),
    )
    op.create_index("ix_parser_paper_projection_runs_status_completed", "canonical_parser_paper_projection_runs", ["status", "completed_at"])
    op.create_index("ix_parser_paper_projection_runs_certification", "canonical_parser_paper_projection_runs", ["certification_db_id", "started_at"])
    op.create_table(
        "canonical_parser_paper_projection_results",
        sa.Column("id", pk, primary_key=True),
        sa.Column("result_id", sa.String(36), nullable=False),
        sa.Column("projection_run_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("source_execution_run_db_id", pk, nullable=False),
        sa.Column("source_execution_run_id", sa.String(36), nullable=False),
        sa.Column("source_result_db_id", pk, nullable=False),
        sa.Column("source_result_id", sa.String(36), nullable=False),
        sa.Column("raw_event_id", sa.Integer(), nullable=False),
        sa.Column("artifact_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("wallet_address", sa.String(64), nullable=True),
        sa.Column("token_mint", sa.String(64), nullable=True),
        sa.Column("token_amount", sa.String(120), nullable=True),
        sa.Column("sol_amount", sa.String(120), nullable=True),
        sa.Column("artifact_hash", sa.String(64), nullable=False),
        sa.Column("projection_hash", sa.String(64), nullable=False),
        sa.Column("projection_payload", sa.JSON(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_parser_paper_projection_results_sequence"),
        sa.CheckConstraint("status IN ('PROJECTABLE', 'REVIEW', 'REJECTED')", name="ck_parser_paper_projection_results_status"),
        sa.CheckConstraint("action IN ('BUY', 'SELL', 'UNKNOWN')", name="ck_parser_paper_projection_results_action"),
        sa.CheckConstraint("artifact_index >= 0", name="ck_parser_paper_projection_results_artifact_index"),
        sa.CheckConstraint("length(artifact_hash) = 64", name="ck_parser_paper_projection_results_artifact_hash"),
        sa.CheckConstraint("length(projection_hash) = 64", name="ck_parser_paper_projection_results_projection_hash"),
        sa.ForeignKeyConstraint(["projection_run_db_id"], ["canonical_parser_paper_projection_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_execution_run_db_id"], ["canonical_parser_shadow_ticket_execution_runs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["source_result_db_id"], ["canonical_parser_shadow_ticket_execution_results.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("result_id", name="uq_parser_paper_projection_results_id"),
        sa.UniqueConstraint("projection_run_db_id", "sequence", name="uq_parser_paper_projection_results_sequence"),
        sa.UniqueConstraint("projection_run_db_id", "source_result_db_id", "artifact_index", name="uq_parser_paper_projection_results_source_artifact"),
    )
    op.create_index("ix_parser_paper_projection_results_run_status", "canonical_parser_paper_projection_results", ["projection_run_db_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_parser_paper_projection_results_run_status", table_name="canonical_parser_paper_projection_results")
    op.drop_table("canonical_parser_paper_projection_results")
    op.drop_index("ix_parser_paper_projection_runs_certification", table_name="canonical_parser_paper_projection_runs")
    op.drop_index("ix_parser_paper_projection_runs_status_completed", table_name="canonical_parser_paper_projection_runs")
    op.drop_table("canonical_parser_paper_projection_runs")
