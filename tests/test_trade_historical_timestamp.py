from datetime import UTC, datetime

from backend.app.services.trade_engine import build_trade_data


def test_build_trade_data_preserves_historical_timestamp():
    timestamp = 1784772000
    data = build_trade_data(
        "wallet-address",
        {
            "signature": "signature",
            "side": "BUY",
            "source": "JUPITER",
            "token_mint": "mint",
            "token_amount": 10,
            "sol_amount": 0.5,
            "fee": 5000,
            "timestamp": timestamp,
        },
    )

    assert data["block_time"] == datetime.fromtimestamp(timestamp, tz=UTC)
