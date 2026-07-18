from datetime import (
    datetime,
    timezone,
)
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import (
    sessionmaker,
)
from sqlalchemy.pool import StaticPool

from backend.app.database.base import Base
from backend.app.models.live_position import (
    LivePosition,
)
from backend.app.models.live_trading_policy import (
    LiveTradingPolicy,
)
from backend.app.models.trade import Trade
from backend.app.services.live_trading_errors import (
    LiveTradingError,
)
from backend.app.services.live_trading_risk_engine import (
    build_live_execution_plan,
)


WALLET = "W" * 32
TOKEN = "T" * 32


@pytest.fixture()
def db():
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

    yield session

    session.close()
    engine.dispose()


def make_policy(
    **overrides,
):
    values = {
        "name": "default",
        "mode": "DRY_RUN",
        "source_wallets": [
            WALLET
        ],
        "fixed_buy_size_sol": 0.05,
        "max_order_size_sol": 0.1,
        "max_daily_buy_sol": 0.5,
        "max_total_exposure_sol": 0.5,
        "min_source_trade_sol": 0.01,
    }

    values.update(
        overrides
    )

    return LiveTradingPolicy(
        **values
    )


def make_trade(
    side="BUY",
):
    return Trade(
        signature=f"sig-{side}",
        wallet_address=WALLET,
        side=side,
        token_mint=TOKEN,
        token_amount=10,
        sol_amount=0.2,
        success=True,
        block_time=datetime.now(
            timezone.utc
        ),
    )


def test_fixed_buy_plan_uses_lamports(
    db,
):
    policy = make_policy()
    trade = make_trade()

    db.add_all(
        [
            policy,
            trade,
        ]
    )

    db.commit()

    plan = build_live_execution_plan(
        db,
        policy=policy,
        trade=trade,
        wallet_balance_sol=None,
    )

    assert plan.side == "BUY"

    assert (
        plan.input_amount_raw
        == 50_000_000
    )

    assert (
        plan.requested_value_sol
        == pytest.approx(0.05)
    )


def test_wallet_outside_allowlist_is_rejected(
    db,
):
    policy = make_policy(
        source_wallets=[
            "A" * 32
        ]
    )

    trade = make_trade()

    db.add_all(
        [
            policy,
            trade,
        ]
    )

    db.commit()

    with pytest.raises(
        LiveTradingError
    ) as exception:
        build_live_execution_plan(
            db,
            policy=policy,
            trade=trade,
            wallet_balance_sol=None,
        )

    assert (
        exception.value.code
        == "SOURCE_WALLET_NOT_ALLOWED"
    )


def test_sell_uses_only_position_in_current_mode(
    db,
):
    policy = make_policy(
        sell_position_percentage=50
    )

    trade = make_trade(
        "SELL"
    )

    db.add_all(
        [
            policy,
            trade,
            LivePosition(
                mode="LIVE",
                token_mint=TOKEN,
                status="OPEN",
                quantity_raw=(
                    Decimal(999)
                ),
                cost_basis_sol=1,
            ),
            LivePosition(
                mode="DRY_RUN",
                token_mint=TOKEN,
                status="OPEN",
                quantity_raw=(
                    Decimal(1000)
                ),
                cost_basis_sol=0.4,
            ),
        ]
    )

    db.commit()

    plan = build_live_execution_plan(
        db,
        policy=policy,
        trade=trade,
        wallet_balance_sol=None,
    )

    assert (
        plan.input_amount_raw
        == 500
    )

    assert (
        plan.requested_value_sol
        == pytest.approx(0.2)
    ) 