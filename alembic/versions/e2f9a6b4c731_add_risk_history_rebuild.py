"""add risk history rebuild checkpoint

Revision ID: e2f9a6b4c731
Revises: d8a4f7c2e915
Create Date: 2026-07-20
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "e2f9a6b4c731"
down_revision: str | None = "d8a4f7c2e915"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "live_risk_states",
        sa.Column(
            "loss_streak_reset_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_live_risk_states_loss_streak_reset_at",
        "live_risk_states",
        ["loss_streak_reset_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_live_risk_states_loss_streak_reset_at",
        table_name="live_risk_states",
    )
    op.drop_column(
        "live_risk_states",
        "loss_streak_reset_at",
    )
