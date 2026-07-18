from datetime import (
    datetime,
    timezone,
)

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
from backend.app.models.trade import Trade
from backend.app.services.jupiter_swap_client import (
    JupiterOrderResult,
)
from backend.app.services.live_copy_trading_engine import (
    execute_source_trade,
)
from backend.app.services.live_trading_policy_service import (
    get_or_create_live_policy,
)


WALLET = "W" * 32
TOKEN = "T" * 32


class FakeJupiter:
    def get_order(
        self,
        **kwargs,
    ):
        amount = kwargs[
            "amount_raw"
        ]

        output = (
            2_000_000
            if kwargs[
                "input_mint"
            ].startswith(
                "So111"
            )
            else 40_000_000
        )

        return JupiterOrderResult(
            raw={
                "requestId":
                    "request-1",
                "transaction":
                    None,
                "inAmount":
                    str(amount),
                "outAmount":
                    str(output),
                "slippageBps":
                    20,
                "router":
                    "iris",
                "priceImpact":
                    0.1,
            },
            request_id="request-1",
            transaction=None,
            in_amount=amount,
            out_amount=output,
            slippage_bps=20,
            router="iris",
            price_impact_percent=0.1,
            last_valid_block_height=None,
        )


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


def configure_policy(
    db,
):
    policy = (
        get_or_create_live_policy(
            db
        )
    )

    policy.mode = "DRY_RUN"

    policy.source_wallets = [
        WALLET
    ]

    policy.fixed_buy_size_sol = 0.05
    policy.max_order_size_sol = 0.1
    policy.max_daily_buy_sol = 0.5
    policy.max_total_exposure_sol = 0.5
    policy.min_source_trade_sol = 0.01

    db.commit()

    return policy


def create_trade(
    db,
    *,
    signature="source-1",
    side="BUY",
):
    trade = Trade(
        signature=signature,
        wallet_address=WALLET,
        side=side,
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

    return trade


def test_dry_run_buy_is_idempotent_and_creates_position(
    db,
):
    configure_policy(
        db
    )

    trade = create_trade(
        db
    )

    first = execute_source_trade(
        db,
        trade=trade,
        jupiter_client=(
            FakeJupiter()
        ),
    )

    second = execute_source_trade(
        db,
        trade=trade,
        jupiter_client=(
            FakeJupiter()
        ),
    )

    assert first.status == "DRY_RUN"
    assert first.id == second.id

    assert (
        db.query(
            LivePosition
        ).count()
        == 1
    )

    position = (
        db.query(
            LivePosition
        ).one()
    )

    assert (
        position.mode
        == "DRY_RUN"
    )

    assert (
        int(
            position.quantity_raw
        )
        == 2_000_000
    )

    assert (
        position.cost_basis_sol
        == pytest.approx(0.05)
    )


def test_dry_run_sell_closes_half_and_records_pnl(
    db,
):
    configure_policy(
        db
    )

    buy = create_trade(
        db
    )

    execute_source_trade(
        db,
        trade=buy,
        jupiter_client=(
            FakeJupiter()
        ),
    )

    policy = (
        get_or_create_live_policy(
            db
        )
    )

    policy.sell_position_percentage = (
        50
    )

    db.commit()

    sell = create_trade(
        db,
        signature="source-2",
        side="SELL",
    )

    order = execute_source_trade(
        db,
        trade=sell,
        jupiter_client=(
            FakeJupiter()
        ),
    )

    position = (
        db.query(
            LivePosition
        ).one()
    )

    assert order.status == "DRY_RUN"

    assert (
        int(
            position.quantity_raw
        )
        == 1_000_000
    )

    assert (
        position.cost_basis_sol
        == pytest.approx(0.025)
    )

    assert (
        order.realized_pnl_sol
        == pytest.approx(0.015)
    ) 