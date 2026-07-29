"""add preproduction certification

Revision ID: a9d1e4f7b853
Revises: f8c0d3e6a742
Create Date: 2026-07-29 16:20:00.000000
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "a9d1e4f7b853"
down_revision: str | Sequence[str] | None = "f8c0d3e6a742"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_preproduction_certifications",
        sa.Column("id", pk, primary_key=True),
        sa.Column("certification_id", sa.String(36), nullable=False),
        sa.Column("certification_key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(48), nullable=False),
        sa.Column("environment", sa.String(24), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("observability_snapshot_db_id", pk, nullable=False),
        sa.Column("observability_snapshot_id", sa.String(36), nullable=False),
        sa.Column("git_commit_sha", sa.String(40), nullable=False),
        sa.Column("alembic_head", sa.String(12), nullable=False),
        sa.Column("fastapi_version", sa.String(32), nullable=False),
        sa.Column("clean_worktree_attested", sa.Boolean(), nullable=False),
        sa.Column("full_test_count", sa.Integer(), nullable=False),
        sa.Column("full_test_failures", sa.Integer(), nullable=False),
        sa.Column("test_evidence_hash", sa.String(64), nullable=False),
        sa.Column("check_summary", sa.JSON(), nullable=False),
        sa.Column("evidence_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("certified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_event_sequence", sa.Integer(), nullable=False),
        sa.Column("latest_event_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope = 'M44_PREPRODUCTION_CERTIFICATION'", name="ck_m44_certification_scope"),
        sa.CheckConstraint("environment = 'PREPRODUCTION'", name="ck_m44_certification_environment"),
        sa.CheckConstraint("status IN ('ACTIVE','REVOKED','EXPIRED')", name="ck_m44_certification_status"),
        sa.CheckConstraint("full_test_count >= 0 AND full_test_failures >= 0", name="ck_m44_certification_test_counts"),
        sa.CheckConstraint("latest_event_sequence >= 1", name="ck_m44_certification_event_sequence"),
        sa.CheckConstraint("length(certification_key) = 64 AND length(test_evidence_hash) = 64 AND length(evidence_hash) = 64 AND length(latest_event_hash) = 64", name="ck_m44_certification_hashes"),
        sa.ForeignKeyConstraint(["observability_snapshot_db_id"], ["canonical_parser_live_observability_snapshots.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("certification_id", name="uq_m44_certification_id"),
        sa.UniqueConstraint("certification_key", name="uq_m44_certification_key"),
    )
    op.create_index("ix_m44_certification_status_expiry", "canonical_parser_preproduction_certifications", ["status", "expires_at"])
    op.create_index("ix_m44_certification_commit", "canonical_parser_preproduction_certifications", ["git_commit_sha"])

    op.create_table(
        "canonical_parser_preproduction_certification_checks",
        sa.Column("id", pk, primary_key=True),
        sa.Column("check_id", sa.String(36), nullable=False),
        sa.Column("certification_db_id", pk, nullable=False),
        sa.Column("check_name", sa.String(80), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("check_detail", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('PASS','FAIL')", name="ck_m44_certification_check_status"),
        sa.CheckConstraint("length(evidence_hash) = 64", name="ck_m44_certification_check_hash"),
        sa.ForeignKeyConstraint(["certification_db_id"], ["canonical_parser_preproduction_certifications.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("check_id", name="uq_m44_certification_check_id"),
        sa.UniqueConstraint("certification_db_id", "check_name", name="uq_m44_certification_check_name"),
    )
    op.create_index("ix_m44_certification_check_status", "canonical_parser_preproduction_certification_checks", ["certification_db_id", "status"])

    op.create_table(
        "canonical_parser_preproduction_certification_events",
        sa.Column("id", pk, primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("certification_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column("previous_event_hash", sa.String(64), nullable=True),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_m44_certification_event_sequence"),
        sa.CheckConstraint("event_type IN ('CERTIFIED','REVOKED','EXPIRED')", name="ck_m44_certification_event_type"),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_m44_certification_event_hash"),
        sa.ForeignKeyConstraint(["certification_db_id"], ["canonical_parser_preproduction_certifications.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("event_id", name="uq_m44_certification_event_id"),
        sa.UniqueConstraint("certification_db_id", "sequence", name="uq_m44_certification_event_sequence"),
    )
    op.create_index("ix_m44_certification_event_time", "canonical_parser_preproduction_certification_events", ["certification_db_id", "occurred_at"])

    op.create_table(
        "canonical_parser_preproduction_release_approvals",
        sa.Column("id", pk, primary_key=True),
        sa.Column("release_id", sa.String(36), nullable=False),
        sa.Column("release_key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(64), nullable=False),
        sa.Column("certification_db_id", pk, nullable=False),
        sa.Column("certification_id", sa.String(36), nullable=False),
        sa.Column("wallet_address", sa.String(64), nullable=False),
        sa.Column("network", sa.String(32), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("token_mint", sa.String(64), nullable=False),
        sa.Column("max_budget_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("approval_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_submission_id", sa.String(36), nullable=True),
        sa.Column("latest_event_sequence", sa.Integer(), nullable=False),
        sa.Column("latest_event_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope = 'M44_SINGLE_USE_PREPRODUCTION_RELEASE_APPROVAL'", name="ck_m44_release_scope"),
        sa.CheckConstraint("network = 'mainnet-beta'", name="ck_m44_release_network"),
        sa.CheckConstraint("side IN ('BUY','SELL')", name="ck_m44_release_side"),
        sa.CheckConstraint("status IN ('ACTIVE','REVOKED','EXPIRED','CONSUMED')", name="ck_m44_release_status"),
        sa.CheckConstraint("max_budget_sol >= 0", name="ck_m44_release_budget"),
        sa.CheckConstraint("latest_event_sequence >= 1", name="ck_m44_release_event_sequence"),
        sa.CheckConstraint("length(release_key) = 64 AND length(evidence_hash) = 64 AND length(latest_event_hash) = 64", name="ck_m44_release_hashes"),
        sa.ForeignKeyConstraint(["certification_db_id"], ["canonical_parser_preproduction_certifications.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("release_id", name="uq_m44_release_id"),
        sa.UniqueConstraint("release_key", name="uq_m44_release_key"),
    )
    op.create_index("ix_m44_release_wallet_status", "canonical_parser_preproduction_release_approvals", ["wallet_address", "status"])
    op.create_index("ix_m44_release_status_expiry", "canonical_parser_preproduction_release_approvals", ["status", "expires_at"])

    op.create_table(
        "canonical_parser_preproduction_release_approval_events",
        sa.Column("id", pk, primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("release_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column("previous_event_hash", sa.String(64), nullable=True),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_m44_release_event_sequence"),
        sa.CheckConstraint("event_type IN ('ISSUED','REVOKED','EXPIRED','CONSUMED')", name="ck_m44_release_event_type"),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_m44_release_event_hash"),
        sa.ForeignKeyConstraint(["release_db_id"], ["canonical_parser_preproduction_release_approvals.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("event_id", name="uq_m44_release_event_id"),
        sa.UniqueConstraint("release_db_id", "sequence", name="uq_m44_release_event_sequence"),
    )
    op.create_index("ix_m44_release_event_time", "canonical_parser_preproduction_release_approval_events", ["release_db_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_m44_release_event_time", table_name="canonical_parser_preproduction_release_approval_events")
    op.drop_table("canonical_parser_preproduction_release_approval_events")
    op.drop_index("ix_m44_release_status_expiry", table_name="canonical_parser_preproduction_release_approvals")
    op.drop_index("ix_m44_release_wallet_status", table_name="canonical_parser_preproduction_release_approvals")
    op.drop_table("canonical_parser_preproduction_release_approvals")
    op.drop_index("ix_m44_certification_event_time", table_name="canonical_parser_preproduction_certification_events")
    op.drop_table("canonical_parser_preproduction_certification_events")
    op.drop_index("ix_m44_certification_check_status", table_name="canonical_parser_preproduction_certification_checks")
    op.drop_table("canonical_parser_preproduction_certification_checks")
    op.drop_index("ix_m44_certification_commit", table_name="canonical_parser_preproduction_certifications")
    op.drop_index("ix_m44_certification_status_expiry", table_name="canonical_parser_preproduction_certifications")
    op.drop_table("canonical_parser_preproduction_certifications")
