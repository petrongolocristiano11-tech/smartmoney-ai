import pytest
from pydantic import ValidationError

from backend.app.core.config import (
    Settings,
)


AUTOMATION_KEY = "a" * 32
LIVE_API_KEY = "l" * 32
WALLET_ADDRESS = "W" * 32


def build_production_settings(
    **overrides,
):
    values = {
        "DATABASE_URL": (
            "postgresql+psycopg://"
            "postgres:postgres@localhost:5432/"
            "smartmoney_test"
        ),
        "SOLANA_RPC_URL": (
            "https://api.mainnet-beta.solana.com"
        ),
        "HELIUS_API_KEY": (
            "test-helius-api-key"
        ),
        "AUTOMATION_API_KEY": (
            AUTOMATION_KEY
        ),
        "ENVIRONMENT": "production",
        "CORS_ORIGINS": (
            "https://smartmoney.example.com"
        ),
        "CORS_ALLOW_CREDENTIALS": True,
    }

    values.update(
        overrides
    )

    return Settings(
        _env_file=None,
        **values,
    )


def test_production_dry_run_allows_api_key_without_wallet():
    settings = (
        build_production_settings(
            LIVE_TRADING_API_KEY=(
                LIVE_API_KEY
            ),
            JUPITER_API_KEY=(
                "test-jupiter-api-key"
            ),
            LIVE_TRADING_WALLET_ADDRESS="",
            LIVE_TRADING_PRIVATE_KEY="",
        )
    )

    assert (
        settings.LIVE_TRADING_API_KEY
        == LIVE_API_KEY
    )

    assert (
        settings
        .is_live_trading_configured
        is False
    )


def test_production_rejects_partial_live_wallet():
    with pytest.raises(
        ValidationError
    ):
        build_production_settings(
            LIVE_TRADING_API_KEY=(
                LIVE_API_KEY
            ),
            JUPITER_API_KEY=(
                "test-jupiter-api-key"
            ),
            LIVE_TRADING_WALLET_ADDRESS=(
                WALLET_ADDRESS
            ),
            LIVE_TRADING_PRIVATE_KEY="",
        )


def test_production_accepts_complete_live_configuration():
    settings = (
        build_production_settings(
            LIVE_TRADING_API_KEY=(
                LIVE_API_KEY
            ),
            JUPITER_API_KEY=(
                "test-jupiter-api-key"
            ),
            LIVE_TRADING_WALLET_ADDRESS=(
                WALLET_ADDRESS
            ),
            LIVE_TRADING_PRIVATE_KEY=(
                "test-private-key"
            ),
        )
    )

    assert (
        settings
        .is_live_trading_configured
        is True
    ) 