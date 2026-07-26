"""add certified shadow consumer dry-run

Revision ID: e1a4c7b9f205
Revises: d8c2f5a7e104
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e1a4c7b9f205"
down_revision: Union[str, Sequence[str], None] = "d8c2f5a7e104"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "canonical_parser_shadow_consumer_runs",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("run_key", sa.String(64), nullable=False),
        sa.Column("lease_db_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("lease_id", sa.String(36), nullable=False),
        sa.Column("certification_id", sa.String(36), nullable=False),
        sa.Column("binding_id", sa.String(36), nullable=False),
        sa.Column("promotion_id", sa.String(36), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("consumer", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("parser_name", sa.String(80), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("parser_implementation_hash", sa.String(64), nullable=False),
        sa.Column("output_schema_version", sa.String(64), nullable=False),
        sa.Column("release_manifest_hash", sa.String(64), nullable=False),
        sa.Column("lease_event_hash", sa.String(64), nullable=False),
        sa.Column("certification_event_hash", sa.String(64), nullable=False),
        sa.Column("consumer_policy_version", sa.String(64), nullable=False),
        sa.Column("consumer_policy_hash", sa.String(64), nullable=False),
        sa.Column("requested_limit", sa.Integer(), nullable=False),
        sa.Column("selected_count", sa.Integer(), nullable=False),
        sa.Column("processed_count", sa.Integer(), nullable=False),
        sa.Column("passed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("artifact_count", sa.Integer(), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("selection_snapshot", sa.JSON(), nullable=False),
        sa.Column("metrics_snapshot", sa.JSON(), nullable=False),
        sa.Column("technical_metadata", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('RUNNING', 'PASSED', 'PARTIAL', 'FAILED')", name="ck_canonical_parser_shadow_consumer_runs_status"),
        sa.CheckConstraint("scope IN ('SHADOW_ONLY')", name="ck_canonical_parser_shadow_consumer_runs_scope"),
        sa.CheckConstraint("channel IN ('CANONICAL_SHADOW')", name="ck_canonical_parser_shadow_consumer_runs_channel"),
        sa.CheckConstraint("consumer IN ('CERTIFIED_SHADOW_RUNTIME')", name="ck_canonical_parser_shadow_consumer_runs_consumer"),
        sa.CheckConstraint("requested_limit >= 1 AND selected_count >= 0 AND processed_count >= 0 AND passed_count >= 0 AND failed_count >= 0 AND skipped_count >= 0 AND artifact_count >= 0", name="ck_canonical_parser_shadow_consumer_runs_counts_nonnegative"),
        sa.CheckConstraint("selected_count >= processed_count", name="ck_canonical_parser_shadow_consumer_runs_selected_processed"),
        sa.CheckConstraint("processed_count = passed_count + failed_count + skipped_count", name="ck_canonical_parser_shadow_consumer_runs_processed_breakdown"),
        sa.CheckConstraint("length(run_key) = 64", name="ck_canonical_parser_shadow_consumer_runs_key_length"),
        sa.CheckConstraint("length(parser_implementation_hash) = 64", name="ck_canonical_parser_shadow_consumer_runs_parser_hash_length"),
        sa.CheckConstraint("length(lease_event_hash) = 64", name="ck_canonical_parser_shadow_consumer_runs_lease_hash_length"),
        sa.CheckConstraint("length(certification_event_hash) = 64", name="ck_canonical_parser_shadow_consumer_runs_cert_hash_length"),
        sa.CheckConstraint("length(release_manifest_hash) = 64", name="ck_canonical_parser_shadow_consumer_runs_release_hash_length"),
        sa.CheckConstraint("length(consumer_policy_hash) = 64", name="ck_canonical_parser_shadow_consumer_runs_policy_hash_length"),
        sa.ForeignKeyConstraint(["lease_db_id"], ["canonical_parser_shadow_runtime_leases.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("run_id", name="uq_canonical_parser_shadow_consumer_runs_id"),
        sa.UniqueConstraint("run_key", name="uq_canonical_parser_shadow_consumer_runs_key"),
    )
    op.create_index("ix_canonical_parser_shadow_consumer_runs_lease_started", "canonical_parser_shadow_consumer_runs", ["lease_db_id", "started_at"])
    op.create_index("ix_canonical_parser_shadow_consumer_runs_status_completed", "canonical_parser_shadow_consumer_runs", ["status", "completed_at"])
    op.create_index("ix_canonical_parser_shadow_consumer_runs_parser_version", "canonical_parser_shadow_consumer_runs", ["parser_name", "parser_version"])

    op.create_table(
        "canonical_parser_shadow_consumer_results",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column("result_id", sa.String(36), nullable=False),
        sa.Column("consumer_run_db_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("raw_event_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("raw_payload_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("compatible", sa.Boolean(), nullable=False),
        sa.Column("deterministic", sa.Boolean(), nullable=True),
        sa.Column("output_hash", sa.String(64), nullable=True),
        sa.Column("verification_output_hash", sa.String(64), nullable=True),
        sa.Column("artifact_count", sa.Integer(), nullable=False),
        sa.Column("shadow_artifacts", sa.JSON(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('PASS', 'FAIL', 'SKIPPED')", name="ck_canonical_parser_shadow_consumer_results_status"),
        sa.CheckConstraint("artifact_count >= 0", name="ck_canonical_parser_shadow_consumer_results_artifact_count"),
        sa.CheckConstraint("length(raw_payload_hash) = 64", name="ck_canonical_parser_shadow_consumer_results_raw_hash_length"),
        sa.CheckConstraint("output_hash IS NULL OR length(output_hash) = 64", name="ck_canonical_parser_shadow_consumer_results_output_hash_length"),
        sa.CheckConstraint("verification_output_hash IS NULL OR length(verification_output_hash) = 64", name="ck_canonical_parser_shadow_consumer_results_verify_hash_length"),
        sa.ForeignKeyConstraint(["consumer_run_db_id"], ["canonical_parser_shadow_consumer_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["raw_event_id"], ["raw_blockchain_events.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("result_id", name="uq_canonical_parser_shadow_consumer_results_id"),
        sa.UniqueConstraint("consumer_run_db_id", "raw_event_id", name="uq_canonical_parser_shadow_consumer_results_run_event"),
    )
    op.create_index("ix_canonical_parser_shadow_consumer_results_run_status", "canonical_parser_shadow_consumer_results", ["consumer_run_db_id", "status"])
    op.create_index("ix_canonical_parser_shadow_consumer_results_raw_event", "canonical_parser_shadow_consumer_results", ["raw_event_id"])


def downgrade() -> None:
    op.drop_index("ix_canonical_parser_shadow_consumer_results_raw_event", table_name="canonical_parser_shadow_consumer_results")
    op.drop_index("ix_canonical_parser_shadow_consumer_results_run_status", table_name="canonical_parser_shadow_consumer_results")
    op.drop_table("canonical_parser_shadow_consumer_results")
    op.drop_index("ix_canonical_parser_shadow_consumer_runs_parser_version", table_name="canonical_parser_shadow_consumer_runs")
    op.drop_index("ix_canonical_parser_shadow_consumer_runs_status_completed", table_name="canonical_parser_shadow_consumer_runs")
    op.drop_index("ix_canonical_parser_shadow_consumer_runs_lease_started", table_name="canonical_parser_shadow_consumer_runs")
    op.drop_table("canonical_parser_shadow_consumer_runs")
