import httpx
import pytest

from backend.app.services.price_oracle import (
    JupiterPriceOracle,
    PriceOracleError,
    SOL_MINT,
)


TOKEN_MINT = (
    "Token1111111111111111111111111111111111111"
)


def make_oracle(handler):
    return JupiterPriceOracle(
        api_key="test-key",
        base_url=(
            "https://api.jup.ag/price/v3"
        ),
        timeout_seconds=5,
        cache_ttl_seconds=30,
        transport=httpx.MockTransport(
            handler
        ),
    )


def test_price_is_converted_from_usd_to_sol():
    def handler(
        request: httpx.Request,
    ):
        assert (
            request.headers[
                "x-api-key"
            ]
            == "test-key"
        )

        return httpx.Response(
            200,
            json={
                TOKEN_MINT: {
                    "usdPrice": 2.0,
                    "blockId": 123,
                    "decimals": 6,
                    "priceChange24h": 5.0,
                },
                SOL_MINT: {
                    "usdPrice": 100.0,
                    "blockId": 124,
                    "decimals": 9,
                    "priceChange24h": 1.0,
                },
            },
        )

    quote = (
        make_oracle(handler)
        .get_price(TOKEN_MINT)
    )

    assert (
        quote.usd_price
        == pytest.approx(2.0)
    )

    assert (
        quote.sol_usd_price
        == pytest.approx(100.0)
    )

    assert (
        quote.sol_price
        == pytest.approx(0.02)
    )

    assert quote.block_id == 123


def test_price_cache_avoids_duplicate_requests():
    calls = 0

    def handler(
        request: httpx.Request,
    ):
        nonlocal calls
        calls += 1

        return httpx.Response(
            200,
            json={
                TOKEN_MINT: {
                    "usdPrice": 2.0,
                },
                SOL_MINT: {
                    "usdPrice": 100.0,
                },
            },
        )

    oracle = make_oracle(handler)

    oracle.get_price(TOKEN_MINT)
    oracle.get_price(TOKEN_MINT)

    assert calls == 1


def test_force_refresh_bypasses_cache():
    calls = 0

    def handler(
        request: httpx.Request,
    ):
        nonlocal calls
        calls += 1

        return httpx.Response(
            200,
            json={
                TOKEN_MINT: {
                    "usdPrice": float(
                        calls
                    ),
                },
                SOL_MINT: {
                    "usdPrice": 100.0,
                },
            },
        )

    oracle = make_oracle(handler)

    first = oracle.get_price(
        TOKEN_MINT
    )

    second = oracle.get_price(
        TOKEN_MINT,
        force_refresh=True,
    )

    assert calls == 2

    assert (
        second.usd_price
        > first.usd_price
    )


def test_missing_token_price_is_rejected():
    def handler(
        request: httpx.Request,
    ):
        return httpx.Response(
            200,
            json={
                SOL_MINT: {
                    "usdPrice": 100.0,
                },
            },
        )

    oracle = make_oracle(handler)

    with pytest.raises(
        PriceOracleError
    ) as exception:
        oracle.get_price(
            TOKEN_MINT
        )

    assert (
        exception.value.code
        == "PRICE_NOT_AVAILABLE"
    )


def test_rate_limit_is_reported():
    def handler(
        request: httpx.Request,
    ):
        return httpx.Response(
            429,
            json={},
        )

    oracle = make_oracle(handler)

    with pytest.raises(
        PriceOracleError
    ) as exception:
        oracle.get_price(
            TOKEN_MINT
        )

    assert (
        exception.value.code
        == "ORACLE_RATE_LIMITED"
    ) 