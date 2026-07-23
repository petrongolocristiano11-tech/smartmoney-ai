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


NOW = datetime.now(timezone.utc)
ACTIVE_WALLET = "A" * 32
INACTIVE_WALLET = "I" * 32


@pytest.fixture()
def api_client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()

    session.add_all(
        [
            DiscoveredWallet(
                wallet_address=ACTIVE_WALLET,
                discovered_from_token="T" * 32,
                smart_score=84,
            ),
            DiscoveredWallet(
                wallet_address=INACTIVE_WALLET,
                discovered_from_token="T" * 32,
                smart_score=96,
            ),
        ]
    )

    active_trades = [
        ("BUY", NOW - timedelta(hours=2), 0.4),
        ("SELL", NOW - timedelta(hours=8), 0.6),
        ("BUY", NOW - timedelta(days=2), 0.3),
        ("SELL", NOW - timedelta(days=4), 0.5),
    ]
    for index, (side, block_time, sol_amount) in enumerate(active_trades):
        session.add(
            Trade(
                signature=f"active-{index}",
                wallet_address=ACTIVE_WALLET,
                side=side,
                source="TEST",
                token_mint=("M" if index < 2 else "N") * 32,
                token_amount=100,
                sol_amount=sol_amount,
                success=True,
                block_time=block_time,
            )
        )

    session.add(
        Trade(
            signature="inactive-0",
            wallet_address=INACTIVE_WALLET,
            side="BUY",
            source="TEST",
            token_mint="M" * 32,
            token_amount=100,
            sol_amount=1,
            success=True,
            block_time=NOW - timedelta(days=10),
        )
    )
    session.commit()

    app = FastAPI()
    app.include_router(router)

    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db

    with TestClient(app) as client:
        yield client

    session.close()
    engine.dispose()


def test_activity_refresh_uses_database_only_and_updates_eligibility(api_client):
    response = api_client.post(
        "/discovered-wallets/activity/refresh",
        params={"limit": 250},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "COMPLETED"
    assert payload["wallets_refreshed"] == 2
    assert payload["helius_requests"] == 0

    listing = api_client.get(
        "/discovered-wallets",
        params={"sort_by": "ranking_score"},
    )
    assert listing.status_code == 200
    wallets = listing.json()

    assert wallets[0]["wallet_address"] == ACTIVE_WALLET
    assert wallets[0]["activity_classification"] == "ATTIVO"
    assert wallets[0]["eligible"] is False
    assert "PROMOTION_GATE_NOT_PASSED" in wallets[0]["eligibility_reasons"]
    assert wallets[0]["swaps_24h"] == 2
    assert wallets[0]["buys_7d"] == 2
    assert wallets[0]["sells_7d"] == 2

    inactive = next(
        wallet for wallet in wallets if wallet["wallet_address"] == INACTIVE_WALLET
    )
    assert inactive["activity_classification"] == "INATTIVO"
    assert inactive["activity_eligible"] is False
    assert inactive["eligible"] is False
    assert "INACTIVE_WALLET" in inactive["eligibility_reasons"]


def test_activity_and_eligible_filters(api_client):
    refresh = api_client.post("/discovered-wallets/activity/refresh")
    assert refresh.status_code == 200

    active = api_client.get(
        "/discovered-wallets",
        params={"activity": "ATTIVO", "eligible_only": False},
    )
    assert active.status_code == 200
    assert [item["wallet_address"] for item in active.json()] == [ACTIVE_WALLET]

    inactive = api_client.get(
        "/discovered-wallets",
        params={"activity": "INATTIVO"},
    )
    assert inactive.status_code == 200
    assert [item["wallet_address"] for item in inactive.json()] == [INACTIVE_WALLET]
