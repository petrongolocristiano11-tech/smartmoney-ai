"""add Gen4 real-time copyability validation

Revision ID: b6f8d2e4c731
Revises: a5e7c1d4b926
Create Date: 2026-08-03 20:15:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "b6f8d2e4c731"
down_revision: str | None = "a5e7c1d4b926"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "canonical_parser_gen4_copyability_campaigns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("forward_campaign_db_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("verdict", sa.String(length=40), nullable=False),
        sa.Column("policy_version", sa.String(length=120), nullable=False),
        sa.Column("policy_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("frozen_wallets", sa.JSON(), nullable=False),
        sa.Column("anchor_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("minimum_complete_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latest_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("minimum_observation_days", sa.Integer(), nullable=False),
        sa.Column("minimum_closed_trades", sa.Integer(), nullable=False),
        sa.Column("proof_closed_trades", sa.Integer(), nullable=False),
        sa.Column("simulated_input_lamports", sa.BigInteger(), nullable=False),
        sa.Column("slippage_bps", sa.Integer(), nullable=False),
        sa.Column("max_signal_age_ms", sa.Integer(), nullable=False),
        sa.Column("max_quote_latency_ms", sa.Integer(), nullable=False),
        sa.Column("max_price_impact_bps", sa.Integer(), nullable=False),
        sa.Column("max_price_deterioration_bps", sa.Integer(), nullable=False),
        sa.Column("estimated_network_fee_lamports", sa.BigInteger(), nullable=False),
        sa.Column("minimum_webhook_coverage_percent", sa.Float(), nullable=False),
        sa.Column("minimum_profit_factor", sa.Float(), nullable=False),
        sa.Column("maximum_drawdown_percent", sa.Float(), nullable=False),
        sa.Column("webhook_id", sa.String(length=80), nullable=True),
        sa.Column("webhook_status", sa.String(length=24), nullable=True),
        sa.Column("webhook_url", sa.String(length=500), nullable=True),
        sa.Column("webhook_configured_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_webhook_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("receipt_count", sa.Integer(), nullable=False),
        sa.Column("duplicate_receipt_count", sa.Integer(), nullable=False),
        sa.Column("recovery_receipt_count", sa.Integer(), nullable=False),
        sa.Column("processed_receipt_count", sa.Integer(), nullable=False),
        sa.Column("failed_receipt_count", sa.Integer(), nullable=False),
        sa.Column("ignored_receipt_count", sa.Integer(), nullable=False),
        sa.Column("buy_signal_count", sa.Integer(), nullable=False),
        sa.Column("sell_signal_count", sa.Integer(), nullable=False),
        sa.Column("executable_entry_count", sa.Integer(), nullable=False),
        sa.Column("rejected_entry_count", sa.Integer(), nullable=False),
        sa.Column("open_position_count", sa.Integer(), nullable=False),
        sa.Column("closed_trade_count", sa.Integer(), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("evidence_gaps", sa.JSON(), nullable=False),
        sa.Column("safety", sa.JSON(), nullable=False),
        sa.Column("actor_label", sa.String(length=80), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("technical_metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE','PAUSED','COMPLETED','FAILED')",
            name="ck_gen4_copy_campaign_status",
        ),
        sa.CheckConstraint(
            "verdict IN ('COLLECTING','NOT_EVALUABLE','NEGATIVE_EVIDENCE',"
            "'PROMISING_NOT_PROVEN','PROFITABLE_EVIDENCE')",
            name="ck_gen4_copy_campaign_verdict",
        ),
        sa.CheckConstraint(
            "minimum_observation_days >= 1 AND minimum_closed_trades >= 1 "
            "AND proof_closed_trades >= minimum_closed_trades",
            name="ck_gen4_copy_campaign_thresholds",
        ),
        sa.CheckConstraint(
            "simulated_input_lamports > 0 AND slippage_bps BETWEEN 1 AND 10000 "
            "AND max_signal_age_ms >= 1000 AND max_quote_latency_ms >= 100 "
            "AND max_price_impact_bps BETWEEN 1 AND 10000 "
            "AND max_price_deterioration_bps BETWEEN 1 AND 50000 "
            "AND estimated_network_fee_lamports >= 0",
            name="ck_gen4_copy_campaign_policy",
        ),
        sa.CheckConstraint(
            "receipt_count >= 0 AND duplicate_receipt_count >= 0 "
            "AND recovery_receipt_count >= 0 AND processed_receipt_count >= 0 "
            "AND failed_receipt_count >= 0 AND ignored_receipt_count >= 0 "
            "AND buy_signal_count >= 0 AND sell_signal_count >= 0 "
            "AND executable_entry_count >= 0 AND rejected_entry_count >= 0 "
            "AND open_position_count >= 0 AND closed_trade_count >= 0",
            name="ck_gen4_copy_campaign_counts",
        ),
        sa.ForeignKeyConstraint(
            ["forward_campaign_db_id"],
            ["canonical_parser_gen4_forward_campaigns.id"],
            ondelete="CASCADE",
            name="fk_gen4_copy_campaign_forward",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", name="uq_gen4_copy_campaign_id"),
        sa.UniqueConstraint(
            "forward_campaign_db_id", name="uq_gen4_copy_campaign_forward"
        ),
    )
    op.create_index(
        "ix_gen4_copy_campaign_status_anchor",
        "canonical_parser_gen4_copyability_campaigns",
        ["status", "anchor_at"],
    )
    op.create_index(
        "ix_gen4_copy_campaign_verdict_updated",
        "canonical_parser_gen4_copyability_campaigns",
        ["verdict", "updated_at"],
    )

    op.create_table(
        "canonical_parser_gen4_webhook_receipts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("receipt_id", sa.String(length=36), nullable=False),
        sa.Column("campaign_db_id", sa.Integer(), nullable=False),
        sa.Column("signature", sa.String(length=128), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("auth_verified", sa.Boolean(), nullable=False),
        sa.Column("wallet_address", sa.String(length=64), nullable=True),
        sa.Column("matched_wallets", sa.JSON(), nullable=False),
        sa.Column("slot", sa.BigInteger(), nullable=True),
        sa.Column("block_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_count", sa.Integer(), nullable=False),
        sa.Column("processing_attempts", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=96), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("parsed_summary", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "source IN ('WEBHOOK','RECOVERY_ONLY')",
            name="ck_gen4_copy_receipt_source",
        ),
        sa.CheckConstraint(
            "status IN ('RECEIVED','PROCESSING','PROCESSED','IGNORED','FAILED',"
            "'EXCLUDED_RECOVERY')",
            name="ck_gen4_copy_receipt_status",
        ),
        sa.CheckConstraint(
            "delivery_count >= 1 AND processing_attempts >= 0",
            name="ck_gen4_copy_receipt_counts",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_db_id"],
            ["canonical_parser_gen4_copyability_campaigns.id"],
            ondelete="CASCADE",
            name="fk_gen4_copy_receipt_campaign",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("receipt_id", name="uq_gen4_copy_receipt_id"),
        sa.UniqueConstraint(
            "campaign_db_id", "signature", name="uq_gen4_copy_receipt_signature"
        ),
    )
    op.create_index(
        "ix_gen4_copy_receipt_status_received",
        "canonical_parser_gen4_webhook_receipts",
        ["status", "received_at"],
    )
    op.create_index(
        "ix_gen4_copy_receipt_campaign_wallet",
        "canonical_parser_gen4_webhook_receipts",
        ["campaign_db_id", "wallet_address"],
    )
    op.create_index(
        "ix_gen4_copy_receipt_signature",
        "canonical_parser_gen4_webhook_receipts",
        ["signature"],
    )

    op.create_table(
        "canonical_parser_gen4_copyability_positions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("position_id", sa.String(length=36), nullable=False),
        sa.Column("campaign_db_id", sa.Integer(), nullable=False),
        sa.Column("entry_receipt_db_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("wallet_address", sa.String(length=64), nullable=False),
        sa.Column("token_mint", sa.String(length=64), nullable=False),
        sa.Column("token_decimals", sa.Integer(), nullable=False),
        sa.Column("entry_signature", sa.String(length=128), nullable=False),
        sa.Column("entry_source", sa.String(length=20), nullable=False),
        sa.Column("entry_signal_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_quote_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entry_quote_received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("chain_age_ms", sa.Integer(), nullable=True),
        sa.Column("entry_quote_latency_ms", sa.Integer(), nullable=True),
        sa.Column("entry_end_to_quote_ms", sa.Integer(), nullable=True),
        sa.Column("entry_price_deterioration_bps", sa.Float(), nullable=True),
        sa.Column("entry_price_impact_bps", sa.Float(), nullable=True),
        sa.Column("entry_transaction_built", sa.Boolean(), nullable=False),
        sa.Column("entry_copyable", sa.Boolean(), nullable=False),
        sa.Column("entry_rejection_reason", sa.String(length=120), nullable=True),
        sa.Column("wallet_token_delta_raw", sa.BigInteger(), nullable=True),
        sa.Column("wallet_sol_equivalent_delta_lamports", sa.BigInteger(), nullable=True),
        sa.Column("wallet_effective_price_sol", sa.Float(), nullable=True),
        sa.Column("entry_input_lamports", sa.BigInteger(), nullable=False),
        sa.Column("entry_output_token_raw", sa.BigInteger(), nullable=False),
        sa.Column("remaining_token_raw", sa.BigInteger(), nullable=False),
        sa.Column("realized_output_lamports", sa.BigInteger(), nullable=False),
        sa.Column("allocated_entry_fee_lamports", sa.BigInteger(), nullable=False),
        sa.Column("allocated_exit_fee_lamports", sa.BigInteger(), nullable=False),
        sa.Column("pnl_lamports", sa.BigInteger(), nullable=True),
        sa.Column("return_percent", sa.Float(), nullable=True),
        sa.Column("close_reason", sa.String(length=80), nullable=True),
        sa.Column("exit_source", sa.String(length=20), nullable=True),
        sa.Column("last_exit_signature", sa.String(length=128), nullable=True),
        sa.Column("exit_quote_latency_ms", sa.Integer(), nullable=True),
        sa.Column("exit_price_impact_bps", sa.Float(), nullable=True),
        sa.Column("exit_transaction_built", sa.Boolean(), nullable=False),
        sa.Column("exit_copyable", sa.Boolean(), nullable=False),
        sa.Column("entry_quote", sa.JSON(), nullable=False),
        sa.Column("exit_quotes", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('OPEN','OPEN_PARTIAL','CLOSED','REJECTED')",
            name="ck_gen4_copy_position_status",
        ),
        sa.CheckConstraint(
            "entry_source IN ('WEBHOOK','RECOVERY_ONLY')",
            name="ck_gen4_copy_position_source",
        ),
        sa.CheckConstraint(
            "entry_input_lamports >= 0 AND entry_output_token_raw >= 0 "
            "AND remaining_token_raw >= 0 AND realized_output_lamports >= 0",
            name="ck_gen4_copy_position_amounts",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_db_id"],
            ["canonical_parser_gen4_copyability_campaigns.id"],
            ondelete="CASCADE",
            name="fk_gen4_copy_position_campaign",
        ),
        sa.ForeignKeyConstraint(
            ["entry_receipt_db_id"],
            ["canonical_parser_gen4_webhook_receipts.id"],
            ondelete="CASCADE",
            name="fk_gen4_copy_position_receipt",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("position_id", name="uq_gen4_copy_position_id"),
        sa.UniqueConstraint(
            "campaign_db_id",
            "entry_signature",
            name="uq_gen4_copy_position_entry_signature",
        ),
    )
    op.create_index(
        "ix_gen4_copy_position_open_wallet_token",
        "canonical_parser_gen4_copyability_positions",
        ["status", "wallet_address", "token_mint"],
    )
    op.create_index(
        "ix_gen4_copy_position_closed_at",
        "canonical_parser_gen4_copyability_positions",
        ["closed_at"],
    )

    op.create_table(
        "canonical_parser_gen4_copyability_worker_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("state_id", sa.String(length=36), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("poll_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("batch_size", sa.Integer(), nullable=False),
        sa.Column("lease_owner", sa.String(length=120), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_iteration_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_iteration_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=24), nullable=True),
        sa.Column("last_error_code", sa.String(length=96), nullable=True),
        sa.Column("last_error_message", sa.String(length=500), nullable=True),
        sa.Column("total_iterations", sa.Integer(), nullable=False),
        sa.Column("total_receipts_processed", sa.Integer(), nullable=False),
        sa.Column("total_quotes", sa.Integer(), nullable=False),
        sa.Column("total_failures", sa.Integer(), nullable=False),
        sa.Column("technical_metadata", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "poll_interval_seconds BETWEEN 1 AND 60 AND batch_size BETWEEN 1 AND 100",
            name="ck_gen4_copy_worker_policy",
        ),
        sa.CheckConstraint(
            "total_iterations >= 0 AND total_receipts_processed >= 0 "
            "AND total_quotes >= 0 AND total_failures >= 0",
            name="ck_gen4_copy_worker_counts",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_id", name="uq_gen4_copy_worker_state_id"),
    )
    op.create_index(
        "ix_gen4_copy_worker_lease",
        "canonical_parser_gen4_copyability_worker_states",
        ["lease_expires_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    protected_tables = (
        "canonical_parser_gen4_copyability_positions",
        "canonical_parser_gen4_webhook_receipts",
        "canonical_parser_gen4_copyability_campaigns",
    )
    for table_name in protected_tables:
        count = bind.execute(sa.text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()
        if int(count or 0) > 0:
            raise RuntimeError(
                "Downgrade M58-M60 rifiutato: esistono evidenze real-time copyability. "
                "Esportarle e rimuoverle esplicitamente prima del downgrade."
            )

    op.drop_index(
        "ix_gen4_copy_worker_lease",
        table_name="canonical_parser_gen4_copyability_worker_states",
    )
    op.drop_table("canonical_parser_gen4_copyability_worker_states")
    op.drop_index(
        "ix_gen4_copy_position_closed_at",
        table_name="canonical_parser_gen4_copyability_positions",
    )
    op.drop_index(
        "ix_gen4_copy_position_open_wallet_token",
        table_name="canonical_parser_gen4_copyability_positions",
    )
    op.drop_table("canonical_parser_gen4_copyability_positions")
    op.drop_index(
        "ix_gen4_copy_receipt_signature",
        table_name="canonical_parser_gen4_webhook_receipts",
    )
    op.drop_index(
        "ix_gen4_copy_receipt_campaign_wallet",
        table_name="canonical_parser_gen4_webhook_receipts",
    )
    op.drop_index(
        "ix_gen4_copy_receipt_status_received",
        table_name="canonical_parser_gen4_webhook_receipts",
    )
    op.drop_table("canonical_parser_gen4_webhook_receipts")
    op.drop_index(
        "ix_gen4_copy_campaign_verdict_updated",
        table_name="canonical_parser_gen4_copyability_campaigns",
    )
    op.drop_index(
        "ix_gen4_copy_campaign_status_anchor",
        table_name="canonical_parser_gen4_copyability_campaigns",
    )
    op.drop_table("canonical_parser_gen4_copyability_campaigns")
