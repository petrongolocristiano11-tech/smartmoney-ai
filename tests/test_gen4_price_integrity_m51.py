from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.core.constants import (
    GEN4_MANDATORY_EXCLUDED_PRICE_MINTS,
    NATIVE_SOL_SENTINEL_MINT,
    SOL_MINT,
    USDC_MINT,
    USDT_MINT,
)
from backend.app.database.base import Base
from backend.app.models.trade import Trade
from backend.app.services.blockchain_parser_gen4_profitability_service import (
    LANE_PROXY,
    PricePoint,
    Signal,
    _policy_snapshot,
    _simulate_signal,
    _valid_price_points,
    preview_gen4_profitability,
)

NOW = datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc)
TOKEN = "PriceIntegrityToken1111111111111111111111111111111"
CUSTOM_EXCLUDED = "CustomQuoteMint111111111111111111111111111111111"
WALLET_A = "PriceWalletA11111111111111111111111111111111111"
WALLET_B = "PriceWalletB11111111111111111111111111111111111"
MARKET = "PriceMarket111111111111111111111111111111111111"


def _settings(**overrides):
    values = {
        "CANONICAL_PARSER_GEN4_PROFITABILITY_ENABLED": False,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_TRAINING_DAYS": 3,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_TEST_DAYS": 1,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_STEP_DAYS": 1,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_WINDOWS": 1,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_SOURCE_TRADES": 10000,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_TRAINING_SOURCE_TRADES": 1,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_TRAINING_CLOSED_POSITIONS": 1,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_WALLET_WIN_RATE_PERCENT": 0.0,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_WALLET_PROFIT_FACTOR": 0.0,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_WALLET_DRAWDOWN_PERCENT": 100.0,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_WALLET_OPEN_POSITIONS": 100,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_CONSENSUS_WINDOW_SECONDS": 180,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_QUALIFIED_WALLETS": 2,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_INDEPENDENT_CLUSTERS": 2,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_EDGE_STRENGTH": 60.0,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_TOKEN_SNAPSHOT_MAX_AGE_MINUTES": 30,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_TOKEN_LIQUIDITY_USD": 0.0,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_TOKEN_RISK_SCORE": 100,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_TOP_HOLDER_PERCENT": 100.0,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_STARTING_CAPITAL_SOL": 1.0,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_ORDER_SIZE_SOL": 0.005,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_SLIPPAGE_BPS": 0,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_FEE_BPS": 0,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_COPY_DELAY_SECONDS": 8,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_EXECUTION_LAG_SECONDS": 180,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_OPEN_POSITIONS": 10,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_STOP_LOSS_PERCENT": 15.0,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_TAKE_PROFIT_PERCENT": 30.0,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_HOLD_MINUTES": 240,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_EVALUABLE_CLOSED_TRADES": 1,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_PROOF_CLOSED_TRADES": 1,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_PORTFOLIO_PROFIT_FACTOR": 0.0,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_PORTFOLIO_DRAWDOWN_PERCENT": 100.0,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_POSITIVE_WINDOW_PERCENT": 0.0,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_WALLET_PROFIT_CONCENTRATION_PERCENT": 100.0,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_EXCLUDED_TOKEN_MINTS": "",
        "CANONICAL_PARSER_GEN4_PROFITABILITY_PRICE_CONTINUITY_WINDOW_SECONDS": 3600,
        "CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_PRICE_DISCONTINUITY_RATIO": 25.0,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _point(*, seconds: int, price: float, side: str = "BUY", wallet: str = MARKET):
    return PricePoint(
        trade_id=seconds + 1,
        signature=f"signature-{seconds}",
        wallet_address=wallet,
        token_mint=TOKEN,
        side=side,
        occurred_at=NOW + timedelta(seconds=seconds),
        price_sol=price,
    )


def _signal() -> Signal:
    return Signal(
        lane=LANE_PROXY,
        token_mint=TOKEN,
        signal_at=NOW,
        contributing_wallets=(WALLET_A, WALLET_B),
        independent_cluster_count=2,
        source_trade_ids=(1, 2),
        source_signatures=("a", "b"),
        evidence={},
    )


def _trade(*, trade_id: int, token: str, at: datetime, price: float, side: str = "BUY") -> Trade:
    return Trade(
        id=trade_id,
        signature=str(uuid4()),
        wallet_address=WALLET_A,
        side=side,
        token_mint=token,
        token_amount=1000.0,
        sol_amount=price * 1000.0,
        success=True,
        block_time=at,
    )


def test_mandatory_quote_assets_are_centrally_excluded():
    assert {SOL_MINT, USDC_MINT, USDT_MINT, NATIVE_SOL_SENTINEL_MINT} <= set(
        GEN4_MANDATORY_EXCLUDED_PRICE_MINTS
    )
    policy = _policy_snapshot(_settings())
    assert set(GEN4_MANDATORY_EXCLUDED_PRICE_MINTS) <= set(policy["excluded_price_mints"])
    assert policy["policy_version"].endswith("/2")


def test_custom_excluded_mint_is_additive_not_a_replacement():
    policy = _policy_snapshot(
        _settings(CANONICAL_PARSER_GEN4_PROFITABILITY_EXCLUDED_TOKEN_MINTS=CUSTOM_EXCLUDED)
    )
    assert CUSTOM_EXCLUDED in policy["excluded_price_mints"]
    assert USDC_MINT in policy["excluded_price_mints"]


def test_quote_assets_do_not_become_price_points():
    policy = _policy_snapshot(_settings())
    trades = [
        _trade(trade_id=1, token=USDC_MINT, at=NOW, price=0.00001),
        _trade(trade_id=2, token=USDT_MINT, at=NOW, price=0.00001),
        _trade(trade_id=3, token=SOL_MINT, at=NOW, price=1.0),
        _trade(trade_id=4, token=TOKEN, at=NOW, price=0.001),
    ]
    points, audit = _valid_price_points(trades, policy=policy)
    assert [item.token_mint for item in points] == [TOKEN]
    assert audit["excluded_quote_asset_count"] == 3
    assert audit["excluded_mint_counts"][USDC_MINT] == 1


def test_short_horizon_price_discontinuity_is_rejected():
    policy = _policy_snapshot(_settings())
    trades = [
        _trade(trade_id=1, token=TOKEN, at=NOW, price=0.001),
        _trade(trade_id=2, token=TOKEN, at=NOW + timedelta(minutes=1), price=0.0011),
        _trade(trade_id=3, token=TOKEN, at=NOW + timedelta(minutes=2), price=100.0),
    ]
    points, audit = _valid_price_points(trades, policy=policy)
    assert [item.trade_id for item in points] == [1, 2]
    assert audit["price_discontinuity_rejected_count"] == 1
    assert audit["price_discontinuity_rejected_trade_ids"] == [3]


def test_take_profit_executes_at_threshold_not_observed_spike():
    policy = _policy_snapshot(_settings())
    outcome = _simulate_signal(
        _signal(),
        token_points=[
            _point(seconds=10, price=0.001),
            _point(seconds=20, price=0.02),
        ],
        policy=policy,
    )
    assert outcome.exit_reason == "TAKE_PROFIT"
    assert outcome.return_percent == 30.0
    assert outcome.evidence["threshold_fill_applied"] is True
    assert outcome.evidence["exit_trigger_observed_price_sol"] == 0.02
    assert outcome.evidence["exit_execution_reference_price_sol"] == 0.0013


def test_stop_loss_executes_at_threshold_not_observed_collapse():
    policy = _policy_snapshot(_settings())
    outcome = _simulate_signal(
        _signal(),
        token_points=[
            _point(seconds=10, price=0.001),
            _point(seconds=20, price=0.0001),
        ],
        policy=policy,
    )
    assert outcome.exit_reason == "STOP_LOSS"
    assert outcome.return_percent == -15.0
    assert outcome.evidence["threshold_fill_applied"] is True
    assert outcome.evidence["exit_execution_reference_price_sol"] == 0.00085


def test_unusable_discontinuous_exit_is_not_turned_into_extreme_profit():
    policy = _policy_snapshot(
        _settings(CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_PRICE_DISCONTINUITY_RATIO=5.0)
    )
    outcome = _simulate_signal(
        _signal(),
        token_points=[
            _point(seconds=10, price=0.001),
            _point(seconds=20, price=100.0),
        ],
        policy=policy,
    )
    assert outcome.pnl_sol is None
    assert outcome.return_percent is None
    assert outcome.exit_reason == "PRICE_INTEGRITY_NO_VALID_EXIT"
    assert outcome.evidence["price_discontinuity_rejected_points"] == 1


def test_preview_reports_price_integrity_audit_and_never_emits_quote_asset_trades():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        old = NOW - timedelta(days=4)
        db.add_all(
            [
                _trade(trade_id=1, token=TOKEN, at=old, price=0.001),
                _trade(trade_id=2, token=USDC_MINT, at=NOW - timedelta(hours=1), price=0.00001),
                _trade(trade_id=3, token=USDC_MINT, at=NOW - timedelta(minutes=50), price=20.0),
                _trade(trade_id=4, token=TOKEN, at=NOW, price=0.0011),
            ]
        )
        db.commit()
        report = preview_gen4_profitability(db, settings_object=_settings(), evaluated_at=NOW)

    assert report["summary"]["price_integrity_audit"]["excluded_quote_asset_count"] == 2
    for window in report["windows"]:
        for trades in window["trades"].values():
            assert all(item["token_mint"] != USDC_MINT for item in trades)
