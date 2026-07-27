"""add paper execution permit governance

Revision ID: e3b8d5f1a942
Revises: d2a7f4c9e831
Create Date: 2026-07-27 18:55:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "e3b8d5f1a942"
down_revision: str | Sequence[str] | None = "d2a7f4c9e831"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_paper_execution_permits",
        sa.Column("id", pk, primary_key=True),
        sa.Column("permit_id", sa.String(36), nullable=False),
        sa.Column("permit_key", sa.String(64), nullable=False),
        sa.Column("readiness_assessment_db_id", pk, nullable=False),
        sa.Column("readiness_assessment_id", sa.String(36), nullable=False),
        sa.Column("readiness_evidence_hash", sa.String(64), nullable=False),
        sa.Column("binding_db_id", pk, nullable=False),
        sa.Column("binding_id", sa.String(36), nullable=False),
        sa.Column("binding_event_hash", sa.String(64), nullable=False),
        sa.Column("certification_id", sa.String(36), nullable=False),
        sa.Column("paper_account_id", sa.Integer(), nullable=False),
        sa.Column("paper_account_name", sa.String(120), nullable=False),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("requested_validity_minutes", sa.Integer(), nullable=False),
        sa.Column("total_budget_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("max_order_budget_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("max_order_count", sa.Integer(), nullable=False),
        sa.Column("consumed_budget_sol", sa.Numeric(20, 9), nullable=False, server_default="0"),
        sa.Column("consumed_order_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
        sa.Column("latest_event_sequence", sa.Integer(), nullable=False),
        sa.Column("latest_event_hash", sa.String(64), nullable=False),
        sa.Column("technical_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE', 'REVOKED')", name="ck_parser_paper_execution_permits_status"),
        sa.CheckConstraint(
            "scope = 'PAPER_EXECUTION_METADATA_ONLY'",
            name="ck_parser_paper_execution_permits_scope",
        ),
        sa.CheckConstraint("requested_validity_minutes >= 1", name="ck_parser_paper_execution_permits_validity"),
        sa.CheckConstraint(
            "total_budget_sol > 0 AND max_order_budget_sol > 0 AND max_order_budget_sol <= total_budget_sol",
            name="ck_parser_paper_execution_permits_budget",
        ),
        sa.CheckConstraint("max_order_count >= 1", name="ck_parser_paper_execution_permits_order_count"),
        sa.CheckConstraint(
            "consumed_budget_sol >= 0 AND consumed_budget_sol <= total_budget_sol",
            name="ck_parser_paper_execution_permits_consumed_budget",
        ),
        sa.CheckConstraint(
            "consumed_order_count >= 0 AND consumed_order_count <= max_order_count",
            name="ck_parser_paper_execution_permits_consumed_orders",
        ),
        sa.CheckConstraint("latest_event_sequence >= 1", name="ck_parser_paper_execution_permits_event_sequence"),
        sa.CheckConstraint("length(permit_key) = 64", name="ck_parser_paper_execution_permits_key"),
        sa.CheckConstraint("length(readiness_evidence_hash) = 64", name="ck_parser_paper_execution_permits_evidence_hash"),
        sa.CheckConstraint("length(binding_event_hash) = 64", name="ck_parser_paper_execution_permits_binding_hash"),
        sa.CheckConstraint("length(policy_hash) = 64", name="ck_parser_paper_execution_permits_policy_hash"),
        sa.CheckConstraint("length(latest_event_hash) = 64", name="ck_parser_paper_execution_permits_event_hash"),
        sa.ForeignKeyConstraint(
            ["readiness_assessment_db_id"],
            ["canonical_parser_paper_canary_readiness_assessments.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["binding_db_id"], ["canonical_parser_paper_runtime_bindings.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(["paper_account_id"], ["paper_accounts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("permit_id", name="uq_parser_paper_execution_permits_id"),
        sa.UniqueConstraint("permit_key", name="uq_parser_paper_execution_permits_key"),
    )
    op.create_index(
        "ix_parser_paper_execution_permits_status_expires",
        "canonical_parser_paper_execution_permits",
        ["status", "expires_at"],
    )
    op.create_index(
        "ix_parser_paper_execution_permits_account_issued",
        "canonical_parser_paper_execution_permits",
        ["paper_account_id", "issued_at"],
    )

    op.create_table(
        "canonical_parser_paper_execution_permit_events",
        sa.Column("id", pk, primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("permit_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("previous_status", sa.String(16), nullable=True),
        sa.Column("new_status", sa.String(16), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column("previous_event_hash", sa.String(64), nullable=True),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_parser_paper_execution_permit_events_sequence"),
        sa.CheckConstraint(
            "event_type IN ('ISSUED', 'REVOKED')",
            name="ck_parser_paper_execution_permit_events_type",
        ),
        sa.CheckConstraint(
            "new_status IN ('ACTIVE', 'REVOKED')",
            name="ck_parser_paper_execution_permit_events_status",
        ),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_parser_paper_execution_permit_events_hash"),
        sa.CheckConstraint(
            "previous_event_hash IS NULL OR length(previous_event_hash) = 64",
            name="ck_parser_paper_execution_permit_events_previous_hash",
        ),
        sa.ForeignKeyConstraint(
            ["permit_db_id"], ["canonical_parser_paper_execution_permits.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("event_id", name="uq_parser_paper_execution_permit_events_id"),
        sa.UniqueConstraint(
            "permit_db_id", "sequence", name="uq_parser_paper_execution_permit_events_sequence"
        ),
    )
    op.create_index(
        "ix_parser_paper_execution_permit_events_permit_occurred",
        "canonical_parser_paper_execution_permit_events",
        ["permit_db_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_parser_paper_execution_permit_events_permit_occurred",
        table_name="canonical_parser_paper_execution_permit_events",
    )
    op.drop_table("canonical_parser_paper_execution_permit_events")
    op.drop_index(
        "ix_parser_paper_execution_permits_account_issued",
        table_name="canonical_parser_paper_execution_permits",
    )
    op.drop_index(
        "ix_parser_paper_execution_permits_status_expires",
        table_name="canonical_parser_paper_execution_permits",
    )
    op.drop_table("canonical_parser_paper_execution_permits")
