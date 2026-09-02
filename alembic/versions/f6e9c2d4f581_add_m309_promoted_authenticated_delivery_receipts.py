"""add M309 promoted authenticated delivery receipt table

Revision ID: f6e9c2d4f581
Revises: f5d8b1c3e470
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "f6e9c2d4f581"
down_revision = "f5d8b1c3e470"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canonical_parser_gen4_promoted_selective_delivery_receipts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("receipt_id", sa.String(length=36), nullable=False),
        sa.Column("activation_db_id", sa.Integer(), nullable=False),
        sa.Column("activation_id", sa.String(length=36), nullable=False),
        sa.Column("signature", sa.String(length=128), nullable=False),
        sa.Column("event_hash", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=24), nullable=False),
        sa.Column("auth_verified", sa.Boolean(), nullable=False),
        sa.Column("wallet_address", sa.String(length=64), nullable=False),
        sa.Column("matched_wallets", sa.JSON(), nullable=False),
        sa.Column("slot", sa.BigInteger(), nullable=True),
        sa.Column("block_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivery_count", sa.Integer(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("source = 'WEBHOOK'", name="ck_gen4_promoted_delivery_receipt_source"),
        sa.ForeignKeyConstraint(
            ["activation_db_id"],
            ["canonical_parser_gen4_promoted_selective_activations.id"],
            name="fk_gen4_promoted_delivery_activation",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("receipt_id", name="uq_gen4_promoted_delivery_receipt_id"),
        sa.UniqueConstraint(
            "activation_db_id", "signature",
            name="uq_gen4_promoted_delivery_activation_signature",
        ),
    )
    op.create_index(
        "ix_gen4_promoted_delivery_activation_received",
        "canonical_parser_gen4_promoted_selective_delivery_receipts",
        ["activation_id", "received_at"],
        unique=False,
    )
    op.create_index(
        "ix_gen4_promoted_delivery_wallet_received",
        "canonical_parser_gen4_promoted_selective_delivery_receipts",
        ["wallet_address", "received_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_gen4_promoted_delivery_wallet_received",
        table_name="canonical_parser_gen4_promoted_selective_delivery_receipts",
    )
    op.drop_index(
        "ix_gen4_promoted_delivery_activation_received",
        table_name="canonical_parser_gen4_promoted_selective_delivery_receipts",
    )
    op.drop_table("canonical_parser_gen4_promoted_selective_delivery_receipts")
