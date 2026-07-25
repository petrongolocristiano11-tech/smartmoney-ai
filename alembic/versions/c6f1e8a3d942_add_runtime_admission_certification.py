"""add runtime admission certification

Revision ID: c6f1e8a3d942
Revises: b4e6a9d1c027
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "c6f1e8a3d942"
down_revision: Union[str, Sequence[str], None] = "b4e6a9d1c027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "canonical_parser_runtime_certifications",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column("certification_id", sa.String(36), nullable=False),
        sa.Column("certification_key", sa.String(64), nullable=False),
        sa.Column("binding_db_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("binding_id", sa.String(36), nullable=False),
        sa.Column("promotion_id", sa.String(36), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("parser_name", sa.String(80), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("parser_implementation_hash", sa.String(64), nullable=False),
        sa.Column("output_schema_version", sa.String(64), nullable=False),
        sa.Column("release_manifest_hash", sa.String(64), nullable=False),
        sa.Column("certification_policy_version", sa.String(64), nullable=False),
        sa.Column("certification_policy_hash", sa.String(64), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("evidence_snapshot", sa.JSON(), nullable=False),
        sa.Column("admission_run_ids", sa.JSON(), nullable=False),
        sa.Column("admission_run_count", sa.Integer(), nullable=False),
        sa.Column("total_processed_count", sa.Integer(), nullable=False),
        sa.Column("total_passed_count", sa.Integer(), nullable=False),
        sa.Column("total_failed_count", sa.Integer(), nullable=False),
        sa.Column("total_skipped_count", sa.Integer(), nullable=False),
        sa.Column("pass_rate", sa.Numeric(7, 4), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("certified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
        sa.Column("latest_event_sequence", sa.Integer(), nullable=False),
        sa.Column("latest_event_hash", sa.String(64), nullable=False),
        sa.Column("technical_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('CERTIFIED', 'REVOKED')", name="ck_canonical_parser_runtime_certifications_status"),
        sa.CheckConstraint("scope IN ('SHADOW_ONLY')", name="ck_canonical_parser_runtime_certifications_scope"),
        sa.CheckConstraint("channel IN ('CANONICAL_SHADOW')", name="ck_canonical_parser_runtime_certifications_channel"),
        sa.CheckConstraint("admission_run_count >= 1", name="ck_canonical_parser_runtime_certifications_run_count"),
        sa.CheckConstraint("total_processed_count >= 0 AND total_passed_count >= 0 AND total_failed_count >= 0 AND total_skipped_count >= 0", name="ck_canonical_parser_runtime_certifications_counts_nonnegative"),
        sa.CheckConstraint("pass_rate >= 0 AND pass_rate <= 100", name="ck_canonical_parser_runtime_certifications_pass_rate"),
        sa.CheckConstraint("latest_event_sequence >= 1", name="ck_canonical_parser_runtime_certifications_sequence_positive"),
        sa.CheckConstraint("length(certification_key) = 64", name="ck_canonical_parser_runtime_certifications_key_length"),
        sa.CheckConstraint("length(parser_implementation_hash) = 64", name="ck_canonical_parser_runtime_certifications_parser_hash_length"),
        sa.CheckConstraint("length(release_manifest_hash) = 64", name="ck_canonical_parser_runtime_certifications_release_hash_length"),
        sa.CheckConstraint("length(certification_policy_hash) = 64", name="ck_canonical_parser_runtime_certifications_policy_hash_length"),
        sa.CheckConstraint("length(evidence_hash) = 64", name="ck_canonical_parser_runtime_certifications_evidence_hash_length"),
        sa.CheckConstraint("length(latest_event_hash) = 64", name="ck_canonical_parser_runtime_certifications_latest_hash_length"),
        sa.ForeignKeyConstraint(["binding_db_id"], ["canonical_parser_runtime_bindings.id"], ondelete="RESTRICT", name="fk_canonical_parser_runtime_certifications_binding"),
        sa.UniqueConstraint("certification_id", name="uq_canonical_parser_runtime_certifications_id"),
        sa.UniqueConstraint("certification_key", name="uq_canonical_parser_runtime_certifications_key"),
    )
    op.create_index("ix_canonical_parser_runtime_certifications_binding_status", "canonical_parser_runtime_certifications", ["binding_db_id", "status"])
    op.create_index("ix_canonical_parser_runtime_certifications_parser_version", "canonical_parser_runtime_certifications", ["parser_name", "parser_version"])
    op.create_index("ix_canonical_parser_runtime_certifications_expires", "canonical_parser_runtime_certifications", ["status", "expires_at"])
    op.create_index(
        "uq_canonical_parser_runtime_certifications_active_binding",
        "canonical_parser_runtime_certifications",
        ["binding_db_id"],
        unique=True,
        postgresql_where=sa.text("status = 'CERTIFIED'"),
        sqlite_where=sa.text("status = 'CERTIFIED'"),
    )
    op.create_table(
        "canonical_parser_runtime_certification_events",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("certification_db_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
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
        sa.CheckConstraint("sequence >= 1", name="ck_canonical_parser_runtime_certification_events_sequence"),
        sa.CheckConstraint("event_type IN ('CERTIFIED', 'REVOKED')", name="ck_canonical_parser_runtime_certification_events_type"),
        sa.CheckConstraint("previous_status IS NULL OR previous_status IN ('CERTIFIED', 'REVOKED')", name="ck_canonical_parser_cert_events_prev_status"),
        sa.CheckConstraint("new_status IN ('CERTIFIED', 'REVOKED')", name="ck_canonical_parser_runtime_certification_events_new_status"),
        sa.CheckConstraint("previous_event_hash IS NULL OR length(previous_event_hash) = 64", name="ck_canonical_parser_cert_events_prev_hash_len"),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_canonical_parser_runtime_certification_events_hash_length"),
        sa.ForeignKeyConstraint(["certification_db_id"], ["canonical_parser_runtime_certifications.id"], ondelete="CASCADE", name="fk_canonical_parser_runtime_certification_events_certification"),
        sa.UniqueConstraint("event_id", name="uq_canonical_parser_runtime_certification_events_id"),
        sa.UniqueConstraint("certification_db_id", "sequence", name="uq_canonical_parser_runtime_certification_events_sequence"),
    )
    op.create_index("ix_canonical_parser_runtime_certification_events_cert_sequence", "canonical_parser_runtime_certification_events", ["certification_db_id", "sequence"])
    op.create_index("ix_canonical_parser_runtime_certification_events_type_time", "canonical_parser_runtime_certification_events", ["event_type", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_canonical_parser_runtime_certification_events_type_time", table_name="canonical_parser_runtime_certification_events")
    op.drop_index("ix_canonical_parser_runtime_certification_events_cert_sequence", table_name="canonical_parser_runtime_certification_events")
    op.drop_table("canonical_parser_runtime_certification_events")
    op.drop_index("uq_canonical_parser_runtime_certifications_active_binding", table_name="canonical_parser_runtime_certifications")
    op.drop_index("ix_canonical_parser_runtime_certifications_expires", table_name="canonical_parser_runtime_certifications")
    op.drop_index("ix_canonical_parser_runtime_certifications_parser_version", table_name="canonical_parser_runtime_certifications")
    op.drop_index("ix_canonical_parser_runtime_certifications_binding_status", table_name="canonical_parser_runtime_certifications")
    op.drop_table("canonical_parser_runtime_certifications")
