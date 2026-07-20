import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database.base import Base
from backend.app.models.token_safety_snapshot import TokenSafetySnapshot
from backend.app.services.jupiter_swap_client import JupiterOrderResult
from backend.app.services.live_platform_config_service import get_or_create_platform_config
from backend.app.services.token_safety_service import (
    TokenMarketMetrics,
    evaluate_token_safety,
    refresh_token_safety_snapshot,
)


TOKEN = "T" * 32


class FakeRpc:
    def call(self, method, params=None):
        if method == "getAccountInfo":
            return {
                "value": {
                    "data": {
                        "parsed": {
                            "info": {
                                "decimals": 6,
                                "mintAuthority": None,
                                "freezeAuthority": None,
                            }
                        }
                    }
                }
            }
        if method == "getTokenSupply":
            return {"value": {"uiAmountString": "1000000"}}
        if method == "getTokenLargestAccounts":
            return {"value": [{"uiAmountString": "100000"}]}
        raise AssertionError(method)


class FakeDex:
    def get_token_metrics(self, token_mint):
        assert token_mint == TOKEN
        return TokenMarketMetrics(
            liquidity_usd=100_000,
            market_cap_usd=2_000_000,
            volume_24h_usd=500_000,
            pair_count=2,
            raw=[],
        )


class FakeJupiter:
    def get_order(self, **kwargs):
        return JupiterOrderResult(
            raw={},
            request_id="safety",
            transaction=None,
            in_amount=kwargs["amount_raw"],
            out_amount=1_000_000,
            slippage_bps=20,
            router="iris",
            price_impact_percent=0.1,
            last_valid_block_height=None,
        )


class FakeRugCheck:
    def get_report(self, token_mint):
        return {"result": "safe", "score": 5, "rugged": False}


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


def test_token_safety_refresh_persists_market_and_onchain_checks(db):
    snapshot = refresh_token_safety_snapshot(
        db,
        token_mint=TOKEN,
        rpc_client=FakeRpc(),
        dex_client=FakeDex(),
        jupiter_client=FakeJupiter(),
        rugcheck_client=FakeRugCheck(),
    )

    assert snapshot.liquidity_usd == 100_000
    assert snapshot.top_holder_percent == pytest.approx(10.0)
    assert snapshot.honeypot is False
    assert snapshot.rugcheck_passed is True
    assert snapshot.risk_score == 5
    assert db.query(TokenSafetySnapshot).count() == 1


def test_token_safety_policy_rejects_unsafe_buy_but_never_blocks_sell(db):
    config = get_or_create_platform_config(db)
    config.token_safety_enabled = True
    config.token_safety_fail_closed = True
    config.min_token_liquidity_usd = 10_000
    config.max_token_risk_score = 60

    snapshot = TokenSafetySnapshot(
        token_mint=TOKEN,
        liquidity_usd=1_000,
        market_cap_usd=100_000,
        volume_24h_usd=100,
        top_holder_percent=80,
        risk_score=95,
        honeypot=True,
        mint_authority_enabled=True,
        freeze_authority_enabled=True,
        source="TEST",
        reasons=["TEST"],
    )

    allowed, reasons = evaluate_token_safety(
        config,
        token_mint=TOKEN,
        snapshot=snapshot,
        side="BUY",
    )
    assert allowed is False
    assert "LIQUIDITY_BELOW_MINIMUM" in reasons
    assert "HONEYPOT_REJECTED" in reasons

    sell_allowed, sell_reasons = evaluate_token_safety(
        config,
        token_mint=TOKEN,
        snapshot=snapshot,
        side="SELL",
    )
    assert sell_allowed is True
    assert sell_reasons == []
