"""add candidate backtest promotion gate

Revision ID: e4b7c2a9d815
Revises: c9e4a7f2d631
Create Date: 2026-07-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "e4b7c2a9d815"
down_revision: str | None = "c9e4a7f2d631"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    discovered_columns = (
        sa.Column(
            "promotion_status",
            sa.String(length=24),
            server_default="NON_ANALIZZATO",
            nullable=False,
        ),
        sa.Column(
            "promotion_eligible",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("promotion_reasons", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("promotion_calculated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_backtest_run_id", sa.String(length=36), nullable=True),
        sa.Column("backtest_score", sa.Float(), server_default="0", nullable=False),
        sa.Column(
            "backtest_total_return_percent", sa.Float(), server_default="0", nullable=False
        ),
        sa.Column("backtest_net_pnl_sol", sa.Float(), server_default="0", nullable=False),
        sa.Column(
            "backtest_win_rate_percent", sa.Float(), server_default="0", nullable=False
        ),
        sa.Column("backtest_profit_factor", sa.Float(), nullable=True),
        sa.Column(
            "backtest_max_drawdown_percent",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "backtest_completed_positions",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "backtest_open_positions",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "backtest_execution_coverage_percent",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "backtest_jupiter_status",
            sa.String(length=24),
            server_default="NOT_CHECKED",
            nullable=False,
        ),
        sa.Column(
            "backtest_jupiter_compatibility_percent",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
    )
    for column in discovered_columns:
        op.add_column("discovered_wallets", column)

    op.create_index(
        "ix_discovered_wallets_promotion_status",
        "discovered_wallets",
        ["promotion_status"],
        unique=False,
    )
    op.create_index(
        "ix_discovered_wallets_promotion_eligible",
        "discovered_wallets",
        ["promotion_eligible"],
        unique=False,
    )
    op.create_index(
        "ix_discovered_wallets_latest_backtest_run_id",
        "discovered_wallets",
        ["latest_backtest_run_id"],
        unique=False,
    )
    op.execute("UPDATE discovered_wallets SET eligible = false")

    live_columns = (
        sa.Column(
            "promotion_status",
            sa.String(length=24),
            server_default="NON_ANALIZZATO",
            nullable=False,
        ),
        sa.Column(
            "promotion_eligible",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("backtest_score", sa.Float(), server_default="0", nullable=False),
        sa.Column(
            "backtest_total_return_percent", sa.Float(), server_default="0", nullable=False
        ),
        sa.Column("backtest_profit_factor", sa.Float(), nullable=True),
        sa.Column(
            "backtest_max_drawdown_percent",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "backtest_jupiter_status",
            sa.String(length=24),
            server_default="NOT_CHECKED",
            nullable=False,
        ),
    )
    for column in live_columns:
        op.add_column("live_wallet_scores", column)
    op.create_index(
        "ix_live_wallet_scores_promotion_status",
        "live_wallet_scores",
        ["promotion_status"],
        unique=False,
    )
    op.execute("UPDATE live_wallet_scores SET eligible = false")

    op.create_table(
        "candidate_backtest_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("wallet_address", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="COMPLETED"),
        sa.Column(
            "decision", sa.String(length=24), nullable=False, server_default="NON_ANALIZZATO"
        ),
        sa.Column("score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reasons", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("parameters", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("safety", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("source_trades", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("valid_priced_trades", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("buy_signals", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sell_signals", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("executed_buys", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_positions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("winning_positions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("losing_positions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("breakeven_positions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("open_positions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_invalid", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "skipped_existing_position", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("skipped_max_positions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "skipped_insufficient_capital", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("unmatched_sells", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unique_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("starting_capital_sol", sa.Float(), nullable=False, server_default="0"),
        sa.Column("ending_equity_sol", sa.Float(), nullable=False, server_default="0"),
        sa.Column("realized_pnl_sol", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unrealized_pnl_sol", sa.Float(), nullable=False, server_default="0"),
        sa.Column("net_pnl_sol", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_return_percent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("win_rate_percent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("profit_factor", sa.Float(), nullable=True),
        sa.Column("max_drawdown_percent", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "execution_coverage_percent", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column("jupiter_checked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "jupiter_status", sa.String(length=24), nullable=False, server_default="NOT_CHECKED"
        ),
        sa.Column("jupiter_tokens_checked", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "jupiter_tokens_compatible", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("jupiter_requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "jupiter_compatibility_percent", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column("jupiter_results", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("position_results", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("run_id", name="uq_candidate_backtest_runs_run_id"),
    )
    op.create_index(
        "ix_candidate_backtest_runs_run_id", "candidate_backtest_runs", ["run_id"], unique=True
    )
    op.create_index(
        "ix_candidate_backtest_runs_wallet_address",
        "candidate_backtest_runs",
        ["wallet_address"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_backtest_runs_decision",
        "candidate_backtest_runs",
        ["decision"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_backtest_runs_status",
        "candidate_backtest_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_backtest_runs_started_at",
        "candidate_backtest_runs",
        ["started_at"],
        unique=False,
    )


def downgrade() -> None:
    for index_name in (
        "ix_candidate_backtest_runs_started_at",
        "ix_candidate_backtest_runs_status",
        "ix_candidate_backtest_runs_decision",
        "ix_candidate_backtest_runs_wallet_address",
        "ix_candidate_backtest_runs_run_id",
    ):
        op.drop_index(index_name, table_name="candidate_backtest_runs")
    op.drop_table("candidate_backtest_runs")

    op.drop_index("ix_live_wallet_scores_promotion_status", table_name="live_wallet_scores")
    for column_name in (
        "backtest_jupiter_status",
        "backtest_max_drawdown_percent",
        "backtest_profit_factor",
        "backtest_total_return_percent",
        "backtest_score",
        "promotion_eligible",
        "promotion_status",
    ):
        op.drop_column("live_wallet_scores", column_name)

    op.drop_index(
        "ix_discovered_wallets_latest_backtest_run_id", table_name="discovered_wallets"
    )
    op.drop_index(
        "ix_discovered_wallets_promotion_eligible", table_name="discovered_wallets"
    )
    op.drop_index(
        "ix_discovered_wallets_promotion_status", table_name="discovered_wallets"
    )
    for column_name in (
        "backtest_jupiter_compatibility_percent",
        "backtest_jupiter_status",
        "backtest_execution_coverage_percent",
        "backtest_open_positions",
        "backtest_completed_positions",
        "backtest_max_drawdown_percent",
        "backtest_profit_factor",
        "backtest_win_rate_percent",
        "backtest_net_pnl_sol",
        "backtest_total_return_percent",
        "backtest_score",
        "latest_backtest_run_id",
        "promotion_calculated_at",
        "promotion_reasons",
        "promotion_eligible",
        "promotion_status",
    ):
        op.drop_column("discovered_wallets", column_name)
