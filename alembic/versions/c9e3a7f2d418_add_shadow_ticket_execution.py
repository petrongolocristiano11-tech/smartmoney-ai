"""add ticket-bound shadow execution and budget settlement

Revision ID: c9e3a7f2d418
Revises: b7d1f4a6c825
Create Date: 2026-07-26 16:00:00.000000
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c9e3a7f2d418"
down_revision: str | Sequence[str] | None = "b7d1f4a6c825"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "canonical_parser_shadow_ticket_execution_runs",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
        ),
        sa.Column("run_id", sa.String(36), nullable=False),
        sa.Column("run_key", sa.String(64), nullable=False),
        sa.Column(
            "ticket_db_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("ticket_id", sa.String(36), nullable=False),
        sa.Column("ticket_key", sa.String(64), nullable=False),
        sa.Column(
            "permit_db_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("permit_id", sa.String(36), nullable=False),
        sa.Column("assessment_id", sa.String(36), nullable=False),
        sa.Column("lease_id", sa.String(36), nullable=False),
        sa.Column("certification_id", sa.String(36), nullable=False),
        sa.Column("binding_id", sa.String(36), nullable=False),
        sa.Column("promotion_id", sa.String(36), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("consumer", sa.String(64), nullable=False),
        sa.Column("executor", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("parser_name", sa.String(80), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("parser_implementation_hash", sa.String(64), nullable=False),
        sa.Column("output_schema_version", sa.String(64), nullable=False),
        sa.Column("release_manifest_hash", sa.String(64), nullable=False),
        sa.Column("readiness_evidence_hash", sa.String(64), nullable=False),
        sa.Column("permit_policy_hash", sa.String(64), nullable=False),
        sa.Column("permit_event_hash", sa.String(64), nullable=False),
        sa.Column("ticket_policy_hash", sa.String(64), nullable=False),
        sa.Column("ticket_event_hash", sa.String(64), nullable=False),
        sa.Column("execution_policy_version", sa.String(64), nullable=False),
        sa.Column("execution_policy_hash", sa.String(64), nullable=False),
        sa.Column("execution_policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("requested_limit", sa.Integer(), nullable=False),
        sa.Column("reserved_run_count", sa.Integer(), nullable=False),
        sa.Column("reserved_event_count", sa.Integer(), nullable=False),
        sa.Column("selected_count", sa.Integer(), nullable=False),
        sa.Column("processed_count", sa.Integer(), nullable=False),
        sa.Column("passed_count", sa.Integer(), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("artifact_count", sa.Integer(), nullable=False),
        sa.Column("consumed_run_count", sa.Integer(), nullable=False),
        sa.Column("consumed_event_count", sa.Integer(), nullable=False),
        sa.Column("released_event_count", sa.Integer(), nullable=False),
        sa.Column("budget_settled", sa.Boolean(), nullable=False),
        sa.Column("settlement_hash", sa.String(64), nullable=True),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("selection_snapshot", sa.JSON(), nullable=False),
        sa.Column("metrics_snapshot", sa.JSON(), nullable=False),
        sa.Column("technical_metadata", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'PASSED', 'PARTIAL', 'FAILED')",
            name="ck_shadow_ticket_execution_runs_status",
        ),
        sa.CheckConstraint(
            "scope IN ('SHADOW_ONLY')",
            name="ck_shadow_ticket_execution_runs_scope",
        ),
        sa.CheckConstraint(
            "channel IN ('CANONICAL_SHADOW')",
            name="ck_shadow_ticket_execution_runs_channel",
        ),
        sa.CheckConstraint(
            "consumer IN ('CERTIFIED_SHADOW_AUTOMATION')",
            name="ck_shadow_ticket_execution_runs_consumer",
        ),
        sa.CheckConstraint(
            "executor IN ('CERTIFIED_SHADOW_TICKET_EXECUTION')",
            name="ck_shadow_ticket_execution_runs_executor",
        ),
        sa.CheckConstraint(
            "requested_limit >= 1 AND reserved_run_count = 1 "
            "AND reserved_event_count >= 1 AND selected_count >= 0 "
            "AND processed_count >= 0 AND passed_count >= 0 "
            "AND failed_count >= 0 AND skipped_count >= 0 "
            "AND artifact_count >= 0 AND consumed_run_count >= 0 "
            "AND consumed_event_count >= 0 AND released_event_count >= 0",
            name="ck_shadow_ticket_execution_runs_counts_nonnegative",
        ),
        sa.CheckConstraint(
            "selected_count >= processed_count",
            name="ck_shadow_ticket_execution_runs_selected_processed",
        ),
        sa.CheckConstraint(
            "processed_count = passed_count + failed_count + skipped_count",
            name="ck_shadow_ticket_execution_runs_processed_breakdown",
        ),
        sa.CheckConstraint(
            "consumed_run_count <= reserved_run_count",
            name="ck_shadow_ticket_execution_runs_run_budget_bound",
        ),
        sa.CheckConstraint(
            "NOT budget_settled OR consumed_event_count + released_event_count = reserved_event_count",
            name="ck_shadow_ticket_execution_runs_event_settlement",
        ),
        sa.CheckConstraint(
            "consumed_event_count = processed_count",
            name="ck_shadow_ticket_execution_runs_consumed_processed",
        ),
        sa.CheckConstraint(
            "length(run_key) = 64",
            name="ck_shadow_ticket_execution_runs_key_len",
        ),
        sa.CheckConstraint(
            "length(ticket_key) = 64",
            name="ck_shadow_ticket_execution_runs_ticket_key_len",
        ),
        sa.CheckConstraint(
            "length(parser_implementation_hash) = 64",
            name="ck_shadow_ticket_execution_runs_parser_hash_len",
        ),
        sa.CheckConstraint(
            "length(release_manifest_hash) = 64",
            name="ck_shadow_ticket_execution_runs_release_hash_len",
        ),
        sa.CheckConstraint(
            "length(readiness_evidence_hash) = 64",
            name="ck_shadow_ticket_execution_runs_readiness_hash_len",
        ),
        sa.CheckConstraint(
            "length(permit_policy_hash) = 64",
            name="ck_shadow_ticket_execution_runs_permit_policy_hash_len",
        ),
        sa.CheckConstraint(
            "length(permit_event_hash) = 64",
            name="ck_shadow_ticket_execution_runs_permit_event_hash_len",
        ),
        sa.CheckConstraint(
            "length(ticket_policy_hash) = 64",
            name="ck_shadow_ticket_execution_runs_ticket_policy_hash_len",
        ),
        sa.CheckConstraint(
            "length(ticket_event_hash) = 64",
            name="ck_shadow_ticket_execution_runs_ticket_event_hash_len",
        ),
        sa.CheckConstraint(
            "length(execution_policy_hash) = 64",
            name="ck_shadow_ticket_execution_runs_policy_hash_len",
        ),
        sa.CheckConstraint(
            "settlement_hash IS NULL OR length(settlement_hash) = 64",
            name="ck_shadow_ticket_execution_runs_settlement_hash_len",
        ),
        sa.ForeignKeyConstraint(
            ["ticket_db_id"],
            ["canonical_parser_shadow_execution_tickets.id"],
            name="fk_shadow_ticket_execution_runs_ticket",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["permit_db_id"],
            ["canonical_parser_shadow_automation_permits.id"],
            name="fk_shadow_ticket_execution_runs_permit",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("run_id", name="uq_shadow_ticket_execution_runs_id"),
        sa.UniqueConstraint("run_key", name="uq_shadow_ticket_execution_runs_key"),
        sa.UniqueConstraint(
            "ticket_db_id", name="uq_shadow_ticket_execution_runs_ticket"
        ),
    )
    op.create_index(
        "ix_shadow_ticket_execution_runs_permit_started",
        "canonical_parser_shadow_ticket_execution_runs",
        ["permit_db_id", "started_at"],
    )
    op.create_index(
        "ix_shadow_ticket_execution_runs_status_completed",
        "canonical_parser_shadow_ticket_execution_runs",
        ["status", "completed_at"],
    )
    op.create_index(
        "ix_shadow_ticket_execution_runs_parser",
        "canonical_parser_shadow_ticket_execution_runs",
        ["parser_name", "parser_version"],
    )

    op.create_table(
        "canonical_parser_shadow_ticket_execution_results",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
        ),
        sa.Column("result_id", sa.String(36), nullable=False),
        sa.Column(
            "execution_run_db_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column(
            "raw_event_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('PASS', 'FAIL', 'SKIPPED')",
            name="ck_shadow_ticket_execution_results_status",
        ),
        sa.CheckConstraint(
            "artifact_count >= 0",
            name="ck_shadow_ticket_execution_results_artifact_count",
        ),
        sa.CheckConstraint(
            "length(raw_payload_hash) = 64",
            name="ck_shadow_ticket_execution_results_raw_hash_len",
        ),
        sa.CheckConstraint(
            "output_hash IS NULL OR length(output_hash) = 64",
            name="ck_shadow_ticket_execution_results_output_hash_len",
        ),
        sa.CheckConstraint(
            "verification_output_hash IS NULL OR length(verification_output_hash) = 64",
            name="ck_shadow_ticket_execution_results_verify_hash_len",
        ),
        sa.ForeignKeyConstraint(
            ["execution_run_db_id"],
            ["canonical_parser_shadow_ticket_execution_runs.id"],
            name="fk_shadow_ticket_execution_results_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["raw_event_id"],
            ["raw_blockchain_events.id"],
            name="fk_shadow_ticket_execution_results_raw_event",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "result_id", name="uq_shadow_ticket_execution_results_id"
        ),
        sa.UniqueConstraint(
            "execution_run_db_id",
            "raw_event_id",
            name="uq_shadow_ticket_execution_results_run_event",
        ),
    )
    op.create_index(
        "ix_shadow_ticket_execution_results_run_status",
        "canonical_parser_shadow_ticket_execution_results",
        ["execution_run_db_id", "status"],
    )
    op.create_index(
        "ix_shadow_ticket_execution_results_raw_event",
        "canonical_parser_shadow_ticket_execution_results",
        ["raw_event_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_shadow_ticket_execution_results_raw_event",
        table_name="canonical_parser_shadow_ticket_execution_results",
    )
    op.drop_index(
        "ix_shadow_ticket_execution_results_run_status",
        table_name="canonical_parser_shadow_ticket_execution_results",
    )
    op.drop_table("canonical_parser_shadow_ticket_execution_results")
    op.drop_index(
        "ix_shadow_ticket_execution_runs_parser",
        table_name="canonical_parser_shadow_ticket_execution_runs",
    )
    op.drop_index(
        "ix_shadow_ticket_execution_runs_status_completed",
        table_name="canonical_parser_shadow_ticket_execution_runs",
    )
    op.drop_index(
        "ix_shadow_ticket_execution_runs_permit_started",
        table_name="canonical_parser_shadow_ticket_execution_runs",
    )
    op.drop_table("canonical_parser_shadow_ticket_execution_runs")
