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

PREVIOUS_HEAD = "d2a4b7c0e186"
EXPECTED_HEAD = "e3b5c8d1f297"
TABLES = {
    "canonical_parser_gen4_profitability_runs",
    "canonical_parser_gen4_profitability_windows",
    "canonical_parser_gen4_profitability_trades",
}


def _require_postgresql(url: URL) -> None:
    if not url.drivername.startswith("postgresql"):
        raise SystemExit("Il verifier richiede DATABASE_URL PostgreSQL.")


def _redact(text: str, url: URL) -> str:
    sanitized = text
    if url.password:
        sanitized = sanitized.replace(url.password, "<REDACTED>")
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
        raise RuntimeError(
            f"Alembic {' '.join(arguments)} non riuscito:\n"
            + _redact((result.stdout or "") + (result.stderr or ""), url)
        )
    if not expect_success and result.returncode == 0:
        raise RuntimeError(f"Alembic {' '.join(arguments)} doveva fallire")
    return result


def _create_database(admin: sa.Engine, name: str) -> None:
    with admin.connect() as connection:
        connection.execute(sa.text(f'CREATE DATABASE "{name}"'))


def _drop_database(admin: sa.Engine, name: str) -> None:
    with admin.connect() as connection:
        connection.execute(
            sa.text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :name AND pid <> pg_backend_pid()"
            ),
            {"name": name},
        )
        connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{name}"'))


def _temp_url(base: URL, name: str) -> URL:
    return base.set(database=name)


def _revision(connection: sa.Connection) -> str | None:
    if not sa.inspect(connection).has_table("alembic_version"):
        return None
    return connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one_or_none()


def _assert_schema(connection: sa.Connection) -> None:
    inspector = sa.inspect(connection)
    missing = TABLES - set(inspector.get_table_names())
    if missing:
        raise AssertionError(f"Tabelle M47 mancanti: {sorted(missing)}")
    run_indexes = {item["name"] for item in inspector.get_indexes("canonical_parser_gen4_profitability_runs")}
    window_indexes = {item["name"] for item in inspector.get_indexes("canonical_parser_gen4_profitability_windows")}
    trade_indexes = {item["name"] for item in inspector.get_indexes("canonical_parser_gen4_profitability_trades")}
    expected = {
        "ix_gen4_profitability_runs_verdict_completed",
        "ix_gen4_profitability_runs_policy",
        "ix_gen4_profitability_windows_run_sequence",
        "ix_gen4_profitability_windows_test_period",
        "ix_gen4_profitability_trades_window_lane",
        "ix_gen4_profitability_trades_token_signal",
        "ix_gen4_profitability_trades_lane_exit_reason",
    }
    actual = run_indexes | window_indexes | trade_indexes
    missing_indexes = expected - actual
    if missing_indexes:
        raise AssertionError(f"Indici M47 mancanti: {sorted(missing_indexes)}")


def _assert_absent(connection: sa.Connection) -> None:
    present = TABLES & set(sa.inspect(connection).get_table_names())
    if present:
        raise AssertionError(f"Tabelle M47 dovevano essere assenti: {sorted(present)}")


def _clean_upgrade(base: URL, admin: sa.Engine) -> None:
    name = f"sm_gen4_profit_clean_{uuid4().hex[:12]}"
    url = _temp_url(base, name)
    _create_database(admin, name)
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
        _drop_database(admin, name)


def _lifecycle(base: URL, admin: sa.Engine) -> None:
    name = f"sm_gen4_profit_lifecycle_{uuid4().hex[:12]}"
    url = _temp_url(base, name)
    _create_database(admin, name)
    try:
        _run_alembic(url, "upgrade", PREVIOUS_HEAD)
        engine = sa.create_engine(url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                _assert_absent(connection)
        finally:
            engine.dispose()
        _run_alembic(url, "upgrade", "head")
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
        _drop_database(admin, name)


def _downgrade_guard(base: URL, admin: sa.Engine) -> None:
    name = f"sm_gen4_profit_guard_{uuid4().hex[:12]}"
    url = _temp_url(base, name)
    _create_database(admin, name)
    try:
        _run_alembic(url, "upgrade", "head")
        engine = sa.create_engine(url, pool_pre_ping=True)
        try:
            with engine.begin() as connection:
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO canonical_parser_gen4_profitability_runs (
                            run_id, run_key, scope, status, verdict,
                            strict_evidence_status, policy_version, policy_hash,
                            policy_snapshot, parameters, summary, strict_metrics,
                            proxy_metrics, baseline_metrics, evidence_gaps, safety,
                            source_trade_count, source_wallet_count, source_token_count,
                            window_count, strict_closed_trade_count, proxy_closed_trade_count,
                            evaluated_at, completed_at, report_hash, actor_label,
                            technical_metadata
                        ) VALUES (
                            :run_id, :run_key, 'HISTORICAL_SHADOW_ANALYTICS_ONLY',
                            'COMPLETED', 'NOT_EVALUABLE', 'INSUFFICIENT',
                            'policy/1', :policy_hash, '{}'::json, '{}'::json,
                            '{}'::json, '{}'::json, '{}'::json, '{}'::json,
                            '[]'::json, '{}'::json, 0, 0, 0, 0, 0, 0,
                            NOW(), NOW(), :report_hash, 'TEST', '{}'::json
                        )
                        """
                    ),
                    {
                        "run_id": str(uuid4()),
                        "run_key": "a" * 64,
                        "policy_hash": "b" * 64,
                        "report_hash": "c" * 64,
                    },
                )
        finally:
            engine.dispose()
        _run_alembic(url, "downgrade", PREVIOUS_HEAD, expect_success=False)
        engine = sa.create_engine(url, pool_pre_ping=True)
        try:
            with engine.connect() as connection:
                if _revision(connection) != EXPECTED_HEAD:
                    raise AssertionError("Downgrade bloccato ha alterato la revision")
                count = connection.execute(
                    sa.text("SELECT COUNT(*) FROM canonical_parser_gen4_profitability_runs")
                ).scalar_one()
                if int(count) != 1:
                    raise AssertionError("Downgrade bloccato non ha preservato i metadati")
        finally:
            engine.dispose()
    finally:
        _drop_database(admin, name)


def _current(base: URL) -> None:
    engine = sa.create_engine(base, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            if _revision(connection) != EXPECTED_HEAD:
                raise SystemExit(f"Database non alla head {EXPECTED_HEAD}")
            _assert_schema(connection)
    finally:
        engine.dispose()
    print(f"Database corrente: revision {EXPECTED_HEAD}")
    print("Tabelle M47 e indici: conformi")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current", action="store_true")
    args = parser.parse_args()
    base = make_url(settings.DATABASE_URL)
    _require_postgresql(base)
    if args.current:
        _current(base)
        return
    admin = sa.create_engine(
        base.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        pool_pre_ping=True,
    )
    try:
        _clean_upgrade(base, admin)
        print("PostgreSQL pulito → M47 head: OK")
        _lifecycle(base, admin)
        print("d2a4b7c0e186 → upgrade → downgrade → upgrade: OK")
        _downgrade_guard(base, admin)
        print("Downgrade con metadati persistiti: bloccato e dati preservati")
    finally:
        admin.dispose()
    print("Database temporanei rimossi")
    print("Nessuna richiesta esterna e nessuna attivazione LIVE eseguita")


if __name__ == "__main__":
    main()
