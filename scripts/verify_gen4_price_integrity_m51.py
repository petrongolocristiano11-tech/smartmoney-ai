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
from backend.app.core.constants import (
    GEN4_MANDATORY_EXCLUDED_PRICE_MINTS,
    NATIVE_SOL_SENTINEL_MINT,
    SOL_MINT,
    USDC_MINT,
    USDT_MINT,
)
from backend.app.services.blockchain_parser_gen4_profitability_service import (
    GEN4_PROFITABILITY_POLICY_VERSION,
    _policy_snapshot,
)

EXPECTED_HEAD = "e3b5c8d1f297"
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

    if GEN4_PROFITABILITY_POLICY_VERSION != "canonical-parser-gen4-walk-forward-profitability/2":
        raise AssertionError(f"Policy M51 inattesa: {GEN4_PROFITABILITY_POLICY_VERSION}")

    mandatory = {SOL_MINT, USDC_MINT, USDT_MINT, NATIVE_SOL_SENTINEL_MINT}
    if not mandatory <= set(GEN4_MANDATORY_EXCLUDED_PRICE_MINTS):
        raise AssertionError("Lista quote asset obbligatoria incompleta")

    policy = _policy_snapshot(settings)
    if not mandatory <= set(policy["excluded_price_mints"]):
        raise AssertionError("Policy runtime non esclude tutti i quote asset obbligatori")
    if float(policy["maximum_price_discontinuity_ratio"]) <= 1:
        raise AssertionError("Rapporto massimo discontinuità prezzo non valido")
    if policy["take_profit_fill_method"] != "THRESHOLD_PRICE_WITH_EXIT_FRICTION":
        raise AssertionError("Take-profit non usa il prezzo soglia")
    if policy["stop_loss_fill_method"] != "THRESHOLD_PRICE_WITH_EXIT_FRICTION":
        raise AssertionError("Stop-loss non usa il prezzo soglia")

    service_path = ROOT / "backend/app/services/blockchain_parser_gen4_profitability_service.py"
    service_source = service_path.read_text(encoding="utf-8")
    required = (
        "GEN4_MANDATORY_EXCLUDED_PRICE_MINTS",
        "price_discontinuity_rejected_count",
        "threshold_fill_applied",
        "exit_reference_price = take_price",
        "exit_reference_price = stop_price",
    )
    for value in required:
        if value not in service_source:
            raise AssertionError(f"Guardia M51 assente: {value}")

    forbidden = (
        "JupiterSwapClient(",
        "httpx.",
        "requests.",
        "send_transaction",
        "sign_transaction",
        "execute_permit_bound_paper",
        "run_live_stream_worker",
    )
    for value in forbidden:
        if value in service_source:
            raise AssertionError(f"Connessione vietata nel servizio M51: {value}")

    config_source = (ROOT / "backend/app/core/config.py").read_text(encoding="utf-8")
    env_source = (ROOT / ".env.example").read_text(encoding="utf-8")
    for setting_name in (
        "CANONICAL_PARSER_GEN4_PROFITABILITY_EXCLUDED_TOKEN_MINTS",
        "CANONICAL_PARSER_GEN4_PROFITABILITY_PRICE_CONTINUITY_WINDOW_SECONDS",
        "CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_PRICE_DISCONTINUITY_RATIO",
    ):
        if setting_name not in config_source or setting_name not in env_source:
            raise AssertionError(f"Configurazione M51 assente: {setting_name}")

    from backend.app.main import app

    missing = EXPECTED_ROUTES - set(app.openapi()["paths"])
    if missing:
        raise AssertionError(f"Route OpenAPI M47/M51 mancanti: {sorted(missing)}")

    if settings.CANONICAL_PARSER_GEN4_PROFITABILITY_ENABLED:
        raise AssertionError("M47/M51 deve restare disabilitata per default")

    print(f"Alembic head invariata: {EXPECTED_HEAD}")
    print(f"Policy Gen4: {GEN4_PROFITABILITY_POLICY_VERSION}")
    print("Quote asset obbligatori esclusi: SOL, native SOL sentinel, USDC, USDT")
    print(
        "Price integrity: continuità temporale, rapporto massimo e fill TP/SL a soglia"
    )
    print("OpenAPI invariata; nessun Helius, Jupiter, paper, signer o LIVE collegato")


def verify_current_database() -> None:
    engine = sa.create_engine(settings.DATABASE_URL, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            revision = connection.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            if revision != EXPECTED_HEAD:
                raise AssertionError(
                    f"Database alla revision {revision}, attesa {EXPECTED_HEAD}"
                )
    finally:
        engine.dispose()
    print(f"Database corrente invariato: revision {EXPECTED_HEAD}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--current-database", action="store_true")
    args = parser.parse_args()
    verify_static()
    if args.current_database:
        verify_current_database()


if __name__ == "__main__":
    main()
