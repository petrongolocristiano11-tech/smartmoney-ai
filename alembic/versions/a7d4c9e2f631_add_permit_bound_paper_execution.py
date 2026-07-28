"""add permit bound paper execution

Revision ID: a7d4c9e2f631
Revises: f2c8a6d1e735
Create Date: 2026-07-28 21:00:00.000000
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "a7d4c9e2f631"
down_revision: str | Sequence[str] | None = "f2c8a6d1e735"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_permit_bound_paper_executions",
        sa.Column("id", pk, primary_key=True),
        sa.Column("execution_id", sa.String(36), nullable=False),
        sa.Column("idempotency_key", sa.String(64), nullable=False),
        sa.Column("permit_db_id", pk, nullable=False),
        sa.Column("permit_id", sa.String(36), nullable=False),
        sa.Column("decision_result_db_id", pk, nullable=False),
        sa.Column("decision_result_id", sa.String(36), nullable=False),
        sa.Column("decision_hash", sa.String(64), nullable=False),
        sa.Column("paper_account_id", sa.Integer(), nullable=False),
        sa.Column("paper_order_id", sa.Integer(), nullable=True),
        sa.Column("paper_position_id", sa.Integer(), nullable=True),
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("token_mint", sa.String(64), nullable=False),
        sa.Column("requested_budget_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("reserved_budget_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("settled_budget_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("quantity", sa.Numeric(36, 18), nullable=False),
        sa.Column("market_price_sol", sa.Numeric(36, 18), nullable=False),
        sa.Column("slippage_percent", sa.Numeric(9, 6), nullable=False),
        sa.Column("fee_percent", sa.Numeric(9, 6), nullable=False),
        sa.Column("signal_score", sa.Numeric(7, 4), nullable=False),
        sa.Column("confidence_score", sa.Numeric(7, 4), nullable=False),
        sa.Column("permit_budget_before_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("permit_order_count_before", sa.Integer(), nullable=False),
        sa.Column("reservation_hash", sa.String(64), nullable=False),
        sa.Column("settlement_hash", sa.String(64), nullable=True),
        sa.Column("failure_code", sa.String(80), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("technical_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("side IN ('BUY', 'SELL')", name="ck_parser_permit_bound_paper_executions_side"),
        sa.CheckConstraint("status IN ('RESERVED', 'SETTLED', 'RELEASED', 'FAILED', 'RECONCILIATION_REQUIRED')", name="ck_parser_permit_bound_paper_executions_status"),
        sa.CheckConstraint("requested_budget_sol >= 0 AND reserved_budget_sol >= 0 AND settled_budget_sol >= 0", name="ck_parser_permit_bound_paper_executions_budgets"),
        sa.CheckConstraint("quantity >= 0 AND market_price_sol > 0 AND slippage_percent >= 0 AND fee_percent >= 0", name="ck_parser_permit_bound_paper_executions_values"),
        sa.CheckConstraint("length(idempotency_key) = 64", name="ck_parser_permit_bound_paper_executions_idempotency"),
        sa.CheckConstraint("length(decision_hash) = 64", name="ck_parser_permit_bound_paper_executions_decision_hash"),
        sa.CheckConstraint("length(reservation_hash) = 64", name="ck_parser_permit_bound_paper_executions_reservation_hash"),
        sa.CheckConstraint("settlement_hash IS NULL OR length(settlement_hash) = 64", name="ck_parser_permit_bound_paper_executions_settlement_hash"),
        sa.ForeignKeyConstraint(["permit_db_id"], ["canonical_parser_paper_execution_permits.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["decision_result_db_id"], ["canonical_parser_unified_decision_results.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["paper_account_id"], ["paper_accounts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["paper_order_id"], ["paper_orders.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["paper_position_id"], ["paper_positions.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("execution_id", name="uq_parser_permit_bound_paper_executions_id"),
        sa.UniqueConstraint("idempotency_key", name="uq_parser_permit_bound_paper_executions_idempotency"),
    )
    op.create_index("ix_parser_permit_bound_paper_executions_status_created", "canonical_parser_permit_bound_paper_executions", ["status", "created_at"])
    op.create_index("ix_parser_permit_bound_paper_executions_permit_created", "canonical_parser_permit_bound_paper_executions", ["permit_db_id", "created_at"])
    op.create_index("ix_parser_permit_bound_paper_executions_account_token", "canonical_parser_permit_bound_paper_executions", ["paper_account_id", "token_mint"])

    op.create_table(
        "canonical_parser_permit_bound_paper_execution_events",
        sa.Column("id", pk, primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("execution_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column("previous_event_hash", sa.String(64), nullable=True),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_parser_permit_bound_paper_execution_events_sequence"),
        sa.CheckConstraint("event_type IN ('RESERVED', 'SETTLED', 'RELEASED', 'FAILED', 'RECONCILIATION_REQUIRED')", name="ck_parser_permit_bound_paper_execution_events_type"),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_parser_permit_bound_paper_execution_events_hash"),
        sa.CheckConstraint("previous_event_hash IS NULL OR length(previous_event_hash) = 64", name="ck_parser_permit_bound_paper_execution_events_previous_hash"),
        sa.ForeignKeyConstraint(["execution_db_id"], ["canonical_parser_permit_bound_paper_executions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("event_id", name="uq_parser_permit_bound_paper_execution_events_id"),
        sa.UniqueConstraint("execution_db_id", "sequence", name="uq_parser_permit_bound_paper_execution_events_sequence"),
    )
    op.create_index("ix_parser_permit_bound_paper_execution_events_execution", "canonical_parser_permit_bound_paper_execution_events", ["execution_db_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_parser_permit_bound_paper_execution_events_execution", table_name="canonical_parser_permit_bound_paper_execution_events")
    op.drop_table("canonical_parser_permit_bound_paper_execution_events")
    op.drop_index("ix_parser_permit_bound_paper_executions_account_token", table_name="canonical_parser_permit_bound_paper_executions")
    op.drop_index("ix_parser_permit_bound_paper_executions_permit_created", table_name="canonical_parser_permit_bound_paper_executions")
    op.drop_index("ix_parser_permit_bound_paper_executions_status_created", table_name="canonical_parser_permit_bound_paper_executions")
    op.drop_table("canonical_parser_permit_bound_paper_executions")
