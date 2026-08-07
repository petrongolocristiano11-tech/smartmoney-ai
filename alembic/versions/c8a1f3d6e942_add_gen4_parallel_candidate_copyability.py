"""add Gen4 parallel qualified-candidate copyability campaigns

Revision ID: c8a1f3d6e942
Revises: b6f8d2e4c731
Create Date: 2026-08-07 21:30:00+00:00
"""

from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "c8a1f3d6e942"
down_revision: str | None = "b6f8d2e4c731"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


TABLE = "canonical_parser_gen4_copyability_campaigns"


def upgrade() -> None:
    op.add_column(
        TABLE,
        sa.Column(
            "campaign_role",
            sa.String(length=32),
            server_default="PRIMARY_FORWARD",
            nullable=False,
        ),
    )
    op.add_column(
        TABLE,
        sa.Column("candidate_key", sa.String(length=64), nullable=True),
    )
    op.add_column(
        TABLE,
        sa.Column(
            "selection_snapshot",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
    )

    bind = op.get_bind()
    bind.execute(
        sa.text(
            f"""
            UPDATE {TABLE}
            SET candidate_key = lpad(id::text, 64, '0')
            WHERE candidate_key IS NULL
            """
        )
    )

    op.alter_column(
        TABLE,
        "candidate_key",
        existing_type=sa.String(length=64),
        nullable=False,
    )
    op.drop_constraint(
        "uq_gen4_copy_campaign_forward",
        TABLE,
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_gen4_copy_campaign_candidate_key",
        TABLE,
        ["candidate_key"],
    )
    op.create_check_constraint(
        "ck_gen4_copy_campaign_role",
        TABLE,
        "campaign_role IN ('PRIMARY_FORWARD','QUALIFIED_CANDIDATE')",
    )
    op.create_check_constraint(
        "ck_gen4_copy_campaign_candidate_key",
        TABLE,
        "length(candidate_key) = 64",
    )
    op.create_index(
        "ix_gen4_copy_campaign_role_status",
        TABLE,
        ["campaign_role", "status"],
    )
    op.create_index(
        "uq_gen4_copy_primary_forward",
        TABLE,
        ["forward_campaign_db_id"],
        unique=True,
        postgresql_where=sa.text("campaign_role = 'PRIMARY_FORWARD'"),
    )

    op.alter_column(
        TABLE,
        "campaign_role",
        server_default=None,
    )
    op.alter_column(
        TABLE,
        "selection_snapshot",
        server_default=None,
    )


def downgrade() -> None:
    bind = op.get_bind()
    candidate_count = int(
        bind.execute(
            sa.text(
                f"""
                SELECT COUNT(*)
                FROM {TABLE}
                WHERE campaign_role <> 'PRIMARY_FORWARD'
                """
            )
        ).scalar_one()
        or 0
    )
    duplicate_forward_count = int(
        bind.execute(
            sa.text(
                f"""
                SELECT COUNT(*)
                FROM (
                    SELECT forward_campaign_db_id
                    FROM {TABLE}
                    GROUP BY forward_campaign_db_id
                    HAVING COUNT(*) > 1
                ) AS duplicated
                """
            )
        ).scalar_one()
        or 0
    )
    if candidate_count > 0 or duplicate_forward_count > 0:
        raise RuntimeError(
            "Downgrade M61 rifiutato: esistono campagne candidate parallele. "
            "Fermarle, esportarne le evidenze e rimuoverle esplicitamente prima del downgrade."
        )

    op.drop_index("uq_gen4_copy_primary_forward", table_name=TABLE)
    op.drop_index("ix_gen4_copy_campaign_role_status", table_name=TABLE)
    op.drop_constraint(
        "ck_gen4_copy_campaign_candidate_key",
        TABLE,
        type_="check",
    )
    op.drop_constraint(
        "ck_gen4_copy_campaign_role",
        TABLE,
        type_="check",
    )
    op.drop_constraint(
        "uq_gen4_copy_campaign_candidate_key",
        TABLE,
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_gen4_copy_campaign_forward",
        TABLE,
        ["forward_campaign_db_id"],
    )
    op.drop_column(TABLE, "selection_snapshot")
    op.drop_column(TABLE, "candidate_key")
    op.drop_column(TABLE, "campaign_role")
