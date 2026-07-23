"""add trade reconstruction audit

Revision ID: a7c4e9b2f136
Revises: f6a8d3c1e927
Create Date: 2026-07-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "a7c4e9b2f136"
down_revision: str | None = "f6a8d3c1e927"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "candidate_reconstruction_audit_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
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
            nullable=False,
            server_default="COMPLETED",
        ),
        sa.Column(
            "parameters",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "safety",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "baseline_metrics",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "exclusion_summary",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "excluded_trades",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "scenario_results",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "diagnoses",
            sa.JSON(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "run_id",
            name="uq_candidate_reconstruction_audit_run_id",
        ),
    )

    op.create_index(
        "ix_candidate_reconstruction_audit_run_id",
        "candidate_reconstruction_audit_runs",
        ["run_id"],
        unique=True,
    )
    op.create_index(
        "ix_candidate_reconstruction_audit_wallet",
        "candidate_reconstruction_audit_runs",
        ["wallet_address"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_reconstruction_audit_status",
        "candidate_reconstruction_audit_runs",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_candidate_reconstruction_audit_started_at",
        "candidate_reconstruction_audit_runs",
        ["started_at"],
        unique=False,
    )


def downgrade() -> None:
    for index_name in (
        "ix_candidate_reconstruction_audit_started_at",
        "ix_candidate_reconstruction_audit_status",
        "ix_candidate_reconstruction_audit_wallet",
        "ix_candidate_reconstruction_audit_run_id",
    ):
        op.drop_index(
            index_name,
            table_name="candidate_reconstruction_audit_runs",
        )

    op.drop_table(
        "candidate_reconstruction_audit_runs"
    )
