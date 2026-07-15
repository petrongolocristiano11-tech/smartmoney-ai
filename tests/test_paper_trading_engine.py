import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import (
    Session,
    sessionmaker,
)
from sqlalchemy.pool import StaticPool

from backend.app.models.paper_account import (
    PaperAccount,
)
from backend.app.models.paper_order import (
    PaperOrder,
)
from backend.app.models.paper_position import (
    PaperPosition,
)
from backend.app.services.paper_trading_engine import (
    PaperTradingError,
    buy_paper_token,
    create_paper_account,
    get_paper_account_summary,
    mark_paper_position,
    sell_paper_token,
)


@pytest.fixture()
def db() -> Session:
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

    session = testing_session()

    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def make_account(
    db: Session,
    **overrides,
):
    values = {
        "name": "Main Paper Account",
        "starting_balance_sol": 10.0,
        "max_position_size_sol": 2.0,
        "max_open_positions": 3,
        "daily_loss_limit_sol": 1.0,
    }

    values.update(overrides)

    return create_paper_account(
        db=db,
        **values,
    )


def test_create_account_and_summary(
    db: Session,
):
    account = make_account(db)

    summary = (
        get_paper_account_summary(
            db,
            account.id,
        )
    )

    assert account.status == "ACTIVE"

    assert (
        summary["cash_balance_sol"]
        == pytest.approx(10.0)
    )

    assert (
        summary["equity_sol"]
        == pytest.approx(10.0)
    )

    assert summary["open_positions"] == 0


def test_buy_updates_account_and_position(
    db: Session,
):
    account = make_account(db)

    result = buy_paper_token(
        db=db,
        account_id=account.id,
        token_mint="TOKEN_A",
        value_sol=1.0,
        market_price_sol=0.1,
        slippage_percent=0,
        fee_percent=0,
        signal_score=80,
        reason="Strong signal",
    )

    position = result["position"]
    order = result["order"]

    assert order.status == "FILLED"
    assert order.side == "BUY"

    assert (
        position.quantity
        == pytest.approx(10.0)
    )

    assert (
        position.cost_basis_sol
        == pytest.approx(1.0)
    )

    assert (
        result["account"]
        .cash_balance_sol
        == pytest.approx(9.0)
    )


def test_buy_respects_max_position_size(
    db: Session,
):
    account = make_account(
        db,
        max_position_size_sol=0.5,
    )

    with pytest.raises(
        PaperTradingError
    ) as exception:
        buy_paper_token(
            db=db,
            account_id=account.id,
            token_mint="TOKEN_A",
            value_sol=1.0,
            market_price_sol=0.1,
            slippage_percent=0,
            fee_percent=0,
        )

    assert (
        exception.value.code
        == "MAX_POSITION_SIZE"
    )


def test_buy_respects_max_open_positions(
    db: Session,
):
    account = make_account(
        db,
        max_open_positions=1,
    )

    buy_paper_token(
        db=db,
        account_id=account.id,
        token_mint="TOKEN_A",
        value_sol=1.0,
        market_price_sol=0.1,
        slippage_percent=0,
        fee_percent=0,
    )

    with pytest.raises(
        PaperTradingError
    ) as exception:
        buy_paper_token(
            db=db,
            account_id=account.id,
            token_mint="TOKEN_B",
            value_sol=1.0,
            market_price_sol=0.1,
            slippage_percent=0,
            fee_percent=0,
        )

    assert (
        exception.value.code
        == "MAX_OPEN_POSITIONS"
    )


def test_mark_price_updates_unrealized_pnl(
    db: Session,
):
    account = make_account(db)

    buy_paper_token(
        db=db,
        account_id=account.id,
        token_mint="TOKEN_A",
        value_sol=1.0,
        market_price_sol=0.1,
        slippage_percent=0,
        fee_percent=0,
    )

    position = mark_paper_position(
        db=db,
        account_id=account.id,
        token_mint="TOKEN_A",
        market_price_sol=0.2,
    )

    assert (
        position.market_value_sol
        == pytest.approx(2.0)
    )

    assert (
        position.unrealized_pnl_sol
        == pytest.approx(1.0)
    )


def test_sell_closes_position_and_realizes_profit(
    db: Session,
):
    account = make_account(db)

    buy_paper_token(
        db=db,
        account_id=account.id,
        token_mint="TOKEN_A",
        value_sol=1.0,
        market_price_sol=0.1,
        slippage_percent=0,
        fee_percent=0,
    )

    result = sell_paper_token(
        db=db,
        account_id=account.id,
        token_mint="TOKEN_A",
        market_price_sol=0.2,
        slippage_percent=0,
        fee_percent=0,
    )

    assert (
        result["position"].status
        == "CLOSED"
    )

    assert (
        result["order"]
        .realized_pnl_sol
        == pytest.approx(1.0)
    )

    assert (
        result["account"]
        .realized_pnl_sol
        == pytest.approx(1.0)
    )

    assert (
        result["account"]
        .cash_balance_sol
        == pytest.approx(11.0)
    )


def test_partial_sell_keeps_position_open(
    db: Session,
):
    account = make_account(db)

    buy_paper_token(
        db=db,
        account_id=account.id,
        token_mint="TOKEN_A",
        value_sol=1.0,
        market_price_sol=0.1,
        slippage_percent=0,
        fee_percent=0,
    )

    result = sell_paper_token(
        db=db,
        account_id=account.id,
        token_mint="TOKEN_A",
        market_price_sol=0.2,
        quantity=5.0,
        slippage_percent=0,
        fee_percent=0,
    )

    assert (
        result["position"].status
        == "OPEN"
    )

    assert (
        result["position"].quantity
        == pytest.approx(5.0)
    )

    assert (
        result["position"]
        .cost_basis_sol
        == pytest.approx(0.5)
    )

    assert (
        result["order"]
        .realized_pnl_sol
        == pytest.approx(0.5)
    )


def test_daily_loss_limit_blocks_new_buy(
    db: Session,
):
    account = make_account(
        db,
        daily_loss_limit_sol=0.25,
    )

    buy_paper_token(
        db=db,
        account_id=account.id,
        token_mint="TOKEN_A",
        value_sol=1.0,
        market_price_sol=1.0,
        slippage_percent=0,
        fee_percent=0,
    )

    sell_paper_token(
        db=db,
        account_id=account.id,
        token_mint="TOKEN_A",
        market_price_sol=0.5,
        slippage_percent=0,
        fee_percent=0,
    )

    with pytest.raises(
        PaperTradingError
    ) as exception:
        buy_paper_token(
            db=db,
            account_id=account.id,
            token_mint="TOKEN_B",
            value_sol=0.5,
            market_price_sol=0.1,
            slippage_percent=0,
            fee_percent=0,
        )

    assert (
        exception.value.code
        == "DAILY_LOSS_LIMIT"
    )


def test_paused_account_cannot_buy(
    db: Session,
):
    account = make_account(db)

    account.status = "PAUSED"
    db.commit()

    with pytest.raises(
        PaperTradingError
    ) as exception:
        buy_paper_token(
            db=db,
            account_id=account.id,
            token_mint="TOKEN_A",
            value_sol=0.5,
            market_price_sol=0.1,
            slippage_percent=0,
            fee_percent=0,
        )

    assert (
        exception.value.code
        == "ACCOUNT_NOT_ACTIVE"
    ) 