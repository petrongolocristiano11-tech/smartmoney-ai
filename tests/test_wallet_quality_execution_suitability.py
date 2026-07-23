from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database.base import Base
from backend.app.models.trade import Trade
from backend.app.services.wallet_activity_service import analyze_wallet_activity
from backend.app.services.wallet_quality_service import analyze_wallet_quality


NOW = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
WALLET = "Q" * 32
TOKEN_A = "A" * 32
TOKEN_B = "B" * 32


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


def add_trade(db, index, *, side, sol, at, token=TOKEN_A):
    db.add(
        Trade(
            signature=f"quality-{index}",
            wallet_address=WALLET,
            side=side,
            source="TEST",
            token_mint=token,
            token_amount=100,
            sol_amount=sol,
            success=True,
            block_time=at,
        )
    )


def test_balanced_meaningful_wallet_is_copyable(db):
    rows = [
        ("BUY", 0.10, NOW - timedelta(hours=2), TOKEN_A),
        ("SELL", 0.12, NOW - timedelta(hours=5), TOKEN_A),
        ("BUY", 0.08, NOW - timedelta(days=1), TOKEN_B),
        ("SELL", 0.09, NOW - timedelta(days=1, hours=2), TOKEN_B),
        ("BUY", 0.06, NOW - timedelta(days=2), TOKEN_A),
        ("SELL", 0.07, NOW - timedelta(days=2, hours=1), TOKEN_A),
    ]
    for index, (side, sol, at, token) in enumerate(rows):
        add_trade(db, index, side=side, sol=sol, at=at, token=token)
    db.commit()

    activity = analyze_wallet_activity(db, WALLET, now=NOW)
    quality = analyze_wallet_quality(
        db,
        WALLET,
        smart_score=82,
        activity=activity,
        now=NOW,
    )

    assert activity["activity_classification"] == "ATTIVO"
    assert quality["quality_classification"] == "COPIABILE"
    assert quality["quality_eligible"] is True
    assert quality["dust_ratio_7d"] == 0
    assert quality["median_swap_sol_7d"] == pytest.approx(0.085)
    assert quality["unique_tokens_7d"] == 2
    assert quality["completed_token_pairs_7d"] == 2
    assert quality["size_compatibility_ratio_7d"] == 1


def test_dust_buy_only_wallet_is_suspicious(db):
    for index in range(20):
        add_trade(
            db,
            index,
            side="BUY",
            sol=0.0001,
            at=NOW - timedelta(hours=index * 3),
            token=TOKEN_A if index % 2 == 0 else TOKEN_B,
        )
    db.commit()

    activity = analyze_wallet_activity(db, WALLET, now=NOW)
    quality = analyze_wallet_quality(
        db,
        WALLET,
        smart_score=90,
        activity=activity,
        now=NOW,
    )

    assert quality["quality_classification"] == "SOSPETTO"
    assert quality["quality_eligible"] is False
    assert quality["dust_ratio_7d"] == 1
    assert quality["size_compatibility_ratio_7d"] == 0
    assert "ONE_SIDED_SWAP_PATTERN" in quality["quality_reasons"]
    assert "DUST_RATIO_HIGH" in quality["quality_reasons"]


def test_low_activity_wallet_remains_observation(db):
    add_trade(db, 1, side="BUY", sol=0.1, at=NOW - timedelta(hours=8))
    add_trade(db, 2, side="SELL", sol=0.12, at=NOW - timedelta(hours=7))
    db.commit()

    activity = analyze_wallet_activity(db, WALLET, now=NOW)
    quality = analyze_wallet_quality(
        db,
        WALLET,
        smart_score=80,
        activity=activity,
        now=NOW,
    )

    assert activity["activity_classification"] == "POCO_ATTIVO"
    assert quality["quality_classification"] == "OSSERVAZIONE"
    assert quality["quality_eligible"] is False
    assert "LOW_RECENT_ACTIVITY" in quality["quality_reasons"]


def test_hyperactive_wallet_is_not_copyable(db):
    for index in range(40):
        add_trade(
            db,
            index,
            side="BUY" if index % 2 == 0 else "SELL",
            sol=0.05,
            at=NOW - timedelta(minutes=index * 10),
            token=TOKEN_A if index % 2 == 0 else TOKEN_B,
        )
    db.commit()

    activity = analyze_wallet_activity(db, WALLET, now=NOW)
    quality = analyze_wallet_quality(
        db,
        WALLET,
        smart_score=95,
        activity=activity,
        now=NOW,
    )

    assert activity["activity_classification"] == "IPERATTIVO"
    assert quality["quality_classification"] == "NON_COPIABILE"
    assert quality["quality_eligible"] is False
    assert "HYPERACTIVE_WALLET" in quality["quality_reasons"]
