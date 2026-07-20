from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database.base import Base
from backend.app.models.live_copy_order import LiveCopyOrder
from backend.app.services.live_risk_state_service import (
    refresh_risk_state,
    reset_risk_cooldown,
)
from backend.app.services.live_trading_policy_service import (
    get_or_create_live_policy,
)


WALLET = "W" * 32
TOKEN = "T" * 32
SOL = "So11111111111111111111111111111111111111112"


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


def add_sell(
    db,
    *,
    index: int,
    pnl: float,
    executed_at: datetime,
    origin: str = "MANUAL_CLOSE",
):
    order = LiveCopyOrder(
        idempotency_key=f"risk-history-{index:02d}".ljust(64, "0"),
        source_trade_id=None,
        source_signature=f"risk-history-signature-{index}",
        source_wallet=WALLET,
        source_side="SELL",
        source_token_mint=TOKEN,
        execution_origin=origin,
        exit_reason=origin,
        mode="DRY_RUN",
        generation=1,
        status="DRY_RUN",
        input_mint=TOKEN,
        output_mint=SOL,
        requested_input_amount_raw=Decimal(100),
        requested_value_sol=0.01,
        actual_input_amount_raw=Decimal(100),
        actual_output_amount_raw=Decimal(10_000_000),
        slippage_bps=50,
        realized_pnl_sol=pnl,
        executed_at=executed_at,
    )
    db.add(order)
    db.commit()
    return order


def configure_policy(db):
    policy = get_or_create_live_policy(db)
    policy.mode = "DRY_RUN"
    policy.loss_streak_cooldown_threshold = 3
    policy.cooldown_after_loss_minutes = 30
    policy.max_portfolio_drawdown_percent = 20
    db.commit()
    return policy


def test_historical_manual_closes_rebuild_three_loss_streak(db):
    policy = configure_policy(db)
    now = datetime.now(timezone.utc)
    add_sell(db, index=1, pnl=-0.001, executed_at=now - timedelta(days=3))
    add_sell(db, index=2, pnl=-0.002, executed_at=now - timedelta(days=2))
    latest = add_sell(
        db,
        index=3,
        pnl=-0.003,
        executed_at=now - timedelta(days=1),
    )

    state = refresh_risk_state(
        db,
        mode="DRY_RUN",
        generation=1,
        now=now,
        policy=policy,
        commit=True,
    )

    assert state.loss_streak == 3
    assert state.realized_pnl_sol == pytest.approx(-0.006)
    assert state.last_loss_at.replace(tzinfo=timezone.utc) == latest.executed_at
    assert state.cooldown_until is None
    assert state.blocked_reason is None


def test_recent_third_loss_activates_cooldown(db):
    policy = configure_policy(db)
    now = datetime.now(timezone.utc)
    add_sell(db, index=1, pnl=-0.001, executed_at=now - timedelta(minutes=15))
    add_sell(db, index=2, pnl=-0.002, executed_at=now - timedelta(minutes=10))
    add_sell(db, index=3, pnl=-0.003, executed_at=now - timedelta(minutes=5))

    state = refresh_risk_state(
        db,
        mode="DRY_RUN",
        generation=1,
        now=now,
        policy=policy,
        commit=True,
    )

    assert state.loss_streak == 3
    cooldown_until = state.cooldown_until.replace(tzinfo=timezone.utc)
    assert abs(cooldown_until - (now + timedelta(minutes=25))) < timedelta(seconds=1)
    assert state.blocked_reason == "COOLDOWN_LOSS_STREAK: 3 perdite consecutive"


def test_profitable_sell_resets_consecutive_streak(db):
    policy = configure_policy(db)
    now = datetime.now(timezone.utc)
    add_sell(db, index=1, pnl=-0.001, executed_at=now - timedelta(minutes=20))
    add_sell(db, index=2, pnl=-0.002, executed_at=now - timedelta(minutes=15))
    add_sell(db, index=3, pnl=0.004, executed_at=now - timedelta(minutes=10))

    state = refresh_risk_state(
        db,
        mode="DRY_RUN",
        generation=1,
        now=now,
        policy=policy,
        commit=True,
    )

    assert state.loss_streak == 0
    assert state.cooldown_until is None
    assert state.last_loss_at is not None


def test_manual_reset_ignores_old_sells_but_counts_new_ones(db):
    policy = configure_policy(db)
    now = datetime.now(timezone.utc)
    add_sell(db, index=1, pnl=-0.001, executed_at=now - timedelta(minutes=20))
    add_sell(db, index=2, pnl=-0.002, executed_at=now - timedelta(minutes=15))
    add_sell(db, index=3, pnl=-0.003, executed_at=now - timedelta(minutes=10))

    state = refresh_risk_state(
        db,
        mode="DRY_RUN",
        generation=1,
        now=now,
        policy=policy,
        commit=True,
    )
    assert state.loss_streak == 3

    reset = reset_risk_cooldown(
        db,
        mode="DRY_RUN",
        generation=1,
    )
    assert reset.loss_streak == 0
    assert reset.loss_streak_reset_at is not None

    refreshed = refresh_risk_state(
        db,
        mode="DRY_RUN",
        generation=1,
        now=now + timedelta(seconds=1),
        policy=policy,
        commit=True,
    )
    assert refreshed.loss_streak == 0

    add_sell(
        db,
        index=4,
        pnl=-0.004,
        executed_at=now + timedelta(seconds=2),
        origin="AUTO_EXIT",
    )
    refreshed = refresh_risk_state(
        db,
        mode="DRY_RUN",
        generation=1,
        now=now + timedelta(seconds=3),
        policy=policy,
        commit=True,
    )
    assert refreshed.loss_streak == 1
