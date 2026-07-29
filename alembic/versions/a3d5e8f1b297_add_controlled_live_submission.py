"""add controlled live submission

Revision ID: a3d5e8f1b297
Revises: f2c4d7e0a186
Create Date: 2026-07-29 12:45:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "a3d5e8f1b297"
down_revision: str | Sequence[str] | None = "f2c4d7e0a186"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_controlled_live_submissions",
        sa.Column("id", pk, primary_key=True),
        sa.Column("submission_id", sa.String(36), nullable=False),
        sa.Column("submission_key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(56), nullable=False),
        sa.Column("approval_db_id", pk, nullable=False),
        sa.Column("approval_id", sa.String(36), nullable=False),
        sa.Column("dry_run_id", sa.String(36), nullable=False),
        sa.Column("micro_live_permit_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("token_mint", sa.String(64), nullable=False),
        sa.Column("reserved_budget_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("signed_transaction_hash", sa.String(64), nullable=False),
        sa.Column("expected_signature", sa.String(96), nullable=False),
        sa.Column("rpc_signature", sa.String(96), nullable=True),
        sa.Column("send_attempted", sa.Boolean(), nullable=False),
        sa.Column("confirmation_status", sa.String(24), nullable=True),
        sa.Column("confirmation_slot", sa.Integer(), nullable=True),
        sa.Column("chain_error", sa.JSON(), nullable=True),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("reservation_snapshot", sa.JSON(), nullable=False),
        sa.Column("submission_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope = 'M38_MANUAL_CONTROLLED_LIVE_SUBMISSION'", name="ck_m38_submission_scope"),
        sa.CheckConstraint("status IN ('RESERVED','SUBMITTED','PROCESSED','CONFIRMED','FINALIZED','FAILED','RECONCILIATION_REQUIRED')", name="ck_m38_submission_status"),
        sa.CheckConstraint("side IN ('BUY','SELL')", name="ck_m38_submission_side"),
        sa.CheckConstraint("reserved_budget_sol >= 0", name="ck_m38_submission_budget"),
        sa.CheckConstraint("length(submission_key) = 64 AND length(signed_transaction_hash) = 64 AND length(evidence_hash) = 64", name="ck_m38_submission_hashes"),
        sa.ForeignKeyConstraint(["approval_db_id"], ["canonical_parser_external_signing_approvals.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("submission_id", name="uq_m38_submission_id"),
        sa.UniqueConstraint("submission_key", name="uq_m38_submission_key"),
        sa.UniqueConstraint("approval_db_id", name="uq_m38_submission_approval"),
        sa.UniqueConstraint("rpc_signature", name="uq_m38_rpc_signature"),
    )
    op.create_index("ix_m38_submission_permit_status", "canonical_parser_controlled_live_submissions", ["micro_live_permit_id", "status"])
    op.create_index("ix_m38_submission_status_created", "canonical_parser_controlled_live_submissions", ["status", "created_at"])

    op.create_table(
        "canonical_parser_controlled_live_submission_events",
        sa.Column("id", pk, primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("submission_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column("previous_event_hash", sa.String(64), nullable=True),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_m38_event_sequence"),
        sa.CheckConstraint("event_type IN ('RESERVED','SUBMITTED','RECONCILED','CONFIRMED','FINALIZED','FAILED','UNCERTAIN')", name="ck_m38_event_type"),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_m38_event_hash"),
        sa.ForeignKeyConstraint(["submission_db_id"], ["canonical_parser_controlled_live_submissions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("event_id", name="uq_m38_event_id"),
        sa.UniqueConstraint("submission_db_id", "sequence", name="uq_m38_event_sequence"),
    )
    op.create_index("ix_m38_event_submission_time", "canonical_parser_controlled_live_submission_events", ["submission_db_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_m38_event_submission_time", table_name="canonical_parser_controlled_live_submission_events")
    op.drop_table("canonical_parser_controlled_live_submission_events")
    op.drop_index("ix_m38_submission_status_created", table_name="canonical_parser_controlled_live_submissions")
    op.drop_index("ix_m38_submission_permit_status", table_name="canonical_parser_controlled_live_submissions")
    op.drop_table("canonical_parser_controlled_live_submissions")
