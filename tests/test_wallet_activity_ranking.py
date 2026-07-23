from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database.base import Base
from backend.app.models.trade import Trade
from backend.app.services.wallet_activity_service import (
    analyze_wallet_activity,
    build_discovery_ranking,
)


WALLET = "A" * 32
NOW = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)


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


def add_trade(db, *, wallet: str, index: int, side: str, at: datetime, sol: float):
    db.add(
        Trade(
            signature=f"{wallet}-{index}",
            wallet_address=wallet,
            side=side,
            source="TEST",
            token_mint="T" * 32,
            token_amount=100,
            sol_amount=sol,
            success=True,
            block_time=at,
        )
    )


def test_active_wallet_metrics_and_ranking(db):
    add_trade(db, wallet=WALLET, index=1, side="BUY", at=NOW - timedelta(hours=2), sol=0.4)
    add_trade(db, wallet=WALLET, index=2, side="SELL", at=NOW - timedelta(hours=8), sol=0.6)
    add_trade(db, wallet=WALLET, index=3, side="BUY", at=NOW - timedelta(days=2), sol=0.3)
    add_trade(db, wallet=WALLET, index=4, side="SELL", at=NOW - timedelta(days=4), sol=0.5)
    db.commit()

    activity = analyze_wallet_activity(db, WALLET, now=NOW)
    ranking = build_discovery_ranking(smart_score=82, activity=activity)

    assert activity["activity_classification"] == "ATTIVO"
    assert activity["swaps_24h"] == 2
    assert activity["swaps_7d"] == 4
    assert activity["buys_7d"] == 2
    assert activity["sells_7d"] == 2
    assert activity["active_days_7d"] == 3
    assert activity["volume_7d_sol"] == pytest.approx(1.8)
    assert activity["activity_eligible"] is True
    assert ranking["eligible"] is True
    assert ranking["ranking_score"] > 60


def test_inactive_wallet_is_excluded(db):
    add_trade(
        db,
        wallet=WALLET,
        index=1,
        side="BUY",
        at=NOW - timedelta(days=8),
        sol=1,
    )
    db.commit()

    activity = analyze_wallet_activity(db, WALLET, now=NOW)
    ranking = build_discovery_ranking(smart_score=95, activity=activity)

    assert activity["activity_classification"] == "INATTIVO"
    assert activity["activity_eligible"] is False
    assert ranking["eligible"] is False
    assert "INACTIVE_WALLET" in ranking["eligibility_reasons"]


def test_hyperactive_wallet_is_excluded(db):
    for index in range(40):
        add_trade(
            db,
            wallet=WALLET,
            index=index,
            side="BUY" if index % 2 == 0 else "SELL",
            at=NOW - timedelta(minutes=index * 10),
            sol=0.05,
        )
    db.commit()

    activity = analyze_wallet_activity(db, WALLET, now=NOW)
    ranking = build_discovery_ranking(smart_score=95, activity=activity)

    assert activity["swaps_24h"] == 40
    assert activity["activity_classification"] == "IPERATTIVO"
    assert activity["activity_eligible"] is False
    assert ranking["eligible"] is False
    assert "HYPERACTIVE_WALLET" in ranking["eligibility_reasons"]


def test_low_activity_remains_rankable_but_penalized(db):
    add_trade(db, wallet=WALLET, index=1, side="BUY", at=NOW - timedelta(hours=6), sol=0.2)
    add_trade(db, wallet=WALLET, index=2, side="SELL", at=NOW - timedelta(hours=5), sol=0.2)
    db.commit()

    activity = analyze_wallet_activity(db, WALLET, now=NOW)
    ranking = build_discovery_ranking(smart_score=75, activity=activity)

    assert activity["activity_classification"] == "POCO_ATTIVO"
    assert activity["activity_eligible"] is True
    assert activity["activity_score"] <= 55
    assert ranking["eligible"] is True
    assert "LOW_RECENT_ACTIVITY" in ranking["eligibility_reasons"]
