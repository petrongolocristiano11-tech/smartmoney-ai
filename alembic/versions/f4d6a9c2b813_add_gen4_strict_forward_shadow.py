"""add Gen4 strict forward shadow campaign

Revision ID: f4d6a9c2b813
Revises: e3b5c8d1f297
Create Date: 2026-08-02 18:35:00
"""

from alembic import op
import sqlalchemy as sa


revision = "f4d6a9c2b813"
down_revision = "e3b5c8d1f297"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canonical_parser_gen4_forward_campaigns",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("campaign_id", sa.String(length=36), nullable=False),
        sa.Column("campaign_key", sa.String(length=64), nullable=False),
        sa.Column("scope", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("verdict", sa.String(length=40), nullable=False),
        sa.Column("strict_evidence_status", sa.String(length=24), nullable=False),
        sa.Column("policy_version", sa.String(length=120), nullable=False),
        sa.Column("policy_hash", sa.String(length=64), nullable=False),
        sa.Column("policy_snapshot", sa.JSON(), nullable=False),
        sa.Column("frozen_wallets", sa.JSON(), nullable=False),
        sa.Column("frozen_wallet_metrics", sa.JSON(), nullable=False),
        sa.Column("frozen_wallet_count", sa.Integer(), nullable=False),
        sa.Column("anchor_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("minimum_complete_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latest_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("minimum_observation_days", sa.Integer(), nullable=False),
        sa.Column("minimum_closed_trades", sa.Integer(), nullable=False),
        sa.Column("proof_closed_trades", sa.Integer(), nullable=False),
        sa.Column("cycle_count", sa.Integer(), nullable=False),
        sa.Column("decision_count", sa.Integer(), nullable=False),
        sa.Column("strict_signal_count", sa.Integer(), nullable=False),
        sa.Column("proxy_signal_count", sa.Integer(), nullable=False),
        sa.Column("baseline_signal_count", sa.Integer(), nullable=False),
        sa.Column("strict_closed_trade_count", sa.Integer(), nullable=False),
        sa.Column("proxy_closed_trade_count", sa.Integer(), nullable=False),
        sa.Column("baseline_closed_trade_count", sa.Integer(), nullable=False),
        sa.Column("rejected_decision_count", sa.Integer(), nullable=False),
        sa.Column("strict_metrics", sa.JSON(), nullable=False),
        sa.Column("proxy_metrics", sa.JSON(), nullable=False),
        sa.Column("baseline_metrics", sa.JSON(), nullable=False),
        sa.Column("evidence_gaps", sa.JSON(), nullable=False),
        sa.Column("safety", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("actor_label", sa.String(length=80), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("technical_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("scope = 'GEN4_STRICT_FORWARD_SHADOW'", name="ck_gen4_forward_campaigns_scope"),
        sa.CheckConstraint("status IN ('ACTIVE','PAUSED','COMPLETED','FAILED')", name="ck_gen4_forward_campaigns_status"),
        sa.CheckConstraint(
            "verdict IN ('COLLECTING','NOT_EVALUABLE','NEGATIVE_EVIDENCE','PROMISING_NOT_PROVEN','PROFITABLE_EVIDENCE')",
            name="ck_gen4_forward_campaigns_verdict",
        ),
        sa.CheckConstraint(
            "strict_evidence_status IN ('COLLECTING','INSUFFICIENT','EVALUABLE','SUFFICIENT')",
            name="ck_gen4_forward_campaigns_strict_status",
        ),
        sa.CheckConstraint(
            "frozen_wallet_count >= 0 AND cycle_count >= 0 AND decision_count >= 0 AND strict_signal_count >= 0 AND proxy_signal_count >= 0 AND baseline_signal_count >= 0 AND strict_closed_trade_count >= 0 AND proxy_closed_trade_count >= 0 AND baseline_closed_trade_count >= 0 AND rejected_decision_count >= 0",
            name="ck_gen4_forward_campaigns_counts",
        ),
        sa.CheckConstraint(
            "minimum_observation_days >= 1 AND minimum_closed_trades >= 1 AND proof_closed_trades >= minimum_closed_trades",
            name="ck_gen4_forward_campaigns_thresholds",
        ),
        sa.CheckConstraint(
            "length(campaign_key) = 64 AND length(policy_hash) = 64 AND length(evidence_hash) = 64",
            name="ck_gen4_forward_campaigns_hashes",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("campaign_id", name="uq_gen4_forward_campaigns_campaign_id"),
        sa.UniqueConstraint("campaign_key", name="uq_gen4_forward_campaigns_campaign_key"),
    )
    op.create_index(
        "ix_gen4_forward_campaigns_status_anchor",
        "canonical_parser_gen4_forward_campaigns",
        ["status", "anchor_at"],
    )
    op.create_index(
        "ix_gen4_forward_campaigns_verdict_updated",
        "canonical_parser_gen4_forward_campaigns",
        ["verdict", "updated_at"],
    )

    op.create_table(
        "canonical_parser_gen4_forward_cycles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("cycle_id", sa.String(length=36), nullable=False),
        sa.Column("cycle_key", sa.String(length=64), nullable=False),
        sa.Column("campaign_db_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("observed_from_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_to_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_trade_count", sa.Integer(), nullable=False),
        sa.Column("accepted_price_point_count", sa.Integer(), nullable=False),
        sa.Column("new_decision_count", sa.Integer(), nullable=False),
        sa.Column("updated_decision_count", sa.Integer(), nullable=False),
        sa.Column("strict_signal_count", sa.Integer(), nullable=False),
        sa.Column("proxy_signal_count", sa.Integer(), nullable=False),
        sa.Column("baseline_signal_count", sa.Integer(), nullable=False),
        sa.Column("closed_decision_count", sa.Integer(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("safety", sa.JSON(), nullable=False),
        sa.Column("report_hash", sa.String(length=64), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status IN ('COMPLETED','NOOP','FAILED')", name="ck_gen4_forward_cycles_status"),
        sa.CheckConstraint("sequence >= 1", name="ck_gen4_forward_cycles_sequence"),
        sa.CheckConstraint(
            "source_trade_count >= 0 AND accepted_price_point_count >= 0 AND new_decision_count >= 0 AND updated_decision_count >= 0 AND strict_signal_count >= 0 AND proxy_signal_count >= 0 AND baseline_signal_count >= 0 AND closed_decision_count >= 0",
            name="ck_gen4_forward_cycles_counts",
        ),
        sa.CheckConstraint("observed_from_at <= observed_to_at", name="ck_gen4_forward_cycles_dates"),
        sa.CheckConstraint(
            "length(cycle_key) = 64 AND length(report_hash) = 64",
            name="ck_gen4_forward_cycles_hashes",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_db_id"],
            ["canonical_parser_gen4_forward_campaigns.id"],
            ondelete="CASCADE",
            name="fk_gen4_forward_cycles_campaign",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cycle_id", name="uq_gen4_forward_cycles_cycle_id"),
        sa.UniqueConstraint("campaign_db_id", "sequence", name="uq_gen4_forward_cycles_sequence"),
        sa.UniqueConstraint("cycle_key", name="uq_gen4_forward_cycles_cycle_key"),
    )
    op.create_index(
        "ix_gen4_forward_cycles_campaign_time",
        "canonical_parser_gen4_forward_cycles",
        ["campaign_db_id", "observed_to_at"],
    )
    op.create_index(
        "ix_gen4_forward_cycles_status_completed",
        "canonical_parser_gen4_forward_cycles",
        ["status", "completed_at"],
    )

    op.create_table(
        "canonical_parser_gen4_forward_decisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("decision_id", sa.String(length=36), nullable=False),
        sa.Column("decision_key", sa.String(length=64), nullable=False),
        sa.Column("campaign_db_id", sa.Integer(), nullable=False),
        sa.Column("lane", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("token_mint", sa.String(length=64), nullable=False),
        sa.Column("signal_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("signal_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("entry_price_sol", sa.Float(), nullable=True),
        sa.Column("exit_price_sol", sa.Float(), nullable=True),
        sa.Column("order_size_sol", sa.Float(), nullable=False),
        sa.Column("pnl_sol", sa.Float(), nullable=True),
        sa.Column("return_percent", sa.Float(), nullable=True),
        sa.Column("exit_reason", sa.String(length=64), nullable=True),
        sa.Column("rejection_reason", sa.String(length=96), nullable=True),
        sa.Column("portfolio_accepted", sa.Boolean(), nullable=False),
        sa.Column("wallet_count", sa.Integer(), nullable=False),
        sa.Column("independent_cluster_count", sa.Integer(), nullable=False),
        sa.Column("contributing_wallets", sa.JSON(), nullable=False),
        sa.Column("source_trade_ids", sa.JSON(), nullable=False),
        sa.Column("source_signatures", sa.JSON(), nullable=False),
        sa.Column("signal_hash", sa.String(length=64), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(length=64), nullable=False),
        sa.Column("first_seen_cycle_sequence", sa.Integer(), nullable=False),
        sa.Column("last_updated_cycle_sequence", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "lane IN ('STRICT_GEN4_FORWARD','SIGNAL_ONLY_FORWARD','SIMPLE_COPY_FORWARD_BASELINE')",
            name="ck_gen4_forward_decisions_lane",
        ),
        sa.CheckConstraint(
            "status IN ('WAITING_SAFETY','REJECTED','PENDING_ENTRY','OPEN','CLOSED','EXPIRED')",
            name="ck_gen4_forward_decisions_status",
        ),
        sa.CheckConstraint("order_size_sol > 0", name="ck_gen4_forward_decisions_order_size"),
        sa.CheckConstraint(
            "wallet_count >= 0 AND independent_cluster_count >= 0",
            name="ck_gen4_forward_decisions_counts",
        ),
        sa.CheckConstraint(
            "length(decision_key) = 64 AND length(signal_hash) = 64 AND length(evidence_hash) = 64",
            name="ck_gen4_forward_decisions_hashes",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_db_id"],
            ["canonical_parser_gen4_forward_campaigns.id"],
            ondelete="CASCADE",
            name="fk_gen4_forward_decisions_campaign",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("decision_id", name="uq_gen4_forward_decisions_decision_id"),
        sa.UniqueConstraint("decision_key", name="uq_gen4_forward_decisions_decision_key"),
    )
    op.create_index(
        "ix_gen4_forward_decisions_campaign_lane",
        "canonical_parser_gen4_forward_decisions",
        ["campaign_db_id", "lane", "status"],
    )
    op.create_index(
        "ix_gen4_forward_decisions_token_signal",
        "canonical_parser_gen4_forward_decisions",
        ["token_mint", "signal_at"],
    )
    op.create_index(
        "ix_gen4_forward_decisions_status_decision",
        "canonical_parser_gen4_forward_decisions",
        ["status", "decision_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    protected_tables = (
        "canonical_parser_gen4_forward_decisions",
        "canonical_parser_gen4_forward_cycles",
        "canonical_parser_gen4_forward_campaigns",
    )
    for table_name in protected_tables:
        count = bind.execute(sa.text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()
        if int(count or 0) > 0:
            raise RuntimeError(
                "Downgrade M52-M53 rifiutato: esistono evidenze forward. "
                "Esportare o rimuovere esplicitamente i metadati prima del downgrade."
            )

    op.drop_index(
        "ix_gen4_forward_decisions_status_decision",
        table_name="canonical_parser_gen4_forward_decisions",
    )
    op.drop_index(
        "ix_gen4_forward_decisions_token_signal",
        table_name="canonical_parser_gen4_forward_decisions",
    )
    op.drop_index(
        "ix_gen4_forward_decisions_campaign_lane",
        table_name="canonical_parser_gen4_forward_decisions",
    )
    op.drop_table("canonical_parser_gen4_forward_decisions")

    op.drop_index(
        "ix_gen4_forward_cycles_status_completed",
        table_name="canonical_parser_gen4_forward_cycles",
    )
    op.drop_index(
        "ix_gen4_forward_cycles_campaign_time",
        table_name="canonical_parser_gen4_forward_cycles",
    )
    op.drop_table("canonical_parser_gen4_forward_cycles")

    op.drop_index(
        "ix_gen4_forward_campaigns_verdict_updated",
        table_name="canonical_parser_gen4_forward_campaigns",
    )
    op.drop_index(
        "ix_gen4_forward_campaigns_status_anchor",
        table_name="canonical_parser_gen4_forward_campaigns",
    )
    op.drop_table("canonical_parser_gen4_forward_campaigns")
