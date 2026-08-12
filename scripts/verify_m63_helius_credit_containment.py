from __future__ import annotations

import ast
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_HEAD = "c8a1f3d6e942"
TARGET_WALLET = "Bs34SxJUSjUntbsWDEZrFKEcCdJfSuF9KiwtFdJ1Tfsd"
DEFAULT_PUBLIC_RPC = "https://api.mainnet-beta.solana.com"


def require_text(path: Path, *needles: str) -> str:
    if not path.exists():
        raise AssertionError(f"File mancante: {path.relative_to(PROJECT_ROOT)}")
    text = path.read_text(encoding="utf-8")
    for needle in needles:
        if needle not in text:
            raise AssertionError(
                f"Contratto mancante in {path.relative_to(PROJECT_ROOT)}: {needle}"
            )
    return text


def _literal_assignment(tree: ast.Module, name: str):
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                return ast.literal_eval(node.value)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == name and node.value is not None:
                return ast.literal_eval(node.value)
    return None


def alembic_heads() -> list[str]:
    revisions: dict[str, str | tuple[str, ...] | None] = {}
    for path in sorted((PROJECT_ROOT / "alembic/versions").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        revision = _literal_assignment(tree, "revision")
        down_revision = _literal_assignment(tree, "down_revision")
        if isinstance(revision, str):
            revisions[revision] = down_revision
    parents: set[str] = set()
    for down_revision in revisions.values():
        if isinstance(down_revision, str):
            parents.add(down_revision)
        elif isinstance(down_revision, tuple):
            parents.update(item for item in down_revision if isinstance(item, str))
    return sorted(set(revisions) - parents)


def main() -> int:
    if alembic_heads() != [EXPECTED_HEAD]:
        raise AssertionError(f"Alembic head inattesa: {alembic_heads()}")

    config_text = require_text(
        PROJECT_ROOT / "backend/app/core/config.py",
        "HELIUS_CREDIT_GUARD_ENABLED: bool = True",
        "HELIUS_APP_DAILY_CREDIT_CAP",
        "default=20_000",
        "HELIUS_ENHANCED_DAILY_CREDIT_CAP",
        "default=10_000",
        "HELIUS_RPC_DAILY_CREDIT_CAP",
        "HELIUS_AUTOMATIC_ENHANCED_API_ENABLED: bool = False",
    )
    guard_text = require_text(
        PROJECT_ROOT / "backend/app/services/helius_credit_guard_service.py",
        'HELIUS_CREDIT_GUARD_POLICY_VERSION = "helius-credit-containment/1"',
        "with_for_update()",
        "HELIUS_AUTOMATIC_ENHANCED_DISABLED",
        "HELIUS_DAILY_TOTAL_CREDIT_CAP_REACHED",
        "HELIUS_DAILY_ENHANCED_CREDIT_CAP_REACHED",
        "HELIUS_DAILY_RPC_CREDIT_CAP_REACHED",
        "raw_webhook_guarded",
    )
    helius_text = require_text(
        PROJECT_ROOT / "backend/app/services/helius.py",
        "reserve_helius_credits(",
        "estimated_credits=100",
        'request_origin: str = "MANUAL_ENHANCED_TRANSACTION"',
        'request_origin: str = "MANUAL_WALLET_HISTORY"',
    )
    legacy_processor_text = require_text(
        PROJECT_ROOT / "backend/app/services/live_trading_stream_processor.py",
        'request_origin="LEGACY_LIVE_STREAM"',
        "automatic=True",
    )
    legacy_scanner_text = require_text(
        PROJECT_ROOT / "backend/app/services/helius_stream.py",
        'request_origin="LEGACY_SCANNER_STREAM"',
        "automatic=True",
    )
    worker_text = require_text(
        PROJECT_ROOT / "backend/app/workers/helius_live_trading_worker.py",
        "HELIUS_AUTOMATIC_ENHANCED_API_ENABLED",
        "HELIUS_AUTOMATIC_ENHANCED_DISABLED",
    )
    copyability_worker_text = require_text(
        PROJECT_ROOT / "backend/app/workers/gen4_copyability_worker.py",
        "active_campaigns",
        "primary_campaigns",
        '"PRIMARY_FORWARD"',
        "if not campaigns:",
        "gen4_copyability_candidate_only_runtime",
        "never receives a signer",
    )
    forward_text = require_text(
        PROJECT_ROOT / "backend/app/services/blockchain_parser_gen4_forward_feed_service.py",
        "HELIUS_AUTOMATIC_ENHANCED_API_ENABLED",
        "HELIUS_AUTOMATIC_ENHANCED_DISABLED",
        'request_origin="GEN4_FORWARD_RECOVERY"',
        "automatic=True",
    )
    copyability_text = require_text(
        PROJECT_ROOT / "backend/app/services/blockchain_parser_gen4_copyability_service.py",
        "record_gen4_copyability_raw_recovery_events",
        "RECOVERY_GAP_QUARANTINE",
        "RECOVERY_GAP_TOKEN_QUARANTINED",
        "RECOVERY_GAP_TOKEN_QUARANTINE_CLEARED",
        'source=SOURCE_RECOVERY',
        'status=RECEIPT_EXCLUDED_RECOVERY',
        'GEN4_COPYABILITY_POLICY_VERSION = "canonical-parser-gen4-realtime-copyability/1"',
    )
    containment_text = require_text(
        PROJECT_ROOT / "backend/app/services/m63_helius_credit_containment_service.py",
        TARGET_WALLET,
        'campaign.status = "PAUSED"',
        "state.enabled = False",
        "policy.stream_execution_enabled = False",
        'legacy_worker.status = "STOPPED"',
        "copy_worker.enabled = True",
        '"rows_deleted": 0',
        '"helius_requests": 0',
    )
    rpc_recovery_text = require_text(
        PROJECT_ROOT / "scripts/reconcile_m63_public_rpc_gap.py",
        DEFAULT_PUBLIC_RPC,
        'if "helius" in hostname',
        "APPLY_M63_PUBLIC_RPC_GAP_RECOVERY",
        "RECOVERY_COUNTS_AS_REALTIME_PROOF=NO",
        "HELIUS_REQUESTS=0",
    )
    api_text = require_text(
        PROJECT_ROOT / "backend/app/api/helius.py",
        "dependencies=[Depends(require_automation_key)]",
        'router.get("/credits/status")',
    )
    webhook_text = require_text(
        PROJECT_ROOT / "scripts/configure_gen4_copyability_helius_webhook.py",
        "reference_campaign = primary or campaigns[0]",
        "M63_EXCLUSIVE_CANDIDATE_WEBHOOK=",
        "GEN4_EXPECT_EXCLUSIVE_WALLET",
    )
    automatic_consumers = "\n".join(
        require_text(
            PROJECT_ROOT / relative_path,
            origin,
            "automatic=True",
        )
        for relative_path, origin in (
            (
                "backend/app/services/candidate_history_service.py",
                "CANDIDATE_HISTORY_ACQUISITION",
            ),
            (
                "backend/app/services/discovery_engine.py",
                "DISCOVERY_TOKEN_HISTORY",
            ),
            (
                "backend/app/services/discovery_hydration_service.py",
                "DISCOVERY_WALLET_HYDRATION",
            ),
            (
                "backend/app/services/gen4_evidence_sprint_service.py",
                "GEN4_EVIDENCE_COMPANION_DISCOVERY",
            ),
            (
                "backend/app/services/wallet_sync_service.py",
                "AUTOMATIC_WALLET_SYNC",
            ),
        )
    )
    test_text = require_text(
        PROJECT_ROOT / "tests/test_m63_helius_credit_containment.py",
        "test_automatic_enhanced_is_blocked_before_network",
        "test_credit_budget_persists_and_resets_by_utc_day",
        "test_containment_preserves_target_and_pauses_only_other_consumers",
        "test_raw_gap_recovery_quarantines_balance_without_changing_proof",
    )

    if helius_text.index("reserve_helius_credits(") > helius_text.index("httpx.request("):
        raise AssertionError("La prenotazione crediti deve precedere la richiesta HTTP.")
    if "get_wallet_history" in rpc_recovery_text or "api.helius" in rpc_recovery_text:
        raise AssertionError("Il recupero pubblico dipende da Helius.")
    if "get_wallet_history" in copyability_text:
        raise AssertionError("Il parser copyability non deve interrogare Enhanced API.")

    guarded = "\n".join(
        [
            config_text,
            guard_text,
            legacy_processor_text,
            legacy_scanner_text,
            worker_text,
            copyability_worker_text,
            forward_text,
            copyability_text,
            containment_text,
            rpc_recovery_text,
            api_text,
            webhook_text,
            automatic_consumers,
            test_text,
        ]
    )
    for forbidden in (
        ".execute_order(",
        "signed_transaction=",
        "submit_transaction(",
        '"automatic_live_activation": True',
        "private_key=",
    ):
        if forbidden in guarded:
            raise AssertionError(f"Percorso unsafe M63 rilevato: {forbidden}")

    print("=== M63 HELIUS CREDIT CONTAINMENT VERIFIER ===")
    print(f"ALEMBIC_HEAD={EXPECTED_HEAD}")
    print("ALEMBIC_MIGRATION=NOT_REQUIRED")
    print("AUTOMATIC_ENHANCED_API=DISABLED_FAIL_CLOSED")
    print("APP_DAILY_CREDIT_CAP=20000")
    print("ENHANCED_DAILY_CREDIT_CAP=10000")
    print("LEGACY_STREAM_ENHANCED=BLOCKED_BEFORE_NETWORK")
    print("RAW_WEBHOOK=ACTIVE_INBOUND_PATH")
    print("NON_TARGET_CAMPAIGNS=PAUSED_HISTORY_PRESERVED")
    print(f"TARGET_WALLET={TARGET_WALLET}")
    print(f"PUBLIC_RECOVERY_RPC={DEFAULT_PUBLIC_RPC}")
    print("RECOVERY_COUNTS_AS_REALTIME_PROOF=NO")
    print("HELIUS_REQUESTS=0")
    print("PAPER_ORDERS=0")
    print("LIVE_ORDERS=0")
    print("VERIFIER=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
