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

from backend.app.api.paper_autopilot import (
    get_autopilot_signal_provider,
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
from backend.app.models.paper_autopilot import (
    PaperAutopilotDecision,
    PaperAutopilotManagedPosition,
    PaperAutopilotPolicy,
    PaperAutopilotRun,
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
    get_price_oracle,
)


PAPER_KEY = "p" * 40
AUTOMATION_KEY = "a" * 40

TOKEN_MINT = (
    "TokenAutopilot111111111111111"
    "1111111111111111"
)


class FakeOracle:
    def __init__(
        self,
        price: float = 0.1,
    ):
        self.price = price

    def _quote(
        self,
        token_mint: str,
    ) -> OraclePrice:
        return OraclePrice(
            token_mint=token_mint,
            usd_price=(
                self.price * 100
            ),
            sol_price=self.price,
            sol_usd_price=100,
            block_id=123,
            decimals=6,
            price_change_24h=1.0,
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
        prices = {
            mint: self._quote(
                mint
            )
            for mint in token_mints
        }

        return OracleBatch(
            prices=prices,
            missing_token_mints=[],
            fetched_at=datetime.now(
                timezone.utc
            ),
        )


def signal_provider(
    db,
    min_buyers=1,
    lookback_hours=24,
):
    signal = {
        "version": "2.0",
        "token_mint": TOKEN_MINT,
        "buyers": 4,
        "signal_score": 90.0,
        "evidence_score": 80.0,
        "confidence": "HIGH",
        "age_hours": 1.0,
        "smart_volume_share_percent": 85.0,
        "volume_concentration_percent": 30.0,
        "risk_flags": [],
        "reasons": [
            "Segnale API test"
        ],
    }

    return {
        "version": "2.0",
        "generated_at": (
            datetime.now(
                timezone.utc
            ).isoformat()
        ),
        "lookback_hours": (
            lookback_hours
        ),
        "count": 1,
        "signals": [signal],
    }


@pytest.fixture()
def api_client(
    monkeypatch,
):
    monkeypatch.setattr(
        settings,
        "PAPER_TRADING_API_KEY",
        PAPER_KEY,
    )

    monkeypatch.setattr(
        settings,
        "AUTOMATION_API_KEY",
        AUTOMATION_KEY,
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

    PaperAutopilotPolicy.__table__.create(
        bind=engine
    )

    PaperAutopilotRun.__table__.create(
        bind=engine
    )

    (
        PaperAutopilotManagedPosition
        .__table__
        .create(
            bind=engine
        )
    )

    (
        PaperAutopilotDecision
        .__table__
        .create(
            bind=engine
        )
    )

    session_factory = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    session: Session = (
        session_factory()
    )

    account = PaperAccount(
        name="Autopilot API",
        status="ACTIVE",
        starting_balance_sol=10.0,
        cash_balance_sol=10.0,
        realized_pnl_sol=0.0,
        max_position_size_sol=0.5,
        max_open_positions=3,
        daily_loss_limit_sol=1.0,
    )

    session.add(account)
    session.commit()
    session.refresh(account)

    app = FastAPI()
    app.include_router(router)

    def override_get_db():
        yield session

    app.dependency_overrides[
        get_db
    ] = override_get_db

    app.dependency_overrides[
        get_price_oracle
    ] = lambda: FakeOracle()

    app.dependency_overrides[
        get_autopilot_signal_provider
    ] = lambda: signal_provider

    with TestClient(
        app
    ) as client:
        yield client, account

    session.close()
    engine.dispose()


def paper_headers():
    return {
        "X-Paper-Trading-Key":
            PAPER_KEY
    }


def automation_headers():
    return {
        "X-Automation-Key":
            AUTOMATION_KEY
    }


def test_dashboard_creates_safe_disabled_policy(
    api_client,
):
    client, account = api_client

    response = client.get(
        (
            "/paper-autopilot/"
            f"accounts/{account.id}"
        ),
        headers=paper_headers(),
    )

    assert response.status_code == 200

    payload = response.json()

    assert (
        payload["policy"]["status"]
        == "DISABLED"
    )

    assert payload["runs"] == []
    assert payload["decisions"] == []


def test_policy_can_be_enabled(
    api_client,
):
    client, account = api_client

    response = client.patch(
        (
            "/paper-autopilot/"
            f"accounts/{account.id}/"
            "policy"
        ),
        headers=paper_headers(),
        json={
            "status": "ENABLED",
            "max_entries_per_run": 1,
            "max_entries_per_day": 3,
        },
    )

    assert response.status_code == 200

    policy = response.json()[
        "policy"
    ]

    assert (
        policy["status"]
        == "ENABLED"
    )

    assert (
        policy["consecutive_errors"]
        == 0
    )


def test_invalid_capital_allocation_is_rejected(
    api_client,
):
    client, account = api_client

    response = client.patch(
        (
            "/paper-autopilot/"
            f"accounts/{account.id}/"
            "policy"
        ),
        headers=paper_headers(),
        json={
            "max_total_exposure_percent":
                90,
            "minimum_cash_reserve_percent":
                20,
        },
    )

    assert response.status_code == 422

    assert (
        response.json()
        ["detail"]
        ["code"]
        == "INVALID_CAPITAL_ALLOCATION"
    )


def test_manual_run_opens_position(
    api_client,
):
    client, account = api_client

    enable_response = client.patch(
        (
            "/paper-autopilot/"
            f"accounts/{account.id}/"
            "policy"
        ),
        headers=paper_headers(),
        json={
            "status": "ENABLED",
            "slippage_percent": 0,
            "fee_percent": 0,
        },
    )

    assert (
        enable_response.status_code
        == 200
    )

    response = client.post(
        (
            "/paper-autopilot/"
            f"accounts/{account.id}/run"
        ),
        headers=paper_headers(),
    )

    assert response.status_code == 200

    payload = response.json()

    assert (
        payload["run"]["status"]
        == "COMPLETED"
    )

    assert (
        payload["run"]
        ["entries_opened"]
        == 1
    )

    buy_decisions = [
        decision
        for decision
        in payload["decisions"]
        if decision["action"]
        == "BUY"
    ]

    assert len(
        buy_decisions
    ) == 1


def test_automation_endpoint_requires_key(
    api_client,
):
    client, _ = api_client

    response = client.post(
        "/paper-autopilot/"
        "automation/run"
    )

    assert response.status_code == 401


def test_automation_runs_enabled_accounts(
    api_client,
):
    client, account = api_client

    enable_response = client.patch(
        (
            "/paper-autopilot/"
            f"accounts/{account.id}/"
            "policy"
        ),
        headers=paper_headers(),
        json={
            "status": "ENABLED",
            "slippage_percent": 0,
            "fee_percent": 0,
        },
    )

    assert (
        enable_response.status_code
        == 200
    )

    response = client.post(
        "/paper-autopilot/"
        "automation/run",
        headers=automation_headers(),
    )

    assert response.status_code == 200

    payload = response.json()

    assert (
        payload["processed_accounts"]
        == 1
    )

    assert (
        payload["successful_runs"]
        == 1
    )

    assert (
        payload["failed_runs"]
        == 0
    ) 