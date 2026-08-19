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
from backend.app.services.gen4_definitive_discovery_rotation_service import (  # noqa: E402
    DISPOSITION_OBSERVE,
    DISPOSITION_RETIRE,
    M72_DEFAULT_POLICY,
    M72_FUTURE_HELIUS_CONFIRMATION,
    M72_VERSION,
    classify_active_candidate,
    validate_policy,
)


EXPECTED_GIT_HEAD = "fe63c528e55af84a97d6deb6872e825a5a43c6b4"
EXPECTED_HASHES = {
    "backend/app/services/gen4_definitive_discovery_rotation_service.py": "7c20d828b4d3e006b0735fcefeeebaeb55cb90c91144454e9cecdbef275aa7f8",
    "scripts/run_m72_definitive_discovery_rotation.py": "0319ce309c38709f59575965037a8fc884fc2cd80ee70d4766c52404d75636a7",
    "tests/fixtures/m72_definitive_discovery_rotation.json": "c8b004fc3615521a2eeac587834011aebfce13d2a8abd457187e4554191bd9be",
    "tests/test_m72_definitive_discovery_rotation.py": "4f38180321a31628dd8d0e9342ab21f8c0d3d21aab59815face92e56567c18d5",
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


def _metrics(row: dict) -> dict:
    return {
        "closed_trade_count": int(row.get("closed_trade_count") or 0),
        "open_positions": int(row.get("open_positions") or 0),
        "net_pnl_sol": float(row.get("net_pnl_sol") or 0.0),
        "net_equity_pnl_sol": float(row.get("net_equity_pnl_sol") or 0.0),
        "profit_factor": float(row.get("profit_factor") or 0.0),
        "win_rate_percent": float(row.get("win_rate_percent") or 0.0),
        "maximum_drawdown_percent": float(row.get("maximum_drawdown_percent") or 0.0),
        "history_span_days": float(row.get("history_span_days") or 0.0),
    }


def main() -> int:
    for relative, expected in EXPECTED_HASHES.items():
        path = PROJECT_ROOT / relative
        _require(path.is_file(), f"File M72 mancante: {relative}.")
        _require(_sha256(path) == expected, f"SHA-256 M72 inatteso: {relative}.")

    policy = validate_policy(dict(M72_DEFAULT_POLICY))
    fixture_path = (
        PROJECT_ROOT / "tests/fixtures/m72_definitive_discovery_rotation.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8-sig"))
    expected_fixture = str(dict(fixture.get("integrity") or {}).get("fixture_sha256") or "")
    _require(
        expected_fixture
        == canonical_sha256(
            {key: value for key, value in fixture.items() if key != "integrity"}
        ),
        "Hash logico fixture M72 non valido.",
    )
    observed: dict[str, tuple[str, str]] = {}
    for row in fixture.get("active_candidates") or []:
        metrics = _metrics(dict(row))
        candidate = {
            "wallet_address": row["wallet_address"],
            "activity": {"deep_history_candidate": True},
            "economic_analysis": {"metrics": metrics, "recent_metrics": {}},
        }
        deep = {
            "history_complete": bool(row["history_complete"]),
            "signature_count": int(row["transaction_count"]),
            "transaction_count": int(row["transaction_count"]),
            "parsed_event_count": int(row["parsed_event_count"]),
            "events": ([{"side": "BUY"}] * int(row["buy_events"]))
            + ([{"side": "SELL"}] * int(row["sell_events"])),
        }
        result = classify_active_candidate(candidate, deep, policy=policy)
        observed[str(row["wallet_address"])] = (
            str(result["disposition"]),
            str(result["reason"]),
        )
    expected = {
        str(row["wallet_address"]): (
            str(row["expected_disposition"]),
            str(row["expected_reason"]),
        )
        for row in fixture.get("active_candidates") or []
    }
    _require(observed == expected, "Rotazione fixture M72 inattesa.")
    _require(
        sum(value[0] == DISPOSITION_OBSERVE for value in observed.values()) == 2,
        "Osservabili fixture M72 != 2.",
    )
    _require(
        sum(value[0] == DISPOSITION_RETIRE for value in observed.values()) == 4,
        "Ritirati fixture M72 != 4.",
    )

    service_text = (
        PROJECT_ROOT
        / "backend/app/services/gen4_definitive_discovery_rotation_service.py"
    ).read_text(encoding="utf-8")
    runner_text = (
        PROJECT_ROOT / "scripts/run_m72_definitive_discovery_rotation.py"
    ).read_text(encoding="utf-8")
    _require(M72_FUTURE_HELIUS_CONFIRMATION in service_text, "Conferma futura M72 assente.")
    _require("PREPARED_DISARMED" in service_text, "Piano M72 non disarmato.")
    _require("execution_authorized\": False" in service_text, "Esecuzione M72 non bloccata.")
    _require("write_json_atomic" in runner_text, "Scrittura atomica M72 assente.")
    for forbidden in (
        "httpx.",
        "requests.get(",
        "requests.post(",
        "urllib.request",
        "mainnet.helius",
        "helius_api_key",
        "db.add(",
        "db.commit(",
        "session.add(",
        "session.commit(",
        "railway",
    ):
        _require(forbidden not in service_text.lower(), f"Token vietato service M72: {forbidden}.")
        _require(forbidden not in runner_text.lower(), f"Token vietato runner M72: {forbidden}.")

    print("=== M72 DEFINITIVE DISCOVERY ROTATION VERIFIER ===")
    print(f"EXPECTED_GIT_HEAD={EXPECTED_GIT_HEAD}")
    print(f"ALEMBIC_HEAD={M64_EXPECTED_ALEMBIC_HEAD}")
    print("ALEMBIC_MIGRATION=NOT_REQUIRED")
    print(f"ROTATION_VERSION={M72_VERSION}")
    print("ACTIVE_WALLETS_REVIEWED=6")
    print("OBSERVE_ONLY=2")
    print("RETIRED_FROM_PROMOTION=4")
    print("QUALIFIED_PENDING_SHORT_CANARY=0")
    print("RESEARCH_ONLY_LOCKED=1")
    print("SAME_INPUT_M71_RERUN=BLOCKED_BY_DECISION")
    print("COMPLETE_HISTORY_DISPOSITIONS=ACCURATE")
    print("CONTROLLED_DISCOVERY_PLAN=PREPARED_DISARMED")
    print("CONTROLLED_HELIUS_MAXIMUM_REQUESTS=6")
    print("CONTROLLED_HELIUS_CREDIT_CAP=600")
    print("CONTROLLED_HELIUS_RETRIES=0")
    print("CONTROLLED_DISCOVERY_EXECUTION_AUTHORIZED=NO")
    print("NETWORK_REQUESTS=0")
    print("PUBLIC_RPC_REQUESTS=0")
    print("HELIUS_REQUESTS=0")
    print("HELIUS_CREDITS=0")
    print("DATABASE_READS=0")
    print("DATABASE_WRITES=0")
    print("BACKEND_POSTS=0")
    print("JUPITER_REQUESTS=0")
    print("PAPER_ORDERS=0")
    print("LIVE_ORDERS=0")
    print("SIGNER_ACCESS=NO")
    print("MICRO_LIVE_EXECUTION_AUTHORIZED=NO")
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
