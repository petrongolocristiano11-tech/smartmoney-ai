from datetime import (
    datetime,
    timezone,
)

import pytest
from fastapi import FastAPI
from fastapi.testclient import (
    TestClient,
)
from sqlalchemy import create_engine
from sqlalchemy.orm import (
    sessionmaker,
)
from sqlalchemy.pool import StaticPool

from backend.app.api.live_trading import (
    get_jupiter_client,
    get_solana_rpc_client,
    router,
)
from backend.app.core.config import (
    settings,
)
from backend.app.database.base import Base
from backend.app.database.session import (
    get_db,
)
from backend.app.models.trade import Trade
from backend.app.services.jupiter_swap_client import (
    JupiterOrderResult,
)


ACCESS_KEY = "k" * 40
WALLET = "W" * 32
TOKEN = "T" * 32


class FakeJupiter:
    def get_order(
        self,
        **kwargs,
    ):
        return JupiterOrderResult(
            raw={
                "requestId":
                    "request-api",
                "transaction":
                    None,
                "inAmount":
                    str(
                        kwargs[
                            "amount_raw"
                        ]
                    ),
                "outAmount":
                    "2000000",
                "slippageBps":
                    20,
                "router":
                    "iris",
                "priceImpact":
                    0.1,
            },
            request_id="request-api",
            transaction=None,
            in_amount=(
                kwargs["amount_raw"]
            ),
            out_amount=2_000_000,
            slippage_bps=20,
            router="iris",
            price_impact_percent=0.1,
            last_valid_block_height=None,
        )


class FakeRpc:
    def get_balance_sol(
        self,
        address,
    ):
        return 10.0


@pytest.fixture()
def api_client(
    monkeypatch,
):
    monkeypatch.setattr(
        settings,
        "LIVE_TRADING_API_KEY",
        ACCESS_KEY,
    )

    monkeypatch.setattr(
        settings,
        "JUPITER_API_KEY",
        "jupiter-key",
    )

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )

    Base.metadata.create_all(
        engine
    )

    session = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )()

    trade = Trade(
        signature="api-source",
        wallet_address=WALLET,
        side="BUY",
        token_mint=TOKEN,
        token_amount=100,
        sol_amount=0.2,
        success=True,
        block_time=datetime.now(
            timezone.utc
        ),
    )

    session.add(trade)
    session.commit()
    session.refresh(trade)

    app = FastAPI()

    app.include_router(
        router
    )

    def override_get_db():
        yield session

    app.dependency_overrides[
        get_db
    ] = override_get_db

    app.dependency_overrides[
        get_jupiter_client
    ] = lambda: FakeJupiter()

    app.dependency_overrides[
        get_solana_rpc_client
    ] = lambda: FakeRpc()

    with TestClient(
        app
    ) as client:
        yield client, trade.id

    session.close()
    engine.dispose()


def headers():
    return {
        "X-Live-Trading-Key":
            ACCESS_KEY
    }


def test_live_api_requires_key(
    api_client,
):
    client, _ = api_client

    response = client.get(
        "/live-trading/policy"
    )

    assert (
        response.status_code
        == 401
    )


def test_dry_run_api_workflow(
    api_client,
):
    client, trade_id = api_client

    response = client.patch(
        "/live-trading/policy",
        headers=headers(),
        json={
            "mode":
                "DRY_RUN",
            "source_wallets":
                [WALLET],
            "fixed_buy_size_sol":
                0.05,
            "max_order_size_sol":
                0.1,
            "max_daily_buy_sol":
                0.5,
            "max_total_exposure_sol":
                0.5,
        },
    )

    assert (
        response.status_code
        == 200
    )

    execution = client.post(
        (
            "/live-trading/"
            "execute/trades/"
            f"{trade_id}"
        ),
        headers=headers(),
    )

    assert (
        execution.status_code
        == 200
    )

    assert (
        execution.json()["status"]
        == "DRY_RUN"
    )

    positions = client.get(
        "/live-trading/positions",
        headers=headers(),
    )

    assert (
        positions.status_code
        == 200
    )

    assert (
        positions.json()["count"]
        == 1
    ) 

def test_dry_run_reset_starts_clean_generation(
    api_client,
):
    client, trade_id = api_client

    policy_response = client.patch(
        "/live-trading/policy",
        headers=headers(),
        json={
            "mode": "DRY_RUN",
            "source_wallets": [WALLET],
            "fixed_buy_size_sol": 0.05,
            "max_order_size_sol": 0.1,
            "max_daily_buy_sol": 0.5,
            "max_total_exposure_sol": 0.5,
            "stream_execution_enabled": False,
        },
    )

    assert (
        policy_response.status_code
        == 200
    )

    first_execution = client.post(
        (
            "/live-trading/"
            "execute/trades/"
            f"{trade_id}"
        ),
        headers=headers(),
    )

    assert (
        first_execution.status_code
        == 200
    )

    assert (
        first_execution.json()
        ["generation"]
        == 1
    )

    reset_response = client.post(
        "/live-trading/dry-run/reset",
        headers=headers(),
        json={
            "confirmation":
                "RESET DRY RUN",
            "source_wallets":
                [WALLET],
            "start_stream": False,
            "buy_enabled": True,
            "sell_enabled": True,
        },
    )

    assert (
        reset_response.status_code
        == 200
    )

    reset_payload = (
        reset_response.json()
    )

    assert (
        reset_payload
        ["previous_generation"]
        == 1
    )

    assert (
        reset_payload
        ["active_generation"]
        == 2
    )

    assert (
        reset_payload
        ["archived_positions"]
        == 1
    )

    assert (
        reset_payload
        ["archived_exposure_sol"]
        == pytest.approx(0.05)
    )

    active_positions = client.get(
        "/live-trading/positions",
        headers=headers(),
    )

    assert (
        active_positions.status_code
        == 200
    )

    assert (
        active_positions.json()["count"]
        == 0
    )

    historical_positions = client.get(
        (
            "/live-trading/positions"
            "?scope=ALL"
        ),
        headers=headers(),
    )

    assert (
        historical_positions.json()
        ["count"]
        == 1
    )

    archived_position = (
        historical_positions.json()
        ["positions"][0]
    )

    assert (
        archived_position["status"]
        == "CLOSED"
    )

    assert (
        archived_position["generation"]
        == 1
    )

    active_orders = client.get(
        "/live-trading/orders",
        headers=headers(),
    )

    assert (
        active_orders.json()["count"]
        == 0
    )

    historical_orders = client.get(
        "/live-trading/orders?scope=ALL",
        headers=headers(),
    )

    assert (
        historical_orders.json()["count"]
        == 1
    )

    second_execution = client.post(
        (
            "/live-trading/"
            "execute/trades/"
            f"{trade_id}"
        ),
        headers=headers(),
    )

    assert (
        second_execution.status_code
        == 200
    )

    assert (
        second_execution.json()
        ["generation"]
        == 2
    )

    status_response = client.get(
        "/live-trading/status",
        headers=headers(),
    )

    assert (
        status_response.status_code
        == 200
    )

    status_payload = (
        status_response.json()
    )

    assert (
        status_payload
        ["active_generation"]
        == 2
    )

    assert (
        status_payload
        ["open_positions"]
        == 1
    )

    assert (
        status_payload
        ["total_exposure_sol"]
        == pytest.approx(0.05)
    )


def test_dry_run_reset_requires_stream_off(
    api_client,
):
    client, _ = api_client

    response = client.patch(
        "/live-trading/policy",
        headers=headers(),
        json={
            "mode": "DRY_RUN",
            "source_wallets": [WALLET],
            "stream_execution_enabled": True,
        },
    )

    assert response.status_code == 200

    reset_response = client.post(
        "/live-trading/dry-run/reset",
        headers=headers(),
        json={
            "confirmation":
                "RESET DRY RUN",
            "source_wallets":
                [WALLET],
            "start_stream": False,
        },
    )

    assert (
        reset_response.status_code
        == 409
    )

    assert (
        reset_response.json()
        ["detail"]["code"]
        == (
            "DRY_RUN_STREAM_"
            "MUST_BE_DISABLED"
        )
    )


def test_api_can_close_active_dry_run_position(
    api_client,
):
    client, trade_id = api_client

    policy_response = client.patch(
        "/live-trading/policy",
        headers=headers(),
        json={
            "mode": "DRY_RUN",
            "source_wallets": [WALLET],
            "fixed_buy_size_sol": 0.05,
            "max_order_size_sol": 0.1,
            "max_daily_buy_sol": 0.5,
            "max_total_exposure_sol": 0.5,
            "stream_execution_enabled": False,
        },
    )

    assert policy_response.status_code == 200

    buy_response = client.post(
        f"/live-trading/execute/trades/{trade_id}",
        headers=headers(),
    )

    assert buy_response.status_code == 200

    positions_response = client.get(
        "/live-trading/positions",
        headers=headers(),
    )

    position_id = (
        positions_response.json()
        ["positions"][0]["id"]
    )

    close_response = client.post(
        (
            "/live-trading/positions/"
            f"{position_id}/close-dry-run"
        ),
        headers=headers(),
        json={
            "confirmation":
                "CLOSE DRY RUN POSITION",
        },
    )

    assert close_response.status_code == 200
    assert close_response.json()["status"] == "DRY_RUN"
    assert close_response.json()["source_side"] == "SELL"

    closed_positions = client.get(
        "/live-trading/positions",
        headers=headers(),
    )

    assert (
        closed_positions.json()
        ["positions"][0]["status"]
        == "CLOSED"
    )

    status_response = client.get(
        "/live-trading/status",
        headers=headers(),
    )

    assert status_response.status_code == 200
    assert status_response.json()["open_positions"] == 0
    assert status_response.json()["realized_pnl_today_sol"] != 0


def test_api_rejects_invalid_dry_run_close_confirmation(
    api_client,
):
    client, _ = api_client

    response = client.post(
        "/live-trading/positions/1/close-dry-run",
        headers=headers(),
        json={
            "confirmation": "CLOSE",
        },
    )

    assert response.status_code == 422
