"""add dry run generations

Revision ID: a8d4c2e7f901
Revises: f4a9c2d7b61e
Create Date: 2026-07-19
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "a8d4c2e7f901"

down_revision: str | None = (
    "f4a9c2d7b61e"
)

branch_labels: (
    str
    | Sequence[str]
    | None
) = None

depends_on: (
    str
    | Sequence[str]
    | None
) = None


def upgrade() -> None:
    op.add_column(
        "live_trading_policies",
        sa.Column(
            "dry_run_generation",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
    )

    op.add_column(
        "live_trading_policies",
        sa.Column(
            "dry_run_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_check_constraint(
        (
            "ck_live_trading_policies_"
            "dry_run_generation_positive"
        ),
        "live_trading_policies",
        "dry_run_generation >= 1",
    )

    op.execute(
        sa.text(
            """
            UPDATE live_trading_policies
            SET dry_run_started_at = COALESCE(
                updated_at,
                created_at,
                NOW()
            )
            WHERE mode = 'DRY_RUN'
              AND dry_run_started_at IS NULL
            """
        )
    )

    op.add_column(
        "live_copy_orders",
        sa.Column(
            "generation",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
    )

    op.create_check_constraint(
        (
            "ck_live_copy_orders_"
            "generation_positive"
        ),
        "live_copy_orders",
        "generation >= 1",
    )

    op.create_index(
        op.f(
            "ix_live_copy_orders_generation"
        ),
        "live_copy_orders",
        ["generation"],
        unique=False,
    )

    op.add_column(
        "live_positions",
        sa.Column(
            "generation",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
    )

    op.create_check_constraint(
        (
            "ck_live_positions_"
            "generation_positive"
        ),
        "live_positions",
        "generation >= 1",
    )

    op.create_index(
        op.f(
            "ix_live_positions_generation"
        ),
        "live_positions",
        ["generation"],
        unique=False,
    )

    op.drop_constraint(
        "uq_live_positions_mode_token",
        "live_positions",
        type_="unique",
    )

    op.create_unique_constraint(
        (
            "uq_live_positions_"
            "mode_generation_token"
        ),
        "live_positions",
        [
            "mode",
            "generation",
            "token_mint",
        ],
    )

    op.add_column(
        "live_trading_events",
        sa.Column(
            "generation",
            sa.Integer(),
            nullable=True,
        ),
    )

    op.create_check_constraint(
        (
            "ck_live_trading_events_"
            "generation_positive"
        ),
        "live_trading_events",
        (
            "generation IS NULL "
            "OR generation >= 1"
        ),
    )

    op.create_index(
        op.f(
            "ix_live_trading_events_generation"
        ),
        "live_trading_events",
        ["generation"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f(
            "ix_live_trading_events_generation"
        ),
        table_name=(
            "live_trading_events"
        ),
    )

    op.drop_constraint(
        (
            "ck_live_trading_events_"
            "generation_positive"
        ),
        "live_trading_events",
        type_="check",
    )

    op.drop_column(
        "live_trading_events",
        "generation",
    )

    op.drop_constraint(
        (
            "uq_live_positions_"
            "mode_generation_token"
        ),
        "live_positions",
        type_="unique",
    )

    op.create_unique_constraint(
        "uq_live_positions_mode_token",
        "live_positions",
        ["mode", "token_mint"],
    )

    op.drop_index(
        op.f(
            "ix_live_positions_generation"
        ),
        table_name="live_positions",
    )

    op.drop_constraint(
        (
            "ck_live_positions_"
            "generation_positive"
        ),
        "live_positions",
        type_="check",
    )

    op.drop_column(
        "live_positions",
        "generation",
    )

    op.drop_index(
        op.f(
            "ix_live_copy_orders_generation"
        ),
        table_name="live_copy_orders",
    )

    op.drop_constraint(
        (
            "ck_live_copy_orders_"
            "generation_positive"
        ),
        "live_copy_orders",
        type_="check",
    )

    op.drop_column(
        "live_copy_orders",
        "generation",
    )

    op.drop_constraint(
        (
            "ck_live_trading_policies_"
            "dry_run_generation_positive"
        ),
        "live_trading_policies",
        type_="check",
    )

    op.drop_column(
        "live_trading_policies",
        "dry_run_started_at",
    )

    op.drop_column(
        "live_trading_policies",
        "dry_run_generation",
    )
