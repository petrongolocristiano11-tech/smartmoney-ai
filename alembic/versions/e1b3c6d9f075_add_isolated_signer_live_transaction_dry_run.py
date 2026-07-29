"""add isolated signer live transaction dry run

Revision ID: e1b3c6d9f075
Revises: d0a2b5c8e964
Create Date: 2026-07-29 00:30:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "e1b3c6d9f075"
down_revision: str | Sequence[str] | None = "d0a2b5c8e964"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")

    op.create_table(
        "canonical_parser_isolated_signer_profiles",
        sa.Column("id", pk, primary_key=True),
        sa.Column("profile_id", sa.String(36), nullable=False),
        sa.Column("profile_key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(48), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("wallet_address", sa.String(64), nullable=False),
        sa.Column("network", sa.String(24), nullable=False),
        sa.Column("allowed_program_ids", sa.JSON(), nullable=False),
        sa.Column("max_transaction_bytes", sa.Integer(), nullable=False),
        sa.Column("max_required_signers", sa.Integer(), nullable=False),
        sa.Column("allow_address_lookup_tables", sa.Boolean(), nullable=False),
        sa.Column("validity_minutes", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(80), nullable=False),
        sa.Column("policy_hash", sa.String(64), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
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
        sa.CheckConstraint("scope = 'M36_ISOLATED_SIGNER_DRY_RUN_ONLY'", name="ck_m36_signer_profile_scope"),
        sa.CheckConstraint("status IN ('ACTIVE','REVOKED','EXPIRED')", name="ck_m36_signer_profile_status"),
        sa.CheckConstraint("network = 'mainnet-beta'", name="ck_m36_signer_profile_network"),
        sa.CheckConstraint("validity_minutes >= 1 AND max_transaction_bytes >= 1 AND max_required_signers >= 1", name="ck_m36_signer_profile_limits"),
        sa.CheckConstraint("latest_event_sequence >= 1", name="ck_m36_signer_profile_event_sequence"),
        sa.CheckConstraint("length(profile_key) = 64 AND length(policy_hash) = 64 AND length(latest_event_hash) = 64", name="ck_m36_signer_profile_hashes"),
        sa.UniqueConstraint("profile_id", name="uq_m36_signer_profile_id"),
        sa.UniqueConstraint("profile_key", name="uq_m36_signer_profile_key"),
    )
    op.create_index(
        "ix_m36_signer_profile_status_expiry",
        "canonical_parser_isolated_signer_profiles",
        ["status", "expires_at"],
    )

    op.create_table(
        "canonical_parser_isolated_signer_profile_events",
        sa.Column("id", pk, primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("profile_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column("previous_event_hash", sa.String(64), nullable=True),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_m36_signer_event_sequence"),
        sa.CheckConstraint("event_type IN ('ISSUED','REVOKED','EXPIRED')", name="ck_m36_signer_event_type"),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_m36_signer_event_hash"),
        sa.ForeignKeyConstraint(["profile_db_id"], ["canonical_parser_isolated_signer_profiles.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("event_id", name="uq_m36_signer_event_id"),
        sa.UniqueConstraint("profile_db_id", "sequence", name="uq_m36_signer_event_sequence"),
    )
    op.create_index(
        "ix_m36_signer_event_profile_time",
        "canonical_parser_isolated_signer_profile_events",
        ["profile_db_id", "occurred_at"],
    )

    op.create_table(
        "canonical_parser_live_transaction_dry_runs",
        sa.Column("id", pk, primary_key=True),
        sa.Column("dry_run_id", sa.String(36), nullable=False),
        sa.Column("dry_run_key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(40), nullable=False),
        sa.Column("signer_profile_db_id", pk, nullable=False),
        sa.Column("signer_profile_id", sa.String(36), nullable=False),
        sa.Column("micro_live_simulation_db_id", pk, nullable=False),
        sa.Column("micro_live_simulation_id", sa.String(36), nullable=False),
        sa.Column("micro_live_permit_id", sa.String(36), nullable=False),
        sa.Column("decision_result_id", sa.String(36), nullable=False),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("transaction_source", sa.String(32), nullable=False),
        sa.Column("transaction_format", sa.String(12), nullable=False),
        sa.Column("token_mint", sa.String(64), nullable=False),
        sa.Column("input_mint", sa.String(64), nullable=False),
        sa.Column("output_mint", sa.String(64), nullable=False),
        sa.Column("amount_raw", sa.Numeric(40, 0), nullable=False),
        sa.Column("requested_budget_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("transaction_size_bytes", sa.Integer(), nullable=False),
        sa.Column("signature_slot_count", sa.Integer(), nullable=False),
        sa.Column("required_signer_count", sa.Integer(), nullable=False),
        sa.Column("static_account_count", sa.Integer(), nullable=False),
        sa.Column("instruction_count", sa.Integer(), nullable=False),
        sa.Column("address_lookup_count", sa.Integer(), nullable=False),
        sa.Column("required_signers", sa.JSON(), nullable=False),
        sa.Column("program_ids", sa.JSON(), nullable=False),
        sa.Column("writable_accounts", sa.JSON(), nullable=False),
        sa.Column("transaction_hash", sa.String(64), nullable=False),
        sa.Column("message_hash", sa.String(64), nullable=False),
        sa.Column("account_keys_hash", sa.String(64), nullable=False),
        sa.Column("jupiter_request_id", sa.String(160), nullable=True),
        sa.Column("jupiter_router", sa.String(160), nullable=True),
        sa.Column("jupiter_price_impact_percent", sa.Numeric(12, 6), nullable=True),
        sa.Column("jupiter_slippage_bps", sa.Integer(), nullable=True),
        sa.Column("rpc_simulation_status", sa.String(20), nullable=False),
        sa.Column("units_consumed", sa.Integer(), nullable=True),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("inspection_snapshot", sa.JSON(), nullable=False),
        sa.Column("rpc_simulation_snapshot", sa.JSON(), nullable=False),
        sa.Column("signing_envelope", sa.JSON(), nullable=False),
        sa.Column("signing_envelope_hash", sa.String(64), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("envelope_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope = 'M36_PRE_SIGN_DRY_RUN_ONLY'", name="ck_m36_dry_run_scope"),
        sa.CheckConstraint("status IN ('READY','REVIEW','BLOCKED','INSUFFICIENT_DATA')", name="ck_m36_dry_run_status"),
        sa.CheckConstraint("transaction_source IN ('JUPITER_ORDER','PROVIDED_TRANSACTION')", name="ck_m36_dry_run_source"),
        sa.CheckConstraint("transaction_format IN ('LEGACY','V0')", name="ck_m36_dry_run_format"),
        sa.CheckConstraint("side IN ('BUY','SELL')", name="ck_m36_dry_run_side"),
        sa.CheckConstraint("rpc_simulation_status IN ('PASSED','FAILED','SKIPPED','UNAVAILABLE')", name="ck_m36_dry_run_rpc_status"),
        sa.CheckConstraint("transaction_size_bytes > 0 AND signature_slot_count >= 0 AND required_signer_count >= 1 AND static_account_count >= 1 AND instruction_count >= 1 AND address_lookup_count >= 0", name="ck_m36_dry_run_counts"),
        sa.CheckConstraint("amount_raw > 0 AND requested_budget_sol >= 0", name="ck_m36_dry_run_values"),
        sa.CheckConstraint("jupiter_slippage_bps IS NULL OR jupiter_slippage_bps >= 0", name="ck_m36_dry_run_slippage"),
        sa.CheckConstraint("length(dry_run_key) = 64 AND length(transaction_hash) = 64 AND length(message_hash) = 64 AND length(account_keys_hash) = 64 AND length(signing_envelope_hash) = 64 AND length(evidence_hash) = 64", name="ck_m36_dry_run_hashes"),
        sa.ForeignKeyConstraint(["signer_profile_db_id"], ["canonical_parser_isolated_signer_profiles.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["micro_live_simulation_db_id"], ["canonical_parser_micro_live_canary_simulations.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("dry_run_id", name="uq_m36_dry_run_id"),
        sa.UniqueConstraint("dry_run_key", name="uq_m36_dry_run_key"),
    )
    op.create_index(
        "ix_m36_dry_run_status_prepared",
        "canonical_parser_live_transaction_dry_runs",
        ["status", "prepared_at"],
    )
    op.create_index(
        "ix_m36_dry_run_profile_prepared",
        "canonical_parser_live_transaction_dry_runs",
        ["signer_profile_db_id", "prepared_at"],
    )
    op.create_index(
        "ix_m36_dry_run_simulation",
        "canonical_parser_live_transaction_dry_runs",
        ["micro_live_simulation_db_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_m36_dry_run_simulation", table_name="canonical_parser_live_transaction_dry_runs")
    op.drop_index("ix_m36_dry_run_profile_prepared", table_name="canonical_parser_live_transaction_dry_runs")
    op.drop_index("ix_m36_dry_run_status_prepared", table_name="canonical_parser_live_transaction_dry_runs")
    op.drop_table("canonical_parser_live_transaction_dry_runs")
    op.drop_index("ix_m36_signer_event_profile_time", table_name="canonical_parser_isolated_signer_profile_events")
    op.drop_table("canonical_parser_isolated_signer_profile_events")
    op.drop_index("ix_m36_signer_profile_status_expiry", table_name="canonical_parser_isolated_signer_profiles")
    op.drop_table("canonical_parser_isolated_signer_profiles")
