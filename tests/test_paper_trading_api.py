import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import (
    Session,
    sessionmaker,
)
from sqlalchemy.pool import StaticPool

from backend.app.api.paper_trading import (
    router,
)
from backend.app.core.config import settings
from backend.app.database.session import get_db
from backend.app.models.paper_account import (
    PaperAccount,
)
from backend.app.models.paper_order import (
    PaperOrder,
)
from backend.app.models.paper_position import (
    PaperPosition,
)


ACCESS_KEY = "k" * 40


@pytest.fixture()
def client(
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

    app = FastAPI()
    app.include_router(router)

    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[
        get_db
    ] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

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
    client: TestClient,
):
    response = client.get(
        "/paper-trading/accounts"
    )

    assert response.status_code == 401


def test_account_creation_and_listing(
    client: TestClient,
):
    created = create_account(client)

    assert (
        created["account"]["name"]
        == "Test Account"
    )

    response = client.get(
        "/paper-trading/accounts",
        headers=auth_headers(),
    )

    assert response.status_code == 200
    assert response.json()["count"] == 1


def test_complete_paper_workflow(
    client: TestClient,
):
    created = create_account(client)

    account_id = (
        created["account"]["id"]
    )

    buy_response = client.post(
        (
            f"/paper-trading/accounts/"
            f"{account_id}/buy"
        ),
        headers=auth_headers(),
        json={
            "token_mint": "TOKEN_A",
            "value_sol": 1,
            "market_price_sol": 0.1,
            "slippage_percent": 0,
            "fee_percent": 0,
            "signal_score": 80,
            "reason": "Test signal",
        },
    )

    assert buy_response.status_code == 200

    assert (
        buy_response.json()
        ["summary"]
        ["cash_balance_sol"]
        == pytest.approx(9)
    )

    mark_response = client.post(
        (
            f"/paper-trading/accounts/"
            f"{account_id}/mark"
        ),
        headers=auth_headers(),
        json={
            "token_mint": "TOKEN_A",
            "market_price_sol": 0.2,
        },
    )

    assert mark_response.status_code == 200

    assert (
        mark_response.json()
        ["unrealized_pnl_sol"]
        == pytest.approx(1)
    )

    sell_response = client.post(
        (
            f"/paper-trading/accounts/"
            f"{account_id}/sell"
        ),
        headers=auth_headers(),
        json={
            "token_mint": "TOKEN_A",
            "market_price_sol": 0.2,
            "quantity": None,
            "slippage_percent": 0,
            "fee_percent": 0,
            "reason": "Close test",
        },
    )

    assert sell_response.status_code == 200

    assert (
        sell_response.json()
        ["order"]
        ["realized_pnl_sol"]
        == pytest.approx(1)
    )

    detail_response = client.get(
        (
            f"/paper-trading/accounts/"
            f"{account_id}"
        ),
        headers=auth_headers(),
    )

    assert detail_response.status_code == 200

    detail = detail_response.json()

    assert (
        detail["summary"]["equity_sol"]
        == pytest.approx(11)
    )

    assert (
        detail["positions"][0]["status"]
        == "CLOSED"
    )


def test_pause_blocks_new_buys(
    client: TestClient,
):
    created = create_account(client)

    account_id = (
        created["account"]["id"]
    )

    pause_response = client.patch(
        (
            f"/paper-trading/accounts/"
            f"{account_id}"
        ),
        headers=auth_headers(),
        json={
            "status": "PAUSED",
        },
    )

    assert pause_response.status_code == 200

    buy_response = client.post(
        (
            f"/paper-trading/accounts/"
            f"{account_id}/buy"
        ),
        headers=auth_headers(),
        json={
            "token_mint": "TOKEN_A",
            "value_sol": 1,
            "market_price_sol": 0.1,
        },
    )

    assert buy_response.status_code == 409


def test_reset_requires_exact_name(
    client: TestClient,
):
    created = create_account(client)

    account_id = (
        created["account"]["id"]
    )

    wrong_response = client.post(
        (
            f"/paper-trading/accounts/"
            f"{account_id}/reset"
        ),
        headers=auth_headers(),
        json={
            "confirmation_name": "Wrong",
        },
    )

    assert wrong_response.status_code == 409

    correct_response = client.post(
        (
            f"/paper-trading/accounts/"
            f"{account_id}/reset"
        ),
        headers=auth_headers(),
        json={
            "confirmation_name":
                "Test Account",
        },
    )

    assert correct_response.status_code == 200

    summary = (
        correct_response.json()
        ["summary"]
    )

    assert summary["equity_sol"] == 10
    assert summary["open_positions"] == 0 