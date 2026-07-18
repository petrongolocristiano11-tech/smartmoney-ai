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