import httpx
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.core.config import settings
from backend.app.database.base import Base
from backend.app.services.live_platform_config_service import (
    get_or_create_platform_config,
    is_live_armed,
)
from backend.app.services.live_readiness_service import (
    arm_live_platform,
    build_live_readiness,
)
from backend.app.services.live_trading_errors import LiveTradingError, SolanaRpcError
from backend.app.services.live_trading_policy_service import (
    engage_kill_switch,
    get_or_create_live_policy,
    update_live_policy,
)
from backend.app.services.solana_rpc import SolanaRpcClient


WALLET = "W" * 32
SOURCE = "S" * 32


class FakeSigner:
    wallet_address = WALLET


class FakeRpc:
    def get_balance_sol(self, address):
        assert address == WALLET
        return 2.0


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


def configure_live(monkeypatch, db):
    monkeypatch.setattr(settings, "LIVE_TRADING_API_KEY", "k" * 40)
    monkeypatch.setattr(settings, "JUPITER_API_KEY", "jupiter")
    monkeypatch.setattr(settings, "LIVE_TRADING_WALLET_ADDRESS", WALLET)
    monkeypatch.setattr(settings, "LIVE_TRADING_PRIVATE_KEY", "configured-secret")
    monkeypatch.setattr(settings, "LIVE_TRADING_REQUIRE_SIMULATION", True)

    policy = get_or_create_live_policy(db)
    policy.mode = "LIVE"
    policy.kill_switch = False
    policy.source_wallets = [SOURCE]
    policy.fixed_buy_size_sol = 0.05
    policy.max_order_size_sol = 0.1
    policy.min_wallet_reserve_sol = 0.05

    config = get_or_create_platform_config(db)
    config.token_safety_enabled = True
    config.token_safety_fail_closed = True
    config.live_arm_ttl_minutes = 15
    db.commit()
    return policy, config


def test_live_readiness_requires_exact_confirmation_and_expires_by_disarm(monkeypatch, db):
    policy, config = configure_live(monkeypatch, db)

    readiness = build_live_readiness(db, rpc_client=FakeRpc(), signer=FakeSigner())
    assert readiness["ready"] is True
    assert readiness["armed"] is False

    with pytest.raises(LiveTradingError) as invalid:
        arm_live_platform(
            db,
            confirmation="ARM",
            rpc_client=FakeRpc(),
            signer=FakeSigner(),
        )
    assert invalid.value.code == "LIVE_ARM_CONFIRMATION_REQUIRED"

    result = arm_live_platform(
        db,
        confirmation="ARM LIVE FOR 15 MINUTES",
        rpc_client=FakeRpc(),
        signer=FakeSigner(),
    )
    assert result["armed"] is True
    assert is_live_armed(config) is True

    update_live_policy(db, policy, {"mode": "DRY_RUN"})
    db.refresh(config)
    assert is_live_armed(config) is False


def test_kill_switch_disarms_existing_live_window(monkeypatch, db):
    policy, config = configure_live(monkeypatch, db)
    arm_live_platform(
        db,
        confirmation="ARM LIVE FOR 15 MINUTES",
        rpc_client=FakeRpc(),
        signer=FakeSigner(),
    )

    engage_kill_switch(db, policy, reason="test")
    db.refresh(config)
    assert config.live_armed_until is None
    assert policy.stream_execution_enabled is False


def test_solana_simulation_success_and_failure():
    def success_handler(request):
        body = request.content.decode("utf-8")
        assert "simulateTransaction" in body
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "value": {
                        "err": None,
                        "logs": ["ok"],
                        "unitsConsumed": 1234,
                    }
                },
            },
        )

    client = SolanaRpcClient(
        rpc_url="https://rpc.test",
        transport=httpx.MockTransport(success_handler),
    )
    result = client.simulate_transaction_base64("dGVzdA==")
    assert result["units_consumed"] == 1234
    assert result["logs"] == ["ok"]

    def failure_handler(request):
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "result": {
                    "value": {
                        "err": {"InstructionError": [0, "Custom"]},
                        "logs": ["failed"],
                    }
                },
            },
        )

    failing_client = SolanaRpcClient(
        rpc_url="https://rpc.test",
        transport=httpx.MockTransport(failure_handler),
    )
    with pytest.raises(SolanaRpcError) as error:
        failing_client.simulate_transaction_base64("dGVzdA==")
    assert error.value.code == "SOLANA_SIMULATION_FAILED"
