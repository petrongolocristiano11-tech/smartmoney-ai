from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database.base import Base
from backend.app.models.live_position import LivePosition
from backend.app.models.live_risk_state import LiveRiskState
from backend.app.models.trade import Trade
from backend.app.services.live_trading_errors import LiveTradingError
from backend.app.services.live_trading_policy_service import get_or_create_live_policy
from backend.app.services.live_trading_risk_engine import build_live_execution_plan


WALLET = "W" * 32
TOKEN = "T" * 32


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


def policy_and_trade(db):
    policy = get_or_create_live_policy(db)
    policy.mode = "DRY_RUN"
    policy.source_wallets = [WALLET]
    policy.fixed_buy_size_sol = 0.05
    policy.max_order_size_sol = 0.1
    policy.max_daily_buy_sol = 0.5
    policy.max_total_exposure_sol = 0.5
    policy.max_token_exposure_sol = 0.1
    policy.max_open_positions = 1
    policy.max_daily_orders = 50
    db.commit()
    trade = Trade(
        signature="risk-buy",
        wallet_address=WALLET,
        side="BUY",
        token_mint=TOKEN,
        token_amount=1,
        sol_amount=0.2,
        success=True,
        block_time=datetime.now(timezone.utc),
    )
    db.add(trade)
    db.commit()
    return policy, trade


def test_loss_streak_cooldown_blocks_new_buy(db):
    policy, trade = policy_and_trade(db)
    db.add(
        LiveRiskState(
            mode="DRY_RUN",
            generation=1,
            starting_equity_sol=1,
            current_equity_sol=1,
            peak_equity_sol=1,
            loss_streak=3,
            cooldown_until=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
    )
    db.commit()

    with pytest.raises(LiveTradingError) as error:
        build_live_execution_plan(
            db,
            policy=policy,
            trade=trade,
            wallet_balance_sol=None,
        )
    assert error.value.code == "LOSS_STREAK_COOLDOWN"


def test_max_open_positions_blocks_new_token(db):
    policy, trade = policy_and_trade(db)
    db.add(
        LivePosition(
            mode="DRY_RUN",
            generation=1,
            token_mint="X" * 32,
            status="OPEN",
            quantity_raw=100,
            cost_basis_sol=0.05,
        )
    )
    db.commit()

    with pytest.raises(LiveTradingError) as error:
        build_live_execution_plan(
            db,
            policy=policy,
            trade=trade,
            wallet_balance_sol=None,
        )
    assert error.value.code == "MAX_OPEN_POSITIONS"


def test_policy_rejects_automatic_exits_when_sells_are_disabled(db):
    from backend.app.services.live_trading_policy_service import update_live_policy

    policy, _ = policy_and_trade(db)
    with pytest.raises(LiveTradingError) as error:
        update_live_policy(
            db,
            policy,
            {
                "automatic_exits_enabled": True,
                "sell_enabled": False,
            },
        )
    assert error.value.code == "AUTOMATIC_EXITS_REQUIRE_SELLS"


def test_policy_rejects_token_exposure_above_total_exposure(db):
    from backend.app.services.live_trading_policy_service import update_live_policy

    policy, _ = policy_and_trade(db)
    with pytest.raises(LiveTradingError) as error:
        update_live_policy(
            db,
            policy,
            {
                "max_token_exposure_sol": 0.6,
                "max_total_exposure_sol": 0.5,
            },
        )
    assert error.value.code == "INVALID_LIVE_TRADING_LIMITS"
