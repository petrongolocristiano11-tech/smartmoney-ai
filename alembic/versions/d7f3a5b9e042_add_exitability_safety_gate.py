"""add exitability safety gate

Revision ID: d7f3a5b9e042
Revises: c6e2f4a8d931
Create Date: 2026-07-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "d7f3a5b9e042"
down_revision: str | None = "c6e2f4a8d931"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_exitability_gate_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="COMPLETED", nullable=False),
        sa.Column("parameters", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("safety", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("summary", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("wallet_results", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    for column_name, unique in (
        ("id", False),
        ("run_id", True),
        ("status", False),
        ("started_at", False),
    ):
        op.create_index(
            f"ix_candidate_exitability_gate_runs_{column_name}",
            "candidate_exitability_gate_runs",
            [column_name],
            unique=unique,
        )

    columns = (
        sa.Column("exitability_gate_status", sa.String(length=24), server_default="NON_ANALIZZATO", nullable=False),
        sa.Column("exitability_gate_score", sa.Float(), server_default="0", nullable=False),
        sa.Column("exitability_gate_eligible", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("exitability_gate_reasons", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("exitability_gate_calculated_at", sa.DateTime(timezone=True), nullable=True),
    )
    for column in columns:
        op.add_column("discovered_wallets", column)

    for column_name in (
        "exitability_gate_status",
        "exitability_gate_score",
        "exitability_gate_eligible",
        "exitability_gate_calculated_at",
    ):
        op.create_index(
            f"ix_discovered_wallets_{column_name}",
            "discovered_wallets",
            [column_name],
            unique=False,
        )


def downgrade() -> None:
    for column_name in (
        "exitability_gate_calculated_at",
        "exitability_gate_eligible",
        "exitability_gate_score",
        "exitability_gate_status",
    ):
        op.drop_index(
            f"ix_discovered_wallets_{column_name}",
            table_name="discovered_wallets",
        )
    for column_name in (
        "exitability_gate_calculated_at",
        "exitability_gate_reasons",
        "exitability_gate_eligible",
        "exitability_gate_score",
        "exitability_gate_status",
    ):
        op.drop_column("discovered_wallets", column_name)

    for column_name in ("started_at", "status", "run_id", "id"):
        op.drop_index(
            f"ix_candidate_exitability_gate_runs_{column_name}",
            table_name="candidate_exitability_gate_runs",
        )
    op.drop_table("candidate_exitability_gate_runs")
