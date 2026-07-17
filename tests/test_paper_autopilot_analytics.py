from datetime import (
    datetime,
    timedelta,
    timezone,
)
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.api.paper_autopilot import router
from backend.app.core.config import settings
from backend.app.database.session import get_db
from backend.app.models.paper_account import PaperAccount
from backend.app.models.paper_autopilot import (
    PaperAutopilotDecision,
    PaperAutopilotManagedPosition,
    PaperAutopilotPolicy,
    PaperAutopilotRun,
)
from backend.app.models.paper_order import PaperOrder
from backend.app.models.paper_position import PaperPosition
from backend.app.services.paper_autopilot_analytics import (
    build_paper_autopilot_analytics,
    calculate_health,
)


PAPER_KEY = "p" * 40

NOW = datetime(
    2026,
    7,
    17,
    12,
    0,
    tzinfo=timezone.utc,
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
    (
        PaperAutopilotDecision
        .__table__
        .create(bind=engine)
    )

    session_factory = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    session: Session = session_factory()

    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def create_account(
    db: Session,
    *,
    name: str = "Analytics Account",
) -> PaperAccount:
    account = PaperAccount(
        name=name,
        status="ACTIVE",
        starting_balance_sol=10.0,
        cash_balance_sol=8.0,
        realized_pnl_sol=0.0,
        max_position_size_sol=2.0,
        max_open_positions=5,
        daily_loss_limit_sol=2.0,
    )

    db.add(account)
    db.commit()
    db.refresh(account)

    return account


def create_policy(
    db: Session,
    account_id: int,
    *,
    status: str = "ENABLED",
) -> PaperAutopilotPolicy:
    policy = PaperAutopilotPolicy(
        account_id=account_id,
        status=status,
    )

    db.add(policy)
    db.commit()
    db.refresh(policy)

    return policy


def create_run(
    db: Session,
    *,
    account_id: int,
    policy_id: int,
    status: str,
    started_at: datetime,
    signals_evaluated: int = 0,
    entries_opened: int = 0,
    exits_closed: int = 0,
    decisions_count: int = 0,
    errors_count: int = 0,
    error_message: str | None = None,
) -> PaperAutopilotRun:
    run = PaperAutopilotRun(
        account_id=account_id,
        policy_id=policy_id,
        trigger="AUTOMATION",
        status=status,
        signals_evaluated=(
            signals_evaluated
        ),
        entries_opened=entries_opened,
        exits_closed=exits_closed,
        decisions_count=decisions_count,
        errors_count=errors_count,
        error_message=error_message,
        started_at=started_at,
        finished_at=(
            started_at
            + timedelta(minutes=2)
            if status != "RUNNING"
            else None
        ),
    )

    db.add(run)
    db.commit()
    db.refresh(run)

    return run


def create_decision(
    db: Session,
    *,
    run_id: int,
    account_id: int,
    action: str,
    reason_code: str,
    created_at: datetime,
    token_mint: str,
) -> PaperAutopilotDecision:
    decision = PaperAutopilotDecision(
        run_id=run_id,
        account_id=account_id,
        token_mint=token_mint,
        action=action,
        reason_code=reason_code,
        reason=f"Decisione {reason_code}",
        created_at=created_at,
    )

    db.add(decision)
    db.commit()
    db.refresh(decision)

    return decision


def create_position(
    db: Session,
    *,
    account_id: int,
    token_mint: str,
    status: str,
    opened_at: datetime,
    closed_at: datetime | None = None,
    cost_basis_sol: float = 0.0,
    market_value_sol: float = 0.0,
    unrealized_pnl_sol: float = 0.0,
) -> PaperPosition:
    position = PaperPosition(
        account_id=account_id,
        token_mint=token_mint,
        status=status,
        quantity=10.0,
        average_entry_price_sol=0.1,
        cost_basis_sol=cost_basis_sol,
        last_price_sol=(
            market_value_sol / 10.0
            if market_value_sol > 0
            else 0.1
        ),
        market_value_sol=market_value_sol,
        unrealized_pnl_sol=(
            unrealized_pnl_sol
        ),
        realized_pnl_sol=0.0,
        opened_at=opened_at,
        closed_at=closed_at,
    )

    db.add(position)
    db.commit()
    db.refresh(position)

    return position


def create_order(
    db: Session,
    *,
    account_id: int,
    position_id: int,
    token_mint: str,
    side: str,
    executed_at: datetime,
    gross_value_sol: float,
    fee_sol: float = 0.0,
    realized_pnl_sol: float = 0.0,
) -> PaperOrder:
    order = PaperOrder(
        account_id=account_id,
        position_id=position_id,
        token_mint=token_mint,
        side=side,
        status="FILLED",
        requested_value_sol=(
            gross_value_sol
        ),
        quantity=10.0,
        execution_price_sol=0.1,
        gross_value_sol=gross_value_sol,
        fee_sol=fee_sol,
        slippage_percent=0.0,
        realized_pnl_sol=(
            realized_pnl_sol
        ),
        executed_at=executed_at,
    )

    db.add(order)
    db.commit()
    db.refresh(order)

    return order


def create_managed_position(
    db: Session,
    *,
    account_id: int,
    paper_position_id: int,
    entry_order_id: int,
    entry_run_id: int,
    token_mint: str,
    opened_at: datetime,
    status: str,
    exit_order_id: int | None = None,
    exit_run_id: int | None = None,
    closed_at: datetime | None = None,
    exit_reason: str | None = None,
    entry_signal_score: float = 80.0,
) -> PaperAutopilotManagedPosition:
    managed_position = (
        PaperAutopilotManagedPosition(
            account_id=account_id,
            paper_position_id=(
                paper_position_id
            ),
            entry_order_id=entry_order_id,
            exit_order_id=exit_order_id,
            entry_run_id=entry_run_id,
            exit_run_id=exit_run_id,
            token_mint=token_mint,
            status=status,
            entry_price_sol=0.1,
            peak_price_sol=0.15,
            stop_loss_price_sol=0.08,
            take_profit_price_sol=0.13,
            trailing_stop_enabled=True,
            trailing_stop_percent=8.0,
            entry_signal_score=(
                entry_signal_score
            ),
            entry_evidence_score=70.0,
            entry_confidence="HIGH",
            exit_reason=exit_reason,
            max_holding_until=(
                opened_at
                + timedelta(hours=72)
            ),
            opened_at=opened_at,
            closed_at=closed_at,
        )
    )

    db.add(managed_position)
    db.commit()
    db.refresh(managed_position)

    return managed_position


def test_empty_analytics_returns_safe_zero_values(
    db,
):
    account = create_account(db)

    analytics = (
        build_paper_autopilot_analytics(
            db,
            account.id,
            days=7,
            now=NOW,
        )
    )

    assert analytics["account_id"] == account.id
    assert analytics["account_name"] == account.name
    assert analytics["window"]["days"] == 7

    assert analytics["health"] == {
        "status": "DISABLED",
        "policy_status": "DISABLED",
        "last_run_status": None,
        "last_run_at": None,
        "hours_since_last_run": None,
        "last_error_message": None,
    }

    assert analytics["runs"]["total_runs"] == 0
    assert (
        analytics["runs"]
        ["operational_success_rate_percent"]
        == 0.0
    )
    assert (
        analytics["decisions"]
        ["total_decisions"]
        == 0
    )
    assert (
        analytics["trading"]
        ["closed_trades"]
        == 0
    )
    assert (
        analytics["open_positions"]
        ["active_managed_positions"]
        == 0
    )
    assert analytics["decision_reasons"] == []
    assert analytics["exit_reasons"] == []
    assert analytics["recent_closed_trades"] == []

    assert len(analytics["daily"]) == 7
    assert all(
        row["runs"] == 0
        and row["decisions"] == 0
        and row["realized_pnl_sol"] == 0.0
        for row in analytics["daily"]
    )


def test_analytics_aggregates_operational_and_trading_metrics(
    db,
):
    account = create_account(db)
    policy = create_policy(
        db,
        account.id,
        status="ENABLED",
    )

    completed_run = create_run(
        db,
        account_id=account.id,
        policy_id=policy.id,
        status="COMPLETED",
        started_at=(
            NOW - timedelta(days=2)
        ),
        signals_evaluated=10,
        entries_opened=2,
        exits_closed=0,
        decisions_count=5,
        errors_count=0,
    )

    partial_run = create_run(
        db,
        account_id=account.id,
        policy_id=policy.id,
        status="PARTIAL",
        started_at=(
            NOW - timedelta(days=1)
        ),
        signals_evaluated=6,
        entries_opened=1,
        exits_closed=1,
        decisions_count=4,
        errors_count=1,
    )

    failed_run = create_run(
        db,
        account_id=account.id,
        policy_id=policy.id,
        status="FAILED",
        started_at=(
            NOW - timedelta(hours=3)
        ),
        signals_evaluated=2,
        decisions_count=1,
        errors_count=2,
        error_message="Oracle unavailable",
    )

    skipped_run = create_run(
        db,
        account_id=account.id,
        policy_id=policy.id,
        status="SKIPPED",
        started_at=(
            NOW - timedelta(hours=2)
        ),
        decisions_count=1,
    )

    running_run = create_run(
        db,
        account_id=account.id,
        policy_id=policy.id,
        status="RUNNING",
        started_at=(
            NOW - timedelta(hours=1)
        ),
        signals_evaluated=1,
    )

    decisions = [
        (
            completed_run,
            "BUY",
            "ENTRY_ACCEPTED",
            NOW - timedelta(days=2),
        ),
        (
            completed_run,
            "BUY",
            "ENTRY_ACCEPTED",
            NOW - timedelta(days=2),
        ),
        (
            completed_run,
            "SKIP",
            "RISK_BLOCKED",
            NOW - timedelta(days=2),
        ),
        (
            partial_run,
            "SELL",
            "TAKE_PROFIT",
            NOW - timedelta(days=1),
        ),
        (
            partial_run,
            "HOLD",
            "POSITION_HELD",
            NOW - timedelta(days=1),
        ),
        (
            failed_run,
            "ERROR",
            "ORACLE_ERROR",
            NOW - timedelta(hours=3),
        ),
        (
            skipped_run,
            "SKIP",
            "RISK_BLOCKED",
            NOW - timedelta(hours=2),
        ),
    ]

    for index, (
        run,
        action,
        reason_code,
        created_at,
    ) in enumerate(decisions, start=1):
        create_decision(
            db,
            run_id=run.id,
            account_id=account.id,
            action=action,
            reason_code=reason_code,
            created_at=created_at,
            token_mint=f"DecisionToken{index}",
        )

    closed_trade_specs = [
        {
            "token_mint": "WinnerToken",
            "opened_at": (
                NOW
                - timedelta(
                    days=2,
                    hours=10,
                )
            ),
            "closed_at": (
                NOW - timedelta(days=2)
            ),
            "realized_pnl": 0.3,
            "invested_sol": 1.0,
            "exit_reason": "TAKE_PROFIT",
            "entry_run": completed_run,
            "exit_run": completed_run,
            "signal_score": 92.0,
        },
        {
            "token_mint": "LoserToken",
            "opened_at": (
                NOW
                - timedelta(
                    days=1,
                    hours=20,
                )
            ),
            "closed_at": (
                NOW - timedelta(days=1)
            ),
            "realized_pnl": -0.1,
            "invested_sol": 0.5,
            "exit_reason": "STOP_LOSS",
            "entry_run": completed_run,
            "exit_run": partial_run,
            "signal_score": 81.0,
        },
        {
            "token_mint": "FlatToken",
            "opened_at": (
                NOW - timedelta(hours=34)
            ),
            "closed_at": (
                NOW - timedelta(hours=4)
            ),
            "realized_pnl": 0.0,
            "invested_sol": 0.25,
            "exit_reason": "MANUAL_EXIT",
            "entry_run": partial_run,
            "exit_run": failed_run,
            "signal_score": 75.0,
        },
    ]

    for spec in closed_trade_specs:
        position = create_position(
            db,
            account_id=account.id,
            token_mint=spec["token_mint"],
            status="CLOSED",
            opened_at=spec["opened_at"],
            closed_at=spec["closed_at"],
            cost_basis_sol=0.0,
            market_value_sol=0.0,
        )

        entry_order = create_order(
            db,
            account_id=account.id,
            position_id=position.id,
            token_mint=spec["token_mint"],
            side="BUY",
            executed_at=spec["opened_at"],
            gross_value_sol=spec["invested_sol"],
        )

        exit_order = create_order(
            db,
            account_id=account.id,
            position_id=position.id,
            token_mint=spec["token_mint"],
            side="SELL",
            executed_at=spec["closed_at"],
            gross_value_sol=(
                spec["invested_sol"]
                + spec["realized_pnl"]
            ),
            realized_pnl_sol=(
                spec["realized_pnl"]
            ),
        )

        create_managed_position(
            db,
            account_id=account.id,
            paper_position_id=position.id,
            entry_order_id=entry_order.id,
            exit_order_id=exit_order.id,
            entry_run_id=(
                spec["entry_run"].id
            ),
            exit_run_id=(
                spec["exit_run"].id
            ),
            token_mint=spec["token_mint"],
            opened_at=spec["opened_at"],
            closed_at=spec["closed_at"],
            status="CLOSED",
            exit_reason=spec["exit_reason"],
            entry_signal_score=(
                spec["signal_score"]
            ),
        )

    active_position = create_position(
        db,
        account_id=account.id,
        token_mint="ActiveToken",
        status="OPEN",
        opened_at=(
            NOW - timedelta(hours=6)
        ),
        cost_basis_sol=1.2,
        market_value_sol=1.5,
        unrealized_pnl_sol=0.3,
    )

    active_entry_order = create_order(
        db,
        account_id=account.id,
        position_id=active_position.id,
        token_mint="ActiveToken",
        side="BUY",
        executed_at=(
            NOW - timedelta(hours=6)
        ),
        gross_value_sol=1.2,
    )

    create_managed_position(
        db,
        account_id=account.id,
        paper_position_id=active_position.id,
        entry_order_id=active_entry_order.id,
        entry_run_id=partial_run.id,
        token_mint="ActiveToken",
        opened_at=(
            NOW - timedelta(hours=6)
        ),
        status="ACTIVE",
    )

    analytics = (
        build_paper_autopilot_analytics(
            db,
            account.id,
            days=4,
            now=NOW,
        )
    )

    assert analytics["health"]["status"] == "HEALTHY"
    assert (
        analytics["health"]
        ["last_run_status"]
        == running_run.status
    )
    assert (
        analytics["health"]
        ["hours_since_last_run"]
        == 1.0
    )

    assert analytics["runs"] == {
        "total_runs": 5,
        "completed_runs": 1,
        "partial_runs": 1,
        "failed_runs": 1,
        "skipped_runs": 1,
        "running_runs": 1,
        "operational_success_rate_percent": 66.6667,
        "signals_evaluated": 19,
        "entries_opened": 3,
        "exits_closed": 1,
        "decisions_recorded": 11,
        "errors_recorded": 3,
    }

    assert analytics["decisions"] == {
        "total_decisions": 7,
        "buy_decisions": 2,
        "sell_decisions": 1,
        "hold_decisions": 1,
        "skip_decisions": 2,
        "error_decisions": 1,
        "entry_acceptance_rate_percent": 40.0,
    }

    assert analytics["trading"] == {
        "closed_trades": 3,
        "winning_trades": 1,
        "losing_trades": 1,
        "breakeven_trades": 1,
        "win_rate_percent": 33.3333,
        "net_realized_pnl_sol": 0.2,
        "gross_profit_sol": 0.3,
        "gross_loss_sol": 0.1,
        "profit_factor": 3.0,
        "average_trade_pnl_sol": (
            0.06666667
        ),
        "best_trade_pnl_sol": 0.3,
        "worst_trade_pnl_sol": -0.1,
        "average_holding_hours": 20.0,
    }

    assert analytics["open_positions"] == {
        "active_managed_positions": 1,
        "cost_basis_sol": 1.2,
        "market_value_sol": 1.5,
        "unrealized_pnl_sol": 0.3,
    }

    decision_breakdown = {
        row["code"]: (
            row["count"],
            row["percentage"],
        )
        for row in analytics[
            "decision_reasons"
        ]
    }

    assert decision_breakdown == {
        "ENTRY_ACCEPTED": (2, 28.5714),
        "RISK_BLOCKED": (2, 28.5714),
        "TAKE_PROFIT": (1, 14.2857),
        "POSITION_HELD": (1, 14.2857),
        "ORACLE_ERROR": (1, 14.2857),
    }

    exit_breakdown = {
        row["code"]: row["count"]
        for row in analytics[
            "exit_reasons"
        ]
    }

    assert exit_breakdown == {
        "MANUAL_EXIT": 1,
        "STOP_LOSS": 1,
        "TAKE_PROFIT": 1,
    }

    recent_trades = analytics[
        "recent_closed_trades"
    ]

    assert [
        trade["token_mint"]
        for trade in recent_trades
    ] == [
        "FlatToken",
        "LoserToken",
        "WinnerToken",
    ]

    assert (
        recent_trades[0]
        ["return_percent"]
        == 0.0
    )
    assert (
        recent_trades[1]
        ["return_percent"]
        == -20.0
    )
    assert (
        recent_trades[2]
        ["return_percent"]
        == 30.0
    )

    daily = {
        row["date"]: row
        for row in analytics["daily"]
    }

    assert len(daily) == 4
    assert (
        daily[NOW.date() - timedelta(days=2)]
        ["realized_pnl_sol"]
        == 0.3
    )
    assert (
        daily[NOW.date() - timedelta(days=1)]
        ["realized_pnl_sol"]
        == -0.1
    )
    assert (
        daily[NOW.date()]
        ["cumulative_realized_pnl_sol"]
        == 0.2
    )


def test_analytics_excludes_records_outside_window(
    db,
):
    account = create_account(db)
    policy = create_policy(
        db,
        account.id,
    )

    old_run = create_run(
        db,
        account_id=account.id,
        policy_id=policy.id,
        status="COMPLETED",
        started_at=(
            NOW - timedelta(days=10)
        ),
        signals_evaluated=50,
        entries_opened=5,
        decisions_count=5,
    )

    create_decision(
        db,
        run_id=old_run.id,
        account_id=account.id,
        action="BUY",
        reason_code="OLD_DECISION",
        created_at=(
            NOW - timedelta(days=10)
        ),
        token_mint="OldToken",
    )

    analytics = (
        build_paper_autopilot_analytics(
            db,
            account.id,
            days=3,
            now=NOW,
        )
    )

    assert analytics["runs"]["total_runs"] == 0
    assert (
        analytics["runs"]
        ["signals_evaluated"]
        == 0
    )
    assert (
        analytics["decisions"]
        ["total_decisions"]
        == 0
    )
    assert analytics["decision_reasons"] == []

    assert analytics["health"]["status"] == "STALE"
    assert (
        analytics["health"]
        ["last_run_status"]
        == "COMPLETED"
    )
    assert (
        analytics["health"]
        ["hours_since_last_run"]
        == 240.0
    )


@pytest.mark.parametrize(
    (
        "policy_status",
        "run_status",
        "run_age_hours",
        "expected_status",
    ),
    [
        (
            "DISABLED",
            None,
            None,
            "DISABLED",
        ),
        (
            "ENABLED",
            None,
            None,
            "STALE",
        ),
        (
            "ENABLED",
            "COMPLETED",
            1.0,
            "HEALTHY",
        ),
        (
            "ENABLED",
            "COMPLETED",
            3.0,
            "STALE",
        ),
        (
            "ENABLED",
            "FAILED",
            0.5,
            "ERROR",
        ),
    ],
)
def test_health_statuses(
    policy_status,
    run_status,
    run_age_hours,
    expected_status,
):
    policy = SimpleNamespace(
        status=policy_status
    )

    latest_run = None

    if run_status is not None:
        latest_run = SimpleNamespace(
            status=run_status,
            started_at=(
                NOW
                - timedelta(
                    hours=run_age_hours
                )
            ),
            error_message=(
                "Failure"
                if run_status == "FAILED"
                else None
            ),
        )

    health = calculate_health(
        policy=policy,
        latest_run=latest_run,
        now=NOW,
    )

    assert health["status"] == expected_status


@pytest.fixture()
def api_client(
    db,
    monkeypatch,
):
    monkeypatch.setattr(
        settings,
        "PAPER_TRADING_API_KEY",
        PAPER_KEY,
    )

    account = create_account(
        db,
        name="Analytics API Account",
    )

    app = FastAPI()
    app.include_router(router)

    def override_get_db():
        yield db

    app.dependency_overrides[
        get_db
    ] = override_get_db

    with TestClient(app) as client:
        yield client, account


def paper_headers():
    return {
        "X-Paper-Trading-Key": PAPER_KEY,
    }


def test_analytics_endpoint_requires_access_key(
    api_client,
):
    client, account = api_client

    response = client.get(
        (
            "/paper-autopilot/"
            f"accounts/{account.id}/"
            "analytics"
        )
    )

    assert response.status_code == 401


def test_analytics_endpoint_returns_valid_response(
    api_client,
):
    client, account = api_client

    response = client.get(
        (
            "/paper-autopilot/"
            f"accounts/{account.id}/"
            "analytics?days=7"
        ),
        headers=paper_headers(),
    )

    assert response.status_code == 200

    payload = response.json()

    assert payload["account_id"] == account.id
    assert payload["account_name"] == account.name
    assert payload["window"]["days"] == 7
    assert len(payload["daily"]) == 7
    assert payload["health"]["status"] == "DISABLED"


def test_analytics_endpoint_validates_days_and_account(
    api_client,
):
    client, _ = api_client

    invalid_days_response = client.get(
        (
            "/paper-autopilot/"
            "accounts/1/analytics?days=0"
        ),
        headers=paper_headers(),
    )

    assert invalid_days_response.status_code == 422

    missing_account_response = client.get(
        (
            "/paper-autopilot/"
            "accounts/999999/analytics"
        ),
        headers=paper_headers(),
    )

    assert missing_account_response.status_code == 404
    assert (
        missing_account_response.json()
        ["detail"]
        ["code"]
        == "ACCOUNT_NOT_FOUND"
    ) 