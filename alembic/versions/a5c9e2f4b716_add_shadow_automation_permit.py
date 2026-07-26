"""add certified shadow automation permit

Revision ID: a5c9e2f4b716
Revises: f3b7d9e2a614
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "a5c9e2f4b716"
down_revision: Union[str, Sequence[str], None] = "f3b7d9e2a614"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "canonical_parser_shadow_automation_permits",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
        ),
        sa.Column("permit_id", sa.String(36), nullable=False),
        sa.Column("permit_key", sa.String(64), nullable=False),
        sa.Column("permit_generation", sa.Integer(), nullable=False),
        sa.Column(
            "assessment_db_id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            nullable=False,
        ),
        sa.Column("assessment_id", sa.String(36), nullable=False),
        sa.Column("assessment_key", sa.String(64), nullable=False),
        sa.Column("lease_id", sa.String(36), nullable=False),
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
        sa.Column("lease_event_hash", sa.String(64), nullable=False),
        sa.Column("certification_event_hash", sa.String(64), nullable=False),
        sa.Column("readiness_policy_hash", sa.String(64), nullable=False),
        sa.Column("readiness_evidence_hash", sa.String(64), nullable=False),
        sa.Column("permit_policy_version", sa.String(64), nullable=False),
        sa.Column("permit_policy_hash", sa.String(64), nullable=False),
        sa.Column("permit_policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("requested_validity_minutes", sa.Integer(), nullable=False),
        sa.Column("run_budget", sa.Integer(), nullable=False),
        sa.Column("event_budget", sa.Integer(), nullable=False),
        sa.Column("consumed_run_count", sa.Integer(), nullable=False),
        sa.Column("consumed_event_count", sa.Integer(), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revocation_reason", sa.Text(), nullable=True),
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
            "status IN ('ACTIVE', 'REVOKED', 'EXPIRED', 'EXHAUSTED')",
            name="ck_shadow_automation_permits_status",
        ),
        sa.CheckConstraint(
            "scope IN ('SHADOW_ONLY')",
            name="ck_shadow_automation_permits_scope",
        ),
        sa.CheckConstraint(
            "channel IN ('CANONICAL_SHADOW')",
            name="ck_shadow_automation_permits_channel",
        ),
        sa.CheckConstraint(
            "consumer IN ('CERTIFIED_SHADOW_AUTOMATION')",
            name="ck_shadow_automation_permits_consumer",
        ),
        sa.CheckConstraint(
            "permit_generation >= 1",
            name="ck_shadow_automation_permits_generation",
        ),
        sa.CheckConstraint(
            "requested_validity_minutes >= 1",
            name="ck_shadow_automation_permits_validity",
        ),
        sa.CheckConstraint(
            "run_budget >= 1 AND event_budget >= 1",
            name="ck_shadow_automation_permits_budget_positive",
        ),
        sa.CheckConstraint(
            "consumed_run_count >= 0 AND consumed_run_count <= run_budget",
            name="ck_shadow_automation_permits_run_consumption",
        ),
        sa.CheckConstraint(
            "consumed_event_count >= 0 AND consumed_event_count <= event_budget",
            name="ck_shadow_automation_permits_event_consumption",
        ),
        sa.CheckConstraint(
            "latest_event_sequence >= 1",
            name="ck_shadow_automation_permits_sequence",
        ),
        sa.CheckConstraint(
            "length(permit_key) = 64",
            name="ck_shadow_automation_permits_key_len",
        ),
        sa.CheckConstraint(
            "length(assessment_key) = 64",
            name="ck_shadow_automation_permits_assessment_key_len",
        ),
        sa.CheckConstraint(
            "length(parser_implementation_hash) = 64",
            name="ck_shadow_automation_permits_parser_hash_len",
        ),
        sa.CheckConstraint(
            "length(release_manifest_hash) = 64",
            name="ck_shadow_automation_permits_release_hash_len",
        ),
        sa.CheckConstraint(
            "length(lease_event_hash) = 64",
            name="ck_shadow_automation_permits_lease_hash_len",
        ),
        sa.CheckConstraint(
            "length(certification_event_hash) = 64",
            name="ck_shadow_automation_permits_cert_hash_len",
        ),
        sa.CheckConstraint(
            "length(readiness_policy_hash) = 64",
            name="ck_shadow_automation_permits_readiness_policy_hash_len",
        ),
        sa.CheckConstraint(
            "length(readiness_evidence_hash) = 64",
            name="ck_shadow_automation_permits_readiness_evidence_hash_len",
        ),
        sa.CheckConstraint(
            "length(permit_policy_hash) = 64",
            name="ck_shadow_automation_permits_policy_hash_len",
        ),
        sa.CheckConstraint(
            "length(latest_event_hash) = 64",
            name="ck_shadow_automation_permits_latest_hash_len",
        ),
        sa.ForeignKeyConstraint(
            ["assessment_db_id"],
            ["canonical_parser_shadow_readiness_assessments.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("permit_id", name="uq_shadow_automation_permits_id"),
        sa.UniqueConstraint("permit_key", name="uq_shadow_automation_permits_key"),
        sa.UniqueConstraint(
            "consumer",
            "permit_generation",
            name="uq_shadow_automation_permits_generation",
        ),
    )
    op.create_index(
        "ix_shadow_automation_permits_assessment_status",
        "canonical_parser_shadow_automation_permits",
        ["assessment_db_id", "status"],
    )
    op.create_index(
        "ix_shadow_automation_permits_expires",
        "canonical_parser_shadow_automation_permits",
        ["status", "expires_at"],
    )
    op.create_index(
        "ix_shadow_automation_permits_parser",
        "canonical_parser_shadow_automation_permits",
        ["parser_name", "parser_version"],
    )
    op.create_index(
        "uq_shadow_automation_permits_active_consumer",
        "canonical_parser_shadow_automation_permits",
        ["consumer"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
        sqlite_where=sa.text("status = 'ACTIVE'"),
    )

    op.create_table(
        "canonical_parser_shadow_automation_permit_events",
        sa.Column(
            "id",
            sa.BigInteger().with_variant(sa.Integer(), "sqlite"),
            primary_key=True,
        ),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column(
            "permit_db_id",
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
        sa.CheckConstraint(
            "sequence >= 1",
            name="ck_shadow_automation_permit_events_sequence",
        ),
        sa.CheckConstraint(
            "event_type IN ('ISSUED', 'REVOKED', 'EXPIRED', 'EXHAUSTED')",
            name="ck_shadow_automation_permit_events_type",
        ),
        sa.CheckConstraint(
            "previous_status IS NULL OR previous_status IN "
            "('ACTIVE', 'REVOKED', 'EXPIRED', 'EXHAUSTED')",
            name="ck_shadow_automation_permit_events_previous_status",
        ),
        sa.CheckConstraint(
            "new_status IN ('ACTIVE', 'REVOKED', 'EXPIRED', 'EXHAUSTED')",
            name="ck_shadow_automation_permit_events_new_status",
        ),
        sa.CheckConstraint(
            "previous_event_hash IS NULL OR length(previous_event_hash) = 64",
            name="ck_shadow_automation_permit_events_prev_hash_len",
        ),
        sa.CheckConstraint(
            "length(event_hash) = 64",
            name="ck_shadow_automation_permit_events_hash_len",
        ),
        sa.ForeignKeyConstraint(
            ["permit_db_id"],
            ["canonical_parser_shadow_automation_permits.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "event_id", name="uq_shadow_automation_permit_events_id"
        ),
        sa.UniqueConstraint(
            "permit_db_id",
            "sequence",
            name="uq_shadow_automation_permit_events_sequence",
        ),
        sa.UniqueConstraint(
            "event_hash", name="uq_shadow_automation_permit_events_hash"
        ),
    )
    op.create_index(
        "ix_shadow_automation_permit_events_permit_sequence",
        "canonical_parser_shadow_automation_permit_events",
        ["permit_db_id", "sequence"],
    )
    op.create_index(
        "ix_shadow_automation_permit_events_type_time",
        "canonical_parser_shadow_automation_permit_events",
        ["event_type", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_shadow_automation_permit_events_type_time",
        table_name="canonical_parser_shadow_automation_permit_events",
    )
    op.drop_index(
        "ix_shadow_automation_permit_events_permit_sequence",
        table_name="canonical_parser_shadow_automation_permit_events",
    )
    op.drop_table("canonical_parser_shadow_automation_permit_events")

    op.drop_index(
        "uq_shadow_automation_permits_active_consumer",
        table_name="canonical_parser_shadow_automation_permits",
    )
    op.drop_index(
        "ix_shadow_automation_permits_parser",
        table_name="canonical_parser_shadow_automation_permits",
    )
    op.drop_index(
        "ix_shadow_automation_permits_expires",
        table_name="canonical_parser_shadow_automation_permits",
    )
    op.drop_index(
        "ix_shadow_automation_permits_assessment_status",
        table_name="canonical_parser_shadow_automation_permits",
    )
    op.drop_table("canonical_parser_shadow_automation_permits")
