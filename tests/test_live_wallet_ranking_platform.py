from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database.base import Base
from backend.app.models.live_copy_order import LiveCopyOrder
from backend.app.models.wallet_profile import WalletProfile
from backend.app.services.live_platform_config_service import get_or_create_platform_config
from backend.app.services.live_trading_errors import LiveTradingError
from backend.app.services.live_trading_policy_service import get_or_create_live_policy
from backend.app.services.live_wallet_ranking_service import (
    apply_ranked_wallets,
    refresh_live_wallet_ranking,
)


WALLET_HIGH = "H" * 32
WALLET_LOW = "L" * 32
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
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def add_completed_order(db, wallet: str, key: str, side: str, pnl: float = 0.0):
    db.add(
        LiveCopyOrder(
            idempotency_key=key,
            source_signature=key,
            source_wallet=wallet,
            source_side=side,
            source_token_mint=TOKEN,
            mode="DRY_RUN",
            generation=1,
            status="DRY_RUN",
            input_mint=TOKEN,
            output_mint=TOKEN,
            requested_input_amount_raw=Decimal(1),
            requested_value_sol=0.1,
            expected_output_amount_raw=Decimal(1),
            actual_input_amount_raw=Decimal(1),
            actual_output_amount_raw=Decimal(1),
            slippage_bps=20,
            realized_pnl_sol=pnl,
            executed_at=datetime.now(timezone.utc),
        )
    )


def test_ranking_combines_profile_and_live_performance(db):
    policy = get_or_create_live_policy(db)
    policy.source_wallets = [WALLET_HIGH, WALLET_LOW]
    config = get_or_create_platform_config(db)
    config.min_wallet_smart_score = 60
    config.max_source_wallets = 1
    config.min_wallet_closed_trades = 1

    db.add_all([
        WalletProfile(wallet_address=WALLET_HIGH, smart_score=90, roi=20, win_rate=80),
        WalletProfile(wallet_address=WALLET_LOW, smart_score=40, roi=-5, win_rate=20),
    ])
    add_completed_order(db, WALLET_HIGH, "high-buy", "BUY")
    add_completed_order(db, WALLET_HIGH, "high-sell", "SELL", 0.03)
    add_completed_order(db, WALLET_LOW, "low-buy", "BUY")
    add_completed_order(db, WALLET_LOW, "low-sell", "SELL", -0.02)
    db.commit()

    ranking = refresh_live_wallet_ranking(db)

    assert ranking[0].wallet_address == WALLET_HIGH
    assert ranking[0].rank == 1
    assert ranking[0].eligible is True
    assert ranking[1].eligible is False
    assert "OUTSIDE_WALLET_LIMIT" in ranking[1].reasons


def test_apply_ranking_requires_feature_and_confirmation(db):
    policy = get_or_create_live_policy(db)
    policy.source_wallets = [WALLET_HIGH]
    config = get_or_create_platform_config(db)
    config.min_wallet_smart_score = 0
    config.min_wallet_closed_trades = 1
    db.add(WalletProfile(wallet_address=WALLET_HIGH, smart_score=90))
    add_completed_order(db, WALLET_HIGH, "apply-buy", "BUY")
    add_completed_order(db, WALLET_HIGH, "apply-sell", "SELL", 0.01)
    db.commit()

    with pytest.raises(LiveTradingError) as disabled:
        apply_ranked_wallets(db, confirmation="APPLY SMART WALLETS")
    assert disabled.value.code == "AUTO_WALLET_SELECTION_DISABLED"

    config.auto_wallet_selection_enabled = True
    db.commit()

    with pytest.raises(LiveTradingError) as invalid:
        apply_ranked_wallets(db, confirmation="NO")
    assert invalid.value.code == "SMART_WALLET_CONFIRMATION_REQUIRED"

    result = apply_ranked_wallets(db, confirmation="APPLY SMART WALLETS", limit=1)
    assert result["source_wallets"] == [WALLET_HIGH]


def test_ranking_requires_minimum_closed_trade_sample(db):
    policy = get_or_create_live_policy(db)
    policy.source_wallets = [WALLET_HIGH]
    config = get_or_create_platform_config(db)
    config.min_wallet_smart_score = 0
    config.min_wallet_closed_trades = 3
    db.add(WalletProfile(wallet_address=WALLET_HIGH, smart_score=90))
    add_completed_order(db, WALLET_HIGH, "sample-buy", "BUY")
    add_completed_order(db, WALLET_HIGH, "sample-sell", "SELL", 0.01)
    db.commit()

    ranking = refresh_live_wallet_ranking(db)

    assert ranking[0].closed_trades == 1
    assert ranking[0].eligible is False
    assert "LIMITED_LIVE_SAMPLE" in ranking[0].reasons


def test_ranking_response_is_limited_to_fifty_rows(db):
    policy = get_or_create_live_policy(db)
    config = get_or_create_platform_config(db)
    config.min_wallet_smart_score = 0
    config.min_wallet_closed_trades = 1

    wallets = [f"{index:032d}" for index in range(60)]
    policy.source_wallets = wallets
    for index, wallet in enumerate(wallets):
        db.add(
            WalletProfile(
                wallet_address=wallet,
                smart_score=100 - index,
            )
        )
    db.commit()

    ranking = refresh_live_wallet_ranking(db)

    assert len(ranking) == 50
    assert ranking[0].rank == 1
    assert ranking[-1].rank == 50


def test_manual_close_pnl_contributes_to_original_wallet_ranking(db):
    policy = get_or_create_live_policy(db)
    policy.source_wallets = [WALLET_HIGH]
    config = get_or_create_platform_config(db)
    config.min_wallet_smart_score = 0
    config.min_wallet_closed_trades = 1
    db.add(WalletProfile(wallet_address=WALLET_HIGH, smart_score=90))
    add_completed_order(db, WALLET_HIGH, "manual-buy", "BUY")
    add_completed_order(
        db,
        "MANUAL_DRY_RUN_CLOSE",
        "manual-sell",
        "SELL",
        -0.02,
    )
    db.commit()

    ranking = refresh_live_wallet_ranking(db)

    row = next(item for item in ranking if item.wallet_address == WALLET_HIGH)
    assert row.closed_trades == 1
    assert row.realized_pnl_sol == pytest.approx(-0.02)
