from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.models.paper_account import PaperAccount
from backend.app.models.paper_autopilot import (
    PaperAutopilotDecision,
    PaperAutopilotManagedPosition,
    PaperAutopilotPolicy,
    PaperAutopilotRun,
)
from backend.app.models.paper_order import PaperOrder
from backend.app.models.paper_position import PaperPosition
from backend.app.services.paper_autopilot_engine import run_paper_autopilot
from backend.app.services.price_oracle import (
    OracleBatch,
    OraclePrice,
    PriceOracleError,
)


TOKEN_MINT = "TokenAutopilot1111111111111111111111111111111"


class FakeOracle:
    def __init__(self, price: float = 0.1):
        self.price = price
        self.fail_batch = False

    def _quote(self, token_mint: str) -> OraclePrice:
        return OraclePrice(
            token_mint=token_mint,
            usd_price=self.price * 100,
            sol_price=self.price,
            sol_usd_price=100,
            block_id=123,
            decimals=6,
            price_change_24h=1.0,
            fetched_at=datetime.now(timezone.utc),
        )

    def get_price(
        self,
        token_mint: str,
        force_refresh: bool = False,
    ) -> OraclePrice:
        return self._quote(token_mint)

    def get_prices(
        self,
        token_mints,
        force_refresh: bool = False,
    ) -> OracleBatch:
        if self.fail_batch:
            raise PriceOracleError(
                "Oracle non disponibile.",
                code="ORACLE_UNAVAILABLE",
            )

        prices = {
            token_mint: self._quote(token_mint)
            for token_mint in token_mints
        }
        return OracleBatch(
            prices=prices,
            missing_token_mints=[],
            fetched_at=datetime.now(timezone.utc),
        )


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    PaperAccount.__table__.create(bind=engine)
    PaperPosition.__table__.create(bind=engine)
    PaperOrder.__table__.create(bind=engine)
    PaperAutopilotPolicy.__table__.create(bind=engine)
    PaperAutopilotRun.__table__.create(bind=engine)
    PaperAutopilotManagedPosition.__table__.create(bind=engine)
    PaperAutopilotDecision.__table__.create(bind=engine)

    session_factory = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )
    session = session_factory()

    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def create_account_and_policy(db):
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

    policy = PaperAutopilotPolicy(
        account_id=account.id,
        status="ENABLED",
        min_signal_score=75,
        min_evidence_score=60,
        min_buyers=3,
        minimum_confidence="HIGH",
        max_signal_age_hours=24,
        min_smart_volume_share_percent=60,
        max_volume_concentration_percent=65,
        blocked_risk_flags=["HIGH_RISK_WALLETS"],
        excluded_token_mints=[],
        max_signals_per_run=20,
        max_entries_per_run=1,
        max_entries_per_day=3,
        token_cooldown_hours=72,
        max_position_percent_of_equity=5,
        max_total_exposure_percent=40,
        minimum_cash_reserve_percent=20,
        minimum_order_size_sol=0.02,
        stop_loss_percent=12,
        take_profit_percent=25,
        trailing_stop_enabled=True,
        trailing_stop_percent=8,
        max_holding_hours=72,
        slippage_percent=0,
        fee_percent=0,
        max_consecutive_errors=3,
        consecutive_errors=0,
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return account, policy


def qualified_signal() -> dict:
    return {
        "version": "2.0",
        "token_mint": TOKEN_MINT,
        "buyers": 4,
        "signal_score": 90.0,
        "evidence_score": 80.0,
        "confidence": "HIGH",
        "age_hours": 1.0,
        "smart_volume_share_percent": 85.0,
        "volume_concentration_percent": 30.0,
        "risk_flags": [],
        "reasons": ["Segnale di test"],
    }


def signal_provider(signals):
    def provider(db, min_buyers=1, lookback_hours=24):
        return {
            "version": "2.0",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "lookback_hours": lookback_hours,
            "count": len(signals),
            "signals": signals,
        }

    return provider


def test_qualified_signal_opens_managed_position(db):
    account, policy = create_account_and_policy(db)
    oracle = FakeOracle(price=0.1)

    result = run_paper_autopilot(
        db=db,
        oracle=oracle,
        account_id=account.id,
        trigger="MANUAL",
        signal_provider=signal_provider([qualified_signal()]),
    )

    assert result["run"].status == "COMPLETED"
    assert result["run"].entries_opened == 1
    assert result["run"].errors_count == 0

    managed = (
        db.query(PaperAutopilotManagedPosition)
        .filter(PaperAutopilotManagedPosition.account_id == account.id)
        .one()
    )
    assert managed.status == "ACTIVE"
    assert managed.stop_loss_price_sol == pytest.approx(
        managed.entry_price_sol * 0.88
    )
    assert managed.take_profit_price_sol == pytest.approx(
        managed.entry_price_sol * 1.25
    )

    decision = (
        db.query(PaperAutopilotDecision)
        .filter(PaperAutopilotDecision.action == "BUY")
        .one()
    )
    assert decision.reason_code == "SIGNAL_ACCEPTED"
    assert decision.signal_score == pytest.approx(90)
    assert float(result["summary"]["cash_balance_sol"]) < 10
    assert policy.consecutive_errors == 0


def test_blocked_risk_flag_skips_entry(db):
    account, _ = create_account_and_policy(db)
    oracle = FakeOracle()
    signal = qualified_signal()
    signal["risk_flags"] = ["HIGH_RISK_WALLETS"]

    result = run_paper_autopilot(
        db=db,
        oracle=oracle,
        account_id=account.id,
        signal_provider=signal_provider([signal]),
    )

    assert result["run"].entries_opened == 0
    assert db.query(PaperOrder).count() == 0

    decision = db.query(PaperAutopilotDecision).one()
    assert decision.action == "SKIP"
    assert decision.reason_code == "BLOCKED_RISK_FLAG"


def test_stop_loss_closes_position(db):
    account, _ = create_account_and_policy(db)
    oracle = FakeOracle(price=0.1)

    first_run = run_paper_autopilot(
        db=db,
        oracle=oracle,
        account_id=account.id,
        signal_provider=signal_provider([qualified_signal()]),
    )
    assert first_run["run"].entries_opened == 1

    oracle.price = 0.08
    second_run = run_paper_autopilot(
        db=db,
        oracle=oracle,
        account_id=account.id,
        signal_provider=signal_provider([]),
    )

    assert second_run["run"].exits_closed == 1

    managed = db.query(PaperAutopilotManagedPosition).one()
    assert managed.status == "CLOSED"
    assert managed.exit_reason == "STOP_LOSS"

    position = db.query(PaperPosition).one()
    assert position.status == "CLOSED"

    sell_decision = (
        db.query(PaperAutopilotDecision)
        .filter(PaperAutopilotDecision.action == "SELL")
        .one()
    )
    assert sell_decision.reason_code == "STOP_LOSS"


def test_disabled_policy_creates_skipped_run(db):
    account, policy = create_account_and_policy(db)
    policy.status = "DISABLED"
    db.commit()

    result = run_paper_autopilot(
        db=db,
        oracle=FakeOracle(),
        account_id=account.id,
        signal_provider=signal_provider([qualified_signal()]),
    )

    assert result["run"].status == "SKIPPED"
    assert result["run"].entries_opened == 0
    assert result["decisions"][0].reason_code == "POLICY_DISABLED"


def test_repeated_oracle_errors_pause_policy(db):
    account, policy = create_account_and_policy(db)
    oracle = FakeOracle(price=0.1)

    run_paper_autopilot(
        db=db,
        oracle=oracle,
        account_id=account.id,
        signal_provider=signal_provider([qualified_signal()]),
    )

    oracle.fail_batch = True
    empty_provider = signal_provider([])

    for _ in range(3):
        run_paper_autopilot(
            db=db,
            oracle=oracle,
            account_id=account.id,
            signal_provider=empty_provider,
        )

    db.refresh(policy)
    assert policy.status == "PAUSED"
    assert policy.consecutive_errors == 3
    assert policy.paused_reason is not None

    failed_runs = (
        db.query(PaperAutopilotRun)
        .filter(PaperAutopilotRun.status == "FAILED")
        .count()
    )
    assert failed_runs == 3
