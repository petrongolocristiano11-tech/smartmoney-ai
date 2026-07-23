from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api import discovered_wallets as api_module
from backend.app.database.base import Base
from backend.app.database.session import get_db
from backend.app.models.candidate_exit_price_audit import CandidateExitPriceAuditRun
from backend.app.models.discovered_wallet import DiscoveredWallet


NOW = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
WALLET = "X" * 32


def test_exit_price_audit_api_and_latest(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    db.add(DiscoveredWallet(wallet_address=WALLET, smart_score=70))
    db.commit()

    def fake_run(session, **payload):
        run = CandidateExitPriceAuditRun(
            run_id="exit-price-api-run",
            wallet_address=payload["wallet_address"],
            status="COMPLETED",
            readiness_status="BLOCKED",
            readiness_score=45,
            parameters={"max_local_price_age_hours": 24},
            safety={"helius_requests": 0, "jupiter_requests": 0},
            summary={"positions_analyzed": 1},
            scenario_results=[],
            position_results=[],
            diagnoses=["CURRENT_CACHED_ROUTE_COVERAGE_LOW"],
            started_at=NOW,
            completed_at=NOW,
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        return run

    monkeypatch.setattr(api_module, "run_candidate_exit_price_audit", fake_run)
    app = FastAPI()
    app.include_router(api_module.router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as client:
        response = client.post(
            "/discovered-wallets/promotion/exit-price-audit",
            json={
                "wallet_address": WALLET,
                "max_local_price_age_hours": 24,
            },
        )
        assert response.status_code == 200
        assert response.json()["readiness_status"] == "BLOCKED"

        latest = client.get(
            f"/discovered-wallets/promotion/exit-price-audit/{WALLET}/latest"
        )
        assert latest.status_code == 200
        assert latest.json()["run_id"] == "exit-price-api-run"

    db.close()
    engine.dispose()
