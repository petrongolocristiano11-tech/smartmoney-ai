"""add parser runtime binding and drift control

Revision ID: a2d8f4c6b913
Revises: f9c4d7a2b815
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a2d8f4c6b913"
down_revision: Union[str, Sequence[str], None] = "f9c4d7a2b815"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "canonical_parser_runtime_bindings",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column("binding_id", sa.String(36), nullable=False),
        sa.Column("binding_key", sa.String(64), nullable=False),
        sa.Column("promotion_db_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
        sa.Column("promotion_id", sa.String(36), nullable=False),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("parser_name", sa.String(80), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("parser_implementation_hash", sa.String(64), nullable=False),
        sa.Column("output_schema_version", sa.String(64), nullable=False),
        sa.Column("release_manifest_hash", sa.String(64), nullable=False),
        sa.Column("binding_policy_version", sa.String(64), nullable=False),
        sa.Column("binding_policy_hash", sa.String(64), nullable=False),
        sa.Column("bound_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("unbound_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unbind_reason", sa.Text(), nullable=True),
        sa.Column("latest_event_sequence", sa.Integer(), nullable=False),
        sa.Column("latest_event_hash", sa.String(64), nullable=False),
        sa.Column("technical_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE', 'UNBOUND')", name="ck_canonical_parser_runtime_bindings_status"),
        sa.CheckConstraint("scope IN ('SHADOW_ONLY')", name="ck_canonical_parser_runtime_bindings_scope"),
        sa.CheckConstraint("channel IN ('CANONICAL_SHADOW')", name="ck_canonical_parser_runtime_bindings_channel"),
        sa.CheckConstraint("latest_event_sequence >= 1", name="ck_canonical_parser_runtime_bindings_event_sequence_positive"),
        sa.CheckConstraint("length(binding_key) = 64", name="ck_canonical_parser_runtime_bindings_key_length"),
        sa.CheckConstraint("length(parser_implementation_hash) = 64", name="ck_canonical_parser_runtime_bindings_parser_hash_length"),
        sa.CheckConstraint("length(release_manifest_hash) = 64", name="ck_canonical_parser_runtime_bindings_release_hash_length"),
        sa.CheckConstraint("length(binding_policy_hash) = 64", name="ck_canonical_parser_runtime_bindings_policy_hash_length"),
        sa.CheckConstraint("length(latest_event_hash) = 64", name="ck_canonical_parser_runtime_bindings_latest_event_hash_length"),
        sa.ForeignKeyConstraint(["promotion_db_id"], ["canonical_parser_promotions.id"], ondelete="RESTRICT", name="fk_canonical_parser_runtime_bindings_promotion"),
        sa.UniqueConstraint("binding_id", name="uq_canonical_parser_runtime_bindings_binding_id"),
        sa.UniqueConstraint("binding_key", name="uq_canonical_parser_runtime_bindings_binding_key"),
    )
    op.create_index("ix_canonical_parser_runtime_bindings_status_scope_channel", "canonical_parser_runtime_bindings", ["status", "scope", "channel"])
    op.create_index("ix_canonical_parser_runtime_bindings_promotion", "canonical_parser_runtime_bindings", ["promotion_db_id"])
    op.create_index("ix_canonical_parser_runtime_bindings_parser_version", "canonical_parser_runtime_bindings", ["parser_name", "parser_version"])
    op.create_index(
        "uq_canonical_parser_runtime_bindings_active_scope_channel",
        "canonical_parser_runtime_bindings", ["scope", "channel"], unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"), sqlite_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_table(
        "canonical_parser_runtime_binding_events",
        sa.Column("id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("binding_db_id", sa.BigInteger().with_variant(sa.Integer(), "sqlite"), nullable=False),
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
        sa.CheckConstraint("sequence >= 1", name="ck_canonical_parser_runtime_binding_events_sequence_positive"),
        sa.CheckConstraint("event_type IN ('BOUND', 'UNBOUND')", name="ck_canonical_parser_runtime_binding_events_type"),
        sa.CheckConstraint("previous_status IS NULL OR previous_status IN ('ACTIVE', 'UNBOUND')", name="ck_canonical_parser_runtime_binding_events_previous_status"),
        sa.CheckConstraint("new_status IN ('ACTIVE', 'UNBOUND')", name="ck_canonical_parser_runtime_binding_events_new_status"),
        sa.CheckConstraint("previous_event_hash IS NULL OR length(previous_event_hash) = 64", name="ck_canonical_parser_runtime_binding_events_previous_hash_length"),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_canonical_parser_runtime_binding_events_hash_length"),
        sa.ForeignKeyConstraint(["binding_db_id"], ["canonical_parser_runtime_bindings.id"], ondelete="CASCADE", name="fk_canonical_parser_runtime_binding_events_binding"),
        sa.UniqueConstraint("event_id", name="uq_canonical_parser_runtime_binding_events_event_id"),
        sa.UniqueConstraint("binding_db_id", "sequence", name="uq_canonical_parser_runtime_binding_events_binding_sequence"),
    )
    op.create_index("ix_canonical_parser_runtime_binding_events_type_occurred", "canonical_parser_runtime_binding_events", ["event_type", "occurred_at"])
    op.create_index("ix_canonical_parser_runtime_binding_events_binding_sequence", "canonical_parser_runtime_binding_events", ["binding_db_id", "sequence"])


def downgrade() -> None:
    op.drop_index("ix_canonical_parser_runtime_binding_events_binding_sequence", table_name="canonical_parser_runtime_binding_events")
    op.drop_index("ix_canonical_parser_runtime_binding_events_type_occurred", table_name="canonical_parser_runtime_binding_events")
    op.drop_table("canonical_parser_runtime_binding_events")
    op.drop_index("uq_canonical_parser_runtime_bindings_active_scope_channel", table_name="canonical_parser_runtime_bindings")
    op.drop_index("ix_canonical_parser_runtime_bindings_parser_version", table_name="canonical_parser_runtime_bindings")
    op.drop_index("ix_canonical_parser_runtime_bindings_promotion", table_name="canonical_parser_runtime_bindings")
    op.drop_index("ix_canonical_parser_runtime_bindings_status_scope_channel", table_name="canonical_parser_runtime_bindings")
    op.drop_table("canonical_parser_runtime_bindings")
