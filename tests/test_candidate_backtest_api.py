from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api.discovered_wallets import router
from backend.app.database.base import Base
from backend.app.database.session import get_db
from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.models.trade import Trade


WALLET = "B" * 32
TOKEN = "T" * 32
NOW = datetime.now(timezone.utc)


@pytest.fixture()
def api_client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    db.add(
        DiscoveredWallet(
            wallet_address=WALLET,
            smart_score=85,
            activity_classification="ATTIVO",
            activity_eligible=True,
            quality_classification="COPIABILE",
            quality_eligible=True,
        )
    )
    db.add_all(
        [
            Trade(
                signature="api-buy",
                wallet_address=WALLET,
                side="BUY",
                source="TEST",
                token_mint=TOKEN,
                token_amount=100,
                sol_amount=0.05,
                success=True,
                block_time=NOW - timedelta(hours=2),
            ),
            Trade(
                signature="api-sell",
                wallet_address=WALLET,
                side="SELL",
                source="TEST",
                token_mint=TOKEN,
                token_amount=100,
                sol_amount=0.07,
                success=True,
                block_time=NOW - timedelta(hours=1),
            ),
        ]
    )
    db.commit()

    app = FastAPI()
    app.include_router(router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client
    db.close()
    engine.dispose()


def test_backtest_api_persists_observation_without_jupiter(api_client):
    response = api_client.post(
        "/discovered-wallets/promotion/backtest",
        json={
            "wallet_address": WALLET,
            "check_jupiter": False,
            "lookback_days": 7,
            "starting_capital_sol": 1,
            "fixed_buy_size_sol": 0.05,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["decision"] == "OSSERVAZIONE"
    assert payload["safety"]["live_enabled"] is False
    assert payload["safety"]["generation_created"] is False

    latest = api_client.get(f"/discovered-wallets/promotion/{WALLET}/latest")
    assert latest.status_code == 200
    assert latest.json()["run_id"] == payload["run_id"]

    listing = api_client.get(
        "/discovered-wallets", params={"promotion": "OSSERVAZIONE"}
    )
    assert listing.status_code == 200
    assert [row["wallet_address"] for row in listing.json()] == [WALLET]


def test_backtest_api_returns_404_for_unknown_wallet(api_client):
    response = api_client.post(
        "/discovered-wallets/promotion/backtest",
        json={"wallet_address": "Z" * 32, "check_jupiter": False},
    )
    assert response.status_code == 404
