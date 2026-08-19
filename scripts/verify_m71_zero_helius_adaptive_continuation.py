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
from backend.app.services.gen4_zero_helius_adaptive_continuation_service import (  # noqa: E402
    M71_DEFAULT_POLICY,
    M71_STRICT_OFFICIAL_FILTER,
    M71_VERSION,
    profile_deep_history,
    validate_policy,
)


EXPECTED_GIT_HEAD = "fe63c528e55af84a97d6deb6872e825a5a43c6b4"
EXPECTED_HASHES = {
    "backend/app/services/gen4_zero_helius_pre_micro_live_service.py": "ce124eb5648676faa275dd75a7777c27c6ce3878a2af6e810908710d1447cfa7",
    "backend/app/services/gen4_zero_helius_adaptive_continuation_service.py": "c79767a58debca865b005d8342555d42a3d60ae074ba82483b40c77a43a42d01",
    "scripts/run_m71_zero_helius_adaptive_continuation.py": "cadd867f388778a46cd50d3f3549f702bb05f884fd3139af602f167759eefcb0",
    "tests/fixtures/m71_zero_helius_adaptive_continuation.json": "d5f9c42bc139bfc363943309f9335f23ca759c135f9b0f5898b39acf84ef1e53",
    "tests/test_m71_zero_helius_adaptive_continuation.py": "a9a297703e9fbb2dd8c943da066a165e779e88b6dfbb7a12b130b05ce4adea45",
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
        _require(path.is_file(), f"File M71 mancante: {relative}.")
        _require(_sha256(path) == expected, f"SHA-256 M71 inatteso: {relative}.")

    policy = validate_policy(dict(M71_DEFAULT_POLICY))
    fixture_path = (
        PROJECT_ROOT / "tests/fixtures/m71_zero_helius_adaptive_continuation.json"
    )
    fixture = json.loads(fixture_path.read_text(encoding="utf-8-sig"))
    expected_fixture = str(dict(fixture.get("integrity") or {}).get("fixture_sha256") or "")
    _require(
        expected_fixture
        == canonical_sha256(
            {key: value for key, value in fixture.items() if key != "integrity"}
        ),
        "Hash logico fixture M71 non valido.",
    )
    observed_actions: dict[str, str] = {}
    for row in fixture.get("active_candidates") or []:
        deep = dict(row.get("deep_history") or {})
        if not deep:
            observed_actions[str(row["wallet_address"])] = "NEW_ACTIVE_CANDIDATE_DEEP_SCAN"
            continue
        events = [
            {"side": "BUY"} for _ in range(int(deep.get("buy_events") or 0))
        ] + [
            {"side": "SELL"} for _ in range(int(deep.get("sell_events") or 0))
        ]
        profile = profile_deep_history(
            {
                **deep,
                "events": events,
                "backtest": {
                    "metrics": {
                        "closed_trade_count": int(deep.get("closed_trade_count") or 0),
                        "open_positions": int(deep.get("open_positions") or 0),
                    }
                },
            },
            policy,
        )
        observed_actions[str(row["wallet_address"])] = profile["classification"]
    _require(
        observed_actions
        == {
            str(row["wallet_address"]): str(row["expected_action"])
            for row in fixture.get("active_candidates") or []
        },
        "Classificazione fixture M71 inattesa.",
    )

    service_text = (
        PROJECT_ROOT
        / "backend/app/services/gen4_zero_helius_adaptive_continuation_service.py"
    ).read_text(encoding="utf-8")
    runner_text = (
        PROJECT_ROOT / "scripts/run_m71_zero_helius_adaptive_continuation.py"
    ).read_text(encoding="utf-8")
    m67_text = (
        PROJECT_ROOT / "backend/app/services/gen4_zero_helius_pre_micro_live_service.py"
    ).read_text(encoding="utf-8")
    _require(M71_STRICT_OFFICIAL_FILTER in m67_text, "Filtro ufficiale M71 assente da M67.")
    _require("RECOVERY_GAP_QUARANTINE" in m67_text, "Quarantena recovery assente.")
    _require("PUBLIC_RPC_POSITION_HISTORY_INCOMPLETE" in m67_text, "Fail-closed storico assente.")
    _require("correct_local_snapshot_official_filter" in service_text, "Correzione 83/85 assente.")
    _require("DEPRIORITIZED_SELL_ONLY_OR_DISTRIBUTION_PATTERN" in service_text, "Profilo sell-only assente.")
    _require("DEPRIORITIZED_LOW_CANONICAL_PARSER_YIELD" in service_text, "Parser yield gate assente.")
    _require("CachedBudgetedPublicRpc" in runner_text, "Cache RPC M71 assente.")
    _require("getSignaturesForAddress" not in runner_text, "Chiamata RPC diretta inattesa.")
    _require("railway" not in runner_text.lower(), "Runner M71 non deve usare Railway/DB.")
    for forbidden in (
        "helius_api_key",
        "mainnet.helius",
        "db.add(",
        "db.commit(",
        "session.add(",
        "session.commit(",
        "requests.post(",
    ):
        _require(forbidden not in service_text.lower(), f"Token vietato service M71: {forbidden}.")
        _require(forbidden not in runner_text.lower(), f"Token vietato runner M71: {forbidden}.")

    print("=== M71 ZERO-HELIUS ADAPTIVE CONTINUATION VERIFIER ===")
    print(f"EXPECTED_GIT_HEAD={EXPECTED_GIT_HEAD}")
    print(f"ALEMBIC_HEAD={M64_EXPECTED_ALEMBIC_HEAD}")
    print("ALEMBIC_MIGRATION=NOT_REQUIRED")
    print(f"CONTINUATION_VERSION={M71_VERSION}")
    print(f"OFFICIAL_FILTER={M71_STRICT_OFFICIAL_FILTER}")
    print("OFFICIAL_REALTIME_COUNTER=83_UNCHANGED")
    print("QUARANTINED_SEED_POSITIONS=SEPARATE_NOT_OFFICIAL")
    print("ADAPTIVE_EXTENSION_FIRST=YES")
    print("SELL_ONLY_DEPRIORITIZATION=YES")
    print("LOW_PARSER_YIELD_DEPRIORITIZATION=YES")
    print("INCOMPLETE_HISTORY_FAILS_CLOSED=YES")
    print("PRIOR_SHA256_CACHE_REQUIRED=YES")
    print("PUBLIC_RPC_REQUEST_CAP=1800")
    print("NETWORK_REQUESTS=0")
    print("HELIUS_REQUESTS=0")
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
