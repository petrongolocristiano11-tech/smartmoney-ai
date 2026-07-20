"""add wallet sample threshold

Revision ID: c7d9e1f2a603
Revises: b6f2e8c9d401
Create Date: 2026-07-20
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c7d9e1f2a603"
down_revision: str | None = "b6f2e8c9d401"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "live_platform_configs",
        sa.Column(
            "min_wallet_closed_trades",
            sa.Integer(),
            server_default="3",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_live_platform_min_wallet_sample",
        "live_platform_configs",
        "min_wallet_closed_trades BETWEEN 1 AND 100",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_live_platform_min_wallet_sample",
        "live_platform_configs",
        type_="check",
    )
    op.drop_column(
        "live_platform_configs",
        "min_wallet_closed_trades",
    )
