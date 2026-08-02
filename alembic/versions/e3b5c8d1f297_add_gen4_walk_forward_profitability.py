"""add Gen4 walk-forward profitability validation

Revision ID: e3b5c8d1f297
Revises: d2a4b7c0e186
Create Date: 2026-08-02 15:06:00
"""

from alembic import op
import sqlalchemy as sa


revision = "e3b5c8d1f297"
down_revision = "d2a4b7c0e186"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canonical_parser_gen4_profitability_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("run_key", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("verdict", sa.String(length=64), nullable=False),
        sa.Column("strict_evidence_status", sa.String(length=32), nullable=False),
        sa.Column("policy_version", sa.String(length=120), nullable=False),
        sa.Column("policy_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("strict_metrics", sa.JSON(), nullable=False),
        sa.Column("proxy_metrics", sa.JSON(), nullable=False),
        sa.Column("baseline_metrics", sa.JSON(), nullable=False),
        sa.Column("evidence_gaps", sa.JSON(), nullable=False),
        sa.Column("safety", sa.JSON(), nullable=False),
        sa.Column("source_trade_count", sa.Integer(), nullable=False),
        sa.Column("source_wallet_count", sa.Integer(), nullable=False),
        sa.Column("source_token_count", sa.Integer(), nullable=False),
        sa.Column("window_count", sa.Integer(), nullable=False),
        sa.Column("strict_closed_trade_count", sa.Integer(), nullable=False),
        sa.Column("proxy_closed_trade_count", sa.Integer(), nullable=False),
        sa.Column("data_start_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data_end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("report_hash", sa.String(length=64), nullable=False),
        sa.Column("actor_label", sa.String(length=80), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("technical_metadata", sa.JSON(), nullable=False),
        sa.CheckConstraint("status IN ('COMPLETED', 'FAILED')", name="ck_gen4_profitability_runs_status"),
        sa.CheckConstraint(
            "verdict IN ('NOT_EVALUABLE', 'NEGATIVE_EVIDENCE', 'PROXY_PROMISING_STRICT_EVIDENCE_MISSING', 'PROMISING_NOT_PROVEN', 'PROFITABLE_EVIDENCE')",
            name="ck_gen4_profitability_runs_verdict",
        ),
        sa.CheckConstraint(
            "strict_evidence_status IN ('INSUFFICIENT', 'EVALUABLE', 'SUFFICIENT')",
            name="ck_gen4_profitability_runs_strict_status",
        ),
        sa.CheckConstraint(
            "source_trade_count >= 0 AND source_wallet_count >= 0 AND source_token_count >= 0 AND window_count >= 0 AND strict_closed_trade_count >= 0 AND proxy_closed_trade_count >= 0",
            name="ck_gen4_profitability_runs_counts",
        ),
        sa.CheckConstraint("length(run_key) = 64", name="ck_gen4_profitability_runs_key_len"),
        sa.CheckConstraint("length(policy_hash) = 64", name="ck_gen4_profitability_runs_policy_hash_len"),
        sa.CheckConstraint("length(report_hash) = 64", name="ck_gen4_profitability_runs_report_hash_len"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_gen4_profitability_runs_run_id"),
        sa.UniqueConstraint("run_key", name="uq_gen4_profitability_runs_run_key"),
        sa.UniqueConstraint("report_hash", name="uq_gen4_profitability_runs_report_hash"),
    )
    op.create_index(
        "ix_gen4_profitability_runs_verdict_completed",
        "canonical_parser_gen4_profitability_runs",
        ["verdict", "completed_at"],
    )
    op.create_index(
        "ix_gen4_profitability_runs_policy",
        "canonical_parser_gen4_profitability_runs",
        ["policy_hash", "evaluated_at"],
    )

    op.create_table(
        "canonical_parser_gen4_profitability_windows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("window_id", sa.String(length=36), nullable=False),
        sa.Column("run_db_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("train_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("train_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("test_start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("test_end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("strict_qualified_wallet_count", sa.Integer(), nullable=False),
        sa.Column("proxy_qualified_wallet_count", sa.Integer(), nullable=False),
        sa.Column("strict_signal_count", sa.Integer(), nullable=False),
        sa.Column("proxy_signal_count", sa.Integer(), nullable=False),
        sa.Column("baseline_signal_count", sa.Integer(), nullable=False),
        sa.Column("strict_metrics", sa.JSON(), nullable=False),
        sa.Column("proxy_metrics", sa.JSON(), nullable=False),
        sa.Column("baseline_metrics", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("window_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_gen4_profitability_windows_sequence"),
        sa.CheckConstraint(
            "strict_qualified_wallet_count >= 0 AND proxy_qualified_wallet_count >= 0 AND strict_signal_count >= 0 AND proxy_signal_count >= 0 AND baseline_signal_count >= 0",
            name="ck_gen4_profitability_windows_counts",
        ),
        sa.CheckConstraint(
            "train_start_at < train_end_at AND train_end_at <= test_start_at AND test_start_at < test_end_at",
            name="ck_gen4_profitability_windows_dates",
        ),
        sa.CheckConstraint("length(window_hash) = 64", name="ck_gen4_profitability_windows_hash_len"),
        sa.ForeignKeyConstraint(
            ["run_db_id"],
            ["canonical_parser_gen4_profitability_runs.id"],
            ondelete="CASCADE",
            name="fk_gen4_profitability_windows_run",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("window_id", name="uq_gen4_profitability_windows_window_id"),
        sa.UniqueConstraint("run_db_id", "sequence", name="uq_gen4_profitability_windows_sequence"),
        sa.UniqueConstraint("window_hash", name="uq_gen4_profitability_windows_hash"),
    )
    op.create_index(
        "ix_gen4_profitability_windows_run_sequence",
        "canonical_parser_gen4_profitability_windows",
        ["run_db_id", "sequence"],
    )
    op.create_index(
        "ix_gen4_profitability_windows_test_period",
        "canonical_parser_gen4_profitability_windows",
        ["test_start_at", "test_end_at"],
    )

    op.create_table(
        "canonical_parser_gen4_profitability_trades",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("trade_id", sa.String(length=36), nullable=False),
        sa.Column("window_db_id", sa.Integer(), nullable=False),
        sa.Column("lane", sa.String(length=32), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("token_mint", sa.String(length=64), nullable=False),
        sa.Column("signal_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entry_price_sol", sa.Float(), nullable=True),
        sa.Column("exit_price_sol", sa.Float(), nullable=True),
        sa.Column("order_size_sol", sa.Float(), nullable=False),
        sa.Column("pnl_sol", sa.Float(), nullable=True),
        sa.Column("return_percent", sa.Float(), nullable=True),
        sa.Column("exit_reason", sa.String(length=48), nullable=True),
        sa.Column("wallet_count", sa.Integer(), nullable=False),
        sa.Column("independent_cluster_count", sa.Integer(), nullable=False),
        sa.Column("contributing_wallets", sa.JSON(), nullable=False),
        sa.Column("source_trade_ids", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("trade_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "lane IN ('STRICT_GEN4', 'SIGNAL_ONLY_PROXY', 'SIMPLE_COPY_BASELINE')",
            name="ck_gen4_profitability_trades_lane",
        ),
        sa.CheckConstraint("sequence >= 1", name="ck_gen4_profitability_trades_sequence"),
        sa.CheckConstraint("order_size_sol > 0", name="ck_gen4_profitability_trades_order_size"),
        sa.CheckConstraint(
            "wallet_count >= 0 AND independent_cluster_count >= 0",
            name="ck_gen4_profitability_trades_counts",
        ),
        sa.CheckConstraint("length(trade_hash) = 64", name="ck_gen4_profitability_trades_hash_len"),
        sa.ForeignKeyConstraint(
            ["window_db_id"],
            ["canonical_parser_gen4_profitability_windows.id"],
            ondelete="CASCADE",
            name="fk_gen4_profitability_trades_window",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trade_id", name="uq_gen4_profitability_trades_trade_id"),
        sa.UniqueConstraint("window_db_id", "lane", "sequence", name="uq_gen4_profitability_trades_sequence"),
        sa.UniqueConstraint("trade_hash", name="uq_gen4_profitability_trades_hash"),
    )
    op.create_index(
        "ix_gen4_profitability_trades_window_lane",
        "canonical_parser_gen4_profitability_trades",
        ["window_db_id", "lane", "sequence"],
    )
    op.create_index(
        "ix_gen4_profitability_trades_token_signal",
        "canonical_parser_gen4_profitability_trades",
        ["token_mint", "signal_at"],
    )
    op.create_index(
        "ix_gen4_profitability_trades_lane_exit_reason",
        "canonical_parser_gen4_profitability_trades",
        ["lane", "exit_reason"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    run_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM canonical_parser_gen4_profitability_runs")
    ).scalar_one()
    if int(run_count or 0) > 0:
        raise RuntimeError(
            "Downgrade M47 rifiutato: esistono validazioni Gen4 persistite. "
            "Esportare o rimuovere esplicitamente i metadati prima del downgrade."
        )

    op.drop_index(
        "ix_gen4_profitability_trades_lane_exit_reason",
        table_name="canonical_parser_gen4_profitability_trades",
    )
    op.drop_index(
        "ix_gen4_profitability_trades_token_signal",
        table_name="canonical_parser_gen4_profitability_trades",
    )
    op.drop_index(
        "ix_gen4_profitability_trades_window_lane",
        table_name="canonical_parser_gen4_profitability_trades",
    )
    op.drop_table("canonical_parser_gen4_profitability_trades")

    op.drop_index(
        "ix_gen4_profitability_windows_test_period",
        table_name="canonical_parser_gen4_profitability_windows",
    )
    op.drop_index(
        "ix_gen4_profitability_windows_run_sequence",
        table_name="canonical_parser_gen4_profitability_windows",
    )
    op.drop_table("canonical_parser_gen4_profitability_windows")

    op.drop_index(
        "ix_gen4_profitability_runs_policy",
        table_name="canonical_parser_gen4_profitability_runs",
    )
    op.drop_index(
        "ix_gen4_profitability_runs_verdict_completed",
        table_name="canonical_parser_gen4_profitability_runs",
    )
    op.drop_table("canonical_parser_gen4_profitability_runs")
