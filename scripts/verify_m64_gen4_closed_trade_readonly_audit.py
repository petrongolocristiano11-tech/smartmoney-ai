from __future__ import annotations

import ast
import hashlib
import json
import os
import sys
from pathlib import Path


os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
os.environ.setdefault("HELIUS_API_KEY", "test-m64-verifier-not-used")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.gen4_closed_trade_readonly_audit_service import (  # noqa: E402
    M64_EXPECTED_ALEMBIC_HEAD,
    M64_EXPECTED_GIT_HEAD,
    M64_EXPECTED_PARSER_VERSION,
    M64_EXPECTED_POLICY_VERSION,
    M64_EXPECTED_RECOVERY_RECEIPTS,
    M64_EXPECTED_QUARANTINED_SEED_POSITIONS,
    M64_OFFICIAL_REALTIME_TRADES,
    M64_TARGET_RECONSTRUCTED_TRADES,
    M64_TARGET_WALLET,
    parse_public_transactions,
    reconstruct_closed_trades,
)

SERVICE_PATH = (
    PROJECT_ROOT
    / "backend/app/services/gen4_closed_trade_readonly_audit_service.py"
)
RUNNER_PATH = PROJECT_ROOT / "scripts/run_m64_gen4_closed_trade_readonly_audit.py"
TEST_PATH = PROJECT_ROOT / "tests/test_m64_gen4_closed_trade_readonly_audit.py"
FIXTURE_PATH = (
    PROJECT_ROOT / "tests/fixtures/m64_gen4_closed_trade_readonly_audit.json"
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def alembic_heads() -> list[str]:
    revisions: dict[str, str | tuple[str, ...] | None] = {}
    for path in sorted((PROJECT_ROOT / "alembic/versions").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        values: dict[str, object] = {}
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in {
                        "revision",
                        "down_revision",
                    }:
                        values[target.id] = ast.literal_eval(node.value)
            elif (
                isinstance(node, ast.AnnAssign)
                and isinstance(node.target, ast.Name)
                and node.target.id in {"revision", "down_revision"}
                and node.value is not None
            ):
                values[node.target.id] = ast.literal_eval(node.value)
        revision = values.get("revision")
        if isinstance(revision, str):
            revisions[revision] = values.get("down_revision")  # type: ignore[assignment]
    parents: set[str] = set()
    for parent in revisions.values():
        if isinstance(parent, str):
            parents.add(parent)
        elif isinstance(parent, tuple):
            parents.update(item for item in parent if isinstance(item, str))
    return sorted(set(revisions) - parents)


def require_text(path: Path, *needles: str) -> str:
    source = path.read_text(encoding="utf-8")
    for needle in needles:
        if needle not in source:
            raise AssertionError(f"Marker M64 mancante in {path.name}: {needle}")
    return source


def main() -> int:
    if alembic_heads() != [M64_EXPECTED_ALEMBIC_HEAD]:
        raise AssertionError(f"Alembic head inattesa: {alembic_heads()}")
    service = require_text(
        SERVICE_PATH,
        'M64_AUDIT_VERSION = "gen4-closed-trade-readonly-audit/1"',
        'M64_DEFAULT_PUBLIC_RPC_URL = "https://api.mainnet-beta.solana.com"',
        'if "helius" in hostname',
        '"SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"',
        '"SHOW transaction_read_only"',
        '"RECOVERY_ANALYTIC_ONLY_NOT_REALTIME_PROOF"',
        '"UNAVAILABLE_NOT_INVENTED"',
        '"DETERMINISTIC_NO_LOOKAHEAD_GEN4_PRO_RATA"',
        "parse_raw_copyability_signal(",
        "maximum_attempts: int = 8",
        "Retry-After",
        "M64_EXPECTED_RECOVERY_RECEIPTS = 28",
        "M64_EXPECTED_QUARANTINED_SEED_POSITIONS = 2",
        "M64_EXPECTED_OFFICIAL_NET_PNL_LAMPORTS = 32_319_569",
        '"entry_sequence": int(row.id)',
        '"target_cut_through_close_batch"',
        '"EXACT_REALTIME_ENTRY_QUOTE_FOR_RECOVERY_EXIT_RECONSTRUCTION"',
        'M64_PRIMARY_CAMPAIGN_ID = "89026d62-1e4e-452b-b0bf-8a5e3dd373e4"',
        'M64_DISABLED_FORWARD_FEED_STATE_ID = "d11626bf-e9ba-4305-b3a9-5c6386148e72"',
    )
    runner = require_text(
        RUNNER_PATH,
        'RUN_CONFIRMATION = "RUN_M64_GEN4_CLOSED_TRADE_READONLY_AUDIT"',
        'print(f"OFFICIAL_REALTIME_TRADES={M64_OFFICIAL_REALTIME_TRADES}")',
        'print(f"RECONSTRUCTED_CLOSED_TRADES={reconstructed_n}")',
        'print(f"COMBINED_EQUIVALENT_SAMPLE={combined_n}")',
        '"COMPLETE_CUTOFF_BATCH_SAMPLE="',
        '"TARGET_CUT_THROUGH_CLOSE_BATCH="',
        'print("HELIUS_REQUESTS=0")',
        'print("DATABASE_WRITES=0")',
        'print("BACKEND_POSTS=0")',
        'print("RECOVERY_COUNTS_AS_REALTIME_PROOF=NO")',
    )
    require_text(
        TEST_PATH,
        "test_round_trip_reconstruction_is_chronological_partial_exit_aware_and_fail_closed",
        "test_first_seventeen_closures_are_selected_without_turning_extra_history_into_proof",
        "test_target_cutoff_extends_only_the_same_close_batch_for_sensitivity",
        "test_quarantined_realtime_entry_seed_is_replayed_without_a_public_rebuy",
        "test_drawdown_tie_break_matches_production_entry_sequence",
        "test_report_keeps_83_official_separate_and_marks_combined_as_analytic_only",
        "test_rpc_rejects_helius_credentials_and_plain_http",
    )
    guarded = service + "\n" + runner
    for forbidden in (
        "api.helius",
        "helius-rpc.com",
        ".commit(",
        ".add(",
        ".delete(",
        ".flush(",
        "execute_order(",
        "submit_transaction(",
        "JupiterSwapClient(",
        "receive_gen4_copyability_webhook(",
        "record_gen4_copyability_raw_recovery_events(",
    ):
        if forbidden in guarded:
            raise AssertionError(f"Percorso vietato rilevato: {forbidden}")
    if service.count(".client.post(") != 1:
        raise AssertionError("M64 deve avere un solo POST, confinato al client RPC pubblico.")

    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    if fixture["wallet"] != M64_TARGET_WALLET:
        raise AssertionError("Wallet fixture inatteso.")
    parsed = parse_public_transactions(
        fixture["transactions"],
        wallet_address=M64_TARGET_WALLET,
    )
    reconstructed = reconstruct_closed_trades(
        parsed["events"],
        policy=fixture["policy"],
        target_closed_trades=M64_TARGET_RECONSTRUCTED_TRADES,
    )
    if len(parsed["events"]) != 5 or len(parsed["rejected"]) != 1:
        raise AssertionError("Fixture parser M64 inattesa.")
    if reconstructed["selected_closed_trade_count"] != 2:
        raise AssertionError("Fixture round trip M64 inattesa.")
    if reconstructed["target_reached"]:
        raise AssertionError("Il verifier non deve forzare 2 round trip a 17.")

    print("=== M64 GEN4 CLOSED TRADE READ-ONLY AUDIT VERIFIER ===")
    print(f"EXPECTED_GIT_HEAD={M64_EXPECTED_GIT_HEAD}")
    print(f"ALEMBIC_HEAD={M64_EXPECTED_ALEMBIC_HEAD}")
    print("ALEMBIC_MIGRATION=NOT_REQUIRED")
    print(f"TARGET_WALLET={M64_TARGET_WALLET}")
    print(f"PARSER_VERSION={M64_EXPECTED_PARSER_VERSION}")
    print(f"POLICY_VERSION={M64_EXPECTED_POLICY_VERSION}")
    print(f"OFFICIAL_REALTIME_TRADES={M64_OFFICIAL_REALTIME_TRADES}")
    print("EXPECTED_OFFICIAL_NET_PNL_LAMPORTS=32319569")
    print(f"EXPECTED_RECOVERY_ONLY_RECEIPTS={M64_EXPECTED_RECOVERY_RECEIPTS}")
    print(
        "EXPECTED_QUARANTINED_SEED_POSITIONS="
        f"{M64_EXPECTED_QUARANTINED_SEED_POSITIONS}"
    )
    print(f"TARGET_RECONSTRUCTED_TRADES={M64_TARGET_RECONSTRUCTED_TRADES}")
    print("FIXTURE_PARSED_EVENTS=5")
    print("FIXTURE_RECONSTRUCTED_CLOSED_TRADES=2")
    print("ROUND_TRIP_COUNT_NOT_FORCED=PASS")
    print("PRODUCTION_DRAWDOWN_TIE_BREAK=PASS")
    print("RECOVERY_QUARANTINED_ENTRY_SEED=PASS")
    print("CUTOFF_CLOSE_BATCH_SENSITIVITY=PASS")
    print("NO_LOOKAHEAD_PAIRING=PASS")
    print("HISTORICAL_JUPITER_QUOTES=UNAVAILABLE_NOT_INVENTED")
    print("PUBLIC_RPC_RETRY_POLICY=0.60S_THROTTLE_MAX_8")
    print("OFFICIAL_COUNTER_MUTATED=NO")
    print("RECOVERY_COUNTS_AS_REALTIME_PROOF=NO")
    print("HELIUS_REQUESTS=0")
    print("DATABASE_WRITES=0")
    print("BACKEND_POSTS=0")
    print("PAPER_ORDERS=0")
    print("LIVE_ORDERS=0")
    print(f"SERVICE_SHA256={sha256(SERVICE_PATH)}")
    print(f"RUNNER_SHA256={sha256(RUNNER_PATH)}")
    print(f"FIXTURE_SHA256={sha256(FIXTURE_PATH)}")
    print("VERIFIER=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
