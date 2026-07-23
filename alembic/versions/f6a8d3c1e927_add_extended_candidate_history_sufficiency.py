"""add extended candidate history and data sufficiency

Revision ID: f6a8d3c1e927
Revises: e4b7c2a9d815
Create Date: 2026-07-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "f6a8d3c1e927"
down_revision: str | None = "e4b7c2a9d815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    extended_history_columns = (
        sa.Column(
            "extended_history_status",
            sa.String(length=24),
            server_default="NEVER",
            nullable=False,
        ),
        sa.Column("extended_history_run_id", sa.String(length=36), nullable=True),
        sa.Column(
            "extended_history_last_attempt_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "extended_history_last_success_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "extended_history_lookback_days",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "extended_history_request_budget",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "extended_history_helius_requests",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "extended_history_pages_fetched",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "extended_history_transactions_found",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "extended_history_swaps_found",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "extended_history_trades_imported",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "extended_history_trades_updated",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "extended_history_parse_failures",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "extended_history_oldest_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "extended_history_newest_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("extended_history_stop_reason", sa.String(length=64), nullable=True),
        sa.Column("extended_history_error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "extended_history_error_message", sa.String(length=500), nullable=True
        ),
        sa.Column(
            "backtest_data_sufficient",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "backtest_data_sufficiency_score",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "backtest_data_sufficiency_reasons",
            sa.JSON(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "backtest_history_span_days",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "backtest_bootstrap_positions",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "backtest_matched_sell_ratio_percent",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
    )
    for column in extended_history_columns:
        op.add_column("discovered_wallets", column)

    op.create_index(
        "ix_discovered_wallets_extended_history_status",
        "discovered_wallets",
        ["extended_history_status"],
        unique=False,
    )
    op.create_index(
        "ix_discovered_wallets_extended_history_run_id",
        "discovered_wallets",
        ["extended_history_run_id"],
        unique=False,
    )
    op.create_index(
        "ix_discovered_wallets_extended_history_last_attempt_at",
        "discovered_wallets",
        ["extended_history_last_attempt_at"],
        unique=False,
    )
    op.create_index(
        "ix_discovered_wallets_backtest_data_sufficient",
        "discovered_wallets",
        ["backtest_data_sufficient"],
        unique=False,
    )

    op.add_column(
        "live_wallet_scores",
        sa.Column(
            "backtest_data_sufficient",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "live_wallet_scores",
        sa.Column(
            "backtest_data_sufficiency_score",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
    )

    candidate_backtest_columns = (
        sa.Column(
            "warmup_source_trades", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "analysis_source_trades", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "bootstrap_positions", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "bootstrap_positions_closed",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "matched_sell_ratio_percent",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "open_position_ratio_percent",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "history_span_days", sa.Float(), server_default="0", nullable=False
        ),
        sa.Column(
            "effective_starting_equity_sol",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "data_sufficient",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column(
            "data_sufficiency_score",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "data_sufficiency_reasons",
            sa.JSON(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("history_oldest_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("history_newest_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "jupiter_cache_hits", sa.Integer(), server_default="0", nullable=False
        ),
        sa.Column(
            "jupiter_live_checks", sa.Integer(), server_default="0", nullable=False
        ),
    )
    for column in candidate_backtest_columns:
        op.add_column("candidate_backtest_runs", column)
    op.create_index(
        "ix_candidate_backtest_runs_data_sufficient",
        "candidate_backtest_runs",
        ["data_sufficient"],
        unique=False,
    )

    op.create_table(
        "candidate_history_backfill_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("wallet_address", sa.String(length=64), nullable=False),
        sa.Column(
            "status", sa.String(length=24), nullable=False, server_default="COMPLETED"
        ),
        sa.Column(
            "stop_reason",
            sa.String(length=64),
            nullable=False,
            server_default="COMPLETED",
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column(
            "requested_lookback_days",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
        sa.Column("page_size", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("request_budget", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("helius_requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pages_fetched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "transactions_found", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("swaps_found", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("trades_imported", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("trades_updated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("parse_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "duplicate_transactions", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "oldest_transaction_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "newest_transaction_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("next_before_signature", sa.String(length=128), nullable=True),
        sa.Column("parameters", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("safety", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "run_id", name="uq_candidate_history_backfill_runs_run_id"
        ),
    )
    op.create_index(
        "ix_candidate_history_backfill_runs_run_id",
        "candidate_history_backfill_runs",
        ["run_id"],
        unique=True,
    )
    op.create_index(
        "ix_candidate_history_backfill_runs_wallet_address",
        "candidate_history_backfill_runs",
        ["wallet_address"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_history_backfill_runs_status",
        "candidate_history_backfill_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_history_backfill_runs_started_at",
        "candidate_history_backfill_runs",
        ["started_at"],
        unique=False,
    )

    op.create_table(
        "candidate_token_compatibilities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("token_mint", sa.String(length=64), nullable=False),
        sa.Column("fixed_buy_size_lamports", sa.BigInteger(), nullable=False),
        sa.Column("slippage_bps", sa.Integer(), nullable=False),
        sa.Column(
            "status", sa.String(length=24), nullable=False, server_default="FAILED"
        ),
        sa.Column("buy_quote", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sell_quote", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("compatible", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("buy_out_amount_raw", sa.BigInteger(), nullable=True),
        sa.Column("sell_out_amount_raw", sa.BigInteger(), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column(
            "checked_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "token_mint",
            "fixed_buy_size_lamports",
            "slippage_bps",
            name="uq_candidate_token_compatibility_quote_profile",
        ),
    )
    op.create_index(
        "ix_candidate_token_compatibilities_token_mint",
        "candidate_token_compatibilities",
        ["token_mint"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_token_compatibilities_status",
        "candidate_token_compatibilities",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_token_compatibilities_compatible",
        "candidate_token_compatibilities",
        ["compatible"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_token_compatibilities_checked_at",
        "candidate_token_compatibilities",
        ["checked_at"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_token_compatibilities_expires_at",
        "candidate_token_compatibilities",
        ["expires_at"],
        unique=False,
    )

    # Fail closed: every wallet must pass the new data sufficiency gate again.
    op.execute(
        "UPDATE discovered_wallets SET eligible = false, "
        "promotion_eligible = false, backtest_data_sufficient = false, "
        "promotion_status = CASE "
        "WHEN quality_classification = 'COPIABILE' "
        "THEN 'DATI_INSUFFICIENTI' ELSE promotion_status END"
    )
    op.execute(
        "UPDATE live_wallet_scores SET eligible = false, "
        "promotion_eligible = false, backtest_data_sufficient = false, "
        "promotion_status = CASE "
        "WHEN quality_classification = 'COPIABILE' "
        "THEN 'DATI_INSUFFICIENTI' ELSE promotion_status END"
    )


def downgrade() -> None:
    for index_name in (
        "ix_candidate_token_compatibilities_expires_at",
        "ix_candidate_token_compatibilities_checked_at",
        "ix_candidate_token_compatibilities_compatible",
        "ix_candidate_token_compatibilities_status",
        "ix_candidate_token_compatibilities_token_mint",
    ):
        op.drop_index(index_name, table_name="candidate_token_compatibilities")
    op.drop_table("candidate_token_compatibilities")

    for index_name in (
        "ix_candidate_history_backfill_runs_started_at",
        "ix_candidate_history_backfill_runs_status",
        "ix_candidate_history_backfill_runs_wallet_address",
        "ix_candidate_history_backfill_runs_run_id",
    ):
        op.drop_index(index_name, table_name="candidate_history_backfill_runs")
    op.drop_table("candidate_history_backfill_runs")

    op.drop_index(
        "ix_candidate_backtest_runs_data_sufficient",
        table_name="candidate_backtest_runs",
    )
    for column_name in (
        "jupiter_live_checks",
        "jupiter_cache_hits",
        "history_newest_at",
        "history_oldest_at",
        "data_sufficiency_reasons",
        "data_sufficiency_score",
        "data_sufficient",
        "effective_starting_equity_sol",
        "history_span_days",
        "open_position_ratio_percent",
        "matched_sell_ratio_percent",
        "bootstrap_positions_closed",
        "bootstrap_positions",
        "analysis_source_trades",
        "warmup_source_trades",
    ):
        op.drop_column("candidate_backtest_runs", column_name)

    op.drop_column("live_wallet_scores", "backtest_data_sufficiency_score")
    op.drop_column("live_wallet_scores", "backtest_data_sufficient")

    op.drop_index(
        "ix_discovered_wallets_backtest_data_sufficient",
        table_name="discovered_wallets",
    )
    op.drop_index(
        "ix_discovered_wallets_extended_history_last_attempt_at",
        table_name="discovered_wallets",
    )
    op.drop_index(
        "ix_discovered_wallets_extended_history_run_id",
        table_name="discovered_wallets",
    )
    op.drop_index(
        "ix_discovered_wallets_extended_history_status",
        table_name="discovered_wallets",
    )
    for column_name in (
        "backtest_matched_sell_ratio_percent",
        "backtest_bootstrap_positions",
        "backtest_history_span_days",
        "backtest_data_sufficiency_reasons",
        "backtest_data_sufficiency_score",
        "backtest_data_sufficient",
        "extended_history_error_message",
        "extended_history_error_code",
        "extended_history_stop_reason",
        "extended_history_newest_at",
        "extended_history_oldest_at",
        "extended_history_parse_failures",
        "extended_history_trades_updated",
        "extended_history_trades_imported",
        "extended_history_swaps_found",
        "extended_history_transactions_found",
        "extended_history_pages_fetched",
        "extended_history_helius_requests",
        "extended_history_request_budget",
        "extended_history_lookback_days",
        "extended_history_last_success_at",
        "extended_history_last_attempt_at",
        "extended_history_run_id",
        "extended_history_status",
    ):
        op.drop_column("discovered_wallets", column_name)
