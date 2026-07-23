"""add exit price coverage audit

Revision ID: c6e2f4a8d931
Revises: b8d5f1a3c742
Create Date: 2026-07-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c6e2f4a8d931"
down_revision: str | None = "b8d5f1a3c742"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_exit_price_audit_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_id", sa.String(length=36), nullable=False),
        sa.Column("wallet_address", sa.String(length=64), nullable=False),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default="COMPLETED",
            nullable=False,
        ),
        sa.Column(
            "readiness_status",
            sa.String(length=24),
            server_default="BLOCKED",
            nullable=False,
        ),
        sa.Column(
            "readiness_score",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("parameters", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("safety", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("summary", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("scenario_results", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("position_results", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("diagnoses", sa.JSON(), server_default="[]", nullable=False),
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
        ("wallet_address", False),
        ("status", False),
        ("readiness_status", False),
        ("readiness_score", False),
        ("started_at", False),
    ):
        op.create_index(
            f"ix_candidate_exit_price_audit_runs_{column_name}",
            "candidate_exit_price_audit_runs",
            [column_name],
            unique=unique,
        )

    columns = (
        sa.Column(
            "exit_price_coverage_status",
            sa.String(length=24),
            server_default="NON_ANALIZZATO",
            nullable=False,
        ),
        sa.Column(
            "exit_price_coverage_score",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "exit_price_local_observable_percent",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "exit_price_current_route_percent",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "exit_price_temporal_execution_percent",
            sa.Float(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "exit_price_audit_reasons",
            sa.JSON(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "latest_exit_price_audit_run_id",
            sa.String(length=36),
            nullable=True,
        ),
        sa.Column(
            "exit_price_audit_calculated_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    for column in columns:
        op.add_column("discovered_wallets", column)

    for column_name in (
        "exit_price_coverage_status",
        "exit_price_coverage_score",
        "latest_exit_price_audit_run_id",
        "exit_price_audit_calculated_at",
    ):
        op.create_index(
            f"ix_discovered_wallets_{column_name}",
            "discovered_wallets",
            [column_name],
            unique=False,
        )


def downgrade() -> None:
    for column_name in (
        "exit_price_audit_calculated_at",
        "latest_exit_price_audit_run_id",
        "exit_price_coverage_score",
        "exit_price_coverage_status",
    ):
        op.drop_index(
            f"ix_discovered_wallets_{column_name}",
            table_name="discovered_wallets",
        )

    for column_name in (
        "exit_price_audit_calculated_at",
        "latest_exit_price_audit_run_id",
        "exit_price_audit_reasons",
        "exit_price_temporal_execution_percent",
        "exit_price_current_route_percent",
        "exit_price_local_observable_percent",
        "exit_price_coverage_score",
        "exit_price_coverage_status",
    ):
        op.drop_column("discovered_wallets", column_name)

    for column_name in (
        "started_at",
        "readiness_score",
        "readiness_status",
        "status",
        "wallet_address",
        "run_id",
        "id",
    ):
        op.drop_index(
            f"ix_candidate_exit_price_audit_runs_{column_name}",
            table_name="candidate_exit_price_audit_runs",
        )
    op.drop_table("candidate_exit_price_audit_runs")
