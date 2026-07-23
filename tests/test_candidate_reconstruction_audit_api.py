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
from backend.app.models.discovered_wallet import (
    DiscoveredWallet,
)
from backend.app.models.trade import Trade


WALLET = "Q" * 32
TOKEN = "Y" * 32
NOW = datetime.now(timezone.utc)


@pytest.fixture()
def api_client():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={
            "check_same_thread": False
        },
        poolclass=StaticPool,
    )

    Base.metadata.create_all(engine)

    db = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )()

    db.add(
        DiscoveredWallet(
            wallet_address=WALLET,
            smart_score=70,
            activity_classification="POCO_ATTIVO",
            quality_classification="OSSERVAZIONE",
        )
    )

    db.add_all(
        [
            Trade(
                signature="audit-api-buy",
                wallet_address=WALLET,
                side="BUY",
                source="TEST",
                token_mint=TOKEN,
                token_amount=100,
                sol_amount=0.05,
                success=True,
                block_time=(
                    NOW - timedelta(hours=2)
                ),
            ),
            Trade(
                signature="audit-api-sell",
                wallet_address=WALLET,
                side="SELL",
                source="TEST",
                token_mint=TOKEN,
                token_amount=100,
                sol_amount=0.07,
                success=True,
                block_time=(
                    NOW - timedelta(hours=1)
                ),
            ),
        ]
    )
    db.commit()

    app = FastAPI()
    app.include_router(router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = (
        override_db
    )

    with TestClient(app) as client:
        yield client

    db.close()
    engine.dispose()


def test_audit_api_and_latest(api_client):
    response = api_client.post(
        "/discovered-wallets/promotion/audit",
        json={
            "wallet_address": WALLET,
            "lookback_days": 14,
            "warmup_days": 14,
            "baseline_starting_capital_sol": 1,
            "baseline_max_open_positions": 5,
        },
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["status"] == "COMPLETED"
    assert len(payload["scenario_results"]) == 9
    assert (
        payload["safety"]["live_enabled"]
        is False
    )

    latest = api_client.get(
        f"/discovered-wallets/promotion/audit/"
        f"{WALLET}/latest"
    )

    assert latest.status_code == 200
    assert (
        latest.json()["run_id"]
        == payload["run_id"]
    )
