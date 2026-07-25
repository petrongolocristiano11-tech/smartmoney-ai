"""add certified shadow runtime lease

Revision ID: d8c2f5a7e104
Revises: c6f1e8a3d942
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d8c2f5a7e104"
down_revision: Union[str, Sequence[str], None] = "c6f1e8a3d942"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "canonical_parser_shadow_runtime_leases",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column("lease_id", sa.String(36), nullable=False),
        sa.Column("lease_key", sa.String(64), nullable=False),
        sa.Column("lease_generation", sa.Integer(), nullable=False),
        sa.Column("certification_db_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
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
        sa.Column("certification_event_hash", sa.String(64), nullable=False),
        sa.Column("lease_policy_version", sa.String(64), nullable=False),
        sa.Column("lease_policy_hash", sa.String(64), nullable=False),
        sa.Column("lease_policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("requested_validity_minutes", sa.Integer(), nullable=False),
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
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE', 'REVOKED', 'EXPIRED')", name="ck_canonical_parser_shadow_runtime_leases_status"),
        sa.CheckConstraint("scope IN ('SHADOW_ONLY')", name="ck_canonical_parser_shadow_runtime_leases_scope"),
        sa.CheckConstraint("channel IN ('CANONICAL_SHADOW')", name="ck_canonical_parser_shadow_runtime_leases_channel"),
        sa.CheckConstraint("consumer IN ('CERTIFIED_SHADOW_RUNTIME')", name="ck_canonical_parser_shadow_runtime_leases_consumer"),
        sa.CheckConstraint("lease_generation >= 1", name="ck_canonical_parser_shadow_runtime_leases_generation"),
        sa.CheckConstraint("requested_validity_minutes >= 5", name="ck_canonical_parser_shadow_runtime_leases_validity"),
        sa.CheckConstraint("latest_event_sequence >= 1", name="ck_canonical_parser_shadow_runtime_leases_sequence"),
        sa.CheckConstraint("length(lease_key) = 64", name="ck_canonical_parser_shadow_runtime_leases_key_length"),
        sa.CheckConstraint("length(parser_implementation_hash) = 64", name="ck_canonical_parser_shadow_runtime_leases_parser_hash_length"),
        sa.CheckConstraint("length(release_manifest_hash) = 64", name="ck_canonical_parser_shadow_runtime_leases_release_hash_length"),
        sa.CheckConstraint("length(certification_event_hash) = 64", name="ck_canonical_parser_shadow_runtime_leases_cert_hash_length"),
        sa.CheckConstraint("length(lease_policy_hash) = 64", name="ck_canonical_parser_shadow_runtime_leases_policy_hash_length"),
        sa.CheckConstraint("length(latest_event_hash) = 64", name="ck_canonical_parser_shadow_runtime_leases_latest_hash_length"),
        sa.ForeignKeyConstraint(["certification_db_id"], ["canonical_parser_runtime_certifications.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("lease_id", name="uq_canonical_parser_shadow_runtime_leases_id"),
        sa.UniqueConstraint("lease_key", name="uq_canonical_parser_shadow_runtime_leases_key"),
        sa.UniqueConstraint("consumer", "lease_generation", name="uq_canonical_parser_shadow_runtime_leases_generation"),
    )
    op.create_index("ix_canonical_parser_shadow_runtime_leases_cert_status", "canonical_parser_shadow_runtime_leases", ["certification_db_id", "status"])
    op.create_index("ix_canonical_parser_shadow_runtime_leases_expires", "canonical_parser_shadow_runtime_leases", ["status", "expires_at"])
    op.create_index("ix_canonical_parser_shadow_runtime_leases_parser_version", "canonical_parser_shadow_runtime_leases", ["parser_name", "parser_version"])
    op.create_index(
        "uq_canonical_parser_shadow_runtime_leases_active_consumer",
        "canonical_parser_shadow_runtime_leases",
        ["consumer"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
        sqlite_where=sa.text("status = 'ACTIVE'"),
    )

    op.create_table(
        "canonical_parser_shadow_runtime_lease_events",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("lease_db_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
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
        sa.CheckConstraint("sequence >= 1", name="ck_canonical_parser_shadow_runtime_lease_events_sequence"),
        sa.CheckConstraint("event_type IN ('ISSUED', 'REVOKED', 'EXPIRED')", name="ck_canonical_parser_shadow_runtime_lease_events_type"),
        sa.CheckConstraint("new_status IN ('ACTIVE', 'REVOKED', 'EXPIRED')", name="ck_canonical_parser_shadow_runtime_lease_events_new_status"),
        sa.CheckConstraint("previous_status IS NULL OR previous_status IN ('ACTIVE', 'REVOKED', 'EXPIRED')", name="ck_canonical_parser_shadow_runtime_lease_events_previous_status"),
        sa.CheckConstraint("previous_event_hash IS NULL OR length(previous_event_hash) = 64", name="ck_canonical_shadow_lease_events_prev_hash_len"),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_canonical_parser_shadow_runtime_lease_events_hash_length"),
        sa.ForeignKeyConstraint(["lease_db_id"], ["canonical_parser_shadow_runtime_leases.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("event_id", name="uq_canonical_parser_shadow_runtime_lease_events_id"),
        sa.UniqueConstraint("lease_db_id", "sequence", name="uq_canonical_parser_shadow_runtime_lease_events_sequence"),
        sa.UniqueConstraint("event_hash", name="uq_canonical_parser_shadow_runtime_lease_events_hash"),
    )
    op.create_index("ix_canonical_parser_shadow_runtime_lease_events_lease_sequence", "canonical_parser_shadow_runtime_lease_events", ["lease_db_id", "sequence"])
    op.create_index("ix_canonical_parser_shadow_runtime_lease_events_type_time", "canonical_parser_shadow_runtime_lease_events", ["event_type", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_canonical_parser_shadow_runtime_lease_events_type_time", table_name="canonical_parser_shadow_runtime_lease_events")
    op.drop_index("ix_canonical_parser_shadow_runtime_lease_events_lease_sequence", table_name="canonical_parser_shadow_runtime_lease_events")
    op.drop_table("canonical_parser_shadow_runtime_lease_events")
    op.drop_index("uq_canonical_parser_shadow_runtime_leases_active_consumer", table_name="canonical_parser_shadow_runtime_leases")
    op.drop_index("ix_canonical_parser_shadow_runtime_leases_parser_version", table_name="canonical_parser_shadow_runtime_leases")
    op.drop_index("ix_canonical_parser_shadow_runtime_leases_expires", table_name="canonical_parser_shadow_runtime_leases")
    op.drop_index("ix_canonical_parser_shadow_runtime_leases_cert_status", table_name="canonical_parser_shadow_runtime_leases")
    op.drop_table("canonical_parser_shadow_runtime_leases")
