"""add assisted micro live pilot

Revision ID: b0e2f5a8c964
Revises: a9d1e4f7b853
Create Date: 2026-07-29 19:30:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b0e2f5a8c964"
down_revision: Union[str, Sequence[str], None] = "a9d1e4f7b853"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")

    op.create_table(
        "canonical_parser_assisted_micro_live_pilots",
        sa.Column("id", pk, primary_key=True),
        sa.Column("pilot_id", sa.String(36), nullable=False),
        sa.Column("pilot_key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(48), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("certification_db_id", pk, nullable=False),
        sa.Column("certification_id", sa.String(36), nullable=False),
        sa.Column("wallet_address", sa.String(64), nullable=False),
        sa.Column("network", sa.String(32), nullable=False),
        sa.Column("token_mint", sa.String(64), nullable=False),
        sa.Column("max_entry_budget_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("max_total_fee_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("max_position_duration_minutes", sa.Integer(), nullable=False),
        sa.Column("required_checklist_count", sa.Integer(), nullable=False),
        sa.Column("passed_checklist_count", sa.Integer(), nullable=False),
        sa.Column("entry_submission_id", sa.String(36), nullable=True),
        sa.Column("entry_settlement_id", sa.String(36), nullable=True),
        sa.Column("position_id", sa.String(36), nullable=True),
        sa.Column("exit_intent_id", sa.String(36), nullable=True),
        sa.Column("exit_submission_id", sa.String(36), nullable=True),
        sa.Column("exit_settlement_id", sa.String(36), nullable=True),
        sa.Column("post_observability_snapshot_id", sa.String(36), nullable=True),
        sa.Column("pilot_snapshot", sa.JSON(), nullable=False),
        sa.Column("completion_snapshot", sa.JSON(), nullable=True),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("armed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("aborted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_event_sequence", sa.Integer(), nullable=False),
        sa.Column("latest_event_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope = 'M45_ASSISTED_MICRO_LIVE_PILOT'", name="ck_m45_pilot_scope"),
        sa.CheckConstraint("network = 'mainnet-beta'", name="ck_m45_pilot_network"),
        sa.CheckConstraint("status IN ('PLANNED','ARMED','ENTRY_SUBMITTED','ENTRY_RECONCILED','ENTRY_SETTLED','EXIT_READY','EXIT_SUBMITTED','EXIT_RECONCILED','EXIT_SETTLED','COMPLETED','ABORTED','EXPIRED')", name="ck_m45_pilot_status"),
        sa.CheckConstraint("max_entry_budget_sol > 0 AND max_total_fee_sol >= 0", name="ck_m45_pilot_budgets"),
        sa.CheckConstraint("max_position_duration_minutes >= 1", name="ck_m45_pilot_duration"),
        sa.CheckConstraint("required_checklist_count >= 1 AND passed_checklist_count >= 0 AND passed_checklist_count <= required_checklist_count", name="ck_m45_pilot_checklist_counts"),
        sa.CheckConstraint("latest_event_sequence >= 1", name="ck_m45_pilot_event_sequence"),
        sa.CheckConstraint("length(pilot_key) = 64 AND length(evidence_hash) = 64 AND length(latest_event_hash) = 64", name="ck_m45_pilot_hashes"),
        sa.ForeignKeyConstraint(["certification_db_id"], ["canonical_parser_preproduction_certifications.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("pilot_id", name="uq_m45_pilot_id"),
        sa.UniqueConstraint("pilot_key", name="uq_m45_pilot_key"),
    )
    op.create_index("ix_m45_pilot_wallet_status", "canonical_parser_assisted_micro_live_pilots", ["wallet_address", "status"])
    op.create_index("ix_m45_pilot_token_status", "canonical_parser_assisted_micro_live_pilots", ["token_mint", "status"])
    op.create_index("ix_m45_pilot_status_expiry", "canonical_parser_assisted_micro_live_pilots", ["status", "expires_at"])

    op.create_table(
        "canonical_parser_assisted_micro_live_pilot_checklist",
        sa.Column("id", pk, primary_key=True),
        sa.Column("item_id", sa.String(36), nullable=False),
        sa.Column("pilot_db_id", pk, nullable=False),
        sa.Column("pilot_id", sa.String(36), nullable=False),
        sa.Column("item_code", sa.String(80), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("attestation_detail", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("attested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('PASS','FAIL')", name="ck_m45_checklist_status"),
        sa.CheckConstraint("length(evidence_hash) = 64", name="ck_m45_checklist_hash"),
        sa.ForeignKeyConstraint(["pilot_db_id"], ["canonical_parser_assisted_micro_live_pilots.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("item_id", name="uq_m45_checklist_item_id"),
        sa.UniqueConstraint("pilot_db_id", "item_code", name="uq_m45_checklist_item_code"),
    )
    op.create_index("ix_m45_checklist_pilot_status", "canonical_parser_assisted_micro_live_pilot_checklist", ["pilot_db_id", "status"])

    op.create_table(
        "canonical_parser_assisted_micro_live_pilot_checkpoints",
        sa.Column("id", pk, primary_key=True),
        sa.Column("checkpoint_id", sa.String(36), nullable=False),
        sa.Column("checkpoint_key", sa.String(64), nullable=False),
        sa.Column("pilot_db_id", pk, nullable=False),
        sa.Column("pilot_id", sa.String(36), nullable=False),
        sa.Column("checkpoint_type", sa.String(32), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(96), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("checkpoint_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("checkpoint_type IN ('ENTRY_RECONCILED','ENTRY_SETTLED','EXIT_INTENT_VERIFIED','EXIT_RECONCILED','EXIT_SETTLED','POST_PILOT_HEALTH')", name="ck_m45_checkpoint_type"),
        sa.CheckConstraint("status IN ('VERIFIED','BLOCKED')", name="ck_m45_checkpoint_status"),
        sa.CheckConstraint("length(checkpoint_key) = 64 AND length(evidence_hash) = 64", name="ck_m45_checkpoint_hashes"),
        sa.ForeignKeyConstraint(["pilot_db_id"], ["canonical_parser_assisted_micro_live_pilots.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("checkpoint_id", name="uq_m45_checkpoint_id"),
        sa.UniqueConstraint("checkpoint_key", name="uq_m45_checkpoint_key"),
    )
    op.create_index("ix_m45_checkpoint_pilot_type", "canonical_parser_assisted_micro_live_pilot_checkpoints", ["pilot_db_id", "checkpoint_type"])
    op.create_index("ix_m45_checkpoint_status_time", "canonical_parser_assisted_micro_live_pilot_checkpoints", ["status", "checked_at"])

    op.create_table(
        "canonical_parser_assisted_micro_live_pilot_events",
        sa.Column("id", pk, primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("pilot_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column("previous_event_hash", sa.String(64), nullable=True),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_m45_pilot_event_sequence"),
        sa.CheckConstraint("event_type IN ('ISSUED','CHECK_ATTESTED','ARMED','ENTRY_SUBMITTED','CHECKPOINT_VERIFIED','EXIT_SUBMITTED','COMPLETED','ABORTED','EXPIRED')", name="ck_m45_pilot_event_type"),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_m45_pilot_event_hash"),
        sa.ForeignKeyConstraint(["pilot_db_id"], ["canonical_parser_assisted_micro_live_pilots.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("event_id", name="uq_m45_pilot_event_id"),
        sa.UniqueConstraint("pilot_db_id", "sequence", name="uq_m45_pilot_event_sequence"),
    )
    op.create_index("ix_m45_pilot_event_time", "canonical_parser_assisted_micro_live_pilot_events", ["pilot_db_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_m45_pilot_event_time", table_name="canonical_parser_assisted_micro_live_pilot_events")
    op.drop_table("canonical_parser_assisted_micro_live_pilot_events")
    op.drop_index("ix_m45_checkpoint_status_time", table_name="canonical_parser_assisted_micro_live_pilot_checkpoints")
    op.drop_index("ix_m45_checkpoint_pilot_type", table_name="canonical_parser_assisted_micro_live_pilot_checkpoints")
    op.drop_table("canonical_parser_assisted_micro_live_pilot_checkpoints")
    op.drop_index("ix_m45_checklist_pilot_status", table_name="canonical_parser_assisted_micro_live_pilot_checklist")
    op.drop_table("canonical_parser_assisted_micro_live_pilot_checklist")
    op.drop_index("ix_m45_pilot_status_expiry", table_name="canonical_parser_assisted_micro_live_pilots")
    op.drop_index("ix_m45_pilot_token_status", table_name="canonical_parser_assisted_micro_live_pilots")
    op.drop_index("ix_m45_pilot_wallet_status", table_name="canonical_parser_assisted_micro_live_pilots")
    op.drop_table("canonical_parser_assisted_micro_live_pilots")
