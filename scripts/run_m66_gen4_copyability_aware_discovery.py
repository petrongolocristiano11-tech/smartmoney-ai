from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.gen4_closed_trade_readonly_audit_service import (  # noqa: E402
    M64_EXPECTED_ALEMBIC_HEAD,
    M64_EXPECTED_DATABASE,
    canonical_sha256,
    file_sha256,
    readonly_database_url,
)
from backend.app.services.gen4_copyability_aware_discovery_service import (  # noqa: E402
    M66_DEFAULT_POLICY,
    M66_RUN_CONFIRMATION,
    M66DiscoveryError,
    build_cached_discovery_snapshot,
    evaluate_copyability_aware_discovery,
    load_json,
    utc_now,
    write_json_atomic,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "M66 definitive copyability-aware Discovery: cached/read-only, "
            "zero Helius, zero provider calls, zero production writes."
        )
    )
    parser.add_argument("--confirmation", default="")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--snapshot", default="")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--maximum-selected-wallets", type=int, default=3)
    parser.add_argument(
        "--database-url-env",
        default="DATABASE_PUBLIC_URL",
        help="Nome variabile DB pubblico; il valore non viene mai stampato.",
    )
    return parser


def _outside_project(path: Path) -> bool:
    try:
        path.relative_to(PROJECT_ROOT)
        return False
    except ValueError:
        return True


def _load_database_snapshot(
    database_public_url: str,
    *,
    limit: int,
    policy: dict,
) -> tuple[dict, dict]:
    url = readonly_database_url(database_public_url)
    engine = create_engine(url, future=True, pool_pre_ping=True)
    connection = None
    transaction = None
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
            raise M66DiscoveryError(
                f"Database inatteso: {database_name}; "
                f"atteso={M64_EXPECTED_DATABASE}."
            )
        if read_only != "on":
            raise M66DiscoveryError("La transazione M66 non e read-only.")
        if alembic_head != M64_EXPECTED_ALEMBIC_HEAD:
            raise M66DiscoveryError(
                f"Alembic head inattesa: {alembic_head}; "
                f"attesa={M64_EXPECTED_ALEMBIC_HEAD}."
            )
        with Session(
            bind=connection,
            autoflush=False,
            expire_on_commit=False,
        ) as db:
            snapshot = build_cached_discovery_snapshot(
                db,
                limit=limit,
                policy=policy,
            )
            if db.new or db.dirty or db.deleted:
                raise M66DiscoveryError(
                    "La preview M66 ha prodotto stato SQLAlchemy mutabile."
                )
        return snapshot, {
            "database_name": database_name,
            "transaction_read_only": read_only,
            "alembic_head": alembic_head,
        }
    finally:
        if transaction is not None and transaction.is_active:
            transaction.rollback()
        if connection is not None:
            connection.close()
        engine.dispose()


def main() -> int:
    args = _parser().parse_args()
    if str(args.confirmation).strip() != M66_RUN_CONFIRMATION:
        raise M66DiscoveryError(f"Conferma richiesta: {M66_RUN_CONFIRMATION}.")
    output_dir = Path(args.output_dir).expanduser().resolve()
    if not _outside_project(output_dir):
        raise M66DiscoveryError("Gli output M66 devono restare fuori dal repository.")
    output_dir.mkdir(parents=True, exist_ok=True)
    maximum_selected = max(1, min(int(args.maximum_selected_wallets), 3))
    policy = {
        **M66_DEFAULT_POLICY,
        "maximum_selected_wallets": maximum_selected,
    }
    database_contract = {
        "database_name": None,
        "transaction_read_only": "not_applicable_fixture",
        "alembic_head": None,
    }
    snapshot_path_argument = str(args.snapshot or "").strip()
    if snapshot_path_argument:
        snapshot = load_json(Path(snapshot_path_argument).expanduser().resolve())
        source_mode = "EXTERNAL_SIGNED_SNAPSHOT"
    else:
        environment_name = str(args.database_url_env or "").strip()
        database_public_url = str(os.getenv(environment_name) or "").strip()
        if not database_public_url:
            raise M66DiscoveryError(
                f"Variabile {environment_name} assente; "
                "nessun fallback a DATABASE_URL."
            )
        snapshot, database_contract = _load_database_snapshot(
            database_public_url,
            limit=max(1, min(int(args.limit), 500)),
            policy=policy,
        )
        source_mode = "PRODUCTION_DATABASE_REPEATABLE_READ_READ_ONLY"

    started_at = utc_now()
    report = evaluate_copyability_aware_discovery(
        snapshot,
        policy=policy,
        evaluated_at=started_at,
    )
    report["source"]["execution_mode"] = source_mode
    report["source"]["database_contract"] = database_contract
    report["integrity"]["report_payload_sha256"] = canonical_sha256(
        {key: value for key, value in report.items() if key != "integrity"}
    )
    timestamp = started_at.strftime("%Y%m%dT%H%M%SZ")
    snapshot_path = output_dir / (
        f"smartmoney-m66-cached-discovery-snapshot-{timestamp}.json"
    )
    report_path = output_dir / (
        f"smartmoney-m66-copyability-aware-discovery-{timestamp}.json"
    )
    write_json_atomic(snapshot_path, snapshot)
    write_json_atomic(report_path, report)
    snapshot_file_hash = file_sha256(snapshot_path)
    report_file_hash = file_sha256(report_path)

    summary = report["summary"]
    acquisition = report["acquisition_plan"]
    print("=== M66 GEN4 DEFINITIVE COPYABILITY-AWARE DISCOVERY ===")
    print("M66_DISCOVERY_EVALUATION=PASS")
    print(
        "CACHED_WALLETS_TOTAL_ZERO_HELIUS_CREDITS="
        + str(summary["cached_wallets_total_zero_helius_credits"])
    )
    print(
        "CACHED_WALLETS_SCANNED_ZERO_HELIUS_CREDITS="
        + str(summary["cached_wallets_scanned_zero_helius_credits"])
    )
    print(
        "CACHED_WALLETS_WITH_COMPLETED_BACKTEST="
        + str(summary["cached_wallets_with_completed_backtest"])
    )
    print(
        "CACHED_WALLETS_WITH_COMPLETE_POSITION_EVIDENCE="
        + str(summary["cached_wallets_with_complete_position_evidence"])
    )
    print(
        "CACHED_TRADE_ROWS_LIFETIME_ZERO_HELIUS_CREDITS="
        + str(summary["cached_trade_rows_lifetime_zero_helius_credits"])
    )
    print(
        "CACHED_TRADE_ROWS_7D_ZERO_HELIUS_CREDITS="
        + str(summary["cached_trade_rows_7d_zero_helius_credits"])
    )
    print(
        "CACHED_WALLETS_WITH_LOCAL_TRADE_EVIDENCE="
        + str(summary["cached_wallets_with_local_trade_evidence"])
    )
    print(
        "CACHED_WALLETS_WITH_RECENT_LOCAL_TRADE_EVIDENCE="
        + str(summary["cached_wallets_with_recent_local_trade_evidence"])
    )
    print(
        "CACHED_WALLETS_PASSING_ZERO_CREDIT_TRADE_PRESCREEN="
        + str(
            summary[
                "cached_wallets_passing_zero_credit_trade_prescreen"
            ]
        )
    )
    print(
        "CACHED_WALLETS_WITHOUT_LOCAL_TRADE_EVIDENCE="
        + str(summary["cached_wallets_without_local_trade_evidence"])
    )
    print(f"WALLETS_EVALUATED={summary['wallets_evaluated']}")
    print(
        "WALLETS_QUALIFIED_FOR_SHORT_CANARY="
        + str(summary["wallets_qualified_for_short_canary"])
    )
    print(
        "WALLETS_SELECTED_FOR_SHORT_CANARY="
        + str(summary["wallets_selected_for_short_canary"])
    )
    print(
        "WALLETS_NEEDING_TARGETED_HISTORY="
        + str(summary["wallets_needing_targeted_history"])
    )
    print(
        "PUBLIC_RPC_REQUESTS_PLANNED="
        + str(acquisition["requests_allocated"])
    )
    print("PUBLIC_RPC_REQUESTS_EXECUTED=0")
    print("AUTOMATIC_ACQUISITION=NO")
    print("DISCOVERY_CRON_REACTIVATED=NO")
    print("HELIUS_REQUESTS=0")
    print("DATABASE_WRITES=0")
    print("BACKEND_POSTS=0")
    print("JUPITER_REQUESTS=0")
    print("PAPER_ORDERS=0")
    print("LIVE_ORDERS=0")
    print("MICRO_LIVE_EXECUTION_AUTHORIZED=NO")
    print("AUTOMATIC_LIVE_ACTIVATION=NO")
    print("SIGNER_AUTHORIZED=NO")
    print("RECOVERY_COUNTS_AS_REALTIME_PROOF=NO")
    print("HISTORICAL_JUPITER_QUOTES_INVENTED=NO")
    print(f"SNAPSHOT_FILE={snapshot_path}")
    print(f"SNAPSHOT_FILE_SHA256={snapshot_file_hash}")
    print(f"DISCOVERY_REPORT_FILE={report_path}")
    print(f"DISCOVERY_REPORT_SHA256={report_file_hash}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001
        print(
            "M66_DISCOVERY_EVALUATION=FAILED "
            f"type={type(error).__name__} message={error}"
        )
        raise SystemExit(1) from None
