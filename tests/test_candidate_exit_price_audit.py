from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database.base import Base
from backend.app.models.candidate_exit_price_audit import CandidateExitPriceAuditRun
from backend.app.models.candidate_position_lifecycle_audit import (
    CandidatePositionLifecycleAuditRun,
)
from backend.app.models.candidate_token_compatibility import (
    CandidateTokenCompatibility,
)
from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.models.trade import Trade
from backend.app.services.candidate_exit_price_audit_service import (
    run_candidate_exit_price_audit,
)


NOW = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
WALLET = "E" * 32
TOKEN = "T" * 32


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    session.add(DiscoveredWallet(wallet_address=WALLET, smart_score=70))
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def add_lifecycle(db, *, entry_hours_ago=12, details=True):
    position_details = []
    if details:
        position_details.append(
            {
                "token_mint": TOKEN,
                "bootstrap": False,
                "entry_at": (NOW - timedelta(hours=entry_hours_ago)).isoformat(),
                "remaining_quantity": 100.0,
                "remaining_cost_basis_sol": 0.05,
                "reason_still_open": "NO_SOURCE_SELL",
                "last_source_activity_at": (
                    NOW - timedelta(hours=entry_hours_ago)
                ).isoformat(),
            }
        )
    run = CandidatePositionLifecycleAuditRun(
        run_id=f"lifecycle-{entry_hours_ago}-{int(details)}",
        wallet_address=WALLET,
        status="COMPLETED",
        parameters={
            "fixed_buy_size_sol": 0.05,
            "slippage_bps": 100,
            "fee_bps": 10,
            "effective_market_friction_bps": 103.3333,
        },
        safety={"cached_data_only": True},
        baseline_metrics={},
        lifecycle_summary={},
        position_details=position_details,
        scenario_results=[],
        diagnoses=[],
        started_at=NOW,
        completed_at=NOW,
    )
    db.add(run)
    db.commit()
    return run


def add_trade(db, *, hours_ago, signature="trade", side="BUY"):
    db.add(
        Trade(
            signature=signature,
            wallet_address=WALLET,
            side=side,
            source="TEST",
            token_mint=TOKEN,
            token_amount=100.0,
            sol_amount=0.05,
            success=True,
            block_time=NOW - timedelta(hours=hours_ago),
        )
    )
    db.commit()


def add_cache(db, *, checked_hours_ago=1, expires_hours_from_now=5):
    db.add(
        CandidateTokenCompatibility(
            token_mint=TOKEN,
            fixed_buy_size_lamports=50_000_000,
            slippage_bps=100,
            status="PASSED",
            buy_quote=True,
            sell_quote=True,
            compatible=True,
            buy_out_amount_raw=100_000,
            sell_out_amount_raw=49_000_000,
            checked_at=NOW - timedelta(hours=checked_hours_ago),
            expires_at=NOW + timedelta(hours=expires_hours_from_now),
        )
    )
    db.commit()


def test_missing_cache_blocks_but_persists_discovery_metadata(db):
    add_lifecycle(db)
    add_trade(db, hours_ago=12)

    run = run_candidate_exit_price_audit(db, wallet_address=WALLET, now=NOW)

    assert run.readiness_status == "BLOCKED"
    assert run.summary["local_observable_percent"] == pytest.approx(100.0)
    assert run.summary["current_route_supported_percent"] == pytest.approx(0.0)
    assert run.summary["cache_missing"] == 1
    assert "ALL_OPEN_POSITIONS_MISSING_CACHE" in run.diagnoses
    assert run.safety["helius_requests"] == 0
    assert run.safety["jupiter_requests"] == 0
    wallet = db.query(DiscoveredWallet).filter_by(wallet_address=WALLET).one()
    assert wallet.exit_price_coverage_status == "BLOCKED"
    assert wallet.latest_exit_price_audit_run_id == run.run_id
    assert db.query(CandidateExitPriceAuditRun).count() == 1


def test_fresh_local_price_and_current_cache_are_ready(db):
    add_lifecycle(db)
    add_trade(db, hours_ago=12)
    add_cache(db)

    run = run_candidate_exit_price_audit(db, wallet_address=WALLET, now=NOW)

    assert run.readiness_status == "READY"
    assert run.readiness_score == 100
    assert run.summary["current_route_supported_percent"] == pytest.approx(100.0)
    assert run.summary["temporal_execution_percent"] == pytest.approx(100.0)
    evidence = run.position_results[0]["scenario_evidence"][0]
    assert evidence["evidence_status"] == "TEMPORALLY_EXECUTABLE"
    assert evidence["cache"]["round_trip_value_sol"] == pytest.approx(0.049)


def test_stale_local_price_is_not_counted_as_observable(db):
    add_lifecycle(db, entry_hours_ago=48)
    add_trade(db, hours_ago=48)
    add_cache(db)

    run = run_candidate_exit_price_audit(
        db,
        wallet_address=WALLET,
        max_local_price_age_hours=24,
        now=NOW,
    )

    assert run.summary["local_observable_percent"] == pytest.approx(0.0)
    assert run.summary["stale_local_prices"] == 1
    evidence = run.position_results[0]["scenario_evidence"][0]
    assert evidence["evidence_status"] == "STALE_LOCAL_PRICE"
    assert evidence["observable_pnl_sol"] is None


def test_future_price_is_rejected_for_historical_expiry(db):
    add_lifecycle(db, entry_hours_ago=48)
    add_trade(db, hours_ago=12, signature="future-for-24h")

    run = run_candidate_exit_price_audit(
        db,
        wallet_address=WALLET,
        max_local_price_age_hours=24,
        now=NOW,
    )

    scenario_24 = next(
        row for row in run.scenario_results if row["holding_period_hours"] == 24
    )
    evidence_24 = next(
        row
        for row in run.position_results[0]["scenario_evidence"]
        if row["holding_period_hours"] == 24
    )
    assert scenario_24["missing_local_prices"] == 1
    assert scenario_24["future_only_prices_rejected"] == 1
    assert evidence_24["local_price_available"] is False
    assert evidence_24["future_price_exists_but_rejected"] is True


def test_no_open_positions_is_ready_and_not_applicable(db):
    add_lifecycle(db, details=False)

    run = run_candidate_exit_price_audit(db, wallet_address=WALLET, now=NOW)

    assert run.readiness_status == "READY"
    assert run.readiness_score == 100
    assert run.summary["positions_analyzed"] == 0
    assert run.diagnoses == ["NO_OPEN_POSITIONS_REQUIRING_EXIT"]
