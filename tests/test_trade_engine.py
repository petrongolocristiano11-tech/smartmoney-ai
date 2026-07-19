from backend.app.core.constants import (
    SOL_MINT,
)
from backend.app.services.trade_engine import (
    build_trade,
    extract_trade_amounts,
    identify_swap_side,
    normalize_swap,
)


WALLET = "WALLET"
OTHER = "OTHER"
POOL = "POOL"
TOKEN = "TOKEN"


def test_identify_swap_side_buy_with_wsol():
    swap = {
        "fee_payer": WALLET,
        "token_transfers": [
            {
                "mint": SOL_MINT,
                "tokenAmount": 0.01,
                "fromUserAccount": WALLET,
                "toUserAccount": POOL,
            },
            {
                "mint": TOKEN,
                "tokenAmount": 1000,
                "fromUserAccount": POOL,
                "toUserAccount": WALLET,
            },
        ],
        "native_transfers": [],
        "account_data": [],
        "events": {},
        "transaction_error": None,
        "type": "SWAP",
    }

    assert identify_swap_side(swap) == "BUY"


def test_identify_swap_side_sell_with_wsol():
    swap = {
        "fee_payer": WALLET,
        "token_transfers": [
            {
                "mint": TOKEN,
                "tokenAmount": 1000,
                "fromUserAccount": WALLET,
                "toUserAccount": POOL,
            },
            {
                "mint": SOL_MINT,
                "tokenAmount": 0.02,
                "fromUserAccount": POOL,
                "toUserAccount": WALLET,
            },
        ],
        "native_transfers": [],
        "account_data": [],
        "events": {},
        "transaction_error": None,
        "type": "SWAP",
    }

    assert identify_swap_side(swap) == "SELL"


def test_extract_trade_amounts_buy_with_wsol():
    swap = {
        "fee_payer": WALLET,
        "token_transfers": [
            {
                "mint": SOL_MINT,
                "tokenAmount": 0.01,
                "fromUserAccount": WALLET,
                "toUserAccount": POOL,
            },
            {
                "mint": TOKEN,
                "tokenAmount": 1000,
                "fromUserAccount": POOL,
                "toUserAccount": WALLET,
            },
        ],
        "native_transfers": [],
        "account_data": [],
        "events": {},
        "transaction_error": None,
        "type": "SWAP",
    }

    amounts = extract_trade_amounts(
        swap
    )

    assert amounts["token_mint"] == TOKEN
    assert amounts["token_amount"] == 1000
    assert amounts["sol_amount"] == 0.01


def test_native_sol_buy_uses_expected_wallet_not_fee_payer():
    normalized = normalize_swap(
        {
            "type": "UNKNOWN",
            "signature": "native-buy",
            "feePayer": OTHER,
            "transactionError": None,
            "nativeTransfers": [
                {
                    "fromUserAccount": WALLET,
                    "toUserAccount": POOL,
                    "amount": 250_000_000,
                }
            ],
            "tokenTransfers": [
                {
                    "mint": TOKEN,
                    "tokenAmount": 1500,
                    "fromUserAccount": POOL,
                    "toUserAccount": WALLET,
                }
            ],
        },
        wallet_address=WALLET,
    )

    trade = build_trade(
        normalized
    )

    assert trade["side"] == "BUY"
    assert trade["token_mint"] == TOKEN
    assert trade["token_amount"] == 1500
    assert trade["sol_amount"] == 0.25
    assert trade["fee_payer"] == OTHER
    assert trade["wallet_address"] == WALLET
    assert trade["parser"] == "TRANSFER_FLOW"


def test_native_sol_sell_uses_expected_wallet_not_fee_payer():
    normalized = normalize_swap(
        {
            "type": "UNKNOWN",
            "signature": "native-sell",
            "feePayer": OTHER,
            "transactionError": None,
            "nativeTransfers": [
                {
                    "fromUserAccount": POOL,
                    "toUserAccount": WALLET,
                    "amount": 320_000_000,
                }
            ],
            "tokenTransfers": [
                {
                    "mint": TOKEN,
                    "tokenAmount": 700,
                    "fromUserAccount": WALLET,
                    "toUserAccount": POOL,
                }
            ],
        },
        wallet_address=WALLET,
    )

    trade = build_trade(
        normalized
    )

    assert trade["side"] == "SELL"
    assert trade["token_mint"] == TOKEN
    assert trade["token_amount"] == 700
    assert trade["sol_amount"] == 0.32
    assert trade["parser"] == "TRANSFER_FLOW"


def test_event_swap_is_preferred_and_converts_raw_amounts():
    normalized = normalize_swap(
        {
            "type": "SWAP",
            "signature": "event-buy",
            "feePayer": OTHER,
            "transactionError": None,
            "nativeTransfers": [],
            "tokenTransfers": [],
            "events": {
                "swap": {
                    "nativeInput": {
                        "account": WALLET,
                        "amount": "125000000",
                    },
                    "nativeOutput": None,
                    "tokenInputs": [],
                    "tokenOutputs": [
                        {
                            "userAccount": WALLET,
                            "mint": TOKEN,
                            "rawTokenAmount": {
                                "tokenAmount": "250000000",
                                "decimals": 6,
                            },
                        }
                    ],
                }
            },
        },
        wallet_address=WALLET,
    )

    trade = build_trade(
        normalized
    )

    assert trade["side"] == "BUY"
    assert trade["token_mint"] == TOKEN
    assert trade["token_amount"] == 250
    assert trade["sol_amount"] == 0.125
    assert trade["parser"] == "EVENT_SWAP"


def test_account_data_is_fallback_for_swap_balance_changes():
    normalized = normalize_swap(
        {
            "type": "SWAP",
            "signature": "account-data-buy",
            "feePayer": OTHER,
            "transactionError": None,
            "nativeTransfers": [],
            "tokenTransfers": [],
            "accountData": [
                {
                    "account": WALLET,
                    "nativeBalanceChange": -210_000_000,
                    "tokenBalanceChanges": [],
                },
                {
                    "account": "TOKEN_ACCOUNT",
                    "nativeBalanceChange": 0,
                    "tokenBalanceChanges": [
                        {
                            "userAccount": WALLET,
                            "mint": TOKEN,
                            "rawTokenAmount": {
                                "tokenAmount": "420000000",
                                "decimals": 6,
                            },
                        }
                    ],
                },
            ],
        },
        wallet_address=WALLET,
    )

    trade = build_trade(
        normalized
    )

    assert trade["side"] == "BUY"
    assert trade["token_mint"] == TOKEN
    assert trade["token_amount"] == 420
    assert trade["sol_amount"] == 0.21


def test_plain_token_transfer_is_not_misclassified_as_buy():
    normalized = normalize_swap(
        {
            "type": "TRANSFER",
            "signature": "airdrop",
            "feePayer": WALLET,
            "transactionError": None,
            "nativeTransfers": [],
            "tokenTransfers": [
                {
                    "mint": TOKEN,
                    "tokenAmount": 10,
                    "fromUserAccount": OTHER,
                    "toUserAccount": WALLET,
                }
            ],
            "accountData": [
                {
                    "account": WALLET,
                    "nativeBalanceChange": -5000,
                    "tokenBalanceChanges": [],
                }
            ],
        },
        wallet_address=WALLET,
    )

    trade = build_trade(
        normalized
    )

    assert trade["side"] == "UNKNOWN"
    assert trade["token_mint"] is None
    assert trade["sol_amount"] is None


def test_failed_transaction_is_not_parsed():
    normalized = normalize_swap(
        {
            "type": "SWAP",
            "signature": "failed",
            "feePayer": WALLET,
            "transactionError": {
                "error": "failed"
            },
            "nativeTransfers": [
                {
                    "fromUserAccount": WALLET,
                    "toUserAccount": POOL,
                    "amount": 100_000_000,
                }
            ],
            "tokenTransfers": [
                {
                    "mint": TOKEN,
                    "tokenAmount": 100,
                    "fromUserAccount": POOL,
                    "toUserAccount": WALLET,
                }
            ],
        },
        wallet_address=WALLET,
    )

    assert identify_swap_side(
        normalized
    ) == "UNKNOWN"
