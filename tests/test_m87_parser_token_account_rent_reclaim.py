from __future__ import annotations

import pytest

from backend.app.services.blockchain_parser_gen4_copyability_service import (
    GEN4_COPYABILITY_RAW_PARSER_VERSION,
    CanonicalParserGen4CopyabilityError,
    parse_raw_copyability_signal,
)

WALLET = "6ni1gQaVtW38qBsGFfdbNURHyEkizAM7WXZbpcqw18x"
TOKEN = "szVXzMs29NDFhkqY86zsmLKhCKXmtzGAX6TZqjEpump"
TOKEN_ACCOUNT = "3dmyz45HDD7NgVVZFwckHTf5SqUBBSfBPQ5egooV7Tbh"
RENT_LAMPORTS = 2_039_280


def _sell_and_close_payload(*, token_pre_raw: int, gross_sale_lamports: int, fee: int = 5_832) -> dict:
    wallet_pre = 1_000_000_000
    # Native wallet receives the sale proceeds plus the closed account's rent,
    # while paying the transaction fee.
    wallet_native_delta = gross_sale_lamports + RENT_LAMPORTS - fee
    return {
        "signature": "m87-rent-reclaim-regression",
        "slot": 1,
        "blockTime": 1_786_990_407,
        "meta": {
            "err": None,
            "fee": fee,
            "preBalances": [wallet_pre, RENT_LAMPORTS],
            "postBalances": [wallet_pre + wallet_native_delta, 0],
            "preTokenBalances": [
                {
                    "accountIndex": 1,
                    "owner": WALLET,
                    "mint": TOKEN,
                    "uiTokenAmount": {"amount": str(token_pre_raw), "decimals": 6},
                }
            ],
            "postTokenBalances": [],
        },
        "transaction": {
            "signatures": ["m87-rent-reclaim-regression"],
            "message": {
                "accountKeys": [
                    {"pubkey": WALLET, "signer": True, "writable": True, "source": "transaction"},
                    {"pubkey": TOKEN_ACCOUNT, "signer": False, "writable": True, "source": "transaction"},
                ]
            },
        },
    }


def test_m87_parser_version_is_v4():
    assert GEN4_COPYABILITY_RAW_PARSER_VERSION == "canonical-parser-gen4-raw-balance-delta/4"


def test_m87_rejects_rent_reclaim_only_sell_with_one_raw_token_delta():
    payload = _sell_and_close_payload(token_pre_raw=1, gross_sale_lamports=0)
    with pytest.raises(CanonicalParserGen4CopyabilityError) as error:
        parse_raw_copyability_signal(payload, frozen_wallets=[WALLET])
    assert error.value.code == "GEN4_COPYABILITY_RAW_SELL_TOKEN_ACCOUNT_RENT_RECLAIM_ONLY"
    evidence = error.value.evidence
    assert evidence["token_account_rent_reclaim_lamports"] == RENT_LAMPORTS
    assert evidence["adjusted_sol_equivalent_delta_lamports"] == -5_832
    assert evidence["closed_token_accounts"][0]["account_index"] == 1


def test_m87_preserves_real_sell_and_close_but_removes_rent_from_proceeds():
    payload = _sell_and_close_payload(token_pre_raw=60_000_000_000, gross_sale_lamports=12_000_000)
    signal = parse_raw_copyability_signal(payload, frozen_wallets=[WALLET])
    assert signal.side == "SELL"
    # Returned SOL-equivalent delta remains fee-inclusive in the same convention
    # as the existing parser: downstream adds fee back to reconstruct gross proceeds.
    assert signal.sol_equivalent_delta_lamports == 12_000_000 - 5_832
    assert signal.evidence["token_account_rent_reclaim_lamports"] == RENT_LAMPORTS
    assert signal.sell_fraction == pytest.approx(1.0)
