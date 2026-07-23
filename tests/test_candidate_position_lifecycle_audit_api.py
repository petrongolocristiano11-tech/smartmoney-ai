from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api import (
    discovered_wallets as api_module,
)
from backend.app.database.base import Base
from backend.app.database.session import get_db
from backend.app.models.candidate_position_lifecycle_audit import (
    CandidatePositionLifecycleAuditRun,
)
from backend.app.models.discovered_wallet import (
    DiscoveredWallet,
)


NOW = datetime(
    2026,
    7,
    23,
    12,
    0,
    tzinfo=timezone.utc,
)
WALLET = "Y" * 32


@pytest.fixture()
def api_client(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={
            "check_same_thread": False
        },
        poolclass=StaticPool,
    )
    db = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )()
    Base.metadata.create_all(engine)
    db.add(
        DiscoveredWallet(
            wallet_address=WALLET,
            smart_score=75,
        )
    )
    db.commit()

    def fake_run(
        session,
        **payload,
    ):
        run = (
            CandidatePositionLifecycleAuditRun(
                run_id="lifecycle-api-run",
                wallet_address=(
                    payload["wallet_address"]
                ),
                status="COMPLETED",
                parameters={
                    "lookback_days": (
                        payload["lookback_days"]
                    )
                },
                safety={
                    "cached_data_only": True,
                    "helius_requests": 0,
                    "jupiter_requests": 0,
                    "live_enabled": False,
                    "generation_created": False,
                },
                baseline_metrics={
                    "open_positions": 1,
                },
                lifecycle_summary={
                    "NO_SOURCE_SELL": 1,
                },
                position_details=[
                    {
                        "token_mint": "A" * 32,
                        "reason_still_open": (
                            "NO_SOURCE_SELL"
                        ),
                    }
                ],
                scenario_results=[
                    {
                        "scenario_key": (
                            "no_expiry"
                        ),
                        "holding_period_hours": (
                            None
                        ),
                    }
                ],
                diagnoses=[
                    (
                        "OPEN_POSITIONS_"
                        "WITHOUT_SOURCE_SELL"
                    )
                ],
                started_at=NOW,
                completed_at=NOW,
            )
        )
        session.add(run)
        session.commit()
        session.refresh(run)
        return run

    monkeypatch.setattr(
        api_module,
        (
            "run_candidate_"
            "position_lifecycle_audit"
        ),
        fake_run,
    )

    app = FastAPI()
    app.include_router(api_module.router)

    def override_db():
        yield db

    app.dependency_overrides[
        get_db
    ] = override_db

    with TestClient(app) as client:
        yield client

    db.close()
    engine.dispose()


def test_lifecycle_audit_api_and_latest(
    api_client,
):
    response = api_client.post(
        (
            "/discovered-wallets/"
            "promotion/lifecycle-audit"
        ),
        json={
            "wallet_address": WALLET,
            "lookback_days": 14,
            "warmup_days": 14,
            "starting_capital_sol": 1,
            "fixed_buy_size_sol": 0.05,
            "slippage_bps": 100,
            "fee_bps": 10,
            "copy_delay_seconds": 8,
            "delay_penalty_bps_per_minute": 25,
            "max_open_positions": 5,
            "max_position_details": 200,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "COMPLETED"
    assert (
        payload["safety"][
            "cached_data_only"
        ]
        is True
    )
    assert (
        payload["lifecycle_summary"][
            "NO_SOURCE_SELL"
        ]
        == 1
    )

    latest = api_client.get(
        (
            "/discovered-wallets/"
            "promotion/lifecycle-audit/"
            f"{WALLET}/latest"
        )
    )

    assert latest.status_code == 200
    assert (
        latest.json()["run_id"]
        == "lifecycle-api-run"
    )
