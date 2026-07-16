from datetime import (
    datetime,
    timedelta,
    timezone,
)

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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


@pytest.fixture()
def db():
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
        .create(bind=engine)
    )

    PaperAutopilotDecision.__table__.create(
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


def create_account(db):
    account = PaperAccount(
        name="Autopilot Account",
        status="ACTIVE",
        starting_balance_sol=10.0,
        cash_balance_sol=10.0,
        realized_pnl_sol=0.0,
        max_position_size_sol=0.5,
        max_open_positions=3,
        daily_loss_limit_sol=1.0,
    )

    db.add(account)
    db.commit()
    db.refresh(account)

    return account


def test_policy_has_final_safe_defaults(db):
    account = create_account(db)

    policy = PaperAutopilotPolicy(
        account_id=account.id,
    )

    db.add(policy)
    db.commit()
    db.refresh(policy)

    assert policy.status == "DISABLED"
    assert policy.min_signal_score == 75
    assert policy.min_evidence_score == 60
    assert policy.minimum_confidence == "HIGH"

    assert (
        policy.max_position_percent_of_equity
        == 5
    )

    assert (
        policy.max_total_exposure_percent
        == 40
    )

    assert policy.stop_loss_percent == 12
    assert policy.take_profit_percent == 25

    assert policy.trailing_stop_enabled is True
    assert policy.trailing_stop_percent == 8

    assert (
        "HIGH_RISK_WALLETS"
        in policy.blocked_risk_flags
    )

    assert (
        "So11111111111111111111111111111111111111112"
        in policy.excluded_token_mints
    )


def test_only_one_policy_per_account(db):
    account = create_account(db)

    db.add(
        PaperAutopilotPolicy(
            account_id=account.id,
        )
    )

    db.commit()

    db.add(
        PaperAutopilotPolicy(
            account_id=account.id,
        )
    )

    with pytest.raises(
        IntegrityError
    ):
        db.commit()

    db.rollback()


def test_complete_autopilot_audit_cycle(db):
    account = create_account(db)

    policy = PaperAutopilotPolicy(
        account_id=account.id,
        status="ENABLED",
    )

    db.add(policy)
    db.commit()
    db.refresh(policy)

    run = PaperAutopilotRun(
        account_id=account.id,
        policy_id=policy.id,
        trigger="MANUAL",
        status="RUNNING",
    )

    db.add(run)
    db.commit()
    db.refresh(run)

    position = PaperPosition(
        account_id=account.id,
        token_mint="TOKEN_AUTOPILOT",
        status="OPEN",
        quantity=10.0,
        average_entry_price_sol=0.1,
        cost_basis_sol=1.0,
        last_price_sol=0.1,
        market_value_sol=1.0,
        unrealized_pnl_sol=0.0,
        realized_pnl_sol=0.0,
    )

    db.add(position)
    db.commit()
    db.refresh(position)

    order = PaperOrder(
        account_id=account.id,
        position_id=position.id,
        token_mint="TOKEN_AUTOPILOT",
        side="BUY",
        status="FILLED",
        requested_value_sol=1.0,
        quantity=10.0,
        execution_price_sol=0.1,
        gross_value_sol=1.0,
        fee_sol=0.0,
        slippage_percent=0.0,
        realized_pnl_sol=0.0,
        signal_score=85.0,
        reason="Autopilot test",
        executed_at=datetime.now(
            timezone.utc
        ),
    )

    db.add(order)
    db.commit()
    db.refresh(order)

    managed = (
        PaperAutopilotManagedPosition(
            account_id=account.id,
            paper_position_id=position.id,
            entry_order_id=order.id,
            entry_run_id=run.id,
            token_mint="TOKEN_AUTOPILOT",
            status="ACTIVE",
            entry_price_sol=0.1,
            peak_price_sol=0.1,
            stop_loss_price_sol=0.088,
            take_profit_price_sol=0.125,
            trailing_stop_enabled=True,
            trailing_stop_percent=8.0,
            entry_signal_score=85.0,
            entry_evidence_score=75.0,
            entry_confidence="HIGH",
            max_holding_until=(
                datetime.now(
                    timezone.utc
                )
                + timedelta(hours=72)
            ),
        )
    )

    db.add(managed)
    db.commit()
    db.refresh(managed)

    decision = PaperAutopilotDecision(
        run_id=run.id,
        account_id=account.id,
        managed_position_id=managed.id,
        paper_position_id=position.id,
        paper_order_id=order.id,
        token_mint="TOKEN_AUTOPILOT",
        action="BUY",
        reason_code="SIGNAL_ACCEPTED",
        reason=(
            "Segnale conforme alla "
            "politica Autopilot."
        ),
        signal_score=85.0,
        evidence_score=75.0,
        buyers=4,
        confidence="HIGH",
        market_price_sol=0.1,
        quantity=10.0,
        value_sol=1.0,
        signal_snapshot={
            "signal_score": 85.0,
            "evidence_score": 75.0,
        },
    )

    db.add(decision)

    run.status = "COMPLETED"
    run.signals_evaluated = 1
    run.entries_opened = 1
    run.decisions_count = 1
    run.finished_at = datetime.now(
        timezone.utc
    )

    db.commit()

    assert managed.status == "ACTIVE"
    assert managed.entry_order_id == order.id
    assert decision.action == "BUY"
    assert decision.reason_code == (
        "SIGNAL_ACCEPTED"
    )
    assert run.status == "COMPLETED"


def test_invalid_policy_status_is_rejected(db):
    account = create_account(db)

    policy = PaperAutopilotPolicy(
        account_id=account.id,
        status="INVALID",
    )

    db.add(policy)

    with pytest.raises(
        IntegrityError
    ):
        db.commit()

    db.rollback() 