from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.constants import USDC_MINT  # noqa: E402
from backend.app.services.blockchain_parser_gen4_copyability_service import (  # noqa: E402
    GEN4_COPYABILITY_RAW_PARSER_VERSION,
    CanonicalParserGen4CopyabilityError,
    parse_raw_copyability_signal,
)
from backend.app.services.gen4_closed_trade_readonly_audit_service import (  # noqa: E402
    parse_public_transactions,
)
from backend.app.services.gen4_m82_paid_rpc_sprint_service import (  # noqa: E402
    build_model_policy,
    normalize_full_transaction,
)
from backend.app.services.gen4_zero_helius_pre_micro_live_service import (  # noqa: E402
    simulate_gen4_from_public_events,
)

TARGET = "6ni1gQaVtW38qBsGFfdbNURHyEkizAM7WXZbpcqw18x"
BAD_SELLS = {
    "cALFjQXXcBbsJaGwJsWegtSWdqQe9vLpQaFyLejN9P4byBrQNyDbZJDXKfoZmmzp92vM4rLPD1UJWrThskPmgqA",
    "TmwpXdFDeZ6AhG8erLbMLS9XGCLhxb5bJDKgoDKKJDq8uxjKKcBg3d9gUaJGpfPXDmpVpMpYcmk7CY3enhHXNWE",
}
EXPECTED_REPORT_SHA = "a5ddd0fbf6e8967e81af124a5ed4e0da460fff9e11ca4d9a62b61c1bd3fae436"
EXPECTED_STATE_SHA = "b885c06be268978da22a5b4cc97c3f62258a7661d7ec38029a86984f4f8355c8"
EXPECTED_CACHE_MANIFEST_SHA = "1b70c8133b75da203dec72d057ae686b26fc7cc28832b6b4e4b20d0cc42f10be"
EXPECTED_PARSER_SHA = "b695cad49e49bf227c4cf3621805e5a82ac9a040a743d349a326bfe804e93658"
EXPECTED_CLOSED_AUDIT_SHA = "7e331acc8752f9017d0726481ec2a873f6dfb5a5a2b8010dec5e9ec0ca6f84ee"
EXPECTED_M82_SERVICE_SHA = "33e8d1e97247328ddea29ccc64bebe9e1d77913bdf450e9b6b40ba040ab23847"
EXPECTED_ZERO_SERVICE_SHA = "ce124eb5648676faa275dd75a7777c27c6ce3878a2af6e810908710d1447cfa7"
PARSER_VERSION = "canonical-parser-gen4-raw-balance-delta/4"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise RuntimeError(f"NOT_OBJECT:{path.name}")
    return value


def canonical(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def integer(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _m81_regression_payload() -> dict[str, Any]:
    wallet = "G4gEznDioDKdK52o66Lhye4h27j43s3JynH2pgnoo2vn"
    token = "BdmmbhuqmMcswTCpP5Dy9H6E87ZqDMULVAWdzu4ZhqTS"
    def bal(mint: str, amount: int) -> dict[str, Any]:
        return {"owner": wallet, "mint": mint, "uiTokenAmount": {"amount": str(amount), "decimals": 6}}
    return {
        "signature": "3wJaTL9PrMtnxN5BomV1HFmf8BCypmP2Vm6u8SzNyaFGBUeECGugUWLH51AzjHF8sCF1LpNg4TheiRUnGY7TZ6Mn",
        "slot": 433992660,
        "blockTime": 1784505018,
        "meta": {
            "err": None,
            "fee": 68685,
            "preBalances": [41427760],
            "postBalances": [41331782],
            "preTokenBalances": [bal(USDC_MINT, 150288129), bal(token, 0)],
            "postTokenBalances": [bal(USDC_MINT, 75144065), bal(token, 7290049656912)],
        },
        "transaction": {
            "signatures": ["3wJaTL9PrMtnxN5BomV1HFmf8BCypmP2Vm6u8SzNyaFGBUeECGugUWLH51AzjHF8sCF1LpNg4TheiRUnGY7TZ6Mn"],
            "message": {"accountKeys": [{"pubkey": wallet, "signer": True, "writable": True, "source": "transaction"}]},
        },
    }


def main() -> int:
    audit_dir = Path.home() / "Downloads" / "smartmoney-audits"
    report_path = audit_dir / "smartmoney-m85-neighbor-canonical-lane-report.json"
    state_path = audit_dir / "smartmoney-m85-neighbor-canonical-lane-state.json"
    cache_dir = audit_dir / "smartmoney-m85-helius-rpc-cache"
    manifest_path = cache_dir / "manifest.json"

    print("=== M87 PARSER RENT-RECLAIM HARDENING VERIFIER ===", flush=True)
    print("NETWORK_REQUESTS=0", flush=True)
    print("HELIUS_CREDITS=0", flush=True)
    print("LIVE_AUTHORIZED=NO", flush=True)
    print("SIGNER_AUTHORIZED=NO", flush=True)

    expected = [
        (report_path, EXPECTED_REPORT_SHA, "M85_REPORT"),
        (state_path, EXPECTED_STATE_SHA, "M85_STATE"),
        (manifest_path, EXPECTED_CACHE_MANIFEST_SHA, "M85_CACHE_MANIFEST"),
        (PROJECT_ROOT / "backend/app/services/blockchain_parser_gen4_copyability_service.py", EXPECTED_PARSER_SHA, "PARSER_V4"),
        (PROJECT_ROOT / "backend/app/services/gen4_closed_trade_readonly_audit_service.py", EXPECTED_CLOSED_AUDIT_SHA, "CLOSED_AUDIT_V4"),
        (PROJECT_ROOT / "backend/app/services/gen4_m82_paid_rpc_sprint_service.py", EXPECTED_M82_SERVICE_SHA, "M82_SERVICE_V4"),
        (PROJECT_ROOT / "backend/app/services/gen4_zero_helius_pre_micro_live_service.py", EXPECTED_ZERO_SERVICE_SHA, "ZERO_SERVICE"),
    ]
    for path, expected_sha, label in expected:
        actual = sha(path) if path.is_file() else ""
        if actual != expected_sha:
            raise RuntimeError(f"{label}_SHA_FAILED:{actual or 'MISSING'}")
        print(f"{label}_SHA=PASS", flush=True)

    if GEN4_COPYABILITY_RAW_PARSER_VERSION != PARSER_VERSION:
        raise RuntimeError(f"PARSER_VERSION_INVALID:{GEN4_COPYABILITY_RAW_PARSER_VERSION}")
    print("PARSER_VERSION_V4=PASS", flush=True)

    # M81 stablecoin-routed false outlier remains blocked.
    m81 = _m81_regression_payload()
    m81_wallet = "G4gEznDioDKdK52o66Lhye4h27j43s3JynH2pgnoo2vn"
    try:
        parse_raw_copyability_signal(m81, frozen_wallets=[m81_wallet])
    except CanonicalParserGen4CopyabilityError as error:
        if error.code != "GEN4_COPYABILITY_RAW_NON_SOL_QUOTE_ASSET_DELTA":
            raise RuntimeError(f"M81_REGRESSION_WRONG_CODE:{error.code}")
    else:
        raise RuntimeError("M81_REGRESSION_NOT_BLOCKED")
    print("M81_STABLECOIN_REGRESSION=PASS", flush=True)

    entries_dir = cache_dir / "entries"
    paths = sorted(entries_dir.glob("*.json"))
    if len(paths) != 41:
        raise RuntimeError(f"M85_CACHE_ENTRY_COUNT_INVALID:{len(paths)}")
    print("M85_CACHE_ENTRIES=PASS count=41", flush=True)

    matching: list[dict[str, Any]] = []
    for path in paths:
        entry = load(path)
        if entry.get("schema") != "SMARTMONEY_M82_GTFA_CACHE_ENTRY_V1":
            raise RuntimeError(f"CACHE_SCHEMA_INVALID:{path.name}")
        result = entry.get("result")
        if str(entry.get("result_sha256") or "") != canonical(result):
            raise RuntimeError(f"CACHE_RESULT_SHA_INVALID:{path.name}")
        request = dict(entry.get("request") or {})
        if str(request.get("address") or "") == TARGET:
            matching.append(entry)
    if not matching:
        raise RuntimeError("TARGET_CACHE_ENTRY_NOT_FOUND")

    tx_by_sig: dict[str, dict[str, Any]] = {}
    for entry in matching:
        for item in dict(entry.get("result") or {}).get("data") or []:
            if not isinstance(item, dict):
                continue
            payload = normalize_full_transaction(dict(item))
            if payload is None:
                continue
            signature = str(payload.get("signature") or "")
            if signature:
                tx_by_sig.setdefault(signature, payload)
    if len(tx_by_sig) != 100:
        raise RuntimeError(f"TARGET_TRANSACTION_COUNT_CHANGED:{len(tx_by_sig)}")
    print("TARGET_TRANSACTIONS=PASS count=100", flush=True)

    for signature in sorted(BAD_SELLS):
        payload = tx_by_sig.get(signature)
        if payload is None:
            raise RuntimeError(f"M86_BAD_SELL_NOT_FOUND:{signature}")
        try:
            parse_raw_copyability_signal(payload, frozen_wallets=[TARGET])
        except CanonicalParserGen4CopyabilityError as error:
            if error.code != "GEN4_COPYABILITY_RAW_SELL_TOKEN_ACCOUNT_RENT_RECLAIM_ONLY":
                raise RuntimeError(f"M86_BAD_SELL_WRONG_CODE:{signature}:{error.code}")
            reclaimed = integer(error.evidence.get("token_account_rent_reclaim_lamports"))
            adjusted = integer(error.evidence.get("adjusted_sol_equivalent_delta_lamports"))
            if reclaimed <= 0 or adjusted > 0:
                raise RuntimeError(f"M86_BAD_SELL_RENT_EVIDENCE_INVALID:{signature}")
            print(
                f"M86_BAD_SELL_BLOCKED={signature};rent={reclaimed};adjusted={adjusted}",
                flush=True,
            )
        else:
            raise RuntimeError(f"M86_BAD_SELL_NOT_BLOCKED:{signature}")

    txs = sorted(
        tx_by_sig.values(),
        key=lambda row: (integer(row.get("blockTime")), integer(row.get("slot")), str(row.get("signature") or "")),
    )
    parsed = parse_public_transactions(txs, wallet_address=TARGET)
    policy = build_model_policy(100)
    backtest = simulate_gen4_from_public_events(parsed["events"], policy=policy)
    closed = [dict(item) for item in backtest.get("closed_trades") or []]
    absurd = [item for item in closed if abs(float(item.get("pnl_sol") or 0.0)) > 1000.0]
    metrics = dict(backtest.get("metrics") or {})
    if absurd:
        raise RuntimeError(f"M86_ABSURD_TRADES_REMAIN:{len(absurd)}")
    print(f"M87_REPLAY_CLOSED_TRADES={metrics.get('closed_trade_count')}", flush=True)
    print(f"M87_REPLAY_NET_PNL_SOL={metrics.get('net_pnl_sol')}", flush=True)
    print(f"M87_REPLAY_PF={metrics.get('profit_factor')}", flush=True)
    print("ABSURD_TRADES_GT_1000_SOL=0", flush=True)
    print("PARSER_V4_ECONOMIC_OUTPUT_SAFE_FOR_M81_M86=YES", flush=True)
    print("M87_VERIFIER=PASS", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"M87_VERIFIER=FAILED {type(exc).__name__}:{' '.join(str(exc).split())[:500]}", flush=True)
        raise SystemExit(1)
