from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database.base import Base
from backend.app.models.candidate_position_lifecycle_audit import (
    CandidatePositionLifecycleAuditRun,
)
from backend.app.models.candidate_token_compatibility import (
    CandidateTokenCompatibility,
)
from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.models.trade import Trade
from backend.app.services.candidate_exitability_refresh_service import (
    refresh_candidate_open_position_exitability,
)


NOW = datetime(2026, 8, 1, 12, 0, tzinfo=timezone.utc)
WALLET = "R" * 32
TOKEN_A = "A" * 32
TOKEN_B = "B" * 32


class FakeJupiter:
    def __init__(self):
        self.calls = []

    def get_order(
        self,
        *,
        input_mint,
        output_mint,
        amount_raw,
        taker,
        slippage_bps,
    ):
        self.calls.append(
            (input_mint, output_mint, amount_raw, slippage_bps)
        )
        if input_mint == "So11111111111111111111111111111111111111112":
            return SimpleNamespace(out_amount=max(1, amount_raw * 2))
        return SimpleNamespace(out_amount=max(1, amount_raw // 2))


def make_db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine, expire_on_commit=False)()
    db.add(DiscoveredWallet(wallet_address=WALLET, smart_score=80))
    db.commit()
    return engine, db


def add_lifecycle(db, *, tokens, run_id="lifecycle-refresh"):
    details = []
    for index, token in enumerate(tokens):
        entry_at = NOW - timedelta(hours=12 + index)
        details.append(
            {
                "token_mint": token,
                "bootstrap": False,
                "entry_at": entry_at.isoformat(),
                "remaining_quantity": 100.0,
                "remaining_cost_basis_sol": 0.005,
                "reason_still_open": "NO_SOURCE_SELL",
                "last_source_activity_at": entry_at.isoformat(),
            }
        )
        db.add(
            Trade(
                signature=f"trade-{index}",
                wallet_address=WALLET,
                side="BUY",
                source="TEST",
                token_mint=token,
                token_amount=100.0,
                sol_amount=0.005,
                success=True,
                block_time=entry_at,
            )
        )

    run = CandidatePositionLifecycleAuditRun(
        run_id=run_id,
        wallet_address=WALLET,
        status="COMPLETED",
        parameters={
            "fixed_buy_size_sol": 0.005,
            "slippage_bps": 100,
            "fee_bps": 10,
            "effective_market_friction_bps": 103.3333,
            "max_open_positions": 10,
        },
        safety={"cached_data_only": True},
        baseline_metrics={"open_positions": len(details)},
        lifecycle_summary={},
        position_details=details,
        scenario_results=[],
        diagnoses=[],
        started_at=NOW - timedelta(minutes=1),
        completed_at=NOW - timedelta(minutes=1),
    )
    db.add(run)
    db.commit()
    return run


def test_refresh_populates_all_open_position_caches_and_reaudits():
    engine, db = make_db()
    try:
        lifecycle = add_lifecycle(db, tokens=[TOKEN_A, TOKEN_B])
        client = FakeJupiter()

        result = refresh_candidate_open_position_exitability(
            db,
            wallet_address=WALLET,
            lifecycle_run_id=lifecycle.run_id,
            cache_ttl_hours=6,
            max_local_price_age_hours=24,
            max_tokens=20,
            force_refresh=True,
            jupiter_client=client,
            now=NOW,
        )

        assert result["status"] == "COMPLETED"
        assert result["summary"]["source_open_positions"] == 2
        assert result["summary"]["tokens_checked"] == 2
        assert result["summary"]["route_found"] == 2
        assert result["summary"]["requests"] == 4
        assert result["summary"]["audit_cache_missing"] == 0
        assert result["summary"]["audit_positions_analyzed"] == 2
        assert result["exit_price_audit"].parameters[
            "source_lifecycle_run_id"
        ] == lifecycle.run_id
        assert result["exit_price_audit"].readiness_status == "READY"
        assert result["safety"]["transactions_signed"] is False
        assert result["safety"]["transactions_submitted"] is False
        assert len(client.calls) == 4
        assert db.query(CandidateTokenCompatibility).count() == 2
    finally:
        db.close()
        engine.dispose()


def test_refresh_is_partial_when_token_budget_is_lower_than_open_tokens():
    engine, db = make_db()
    try:
        lifecycle = add_lifecycle(db, tokens=[TOKEN_A, TOKEN_B])

        result = refresh_candidate_open_position_exitability(
            db,
            wallet_address=WALLET,
            lifecycle_run_id=lifecycle.run_id,
            max_tokens=1,
            force_refresh=True,
            jupiter_client=FakeJupiter(),
            now=NOW,
        )

        assert result["status"] == "PARTIAL"
        assert result["summary"]["tokens_selected"] == 1
        assert result["summary"]["tokens_not_selected"] == 1
        assert result["summary"]["audit_cache_missing"] == 1
        assert result["exit_price_audit"].summary[
            "positions_analyzed"
        ] == 2
    finally:
        db.close()
        engine.dispose()
