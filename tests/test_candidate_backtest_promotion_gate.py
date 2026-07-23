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
TOKENS = [chr(65 + index) * 32 for index in range(10)]


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
            block_time=at + timedelta(hours=6),
        )
    )


def add_sufficient_sample(db, *, buy_sol: float, sell_sol: float):
    for index, token in enumerate(TOKENS[:6]):
        add_round_trip(
            db,
            index,
            token,
            buy_sol=buy_sol,
            sell_sol=sell_sol,
            at=NOW - timedelta(days=10 - index * 2),
        )


def test_profitable_copyable_wallet_is_promoted(db):
    wallet = add_wallet(db)
    add_sufficient_sample(db, buy_sol=0.05, sell_sol=0.075)
    db.commit()

    client = CompatibleJupiterClient()
    run = run_candidate_backtest(
        db,
        wallet_address=WALLET,
        now=NOW,
        lookback_days=30,
        warmup_days=14,
        check_jupiter=True,
        jupiter_client=client,
    )

    assert run.decision == "PROMOSSO"
    assert run.data_sufficient is True
    assert run.completed_positions == 5
    assert run.net_pnl_sol > 0
    assert run.profit_factor == 999.0
    assert run.jupiter_status == "PASSED"
    assert run.jupiter_tokens_compatible == 6
    assert run.safety["transactions_signed"] is False
    assert run.safety["transactions_submitted"] is False
    assert wallet.promotion_eligible is True
    assert wallet.backtest_data_sufficient is True
    assert wallet.eligible is True
    assert db.query(CandidateBacktestRun).count() == 1


def test_losing_wallet_is_rejected_only_with_sufficient_data(db):
    wallet = add_wallet(db)
    add_sufficient_sample(db, buy_sol=0.08, sell_sol=0.03)
    db.commit()

    run = run_candidate_backtest(
        db,
        wallet_address=WALLET,
        now=NOW,
        lookback_days=30,
        warmup_days=14,
        check_jupiter=True,
        jupiter_client=CompatibleJupiterClient(),
    )

    assert run.data_sufficient is True
    assert run.decision == "BOCCIATO"
    assert run.total_return_percent < 0
    assert run.profit_factor == 0
    assert wallet.promotion_eligible is False
    assert wallet.eligible is False
    assert "NON_POSITIVE_NET_RETURN" in run.reasons


def test_small_sample_is_data_insufficient_not_rejected(db):
    wallet = add_wallet(db)
    for index, token in enumerate(TOKENS[:3]):
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
        lookback_days=7,
        check_jupiter=True,
        jupiter_client=CompatibleJupiterClient(),
    )

    assert run.decision == "DATI_INSUFFICIENTI"
    assert run.data_sufficient is False
    assert "COMPLETED_POSITIONS_BELOW_SUFFICIENCY_MINIMUM" in run.reasons
    assert wallet.backtest_data_sufficient is False
    assert wallet.eligible is False


def test_jupiter_check_is_required_after_data_is_sufficient(db):
    wallet = add_wallet(db)
    add_sufficient_sample(db, buy_sol=0.05, sell_sol=0.075)
    db.commit()

    run = run_candidate_backtest(
        db,
        wallet_address=WALLET,
        now=NOW,
        lookback_days=30,
        check_jupiter=False,
    )

    assert run.data_sufficient is True
    assert run.decision == "OSSERVAZIONE"
    assert run.jupiter_status == "NOT_CHECKED"
    assert "JUPITER_CHECK_REQUIRED" in run.reasons
    assert wallet.eligible is False


def test_quality_gate_prevents_promotion_even_with_profit(db):
    wallet = add_wallet(db, quality="OSSERVAZIONE")
    add_sufficient_sample(db, buy_sol=0.05, sell_sol=0.075)
    db.commit()

    run = run_candidate_backtest(
        db,
        wallet_address=WALLET,
        now=NOW,
        lookback_days=30,
        check_jupiter=True,
        jupiter_client=CompatibleJupiterClient(),
    )

    assert run.decision == "OSSERVAZIONE"
    assert "QUALITY_NOT_COPYABLE" in run.reasons
    assert wallet.eligible is False


def test_warmup_reconstructs_position_and_matches_later_sell(db):
    wallet = add_wallet(db)
    token = TOKENS[0]
    db.add(
        Trade(
            signature="warmup-buy",
            wallet_address=WALLET,
            side="BUY",
            source="TEST",
            token_mint=token,
            token_amount=100,
            sol_amount=0.05,
            success=True,
            block_time=NOW - timedelta(days=10),
        )
    )
    db.add(
        Trade(
            signature="analysis-sell",
            wallet_address=WALLET,
            side="SELL",
            source="TEST",
            token_mint=token,
            token_amount=100,
            sol_amount=0.07,
            success=True,
            block_time=NOW - timedelta(days=3),
        )
    )
    db.commit()

    run = run_candidate_backtest(
        db,
        wallet_address=WALLET,
        now=NOW,
        lookback_days=7,
        warmup_days=14,
        check_jupiter=False,
    )

    assert run.bootstrap_positions == 1
    assert run.bootstrap_positions_closed == 1
    assert run.completed_positions == 1
    assert run.unmatched_sells == 0
    assert run.position_results[0]["bootstrap"] is True
