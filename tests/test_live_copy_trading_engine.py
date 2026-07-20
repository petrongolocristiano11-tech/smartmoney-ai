from datetime import (
    datetime,
    timezone,
)

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import (
    sessionmaker,
)
from sqlalchemy.pool import StaticPool

from backend.app.database.base import Base
from backend.app.models.live_copy_order import (
    LiveCopyOrder,
)
from backend.app.models.live_position import (
    LivePosition,
)
from backend.app.models.trade import Trade
from backend.app.services.jupiter_swap_client import (
    JupiterOrderResult,
)
from backend.app.services.live_copy_trading_engine import (
    close_dry_run_position,
    execute_source_trade,
)
from backend.app.services.live_trading_errors import (
    LiveTradingError,
)
from backend.app.services.live_trading_policy_service import (
    get_or_create_live_policy,
)


WALLET = "W" * 32
TOKEN = "T" * 32


class FakeJupiter:
    def get_order(
        self,
        **kwargs,
    ):
        amount = kwargs[
            "amount_raw"
        ]

        output = (
            2_000_000
            if kwargs[
                "input_mint"
            ].startswith(
                "So111"
            )
            else 40_000_000
        )

        return JupiterOrderResult(
            raw={
                "requestId":
                    "request-1",
                "transaction":
                    None,
                "inAmount":
                    str(amount),
                "outAmount":
                    str(output),
                "slippageBps":
                    20,
                "router":
                    "iris",
                "priceImpact":
                    0.1,
            },
            request_id="request-1",
            transaction=None,
            in_amount=amount,
            out_amount=output,
            slippage_bps=20,
            router="iris",
            price_impact_percent=0.1,
            last_valid_block_height=None,
        )


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={
            "check_same_thread": False,
        },
        poolclass=StaticPool,
    )

    Base.metadata.create_all(
        engine
    )

    session = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )()

    yield session

    session.close()
    engine.dispose()


def configure_policy(
    db,
):
    policy = (
        get_or_create_live_policy(
            db
        )
    )

    policy.mode = "DRY_RUN"

    policy.source_wallets = [
        WALLET
    ]

    policy.fixed_buy_size_sol = 0.05
    policy.max_order_size_sol = 0.1
    policy.max_daily_buy_sol = 0.5
    policy.max_total_exposure_sol = 0.5
    policy.min_source_trade_sol = 0.01

    db.commit()

    return policy


def create_trade(
    db,
    *,
    signature="source-1",
    side="BUY",
):
    trade = Trade(
        signature=signature,
        wallet_address=WALLET,
        side=side,
        token_mint=TOKEN,
        token_amount=100,
        sol_amount=0.2,
        success=True,
        block_time=datetime.now(
            timezone.utc
        ),
    )

    db.add(trade)
    db.commit()
    db.refresh(trade)

    return trade


def test_dry_run_buy_is_idempotent_and_creates_position(
    db,
):
    configure_policy(
        db
    )

    trade = create_trade(
        db
    )

    first = execute_source_trade(
        db,
        trade=trade,
        jupiter_client=(
            FakeJupiter()
        ),
    )

    second = execute_source_trade(
        db,
        trade=trade,
        jupiter_client=(
            FakeJupiter()
        ),
    )

    assert first.status == "DRY_RUN"
    assert first.id == second.id

    assert (
        db.query(
            LivePosition
        ).count()
        == 1
    )

    position = (
        db.query(
            LivePosition
        ).one()
    )

    assert (
        position.mode
        == "DRY_RUN"
    )

    assert (
        int(
            position.quantity_raw
        )
        == 2_000_000
    )

    assert (
        position.cost_basis_sol
        == pytest.approx(0.05)
    )


def test_dry_run_sell_closes_half_and_records_pnl(
    db,
):
    configure_policy(
        db
    )

    buy = create_trade(
        db
    )

    execute_source_trade(
        db,
        trade=buy,
        jupiter_client=(
            FakeJupiter()
        ),
    )

    policy = (
        get_or_create_live_policy(
            db
        )
    )

    policy.sell_position_percentage = (
        50
    )

    db.commit()

    sell = create_trade(
        db,
        signature="source-2",
        side="SELL",
    )

    order = execute_source_trade(
        db,
        trade=sell,
        jupiter_client=(
            FakeJupiter()
        ),
    )

    position = (
        db.query(
            LivePosition
        ).one()
    )

    assert order.status == "DRY_RUN"

    assert (
        int(
            position.quantity_raw
        )
        == 1_000_000
    )

    assert (
        position.cost_basis_sol
        == pytest.approx(0.025)
    )

    assert (
        order.realized_pnl_sol
        == pytest.approx(0.015)
    ) 

def test_manual_dry_run_close_closes_position_and_is_idempotent(
    db,
):
    configure_policy(db)

    buy = create_trade(db)

    execute_source_trade(
        db,
        trade=buy,
        jupiter_client=FakeJupiter(),
    )

    position = (
        db.query(LivePosition)
        .one()
    )

    first = close_dry_run_position(
        db,
        position_id=position.id,
        jupiter_client=FakeJupiter(),
    )

    second = close_dry_run_position(
        db,
        position_id=position.id,
        jupiter_client=FakeJupiter(),
    )

    db.refresh(position)

    assert first.id == second.id
    assert first.status == "DRY_RUN"
    assert first.source_side == "SELL"
    assert first.source_trade_id is None
    assert first.source_wallet == WALLET
    assert first.realized_pnl_sol == pytest.approx(
        -0.01
    )

    assert position.status == "CLOSED"
    assert int(position.quantity_raw) == 0
    assert position.cost_basis_sol == 0
    assert position.realized_pnl_sol == pytest.approx(
        -0.01
    )

    assert (
        db.query(LiveCopyOrder).count()
        == 2
    )


def test_manual_dry_run_close_requires_stream_disabled(
    db,
):
    policy = configure_policy(db)

    buy = create_trade(db)

    execute_source_trade(
        db,
        trade=buy,
        jupiter_client=FakeJupiter(),
    )

    position = db.query(LivePosition).one()

    policy.stream_execution_enabled = True
    db.commit()

    with pytest.raises(
        LiveTradingError
    ) as error_info:
        close_dry_run_position(
            db,
            position_id=position.id,
            jupiter_client=FakeJupiter(),
        )

    assert (
        error_info.value.code
        == "STREAM_MUST_BE_DISABLED"
    )


def test_token_safety_rejects_unsafe_dry_run_buy(
    db,
):
    from backend.app.models.token_safety_snapshot import TokenSafetySnapshot
    from backend.app.services.live_platform_config_service import get_or_create_platform_config

    configure_policy(db)
    config = get_or_create_platform_config(db)
    config.token_safety_enabled = True
    config.token_safety_fail_closed = True
    config.min_token_liquidity_usd = 10_000
    config.max_token_risk_score = 60

    db.add(
        TokenSafetySnapshot(
            token_mint=TOKEN,
            liquidity_usd=100,
            market_cap_usd=1_000,
            volume_24h_usd=50,
            top_holder_percent=90,
            risk_score=95,
            honeypot=True,
            mint_authority_enabled=True,
            freeze_authority_enabled=True,
            source="TEST",
            reasons=["UNSAFE"],
        )
    )
    db.commit()

    order = execute_source_trade(
        db,
        trade=create_trade(db, signature="unsafe-buy"),
        jupiter_client=FakeJupiter(),
    )

    assert order.status == "REJECTED"
    assert order.error_code == "TOKEN_SAFETY_REJECTED"
    assert db.query(LivePosition).count() == 0


def test_live_execution_requires_active_arm_window(
    db,
    monkeypatch,
):
    from backend.app.core.config import settings

    policy = configure_policy(db)
    policy.mode = "LIVE"
    db.commit()

    monkeypatch.setattr(settings, "LIVE_TRADING_API_KEY", "k" * 40)
    monkeypatch.setattr(settings, "JUPITER_API_KEY", "jupiter")
    monkeypatch.setattr(settings, "LIVE_TRADING_WALLET_ADDRESS", WALLET)
    monkeypatch.setattr(settings, "LIVE_TRADING_PRIVATE_KEY", "configured")

    order = execute_source_trade(
        db,
        trade=create_trade(db, signature="live-not-armed"),
        jupiter_client=FakeJupiter(),
    )

    assert order.status == "REJECTED"
    assert order.error_code == "LIVE_NOT_ARMED"


def test_live_execution_simulates_before_submit(
    db,
    monkeypatch,
):
    from datetime import timedelta

    from backend.app.core.config import settings
    from backend.app.models.live_platform_config import LivePlatformConfig
    from backend.app.services.jupiter_swap_client import (
        JupiterExecuteResult,
        JupiterOrderResult,
    )
    from backend.app.services.live_platform_config_service import utc_now

    class LiveJupiter:
        def get_order(self, **kwargs):
            return JupiterOrderResult(
                raw={"requestId": "live-request", "transaction": "unsigned"},
                request_id="live-request",
                transaction="unsigned",
                in_amount=kwargs["amount_raw"],
                out_amount=2_000_000,
                slippage_bps=20,
                router="iris",
                price_impact_percent=0.1,
                last_valid_block_height="123",
            )

        def execute_order(self, **kwargs):
            assert kwargs["signed_transaction"] == "signed"
            return JupiterExecuteResult(
                raw={"status": "Success", "signature": "chain-signature"},
                success=True,
                signature="chain-signature",
                code=0,
                error=None,
                input_amount=50_000_000,
                output_amount=2_000_000,
            )

    class LiveRpc:
        simulated = False

        def get_balance_sol(self, address):
            return 10.0

        def simulate_transaction_base64(self, transaction):
            assert transaction == "signed"
            self.simulated = True
            return {"units_consumed": 999, "logs": ["ok"]}

    class LiveSigner:
        def sign_base64_versioned_transaction(self, transaction):
            assert transaction == "unsigned"
            return "signed"

    policy = configure_policy(db)
    policy.mode = "LIVE"
    db.add(
        LivePlatformConfig(
            name="default",
            token_safety_enabled=False,
            live_armed_until=utc_now() + timedelta(minutes=15),
        )
    )
    db.commit()

    monkeypatch.setattr(settings, "LIVE_TRADING_API_KEY", "k" * 40)
    monkeypatch.setattr(settings, "JUPITER_API_KEY", "jupiter")
    monkeypatch.setattr(settings, "LIVE_TRADING_WALLET_ADDRESS", WALLET)
    monkeypatch.setattr(settings, "LIVE_TRADING_PRIVATE_KEY", "configured")
    monkeypatch.setattr(settings, "LIVE_TRADING_REQUIRE_SIMULATION", True)

    rpc = LiveRpc()
    order = execute_source_trade(
        db,
        trade=create_trade(db, signature="live-simulated"),
        jupiter_client=LiveJupiter(),
        rpc_client=rpc,
        signer=LiveSigner(),
    )

    assert rpc.simulated is True
    assert order.status == "FILLED"
    assert order.transaction_signature == "chain-signature"
    assert order.order_response["simulation"]["units_consumed"] == 999
