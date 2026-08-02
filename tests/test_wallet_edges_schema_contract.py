import ast
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from backend.app.models.wallet_edge import WalletEdge

MIGRATION_PATH = Path(
    "alembic/versions/d2a4b7c0e186_add_wallet_edges_schema_contract.py"
)
EXPECTED_INDEXES = {
    "ix_wallet_edges_id": ["id"],
    "ix_wallet_edges_source_wallet": ["source_wallet"],
    "ix_wallet_edges_target_wallet": ["target_wallet"],
}


def load_migration_module():
    spec = importlib.util.spec_from_file_location(
        "wallet_edges_schema_contract_migration",
        MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_migration(module, connection, function_name: str):
    original_op = module.op
    module.op = Operations(MigrationContext.configure(connection))
    try:
        getattr(module, function_name)()
    finally:
        module.op = original_op


def assert_wallet_edges_contract(connection):
    inspector = sa.inspect(connection)
    assert inspector.has_table("wallet_edges")

    columns = {
        item["name"]: item for item in inspector.get_columns("wallet_edges")
    }
    assert list(columns) == [
        "id",
        "source_wallet",
        "target_wallet",
        "token_mint",
        "edge_type",
        "strength",
        "created_at",
    ]
    assert columns["id"]["nullable"] is False
    assert columns["source_wallet"]["nullable"] is False
    assert columns["target_wallet"]["nullable"] is False
    assert columns["token_mint"]["nullable"] is True
    assert columns["edge_type"]["nullable"] is False
    assert columns["strength"]["nullable"] is False
    assert columns["created_at"]["nullable"] is False
    assert columns["edge_type"].get("default") is None
    assert columns["strength"].get("default") is None
    assert columns["created_at"].get("default") is not None

    assert isinstance(columns["id"]["type"], sa.Integer)
    assert isinstance(columns["source_wallet"]["type"], sa.String)
    assert columns["source_wallet"]["type"].length == 64
    assert isinstance(columns["target_wallet"]["type"], sa.String)
    assert columns["target_wallet"]["type"].length == 64
    assert isinstance(columns["token_mint"]["type"], sa.String)
    assert columns["token_mint"]["type"].length == 64
    assert isinstance(columns["edge_type"]["type"], sa.String)
    assert columns["edge_type"]["type"].length == 30
    assert isinstance(columns["strength"]["type"], sa.Float)
    assert isinstance(columns["created_at"]["type"], sa.DateTime)

    primary_key = inspector.get_pk_constraint("wallet_edges")
    assert primary_key["constrained_columns"] == ["id"]

    indexes = {
        item["name"]: item for item in inspector.get_indexes("wallet_edges")
    }
    assert set(indexes) == set(EXPECTED_INDEXES)
    for name, expected_columns in EXPECTED_INDEXES.items():
        assert indexes[name]["column_names"] == expected_columns
        assert not indexes[name]["unique"]

    assert inspector.get_foreign_keys("wallet_edges") == []
    assert inspector.get_unique_constraints("wallet_edges") == []
    assert inspector.get_check_constraints("wallet_edges") == []


def test_wallet_edge_model_declares_the_database_contract():
    table = WalletEdge.__table__
    assert table.name == "wallet_edges"
    assert list(table.columns.keys()) == [
        "id",
        "source_wallet",
        "target_wallet",
        "token_mint",
        "edge_type",
        "strength",
        "created_at",
    ]
    assert table.c.id.primary_key is True
    assert table.c.id.nullable is False
    assert table.c.source_wallet.nullable is False
    assert table.c.target_wallet.nullable is False
    assert table.c.token_mint.nullable is True
    assert table.c.edge_type.nullable is False
    assert table.c.strength.nullable is False
    assert table.c.created_at.nullable is False
    assert table.c.edge_type.default.arg == "SHARED_TOKEN"
    assert table.c.strength.default.arg == 0
    assert table.c.created_at.server_default is not None
    assert {index.name for index in table.indexes} == set(EXPECTED_INDEXES)


def test_wallet_graph_service_contains_no_runtime_ddl():
    path = Path("backend/app/services/wallet_graph_engine.py")
    source = path.read_text()
    tree = ast.parse(source)

    assert "ensure_wallet_edges_table" not in source
    assert "CREATE TABLE" not in source.upper()
    assert "sqlalchemy import text" not in source

    function_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    assert function_names == {"save_wallet_edge"}


def test_migration_is_consecutive_and_becomes_the_only_head():
    text = MIGRATION_PATH.read_text()
    assert 'revision: str = "d2a4b7c0e186"' in text
    assert 'down_revision: Union[str, Sequence[str], None] = "c1f3a6b9d075"' in text

    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["d2a4b7c0e186"]
    assert script.get_revision("d2a4b7c0e186").down_revision == "c1f3a6b9d075"


def test_upgrade_creates_exact_table_without_touching_other_tables():
    module = load_migration_module()
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            sa.text("CREATE TABLE sentinel_table (id INTEGER PRIMARY KEY)")
        )
        run_migration(module, connection, "upgrade")
        assert_wallet_edges_contract(connection)
        assert sa.inspect(connection).has_table("sentinel_table")

        run_migration(module, connection, "downgrade")
        inspector = sa.inspect(connection)
        assert not inspector.has_table("wallet_edges")
        assert inspector.has_table("sentinel_table")
    engine.dispose()


def test_upgrade_normalizes_legacy_runtime_table_and_preserves_rows():
    module = load_migration_module()
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                CREATE TABLE wallet_edges (
                    id INTEGER PRIMARY KEY,
                    source_wallet VARCHAR(64),
                    target_wallet VARCHAR(64),
                    token_mint VARCHAR(64),
                    edge_type VARCHAR(30) DEFAULT 'SHARED_TOKEN',
                    strength FLOAT DEFAULT 0,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )
        connection.execute(
            sa.text(
                """
                INSERT INTO wallet_edges (
                    id, source_wallet, target_wallet, token_mint,
                    edge_type, strength, created_at
                ) VALUES (
                    7, 'wallet-a', 'wallet-b', 'token-a', NULL, NULL, NULL
                )
                """
            )
        )

        run_migration(module, connection, "upgrade")
        assert_wallet_edges_contract(connection)
        row = connection.execute(
            sa.text(
                "SELECT id, source_wallet, target_wallet, token_mint, "
                "edge_type, strength, created_at FROM wallet_edges"
            )
        ).mappings().one()
        assert row["id"] == 7
        assert row["source_wallet"] == "wallet-a"
        assert row["target_wallet"] == "wallet-b"
        assert row["token_mint"] == "token-a"
        assert row["edge_type"] == "SHARED_TOKEN"
        assert row["strength"] == 0
        assert row["created_at"] is not None

        with pytest.raises(RuntimeError, match="Downgrade bloccato"):
            run_migration(module, connection, "downgrade")
        assert sa.inspect(connection).has_table("wallet_edges")
    engine.dispose()


def test_upgrade_adds_missing_optional_columns_without_losing_data():
    module = load_migration_module()
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                CREATE TABLE wallet_edges (
                    id INTEGER PRIMARY KEY,
                    source_wallet VARCHAR(64) NOT NULL,
                    target_wallet VARCHAR(64) NOT NULL
                )
                """
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO wallet_edges (id, source_wallet, target_wallet) "
                "VALUES (1, 'source', 'target')"
            )
        )

        run_migration(module, connection, "upgrade")
        assert_wallet_edges_contract(connection)
        row = connection.execute(
            sa.text(
                "SELECT id, source_wallet, target_wallet, token_mint, "
                "edge_type, strength, created_at FROM wallet_edges"
            )
        ).mappings().one()
        assert row["id"] == 1
        assert row["source_wallet"] == "source"
        assert row["target_wallet"] == "target"
        assert row["token_mint"] is None
        assert row["edge_type"] == "SHARED_TOKEN"
        assert row["strength"] == 0
        assert row["created_at"] is not None
    engine.dispose()


def test_upgrade_rebuilds_an_empty_partial_table():
    module = load_migration_module()
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE wallet_edges (legacy_id INTEGER)"))
        run_migration(module, connection, "upgrade")
        assert_wallet_edges_contract(connection)
    engine.dispose()


def test_upgrade_refuses_populated_table_missing_core_columns():
    module = load_migration_module()
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(sa.text("CREATE TABLE wallet_edges (legacy_id INTEGER)"))
        connection.execute(
            sa.text("INSERT INTO wallet_edges (legacy_id) VALUES (1)")
        )
        with pytest.raises(RuntimeError, match="colonne fondamentali"):
            run_migration(module, connection, "upgrade")
    engine.dispose()


def test_upgrade_refuses_to_invent_missing_wallet_addresses():
    module = load_migration_module()
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                """
                CREATE TABLE wallet_edges (
                    id INTEGER PRIMARY KEY,
                    source_wallet VARCHAR(64),
                    target_wallet VARCHAR(64),
                    token_mint VARCHAR(64),
                    edge_type VARCHAR(30),
                    strength FLOAT,
                    created_at DATETIME
                )
                """
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO wallet_edges "
                "(id, source_wallet, target_wallet) VALUES (1, NULL, 'target')"
            )
        )
        with pytest.raises(RuntimeError, match="nessun valore è stato inventato"):
            run_migration(module, connection, "upgrade")
    engine.dispose()
