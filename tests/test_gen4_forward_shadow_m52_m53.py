from __future__ import annotations

import os
import subprocess
import sys
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
from backend.app.models.gen4_forward_shadow import (
    CanonicalParserGen4ForwardCampaign,
    CanonicalParserGen4ForwardCycle,
    CanonicalParserGen4ForwardDecision,
)
from backend.app.models.token_safety_snapshot import TokenSafetySnapshot
from backend.app.models.trade import Trade
from backend.app.services.blockchain_parser_gen4_forward_shadow_service import (
    GEN4_FORWARD_CYCLE_CONFIRMATION,
    GEN4_FORWARD_START_CONFIRMATION,
    GEN4_FORWARD_STOP_CONFIRMATION,
    LANE_BASELINE_FORWARD,
    LANE_PROXY_FORWARD,
    LANE_STRICT_FORWARD,
    CanonicalParserGen4ForwardShadowError,
    get_gen4_forward_status,
    preview_gen4_forward_campaign,
    run_gen4_forward_cycle,
    start_gen4_forward_campaign,
    stop_gen4_forward_campaign,
)

NOW = datetime(2026, 8, 2, 16, 30, tzinfo=timezone.utc)
TOKEN_A = "ForwardTokenA111111111111111111111111111111111111"
TOKEN_B = "ForwardTokenB111111111111111111111111111111111111"
WALLET_A = "ForwardWalletA111111111111111111111111111111111"
WALLET_B = "ForwardWalletB111111111111111111111111111111111"
MARKET = "ForwardMarket1111111111111111111111111111111111"


def _settings(*, enabled: bool = True, observation_days: int = 1):
    return SimpleNamespace(
        CANONICAL_PARSER_GEN4_PROFITABILITY_ENABLED=False,
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
        CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_PROOF_CLOSED_TRADES=1,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_PORTFOLIO_PROFIT_FACTOR=1.0,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_PORTFOLIO_DRAWDOWN_PERCENT=100.0,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_POSITIVE_WINDOW_PERCENT=0.0,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_WALLET_PROFIT_CONCENTRATION_PERCENT=100.0,
        CANONICAL_PARSER_GEN4_PROFITABILITY_EXCLUDED_TOKEN_MINTS="",
        CANONICAL_PARSER_GEN4_PROFITABILITY_PRICE_CONTINUITY_WINDOW_SECONDS=3600,
        CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_PRICE_DISCONTINUITY_RATIO=25.0,
        CANONICAL_PARSER_GEN4_FORWARD_ENABLED=enabled,
        CANONICAL_PARSER_GEN4_FORWARD_TRAINING_DAYS=3,
        CANONICAL_PARSER_GEN4_FORWARD_MIN_FROZEN_WALLETS=2,
        CANONICAL_PARSER_GEN4_FORWARD_MAX_FROZEN_WALLETS=20,
        CANONICAL_PARSER_GEN4_FORWARD_MIN_OBSERVATION_DAYS=observation_days,
        CANONICAL_PARSER_GEN4_FORWARD_MIN_CLOSED_TRADES=1,
        CANONICAL_PARSER_GEN4_FORWARD_PROOF_CLOSED_TRADES=1,
        CANONICAL_PARSER_GEN4_FORWARD_MAX_SOURCE_TRADES_PER_CYCLE=10000,
        CANONICAL_PARSER_GEN4_FORWARD_MAX_INGESTION_LAG_SECONDS=300,
        CANONICAL_PARSER_GEN4_FORWARD_MAX_SAFETY_WAIT_MINUTES=30,
    )


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _trade(
    db: Session,
    *,
    wallet: str,
    side: str,
    token: str,
    block_at: datetime,
    created_at: datetime,
    price: float,
) -> Trade:
    token_amount = 1000.0
    row = Trade(
        signature=str(uuid4()),
        wallet_address=wallet,
        side=side,
        token_mint=token,
        token_amount=token_amount,
        sol_amount=price * token_amount,
        success=True,
        block_time=block_at,
        created_at=created_at,
    )
    db.add(row)
    db.flush()
    return row


def _training(db: Session):
    start = NOW - timedelta(days=2)
    for wallet, token, offset in (
        (WALLET_A, TOKEN_A, 0),
        (WALLET_B, TOKEN_B, 5),
    ):
        _trade(
            db,
            wallet=wallet,
            side="BUY",
            token=token,
            block_at=start + timedelta(minutes=offset),
            created_at=start + timedelta(minutes=offset, seconds=1),
            price=0.001,
        )
        _trade(
            db,
            wallet=wallet,
            side="SELL",
            token=token,
            block_at=start + timedelta(hours=1, minutes=offset),
            created_at=start + timedelta(hours=1, minutes=offset, seconds=1),
            price=0.0012,
        )
    db.commit()


def _start(db: Session, settings_object=None):
    settings_object = settings_object or _settings()
    return start_gen4_forward_campaign(
        db,
        confirmation=GEN4_FORWARD_START_CONFIRMATION,
        candidate_wallets=[WALLET_A, WALLET_B],
        anchor_at=NOW,
        actor_label="TEST",
        settings_object=settings_object,
    )


def _future_profitable_signal(db: Session, *, safe: bool = True):
    _trade(
        db,
        wallet=WALLET_A,
        side="BUY",
        token=TOKEN_A,
        block_at=NOW + timedelta(seconds=10),
        created_at=NOW + timedelta(seconds=11),
        price=0.001,
    )
    _trade(
        db,
        wallet=WALLET_B,
        side="BUY",
        token=TOKEN_A,
        block_at=NOW + timedelta(seconds=20),
        created_at=NOW + timedelta(seconds=21),
        price=0.001,
    )
    _trade(
        db,
        wallet=MARKET,
        side="BUY",
        token=TOKEN_A,
        block_at=NOW + timedelta(seconds=30),
        created_at=NOW + timedelta(seconds=31),
        price=0.001,
    )
    _trade(
        db,
        wallet=WALLET_A,
        side="SELL",
        token=TOKEN_A,
        block_at=NOW + timedelta(seconds=60),
        created_at=NOW + timedelta(seconds=61),
        price=0.0014,
    )
    if safe:
        db.add(
            TokenSafetySnapshot(
                token_mint=TOKEN_A,
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
                fetched_at=NOW + timedelta(seconds=22),
                created_at=NOW + timedelta(seconds=22),
                updated_at=NOW + timedelta(seconds=22),
            )
        )
    db.commit()


def test_models_and_migration_are_registered_as_single_head():
    for table in (
        "canonical_parser_gen4_forward_campaigns",
        "canonical_parser_gen4_forward_cycles",
        "canonical_parser_gen4_forward_decisions",
    ):
        assert table in Base.metadata.tables
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("f4d6a9c2b813")
    assert revision.down_revision == "e3b5c8d1f297"
    assert scripts.get_revision("a5e7c1d4b926").down_revision == "f4d6a9c2b813"
    assert scripts.get_heads() == ["a5e7c1d4b926"]


def test_preview_is_read_only_and_freezes_only_qualified_wallets(db):
    _training(db)
    preview = preview_gen4_forward_campaign(
        db,
        candidate_wallets=[WALLET_A, WALLET_B],
        anchor_at=NOW,
        settings_object=_settings(),
    )
    assert preview["ready"] is True
    assert preview["writes_performed"] is False
    assert preview["training_snapshot"]["selected_wallets"] == [WALLET_A, WALLET_B]
    assert db.query(CanonicalParserGen4ForwardCampaign).count() == 0


def test_start_requires_enablement_and_confirmation(db):
    _training(db)
    with pytest.raises(CanonicalParserGen4ForwardShadowError) as disabled:
        start_gen4_forward_campaign(
            db,
            confirmation=GEN4_FORWARD_START_CONFIRMATION,
            candidate_wallets=[WALLET_A, WALLET_B],
            anchor_at=NOW,
            settings_object=_settings(enabled=False),
        )
    assert disabled.value.code == "GEN4_FORWARD_DISABLED"
    with pytest.raises(CanonicalParserGen4ForwardShadowError) as confirmation:
        start_gen4_forward_campaign(
            db,
            confirmation="WRONG",
            candidate_wallets=[WALLET_A, WALLET_B],
            anchor_at=NOW,
            settings_object=_settings(),
        )
    assert confirmation.value.code == "GEN4_FORWARD_START_CONFIRMATION_REQUIRED"


def test_start_persists_frozen_wallets_and_blocks_second_active_campaign(db):
    _training(db)
    started = _start(db)
    db.commit()
    assert started["status"] == "ACTIVE"
    assert set(started["frozen_wallets"]) == {WALLET_A, WALLET_B}
    assert db.query(CanonicalParserGen4ForwardCampaign).count() == 1
    preview = preview_gen4_forward_campaign(
        db,
        candidate_wallets=[WALLET_A, WALLET_B],
        anchor_at=NOW + timedelta(seconds=1),
        settings_object=_settings(),
    )
    assert preview["ready"] is False
    assert "ACTIVE_FORWARD_CAMPAIGN_ALREADY_EXISTS" in preview["reason_codes"]


def test_cycle_rejects_historical_backfill_after_anchor(db):
    _training(db)
    started = _start(db)
    db.commit()
    _trade(
        db,
        wallet=WALLET_A,
        side="BUY",
        token=TOKEN_A,
        block_at=NOW - timedelta(days=1),
        created_at=NOW + timedelta(seconds=10),
        price=0.001,
    )
    _trade(
        db,
        wallet=WALLET_B,
        side="BUY",
        token=TOKEN_A,
        block_at=NOW + timedelta(seconds=10),
        created_at=NOW - timedelta(seconds=1),
        price=0.001,
    )
    db.commit()
    result = run_gen4_forward_cycle(
        db,
        campaign_id=started["campaign_id"],
        confirmation=GEN4_FORWARD_CYCLE_CONFIRMATION,
        observed_at=NOW + timedelta(minutes=1),
        settings_object=_settings(),
    )
    db.commit()
    assert result["cycle"]["source_trade_count"] == 0
    assert result["campaign"]["decision_count"] == 0


def test_forward_cycle_produces_strict_proxy_and_baseline_closed_outcomes(db):
    _training(db)
    started = _start(db)
    db.commit()
    _future_profitable_signal(db, safe=True)
    result = run_gen4_forward_cycle(
        db,
        campaign_id=started["campaign_id"],
        confirmation=GEN4_FORWARD_CYCLE_CONFIRMATION,
        observed_at=NOW + timedelta(minutes=2),
        settings_object=_settings(),
    )
    db.commit()
    campaign = result["campaign"]
    assert campaign["strict_closed_trade_count"] == 1
    assert campaign["proxy_closed_trade_count"] == 1
    assert campaign["baseline_closed_trade_count"] >= 1
    assert campaign["strict_metrics"]["total_return_percent"] > 0
    assert campaign["safety"]["transactions_sent"] == 0
    lanes = {row.lane for row in db.query(CanonicalParserGen4ForwardDecision).all()}
    assert {LANE_STRICT_FORWARD, LANE_PROXY_FORWARD, LANE_BASELINE_FORWARD} <= lanes


def test_missing_safety_keeps_strict_waiting_but_proxy_is_forward_visible(db):
    _training(db)
    started = _start(db)
    db.commit()
    _future_profitable_signal(db, safe=False)
    result = run_gen4_forward_cycle(
        db,
        campaign_id=started["campaign_id"],
        confirmation=GEN4_FORWARD_CYCLE_CONFIRMATION,
        observed_at=NOW + timedelta(minutes=2),
        settings_object=_settings(),
    )
    db.commit()
    strict = db.query(CanonicalParserGen4ForwardDecision).filter_by(
        lane=LANE_STRICT_FORWARD
    ).one()
    proxy = db.query(CanonicalParserGen4ForwardDecision).filter_by(
        lane=LANE_PROXY_FORWARD
    ).one()
    assert strict.status == "WAITING_SAFETY"
    assert proxy.status == "CLOSED"
    assert result["campaign"]["strict_closed_trade_count"] == 0
    assert result["campaign"]["proxy_closed_trade_count"] == 1


def test_repeating_same_watermark_is_decision_idempotent(db):
    _training(db)
    started = _start(db)
    db.commit()
    _future_profitable_signal(db, safe=True)
    first = run_gen4_forward_cycle(
        db,
        campaign_id=started["campaign_id"],
        confirmation=GEN4_FORWARD_CYCLE_CONFIRMATION,
        observed_at=NOW + timedelta(minutes=2),
        settings_object=_settings(),
    )
    db.commit()
    count = db.query(CanonicalParserGen4ForwardDecision).count()
    second = run_gen4_forward_cycle(
        db,
        campaign_id=started["campaign_id"],
        confirmation=GEN4_FORWARD_CYCLE_CONFIRMATION,
        observed_at=NOW + timedelta(minutes=2),
        settings_object=_settings(),
    )
    db.commit()
    assert db.query(CanonicalParserGen4ForwardDecision).count() == count
    assert second["cycle"]["new_decision_count"] == 0
    assert second["cycle"]["updated_decision_count"] == 0
    assert db.query(CanonicalParserGen4ForwardCycle).count() == 2
    assert first["campaign"]["strict_closed_trade_count"] == second["campaign"]["strict_closed_trade_count"]


def test_stop_after_minimum_period_evaluates_strict_sample(db):
    _training(db)
    started = _start(db, _settings(observation_days=1))
    db.commit()
    _future_profitable_signal(db, safe=True)
    run_gen4_forward_cycle(
        db,
        campaign_id=started["campaign_id"],
        confirmation=GEN4_FORWARD_CYCLE_CONFIRMATION,
        observed_at=NOW + timedelta(minutes=2),
        settings_object=_settings(observation_days=1),
    )
    stopped = stop_gen4_forward_campaign(
        db,
        campaign_id=started["campaign_id"],
        confirmation=GEN4_FORWARD_STOP_CONFIRMATION,
        observed_at=NOW + timedelta(days=1, minutes=1),
        settings_object=_settings(observation_days=1),
    )
    db.commit()
    assert stopped["status"] == "COMPLETED"
    assert stopped["strict_evidence_status"] == "SUFFICIENT"
    assert stopped["verdict"] == "PROFITABLE_EVIDENCE"


def test_status_is_metadata_only(db):
    status = get_gen4_forward_status(db, settings_object=_settings())
    assert status["campaign_count"] == 0
    assert status["safety"]["external_requests"] == 0
    assert status["safety"]["live_execution_authorized"] is False


def test_config_routes_service_and_protected_downgrade_contract():
    config_source = Path("backend/app/core/config.py").read_text(encoding="utf-8")
    env_source = Path(".env.example").read_text(encoding="utf-8")
    main_source = Path("backend/app/main.py").read_text(encoding="utf-8")
    service_source = Path(
        "backend/app/services/blockchain_parser_gen4_forward_shadow_service.py"
    ).read_text(encoding="utf-8")
    migration_source = Path(
        "alembic/versions/f4d6a9c2b813_add_gen4_strict_forward_shadow.py"
    ).read_text(encoding="utf-8")
    assert "CANONICAL_PARSER_GEN4_FORWARD_ENABLED: bool = False" in config_source
    assert "CANONICAL_PARSER_GEN4_FORWARD_ENABLED=false" in env_source
    for route in (
        "/integrity/parser-gen4-forward/status",
        "/integrity/parser-gen4-forward/preview",
        "/integrity/parser-gen4-forward/start",
        "/integrity/parser-gen4-forward/cycle",
        "/integrity/parser-gen4-forward/stop",
        "/integrity/parser-gen4-forward/campaigns/{campaign_id}",
    ):
        assert route in main_source
    for forbidden in (
        "JupiterSwapClient(",
        "httpx.",
        "requests.",
        "send_transaction",
        "sign_transaction",
        "execute_permit_bound_paper",
        "run_live_stream_worker",
    ):
        assert forbidden not in service_source
    assert "Downgrade M52-M53 rifiutato" in migration_source
    assert "historical_backfill_after_anchor_allowed" in service_source


def test_cli_launcher_works_from_external_cwd(tmp_path):
    script = Path("scripts/run_gen4_forward_shadow.py").resolve()
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_URL": "sqlite+pysqlite:///:memory:",
            "SOLANA_RPC_URL": "http://localhost:8899",
            "HELIUS_API_KEY": "test-key",
        }
    )
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "strict forward shadow" in result.stdout
