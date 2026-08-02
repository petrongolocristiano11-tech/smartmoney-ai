from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.database.base import Base
from backend.app.models.candidate_backtest import CandidateBacktestRun
from backend.app.models.gen4_profitability import (
    CanonicalParserGen4ProfitabilityRun,
    CanonicalParserGen4ProfitabilityTrade,
    CanonicalParserGen4ProfitabilityWindow,
)
from backend.app.models.token_safety_snapshot import TokenSafetySnapshot
from backend.app.models.trade import Trade
from backend.app.services.blockchain_parser_gen4_profitability_service import (
    GEN4_PROFITABILITY_CONFIRMATION,
    VERDICT_NOT_EVALUABLE,
    VERDICT_PROFITABLE,
    CanonicalParserGen4ProfitabilityError,
    get_gen4_profitability_status,
    preview_gen4_profitability,
    run_gen4_profitability_validation,
)

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
BASE = NOW - timedelta(days=4)
TOKEN = "TokenMint111111111111111111111111111111111111111"
WALLET_A = "WalletA111111111111111111111111111111111111111"
WALLET_B = "WalletB111111111111111111111111111111111111111"
MARKET = "Market111111111111111111111111111111111111111"


def _settings(*, enabled: bool = False, proof: int = 1):
    return SimpleNamespace(
        CANONICAL_PARSER_GEN4_PROFITABILITY_ENABLED=enabled,
        CANONICAL_PARSER_GEN4_PROFITABILITY_TRAINING_DAYS=3,
        CANONICAL_PARSER_GEN4_PROFITABILITY_TEST_DAYS=1,
        CANONICAL_PARSER_GEN4_PROFITABILITY_STEP_DAYS=1,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_WINDOWS=1,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_SOURCE_TRADES=10000,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_TRAINING_SOURCE_TRADES=2,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_TRAINING_CLOSED_POSITIONS=1,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_WALLET_WIN_RATE_PERCENT=0.0,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_WALLET_PROFIT_FACTOR=1.0,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_WALLET_DRAWDOWN_PERCENT=100.0,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_WALLET_OPEN_POSITIONS=2,
        CANONICAL_PARSER_GEN4_PROFITABILITY_CONSENSUS_WINDOW_SECONDS=180,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_QUALIFIED_WALLETS=2,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_INDEPENDENT_CLUSTERS=2,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_EDGE_STRENGTH=60.0,
        CANONICAL_PARSER_GEN4_PROFITABILITY_TOKEN_SNAPSHOT_MAX_AGE_MINUTES=30,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_TOKEN_LIQUIDITY_USD=1000.0,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_TOKEN_RISK_SCORE=35,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_TOP_HOLDER_PERCENT=25.0,
        CANONICAL_PARSER_GEN4_PROFITABILITY_STARTING_CAPITAL_SOL=1.0,
        CANONICAL_PARSER_GEN4_PROFITABILITY_ORDER_SIZE_SOL=0.005,
        CANONICAL_PARSER_GEN4_PROFITABILITY_SLIPPAGE_BPS=0,
        CANONICAL_PARSER_GEN4_PROFITABILITY_FEE_BPS=0,
        CANONICAL_PARSER_GEN4_PROFITABILITY_COPY_DELAY_SECONDS=8,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_EXECUTION_LAG_SECONDS=180,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_OPEN_POSITIONS=5,
        CANONICAL_PARSER_GEN4_PROFITABILITY_STOP_LOSS_PERCENT=15.0,
        CANONICAL_PARSER_GEN4_PROFITABILITY_TAKE_PROFIT_PERCENT=30.0,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_HOLD_MINUTES=240,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_EVALUABLE_CLOSED_TRADES=1,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_PROOF_CLOSED_TRADES=proof,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_PORTFOLIO_PROFIT_FACTOR=1.0,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_PORTFOLIO_DRAWDOWN_PERCENT=100.0,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_POSITIVE_WINDOW_PERCENT=0.0,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_WALLET_PROFIT_CONCENTRATION_PERCENT=100.0,
    )


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _trade(db: Session, *, wallet: str, side: str, at: datetime, price: float, token: str = TOKEN):
    token_amount = 1000.0
    row = Trade(
        signature=str(uuid4()),
        wallet_address=wallet,
        side=side,
        token_mint=token,
        token_amount=token_amount,
        sol_amount=price * token_amount,
        success=True,
        block_time=at,
    )
    db.add(row)
    db.flush()
    return row


def _training_history(db: Session, wallet: str, offset_minutes: int):
    if offset_minutes == 0:
        _trade(
            db,
            wallet=MARKET,
            side="BUY",
            at=BASE,
            price=0.001,
            token="HistoryMarker1111111111111111111111111111111111",
        )
    _trade(db, wallet=wallet, side="BUY", at=BASE + timedelta(hours=2, minutes=offset_minutes), price=0.001)
    _trade(db, wallet=wallet, side="SELL", at=BASE + timedelta(hours=3, minutes=offset_minutes), price=0.0012)


def _point_in_time_backtest(db: Session, wallet: str, completed_at: datetime):
    db.add(
        CandidateBacktestRun(
            run_id=str(uuid4()),
            wallet_address=wallet,
            status="COMPLETED",
            decision="PROMOSSO",
            data_sufficient=True,
            source_trades=10,
            analysis_source_trades=10,
            completed_positions=5,
            open_positions=0,
            total_return_percent=20.0,
            win_rate_percent=60.0,
            profit_factor=2.0,
            max_drawdown_percent=5.0,
            started_at=completed_at - timedelta(minutes=1),
            completed_at=completed_at,
        )
    )


def _profitable_test_signal(db: Session):
    signal_base = BASE + timedelta(days=3, hours=1)
    _trade(db, wallet=WALLET_A, side="BUY", at=signal_base, price=0.001)
    _trade(db, wallet=WALLET_B, side="BUY", at=signal_base + timedelta(seconds=10), price=0.001)
    _trade(db, wallet=MARKET, side="BUY", at=signal_base + timedelta(seconds=20), price=0.001)
    _trade(db, wallet=WALLET_A, side="SELL", at=signal_base + timedelta(minutes=1), price=0.0014)
    _trade(
        db,
        wallet=MARKET,
        side="BUY",
        at=BASE + timedelta(days=4),
        price=0.002,
        token="MarkerToken111111111111111111111111111111111111",
    )
    return signal_base


def _seed_complete_evidence(db: Session):
    _training_history(db, WALLET_A, 0)
    _training_history(db, WALLET_B, 5)
    signal_at = _profitable_test_signal(db)
    train_end = BASE + timedelta(days=3)
    _point_in_time_backtest(db, WALLET_A, train_end - timedelta(hours=1))
    _point_in_time_backtest(db, WALLET_B, train_end - timedelta(hours=1))
    db.add(
        TokenSafetySnapshot(
            token_mint=TOKEN,
            liquidity_usd=100000.0,
            market_cap_usd=1000000.0,
            volume_24h_usd=500000.0,
            top_holder_percent=10.0,
            risk_score=10,
            honeypot=False,
            mint_authority_enabled=False,
            freeze_authority_enabled=False,
            rugged=False,
            rugcheck_passed=True,
            fetched_at=signal_at - timedelta(minutes=5),
        )
    )
    db.commit()


def test_m47_models_and_migration_are_registered():
    for table in (
        "canonical_parser_gen4_profitability_runs",
        "canonical_parser_gen4_profitability_windows",
        "canonical_parser_gen4_profitability_trades",
    ):
        assert table in Base.metadata.tables

    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("e3b5c8d1f297")
    assert revision.down_revision == "d2a4b7c0e186"
    assert scripts.get_revision("a5e7c1d4b926").down_revision == "f4d6a9c2b813"
    assert scripts.get_heads() == ["a5e7c1d4b926"]
def test_preview_without_history_is_read_only_and_not_evaluable(db):
    report = preview_gen4_profitability(db, settings_object=_settings(), evaluated_at=NOW)
    assert report["verdict"] == VERDICT_NOT_EVALUABLE
    assert report["writes_performed"] is False
    assert report["safety"]["transactions_sent"] == 0
    assert db.query(CanonicalParserGen4ProfitabilityRun).count() == 0


def test_strict_lane_rejects_future_point_in_time_evidence(db):
    _training_history(db, WALLET_A, 0)
    _training_history(db, WALLET_B, 5)
    signal_at = _profitable_test_signal(db)
    _point_in_time_backtest(db, WALLET_A, signal_at + timedelta(hours=1))
    _point_in_time_backtest(db, WALLET_B, signal_at + timedelta(hours=1))
    db.add(
        TokenSafetySnapshot(
            token_mint=TOKEN,
            liquidity_usd=100000.0,
            top_holder_percent=10.0,
            risk_score=10,
            honeypot=False,
            mint_authority_enabled=False,
            freeze_authority_enabled=False,
            rugged=False,
            rugcheck_passed=True,
            fetched_at=signal_at + timedelta(minutes=1),
        )
    )
    db.commit()

    report = preview_gen4_profitability(db, settings_object=_settings(), evaluated_at=NOW)
    assert report["strict_metrics"]["closed_trades"] == 0
    assert report["proxy_metrics"]["closed_trades"] == 1
    assert "POINT_IN_TIME_WALLET_BACKTEST_COVERAGE_INCOMPLETE" in report["evidence_gaps"]


def test_complete_point_in_time_evidence_can_produce_strict_profitable_verdict(db):
    _seed_complete_evidence(db)
    report = preview_gen4_profitability(db, settings_object=_settings(), evaluated_at=NOW)
    assert report["strict_metrics"]["closed_trades"] == 1
    assert report["strict_metrics"]["net_pnl_sol"] > 0
    assert report["strict_metrics"]["profit_factor"] >= 1.0
    assert report["verdict"] == VERDICT_PROFITABLE
    assert report["summary"]["strict_vs_baseline_net_pnl_delta_sol"] <= report["strict_metrics"]["net_pnl_sol"]


def test_run_requires_enablement_and_confirmation(db):
    with pytest.raises(CanonicalParserGen4ProfitabilityError) as disabled:
        run_gen4_profitability_validation(
            db,
            confirmation=GEN4_PROFITABILITY_CONFIRMATION,
            settings_object=_settings(enabled=False),
            evaluated_at=NOW,
        )
    assert disabled.value.code == "GEN4_PROFITABILITY_DISABLED"

    with pytest.raises(CanonicalParserGen4ProfitabilityError) as confirmation:
        run_gen4_profitability_validation(
            db,
            confirmation="WRONG",
            settings_object=_settings(enabled=True),
            evaluated_at=NOW,
        )
    assert confirmation.value.code == "GEN4_PROFITABILITY_CONFIRMATION_REQUIRED"


def test_run_persists_metadata_only_and_is_idempotent(db):
    _seed_complete_evidence(db)
    settings_object = _settings(enabled=True)
    first = run_gen4_profitability_validation(
        db,
        confirmation=GEN4_PROFITABILITY_CONFIRMATION,
        settings_object=settings_object,
        evaluated_at=NOW,
    )
    db.commit()
    second = run_gen4_profitability_validation(
        db,
        confirmation=GEN4_PROFITABILITY_CONFIRMATION,
        settings_object=settings_object,
        evaluated_at=NOW,
    )
    assert first["run_id"] == second["run_id"]
    assert second["idempotent_replay"] is True
    assert db.query(CanonicalParserGen4ProfitabilityRun).count() == 1
    assert db.query(CanonicalParserGen4ProfitabilityWindow).count() == 1
    assert db.query(CanonicalParserGen4ProfitabilityTrade).count() >= 3
    status = get_gen4_profitability_status(db, settings_object=settings_object)
    assert status["run_count"] == 1
    assert status["safety"]["live_execution_authorized"] is False
    assert status["safety"]["external_requests"] == 0


def test_service_source_contains_no_execution_or_external_client_calls():
    source = Path(
        "backend/app/services/blockchain_parser_gen4_profitability_service.py"
    ).read_text()
    forbidden = (
        "JupiterSwapClient(",
        "httpx.",
        "requests.",
        "send_transaction",
        "sign_transaction",
        "execute_permit_bound_paper",
        "run_live_stream_worker",
    )
    for value in forbidden:
        assert value not in source


def test_m47_config_and_routes_are_registered_disabled_by_default():
    config_source = Path("backend/app/core/config.py").read_text()
    env_source = Path(".env.example").read_text()
    main_source = Path("backend/app/main.py").read_text()
    assert "CANONICAL_PARSER_GEN4_PROFITABILITY_ENABLED: bool = False" in config_source
    assert "CANONICAL_PARSER_GEN4_PROFITABILITY_ENABLED=false" in env_source
    for route in (
        "/integrity/parser-gen4-profitability/status",
        "/integrity/parser-gen4-profitability/preview",
        "/integrity/parser-gen4-profitability/run",
        "/integrity/parser-gen4-profitability/runs/{run_id}",
    ):
        assert route in main_source


def test_m47_migration_has_metadata_only_tables_and_protected_downgrade():
    source = Path(
        "alembic/versions/e3b5c8d1f297_add_gen4_walk_forward_profitability.py"
    ).read_text()
    for table in (
        "canonical_parser_gen4_profitability_runs",
        "canonical_parser_gen4_profitability_windows",
        "canonical_parser_gen4_profitability_trades",
    ):
        assert f'"{table}"' in source
    assert "Downgrade M47 rifiutato" in source
    assert "wallet_edges" not in source
    assert "paper_orders" not in source
    assert "live_positions" not in source
