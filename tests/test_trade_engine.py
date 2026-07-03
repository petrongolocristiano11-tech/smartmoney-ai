from backend.app.services.trade_engine import (
    identify_swap_side,
    extract_trade_amounts,
)


def test_identify_swap_side_buy():
    wallet = "WALLET"
    swap = {
        "fee_payer": wallet,
        "token_transfers": [
            {
                "mint": "So11111111111111111111111111111111111111112",
                "tokenAmount": 0.01,
                "fromUserAccount": wallet,
                "toUserAccount": "POOL",
            },
            {
                "mint": "TOKEN",
                "tokenAmount": 1000,
                "fromUserAccount": "POOL",
                "toUserAccount": wallet,
            },
        ],
        "native_transfers": [],
    }

    assert identify_swap_side(swap) == "BUY"


def test_identify_swap_side_sell():
    wallet = "WALLET"
    swap = {
        "fee_payer": wallet,
        "token_transfers": [
            {
                "mint": "TOKEN",
                "tokenAmount": 1000,
                "fromUserAccount": wallet,
                "toUserAccount": "POOL",
            },
            {
                "mint": "So11111111111111111111111111111111111111112",
                "tokenAmount": 0.02,
                "fromUserAccount": "POOL",
                "toUserAccount": wallet,
            },
        ],
        "native_transfers": [],
    }

    assert identify_swap_side(swap) == "SELL"


def test_extract_trade_amounts_buy():
    wallet = "WALLET"
    swap = {
        "fee_payer": wallet,
        "token_transfers": [
            {
                "mint": "So11111111111111111111111111111111111111112",
                "tokenAmount": 0.01,
                "fromUserAccount": wallet,
                "toUserAccount": "POOL",
            },
            {
                "mint": "TOKEN",
                "tokenAmount": 1000,
                "fromUserAccount": "POOL",
                "toUserAccount": wallet,
            },
        ],
        "native_transfers": [],
    }

    amounts = extract_trade_amounts(swap)

    assert amounts["token_mint"] == "TOKEN"
    assert amounts["token_amount"] == 1000
    assert amounts["sol_amount"] == 0.01 