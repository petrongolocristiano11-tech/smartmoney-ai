"""add live worker state

Revision ID: f4a9c2d7b61e
Revises: e91c4b7a2f10
Create Date: 2026-07-19
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "f4a9c2d7b61e"

down_revision: str | None = (
    "e91c4b7a2f10"
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
    op.create_table(
        "live_trading_worker_states",
        sa.Column(
            "id",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default="STOPPED",
            nullable=False,
        ),
        sa.Column(
            "worker_id",
            sa.String(length=160),
            nullable=True,
        ),
        sa.Column(
            "lease_owner",
            sa.String(length=160),
            nullable=True,
        ),
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "active_wallets",
            sa.JSON(),
            server_default=sa.text(
                "'[]'::json"
            ),
            nullable=False,
        ),
        sa.Column(
            "monitored_wallets",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "active_subscriptions",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "queue_depth",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "reconnect_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "signatures_received",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "signatures_processed",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "signatures_failed",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "signatures_dropped",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
        sa.Column(
            "last_latency_ms",
            sa.Float(),
            nullable=True,
        ),
        sa.Column(
            "config_fingerprint",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "last_signature",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "last_error_code",
            sa.String(length=100),
            nullable=True,
        ),
        sa.Column(
            "last_error_message",
            sa.Text(),
            nullable=True,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "connected_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_message_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_trade_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_error_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "id = 1",
            name=(
                "ck_live_trading_worker_"
                "singleton"
            ),
        ),
        sa.CheckConstraint(
            "status IN ("
            "'STOPPED', "
            "'STARTING', "
            "'IDLE', "
            "'CONNECTING', "
            "'RUNNING', "
            "'DEGRADED', "
            "'ERROR'"
            ")",
            name=(
                "ck_live_trading_worker_"
                "status"
            ),
        ),
        sa.CheckConstraint(
            "monitored_wallets >= 0",
            name=(
                "ck_live_trading_worker_"
                "monitored_wallets"
            ),
        ),
        sa.CheckConstraint(
            "active_subscriptions >= 0",
            name=(
                "ck_live_trading_worker_"
                "active_subscriptions"
            ),
        ),
        sa.CheckConstraint(
            "queue_depth >= 0",
            name=(
                "ck_live_trading_worker_"
                "queue_depth"
            ),
        ),
        sa.CheckConstraint(
            "reconnect_count >= 0",
            name=(
                "ck_live_trading_worker_"
                "reconnect_count"
            ),
        ),
        sa.CheckConstraint(
            "signatures_received >= 0",
            name=(
                "ck_live_trading_worker_"
                "received"
            ),
        ),
        sa.CheckConstraint(
            "signatures_processed >= 0",
            name=(
                "ck_live_trading_worker_"
                "processed"
            ),
        ),
        sa.CheckConstraint(
            "signatures_failed >= 0",
            name=(
                "ck_live_trading_worker_"
                "failed"
            ),
        ),
        sa.CheckConstraint(
            "signatures_dropped >= 0",
            name=(
                "ck_live_trading_worker_"
                "dropped"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "id"
        ),
    )

    op.create_index(
        op.f(
            "ix_live_trading_worker_"
            "states_status"
        ),
        "live_trading_worker_states",
        ["status"],
        unique=False,
    )

    op.create_index(
        op.f(
            "ix_live_trading_worker_"
            "states_lease_owner"
        ),
        "live_trading_worker_states",
        ["lease_owner"],
        unique=False,
    )

    op.create_index(
        op.f(
            "ix_live_trading_worker_"
            "states_lease_expires_at"
        ),
        "live_trading_worker_states",
        ["lease_expires_at"],
        unique=False,
    )

    op.create_index(
        op.f(
            "ix_live_trading_worker_"
            "states_heartbeat_at"
        ),
        "live_trading_worker_states",
        ["heartbeat_at"],
        unique=False,
    )

    op.execute(
        sa.text(
            """
            INSERT INTO live_trading_worker_states (
                id,
                status,
                active_wallets,
                monitored_wallets,
                active_subscriptions,
                queue_depth,
                reconnect_count,
                signatures_received,
                signatures_processed,
                signatures_failed,
                signatures_dropped
            )
            VALUES (
                1,
                'STOPPED',
                '[]'::json,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0
            )
            ON CONFLICT (id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.drop_table(
        "live_trading_worker_states"
    ) 