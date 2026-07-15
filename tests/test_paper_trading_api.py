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
    Session,
    sessionmaker,
)
from sqlalchemy.pool import StaticPool

from backend.app.api.paper_trading import (
    router,
)
from backend.app.core.config import (
    settings,
)
from backend.app.database.session import (
    get_db,
)
from backend.app.models.paper_account import (
    PaperAccount,
)
from backend.app.models.paper_order import (
    PaperOrder,
)
from backend.app.models.paper_position import (
    PaperPosition,
)
from backend.app.services.price_oracle import (
    OracleBatch,
    OraclePrice,
    PriceOracleError,
    get_price_oracle,
)


ACCESS_KEY = "k" * 40

TOKEN_MINT = (
    "Token1111111111111111111111111111111111111"
)


class FakeOracle:
    def __init__(self):
        self.sol_price = 0.1

    def _quote(
        self,
        token_mint: str,
    ) -> OraclePrice:
        if token_mint != TOKEN_MINT:
            raise PriceOracleError(
                "Prezzo non disponibile.",
                code=(
                    "PRICE_NOT_AVAILABLE"
                ),
            )

        return OraclePrice(
            token_mint=token_mint,
            usd_price=(
                self.sol_price * 100
            ),
            sol_price=self.sol_price,
            sol_usd_price=100,
            block_id=123,
            decimals=6,
            price_change_24h=2.5,
            fetched_at=datetime.now(
                timezone.utc
            ),
        )

    def get_price(
        self,
        token_mint: str,
        force_refresh: bool = False,
    ) -> OraclePrice:
        return self._quote(
            token_mint
        )

    def get_prices(
        self,
        token_mints,
        force_refresh: bool = False,
    ) -> OracleBatch:
        prices = {}
        missing = []

        for token_mint in token_mints:
            try:
                prices[token_mint] = (
                    self._quote(
                        token_mint
                    )
                )

            except PriceOracleError:
                missing.append(
                    token_mint
                )

        return OracleBatch(
            prices=prices,
            missing_token_mints=missing,
            fetched_at=datetime.now(
                timezone.utc
            ),
        )


@pytest.fixture()
def api_client(
    monkeypatch,
):
    monkeypatch.setattr(
        settings,
        "PAPER_TRADING_API_KEY",
        ACCESS_KEY,
    )

    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )

    PaperAccount.__table__.create(
        bind=engine
    )

    PaperPosition.__table__.create(
        bind=engine
    )

    PaperOrder.__table__.create(
        bind=engine
    )

    testing_session = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    session: Session = (
        testing_session()
    )

    oracle = FakeOracle()

    app = FastAPI()
    app.include_router(router)

    def override_get_db():
        yield session

    app.dependency_overrides[
        get_db
    ] = override_get_db

    app.dependency_overrides[
        get_price_oracle
    ] = lambda: oracle

    with TestClient(
        app
    ) as client:
        yield client, oracle

    session.close()
    engine.dispose()


def auth_headers():
    return {
        "X-Paper-Trading-Key":
            ACCESS_KEY
    }


def create_account(
    client: TestClient,
):
    response = client.post(
        "/paper-trading/accounts",
        headers=auth_headers(),
        json={
            "name": "Test Account",
            "starting_balance_sol": 10,
            "max_position_size_sol": 2,
            "max_open_positions": 3,
            "daily_loss_limit_sol": 1,
        },
    )

    assert response.status_code == 201

    return response.json()


def test_access_key_is_required(
    api_client,
):
    client, _ = api_client

    response = client.get(
        "/paper-trading/accounts"
    )

    assert response.status_code == 401


def test_price_preview_uses_oracle(
    api_client,
):
    client, _ = api_client

    response = client.get(
        (
            "/paper-trading/prices/"
            f"{TOKEN_MINT}"
        ),
        headers=auth_headers(),
    )

    assert response.status_code == 200

    assert (
        response.json()["sol_price"]
        == pytest.approx(0.1)
    )


def test_complete_oracle_workflow(
    api_client,
):
    client, oracle = api_client

    created = create_account(
        client
    )

    account_id = (
        created["account"]["id"]
    )

    buy_response = client.post(
        (
            "/paper-trading/accounts/"
            f"{account_id}/buy"
        ),
        headers=auth_headers(),
        json={
            "token_mint": TOKEN_MINT,
            "value_sol": 1,
            "slippage_percent": 0,
            "fee_percent": 0,
            "signal_score": 80,
            "reason": "Test signal",
        },
    )

    assert (
        buy_response.status_code
        == 200
    )

    assert (
        buy_response.json()
        ["price"]
        ["sol_price"]
        == pytest.approx(0.1)
    )

    assert (
        buy_response.json()
        ["summary"]
        ["cash_balance_sol"]
        == pytest.approx(9)
    )

    oracle.sol_price = 0.2

    refresh_response = client.post(
        (
            "/paper-trading/accounts/"
            f"{account_id}/"
            "refresh-prices"
        ),
        headers=auth_headers(),
        params={
            "force_refresh": True,
        },
    )

    assert (
        refresh_response.status_code
        == 200
    )

    assert (
        refresh_response.json()
        ["updated_positions"]
        [0]
        ["unrealized_pnl_sol"]
        == pytest.approx(1)
    )

    sell_response = client.post(
        (
            "/paper-trading/accounts/"
            f"{account_id}/sell"
        ),
        headers=auth_headers(),
        json={
            "token_mint": TOKEN_MINT,
            "quantity": None,
            "slippage_percent": 0,
            "fee_percent": 0,
            "reason": "Close test",
        },
    )

    assert (
        sell_response.status_code
        == 200
    )

    assert (
        sell_response.json()
        ["order"]
        ["realized_pnl_sol"]
        == pytest.approx(1)
    )

    assert (
        sell_response.json()
        ["summary"]
        ["equity_sol"]
        == pytest.approx(11)
    )


def test_manual_market_price_is_rejected(
    api_client,
):
    client, _ = api_client

    created = create_account(
        client
    )

    account_id = (
        created["account"]["id"]
    )

    response = client.post(
        (
            "/paper-trading/accounts/"
            f"{account_id}/buy"
        ),
        headers=auth_headers(),
        json={
            "token_mint": TOKEN_MINT,
            "value_sol": 1,
            "market_price_sol": (
                0.000001
            ),
        },
    )

    assert response.status_code == 422


def test_missing_oracle_price_blocks_buy(
    api_client,
):
    client, _ = api_client

    created = create_account(
        client
    )

    account_id = (
        created["account"]["id"]
    )

    response = client.post(
        (
            "/paper-trading/accounts/"
            f"{account_id}/buy"
        ),
        headers=auth_headers(),
        json={
            "token_mint": (
                "Missing111111111111111111"
                "111111111111111111"
            ),
            "value_sol": 1,
        },
    )

    assert response.status_code == 422

    assert (
        response.json()
        ["detail"]
        ["code"]
        == "PRICE_NOT_AVAILABLE"
    )


def test_pause_blocks_new_buys(
    api_client,
):
    client, _ = api_client

    created = create_account(
        client
    )

    account_id = (
        created["account"]["id"]
    )

    pause_response = client.patch(
        (
            "/paper-trading/accounts/"
            f"{account_id}"
        ),
        headers=auth_headers(),
        json={
            "status": "PAUSED",
        },
    )

    assert (
        pause_response.status_code
        == 200
    )

    buy_response = client.post(
        (
            "/paper-trading/accounts/"
            f"{account_id}/buy"
        ),
        headers=auth_headers(),
        json={
            "token_mint": TOKEN_MINT,
            "value_sol": 1,
        },
    )

    assert (
        buy_response.status_code
        == 409
    ) 