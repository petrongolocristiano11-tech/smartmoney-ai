from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "M66 controlled Helius Discovery: explicit, cached, zero retry, "
            "hard cap of 90 Enhanced requests / 9000 credits; default tranche 86/8600."
        )
    )
    parser.add_argument("--confirmation", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--seed-wallet", default="")
    parser.add_argument("--cache-input", default="")
    parser.add_argument("--maximum-seed-tokens", type=int, default=15)
    parser.add_argument("--maximum-candidate-wallets", type=int, default=70)
    parser.add_argument("--database-url-env", default="DATABASE_PUBLIC_URL")
    return parser


def _outside_project(path: Path) -> bool:
    try:
        path.relative_to(PROJECT_ROOT)
        return False
    except ValueError:
        return True


def _load_cache(path_text: str) -> dict | None:
    if not str(path_text or "").strip():
        return None
    path = Path(path_text).expanduser().resolve()
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Cache Helius M66 non leggibile: {path.name}.") from error
    if not isinstance(value, dict):
        raise RuntimeError("Cache Helius M66 root non oggetto.")
    return value


def main() -> int:
    args = _parser().parse_args()
    environment_name = str(args.database_url_env or "").strip()
    public_url = str(os.getenv(environment_name) or "").strip()
    if not public_url:
        raise RuntimeError(
            f"Variabile {environment_name} assente; nessun fallback silenzioso."
        )

    # Il processo locale Railway deve usare lo stesso endpoint pubblico anche
    # per le prenotazioni persistenti della guardia crediti. Il valore non viene
    # mai stampato e la connessione di inventario usa comunque una URL read-only.
    os.environ["DATABASE_URL"] = public_url

    from backend.app.core.config import settings  # noqa: WPS433
    from backend.app.models.discovered_wallet import DiscoveredWallet  # noqa: WPS433
    from backend.app.services.gen4_closed_trade_readonly_audit_service import (  # noqa: WPS433,E501
        M64_EXPECTED_ALEMBIC_HEAD,
        M64_EXPECTED_DATABASE,
        file_sha256,
        readonly_database_url,
        write_json_atomic,
    )
    from backend.app.services.gen4_controlled_helius_discovery_service import (  # noqa: WPS433,E501
        M66_DEFAULT_SEED_WALLET,
        M66_HELIUS_CONFIRMATION,
        M66ControlledHeliusDiscoveryError,
        build_controlled_helius_plan,
        execute_controlled_helius_discovery,
    )
    from backend.app.services.helius_credit_guard_service import (  # noqa: WPS433
        get_helius_credit_guard_status,
    )

    if str(args.confirmation or "").strip() != M66_HELIUS_CONFIRMATION:
        raise M66ControlledHeliusDiscoveryError(
            f"Conferma Helius richiesta: {M66_HELIUS_CONFIRMATION}."
        )
    output_dir = Path(args.output_dir).expanduser().resolve()
    if not _outside_project(output_dir):
        raise M66ControlledHeliusDiscoveryError(
            "Gli output Helius M66 devono restare fuori dal repository."
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_input = _load_cache(str(args.cache_input or ""))
    seed_wallet = str(args.seed_wallet or "").strip() or M66_DEFAULT_SEED_WALLET
    plan = build_controlled_helius_plan(
        seed_wallet=seed_wallet,
        maximum_seed_tokens=args.maximum_seed_tokens,
        maximum_candidate_wallets=args.maximum_candidate_wallets,
    )

    api_key = str(getattr(settings, "HELIUS_API_KEY", "") or "").strip()
    if not api_key or api_key.upper() in {"CHANGE_ME", "CHANGEME", "TEST"}:
        raise M66ControlledHeliusDiscoveryError(
            "HELIUS_API_KEY assente o placeholder; nessuna richiesta eseguita."
        )
    guard_enabled = bool(getattr(settings, "HELIUS_CREDIT_GUARD_ENABLED", True))
    guard_enforced = (
        str(getattr(settings, "ENVIRONMENT", "development")).lower()
        == "production"
        or bool(
            getattr(
                settings,
                "HELIUS_CREDIT_GUARD_ENFORCE_IN_NON_PRODUCTION",
                False,
            )
        )
    )
    if not guard_enabled or not guard_enforced:
        raise M66ControlledHeliusDiscoveryError(
            "Guardia crediti Helius non attiva/enforced; nessuna richiesta eseguita."
        )

    engine = create_engine(
        readonly_database_url(public_url),
        future=True,
        pool_pre_ping=True,
    )
    connection = None
    transaction = None
    cached_wallets: set[str] = set()
    try:
        connection = engine.connect()
        transaction = connection.begin()
        connection.exec_driver_sql(
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
        )
        database_name = str(
            connection.execute(text("SELECT current_database()" )).scalar_one()
        )
        read_only = str(
            connection.execute(text("SHOW transaction_read_only")).scalar_one()
        ).lower()
        alembic_head = str(
            connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        )
        if database_name != M64_EXPECTED_DATABASE:
            raise M66ControlledHeliusDiscoveryError(
                f"Database inatteso: {database_name}; atteso={M64_EXPECTED_DATABASE}."
            )
        if read_only != "on":
            raise M66ControlledHeliusDiscoveryError(
                "Inventario Helius M66 non in transazione read-only."
            )
        if alembic_head != M64_EXPECTED_ALEMBIC_HEAD:
            raise M66ControlledHeliusDiscoveryError(
                f"Alembic head inattesa: {alembic_head}; "
                f"attesa={M64_EXPECTED_ALEMBIC_HEAD}."
            )
        with Session(
            bind=connection,
            autoflush=False,
            expire_on_commit=False,
        ) as db:
            cached_wallets = {
                str(value)
                for (value,) in db.query(DiscoveredWallet.wallet_address).all()
            }
            guard_status = get_helius_credit_guard_status(db)
            if db.new or db.dirty or db.deleted:
                raise M66ControlledHeliusDiscoveryError(
                    "Preflight Helius M66 ha prodotto stato SQLAlchemy mutabile."
                )
        required_credits = int(plan["enhanced_credit_cap"])
        if int(guard_status["daily_total_credits_remaining"]) < required_credits:
            raise M66ControlledHeliusDiscoveryError(
                "Budget totale Helius residuo inferiore al cap M66; "
                "nessuna richiesta eseguita."
            )
        if int(guard_status["daily_enhanced_credits_remaining"]) < required_credits:
            raise M66ControlledHeliusDiscoveryError(
                "Budget Enhanced Helius residuo inferiore al cap M66; "
                "nessuna richiesta eseguita."
            )
        print("M66_M63_DAILY_TOTAL_CREDITS_REMAINING=" + str(guard_status["daily_total_credits_remaining"]))
        print("M66_M63_DAILY_ENHANCED_CREDITS_REMAINING=" + str(guard_status["daily_enhanced_credits_remaining"]))
        print("M66_PLANNED_REQUEST_CAP=" + str(plan["enhanced_request_cap"]))
        print("M66_PLANNED_CREDIT_CAP=" + str(plan["enhanced_credit_cap"]))
    finally:
        if transaction is not None and transaction.is_active:
            transaction.rollback()
        if connection is not None:
            connection.close()
        engine.dispose()

    report, output_cache = execute_controlled_helius_discovery(
        confirmation=args.confirmation,
        seed_wallet=seed_wallet,
        cached_wallet_addresses=cached_wallets,
        maximum_seed_tokens=args.maximum_seed_tokens,
        maximum_candidate_wallets=args.maximum_candidate_wallets,
        request_cache=cache_input,
    )
    timestamp = report["executed_at_utc"].replace("-", "").replace(":", "")
    timestamp = timestamp.split(".", 1)[0].replace("+0000", "").replace("+00", "")
    timestamp = timestamp.replace("T", "T") + "Z"
    report_path = output_dir / (
        f"smartmoney-m66-controlled-helius-discovery-{timestamp}.json"
    )
    cache_path = output_dir / (
        f"smartmoney-m66-helius-request-cache-{timestamp}.json"
    )
    write_json_atomic(report_path, report)
    write_json_atomic(cache_path, output_cache)

    summary = report["summary"]
    budget = report["budget"]
    print("=== M66 CONTROLLED HELIUS NEW-WALLET DISCOVERY ===")
    print("M66_CONTROLLED_HELIUS_DISCOVERY=PASS")
    print(f"CACHED_WALLETS_EXCLUDED={len(cached_wallets)}")
    print(
        "NEW_WALLETS_FOUND_BEFORE_LIMIT="
        + str(report["candidate_pool"]["new_wallets_found_before_limit"])
    )
    print(f"NEW_WALLETS_PRESCREENED={summary['new_wallets_prescreened']}")
    print(
        "PRESCREEN_PASS_NEEDING_FULL_GEN4_HISTORY="
        + str(summary["prescreen_pass_needing_full_gen4_history"])
    )
    print(f"HELIUS_REQUEST_CAP={budget['enhanced_request_cap']}")
    print(f"HELIUS_REQUESTS={budget['enhanced_requests_executed']}")
    print(f"HELIUS_CREDIT_CAP={budget['enhanced_credit_cap']}")
    print(
        "HELIUS_CREDITS_RESERVED_MAXIMUM="
        + str(budget["enhanced_credits_reserved_maximum"])
    )
    print(f"HELIUS_CACHE_HITS={budget['cache_hits']}")
    print("HELIUS_RETRIES=0")
    print("AUTOMATIC_ENHANCED_POLLING=NO")
    print("CANDIDATE_DATABASE_WRITES=0")
    print("RAW_CAPTURE_WRITES=0")
    print("DATABASE_WRITE_SCOPE=HELIUS_CREDIT_GUARD_RESERVATIONS_ONLY")
    print("BACKEND_POSTS=0")
    print("JUPITER_REQUESTS=0")
    print("DISCOVERY_CRON_REACTIVATED=NO")
    print("PRIMARY_CAMPAIGN_REACTIVATED=NO")
    print("OLD_FORWARD_FEED_REACTIVATED=NO")
    print("OFFICIAL_REALTIME_COUNTER_MUTATED=NO")
    print("RECOVERY_COUNTS_AS_REALTIME_PROOF=NO")
    print("SHORT_CANARY_ACTIVATED=NO")
    print("MICRO_LIVE_EXECUTION_AUTHORIZED=NO")
    print("SIGNER_AUTHORIZED=NO")
    print(f"HELIUS_DISCOVERY_REPORT_FILE={report_path}")
    print(f"HELIUS_DISCOVERY_REPORT_SHA256={file_sha256(report_path)}")
    print(f"HELIUS_REQUEST_CACHE_FILE={cache_path}")
    print(f"HELIUS_REQUEST_CACHE_SHA256={file_sha256(cache_path)}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001
        print(
            "M66_CONTROLLED_HELIUS_DISCOVERY=FAILED "
            f"type={type(error).__name__} message={error}"
        )
        raise SystemExit(1) from None
