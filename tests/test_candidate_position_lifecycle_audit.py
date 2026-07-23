from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database.base import Base
from backend.app.models.candidate_position_lifecycle_audit import (
    CandidatePositionLifecycleAuditRun,
)
from backend.app.models.discovered_wallet import (
    DiscoveredWallet,
)
from backend.app.models.trade import Trade
from backend.app.services import (
    candidate_position_lifecycle_audit_service
    as lifecycle,
)


NOW = datetime(
    2026,
    7,
    23,
    12,
    0,
    tzinfo=timezone.utc,
)
WALLET = "L" * 32


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={
            "check_same_thread": False
        },
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )()
    session.add(
        DiscoveredWallet(
            wallet_address=WALLET,
            smart_score=70,
            activity_classification=(
                "POCO_ATTIVO"
            ),
            quality_classification=(
                "OSSERVAZIONE"
            ),
        )
    )
    session.commit()

    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def add_trade(
    db,
    *,
    signature,
    token,
    side,
    token_amount,
    sol_amount,
    hours_ago,
):
    db.add(
        Trade(
            signature=signature,
            wallet_address=WALLET,
            side=side,
            source="TEST",
            token_mint=token,
            token_amount=token_amount,
            sol_amount=sol_amount,
            success=True,
            block_time=(
                NOW
                - timedelta(
                    hours=hours_ago
                )
            ),
        )
    )


def compatible_cache(
    monkeypatch,
    tokens,
):
    monkeypatch.setattr(
        lifecycle,
        "_latest_jupiter_map",
        lambda *_args, **_kwargs: {
            token: {
                "compatible": True,
                "status": "PASSED",
            }
            for token in tokens
        },
    )


def test_lifecycle_audit_is_cached_only_and_persisted(
    db,
    monkeypatch,
):
    token = "A" * 32
    compatible_cache(
        monkeypatch,
        [token],
    )
    add_trade(
        db,
        signature="buy-a",
        token=token,
        side="BUY",
        token_amount=100,
        sol_amount=0.05,
        hours_ago=48,
    )
    db.commit()

    run = (
        lifecycle
        .run_candidate_position_lifecycle_audit(
            db,
            wallet_address=WALLET,
            now=NOW,
        )
    )

    assert run.status == "COMPLETED"
    assert len(run.scenario_results) == 4
    assert run.safety["cached_data_only"] is True
    assert run.safety["helius_requests"] == 0
    assert run.safety["jupiter_requests"] == 0
    assert run.safety["live_enabled"] is False
    assert run.safety["generation_created"] is False
    assert (
        db.query(
            CandidatePositionLifecycleAuditRun
        ).count()
        == 1
    )


def test_open_position_without_sell_is_classified(
    db,
    monkeypatch,
):
    token = "B" * 32
    compatible_cache(
        monkeypatch,
        [token],
    )
    add_trade(
        db,
        signature="buy-b",
        token=token,
        side="BUY",
        token_amount=100,
        sol_amount=0.05,
        hours_ago=12,
    )
    db.commit()

    run = (
        lifecycle
        .run_candidate_position_lifecycle_audit(
            db,
            wallet_address=WALLET,
            now=NOW,
        )
    )

    assert (
        run.lifecycle_summary[
            "NO_SOURCE_SELL"
        ]
        == 1
    )
    assert (
        run.position_details[0][
            "reason_still_open"
        ]
        == "NO_SOURCE_SELL"
    )


def test_partial_source_exit_leaves_residual(
    db,
    monkeypatch,
):
    token = "C" * 32
    compatible_cache(
        monkeypatch,
        [token],
    )
    add_trade(
        db,
        signature="buy-c",
        token=token,
        side="BUY",
        token_amount=100,
        sol_amount=0.05,
        hours_ago=20,
    )
    add_trade(
        db,
        signature="sell-c-partial",
        token=token,
        side="SELL",
        token_amount=25,
        sol_amount=0.02,
        hours_ago=10,
    )
    db.commit()

    run = (
        lifecycle
        .run_candidate_position_lifecycle_audit(
            db,
            wallet_address=WALLET,
            now=NOW,
        )
    )

    detail = run.position_details[0]

    assert (
        detail["reason_still_open"]
        == "PARTIAL_SOURCE_EXIT"
    )
    assert (
        detail[
            "matched_exit_fraction_percent"
        ]
        == pytest.approx(25.0)
    )
    assert detail["partial_exit_count"] == 1


def test_24h_expiry_frees_capacity(
    db,
    monkeypatch,
):
    tokens = [
        chr(68 + index) * 32
        for index in range(3)
    ]
    compatible_cache(
        monkeypatch,
        tokens,
    )

    add_trade(
        db,
        signature="buy-old-1",
        token=tokens[0],
        side="BUY",
        token_amount=100,
        sol_amount=0.05,
        hours_ago=96,
    )
    add_trade(
        db,
        signature="buy-old-2",
        token=tokens[1],
        side="BUY",
        token_amount=100,
        sol_amount=0.05,
        hours_ago=72,
    )
    add_trade(
        db,
        signature="buy-new",
        token=tokens[2],
        side="BUY",
        token_amount=100,
        sol_amount=0.05,
        hours_ago=12,
    )
    db.commit()

    run = (
        lifecycle
        .run_candidate_position_lifecycle_audit(
            db,
            wallet_address=WALLET,
            max_open_positions=2,
            now=NOW,
        )
    )

    no_expiry = (
        run.scenario_results[0][
            "with_bootstrap"
        ]
    )
    expiry_24h = next(
        row["with_bootstrap"]
        for row in run.scenario_results
        if row["holding_period_hours"] == 24
    )

    assert (
        no_expiry["skipped_max_positions"]
        == 1
    )
    assert expiry_24h["forced_closes"] >= 1
    assert (
        expiry_24h["executed_buys"]
        > no_expiry["executed_buys"]
    )
    assert (
        "STALE_POSITIONS_BLOCKING_CAPACITY"
        in run.diagnoses
    )


def test_unquotable_cache_blocks_forced_close(
    db,
    monkeypatch,
):
    token = "Z" * 32
    monkeypatch.setattr(
        lifecycle,
        "_latest_jupiter_map",
        lambda *_args, **_kwargs: {
            token: {
                "compatible": False,
                "status": "FAILED",
            }
        },
    )
    add_trade(
        db,
        signature="buy-z",
        token=token,
        side="BUY",
        token_amount=100,
        sol_amount=0.05,
        hours_ago=96,
    )
    db.commit()

    run = (
        lifecycle
        .run_candidate_position_lifecycle_audit(
            db,
            wallet_address=WALLET,
            now=NOW,
        )
    )
    expiry_24h = next(
        row["with_bootstrap"]
        for row in run.scenario_results
        if row["holding_period_hours"] == 24
    )

    assert expiry_24h["forced_closes"] == 0
    assert (
        expiry_24h[
            "forced_close_skipped_unquotable"
        ]
        == 1
    )
    assert (
        run.lifecycle_summary[
            "CACHE_UNQUOTABLE"
        ]
        == 1
    )


def test_unknown_wallet_is_rejected(db):
    with pytest.raises(
        ValueError,
        match="Wallet scoperto non trovato",
    ):
        (
            lifecycle
            .run_candidate_position_lifecycle_audit(
                db,
                wallet_address="Q" * 32,
                now=NOW,
            )
        )
