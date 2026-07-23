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
COPYABLE = "C" * 32
SUSPICIOUS = "S" * 32
TOKEN_A = "A" * 32
TOKEN_B = "B" * 32


@pytest.fixture()
def api_client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)
    db = session_factory()
    db.add_all(
        [
            DiscoveredWallet(wallet_address=COPYABLE, smart_score=85),
            DiscoveredWallet(wallet_address=SUSPICIOUS, smart_score=90),
        ]
    )
    for index in range(6):
        db.add(
            Trade(
                signature=f"copyable-{index}",
                wallet_address=COPYABLE,
                side="BUY" if index % 2 == 0 else "SELL",
                source="TEST",
                token_mint=TOKEN_A if index < 4 else TOKEN_B,
                token_amount=100,
                sol_amount=0.05 + index * 0.01,
                success=True,
                block_time=NOW - timedelta(hours=index * 10),
            )
        )
    for index in range(20):
        db.add(
            Trade(
                signature=f"suspicious-{index}",
                wallet_address=SUSPICIOUS,
                side="BUY",
                source="TEST",
                token_mint=TOKEN_A,
                token_amount=1,
                sol_amount=0.0001,
                success=True,
                block_time=NOW - timedelta(hours=index * 2),
            )
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


def test_quality_refresh_is_database_only_and_updates_final_eligibility(api_client):
    response = api_client.post("/discovered-wallets/quality/refresh", params={"limit": 500})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "COMPLETED"
    assert payload["helius_requests"] == 0
    assert payload["copyable"] == 1
    assert payload["suspicious"] == 1

    listing = api_client.get("/discovered-wallets")
    rows = {item["wallet_address"]: item for item in listing.json()}
    assert rows[COPYABLE]["quality_classification"] == "COPIABILE"
    assert rows[COPYABLE]["eligible"] is False
    assert "PROMOTION_GATE_NOT_PASSED" in rows[COPYABLE]["eligibility_reasons"]
    assert rows[SUSPICIOUS]["quality_classification"] == "SOSPETTO"
    assert rows[SUSPICIOUS]["eligible"] is False


def test_quality_filter_returns_only_requested_class(api_client):
    refresh = api_client.post("/discovered-wallets/quality/refresh")
    assert refresh.status_code == 200

    response = api_client.get(
        "/discovered-wallets",
        params={"quality": "SOSPETTO", "sort_by": "quality_score"},
    )
    assert response.status_code == 200
    assert [item["wallet_address"] for item in response.json()] == [SUSPICIOUS]
