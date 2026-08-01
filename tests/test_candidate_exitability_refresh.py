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


def test_refresh_reuses_current_routes_and_retries_only_transient_failures():
    from backend.app.services.live_trading_errors import JupiterSwapError

    class RecoveringRateLimitJupiter:
        def __init__(self):
            self.calls = []
            self.rate_limited_once = False

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
            if (
                output_mint == TOKEN_B
                and not self.rate_limited_once
            ):
                self.rate_limited_once = True
                raise JupiterSwapError(
                    "[API Gateway] Too many requests",
                    code="JUPITER_HTTP_ERROR",
                    status_code=429,
                )
            if input_mint == "So11111111111111111111111111111111111111112":
                return SimpleNamespace(out_amount=max(1, amount_raw * 2))
            return SimpleNamespace(out_amount=max(1, amount_raw // 2))

    engine, db = make_db()
    try:
        lifecycle = add_lifecycle(db, tokens=[TOKEN_A, TOKEN_B])
        db.add_all(
            [
                CandidateTokenCompatibility(
                    token_mint=TOKEN_A,
                    fixed_buy_size_lamports=5_000_000,
                    slippage_bps=100,
                    status="PASSED",
                    buy_quote=True,
                    sell_quote=True,
                    compatible=True,
                    buy_out_amount_raw=10_000_000,
                    sell_out_amount_raw=4_900_000,
                    checked_at=NOW - timedelta(minutes=5),
                    expires_at=NOW + timedelta(hours=6),
                ),
                CandidateTokenCompatibility(
                    token_mint=TOKEN_B,
                    fixed_buy_size_lamports=5_000_000,
                    slippage_bps=100,
                    status="FAILED",
                    buy_quote=False,
                    sell_quote=False,
                    compatible=False,
                    error_code="JUPITER_HTTP_ERROR",
                    error_message="[API Gateway] Too many requests",
                    checked_at=NOW - timedelta(minutes=5),
                    expires_at=NOW + timedelta(hours=6),
                ),
            ]
        )
        db.commit()

        client = RecoveringRateLimitJupiter()
        sleeps = []
        result = refresh_candidate_open_position_exitability(
            db,
            wallet_address=WALLET,
            lifecycle_run_id=lifecycle.run_id,
            force_refresh=True,
            jupiter_client=client,
            now=NOW,
            transient_retry_count=1,
            transient_retry_delay_seconds=0.25,
            sleep_fn=sleeps.append,
        )

        assert result["status"] == "COMPLETED"
        assert result["summary"]["route_found"] == 2
        assert result["summary"]["quote_errors"] == 0
        assert result["summary"]["reused_current_routes"] == 1
        assert result["summary"]["tokens_retried"] == 1
        assert result["summary"]["retry_attempts"] == 1
        assert result["summary"]["transient_errors_seen"] == 1
        assert result["summary"]["requests"] == 3
        assert result["summary"]["cache_hits"] == 1
        assert result["summary"]["audit_current_route_percent"] == 100.0
        assert result["safety"]["current_compatible_cache_preserved"] is True
        assert sleeps == [0.25]
        assert len(client.calls) == 3

        row_a = (
            db.query(CandidateTokenCompatibility)
            .filter_by(token_mint=TOKEN_A)
            .one()
        )
        row_b = (
            db.query(CandidateTokenCompatibility)
            .filter_by(token_mint=TOKEN_B)
            .one()
        )
        assert row_a.checked_at.replace(tzinfo=timezone.utc) == NOW - timedelta(minutes=5)
        assert row_a.compatible is True
        assert row_b.compatible is True
        assert row_b.error_code is None
    finally:
        db.close()
        engine.dispose()
