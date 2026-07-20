from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database.base import Base
from backend.app.models.live_copy_order import LiveCopyOrder
from backend.app.models.live_position import LivePosition
from backend.app.services.live_platform_config_service import get_or_create_platform_config
from backend.app.services.live_trading_analytics import (
    build_live_trading_analytics,
    build_live_trading_csv,
)
from backend.app.services.live_trading_policy_service import get_or_create_live_policy


WALLET = "W" * 32
TOKEN_A = "A" * 32
TOKEN_B = "B" * 32


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def add_order(
    db,
    *,
    key: str,
    side: str,
    token: str,
    value_sol: float,
    pnl_sol: float,
    when: datetime,
    wallet: str = WALLET,
):
    order = LiveCopyOrder(
        idempotency_key=key,
        source_signature=key,
        source_wallet=wallet,
        source_side=side,
        source_token_mint=token,
        mode="DRY_RUN",
        generation=2,
        status="DRY_RUN",
        input_mint="So11111111111111111111111111111111111111112" if side == "BUY" else token,
        output_mint=token if side == "BUY" else "So11111111111111111111111111111111111111112",
        requested_input_amount_raw=Decimal(1_000_000),
        requested_value_sol=value_sol,
        expected_output_amount_raw=Decimal(2_000_000),
        actual_input_amount_raw=Decimal(1_000_000),
        actual_output_amount_raw=Decimal(2_000_000),
        slippage_bps=20,
        realized_pnl_sol=pnl_sol,
        created_at=when,
        executed_at=when,
    )
    db.add(order)
    return order


def test_analytics_calculates_pnl_roi_profit_factor_and_drawdown(db):
    now = datetime.now(timezone.utc)
    policy = get_or_create_live_policy(db)
    policy.mode = "DRY_RUN"
    policy.dry_run_generation = 2

    config = get_or_create_platform_config(db)
    config.analytics_starting_equity_sol = 1.0

    add_order(db, key="buy-a", side="BUY", token=TOKEN_A, value_sol=0.05, pnl_sol=0, when=now - timedelta(days=3))
    add_order(db, key="sell-a", side="SELL", token=TOKEN_A, value_sol=0.05, pnl_sol=0.02, when=now - timedelta(days=2))
    add_order(db, key="buy-b", side="BUY", token=TOKEN_B, value_sol=0.05, pnl_sol=0, when=now - timedelta(days=2))
    add_order(db, key="sell-b", side="SELL", token=TOKEN_B, value_sol=0.05, pnl_sol=-0.01, when=now - timedelta(days=1))

    db.add_all([
        LivePosition(
            mode="DRY_RUN",
            generation=2,
            token_mint=TOKEN_A,
            status="CLOSED",
            quantity_raw=Decimal(0),
            cost_basis_sol=0,
            realized_pnl_sol=0.02,
            opened_at=now - timedelta(days=3),
            closed_at=now - timedelta(days=2),
        ),
        LivePosition(
            mode="DRY_RUN",
            generation=2,
            token_mint=TOKEN_B,
            status="CLOSED",
            quantity_raw=Decimal(0),
            cost_basis_sol=0,
            realized_pnl_sol=-0.01,
            opened_at=now - timedelta(days=2),
            closed_at=now - timedelta(days=1),
        ),
    ])
    db.commit()

    payload = build_live_trading_analytics(db, days=7, mode="DRY_RUN", generation=2, now=now)
    summary = payload["summary"]

    assert summary["net_realized_pnl_sol"] == pytest.approx(0.01)
    assert summary["roi_percent"] == pytest.approx(10.0)
    assert summary["win_rate_percent"] == pytest.approx(50.0)
    assert summary["profit_factor"] == pytest.approx(2.0)
    assert summary["max_drawdown_sol"] == pytest.approx(0.01)
    assert summary["ending_equity_sol"] == pytest.approx(1.01)
    assert len(payload["wallet_performance"]) == 1
    assert len(payload["token_performance"]) == 2


def test_analytics_csv_contains_daily_equity_rows(db):
    now = datetime.now(timezone.utc)
    policy = get_or_create_live_policy(db)
    policy.mode = "DRY_RUN"
    policy.dry_run_generation = 2
    db.commit()

    payload = build_live_trading_analytics(db, days=3, mode="DRY_RUN", generation=2, now=now)
    csv_content = build_live_trading_csv(payload)

    assert "date,mode,generation" in csv_content
    assert csv_content.count("DRY_RUN,2") == 3


def test_manual_close_pnl_is_attributed_to_original_wallet(db):
    now = datetime.now(timezone.utc)
    policy = get_or_create_live_policy(db)
    policy.mode = "DRY_RUN"
    policy.dry_run_generation = 2

    add_order(
        db,
        key="original-buy",
        side="BUY",
        token=TOKEN_A,
        value_sol=0.05,
        pnl_sol=0,
        when=now - timedelta(hours=2),
    )
    add_order(
        db,
        key="manual-close",
        side="SELL",
        token=TOKEN_A,
        value_sol=0.05,
        pnl_sol=-0.01,
        when=now - timedelta(hours=1),
        wallet="MANUAL_DRY_RUN_CLOSE",
    )
    db.commit()

    payload = build_live_trading_analytics(
        db,
        days=7,
        mode="DRY_RUN",
        generation=2,
        now=now,
    )

    assert len(payload["wallet_performance"]) == 1
    row = payload["wallet_performance"][0]
    assert row["source_wallet"] == WALLET
    assert row["orders"] == 2
    assert row["sells"] == 1
    assert row["realized_pnl_sol"] == pytest.approx(-0.01)
