from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import pytest

from backend.app.api.live_platform import (
    get_dex_client,
    get_jupiter_client,
    get_rpc_client,
    get_rugcheck_client,
    get_signer,
    router,
)
from backend.app.core.config import settings
from backend.app.database.base import Base
from backend.app.database.session import get_db
from backend.app.services.jupiter_swap_client import JupiterOrderResult
from backend.app.services.token_safety_service import TokenMarketMetrics


ACCESS_KEY = "k" * 40
TOKEN = "T" * 32


class FakeRpc:
    def call(self, method, params=None):
        if method == "getAccountInfo":
            return {
                "value": {
                    "data": {
                        "parsed": {
                            "info": {
                                "decimals": 6,
                                "mintAuthority": None,
                                "freezeAuthority": None,
                            }
                        }
                    }
                }
            }
        if method == "getTokenSupply":
            return {"value": {"uiAmountString": "1000000"}}
        if method == "getTokenLargestAccounts":
            return {"value": [{"uiAmountString": "10000"}]}
        raise AssertionError(method)

    def get_balance_sol(self, address):
        return 10.0


class FakeJupiter:
    def get_order(self, **kwargs):
        return JupiterOrderResult(
            raw={},
            request_id="api-safety",
            transaction=None,
            in_amount=kwargs["amount_raw"],
            out_amount=10,
            slippage_bps=20,
            router="iris",
            price_impact_percent=0.1,
            last_valid_block_height=None,
        )


class FakeDex:
    def get_token_metrics(self, token_mint):
        return TokenMarketMetrics(
            liquidity_usd=100_000,
            market_cap_usd=1_000_000,
            volume_24h_usd=200_000,
            pair_count=1,
            raw=[],
        )


class FakeRugCheck:
    def get_report(self, token_mint):
        return None


class FakeSigner:
    wallet_address = "W" * 32


@pytest.fixture()
def api_client(monkeypatch):
    monkeypatch.setattr(settings, "LIVE_TRADING_API_KEY", ACCESS_KEY)
    monkeypatch.setattr(settings, "JUPITER_API_KEY", "jupiter")
    monkeypatch.setattr(settings, "LIVE_TRADING_WALLET_ADDRESS", "")
    monkeypatch.setattr(settings, "LIVE_TRADING_PRIVATE_KEY", "")

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()

    app = FastAPI()
    app.include_router(router)

    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_rpc_client] = lambda: FakeRpc()
    app.dependency_overrides[get_jupiter_client] = lambda: FakeJupiter()
    app.dependency_overrides[get_dex_client] = lambda: FakeDex()
    app.dependency_overrides[get_rugcheck_client] = lambda: FakeRugCheck()
    app.dependency_overrides[get_signer] = lambda: FakeSigner()

    with TestClient(app) as client:
        yield client

    session.close()
    engine.dispose()


def headers():
    return {"X-Live-Trading-Key": ACCESS_KEY}


def test_platform_api_requires_internal_key(api_client):
    response = api_client.get("/live-trading/platform/config")
    assert response.status_code == 401


def test_platform_config_analytics_and_ranking_endpoints(api_client):
    config = api_client.patch(
        "/live-trading/platform/config",
        headers=headers(),
        json={
            "analytics_starting_equity_sol": 2,
            "max_source_wallets": 50,
            "min_wallet_smart_score": 55,
            "token_safety_enabled": True,
        },
    )
    assert config.status_code == 200
    assert config.json()["max_source_wallets"] == 50

    analytics = api_client.get(
        "/live-trading/platform/analytics",
        headers=headers(),
        params={"days": 7, "mode": "DRY_RUN", "generation": 1},
    )
    assert analytics.status_code == 200
    assert analytics.json()["summary"]["starting_equity_sol"] == 2

    ranking = api_client.post(
        "/live-trading/platform/wallet-ranking/refresh",
        headers=headers(),
    )
    assert ranking.status_code == 200
    assert ranking.json()["count"] == 0


def test_platform_token_safety_and_readiness_endpoints(api_client):
    safety = api_client.post(
        f"/live-trading/platform/token-safety/{TOKEN}/refresh",
        headers=headers(),
    )
    assert safety.status_code == 200
    assert safety.json()["honeypot"] is False
    assert safety.json()["liquidity_usd"] == 100_000

    listing = api_client.get(
        "/live-trading/platform/token-safety",
        headers=headers(),
    )
    assert listing.status_code == 200
    assert listing.json()["count"] == 1

    readiness = api_client.get(
        "/live-trading/platform/readiness",
        headers=headers(),
    )
    assert readiness.status_code == 200
    assert readiness.json()["ready"] is False
    assert readiness.json()["armed"] is False
