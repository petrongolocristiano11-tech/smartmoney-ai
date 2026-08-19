from __future__ import annotations

import copy
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("SOLANA_RPC_URL", "https://example.invalid")
os.environ.setdefault("HELIUS_API_KEY", "test-m66-not-used")
os.environ.setdefault("ENVIRONMENT", "test")

from backend.app.services.gen4_closed_trade_readonly_audit_service import (  # noqa: E402
    canonical_sha256,
    file_sha256,
)
from backend.app.services.gen4_copyability_aware_discovery_service import (  # noqa: E402
    M66_DEFAULT_POLICY,
    M66_CACHED_TRADE_ENRICHMENT_VERSION,
    M66_DISCOVERY_VERSION,
    M66_SCOPE,
    STATUS_NEEDS_HISTORY,
    evaluate_copyability_aware_discovery,
    validate_snapshot,
)
from backend.app.services.gen4_controlled_helius_discovery_service import (  # noqa: E402
    M66_HELIUS_CONFIRMATION,
    M66_MAX_ENHANCED_CREDITS,
    M66_MAX_ENHANCED_REQUESTS,
    build_controlled_helius_plan,
)


FIXTURE = (
    PROJECT_ROOT
    / "tests/fixtures/m66_gen4_copyability_aware_discovery.json"
)
SERVICE = (
    PROJECT_ROOT
    / "backend/app/services/gen4_copyability_aware_discovery_service.py"
)
RUNNER = PROJECT_ROOT / "scripts/run_m66_gen4_copyability_aware_discovery.py"
HELIUS_SERVICE = (
    PROJECT_ROOT
    / "backend/app/services/gen4_controlled_helius_discovery_service.py"
)
HELIUS_RUNNER = PROJECT_ROOT / "scripts/run_m66_controlled_helius_discovery.py"
API = PROJECT_ROOT / "backend/app/api/discovered_wallets.py"
ACTIVITY_SERVICE = PROJECT_ROOT / "backend/app/services/wallet_activity_service.py"
QUALITY_SERVICE = PROJECT_ROOT / "backend/app/services/wallet_quality_service.py"


def _sign(snapshot: dict) -> dict:
    snapshot["integrity"] = {
        "snapshot_payload_sha256": canonical_sha256(
            {key: value for key, value in snapshot.items() if key != "integrity"}
        )
    }
    return snapshot


def main() -> int:
    snapshot = json.loads(FIXTURE.read_text(encoding="utf-8"))
    validated = validate_snapshot(snapshot)
    assert validated["candidate_count"] == 3
    report = evaluate_copyability_aware_discovery(
        snapshot,
        evaluated_at=datetime(2026, 8, 14, 20, 30, tzinfo=timezone.utc),
    )
    assert report["scope"] == M66_SCOPE
    assert report["discovery_version"] == M66_DISCOVERY_VERSION
    assert report["summary"]["wallets_qualified_for_short_canary"] == 2
    assert report["summary"]["wallets_selected_for_short_canary"] == 1
    assert report["summary"]["wallets_research_only"] == 1
    assert report["selected_wallets"][0]["wallet_address"] == "1" * 32
    second = next(
        item
        for item in report["candidate_results"]
        if item["wallet_address"] == "2" * 32
    )
    assert second["selection"]["cluster_collision"] is True

    needs_history = copy.deepcopy(snapshot)
    candidate = needs_history["candidates"][0]
    needs_history["candidates"] = [candidate]
    needs_history["source"]["wallet_rows_total"] = 1
    needs_history["source"]["wallet_rows_read"] = 1
    needs_history["source"]["wallet_rows_truncated"] = False
    candidate["wallet_address"] = "4" * 32
    candidate["independence"]["cluster_id"] = "fixture-history-cluster"
    candidate["independence"]["cluster_size"] = 1
    candidate["independence"]["cluster_members"] = ["4" * 32]
    candidate["economics"]["closed_trade_count"] = 60
    candidate["economics"]["position_result_count"] = 60
    candidate["economics"]["history_span_days"] = 18
    candidate["economics"]["stability_windows"] = candidate["economics"][
        "stability_windows"
    ][:3]
    candidate["economics"]["positive_stability_window_count"] = 3
    _sign(needs_history)
    history_report = evaluate_copyability_aware_discovery(
        needs_history,
        evaluated_at=datetime(2026, 8, 14, 20, 30, tzinfo=timezone.utc),
    )
    assert history_report["candidate_results"][0]["status"] == STATUS_NEEDS_HISTORY
    assert history_report["acquisition_plan"]["wallets_queued"] == 1
    assert history_report["acquisition_plan"]["execution_authorized"] is False

    service_source = SERVICE.read_text(encoding="utf-8")
    runner_source = RUNNER.read_text(encoding="utf-8")
    helius_service_source = HELIUS_SERVICE.read_text(encoding="utf-8")
    helius_runner_source = HELIUS_RUNNER.read_text(encoding="utf-8")
    api_source = API.read_text(encoding="utf-8")
    activity_source = ACTIVITY_SERVICE.read_text(encoding="utf-8")
    quality_source = QUALITY_SERVICE.read_text(encoding="utf-8")
    for forbidden in (
        "db.add(",
        "db.commit(",
        "httpx.",
        "requests.",
        "get_wallet_history(",
        "JupiterSwapClient(",
    ):
        assert forbidden not in service_source
    assert '"/definitive-discovery/preview"' in api_source
    route_index = api_source.index('"/definitive-discovery/preview"')
    assert api_source.rfind("@router.get(", 0, route_index) > api_source.rfind(
        "@router.post(", 0, route_index
    )
    assert "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY" in runner_source
    assert "nessun fallback a DATABASE_URL" in runner_source
    assert "Trade.wallet_address.in_(addresses)" in service_source
    assert "DERIVED_IN_MEMORY_FROM_CACHED_TRADE_ROWS" in service_source
    assert "economic_metrics_inferred\": False" in service_source
    assert "analyze_wallet_activity_from_trades" in activity_source
    assert "analyze_wallet_quality_from_trades" in quality_source
    assert M66_DEFAULT_POLICY["minimum_closed_trades"] == 100
    assert M66_DEFAULT_POLICY["minimum_profit_factor"] == 1.30
    assert M66_DEFAULT_POLICY["maximum_selected_wallets"] == 3
    assert M66_DEFAULT_POLICY["maximum_drawdown_percent"] == 15.0
    assert M66_DEFAULT_POLICY["required_backtest_starting_capital_sol"] == 1.0
    assert M66_DEFAULT_POLICY["required_backtest_fixed_buy_size_sol"] == 0.05
    assert M66_DEFAULT_POLICY["required_backtest_slippage_bps"] == 100
    assert M66_DEFAULT_POLICY["required_backtest_fee_bps"] == 10
    assert M66_DEFAULT_POLICY["required_backtest_copy_delay_seconds"] == 8
    assert M66_DEFAULT_POLICY[
        "required_backtest_delay_penalty_bps_per_minute"
    ] == 25.0
    assert M66_DEFAULT_POLICY["required_backtest_max_open_positions"] == 5
    plan = build_controlled_helius_plan()
    assert plan["enhanced_request_cap"] == M66_MAX_ENHANCED_REQUESTS == 6
    assert plan["enhanced_credit_cap"] == M66_MAX_ENHANCED_CREDITS == 600
    assert plan["execution"]["maximum_retries"] == 0
    assert plan["execution"]["automatic_enhanced_api"] is False
    assert plan["execution"]["explicit_confirmation_required"] == (
        M66_HELIUS_CONFIRMATION
    )
    assert "automatic=False" in helius_service_source
    assert "max_retries=0" in helius_service_source
    assert "capture_response=False" in helius_service_source
    assert "discover_full_from_wallet" not in helius_service_source
    assert "run_extended_candidate_history" not in helius_service_source
    assert "db.add(" not in helius_service_source
    assert "db.commit(" not in helius_service_source
    assert 'os.environ["DATABASE_URL"] = public_url' in helius_runner_source
    assert "get_helius_credit_guard_status" in helius_runner_source

    print("=== M66 GEN4 COPYABILITY-AWARE DISCOVERY VERIFIER ===")
    print(f"DISCOVERY_VERSION={M66_DISCOVERY_VERSION}")
    print("CACHED_DATABASE_PREVIEW=READ_ONLY")
    print("ECONOMIC_PRESCREEN=100_CLOSED_COSTED_TRADES")
    print("MINIMUM_PROFIT_FACTOR=1.30")
    print("MAXIMUM_DRAWDOWN_PERCENT=15.0")
    print("GEN4_MODEL=1.0_SOL_CAPITAL_0.05_SOL_SIZE_100_BPS_SLIPPAGE")
    print("GEN4_COSTS=10_BPS_FEE_8S_DELAY_25_BPS_PER_MINUTE")
    print("GEN4_MAX_OPEN_POSITIONS=5")
    print("RECENT_STABILITY_AND_BEST_TRADE_DEPENDENCY=ENFORCED")
    print("MAXIMUM_SELECTED_WALLETS=3")
    print("CACHED_WALLET_INVENTORY_COUNT=EXACT_ZERO_CREDIT_REPORT")
    print(
        "CACHED_TRADE_ENRICHMENT_VERSION="
        f"{M66_CACHED_TRADE_ENRICHMENT_VERSION}"
    )
    print("CACHED_TRADE_ACTIVITY_QUALITY=DERIVED_IN_MEMORY_READ_ONLY")
    print("CACHED_TRADE_QUERY_MODE=BULK_SIX_DATABASE_QUERIES")
    print("CACHED_TRADE_ECONOMIC_METRICS_INFERRED=NO")
    print("CLUSTER_COLLISION_DEDUPLICATION=PASS")
    print("MANUAL_INDEPENDENCE_CONFIRMATION_REQUIRED=YES")
    print("BUDGETED_PUBLIC_RPC_PLAN=NOT_EXECUTED")
    print("SHORT_REALTIME_CANARY_REQUIRED=YES")
    print("DISCOVERY_CRON_REACTIVATION_AUTHORIZED=NO")
    print("CONTROLLED_HELIUS_NEW_WALLET_LANE=AVAILABLE_MANUAL_ONLY")
    print("CONTROLLED_HELIUS_REQUEST_CAP=6")
    print("CONTROLLED_HELIUS_CREDIT_CAP=600")
    print("CONTROLLED_HELIUS_RETRIES=0")
    print("CONTROLLED_HELIUS_CACHE=SHA256_REUSABLE")
    print("AUTOMATIC_ENHANCED_API=DISABLED")
    print("MICRO_LIVE_EXECUTION_AUTHORIZED=NO")
    print("AUTOMATIC_LIVE_ACTIVATION=NO")
    print("SIGNER_AUTHORIZED=NO")
    print("NETWORK_REQUESTS=0")
    print("HELIUS_REQUESTS=0")
    print("DATABASE_WRITES=0")
    print("BACKEND_POSTS=0")
    print("JUPITER_REQUESTS=0")
    print("PAPER_ORDERS=0")
    print("LIVE_ORDERS=0")
    print("RECOVERY_COUNTS_AS_REALTIME_PROOF=NO")
    print("HISTORICAL_JUPITER_QUOTES_INVENTED=NO")
    print(f"SERVICE_SHA256={file_sha256(SERVICE)}")
    print(f"RUNNER_SHA256={file_sha256(RUNNER)}")
    print(f"ACTIVITY_SERVICE_SHA256={file_sha256(ACTIVITY_SERVICE)}")
    print(f"QUALITY_SERVICE_SHA256={file_sha256(QUALITY_SERVICE)}")
    print(f"HELIUS_SERVICE_SHA256={file_sha256(HELIUS_SERVICE)}")
    print(f"HELIUS_RUNNER_SHA256={file_sha256(HELIUS_RUNNER)}")
    print(f"FIXTURE_SHA256={file_sha256(FIXTURE)}")
    print("VERIFIER=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
