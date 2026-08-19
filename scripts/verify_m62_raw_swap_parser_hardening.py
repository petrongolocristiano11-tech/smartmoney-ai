from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVICE_PATH = (
    PROJECT_ROOT
    / "backend"
    / "app"
    / "services"
    / "blockchain_parser_gen4_copyability_service.py"
)
FIXTURE_PATH = PROJECT_ROOT / "tests" / "fixtures" / "m62_raw_parser_audit.json"

CANDIDATE_CAMPAIGN_ID = "e5eaf7b6-a4e7-4182-96a2-d5f6af668e74"
PRIMARY_CAMPAIGN_ID = "89026d62-1e4e-452b-b0bf-8a5e3dd373e4"
CANDIDATE_WALLET = "Bs34SxJUSjUntbsWDEZrFKEcCdJfSuF9KiwtFdJ1Tfsd"
SOL_MINT = "So11111111111111111111111111111111111111112"
EXCLUDED_MINTS = frozenset(
    {
        SOL_MINT,
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
        "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
        "11111111111111111111111111111111",
    }
)

NATIVE_ONLY_SIGNATURES = {
    "4RTrNZ8cCqhiJf7uDrqC1sAHwzaPUJxTjT93zK78qYszxQPy2ycLzhbPxLS4oBaiagiVYikppDV6ty2eCur3Bnyn",
    "3bjazFxQnHDuP4sMKeoWLWHHeigsK1E33ikhPwF3XmrNWg2B8B7ah5djzk5PYqinMoPBgotgrBMGruL8mSBSU46y",
}
OWNER_ONLY_SIGNATURE = (
    "56wWuZNPQnYGSizLfyEtWxCzBMM7j24oByvDe3dAomiwiXLGXPwAR6fnAUJZmsosBUXBmidrnFZ3y1CzmPLUTyTj"
)

PURE_FUNCTIONS = {
    "_utc_now",
    "_aware",
    "_timestamp",
    "_extract_signature",
    "_account_keys",
    "_token_balance_owners",
    "_matched_wallets",
    "_raw_amount",
    "_wallet_token_deltas",
    "_native_delta",
    "_closed_wallet_token_account_reclaim_lamports",
    "_sol_equivalent_delta",
    "parse_raw_copyability_signal",
}
PURE_CLASSES = {
    "CanonicalParserGen4CopyabilityError",
    "ParsedRawSignal",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_parser_namespace() -> dict[str, Any]:
    source = SERVICE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SERVICE_PATH))
    selected = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in PURE_FUNCTIONS:
            selected.append(node)
        elif isinstance(node, ast.ClassDef) and node.name in PURE_CLASSES:
            selected.append(node)
    found = {
        node.name
        for node in selected
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    expected = PURE_FUNCTIONS | PURE_CLASSES
    if found != expected:
        raise RuntimeError(f"Pure parser symbols mismatch: missing={sorted(expected - found)}")

    namespace: dict[str, Any] = {
        "Any": Any,
        "Iterable": Iterable,
        "dataclass": dataclass,
        "datetime": datetime,
        "timezone": timezone,
        "GEN4_COPYABILITY_RAW_PARSER_VERSION": "canonical-parser-gen4-raw-balance-delta/4",
        "GEN4_MANDATORY_EXCLUDED_PRICE_MINTS": EXCLUDED_MINTS,
        "SOL_MINT": SOL_MINT,
        "MIN_SOL_SPENT_FOR_ROI": 0.001,
        "LAMPORTS_PER_SOL": 1_000_000_000,
    }
    module = ast.Module(body=selected, type_ignores=[])
    ast.fix_missing_locations(module)
    exec(compile(module, str(SERVICE_PATH), "exec"), namespace)
    return namespace


def receipts(report: dict[str, Any], campaign_id: str) -> list[dict[str, Any]]:
    return [
        item
        for item in report["database"]["receipts"]
        if item["campaign_id"] == campaign_id
    ]


def expect_error(
    parse: Any,
    error_type: type[Exception],
    payload: dict[str, Any],
    wallets: list[str],
    code: str,
) -> Exception:
    try:
        parse(payload, frozen_wallets=wallets)
    except error_type as error:
        if getattr(error, "code", None) != code:
            raise AssertionError(f"Expected {code}, got {getattr(error, 'code', None)}") from error
        return error
    raise AssertionError(f"Expected parser error {code}")


def valid_buy_payload(*, multiple: bool = False) -> dict[str, Any]:
    first_mint = "61BtvdXLEWT52BBsGh6qrsuwoGUcE3cuuS3EC8Mjpump"
    account_keys = [CANDIDATE_WALLET, "TokenAccount1111111111111111111111111111"]
    pre = [
        {
            "accountIndex": 1,
            "owner": CANDIDATE_WALLET,
            "mint": first_mint,
            "uiTokenAmount": {"amount": "0", "decimals": 6},
        }
    ]
    post = [
        {
            "accountIndex": 1,
            "owner": CANDIDATE_WALLET,
            "mint": first_mint,
            "uiTokenAmount": {"amount": "1000000", "decimals": 6},
        }
    ]
    if multiple:
        account_keys.append("TokenAccount2222222222222222222222222222")
        second_mint = "GnzqboS9akb8VDMdazHRxQHtPsBgQAWUnQTBaZ5CxkyD"
        pre.append(
            {
                "accountIndex": 2,
                "owner": CANDIDATE_WALLET,
                "mint": second_mint,
                "uiTokenAmount": {"amount": "0", "decimals": 6},
            }
        )
        post.append(
            {
                "accountIndex": 2,
                "owner": CANDIDATE_WALLET,
                "mint": second_mint,
                "uiTokenAmount": {"amount": "1", "decimals": 6},
            }
        )
    return {
        "signature": "m62-valid-buy",
        "slot": 1,
        "blockTime": 1_786_186_491,
        "transaction": {
            "signatures": ["m62-valid-buy"],
            "message": {"accountKeys": account_keys},
        },
        "meta": {
            "err": None,
            "fee": 100_000,
            "preBalances": [1_000_000_000, 2_039_280, 2_039_280],
            "postBalances": [989_900_000, 2_039_280, 2_039_280],
            "preTokenBalances": pre,
            "postTokenBalances": post,
            "loadedAddresses": {"writable": [], "readonly": []},
        },
    }


def main() -> int:
    namespace = load_parser_namespace()
    parse = namespace["parse_raw_copyability_signal"]
    error_type = namespace["CanonicalParserGen4CopyabilityError"]
    report = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    assert report["audit"] == "PASS"
    assert report["safety"]["helius_requests"] == 0
    assert report["safety"]["database_writes"] == 0
    assert report["safety"]["backend_posts"] == 0
    assert report["database"]["transaction_read_only"] == "on"

    candidate = receipts(report, CANDIDATE_CAMPAIGN_ID)
    primary = receipts(report, PRIMARY_CAMPAIGN_ID)
    assert len(candidate) == 3
    assert len(primary) == 6

    native_count = 0
    owner_only_count = 0
    for receipt in candidate:
        if receipt["signature"] in NATIVE_ONLY_SIGNATURES:
            error = expect_error(
                parse,
                error_type,
                receipt["raw_payload"],
                receipt["frozen_wallets"],
                "GEN4_COPYABILITY_RAW_NO_SPECULATIVE_TOKEN_DELTA",
            )
            assert error.evidence["candidate_count"] == 0
            assert error.evidence["wallet_deltas"][0]["native_delta_lamports"] > 0
            native_count += 1
        elif receipt["signature"] == OWNER_ONLY_SIGNATURE:
            error = expect_error(
                parse,
                error_type,
                receipt["raw_payload"],
                receipt["frozen_wallets"],
                "GEN4_COPYABILITY_RAW_WALLET_NOT_TRANSACTION_ACCOUNT",
            )
            assert error.evidence["classification"] == "OWNER_ONLY_TOKEN_DELTA"
            assert error.evidence["token_delta_raw"] == 21_650_385_222
            owner_only_count += 1
        else:
            raise AssertionError(f"Unexpected candidate receipt {receipt['signature']}")
    assert native_count == 2
    assert owner_only_count == 1

    for receipt in primary:
        error = expect_error(
            parse,
            error_type,
            receipt["raw_payload"],
            receipt["frozen_wallets"],
            "GEN4_COPYABILITY_RAW_NO_SPECULATIVE_TOKEN_DELTA",
        )
        assert error.evidence["candidate_count"] == 0

    valid = parse(valid_buy_payload(), frozen_wallets=[CANDIDATE_WALLET])
    assert valid.side == "BUY"
    assert valid.sol_equivalent_delta_lamports == -10_100_000
    assert valid.evidence["raw_parser_version"] == "canonical-parser-gen4-raw-balance-delta/4"

    ambiguous = expect_error(
        parse,
        error_type,
        valid_buy_payload(multiple=True),
        [CANDIDATE_WALLET],
        "GEN4_COPYABILITY_RAW_AMBIGUOUS_TOKEN_DELTAS",
    )
    assert ambiguous.evidence["candidate_count"] == 2

    source = SERVICE_PATH.read_text(encoding="utf-8")
    assert 'GEN4_COPYABILITY_POLICY_VERSION = "canonical-parser-gen4-realtime-copyability/1"' in source
    assert "receive_gen4_copyability_webhook" in source
    assert "get_wallet_transactions" not in source
    print("=== M62 RAW SWAP PARSER HARDENING VERIFIER ===")
    print(f"SERVICE_SHA256={sha256(SERVICE_PATH)}")
    print(f"FIXTURE_SHA256={sha256(FIXTURE_PATH)}")
    print("CANDIDATE_NATIVE_ONLY_CLASSIFIED=2")
    print("CANDIDATE_OWNER_ONLY_DISTRIBUTION_CLASSIFIED=1")
    print("PRIMARY_NON_SWAP_RECEIPTS_CLASSIFIED=6")
    print("VALID_SOL_PAIRED_BUY=PASS")
    print("MULTIPLE_TOKEN_DELTAS_FAIL_CLOSED=PASS")
    print("POLICY_VERSION_UNCHANGED=PASS")
    print("HELIUS_REQUESTS=0")
    print("DATABASE_WRITES=0")
    print("BACKEND_POSTS=0")
    print("VERIFIER=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
