"""add certified shadow execution ticket

Revision ID: b7d1f4a6c825
Revises: a5c9e2f4b716
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b7d1f4a6c825"
down_revision: Union[str, Sequence[str], None] = "a5c9e2f4b716"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "canonical_parser_shadow_execution_tickets",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
        ),
        sa.Column("ticket_id", sa.String(36), nullable=False),
        sa.Column("ticket_key", sa.String(64), nullable=False),
        sa.Column("ticket_generation", sa.Integer(), nullable=False),
        sa.Column(
            "permit_db_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("permit_id", sa.String(36), nullable=False),
        sa.Column("permit_key", sa.String(64), nullable=False),
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
        sa.Column("ticket_policy_version", sa.String(64), nullable=False),
        sa.Column("ticket_policy_hash", sa.String(64), nullable=False),
        sa.Column("ticket_policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("requested_validity_seconds", sa.Integer(), nullable=False),
        sa.Column("run_reservation", sa.Integer(), nullable=False),
        sa.Column("event_reservation", sa.Integer(), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("release_reason", sa.Text(), nullable=True),
        sa.Column("latest_event_sequence", sa.Integer(), nullable=False),
        sa.Column("latest_event_hash", sa.String(64), nullable=False),
        sa.Column("technical_metadata", sa.JSON(), nullable=False),
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
            "status IN ('RESERVED', 'RELEASED', 'EXPIRED')",
            name="ck_shadow_execution_tickets_status",
        ),
        sa.CheckConstraint(
            "scope IN ('SHADOW_ONLY')",
            name="ck_shadow_execution_tickets_scope",
        ),
        sa.CheckConstraint(
            "channel IN ('CANONICAL_SHADOW')",
            name="ck_shadow_execution_tickets_channel",
        ),
        sa.CheckConstraint(
            "consumer IN ('CERTIFIED_SHADOW_AUTOMATION')",
            name="ck_shadow_execution_tickets_consumer",
        ),
        sa.CheckConstraint(
            "executor IN ('CERTIFIED_SHADOW_EXECUTION_TICKET')",
            name="ck_shadow_execution_tickets_executor",
        ),
        sa.CheckConstraint(
            "ticket_generation >= 1",
            name="ck_shadow_execution_tickets_generation",
        ),
        sa.CheckConstraint(
            "requested_validity_seconds >= 1",
            name="ck_shadow_execution_tickets_validity",
        ),
        sa.CheckConstraint(
            "run_reservation = 1",
            name="ck_shadow_execution_tickets_run_reservation",
        ),
        sa.CheckConstraint(
            "event_reservation >= 1",
            name="ck_shadow_execution_tickets_event_reservation",
        ),
        sa.CheckConstraint(
            "latest_event_sequence >= 1",
            name="ck_shadow_execution_tickets_sequence",
        ),
        sa.CheckConstraint("length(ticket_key) = 64", name="ck_shadow_execution_tickets_key_len"),
        sa.CheckConstraint("length(permit_key) = 64", name="ck_shadow_execution_tickets_permit_key_len"),
        sa.CheckConstraint("length(parser_implementation_hash) = 64", name="ck_shadow_execution_tickets_parser_hash_len"),
        sa.CheckConstraint("length(release_manifest_hash) = 64", name="ck_shadow_execution_tickets_release_hash_len"),
        sa.CheckConstraint("length(readiness_evidence_hash) = 64", name="ck_shadow_execution_tickets_readiness_hash_len"),
        sa.CheckConstraint("length(permit_policy_hash) = 64", name="ck_shadow_execution_tickets_permit_policy_hash_len"),
        sa.CheckConstraint("length(permit_event_hash) = 64", name="ck_shadow_execution_tickets_permit_event_hash_len"),
        sa.CheckConstraint("length(ticket_policy_hash) = 64", name="ck_shadow_execution_tickets_policy_hash_len"),
        sa.CheckConstraint("length(latest_event_hash) = 64", name="ck_shadow_execution_tickets_latest_hash_len"),
        sa.ForeignKeyConstraint(
            ["permit_db_id"],
            ["canonical_parser_shadow_automation_permits.id"],
            name="fk_shadow_execution_tickets_permit",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("ticket_id", name="uq_shadow_execution_tickets_id"),
        sa.UniqueConstraint("ticket_key", name="uq_shadow_execution_tickets_key"),
        sa.UniqueConstraint("permit_db_id", "ticket_generation", name="uq_shadow_execution_tickets_generation"),
    )
    op.create_index(
        "ix_shadow_execution_tickets_permit_status",
        "canonical_parser_shadow_execution_tickets",
        ["permit_db_id", "status"],
    )
    op.create_index(
        "ix_shadow_execution_tickets_expires",
        "canonical_parser_shadow_execution_tickets",
        ["status", "expires_at"],
    )
    op.create_index(
        "ix_shadow_execution_tickets_parser",
        "canonical_parser_shadow_execution_tickets",
        ["parser_name", "parser_version"],
    )

    op.create_table(
        "canonical_parser_shadow_execution_ticket_events",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
        ),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column(
            "ticket_db_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_shadow_execution_ticket_events_sequence"),
        sa.CheckConstraint("event_type IN ('RESERVED', 'RELEASED', 'EXPIRED')", name="ck_shadow_execution_ticket_events_type"),
        sa.CheckConstraint("previous_status IS NULL OR previous_status IN ('RESERVED', 'RELEASED', 'EXPIRED')", name="ck_shadow_execution_ticket_events_previous_status"),
        sa.CheckConstraint("new_status IN ('RESERVED', 'RELEASED', 'EXPIRED')", name="ck_shadow_execution_ticket_events_new_status"),
        sa.CheckConstraint("previous_event_hash IS NULL OR length(previous_event_hash) = 64", name="ck_shadow_execution_ticket_events_prev_hash_len"),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_shadow_execution_ticket_events_hash_len"),
        sa.ForeignKeyConstraint(
            ["ticket_db_id"],
            ["canonical_parser_shadow_execution_tickets.id"],
            name="fk_shadow_execution_ticket_events_ticket",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("event_id", name="uq_shadow_execution_ticket_events_id"),
        sa.UniqueConstraint("ticket_db_id", "sequence", name="uq_shadow_execution_ticket_events_sequence"),
        sa.UniqueConstraint("event_hash", name="uq_shadow_execution_ticket_events_hash"),
    )
    op.create_index(
        "ix_shadow_execution_ticket_events_ticket_sequence",
        "canonical_parser_shadow_execution_ticket_events",
        ["ticket_db_id", "sequence"],
    )
    op.create_index(
        "ix_shadow_execution_ticket_events_type_time",
        "canonical_parser_shadow_execution_ticket_events",
        ["event_type", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_shadow_execution_ticket_events_type_time",
        table_name="canonical_parser_shadow_execution_ticket_events",
    )
    op.drop_index(
        "ix_shadow_execution_ticket_events_ticket_sequence",
        table_name="canonical_parser_shadow_execution_ticket_events",
    )
    op.drop_table("canonical_parser_shadow_execution_ticket_events")
    op.drop_index(
        "ix_shadow_execution_tickets_parser",
        table_name="canonical_parser_shadow_execution_tickets",
    )
    op.drop_index(
        "ix_shadow_execution_tickets_expires",
        table_name="canonical_parser_shadow_execution_tickets",
    )
    op.drop_index(
        "ix_shadow_execution_tickets_permit_status",
        table_name="canonical_parser_shadow_execution_tickets",
    )
    op.drop_table("canonical_parser_shadow_execution_tickets")
