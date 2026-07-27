"""add paper admission certification

Revision ID: a9e6c2b4d731
Revises: f7c3a1d5e826
Create Date: 2026-07-26 21:25:00.000000
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "a9e6c2b4d731"
down_revision: str | Sequence[str] | None = "f7c3a1d5e826"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_paper_admission_certifications",
        sa.Column("id", pk, primary_key=True),
        sa.Column("certification_id", sa.String(36), nullable=False),
        sa.Column("certification_key", sa.String(64), nullable=False),
        sa.Column("assessment_db_id", pk, nullable=False),
        sa.Column("assessment_id", sa.String(36), nullable=False),
        sa.Column("assessment_key", sa.String(64), nullable=False),
        sa.Column("reliability_certification_id", sa.String(36), nullable=False),
        sa.Column("reliability_certification_event_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(64), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
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
        sa.CheckConstraint("status IN ('ACTIVE', 'REVOKED')", name="ck_parser_paper_admission_certifications_status"),
        sa.CheckConstraint("length(certification_key) = 64", name="ck_parser_paper_admission_certifications_key"),
        sa.CheckConstraint("length(reliability_certification_event_hash) = 64", name="ck_parser_paper_admission_certifications_reliability_hash"),
        sa.CheckConstraint("length(evidence_hash) = 64", name="ck_parser_paper_admission_certifications_evidence_hash"),
        sa.CheckConstraint("length(policy_hash) = 64", name="ck_parser_paper_admission_certifications_policy_hash"),
        sa.CheckConstraint("latest_event_sequence >= 1", name="ck_parser_paper_admission_certifications_event_sequence"),
        sa.CheckConstraint("length(latest_event_hash) = 64", name="ck_parser_paper_admission_certifications_event_hash"),
        sa.ForeignKeyConstraint(["assessment_db_id"], ["canonical_parser_paper_projection_readiness_assessments.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("certification_id", name="uq_parser_paper_admission_certifications_id"),
        sa.UniqueConstraint("certification_key", name="uq_parser_paper_admission_certifications_key"),
    )
    op.create_index("ix_parser_paper_admission_certifications_status_expiry", "canonical_parser_paper_admission_certifications", ["status", "expires_at"])
    op.create_index("ix_parser_paper_admission_certifications_assessment", "canonical_parser_paper_admission_certifications", ["assessment_db_id", "certified_at"])
    op.create_table(
        "canonical_parser_paper_admission_certification_events",
        sa.Column("id", pk, primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("certification_db_id", pk, nullable=False),
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
        sa.CheckConstraint("sequence >= 1", name="ck_parser_paper_admission_certification_events_sequence"),
        sa.CheckConstraint("event_type IN ('CERTIFIED', 'REVOKED')", name="ck_parser_paper_admission_certification_events_type"),
        sa.CheckConstraint("new_status IN ('ACTIVE', 'REVOKED')", name="ck_parser_paper_admission_certification_events_status"),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_parser_paper_admission_certification_events_hash"),
        sa.ForeignKeyConstraint(["certification_db_id"], ["canonical_parser_paper_admission_certifications.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("event_id", name="uq_parser_paper_admission_certification_events_id"),
        sa.UniqueConstraint("certification_db_id", "sequence", name="uq_parser_paper_admission_certification_events_sequence"),
    )
    op.create_index("ix_parser_paper_admission_certification_events_cert_sequence", "canonical_parser_paper_admission_certification_events", ["certification_db_id", "sequence"])


def downgrade() -> None:
    op.drop_index("ix_parser_paper_admission_certification_events_cert_sequence", table_name="canonical_parser_paper_admission_certification_events")
    op.drop_table("canonical_parser_paper_admission_certification_events")
    op.drop_index("ix_parser_paper_admission_certifications_assessment", table_name="canonical_parser_paper_admission_certifications")
    op.drop_index("ix_parser_paper_admission_certifications_status_expiry", table_name="canonical_parser_paper_admission_certifications")
    op.drop_table("canonical_parser_paper_admission_certifications")
