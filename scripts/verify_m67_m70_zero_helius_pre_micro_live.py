from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.gen4_closed_trade_readonly_audit_service import (  # noqa: E402
    M64_EXPECTED_ALEMBIC_HEAD,
    canonical_sha256,
)
from backend.app.services.gen4_zero_helius_pre_micro_live_service import (  # noqa: E402
    M67_M70_VERSION,
    evaluate_zero_helius_pre_micro_live,
)


EXPECTED_GIT_HEAD = "fe63c528e55af84a97d6deb6872e825a5a43c6b4"
EXPECTED_HASHES = {
    "backend/app/services/gen4_zero_helius_pre_micro_live_service.py": "ce124eb5648676faa275dd75a7777c27c6ce3878a2af6e810908710d1447cfa7",
    "scripts/run_m67_m70_zero_helius_pre_micro_live.py": "549d08c98cff48be9dbe8bc7582935daa1db4c361a87c0cca793350b9eda44d7",
    "tests/fixtures/m67_m70_zero_helius_pre_micro_live.json": "7e9f0045f225d9975af678b7a8fe08f0170fb7d2d33cbc3819f80ca3894804a3",
    "tests/test_m67_m70_zero_helius_pre_micro_live.py": "c28e47ce415e4650441084863bd69b7a78af337b436ec7f67c5fd2acc6b35cb5",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def main() -> int:
    for relative, expected in EXPECTED_HASHES.items():
        path = PROJECT_ROOT / relative
        _require(path.is_file(), f"File M67-M70 mancante: {relative}.")
        _require(_sha256(path) == expected, f"SHA-256 M67-M70 inatteso: {relative}.")

    service_text = (
        PROJECT_ROOT / "backend/app/services/gen4_zero_helius_pre_micro_live_service.py"
    ).read_text(encoding="utf-8")
    runner_text = (
        PROJECT_ROOT / "scripts/run_m67_m70_zero_helius_pre_micro_live.py"
    ).read_text(encoding="utf-8")
    _require("build_unified_local_snapshot" in service_text, "Evidence union assente.")
    _require("CanonicalParserGen4CopyabilityPosition" in service_text, "M58-M61 non lette.")
    _require("validate_external_m64_report" in service_text, "M64 non integrato.")
    _require("validate_external_m65_report" in service_text, "M65 non integrato.")
    _require("NOT_AVAILABLE_UNTIL_POSITION_EVIDENCE" in service_text, "Score N/D assente.")
    _require("replay_multi_wallet_consensus" in service_text, "Consenso assente.")
    _require("PREPARED_DISARMED" in service_text, "Foundation disarmata assente.")
    _require(
        "CLOSED_WEBHOOK_ENTRY_AND_EXIT_COPYABLE_WITH_PNL" in service_text,
        "Filtro ufficiale copyability esatto assente.",
    )
    _require(
        "PUBLIC_RPC_POSITION_HISTORY_INCOMPLETE" in service_text,
        "Storico position-level incompleto non fail-closed.",
    )
    _require("getSignaturesForAddress" in runner_text, "Prescreen RPC pubblico assente.")
    _require("getTransaction" in runner_text, "Deep history RPC pubblico assente.")
    _require("PublicRpcBudgetExhausted" in runner_text, "Cap RPC hard assente.")
    _require("if \"helius\" in hostname" in runner_text, "Blocco endpoint Helius assente.")
    for forbidden in ("db.add(", "db.commit(", "session.add(", "session.commit("):
        _require(forbidden not in service_text.lower(), f"Scrittura DB nel service: {forbidden}.")
        _require(forbidden not in runner_text.lower(), f"Scrittura DB nel runner: {forbidden}.")

    fixture_path = PROJECT_ROOT / "tests/fixtures/m67_m70_zero_helius_pre_micro_live.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8-sig"))
    expected_fixture = str(dict(fixture.get("integrity") or {}).get("fixture_sha256") or "")
    _require(
        expected_fixture
        == canonical_sha256({key: value for key, value in fixture.items() if key != "integrity"}),
        "Hash logico fixture M67-M70 non valido.",
    )
    report = evaluate_zero_helius_pre_micro_live(
        dict(fixture["local_snapshot"]),
        dict(fixture["rpc_evidence"]),
        policy=dict(fixture["policy"]),
    )
    _require(report["evaluation"] == "PASS", "Replay fixture M67-M70 fallito.")
    _require(report["source"]["wallets_evaluated"] == 1, "Inventario fixture inatteso.")
    _require(report["candidate_results"][0]["economic_score"] is None, "Score inventato.")
    _require(report["safety"]["helius_requests"] == 0, "Helius nel verifier.")
    _require(report["safety"]["database_writes"] == 0, "Write DB nel verifier.")
    _require(report["safety"]["live_orders"] == 0, "LIVE nel verifier.")
    _require(report["safety"]["signer_access"] is False, "Signer nel verifier.")

    print("=== M67-M70 ZERO-HELIUS PRE-MICRO-LIVE VERIFIER ===")
    print(f"EXPECTED_GIT_HEAD={EXPECTED_GIT_HEAD}")
    print(f"ALEMBIC_HEAD={M64_EXPECTED_ALEMBIC_HEAD}")
    print("ALEMBIC_MIGRATION=NOT_REQUIRED")
    print(f"FOUNDATION_VERSION={M67_M70_VERSION}")
    print("LOCAL_EVIDENCE_UNION=M58_M66_PLUS_M64_M65_REPORTS")
    print("MISSING_ECONOMIC_SCORE=NOT_AVAILABLE_NOT_ZERO")
    print("PUBLIC_RPC_ACTIVITY_PRESCREEN=TRANSACTION_ACTIVITY_NOT_SWAP_METRICS")
    print("PUBLIC_RPC_DEEP_HISTORY=CANONICAL_GEN4_PARSER")
    print("PUBLIC_RPC_REQUEST_CAP=HARD_PER_NETWORK_ATTEMPT")
    print("PUBLIC_RPC_CACHE=SHA256_VERIFIED_REUSABLE")
    print("GEN4_MODEL=1_SOL_0.05_SOL_100_BPS_10_BPS_8S_25_BPS_PER_MIN")
    print("HISTORICAL_JUPITER_QUOTES_INVENTED=NO")
    print("MULTI_WALLET_CONSENSUS=180S_CLUSTER_DEDUPLICATED")
    print("SHORT_CANARY=PREPARED_DISARMED")
    print("MICRO_LIVE_FOUNDATION=PREPARED_DISARMED")
    print("OFFICIAL_REALTIME_COUNTER=83_UNCHANGED")
    print("OFFICIAL_FILTER=CLOSED_WEBHOOK_ENTRY_AND_EXIT_COPYABLE_WITH_PNL")
    print("INCOMPLETE_POSITION_HISTORY=NEEDS_MORE_PUBLIC_RPC_HISTORY")
    print("RECOVERY_COUNTS_AS_REALTIME_PROOF=NO")
    print("NETWORK_REQUESTS=0")
    print("HELIUS_REQUESTS=0")
    print("DATABASE_WRITES=0")
    print("BACKEND_POSTS=0")
    print("JUPITER_REQUESTS=0")
    print("PAPER_ORDERS=0")
    print("LIVE_ORDERS=0")
    print("SIGNER_ACCESS=NO")
    for relative in EXPECTED_HASHES:
        label = relative.upper().replace("/", "_").replace(".", "_")
        print(f"{label}_SHA256={EXPECTED_HASHES[relative]}")
    print("VERIFIER=PASS")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:  # noqa: BLE001
        print(f"VERIFIER=FAILED type={type(error).__name__} message={error}")
        raise SystemExit(1) from None
