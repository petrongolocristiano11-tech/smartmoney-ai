from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api import discovered_wallets as api_module
from backend.app.database.base import Base
from backend.app.database.session import get_db
from backend.app.models.candidate_exit_price_audit import (
    CandidateExitPriceAuditRun,
)


from backend.app.schemas.candidate_backtest import (
    CandidateExitabilityRefreshRequest,
)

NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
WALLET = "Y" * 32


def test_exitability_refresh_api(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()

    def fake_refresh(session, **payload):
        audit = CandidateExitPriceAuditRun(
            id=1,
            run_id="exit-audit-refresh-api",
            wallet_address=payload["wallet_address"],
            status="COMPLETED",
            readiness_status="PARTIAL",
            readiness_score=70,
            parameters={
                "source_lifecycle_run_id": payload["lifecycle_run_id"],
            },
            safety={"jupiter_requests": 0},
            summary={"positions_analyzed": 2},
            scenario_results=[],
            position_results=[],
            diagnoses=["CURRENT_CACHED_ROUTE_COVERAGE_LOW"],
            started_at=NOW,
            completed_at=NOW,
            created_at=NOW,
        )
        return {
            "wallet_address": payload["wallet_address"],
            "lifecycle_run_id": payload["lifecycle_run_id"],
            "status": "COMPLETED",
            "parameters": {"force_refresh": True},
            "safety": {
                "transactions_signed": False,
                "transactions_submitted": False,
            },
            "summary": {"route_found": 1, "no_route": 1},
            "results": [],
            "exit_price_audit": audit,
            "started_at": NOW,
            "completed_at": NOW,
        }

    monkeypatch.setattr(
        api_module,
        "refresh_candidate_open_position_exitability",
        fake_refresh,
    )

    app = FastAPI()
    app.include_router(api_module.router)

    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db

    with TestClient(app) as client:
        response = client.post(
            "/discovered-wallets/promotion/exitability-refresh",
            json={
                "wallet_address": WALLET,
                "lifecycle_run_id": "lifecycle-api",
                "cache_ttl_hours": 6,
                "max_local_price_age_hours": 24,
                "max_tokens": 20,
                "force_refresh": True,
            },
        )

    assert response.status_code == 200
    assert response.json()["status"] == "COMPLETED"
    assert response.json()["summary"]["route_found"] == 1
    assert response.json()["exit_price_audit"]["summary"][
        "positions_analyzed"
    ] == 2

    db.close()
    engine.dispose()


def test_exitability_refresh_request_defaults_to_cache_preserving_mode():
    request = CandidateExitabilityRefreshRequest(
        wallet_address=WALLET,
        lifecycle_run_id="lifecycle-api",
    )

    assert request.force_refresh is False
