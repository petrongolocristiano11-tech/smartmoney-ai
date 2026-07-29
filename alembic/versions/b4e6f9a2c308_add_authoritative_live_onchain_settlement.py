"""add authoritative live onchain settlement

Revision ID: b4e6f9a2c308
Revises: a3d5e8f1b297
Create Date: 2026-07-29 13:20:00.000000
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "b4e6f9a2c308"
down_revision: str | Sequence[str] | None = "a3d5e8f1b297"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_live_onchain_settlements",
        sa.Column("id", pk, primary_key=True),
        sa.Column("settlement_id", sa.String(36), nullable=False),
        sa.Column("settlement_key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(48), nullable=False),
        sa.Column("submission_db_id", pk, nullable=False),
        sa.Column("submission_id", sa.String(36), nullable=False),
        sa.Column("dry_run_id", sa.String(36), nullable=False),
        sa.Column("micro_live_permit_id", sa.String(36), nullable=False),
        sa.Column("decision_result_id", sa.String(36), nullable=False),
        sa.Column("position_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("token_mint", sa.String(64), nullable=False),
        sa.Column("wallet_address", sa.String(64), nullable=False),
        sa.Column("rpc_signature", sa.String(96), nullable=False),
        sa.Column("confirmation_status", sa.String(24), nullable=True),
        sa.Column("slot", sa.BigInteger(), nullable=True),
        sa.Column("block_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fee_lamports", sa.Numeric(20, 0), nullable=False),
        sa.Column("wallet_sol_delta_lamports", sa.Numeric(38, 0), nullable=False),
        sa.Column("token_delta_raw", sa.Numeric(38, 0), nullable=False),
        sa.Column("actual_input_amount_raw", sa.Numeric(38, 0), nullable=False),
        sa.Column("actual_output_amount_raw", sa.Numeric(38, 0), nullable=False),
        sa.Column("actual_input_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("actual_output_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("transaction_snapshot", sa.JSON(), nullable=False),
        sa.Column("attribution_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope = 'M39_AUTHORITATIVE_ONCHAIN_SETTLEMENT'", name="ck_m39_settlement_scope"),
        sa.CheckConstraint("status IN ('SETTLED','REVIEW','BLOCKED','INSUFFICIENT_DATA')", name="ck_m39_settlement_status"),
        sa.CheckConstraint("side IN ('BUY','SELL')", name="ck_m39_settlement_side"),
        sa.CheckConstraint("fee_lamports >= 0 AND actual_input_amount_raw >= 0 AND actual_output_amount_raw >= 0", name="ck_m39_settlement_amounts"),
        sa.CheckConstraint("length(settlement_key) = 64 AND length(evidence_hash) = 64", name="ck_m39_settlement_hashes"),
        sa.ForeignKeyConstraint(["submission_db_id"], ["canonical_parser_controlled_live_submissions.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("settlement_id", name="uq_m39_settlement_id"),
        sa.UniqueConstraint("settlement_key", name="uq_m39_settlement_key"),
        sa.UniqueConstraint("submission_db_id", name="uq_m39_settlement_submission"),
    )
    op.create_index("ix_m39_settlement_status_time", "canonical_parser_live_onchain_settlements", ["status", "settled_at"])
    op.create_index("ix_m39_settlement_wallet_token", "canonical_parser_live_onchain_settlements", ["wallet_address", "token_mint"])

    op.create_table(
        "canonical_parser_live_onchain_settlement_events",
        sa.Column("id", pk, primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("settlement_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column("previous_event_hash", sa.String(64), nullable=True),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_m39_settlement_event_sequence"),
        sa.CheckConstraint("event_type IN ('SETTLED','REVIEW','BLOCKED','INSUFFICIENT_DATA','POSITION_OPENED','POSITION_REDUCED','POSITION_CLOSED')", name="ck_m39_settlement_event_type"),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_m39_settlement_event_hash"),
        sa.ForeignKeyConstraint(["settlement_db_id"], ["canonical_parser_live_onchain_settlements.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("event_id", name="uq_m39_settlement_event_id"),
        sa.UniqueConstraint("settlement_db_id", "sequence", name="uq_m39_settlement_event_sequence"),
    )
    op.create_index("ix_m39_settlement_event_time", "canonical_parser_live_onchain_settlement_events", ["settlement_db_id", "occurred_at"])

    op.create_table(
        "canonical_parser_governed_live_positions",
        sa.Column("id", pk, primary_key=True),
        sa.Column("position_id", sa.String(36), nullable=False),
        sa.Column("position_key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(48), nullable=False),
        sa.Column("entry_settlement_db_id", pk, nullable=False),
        sa.Column("entry_settlement_id", sa.String(36), nullable=False),
        sa.Column("last_settlement_id", sa.String(36), nullable=False),
        sa.Column("micro_live_permit_id", sa.String(36), nullable=False),
        sa.Column("decision_result_id", sa.String(36), nullable=False),
        sa.Column("wallet_address", sa.String(64), nullable=False),
        sa.Column("token_mint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("quantity_raw", sa.Numeric(38, 0), nullable=False),
        sa.Column("cost_basis_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("realized_proceeds_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("realized_pnl_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("high_watermark_value_sol", sa.Numeric(20, 9), nullable=True),
        sa.Column("high_watermark_roi_percent", sa.Numeric(18, 8), nullable=True),
        sa.Column("exit_plan", sa.JSON(), nullable=False),
        sa.Column("position_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("position_version", sa.Integer(), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_assessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope = 'M39_GOVERNED_LIVE_POSITION_LEDGER'", name="ck_m39_position_scope"),
        sa.CheckConstraint("status IN ('OPEN','CLOSED','REVIEW')", name="ck_m39_position_status"),
        sa.CheckConstraint("quantity_raw >= 0 AND cost_basis_sol >= 0 AND realized_proceeds_sol >= 0", name="ck_m39_position_values"),
        sa.CheckConstraint("position_version >= 1", name="ck_m39_position_version"),
        sa.CheckConstraint("length(position_key) = 64 AND length(evidence_hash) = 64", name="ck_m39_position_hashes"),
        sa.ForeignKeyConstraint(["entry_settlement_db_id"], ["canonical_parser_live_onchain_settlements.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("position_id", name="uq_m39_position_id"),
        sa.UniqueConstraint("position_key", name="uq_m39_position_key"),
        sa.UniqueConstraint("entry_settlement_db_id", name="uq_m39_position_entry_settlement"),
    )
    op.create_index("ix_m39_position_status_token", "canonical_parser_governed_live_positions", ["status", "token_mint"])
    op.create_index("ix_m39_position_wallet_opened", "canonical_parser_governed_live_positions", ["wallet_address", "opened_at"])


def downgrade() -> None:
    op.drop_index("ix_m39_position_wallet_opened", table_name="canonical_parser_governed_live_positions")
    op.drop_index("ix_m39_position_status_token", table_name="canonical_parser_governed_live_positions")
    op.drop_table("canonical_parser_governed_live_positions")
    op.drop_index("ix_m39_settlement_event_time", table_name="canonical_parser_live_onchain_settlement_events")
    op.drop_table("canonical_parser_live_onchain_settlement_events")
    op.drop_index("ix_m39_settlement_wallet_token", table_name="canonical_parser_live_onchain_settlements")
    op.drop_index("ix_m39_settlement_status_time", table_name="canonical_parser_live_onchain_settlements")
    op.drop_table("canonical_parser_live_onchain_settlements")
