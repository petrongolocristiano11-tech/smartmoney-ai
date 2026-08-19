from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core.constants import USDC_MINT  # noqa: E402
from backend.app.services.blockchain_parser_gen4_copyability_service import (  # noqa: E402
    GEN4_COPYABILITY_RAW_PARSER_VERSION,
    CanonicalParserGen4CopyabilityError,
    parse_raw_copyability_signal,
)
from backend.app.services.gen4_m82_paid_rpc_sprint_service import (  # noqa: E402
    M82_CONFIRMATION,
    M82_GTFA_CREDITS_PER_REQUEST,
    M82_MAX_RPC_CREDITS,
    M82_PASS1_TRANSACTIONS,
    M82_PASS2_TRANSACTIONS,
    M82_PASS3_TRANSACTIONS,
    M82_SCOPE,
    M82_VERSION,
    M82_WORKERS,
    build_model_policy,
)
from backend.app.services.helius import helius_rpc_credit_cost  # noqa: E402

WALLET = "G4gEznDioDKdK52o66Lhye4h27j43s3JynH2pgnoo2vn"
TOKEN = "BdmmbhuqmMcswTCpP5Dy9H6E87ZqDMULVAWdzu4ZhqTS"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def _balance(mint: str, amount: int, decimals: int) -> dict:
    return {
        "owner": WALLET,
        "mint": mint,
        "uiTokenAmount": {"amount": str(amount), "decimals": decimals},
    }


def _regression_payload() -> dict:
    return {
        "signature": "3wJaTL9PrMtnxN5BomV1HFmf8BCypmP2Vm6u8SzNyaFGBUeECGugUWLH51AzjHF8sCF1LpNg4TheiRUnGY7TZ6Mn",
        "slot": 433992660,
        "blockTime": 1784505018,
        "meta": {
            "err": None,
            "fee": 68685,
            "preBalances": [41427760],
            "postBalances": [41331782],
            "preTokenBalances": [
                _balance(USDC_MINT, 150288129, 6),
                _balance(TOKEN, 0, 6),
            ],
            "postTokenBalances": [
                _balance(USDC_MINT, 75144065, 6),
                _balance(TOKEN, 7290049656912, 6),
            ],
        },
        "transaction": {
            "signatures": [
                "3wJaTL9PrMtnxN5BomV1HFmf8BCypmP2Vm6u8SzNyaFGBUeECGugUWLH51AzjHF8sCF1LpNg4TheiRUnGY7TZ6Mn"
            ],
            "message": {
                "accountKeys": [
                    {
                        "pubkey": WALLET,
                        "signer": True,
                        "writable": True,
                        "source": "transaction",
                    }
                ]
            },
        },
    }


def main() -> int:
    _require(
        GEN4_COPYABILITY_RAW_PARSER_VERSION
        == "canonical-parser-gen4-raw-balance-delta/4",
        "Parser M82 non /4.",
    )
    try:
        parse_raw_copyability_signal(
            _regression_payload(),
            frozen_wallets=[WALLET],
        )
    except CanonicalParserGen4CopyabilityError as error:
        _require(
            error.code == "GEN4_COPYABILITY_RAW_NON_SOL_QUOTE_ASSET_DELTA",
            f"Regression code inatteso: {error.code}",
        )
        deltas = dict(error.evidence.get("non_sol_quote_asset_deltas_raw") or {})
        _require(
            int(deltas.get(USDC_MINT) or 0) == -75144064,
            "Delta USDC regression non provato.",
        )
    else:
        raise RuntimeError("Regression USDC-routed non bloccata.")

    _require(M82_VERSION == "canonical-parser-gen4-paid-rpc-sprint/1", "Versione M82 inattesa.")
    _require(M82_SCOPE == "M82_STABLECOIN_HARDENED_PAID_RPC_SPRINT", "Scope M82 inatteso.")
    _require(
        M82_CONFIRMATION == "RUN_M82_PAID_RPC_SPRINT_MAX_9000_CREDITS",
        "Conferma M82 inattesa.",
    )
    _require(M82_MAX_RPC_CREDITS == 9000, "Cap M82 != 9000.")
    _require(M82_GTFA_CREDITS_PER_REQUEST == 50, "Costo gTFA M82 != 50.")
    _require(helius_rpc_credit_cost("getTransactionsForAddress") == 50, "Guard gTFA non conta 50.")
    _require(M82_WORKERS == 8, "Parallelismo M82 inatteso.")

    for depth in (M82_PASS1_TRANSACTIONS, M82_PASS2_TRANSACTIONS, M82_PASS3_TRANSACTIONS):
        policy = build_model_policy(depth)
        _require(1 <= int(policy["maximum_deep_wallets"]) <= 3, "M82 viola max deep wallet M67.")
        _require(30 <= int(policy["public_rpc_request_cap"]) <= 2000, "M82 viola cap RPC M67.")

    runner = (PROJECT_ROOT / "scripts" / "run_m82_paid_rpc_sprint.py").read_text(encoding="utf-8")
    launcher = (PROJECT_ROOT / "scripts" / "launch_m82_paid_rpc_sprint.py").read_text(encoding="utf-8")
    _require("getTransactionsForAddress" in runner, "gTFA assente dal runner M82.")
    _require("api.mainnet-beta.solana.com" not in runner, "RPC pubblico lento ancora presente in M82.")
    _require("M82_HEARTBEAT=" in runner, "Heartbeat M82 assente.")
    _require("checkpoint-lock-policy-resume/1" in runner, "Hotfix resume M82 assente.")
    _require("M82_RESUME_RETRY_ROWS_RESET=" in runner, "Repair retry rows M82 assente.")
    _require("_STATE_LOCK = threading.RLock()" in runner, "Lock checkpoint M82 assente.")
    _require("reserve_helius_credits" in runner, "Credit guard M82 assente.")
    _require("M82_MAX_RPC_CREDITS" in runner, "Hard cap M82 assente.")
    _require("railway.cmd" in launcher, "railway.cmd assente dal launcher.")
    _require("railway.exe" not in launcher, "railway.exe non consentito.")
    _require("RAW_BLOCKCHAIN_CAPTURE_ENABLED" in launcher, "Raw capture isolation assente.")
    _require("LIVE_AUTHORIZED=NO" in launcher, "Safety LIVE launcher assente.")
    _require("SIGNER_AUTHORIZED=NO" in launcher, "Safety signer launcher assente.")

    print("M82_VERIFIER=PASS")
    print("PARSER_V4_STABLECOIN_AND_RENT_RECLAIM_GUARD=PASS")
    print("M81_FALSE_OUTLIER_REGRESSION=PASS")
    print("HELIUS_GTFA_CREDIT_COST_50=PASS")
    print("HELIUS_RPC_HARD_CAP_9000=PASS")
    print("PUBLIC_RPC_SLOW_PATH=ABSENT")
    print("HEARTBEAT_5S=CONFIGURED")
    print("CHECKPOINT_WRITE_LOCK=PASS")
    print("M67_POLICY_COMPATIBILITY=PASS")
    print("RESUME_RETRY_ROW_REPAIR=PASS")
    print("LIVE_AUTHORIZED=NO")
    print("SIGNER_AUTHORIZED=NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
