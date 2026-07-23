from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database.base import Base
from backend.app.models.candidate_backtest import CandidateBacktestRun
from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.models.trade import Trade
from backend.app.services.candidate_backtest_service import run_candidate_backtest


NOW = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
WALLET = "P" * 32
TOKEN_A = "A" * 32
TOKEN_B = "B" * 32
TOKEN_C = "C" * 32
TOKEN_D = "D" * 32


class CompatibleJupiterClient:
    def __init__(self):
        self.calls = []

    def get_order(self, *, input_mint, output_mint, amount_raw, taker, slippage_bps):
        self.calls.append((input_mint, output_mint, amount_raw))
        return SimpleNamespace(out_amount=max(1, amount_raw * 2))


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


def add_wallet(db, *, quality="COPIABILE", activity="ATTIVO"):
    wallet = DiscoveredWallet(
        wallet_address=WALLET,
        smart_score=82,
        activity_score=90,
        activity_classification=activity,
        activity_eligible=activity == "ATTIVO",
        activity_reasons=[],
        quality_score=85,
        quality_classification=quality,
        quality_eligible=quality == "COPIABILE",
        quality_reasons=[],
        eligible=False,
    )
    db.add(wallet)
    db.flush()
    return wallet


def add_round_trip(db, index, token, buy_sol, sell_sol, at):
    db.add(
        Trade(
            signature=f"buy-{index}",
            wallet_address=WALLET,
            side="BUY",
            source="TEST",
            token_mint=token,
            token_amount=100,
            sol_amount=buy_sol,
            success=True,
            block_time=at,
        )
    )
    db.add(
        Trade(
            signature=f"sell-{index}",
            wallet_address=WALLET,
            side="SELL",
            source="TEST",
            token_mint=token,
            token_amount=100,
            sol_amount=sell_sol,
            success=True,
            block_time=at + timedelta(minutes=30),
        )
    )


def test_profitable_copyable_wallet_is_promoted(db):
    wallet = add_wallet(db)
    for index, token in enumerate((TOKEN_A, TOKEN_B, TOKEN_C, TOKEN_D)):
        add_round_trip(
            db,
            index,
            token,
            buy_sol=0.05,
            sell_sol=0.075,
            at=NOW - timedelta(days=4 - index),
        )
    db.commit()

    client = CompatibleJupiterClient()
    run = run_candidate_backtest(
        db,
        wallet_address=WALLET,
        now=NOW,
        check_jupiter=True,
        jupiter_client=client,
    )

    assert run.decision == "PROMOSSO"
    assert run.completed_positions == 4
    assert run.net_pnl_sol > 0
    assert run.profit_factor == 999.0
    assert run.jupiter_status == "PASSED"
    assert run.jupiter_tokens_compatible == 4
    assert run.safety["transactions_signed"] is False
    assert run.safety["transactions_submitted"] is False
    assert wallet.promotion_eligible is True
    assert wallet.eligible is True
    assert db.query(CandidateBacktestRun).count() == 1


def test_losing_wallet_is_rejected(db):
    wallet = add_wallet(db)
    for index, token in enumerate((TOKEN_A, TOKEN_B, TOKEN_C)):
        add_round_trip(
            db,
            index,
            token,
            buy_sol=0.08,
            sell_sol=0.03,
            at=NOW - timedelta(days=3 - index),
        )
    db.commit()

    run = run_candidate_backtest(
        db,
        wallet_address=WALLET,
        now=NOW,
        check_jupiter=True,
        jupiter_client=CompatibleJupiterClient(),
    )

    assert run.decision == "BOCCIATO"
    assert run.total_return_percent < 0
    assert run.profit_factor == 0
    assert wallet.promotion_eligible is False
    assert wallet.eligible is False
    assert "NON_POSITIVE_NET_RETURN" in run.reasons


def test_jupiter_check_is_required_for_promotion(db):
    wallet = add_wallet(db)
    for index, token in enumerate((TOKEN_A, TOKEN_B, TOKEN_C)):
        add_round_trip(
            db,
            index,
            token,
            buy_sol=0.05,
            sell_sol=0.075,
            at=NOW - timedelta(days=3 - index),
        )
    db.commit()

    run = run_candidate_backtest(
        db,
        wallet_address=WALLET,
        now=NOW,
        check_jupiter=False,
    )

    assert run.decision == "OSSERVAZIONE"
    assert run.jupiter_status == "NOT_CHECKED"
    assert "JUPITER_CHECK_REQUIRED" in run.reasons
    assert wallet.eligible is False


def test_quality_gate_prevents_promotion_even_with_profit(db):
    wallet = add_wallet(db, quality="OSSERVAZIONE")
    for index, token in enumerate((TOKEN_A, TOKEN_B, TOKEN_C)):
        add_round_trip(
            db,
            index,
            token,
            buy_sol=0.05,
            sell_sol=0.075,
            at=NOW - timedelta(days=3 - index),
        )
    db.commit()

    run = run_candidate_backtest(
        db,
        wallet_address=WALLET,
        now=NOW,
        check_jupiter=True,
        jupiter_client=CompatibleJupiterClient(),
    )

    assert run.decision == "OSSERVAZIONE"
    assert "QUALITY_NOT_COPYABLE" in run.reasons
    assert wallet.eligible is False
