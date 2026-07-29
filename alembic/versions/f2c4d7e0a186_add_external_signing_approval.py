"""add external signing approval

Revision ID: f2c4d7e0a186
Revises: e1b3c6d9f075
Create Date: 2026-07-29 12:30:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "f2c4d7e0a186"
down_revision: str | Sequence[str] | None = "e1b3c6d9f075"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_external_signing_approvals",
        sa.Column("id", pk, primary_key=True),
        sa.Column("approval_id", sa.String(36), nullable=False),
        sa.Column("approval_key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(48), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("dry_run_db_id", pk, nullable=False),
        sa.Column("dry_run_id", sa.String(36), nullable=False),
        sa.Column("signer_profile_id", sa.String(36), nullable=False),
        sa.Column("micro_live_permit_id", sa.String(36), nullable=False),
        sa.Column("signed_transaction_hash", sa.String(64), nullable=False),
        sa.Column("message_hash", sa.String(64), nullable=False),
        sa.Column("expected_signature", sa.String(96), nullable=False),
        sa.Column("verified_signers", sa.JSON(), nullable=False),
        sa.Column("signature_count", sa.Integer(), nullable=False),
        sa.Column("signature_verification_status", sa.String(16), nullable=False),
        sa.Column("rpc_simulation_status", sa.String(20), nullable=False),
        sa.Column("units_consumed", sa.Integer(), nullable=True),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("verification_snapshot", sa.JSON(), nullable=False),
        sa.Column("rpc_simulation_snapshot", sa.JSON(), nullable=False),
        sa.Column("approval_envelope", sa.JSON(), nullable=False),
        sa.Column("approval_envelope_hash", sa.String(64), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope = 'M37_EXTERNAL_SIGNING_APPROVAL_ONLY'", name="ck_m37_approval_scope"),
        sa.CheckConstraint("status IN ('READY','REVIEW','BLOCKED','INSUFFICIENT_DATA','REVOKED','EXPIRED')", name="ck_m37_approval_status"),
        sa.CheckConstraint("signature_verification_status IN ('PASSED','FAILED')", name="ck_m37_signature_status"),
        sa.CheckConstraint("rpc_simulation_status IN ('PASSED','FAILED','SKIPPED','UNAVAILABLE')", name="ck_m37_rpc_status"),
        sa.CheckConstraint("signature_count >= 1", name="ck_m37_signature_count"),
        sa.CheckConstraint("length(approval_key) = 64 AND length(signed_transaction_hash) = 64 AND length(message_hash) = 64 AND length(approval_envelope_hash) = 64 AND length(evidence_hash) = 64", name="ck_m37_hashes"),
        sa.ForeignKeyConstraint(["dry_run_db_id"], ["canonical_parser_live_transaction_dry_runs.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("approval_id", name="uq_m37_approval_id"),
        sa.UniqueConstraint("approval_key", name="uq_m37_approval_key"),
    )
    op.create_index("ix_m37_approval_status_expiry", "canonical_parser_external_signing_approvals", ["status", "expires_at"])
    op.create_index("ix_m37_approval_dry_run", "canonical_parser_external_signing_approvals", ["dry_run_db_id"])

    op.create_table(
        "canonical_parser_external_signing_approval_events",
        sa.Column("id", pk, primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("approval_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column("previous_event_hash", sa.String(64), nullable=True),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_m37_event_sequence"),
        sa.CheckConstraint("event_type IN ('APPROVED','REVOKED','EXPIRED')", name="ck_m37_event_type"),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_m37_event_hash"),
        sa.ForeignKeyConstraint(["approval_db_id"], ["canonical_parser_external_signing_approvals.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("event_id", name="uq_m37_event_id"),
        sa.UniqueConstraint("approval_db_id", "sequence", name="uq_m37_event_sequence"),
    )
    op.create_index("ix_m37_event_approval_time", "canonical_parser_external_signing_approval_events", ["approval_db_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_m37_event_approval_time", table_name="canonical_parser_external_signing_approval_events")
    op.drop_table("canonical_parser_external_signing_approval_events")
    op.drop_index("ix_m37_approval_dry_run", table_name="canonical_parser_external_signing_approvals")
    op.drop_index("ix_m37_approval_status_expiry", table_name="canonical_parser_external_signing_approvals")
    op.drop_table("canonical_parser_external_signing_approvals")
