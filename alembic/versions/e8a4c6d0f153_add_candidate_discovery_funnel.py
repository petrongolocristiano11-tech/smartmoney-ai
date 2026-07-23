"""add candidate discovery funnel

Revision ID: e8a4c6d0f153
Revises: d7f3a5b9e042
Create Date: 2026-07-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "e8a4c6d0f153"
down_revision: str | None = "d7f3a5b9e042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_discovery_funnel_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default="COMPLETED",
            nullable=False,
        ),
        sa.Column("parameters", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("safety", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("summary", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("wallet_results", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("history_queue", sa.JSON(), server_default="[]", nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    for column_name, unique in (
        ("id", False),
        ("run_id", True),
        ("status", False),
        ("started_at", False),
    ):
        op.create_index(
            f"ix_candidate_discovery_funnel_runs_{column_name}",
            "candidate_discovery_funnel_runs",
            [column_name],
            unique=unique,
        )

    columns = (
        sa.Column(
            "discovery_funnel_status",
            sa.String(length=24),
            server_default="NEEDS_LOCAL_DATA",
            nullable=False,
        ),
        sa.Column(
            "discovery_funnel_score",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "discovery_funnel_priority",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "discovery_funnel_action",
            sa.String(length=40),
            server_default="RUN_CONTROLLED_HYDRATION",
            nullable=False,
        ),
        sa.Column(
            "discovery_funnel_reasons",
            sa.JSON(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "discovery_funnel_history_budget",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "discovery_funnel_calculated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    for column in columns:
        op.add_column("discovered_wallets", column)

    for column_name in (
        "discovery_funnel_status",
        "discovery_funnel_score",
        "discovery_funnel_priority",
        "discovery_funnel_calculated_at",
    ):
        op.create_index(
            f"ix_discovered_wallets_{column_name}",
            "discovered_wallets",
            [column_name],
            unique=False,
        )


def downgrade() -> None:
    for column_name in (
        "discovery_funnel_calculated_at",
        "discovery_funnel_priority",
        "discovery_funnel_score",
        "discovery_funnel_status",
    ):
        op.drop_index(
            f"ix_discovered_wallets_{column_name}",
            table_name="discovered_wallets",
        )
    for column_name in (
        "discovery_funnel_calculated_at",
        "discovery_funnel_history_budget",
        "discovery_funnel_reasons",
        "discovery_funnel_action",
        "discovery_funnel_priority",
        "discovery_funnel_score",
        "discovery_funnel_status",
    ):
        op.drop_column("discovered_wallets", column_name)

    for column_name in ("started_at", "status", "run_id", "id"):
        op.drop_index(
            f"ix_candidate_discovery_funnel_runs_{column_name}",
            table_name="candidate_discovery_funnel_runs",
        )
    op.drop_table("candidate_discovery_funnel_runs")
