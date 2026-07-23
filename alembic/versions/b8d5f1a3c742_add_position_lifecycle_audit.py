"""add position lifecycle audit

Revision ID: b8d5f1a3c742
Revises: a7c4e9b2f136
Create Date: 2026-07-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "b8d5f1a3c742"
down_revision: str | None = "a7c4e9b2f136"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_position_lifecycle_audit_runs",
        sa.Column(
            "id",
            sa.Integer(),
            primary_key=True,
        ),
        sa.Column(
            "run_id",
            sa.String(length=36),
            nullable=False,
        ),
        sa.Column(
            "wallet_address",
            sa.String(length=64),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=24),
            server_default="COMPLETED",
            nullable=False,
        ),
        sa.Column(
            "parameters",
            sa.JSON(),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "safety",
            sa.JSON(),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "baseline_metrics",
            sa.JSON(),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "lifecycle_summary",
            sa.JSON(),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "position_details",
            sa.JSON(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "scenario_results",
            sa.JSON(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "diagnoses",
            sa.JSON(),
            server_default="[]",
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_candidate_position_lifecycle_audit_runs_id",
        "candidate_position_lifecycle_audit_runs",
        ["id"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_position_lifecycle_audit_runs_run_id",
        "candidate_position_lifecycle_audit_runs",
        ["run_id"],
        unique=True,
    )
    op.create_index(
        "ix_candidate_position_lifecycle_audit_runs_wallet_address",
        "candidate_position_lifecycle_audit_runs",
        ["wallet_address"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_position_lifecycle_audit_runs_status",
        "candidate_position_lifecycle_audit_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_position_lifecycle_audit_runs_started_at",
        "candidate_position_lifecycle_audit_runs",
        ["started_at"],
        unique=False,
    )


def downgrade() -> None:
    for index_name in (
        "ix_candidate_position_lifecycle_audit_runs_started_at",
        "ix_candidate_position_lifecycle_audit_runs_status",
        "ix_candidate_position_lifecycle_audit_runs_wallet_address",
        "ix_candidate_position_lifecycle_audit_runs_run_id",
        "ix_candidate_position_lifecycle_audit_runs_id",
    ):
        op.drop_index(
            index_name,
            table_name=(
                "candidate_position_lifecycle_audit_runs"
            ),
        )

    op.drop_table(
        "candidate_position_lifecycle_audit_runs"
    )
