"""add paper runtime binding

Revision ID: b2d8f4a6c913
Revises: a9e6c2b4d731
Create Date: 2026-07-27 16:00:00.000000
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "b2d8f4a6c913"
down_revision: str | Sequence[str] | None = "a9e6c2b4d731"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_paper_runtime_bindings",
        sa.Column("id", pk, primary_key=True),
        sa.Column("binding_id", sa.String(36), nullable=False),
        sa.Column("binding_key", sa.String(64), nullable=False),
        sa.Column("certification_db_id", pk, nullable=False),
        sa.Column("certification_id", sa.String(36), nullable=False),
        sa.Column("certification_event_hash", sa.String(64), nullable=False),
        sa.Column("paper_account_id", sa.Integer(), nullable=False),
        sa.Column("paper_account_name", sa.String(80), nullable=False),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("account_snapshot_hash", sa.String(64), nullable=False),
        sa.Column("account_snapshot", sa.JSON(), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unbind_reason", sa.Text(), nullable=True),
        sa.Column("latest_event_sequence", sa.Integer(), nullable=False),
        sa.Column("latest_event_hash", sa.String(64), nullable=False),
        sa.Column("technical_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE', 'UNBOUND')", name="ck_parser_paper_runtime_bindings_status"),
        sa.CheckConstraint("mode = 'READ_ONLY_CANARY'", name="ck_parser_paper_runtime_bindings_mode"),
        sa.CheckConstraint("length(binding_key) = 64", name="ck_parser_paper_runtime_bindings_key"),
        sa.CheckConstraint("length(certification_event_hash) = 64", name="ck_parser_paper_runtime_bindings_cert_hash"),
        sa.CheckConstraint("length(account_snapshot_hash) = 64", name="ck_parser_paper_runtime_bindings_account_hash"),
        sa.CheckConstraint("length(policy_hash) = 64", name="ck_parser_paper_runtime_bindings_policy_hash"),
        sa.CheckConstraint("latest_event_sequence >= 1", name="ck_parser_paper_runtime_bindings_event_sequence"),
        sa.CheckConstraint("length(latest_event_hash) = 64", name="ck_parser_paper_runtime_bindings_event_hash"),
        sa.ForeignKeyConstraint(["certification_db_id"], ["canonical_parser_paper_admission_certifications.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["paper_account_id"], ["paper_accounts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("binding_id", name="uq_parser_paper_runtime_bindings_id"),
        sa.UniqueConstraint("binding_key", name="uq_parser_paper_runtime_bindings_key"),
    )
    op.create_index("ix_parser_paper_runtime_bindings_status_expiry", "canonical_parser_paper_runtime_bindings", ["status", "expires_at"])
    op.create_index("ix_parser_paper_runtime_bindings_account", "canonical_parser_paper_runtime_bindings", ["paper_account_id", "bound_at"])
    op.create_table(
        "canonical_parser_paper_runtime_binding_events",
        sa.Column("id", pk, primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("binding_db_id", pk, nullable=False),
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
        sa.CheckConstraint("sequence >= 1", name="ck_parser_paper_runtime_binding_events_sequence"),
        sa.CheckConstraint("event_type IN ('BOUND', 'UNBOUND')", name="ck_parser_paper_runtime_binding_events_type"),
        sa.CheckConstraint("new_status IN ('ACTIVE', 'UNBOUND')", name="ck_parser_paper_runtime_binding_events_status"),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_parser_paper_runtime_binding_events_hash"),
        sa.ForeignKeyConstraint(["binding_db_id"], ["canonical_parser_paper_runtime_bindings.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("event_id", name="uq_parser_paper_runtime_binding_events_id"),
        sa.UniqueConstraint("binding_db_id", "sequence", name="uq_parser_paper_runtime_binding_events_sequence"),
    )
    op.create_index("ix_parser_paper_runtime_binding_events_binding_sequence", "canonical_parser_paper_runtime_binding_events", ["binding_db_id", "sequence"])


def downgrade() -> None:
    op.drop_index("ix_parser_paper_runtime_binding_events_binding_sequence", table_name="canonical_parser_paper_runtime_binding_events")
    op.drop_table("canonical_parser_paper_runtime_binding_events")
    op.drop_index("ix_parser_paper_runtime_bindings_account", table_name="canonical_parser_paper_runtime_bindings")
    op.drop_index("ix_parser_paper_runtime_bindings_status_expiry", table_name="canonical_parser_paper_runtime_bindings")
    op.drop_table("canonical_parser_paper_runtime_bindings")
