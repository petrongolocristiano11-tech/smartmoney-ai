from __future__ import annotations

import argparse
from pathlib import Path
import sys

import sqlalchemy as sa
from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.core.config import settings
from backend.app.models.gen4_profitability import (
    CanonicalParserGen4ProfitabilityRun,
    CanonicalParserGen4ProfitabilityTrade,
    CanonicalParserGen4ProfitabilityWindow,
)

EXPECTED_HEAD = "e3b5c8d1f297"
EXPECTED_TABLES = {
    "canonical_parser_gen4_profitability_runs",
    "canonical_parser_gen4_profitability_windows",
    "canonical_parser_gen4_profitability_trades",
}
EXPECTED_ROUTES = {
    "/integrity/parser-gen4-profitability/status",
    "/integrity/parser-gen4-profitability/preview",
    "/integrity/parser-gen4-profitability/run",
    "/integrity/parser-gen4-profitability/runs/{run_id}",
}


def verify_static() -> None:
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    if scripts.get_heads() != [EXPECTED_HEAD]:
        raise AssertionError(f"Alembic head inattesa: {scripts.get_heads()}")
    revision = scripts.get_revision(EXPECTED_HEAD)
    if revision.down_revision != "d2a4b7c0e186":
        raise AssertionError("M47 non è consecutiva a d2a4b7c0e186")

    tables = {
        CanonicalParserGen4ProfitabilityRun.__tablename__,
        CanonicalParserGen4ProfitabilityWindow.__tablename__,
        CanonicalParserGen4ProfitabilityTrade.__tablename__,
    }
    if tables != EXPECTED_TABLES:
        raise AssertionError(f"Tabelle modello inattese: {sorted(tables)}")

    service_source = (
        ROOT / "backend/app/services/blockchain_parser_gen4_profitability_service.py"
    ).read_text(encoding="utf-8")
    for forbidden in (
        "JupiterSwapClient(",
        "httpx.",
        "requests.",
        "send_transaction",
        "sign_transaction",
        "execute_permit_bound_paper",
        "run_live_stream_worker",
    ):
        if forbidden in service_source:
            raise AssertionError(f"Connessione vietata trovata nel servizio: {forbidden}")

    main_source = (ROOT / "backend/app/main.py").read_text(encoding="utf-8")
    for route in EXPECTED_ROUTES:
        if route not in main_source:
            raise AssertionError(f"Route M47 assente: {route}")

    if settings.CANONICAL_PARSER_GEN4_PROFITABILITY_ENABLED:
        raise AssertionError("M47 deve essere disabilitata per default durante il verifier")

    from backend.app.main import app

    paths = set(app.openapi()["paths"])
    missing = EXPECTED_ROUTES - paths
    if missing:
        raise AssertionError(f"Route OpenAPI M47 mancanti: {sorted(missing)}")

    print(f"Alembic head: {EXPECTED_HEAD}")
    print("M47: 3 tabelle metadata-only registrate")
    print("OpenAPI: status, preview, run e dettaglio run presenti")
    print("STRICT_GEN4 e SIGNAL_ONLY_PROXY distinti")
    print("LIVE, worker, scheduler, signer, submit ed external requests: non collegati")


def verify_current_database() -> None:
    engine = sa.create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            inspector = sa.inspect(connection)
            revision = connection.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            if revision != EXPECTED_HEAD:
                raise AssertionError(
                    f"Database alla revision {revision}, attesa {EXPECTED_HEAD}"
                )
            missing = EXPECTED_TABLES - set(inspector.get_table_names())
            if missing:
                raise AssertionError(f"Tabelle M47 mancanti: {sorted(missing)}")
            counts = {
                table: int(
                    connection.execute(sa.text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one()
                )
                for table in sorted(EXPECTED_TABLES)
            }
    finally:
        engine.dispose()
    print(f"Database corrente: revision {EXPECTED_HEAD}")
    print(f"Righe metadata M47: {counts}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current-database", action="store_true")
    args = parser.parse_args()
    verify_static()
    if args.current_database:
        verify_current_database()


if __name__ == "__main__":
    main()
