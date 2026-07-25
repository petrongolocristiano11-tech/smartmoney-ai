"""add parser runtime admission canary

Revision ID: b4e6a9d1c027
Revises: a2d8f4c6b913
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b4e6a9d1c027"
down_revision: Union[str, Sequence[str], None] = "a2d8f4c6b913"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PK = sa.BigInteger().with_variant(sa.Integer(), "sqlite")


def upgrade() -> None:
    op.create_table(
        "canonical_parser_admission_runs",
        sa.Column("id", _PK, primary_key=True),
        sa.Column("admission_id", sa.String(36), nullable=False),
        sa.Column("admission_key", sa.String(64), nullable=False),
        sa.Column("binding_db_id", _PK, nullable=False),
        sa.Column("binding_id", sa.String(36), nullable=False),
        sa.Column("promotion_id", sa.String(36), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("parser_name", sa.String(80), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("parser_implementation_hash", sa.String(64), nullable=False),
        sa.Column("output_schema_version", sa.String(64), nullable=False),
        sa.Column("binding_event_hash", sa.String(64), nullable=False),
        sa.Column("release_manifest_hash", sa.String(64), nullable=False),
        sa.Column("admission_policy_version", sa.String(64), nullable=False),
        sa.Column("admission_policy_hash", sa.String(64), nullable=False),
        sa.Column("requested_limit", sa.Integer(), nullable=False),
        sa.Column("selected_count", sa.Integer(), nullable=False),
        sa.Column("processed_count", sa.Integer(), nullable=False),
        sa.Column("passed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("selection_snapshot", sa.JSON(), nullable=False),
        sa.Column("metrics_snapshot", sa.JSON(), nullable=False),
        sa.Column("technical_metadata", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('RUNNING', 'PASSED', 'PARTIAL', 'FAILED')", name="ck_canonical_parser_admission_runs_status"),
        sa.CheckConstraint("scope IN ('SHADOW_ONLY')", name="ck_canonical_parser_admission_runs_scope"),
        sa.CheckConstraint("channel IN ('CANONICAL_SHADOW')", name="ck_canonical_parser_admission_runs_channel"),
        sa.CheckConstraint("requested_limit >= 1 AND selected_count >= 0 AND processed_count >= 0 AND passed_count >= 0 AND failed_count >= 0 AND skipped_count >= 0", name="ck_canonical_parser_admission_runs_counts_nonnegative"),
        sa.CheckConstraint("selected_count >= processed_count", name="ck_canonical_parser_admission_runs_selected_processed"),
        sa.CheckConstraint("processed_count = passed_count + failed_count + skipped_count", name="ck_canonical_parser_admission_runs_processed_breakdown"),
        sa.CheckConstraint("length(admission_key) = 64", name="ck_canonical_parser_admission_runs_key_length"),
        sa.CheckConstraint("length(parser_implementation_hash) = 64", name="ck_canonical_parser_admission_runs_parser_hash_length"),
        sa.CheckConstraint("length(binding_event_hash) = 64", name="ck_canonical_parser_admission_runs_binding_hash_length"),
        sa.CheckConstraint("length(release_manifest_hash) = 64", name="ck_canonical_parser_admission_runs_release_hash_length"),
        sa.CheckConstraint("length(admission_policy_hash) = 64", name="ck_canonical_parser_admission_runs_policy_hash_length"),
        sa.ForeignKeyConstraint(["binding_db_id"], ["canonical_parser_runtime_bindings.id"], ondelete="RESTRICT", name="fk_canonical_parser_admission_runs_binding"),
        sa.UniqueConstraint("admission_id", name="uq_canonical_parser_admission_runs_admission_id"),
        sa.UniqueConstraint("admission_key", name="uq_canonical_parser_admission_runs_admission_key"),
    )
    op.create_index("ix_canonical_parser_admission_runs_status_started", "canonical_parser_admission_runs", ["status", "started_at"])
    op.create_index("ix_canonical_parser_admission_runs_binding", "canonical_parser_admission_runs", ["binding_db_id"])
    op.create_index("ix_canonical_parser_admission_runs_parser_version", "canonical_parser_admission_runs", ["parser_name", "parser_version"])

    op.create_table(
        "canonical_parser_admission_results",
        sa.Column("id", _PK, primary_key=True),
        sa.Column("result_id", sa.String(36), nullable=False),
        sa.Column("admission_run_db_id", _PK, nullable=False),
        sa.Column("raw_event_id", _PK, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("compatible", sa.Boolean(), nullable=False),
        sa.Column("deterministic", sa.Boolean(), nullable=True),
        sa.Column("first_output_hash", sa.String(64), nullable=True),
        sa.Column("second_output_hash", sa.String(64), nullable=True),
        sa.Column("artifact_count", sa.Integer(), nullable=False),
        sa.Column("artifact_summary", sa.JSON(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('PASS', 'FAIL', 'SKIPPED')", name="ck_canonical_parser_admission_results_status"),
        sa.CheckConstraint("artifact_count >= 0", name="ck_canonical_parser_admission_results_artifact_count"),
        sa.CheckConstraint("first_output_hash IS NULL OR length(first_output_hash) = 64", name="ck_canonical_parser_admission_results_first_hash_length"),
        sa.CheckConstraint("second_output_hash IS NULL OR length(second_output_hash) = 64", name="ck_canonical_parser_admission_results_second_hash_length"),
        sa.ForeignKeyConstraint(["admission_run_db_id"], ["canonical_parser_admission_runs.id"], ondelete="CASCADE", name="fk_canonical_parser_admission_results_run"),
        sa.ForeignKeyConstraint(["raw_event_id"], ["raw_blockchain_events.id"], ondelete="RESTRICT", name="fk_canonical_parser_admission_results_raw_event"),
        sa.UniqueConstraint("result_id", name="uq_canonical_parser_admission_results_result_id"),
        sa.UniqueConstraint("admission_run_db_id", "raw_event_id", name="uq_canonical_parser_admission_results_run_event"),
    )
    op.create_index("ix_canonical_parser_admission_results_run_status", "canonical_parser_admission_results", ["admission_run_db_id", "status"])
    op.create_index("ix_canonical_parser_admission_results_raw_event", "canonical_parser_admission_results", ["raw_event_id"])


def downgrade() -> None:
    op.drop_index("ix_canonical_parser_admission_results_raw_event", table_name="canonical_parser_admission_results")
    op.drop_index("ix_canonical_parser_admission_results_run_status", table_name="canonical_parser_admission_results")
    op.drop_table("canonical_parser_admission_results")
    op.drop_index("ix_canonical_parser_admission_runs_parser_version", table_name="canonical_parser_admission_runs")
    op.drop_index("ix_canonical_parser_admission_runs_binding", table_name="canonical_parser_admission_runs")
    op.drop_index("ix_canonical_parser_admission_runs_status_started", table_name="canonical_parser_admission_runs")
    op.drop_table("canonical_parser_admission_runs")
