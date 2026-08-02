"""add wallet edges schema contract

Revision ID: d2a4b7c0e186
Revises: c1f3a6b9d075
Create Date: 2026-08-02 12:45:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d2a4b7c0e186"
down_revision: Union[str, Sequence[str], None] = "c1f3a6b9d075"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "wallet_edges"
EXPECTED_COLUMNS = {
    "id",
    "source_wallet",
    "target_wallet",
    "token_mint",
    "edge_type",
    "strength",
    "created_at",
}
CORE_COLUMNS = {"id", "source_wallet", "target_wallet"}
INDEXES = {
    "ix_wallet_edges_id": ["id"],
    "ix_wallet_edges_source_wallet": ["source_wallet"],
    "ix_wallet_edges_target_wallet": ["target_wallet"],
}


def _inspector(bind):
    return sa.inspect(bind)


def _table_exists(bind) -> bool:
    return _inspector(bind).has_table(TABLE_NAME)


def _row_count(bind) -> int:
    return int(
        bind.execute(sa.text(f'SELECT COUNT(*) FROM "{TABLE_NAME}"')).scalar_one()
    )


def _create_wallet_edges_table() -> None:
    op.create_table(
        TABLE_NAME,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("source_wallet", sa.String(length=64), nullable=False),
        sa.Column("target_wallet", sa.String(length=64), nullable=False),
        sa.Column("token_mint", sa.String(length=64), nullable=True),
        sa.Column("edge_type", sa.String(length=30), nullable=False),
        sa.Column("strength", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    for name, columns in INDEXES.items():
        op.create_index(name, TABLE_NAME, columns, unique=False)


def _assert_no_unrecoverable_shape(bind, columns: dict[str, dict], row_count: int) -> None:
    names = set(columns)
    missing_core = CORE_COLUMNS - names
    extra_columns = names - EXPECTED_COLUMNS

    if missing_core:
        if row_count == 0:
            return
        raise RuntimeError(
            "wallet_edges esiste con dati ma senza colonne fondamentali: "
            + ", ".join(sorted(missing_core))
        )

    if extra_columns:
        raise RuntimeError(
            "wallet_edges contiene colonne non previste; migrazione interrotta per "
            "evitare modifiche distruttive: "
            + ", ".join(sorted(extra_columns))
        )

    pk_columns = _inspector(bind).get_pk_constraint(TABLE_NAME).get(
        "constrained_columns"
    ) or []
    if pk_columns != ["id"]:
        if row_count == 0:
            return
        raise RuntimeError(
            "wallet_edges contiene dati ma la primary key non è esattamente id"
        )

    foreign_keys = _inspector(bind).get_foreign_keys(TABLE_NAME)
    if foreign_keys:
        raise RuntimeError(
            "wallet_edges contiene foreign key non previste; migrazione interrotta"
        )

    unique_constraints = _inspector(bind).get_unique_constraints(TABLE_NAME)
    if unique_constraints:
        raise RuntimeError(
            "wallet_edges contiene unique constraint non previste; migrazione interrotta"
        )

    check_constraints = _inspector(bind).get_check_constraints(TABLE_NAME)
    if check_constraints:
        raise RuntimeError(
            "wallet_edges contiene check constraint non previste; migrazione interrotta"
        )


def _rebuild_if_empty_and_unrecoverable(bind, columns: dict[str, dict]) -> bool:
    row_count = _row_count(bind)
    names = set(columns)
    pk_columns = _inspector(bind).get_pk_constraint(TABLE_NAME).get(
        "constrained_columns"
    ) or []
    if row_count == 0 and (CORE_COLUMNS - names or pk_columns != ["id"]):
        op.drop_table(TABLE_NAME)
        _create_wallet_edges_table()
        return True
    return False


def _add_missing_optional_columns(bind) -> None:
    names = {item["name"] for item in _inspector(bind).get_columns(TABLE_NAME)}
    if "token_mint" not in names:
        op.add_column(
            TABLE_NAME,
            sa.Column("token_mint", sa.String(length=64), nullable=True),
        )
    if "edge_type" not in names:
        op.add_column(
            TABLE_NAME,
            sa.Column("edge_type", sa.String(length=30), nullable=True),
        )
    if "strength" not in names:
        op.add_column(
            TABLE_NAME,
            sa.Column("strength", sa.Float(), nullable=True),
        )
    if "created_at" not in names:
        op.add_column(
            TABLE_NAME,
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )


def _assert_data_can_be_normalized(bind) -> None:
    invalid_wallets = int(
        bind.execute(
            sa.text(
                f'SELECT COUNT(*) FROM "{TABLE_NAME}" '
                "WHERE source_wallet IS NULL OR target_wallet IS NULL"
            )
        ).scalar_one()
    )
    if invalid_wallets:
        raise RuntimeError(
            "wallet_edges contiene righe con source_wallet o target_wallet NULL; "
            "nessun valore è stato inventato"
        )

    duplicate_ids = int(
        bind.execute(
            sa.text(
                f'SELECT COUNT(*) FROM ('
                f'SELECT id FROM "{TABLE_NAME}" '
                "GROUP BY id HAVING COUNT(*) > 1"
                ") AS duplicated_wallet_edge_ids"
            )
        ).scalar_one()
    )
    null_ids = int(
        bind.execute(
            sa.text(
                f'SELECT COUNT(*) FROM "{TABLE_NAME}" WHERE id IS NULL'
            )
        ).scalar_one()
    )
    if duplicate_ids or null_ids:
        raise RuntimeError(
            "wallet_edges contiene id NULL o duplicati; migrazione interrotta"
        )

    length_checks = {
        "source_wallet": 64,
        "target_wallet": 64,
        "token_mint": 64,
        "edge_type": 30,
    }
    for column, maximum in length_checks.items():
        longest = bind.execute(
            sa.text(
                f'SELECT MAX(LENGTH("{column}")) FROM "{TABLE_NAME}"'
            )
        ).scalar_one()
        if longest is not None and int(longest) > maximum:
            raise RuntimeError(
                f"wallet_edges.{column} contiene valori oltre {maximum} caratteri"
            )


def _backfill_safe_defaults(bind) -> None:
    bind.execute(
        sa.text(
            f'UPDATE "{TABLE_NAME}" '
            "SET edge_type = 'SHARED_TOKEN' WHERE edge_type IS NULL"
        )
    )
    bind.execute(
        sa.text(
            f'UPDATE "{TABLE_NAME}" SET strength = 0 WHERE strength IS NULL'
        )
    )
    bind.execute(
        sa.text(
            f'UPDATE "{TABLE_NAME}" '
            "SET created_at = CURRENT_TIMESTAMP WHERE created_at IS NULL"
        )
    )


def _normalize_columns(bind) -> None:
    columns = {
        item["name"]: item for item in _inspector(bind).get_columns(TABLE_NAME)
    }
    with op.batch_alter_table(TABLE_NAME) as batch_op:
        batch_op.alter_column(
            "id",
            existing_type=columns["id"]["type"],
            type_=sa.Integer(),
            nullable=False,
        )
        batch_op.alter_column(
            "source_wallet",
            existing_type=columns["source_wallet"]["type"],
            type_=sa.String(length=64),
            nullable=False,
        )
        batch_op.alter_column(
            "target_wallet",
            existing_type=columns["target_wallet"]["type"],
            type_=sa.String(length=64),
            nullable=False,
        )
        batch_op.alter_column(
            "token_mint",
            existing_type=columns["token_mint"]["type"],
            type_=sa.String(length=64),
            nullable=True,
        )
        batch_op.alter_column(
            "edge_type",
            existing_type=columns["edge_type"]["type"],
            type_=sa.String(length=30),
            nullable=False,
            server_default=None,
        )
        batch_op.alter_column(
            "strength",
            existing_type=columns["strength"]["type"],
            type_=sa.Float(),
            nullable=False,
            server_default=None,
        )
        batch_op.alter_column(
            "created_at",
            existing_type=columns["created_at"]["type"],
            type_=sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        )


def _ensure_indexes(bind) -> None:
    indexes = {
        item["name"]: item for item in _inspector(bind).get_indexes(TABLE_NAME)
    }
    for name, columns in INDEXES.items():
        existing = indexes.get(name)
        if existing is not None:
            if existing.get("column_names") != columns or existing.get("unique"):
                raise RuntimeError(
                    f"Indice {name} esistente ma incompatibile con il modello"
                )
            continue
        op.create_index(name, TABLE_NAME, columns, unique=False)


def upgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind):
        _create_wallet_edges_table()
        return

    columns = {
        item["name"]: item for item in _inspector(bind).get_columns(TABLE_NAME)
    }
    row_count = _row_count(bind)
    _assert_no_unrecoverable_shape(bind, columns, row_count)
    if _rebuild_if_empty_and_unrecoverable(bind, columns):
        return

    _add_missing_optional_columns(bind)
    _assert_data_can_be_normalized(bind)
    _backfill_safe_defaults(bind)
    _normalize_columns(bind)
    _ensure_indexes(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if not _table_exists(bind):
        return

    if _row_count(bind) > 0:
        raise RuntimeError(
            "Downgrade bloccato: wallet_edges contiene dati. "
            "Esportare o rimuovere consapevolmente i dati prima del rollback."
        )

    existing_indexes = {
        item["name"] for item in _inspector(bind).get_indexes(TABLE_NAME)
    }
    for name in INDEXES:
        if name in existing_indexes:
            op.drop_index(name, table_name=TABLE_NAME)
    op.drop_table(TABLE_NAME)
