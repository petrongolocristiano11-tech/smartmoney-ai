"""Add realized PnL to paper orders

Revision ID: c7e1b4f5a902
Revises: 9f2a7c4d8e61
Create Date: 2026-07-15
"""

from typing import (
    Sequence,
    Union,
)

from alembic import op
import sqlalchemy as sa


revision: str = "c7e1b4f5a902"

down_revision: Union[
    str,
    Sequence[str],
    None,
] = "9f2a7c4d8e61"

branch_labels: Union[
    str,
    Sequence[str],
    None,
] = None

depends_on: Union[
    str,
    Sequence[str],
    None,
] = None


def upgrade() -> None:
    op.add_column(
        "paper_orders",
        sa.Column(
            "realized_pnl_sol",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "paper_orders",
        "realized_pnl_sol",
    ) 