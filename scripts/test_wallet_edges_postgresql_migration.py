"""PostgreSQL lifecycle verification for the wallet_edges Alembic repair.

The default mode creates isolated temporary databases, runs the real Alembic
chain, verifies upgrade/downgrade behavior, and removes the databases.
Use --current only after the local upgrade for a read-only schema check.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.engine import URL, make_url

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.config import settings

PREVIOUS_HEAD = "c1f3a6b9d075"
EXPECTED_HEAD = "d2a4b7c0e186"
EXPECTED_INDEXES = {
    "ix_wallet_edges_id": ["id"],
    "ix_wallet_edges_source_wallet": ["source_wallet"],
    "ix_wallet_edges_target_wallet": ["target_wallet"],
}


def _require_postgresql(url: URL) -> None:
    if not url.drivername.startswith("postgresql"):
        raise SystemExit(
            "Il verifier PostgreSQL richiede DATABASE_URL PostgreSQL."
        )


def _redact(text: str, url: URL) -> str:
    sanitized = text
    password = url.password
    if password:
        sanitized = sanitized.replace(password, "<REDACTED>")
    sanitized = sanitized.replace(
        url.render_as_string(hide_password=False),
        url.render_as_string(hide_password=True),
    )
    return sanitized


def _run_alembic(url: URL, *arguments: str, expect_success: bool = True):
    env = os.environ.copy()
    env["DATABASE_URL"] = url.render_as_string(hide_password=False)
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *arguments],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if expect_success and result.returncode != 0:
        output = _redact((result.stdout or "") + (result.stderr or ""), url)
        raise RuntimeError(
            f"Alembic {' '.join(arguments)} non riuscito:\n{output}"
        )
    if not expect_success and result.returncode == 0:
        raise RuntimeError(
            f"Alembic {' '.join(arguments)} doveva essere bloccato ma è riuscito"
        )
    return result


def _create_database(admin_engine: sa.Engine, name: str) -> None:
    with admin_engine.connect() as connection:
        connection.execute(sa.text(f'CREATE DATABASE "{name}"'))


def _drop_database(admin_engine: sa.Engine, name: str) -> None:
    with admin_engine.connect() as connection:
        connection.execute(
            sa.text(
                "SELECT pg_terminate_backend(pid) "
                "FROM pg_stat_activity "
                "WHERE datname = :name AND pid <> pg_backend_pid()"
            ),
            {"name": name},
        )
        connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}"'))


def _revision(connection: sa.Connection) -> str | None:
    inspector = sa.inspect(connection)
    if not inspector.has_table("alembic_version"):
        return None
    return connection.execute(
        sa.text("SELECT version_num FROM alembic_version")
    ).scalar_one_or_none()


def _assert_schema(connection: sa.Connection) -> None:
    inspector = sa.inspect(connection)
    if not inspector.has_table("wallet_edges"):
        raise AssertionError("wallet_edges assente")

    columns = {
        item["name"]: item for item in inspector.get_columns("wallet_edges")
    }
    expected_names = {
        "id",
        "source_wallet",
        "target_wallet",
        "token_mint",
        "edge_type",
        "strength",
        "created_at",
    }
    if set(columns) != expected_names:
        raise AssertionError(
            f"Colonne wallet_edges inattese: {sorted(columns)}"
        )

    expected_nullability = {
        "id": False,
        "source_wallet": False,
        "target_wallet": False,
        "token_mint": True,
        "edge_type": False,
        "strength": False,
        "created_at": False,
    }
    for name, nullable in expected_nullability.items():
        if columns[name]["nullable"] is not nullable:
            raise AssertionError(f"Nullability inattesa per wallet_edges.{name}")

    if not isinstance(columns["id"]["type"], sa.Integer):
        raise AssertionError("wallet_edges.id non è Integer")
    for name in ("source_wallet", "target_wallet", "token_mint"):
        if not isinstance(columns[name]["type"], sa.String):
            raise AssertionError(f"wallet_edges.{name} non è String")
        if columns[name]["type"].length != 64:
            raise AssertionError(f"Lunghezza inattesa per wallet_edges.{name}")
    if not isinstance(columns["edge_type"]["type"], sa.String):
        raise AssertionError("wallet_edges.edge_type non è String")
    if columns["edge_type"]["type"].length != 30:
        raise AssertionError("Lunghezza inattesa per wallet_edges.edge_type")
    if not isinstance(columns["strength"]["type"], sa.Float):
        raise AssertionError("wallet_edges.strength non è Float")
    if not isinstance(columns["created_at"]["type"], sa.DateTime):
        raise AssertionError("wallet_edges.created_at non è DateTime")
    if columns["edge_type"].get("default") is not None:
        raise AssertionError("edge_type conserva un server default legacy")
    if columns["strength"].get("default") is not None:
        raise AssertionError("strength conserva un server default legacy")
    if columns["created_at"].get("default") is None:
        raise AssertionError("created_at non ha server default")

    primary_key = inspector.get_pk_constraint("wallet_edges")
    if primary_key.get("constrained_columns") != ["id"]:
        raise AssertionError("Primary key wallet_edges inattesa")

    indexes = {
        item["name"]: item for item in inspector.get_indexes("wallet_edges")
    }
    for name, column_names in EXPECTED_INDEXES.items():
        if name not in indexes:
            raise AssertionError(f"Indice mancante: {name}")
        if indexes[name].get("column_names") != column_names:
            raise AssertionError(f"Indice incompatibile: {name}")
        if indexes[name].get("unique"):
            raise AssertionError(f"Indice non deve essere unique: {name}")

    if inspector.get_foreign_keys("wallet_edges"):
        raise AssertionError("Foreign key inattese su wallet_edges")
    if inspector.get_unique_constraints("wallet_edges"):
        raise AssertionError("Unique constraint inattese su wallet_edges")
    if inspector.get_check_constraints("wallet_edges"):
        raise AssertionError("Check constraint inattese su wallet_edges")


def _assert_absent(connection: sa.Connection) -> None:
    if sa.inspect(connection).has_table("wallet_edges"):
        raise AssertionError("wallet_edges doveva essere assente")


def _temporary_url(base_url: URL, database_name: str) -> URL:
    return base_url.set(database=database_name)


def _verify_clean_upgrade(base_url: URL, admin_engine: sa.Engine) -> None:
    name = f"sm_wallet_edges_clean_{uuid4().hex[:12]}"
    url = _temporary_url(base_url, name)
    _create_database(admin_engine, name)
    try:
        _run_alembic(url, "upgrade", "head")
        engine = sa.create_engine(url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                if _revision(connection) != EXPECTED_HEAD:
                    raise AssertionError("Head errata dopo upgrade pulito")
                _assert_schema(connection)
        finally:
            engine.dispose()
    finally:
        _drop_database(admin_engine, name)


def _verify_previous_head_lifecycle(base_url: URL, admin_engine: sa.Engine) -> None:
    name = f"sm_wallet_edges_prev_{uuid4().hex[:12]}"
    url = _temporary_url(base_url, name)
    _create_database(admin_engine, name)
    try:
        _run_alembic(url, "upgrade", PREVIOUS_HEAD)
        engine = sa.create_engine(url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                if _revision(connection) != PREVIOUS_HEAD:
                    raise AssertionError("Revision errata alla precedente head")
                _assert_absent(connection)
        finally:
            engine.dispose()

        _run_alembic(url, "upgrade", "head")
        engine = sa.create_engine(url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                _assert_schema(connection)
        finally:
            engine.dispose()

        _run_alembic(url, "downgrade", PREVIOUS_HEAD)
        engine = sa.create_engine(url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                if _revision(connection) != PREVIOUS_HEAD:
                    raise AssertionError("Revision errata dopo downgrade")
                _assert_absent(connection)
        finally:
            engine.dispose()

        _run_alembic(url, "upgrade", "head")
        engine = sa.create_engine(url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                if _revision(connection) != EXPECTED_HEAD:
                    raise AssertionError("Revision errata dopo nuovo upgrade")
                _assert_schema(connection)
        finally:
            engine.dispose()
    finally:
        _drop_database(admin_engine, name)


def _verify_legacy_preservation(base_url: URL, admin_engine: sa.Engine) -> None:
    name = f"sm_wallet_edges_legacy_{uuid4().hex[:12]}"
    url = _temporary_url(base_url, name)
    _create_database(admin_engine, name)
    try:
        _run_alembic(url, "upgrade", PREVIOUS_HEAD)
        engine = sa.create_engine(url, pool_pre_ping=True)
        try:
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        """
                        CREATE TABLE wallet_edges (
                            id SERIAL PRIMARY KEY,
                            source_wallet VARCHAR(64),
                            target_wallet VARCHAR(64),
                            token_mint VARCHAR(64),
                            edge_type VARCHAR(30) DEFAULT 'SHARED_TOKEN',
                            strength FLOAT DEFAULT 0,
                            created_at TIMESTAMPTZ DEFAULT NOW()
                        )
                        """
                    )
                )
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO wallet_edges (
                            source_wallet, target_wallet, token_mint,
                            edge_type, strength, created_at
                        ) VALUES (
                            'wallet-source', 'wallet-target', 'token-mint',
                            NULL, NULL, NULL
                        )
                        """
                    )
                )
        finally:
            engine.dispose()

        _run_alembic(url, "upgrade", "head")
        engine = sa.create_engine(url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                _assert_schema(connection)
                row = connection.execute(
                    sa.text(
                        "SELECT source_wallet, target_wallet, token_mint, "
                        "edge_type, strength, created_at FROM wallet_edges"
                    )
                ).mappings().one()
                if row["source_wallet"] != "wallet-source":
                    raise AssertionError("source_wallet legacy non preservato")
                if row["target_wallet"] != "wallet-target":
                    raise AssertionError("target_wallet legacy non preservato")
                if row["token_mint"] != "token-mint":
                    raise AssertionError("token_mint legacy non preservato")
                if row["edge_type"] != "SHARED_TOKEN":
                    raise AssertionError("edge_type NULL non sanato")
                if float(row["strength"]) != 0.0:
                    raise AssertionError("strength NULL non sanato")
                if row["created_at"] is None:
                    raise AssertionError("created_at NULL non sanato")
        finally:
            engine.dispose()

        _run_alembic(
            url,
            "downgrade",
            PREVIOUS_HEAD,
            expect_success=False,
        )
        engine = sa.create_engine(url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                if _revision(connection) != EXPECTED_HEAD:
                    raise AssertionError(
                        "Il downgrade bloccato ha alterato alembic_version"
                    )
                count = connection.execute(
                    sa.text("SELECT COUNT(*) FROM wallet_edges")
                ).scalar_one()
                if int(count) != 1:
                    raise AssertionError(
                        "Il downgrade bloccato non ha preservato i dati"
                    )
        finally:
            engine.dispose()
    finally:
        _drop_database(admin_engine, name)


def _verify_current_database(base_url: URL) -> None:
    engine = sa.create_engine(base_url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            revision = _revision(connection)
            if revision != EXPECTED_HEAD:
                raise SystemExit(
                    f"Database corrente alla revision {revision}, attesa {EXPECTED_HEAD}"
                )
            _assert_schema(connection)
            count = connection.execute(
                sa.text("SELECT COUNT(*) FROM wallet_edges")
            ).scalar_one()
    finally:
        engine.dispose()
    print(f"Database corrente: revision {EXPECTED_HEAD}")
    print(f"wallet_edges: schema conforme, righe preservate {int(count)}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--current",
        action="store_true",
        help="Verifica read-only del database configurato, senza database temporanei.",
    )
    args = parser.parse_args()

    base_url = make_url(settings.DATABASE_URL)
    _require_postgresql(base_url)

    if args.current:
        _verify_current_database(base_url)
        return

    admin_url = base_url.set(database="postgres")
    admin_engine = sa.create_engine(
        admin_url,
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    try:
        _verify_clean_upgrade(base_url, admin_engine)
        print("PostgreSQL pulito → head: OK")
        _verify_previous_head_lifecycle(base_url, admin_engine)
        print("c1f3a6b9d075 → upgrade → downgrade → upgrade: OK")
        _verify_legacy_preservation(base_url, admin_engine)
        print("Tabella legacy con dati → normalizzazione e protezione rollback: OK")
    finally:
        admin_engine.dispose()

    print("Database temporanei rimossi")
    print("Nessuna richiesta esterna e nessuna attivazione LIVE eseguita")


if __name__ == "__main__":
    main()
