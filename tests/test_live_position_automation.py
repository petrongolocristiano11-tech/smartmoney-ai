from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database.base import Base
from backend.app.models.live_copy_order import LiveCopyOrder
from backend.app.models.live_position import LivePosition
from backend.app.models.live_risk_state import LiveRiskState
from backend.app.models.trade import Trade
from backend.app.services.jupiter_swap_client import JupiterOrderResult
from backend.app.services.live_copy_trading_engine import execute_source_trade
from backend.app.services.live_position_automation_service import (
    evaluate_exit_reason,
    run_position_monitor_cycle,
)
from backend.app.services.live_trading_policy_service import get_or_create_live_policy


WALLET = "W" * 32
TOKEN = "T" * 32


class ExitJupiter:
    def get_order(self, **kwargs):
        input_is_sol = kwargs["input_mint"].startswith("So111")
        output = 2_000_000 if input_is_sol else 60_000_000
        return JupiterOrderResult(
            raw={
                "requestId": "exit-request",
                "transaction": None,
                "inAmount": str(kwargs["amount_raw"]),
                "outAmount": str(output),
                "slippageBps": 20,
                "router": "iris",
                "priceImpact": 0.1,
            },
            request_id="exit-request",
            transaction=None,
            in_amount=kwargs["amount_raw"],
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
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


def configure(db):
    policy = get_or_create_live_policy(db)
    policy.mode = "DRY_RUN"
    policy.source_wallets = [WALLET]
    policy.fixed_buy_size_sol = 0.05
    policy.max_order_size_sol = 0.1
    policy.max_daily_buy_sol = 0.5
    policy.max_total_exposure_sol = 0.5
    policy.max_token_exposure_sol = 0.2
    policy.max_open_positions = 5
    policy.max_daily_orders = 50
    policy.automatic_exits_enabled = True
    policy.take_profit_enabled = True
    policy.take_profit_percent = 10
    policy.stop_loss_enabled = True
    policy.stop_loss_percent = 15
    db.commit()
    return policy


def create_buy(db):
    trade = Trade(
        signature="auto-buy",
        wallet_address=WALLET,
        side="BUY",
        token_mint=TOKEN,
        token_amount=100,
        sol_amount=0.2,
        success=True,
        block_time=datetime.now(timezone.utc),
    )
    db.add(trade)
    db.commit()
    execute_source_trade(db, trade=trade, jupiter_client=ExitJupiter())
    return db.query(LivePosition).one()


def test_monitor_triggers_take_profit_and_closes_position(db):
    configure(db)
    position = create_buy(db)

    summary = run_position_monitor_cycle(db, jupiter_client=ExitJupiter())
    db.refresh(position)

    assert summary["positions_scanned"] == 1
    assert summary["exits_triggered"] == 1
    assert summary["exits_completed"] == 1
    assert position.status == "CLOSED"

    exit_order = (
        db.query(LiveCopyOrder)
        .filter(LiveCopyOrder.execution_origin == "AUTO_EXIT")
        .one()
    )
    assert exit_order.exit_reason == "TAKE_PROFIT"
    assert exit_order.status == "DRY_RUN"
    assert exit_order.realized_pnl_sol == pytest.approx(0.01)


def test_exit_priority_prefers_stop_loss(db):
    policy = configure(db)
    position = LivePosition(
        mode="DRY_RUN",
        generation=1,
        token_mint=TOKEN,
        status="OPEN",
        quantity_raw=100,
        cost_basis_sol=1.0,
        unrealized_roi_percent=-20,
        current_value_sol=0.8,
        high_watermark_roi_percent=30,
        trailing_stop_value_sol=0.9,
    )
    assert evaluate_exit_reason(position, policy) == "STOP_LOSS"


def test_risk_state_is_updated_after_auto_exit(db):
    configure(db)
    create_buy(db)
    run_position_monitor_cycle(db, jupiter_client=ExitJupiter())

    state = db.query(LiveRiskState).one()
    assert state.realized_pnl_sol == pytest.approx(0.01)
    assert state.current_equity_sol == pytest.approx(1.01)
    assert state.loss_streak == 0


def test_monitor_quotes_without_closing_when_automatic_exits_are_disabled(db):
    policy = configure(db)
    policy.automatic_exits_enabled = False
    db.commit()
    position = create_buy(db)

    summary = run_position_monitor_cycle(db, jupiter_client=ExitJupiter())
    db.refresh(position)

    assert summary["positions_scanned"] == 1
    assert summary["quotes_succeeded"] == 1
    assert summary["exits_triggered"] == 0
    assert summary["exits_completed"] == 0
    assert position.status == "OPEN"
    assert position.current_value_sol == pytest.approx(0.06)
    assert position.unrealized_pnl_sol == pytest.approx(0.01)
    assert position.unrealized_roi_percent == pytest.approx(20.0)
    assert summary["items"][0]["exit_reason"] == "TAKE_PROFIT"
    assert summary["items"][0]["status"] == "QUOTED"
