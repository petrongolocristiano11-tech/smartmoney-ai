from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.services.blockchain_parser_gen4_copyability_service import (
    GEN4_COPYABILITY_POLICY_VERSION,
    GEN4_COPYABILITY_RAW_PARSER_VERSION,
    CanonicalParserGen4CopyabilityError,
    parse_raw_copyability_signal,
)


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "m62_raw_parser_audit.json"
CANDIDATE_CAMPAIGN_ID = "e5eaf7b6-a4e7-4182-96a2-d5f6af668e74"
PRIMARY_CAMPAIGN_ID = "89026d62-1e4e-452b-b0bf-8a5e3dd373e4"
CANDIDATE_WALLET = "Bs34SxJUSjUntbsWDEZrFKEcCdJfSuF9KiwtFdJ1Tfsd"
SOL_MINT = "So11111111111111111111111111111111111111112"

NATIVE_ONLY_SIGNATURES = {
    "4RTrNZ8cCqhiJf7uDrqC1sAHwzaPUJxTjT93zK78qYszxQPy2ycLzhbPxLS4oBaiagiVYikppDV6ty2eCur3Bnyn",
    "3bjazFxQnHDuP4sMKeoWLWHHeigsK1E33ikhPwF3XmrNWg2B8B7ah5djzk5PYqinMoPBgotgrBMGruL8mSBSU46y",
}
OWNER_ONLY_DISTRIBUTION_SIGNATURE = (
    "56wWuZNPQnYGSizLfyEtWxCzBMM7j24oByvDe3dAomiwiXLGXPwAR6fnAUJZmsosBUXBmidrnFZ3y1CzmPLUTyTj"
)


def _audit_report() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _campaign_receipts(campaign_id: str) -> list[dict]:
    return [
        item
        for item in _audit_report()["database"]["receipts"]
        if item["campaign_id"] == campaign_id
    ]


def _valid_buy_payload(*, second_token: str | None = None) -> dict:
    wallet = CANDIDATE_WALLET
    token = "61BtvdXLEWT52BBsGh6qrsuwoGUcE3cuuS3EC8Mjpump"
    pre_token_balances = [
        {
            "accountIndex": 1,
            "owner": wallet,
            "mint": token,
            "uiTokenAmount": {"amount": "0", "decimals": 6},
        }
    ]
    post_token_balances = [
        {
            "accountIndex": 1,
            "owner": wallet,
            "mint": token,
            "uiTokenAmount": {"amount": "1000000", "decimals": 6},
        }
    ]
    account_keys = [wallet, "TokenAccount1111111111111111111111111111"]
    if second_token:
        account_keys.append("TokenAccount2222222222222222222222222222")
        pre_token_balances.append(
            {
                "accountIndex": 2,
                "owner": wallet,
                "mint": second_token,
                "uiTokenAmount": {"amount": "0", "decimals": 6},
            }
        )
        post_token_balances.append(
            {
                "accountIndex": 2,
                "owner": wallet,
                "mint": second_token,
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
            "preTokenBalances": pre_token_balances,
            "postTokenBalances": post_token_balances,
            "loadedAddresses": {"writable": [], "readonly": []},
        },
    }


def test_m62_audit_fixture_is_read_only_and_complete():
    report = _audit_report()

    assert report["audit"] == "PASS"
    assert report["safety"] == {
        "helius_requests": 0,
        "database_writes": 0,
        "backend_posts": 0,
        "railway_mutations": 0,
        "secret_values_written": False,
        "paper_orders": 0,
        "live_orders": 0,
        "signed_transactions": 0,
        "submitted_transactions": 0,
    }
    assert report["database"]["transaction_read_only"] == "on"
    assert report["database"]["target_candidate_signature_count"] == 3
    assert len(_campaign_receipts(CANDIDATE_CAMPAIGN_ID)) == 3


@pytest.mark.parametrize("signature", sorted(NATIVE_ONLY_SIGNATURES))
def test_candidate_native_only_receipts_are_not_misclassified_as_swaps(signature: str):
    receipt = next(
        item
        for item in _campaign_receipts(CANDIDATE_CAMPAIGN_ID)
        if item["signature"] == signature
    )

    with pytest.raises(CanonicalParserGen4CopyabilityError) as captured:
        parse_raw_copyability_signal(
            receipt["raw_payload"],
            frozen_wallets=receipt["frozen_wallets"],
        )

    assert captured.value.code == "GEN4_COPYABILITY_RAW_NO_SPECULATIVE_TOKEN_DELTA"
    assert captured.value.evidence["raw_parser_version"] == GEN4_COPYABILITY_RAW_PARSER_VERSION
    assert captured.value.evidence["classification"] == "NO_SPECULATIVE_TOKEN_DELTA"
    assert captured.value.evidence["candidate_count"] == 0
    assert captured.value.evidence["wallet_deltas"][0]["native_delta_lamports"] > 0


def test_candidate_batch_distribution_requires_wallet_transaction_authority():
    receipt = next(
        item
        for item in _campaign_receipts(CANDIDATE_CAMPAIGN_ID)
        if item["signature"] == OWNER_ONLY_DISTRIBUTION_SIGNATURE
    )

    with pytest.raises(CanonicalParserGen4CopyabilityError) as captured:
        parse_raw_copyability_signal(
            receipt["raw_payload"],
            frozen_wallets=receipt["frozen_wallets"],
        )

    assert captured.value.code == "GEN4_COPYABILITY_RAW_WALLET_NOT_TRANSACTION_ACCOUNT"
    assert captured.value.evidence == {
        "raw_parser_version": GEN4_COPYABILITY_RAW_PARSER_VERSION,
        "classification": "OWNER_ONLY_TOKEN_DELTA",
        "matched_wallets": [CANDIDATE_WALLET],
        "candidate_count": 1,
        "wallet_address": CANDIDATE_WALLET,
        "wallet_in_transaction_accounts": False,
        "token_mint": "GnzqboS9akb8VDMdazHRxQHtPsBgQAWUnQTBaZ5CxkyD",
        "token_delta_raw": 21_650_385_222,
        "side_from_token_delta": "BUY",
    }


def test_primary_native_only_receipts_receive_precise_non_swap_reason():
    receipts = _campaign_receipts(PRIMARY_CAMPAIGN_ID)
    assert len(receipts) == 6

    for receipt in receipts:
        with pytest.raises(CanonicalParserGen4CopyabilityError) as captured:
            parse_raw_copyability_signal(
                receipt["raw_payload"],
                frozen_wallets=receipt["frozen_wallets"],
            )
        assert captured.value.code == "GEN4_COPYABILITY_RAW_NO_SPECULATIVE_TOKEN_DELTA"
        assert captured.value.evidence["candidate_count"] == 0


def test_valid_sol_paired_buy_remains_accepted_and_versioned():
    signal = parse_raw_copyability_signal(
        _valid_buy_payload(),
        frozen_wallets=[CANDIDATE_WALLET],
    )

    assert signal.side == "BUY"
    assert signal.sol_equivalent_delta_lamports == -10_100_000
    assert signal.evidence["raw_parser_version"] == GEN4_COPYABILITY_RAW_PARSER_VERSION
    assert GEN4_COPYABILITY_POLICY_VERSION == "canonical-parser-gen4-realtime-copyability/1"


def test_multiple_speculative_deltas_remain_fail_closed_and_compatible():
    payload = _valid_buy_payload(
        second_token="GnzqboS9akb8VDMdazHRxQHtPsBgQAWUnQTBaZ5CxkyD"
    )

    with pytest.raises(CanonicalParserGen4CopyabilityError) as captured:
        parse_raw_copyability_signal(payload, frozen_wallets=[CANDIDATE_WALLET])

    assert captured.value.code == "GEN4_COPYABILITY_RAW_AMBIGUOUS_TOKEN_DELTAS"
    assert captured.value.evidence["classification"] == "MULTIPLE_SPECULATIVE_TOKEN_DELTAS"
    assert captured.value.evidence["candidate_count"] == 2
    assert len(captured.value.evidence["candidate_mints"]) == 2


def test_m62_fixture_contains_no_wsol_owned_by_candidate_distribution_wallet():
    receipt = next(
        item
        for item in _campaign_receipts(CANDIDATE_CAMPAIGN_ID)
        if item["signature"] == OWNER_ONLY_DISTRIBUTION_SIGNATURE
    )
    candidate_balances = [
        item
        for phase in ("preTokenBalances", "postTokenBalances")
        for item in receipt["raw_payload"]["meta"][phase]
        if item.get("owner") == CANDIDATE_WALLET
    ]

    assert candidate_balances
    assert {item["mint"] for item in candidate_balances} != {SOL_MINT}
    assert all(item["mint"] != SOL_MINT for item in candidate_balances)
