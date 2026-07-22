from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.config import settings
from backend.app.database.base import Base
from backend.app.models.live_copy_order import LiveCopyOrder
from backend.app.models.live_position import LivePosition
from backend.app.models.live_trading_event import LiveTradingEvent
from backend.app.models.trade import Trade
from backend.app.services.jupiter_swap_client import JupiterSwapClient
from backend.app.services.live_copy_trading_engine import execute_source_trade
from backend.app.services.live_trading_errors import JupiterSwapError, LiveTradingError
from backend.app.services.live_trading_policy_service import get_or_create_live_policy
from backend.app.services.live_trading_risk_engine import build_live_execution_plan
from backend.app.workers import helius_live_trading_worker as worker_module


WALLET = "W" * 32
TOKEN = "T" * 32


@pytest.fixture()
def session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )

    Base.metadata.create_all(engine)

    factory = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    yield factory

    engine.dispose()


def configure_policy(db):
    policy = get_or_create_live_policy(db)

    policy.mode = "DRY_RUN"
    policy.stream_execution_enabled = True
    policy.source_wallets = [WALLET]
    policy.buy_enabled = True
    policy.sell_enabled = True
    policy.fixed_buy_size_sol = 0.01
    policy.max_order_size_sol = 0.01
    policy.max_daily_buy_sol = 0.10
    policy.max_daily_orders = 20
    policy.max_total_exposure_sol = 0.03
    policy.max_token_exposure_sol = 0.01
    policy.min_source_trade_sol = 0.001
    policy.max_source_trade_age_seconds = 300

    db.commit()
    db.refresh(policy)

    return policy


def test_jupiter_quote_retries_transient_http_error():
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1

        if calls["count"] == 1:
            return httpx.Response(
                503,
                json={
                    "error": "temporary",
                },
            )

        return httpx.Response(
            200,
            json={
                "requestId": "quote-1",
                "transaction": None,
                "inAmount": "100",
                "outAmount": "200",
                "slippageBps": 20,
                "router": "iris",
                "priceImpact": 0.1,
            },
        )

    client = JupiterSwapClient(
        api_key="test-key",
        base_url="https://jupiter.test",
        max_retries=2,
        retry_base_seconds=0,
        retry_max_seconds=0,
        sleep_fn=lambda seconds: None,
        transport=httpx.MockTransport(handler),
    )

    result = client.get_order(
        input_mint="A",
        output_mint="B",
        amount_raw=100,
        taker=None,
        slippage_bps=20,
    )

    assert calls["count"] == 2
    assert result.request_id == "quote-1"
    assert result.out_amount == 200


def test_jupiter_execute_is_not_retried():
    calls = {"count": 0}

    def handler(request):
        calls["count"] += 1

        return httpx.Response(
            503,
            json={
                "error": "temporary",
            },
        )

    client = JupiterSwapClient(
        api_key="test-key",
        base_url="https://jupiter.test",
        max_retries=5,
        retry_base_seconds=0,
        retry_max_seconds=0,
        sleep_fn=lambda seconds: None,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(
        JupiterSwapError
    ) as error:
        client.execute_order(
            signed_transaction="signed",
            request_id="request-1",
        )

    assert calls["count"] == 1
    assert (
        error.value.code
        == "JUPITER_HTTP_ERROR"
    )


def test_token_reentry_cooldown_blocks_immediate_buy(
    session_factory,
    monkeypatch,
):
    monkeypatch.setattr(
        settings,
        "LIVE_TOKEN_REENTRY_COOLDOWN_MINUTES",
        15,
    )

    db = session_factory()

    try:
        policy = configure_policy(db)
        now = datetime.now(timezone.utc)

        db.add(
            LivePosition(
                mode="DRY_RUN",
                generation=1,
                token_mint=TOKEN,
                status="CLOSED",
                quantity_raw=Decimal(0),
                cost_basis_sol=0,
                realized_pnl_sol=0.001,
                opened_at=(
                    now
                    - timedelta(
                        minutes=20
                    )
                ),
                closed_at=(
                    now
                    - timedelta(
                        minutes=5
                    )
                ),
            )
        )

        trade = Trade(
            signature="reentry-buy",
            wallet_address=WALLET,
            side="BUY",
            token_mint=TOKEN,
            token_amount=100,
            sol_amount=0.2,
            success=True,
            block_time=now,
        )

        db.add(trade)
        db.commit()

        with pytest.raises(
            LiveTradingError
        ) as error:
            build_live_execution_plan(
                db,
                policy=policy,
                trade=trade,
                wallet_balance_sol=None,
                now=now,
            )

        assert (
            error.value.code
            == "TOKEN_REENTRY_COOLDOWN"
        )

    finally:
        db.close()


def test_stream_sell_without_position_is_ignored(
    session_factory,
):
    db = session_factory()

    try:
        configure_policy(db)

        trade = Trade(
            signature="duplicate-sell",
            wallet_address=WALLET,
            side="SELL",
            token_mint=TOKEN,
            token_amount=100,
            sol_amount=0.2,
            success=True,
            block_time=datetime.now(
                timezone.utc
            ),
        )

        db.add(trade)
        db.commit()
        db.refresh(trade)

        result = execute_source_trade(
            db,
            trade=trade,
            origin="STREAM",
        )

        assert result is None
        assert (
            db.query(
                LiveCopyOrder
            ).count()
            == 0
        )

        event = (
            db.query(
                LiveTradingEvent
            )
            .filter(
                LiveTradingEvent.event_type
                == "SOURCE_SELL_IGNORED"
            )
            .one()
        )

        assert (
            event.payload["code"]
            == "IGNORED_ALREADY_CLOSED"
        )

    finally:
        db.close()


def test_worker_pauses_after_daily_order_limit(
    session_factory,
    monkeypatch,
):
    monkeypatch.setattr(
        worker_module,
        "SessionLocal",
        session_factory,
    )

    monkeypatch.setattr(
        settings,
        "JUPITER_API_KEY",
        "test-jupiter",
    )

    db = session_factory()

    try:
        policy = configure_policy(db)
        policy.max_daily_orders = 1

        db.add(
            LiveCopyOrder(
                idempotency_key=(
                    "daily-order-limit"
                ),
                source_signature=(
                    "daily-order-limit"
                ),
                source_wallet=WALLET,
                source_side="BUY",
                source_token_mint=TOKEN,
                mode="DRY_RUN",
                generation=1,
                status="DRY_RUN",
                input_mint="SOL",
                output_mint=TOKEN,
                requested_input_amount_raw=(
                    Decimal(
                        10_000_000
                    )
                ),
                requested_value_sol=0.01,
                actual_input_amount_raw=(
                    Decimal(
                        10_000_000
                    )
                ),
                actual_output_amount_raw=(
                    Decimal(100)
                ),
                slippage_bps=20,
                executed_at=datetime.now(
                    timezone.utc
                ),
            )
        )

        db.commit()

        snapshot = (
            worker_module
            .load_policy_snapshot()
        )

        assert snapshot.enabled is False
        assert (
            snapshot.blocked_reason
            == "PAUSED_MAX_DAILY_ORDERS"
        )

    finally:
        db.close()
