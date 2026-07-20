from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import pytest

from backend.app.api.live_operations import (
    get_jupiter_client,
    get_rpc_client,
    get_signer,
    router,
)
from backend.app.core.config import settings
from backend.app.database.base import Base
from backend.app.database.session import get_db
from backend.app.models.live_position import LivePosition
from backend.app.services.jupiter_swap_client import JupiterOrderResult
from backend.app.services.live_trading_policy_service import get_or_create_live_policy


ACCESS_KEY = "k" * 40
TOKEN = "T" * 32
WALLET = "W" * 32


class FakeJupiter:
    def get_order(self, **kwargs):
        return JupiterOrderResult(
            raw={
                "requestId": "operations-request",
                "transaction": None,
                "inAmount": str(kwargs["amount_raw"]),
                "outAmount": "60000000",
                "slippageBps": 20,
                "router": "iris",
                "priceImpact": 0.1,
            },
            request_id="operations-request",
            transaction=None,
            in_amount=kwargs["amount_raw"],
            out_amount=60_000_000,
            slippage_bps=20,
            router="iris",
            price_impact_percent=0.1,
            last_valid_block_height=None,
        )


class FakeRpc:
    def get_signature_status(self, signature):
        return {
            "found": False,
            "confirmation_status": None,
            "confirmations": None,
            "error": None,
            "slot": None,
        }


class FakeSigner:
    wallet_address = WALLET


@pytest.fixture()
def api_client(monkeypatch):
    monkeypatch.setattr(settings, "LIVE_TRADING_API_KEY", ACCESS_KEY)
    monkeypatch.setattr(settings, "RUN_LIVE_POSITION_MONITOR", False)

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()

    policy = get_or_create_live_policy(session)
    policy.mode = "DRY_RUN"
    policy.sell_enabled = True
    policy.automatic_exits_enabled = True
    policy.take_profit_enabled = True
    policy.take_profit_percent = 10
    policy.stop_loss_enabled = True
    policy.max_token_exposure_sol = 0.1
    policy.max_total_exposure_sol = 0.5
    session.add(
        LivePosition(
            mode="DRY_RUN",
            generation=1,
            token_mint=TOKEN,
            source_wallet=WALLET,
            status="OPEN",
            quantity_raw=2_000_000,
            cost_basis_sol=0.05,
            realized_pnl_sol=0.0,
        )
    )
    session.commit()

    app = FastAPI()
    app.include_router(router)

    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_jupiter_client] = lambda: FakeJupiter()
    app.dependency_overrides[get_rpc_client] = lambda: FakeRpc()
    app.dependency_overrides[get_signer] = lambda: FakeSigner()

    with TestClient(app) as client:
        yield client

    session.close()
    engine.dispose()


def headers():
    return {"X-Live-Trading-Key": ACCESS_KEY}


def test_operations_api_requires_internal_key(api_client):
    response = api_client.get("/live-trading/operations/overview")
    assert response.status_code == 401


def test_operations_run_once_closes_profitable_dry_run_position(api_client):
    run = api_client.post(
        "/live-trading/operations/run-once",
        headers=headers(),
        json={"position_limit": 10, "reconcile_limit": 10},
    )
    assert run.status_code == 200
    payload = run.json()
    assert payload["positions_scanned"] == 1
    assert payload["exits_triggered"] == 1
    assert payload["exits_completed"] == 1
    assert payload["items"][0]["exit_reason"] == "TAKE_PROFIT"

    overview = api_client.get(
        "/live-trading/operations/overview",
        headers=headers(),
    )
    assert overview.status_code == 200
    data = overview.json()
    assert data["open_positions"] == 0
    assert data["monitor"]["total_runs"] == 1
    assert data["risk"]["realized_pnl_sol"] == pytest.approx(0.01)
    assert data["automatic_exits_enabled"] is True
    assert data["monitor_runtime_enabled"] is False


def test_cooldown_reset_requires_exact_confirmation(api_client):
    invalid = api_client.post(
        "/live-trading/operations/risk/cooldown/reset",
        headers=headers(),
        json={"confirmation": "RESET"},
    )
    assert invalid.status_code == 422

    valid = api_client.post(
        "/live-trading/operations/risk/cooldown/reset",
        headers=headers(),
        json={"confirmation": "RESET RISK COOLDOWN"},
    )
    assert valid.status_code == 200
    assert valid.json()["loss_streak"] == 0
