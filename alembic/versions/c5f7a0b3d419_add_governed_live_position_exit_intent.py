"""add governed live position exit intent

Revision ID: c5f7a0b3d419
Revises: b4e6f9a2c308
Create Date: 2026-07-29 13:30:00.000000
"""
from collections.abc import Sequence
from alembic import op
import sqlalchemy as sa

revision: str = "c5f7a0b3d419"
down_revision: str | Sequence[str] | None = "b4e6f9a2c308"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pk = sa.BigInteger().with_variant(sa.Integer(), "sqlite")
    op.create_table(
        "canonical_parser_governed_live_position_assessments",
        sa.Column("id", pk, primary_key=True),
        sa.Column("assessment_id", sa.String(36), nullable=False),
        sa.Column("assessment_key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(52), nullable=False),
        sa.Column("position_db_id", pk, nullable=False),
        sa.Column("position_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("quoted_output_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("current_value_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("unrealized_pnl_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("unrealized_roi_percent", sa.Numeric(18, 8), nullable=False),
        sa.Column("high_watermark_value_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("high_watermark_roi_percent", sa.Numeric(18, 8), nullable=False),
        sa.Column("trailing_drawdown_percent", sa.Numeric(18, 8), nullable=False),
        sa.Column("price_impact_percent", sa.Numeric(12, 6), nullable=False),
        sa.Column("sell_route_available", sa.Boolean(), nullable=False),
        sa.Column("token_safety_status", sa.String(16), nullable=False),
        sa.Column("source_wallet_sell_detected", sa.Boolean(), nullable=False),
        sa.Column("emergency_exit_requested", sa.Boolean(), nullable=False),
        sa.Column("reason_codes", sa.JSON(), nullable=False),
        sa.Column("assessment_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("quote_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("assessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope = 'M40_GOVERNED_LIVE_POSITION_ASSESSMENT'", name="ck_m40_assessment_scope"),
        sa.CheckConstraint("status IN ('HOLD','EXIT_READY','REVIEW','BLOCKED','INSUFFICIENT_DATA')", name="ck_m40_assessment_status"),
        sa.CheckConstraint("quoted_output_sol >= 0 AND current_value_sol >= 0", name="ck_m40_assessment_values"),
        sa.CheckConstraint("price_impact_percent >= 0", name="ck_m40_assessment_price_impact"),
        sa.CheckConstraint("token_safety_status IN ('SAFE','REVIEW','UNSAFE','UNKNOWN')", name="ck_m40_assessment_token_safety"),
        sa.CheckConstraint("length(assessment_key) = 64 AND length(evidence_hash) = 64", name="ck_m40_assessment_hashes"),
        sa.ForeignKeyConstraint(["position_db_id"], ["canonical_parser_governed_live_positions.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("assessment_id", name="uq_m40_assessment_id"),
        sa.UniqueConstraint("assessment_key", name="uq_m40_assessment_key"),
    )
    op.create_index("ix_m40_assessment_position_time", "canonical_parser_governed_live_position_assessments", ["position_db_id", "assessed_at"])
    op.create_index("ix_m40_assessment_status_expiry", "canonical_parser_governed_live_position_assessments", ["status", "expires_at"])

    op.create_table(
        "canonical_parser_governed_live_exit_intents",
        sa.Column("id", pk, primary_key=True),
        sa.Column("intent_id", sa.String(36), nullable=False),
        sa.Column("intent_key", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(52), nullable=False),
        sa.Column("position_db_id", pk, nullable=False),
        sa.Column("position_id", sa.String(36), nullable=False),
        sa.Column("assessment_db_id", pk, nullable=False),
        sa.Column("assessment_id", sa.String(36), nullable=False),
        sa.Column("micro_live_permit_id", sa.String(36), nullable=False),
        sa.Column("decision_result_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reason_code", sa.String(80), nullable=False),
        sa.Column("quantity_raw", sa.Numeric(38, 0), nullable=False),
        sa.Column("percentage", sa.Numeric(7, 4), nullable=False),
        sa.Column("expected_output_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("minimum_output_sol", sa.Numeric(20, 9), nullable=False),
        sa.Column("intent_snapshot", sa.JSON(), nullable=False),
        sa.Column("evidence_hash", sa.String(64), nullable=False),
        sa.Column("actor_label", sa.String(80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latest_event_sequence", sa.Integer(), nullable=False),
        sa.Column("latest_event_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("scope = 'M40_MANUAL_GOVERNED_LIVE_EXIT_INTENT'", name="ck_m40_intent_scope"),
        sa.CheckConstraint("status IN ('ACTIVE','REVOKED','EXPIRED','CONSUMED')", name="ck_m40_intent_status"),
        sa.CheckConstraint("quantity_raw > 0 AND percentage > 0 AND percentage <= 100", name="ck_m40_intent_quantity"),
        sa.CheckConstraint("expected_output_sol >= 0 AND minimum_output_sol >= 0", name="ck_m40_intent_output"),
        sa.CheckConstraint("latest_event_sequence >= 1", name="ck_m40_intent_event_sequence"),
        sa.CheckConstraint("length(intent_key) = 64 AND length(evidence_hash) = 64 AND length(latest_event_hash) = 64", name="ck_m40_intent_hashes"),
        sa.ForeignKeyConstraint(["position_db_id"], ["canonical_parser_governed_live_positions.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assessment_db_id"], ["canonical_parser_governed_live_position_assessments.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("intent_id", name="uq_m40_intent_id"),
        sa.UniqueConstraint("intent_key", name="uq_m40_intent_key"),
    )
    op.create_index("ix_m40_intent_position_status", "canonical_parser_governed_live_exit_intents", ["position_db_id", "status"])
    op.create_index("ix_m40_intent_status_expiry", "canonical_parser_governed_live_exit_intents", ["status", "expires_at"])

    op.create_table(
        "canonical_parser_governed_live_exit_intent_events",
        sa.Column("id", pk, primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False),
        sa.Column("intent_db_id", pk, nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(16), nullable=False),
        sa.Column("event_payload", sa.JSON(), nullable=False),
        sa.Column("previous_event_hash", sa.String(64), nullable=True),
        sa.Column("event_hash", sa.String(64), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_m40_intent_event_sequence"),
        sa.CheckConstraint("event_type IN ('ISSUED','REVOKED','EXPIRED','CONSUMED')", name="ck_m40_intent_event_type"),
        sa.CheckConstraint("length(event_hash) = 64", name="ck_m40_intent_event_hash"),
        sa.ForeignKeyConstraint(["intent_db_id"], ["canonical_parser_governed_live_exit_intents.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("event_id", name="uq_m40_intent_event_id"),
        sa.UniqueConstraint("intent_db_id", "sequence", name="uq_m40_intent_event_sequence"),
    )
    op.create_index("ix_m40_intent_event_time", "canonical_parser_governed_live_exit_intent_events", ["intent_db_id", "occurred_at"])


def downgrade() -> None:
    op.drop_index("ix_m40_intent_event_time", table_name="canonical_parser_governed_live_exit_intent_events")
    op.drop_table("canonical_parser_governed_live_exit_intent_events")
    op.drop_index("ix_m40_intent_status_expiry", table_name="canonical_parser_governed_live_exit_intents")
    op.drop_index("ix_m40_intent_position_status", table_name="canonical_parser_governed_live_exit_intents")
    op.drop_table("canonical_parser_governed_live_exit_intents")
    op.drop_index("ix_m40_assessment_status_expiry", table_name="canonical_parser_governed_live_position_assessments")
    op.drop_index("ix_m40_assessment_position_time", table_name="canonical_parser_governed_live_position_assessments")
    op.drop_table("canonical_parser_governed_live_position_assessments")
