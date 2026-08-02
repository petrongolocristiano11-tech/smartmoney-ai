"""add gen4 forward feed

Revision ID: a5e7c1d4b926
Revises: f4d6a9c2b813
Create Date: 2026-08-02 20:30:00
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "a5e7c1d4b926"
down_revision: str | None = "f4d6a9c2b813"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "canonical_parser_gen4_forward_feed_states",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("state_id", sa.String(length=36), nullable=False),
        sa.Column("campaign_db_id", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=False),
        sa.Column("max_requests_per_run", sa.Integer(), nullable=False),
        sa.Column("page_size", sa.Integer(), nullable=False),
        sa.Column("overlap_seconds", sa.Integer(), nullable=False),
        sa.Column("feed_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_poll_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_poll_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_poll_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=120), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=24), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column("last_error_message", sa.String(length=500), nullable=True),
        sa.Column("total_runs", sa.Integer(), nullable=False),
        sa.Column("successful_runs", sa.Integer(), nullable=False),
        sa.Column("failed_runs", sa.Integer(), nullable=False),
        sa.Column("total_helius_requests", sa.Integer(), nullable=False),
        sa.Column("total_transactions_found", sa.Integer(), nullable=False),
        sa.Column("total_swaps_found", sa.Integer(), nullable=False),
        sa.Column("total_trades_imported", sa.Integer(), nullable=False),
        sa.Column("total_trades_updated", sa.Integer(), nullable=False),
        sa.Column("total_parse_failures", sa.Integer(), nullable=False),
        sa.Column("total_stale_transactions_filtered", sa.Integer(), nullable=False),
        sa.Column("technical_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("interval_seconds BETWEEN 30 AND 3600", name="ck_gen4_forward_feed_states_interval"),
        sa.CheckConstraint("max_requests_per_run BETWEEN 1 AND 20", name="ck_gen4_forward_feed_states_requests"),
        sa.CheckConstraint("page_size BETWEEN 10 AND 100", name="ck_gen4_forward_feed_states_page_size"),
        sa.CheckConstraint("overlap_seconds BETWEEN 0 AND 300", name="ck_gen4_forward_feed_states_overlap"),
        sa.CheckConstraint(
            "total_runs >= 0 AND successful_runs >= 0 AND failed_runs >= 0 "
            "AND total_helius_requests >= 0 AND total_transactions_found >= 0 "
            "AND total_swaps_found >= 0 AND total_trades_imported >= 0 "
            "AND total_trades_updated >= 0 AND total_parse_failures >= 0 "
            "AND total_stale_transactions_filtered >= 0",
            name="ck_gen4_forward_feed_states_counts",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_db_id"],
            ["canonical_parser_gen4_forward_campaigns.id"],
            ondelete="CASCADE",
            name="fk_gen4_forward_feed_states_campaign",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("state_id", name="uq_gen4_forward_feed_states_state_id"),
        sa.UniqueConstraint("campaign_db_id", name="uq_gen4_forward_feed_states_campaign"),
    )
    op.create_index(
        "ix_gen4_forward_feed_states_enabled_next",
        "canonical_parser_gen4_forward_feed_states",
        ["enabled", "next_poll_at"],
    )
    op.create_index(
        "ix_gen4_forward_feed_states_lease",
        "canonical_parser_gen4_forward_feed_states",
        ["lease_expires_at"],
    )

    op.create_table(
        "canonical_parser_gen4_forward_feed_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("state_db_id", sa.Integer(), nullable=False),
        sa.Column("campaign_db_id", sa.Integer(), nullable=False),
        sa.Column("trigger", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("owner_id", sa.String(length=120), nullable=False),
        sa.Column("observed_from_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_to_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("wallet_count", sa.Integer(), nullable=False),
        sa.Column("request_budget", sa.Integer(), nullable=False),
        sa.Column("helius_requests", sa.Integer(), nullable=False),
        sa.Column("transactions_found", sa.Integer(), nullable=False),
        sa.Column("swaps_found", sa.Integer(), nullable=False),
        sa.Column("trades_imported", sa.Integer(), nullable=False),
        sa.Column("trades_updated", sa.Integer(), nullable=False),
        sa.Column("parse_failures", sa.Integer(), nullable=False),
        sa.Column("stale_transactions_filtered", sa.Integer(), nullable=False),
        sa.Column("cycle_id", sa.String(length=36), nullable=True),
        sa.Column("cycle_sequence", sa.Integer(), nullable=True),
        sa.Column("cycle_status", sa.String(length=16), nullable=True),
        sa.Column("new_decisions", sa.Integer(), nullable=False),
        sa.Column("updated_decisions", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("safety", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("trigger IN ('MANUAL','SCHEDULER','STARTUP')", name="ck_gen4_forward_feed_runs_trigger"),
        sa.CheckConstraint(
            "status IN ('COMPLETED','NOOP','PARTIAL','FAILED','SKIPPED_LOCKED','SKIPPED_BUDGET')",
            name="ck_gen4_forward_feed_runs_status",
        ),
        sa.CheckConstraint(
            "wallet_count >= 0 AND request_budget >= 0 AND helius_requests >= 0 "
            "AND transactions_found >= 0 AND swaps_found >= 0 "
            "AND trades_imported >= 0 AND trades_updated >= 0 "
            "AND parse_failures >= 0 AND stale_transactions_filtered >= 0 "
            "AND new_decisions >= 0 AND updated_decisions >= 0",
            name="ck_gen4_forward_feed_runs_counts",
        ),
        sa.ForeignKeyConstraint(
            ["campaign_db_id"],
            ["canonical_parser_gen4_forward_campaigns.id"],
            ondelete="CASCADE",
            name="fk_gen4_forward_feed_runs_campaign",
        ),
        sa.ForeignKeyConstraint(
            ["state_db_id"],
            ["canonical_parser_gen4_forward_feed_states.id"],
            ondelete="CASCADE",
            name="fk_gen4_forward_feed_runs_state",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", name="uq_gen4_forward_feed_runs_run_id"),
    )
    op.create_index(
        "ix_gen4_forward_feed_runs_campaign_started",
        "canonical_parser_gen4_forward_feed_runs",
        ["campaign_db_id", "started_at"],
    )
    op.create_index(
        "ix_gen4_forward_feed_runs_status_completed",
        "canonical_parser_gen4_forward_feed_runs",
        ["status", "completed_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_gen4_forward_feed_runs_status_completed",
        table_name="canonical_parser_gen4_forward_feed_runs",
    )
    op.drop_index(
        "ix_gen4_forward_feed_runs_campaign_started",
        table_name="canonical_parser_gen4_forward_feed_runs",
    )
    op.drop_table("canonical_parser_gen4_forward_feed_runs")
    op.drop_index(
        "ix_gen4_forward_feed_states_lease",
        table_name="canonical_parser_gen4_forward_feed_states",
    )
    op.drop_index(
        "ix_gen4_forward_feed_states_enabled_next",
        table_name="canonical_parser_gen4_forward_feed_states",
    )
    op.drop_table("canonical_parser_gen4_forward_feed_states")
