from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api import discovered_wallets as api_module
from backend.app.database.base import Base
from backend.app.database.session import get_db
from backend.app.models.candidate_history_backfill import CandidateHistoryBackfillRun
from backend.app.models.discovered_wallet import DiscoveredWallet


WALLET = "Q" * 32
NOW = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)


@pytest.fixture()
def api_client(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    Base.metadata.create_all(engine)
    db.add(
        DiscoveredWallet(
            wallet_address=WALLET,
            smart_score=85,
            quality_classification="COPIABILE",
            quality_eligible=True,
        )
    )
    db.commit()

    def fake_run(session, **payload):
        run = CandidateHistoryBackfillRun(
            run_id="run-history-api",
            wallet_address=payload["wallet_address"],
            status="COMPLETED",
            stop_reason="LAST_PAGE",
            requested_lookback_days=payload["lookback_days"],
            page_size=payload["page_size"],
            request_budget=payload["max_helius_requests"],
            helius_requests=2,
            pages_fetched=2,
            transactions_found=15,
            swaps_found=15,
            trades_imported=12,
            trades_updated=3,
            parameters={},
            safety={"live_enabled": False, "generation_created": False},
            started_at=NOW,
            completed_at=NOW,
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        return run

    monkeypatch.setattr(api_module, "run_extended_candidate_history", fake_run)

    app = FastAPI()
    app.include_router(api_module.router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        yield client
    db.close()
    engine.dispose()


def test_extended_history_api_and_latest(api_client):
    response = api_client.post(
        "/discovered-wallets/promotion/history/backfill",
        json={
            "wallet_address": WALLET,
            "lookback_days": 30,
            "max_helius_requests": 5,
            "page_size": 100,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "COMPLETED"
    assert payload["helius_requests"] == 2
    assert payload["safety"]["live_enabled"] is False

    latest = api_client.get(
        f"/discovered-wallets/promotion/history/{WALLET}/latest"
    )
    assert latest.status_code == 200
    assert latest.json()["run_id"] == "run-history-api"
