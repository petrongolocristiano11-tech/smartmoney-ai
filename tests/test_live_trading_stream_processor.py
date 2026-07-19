from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import (
    sessionmaker,
)
from sqlalchemy.pool import StaticPool

from backend.app.core.constants import (
    SOL_MINT,
)
from backend.app.database.base import Base
from backend.app.models.trade import Trade
from backend.app.services.live_trading_stream_processor import (
    process_live_signature,
)


WALLET = "W" * 32
OTHER_WALLET = "A" * 32
TOKEN = "T" * 32


@pytest.fixture()
def session_factory():
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

    factory = sessionmaker(
        bind=engine,
        expire_on_commit=False,
    )

    yield factory

    engine.dispose()


def build_swap(
    *,
    fee_payer=WALLET,
):
    return {
        "type": "SWAP",
        "signature": "signature-1",
        "timestamp": 1_800_000_000,
        "source": "JUPITER",
        "fee": 5000,
        "feePayer": fee_payer,
        "transactionError": None,
        "description": "test swap",
        "nativeTransfers": [],
        "tokenTransfers": [
            {
                "mint": SOL_MINT,
                "tokenAmount": 0.2,
                "fromUserAccount":
                    fee_payer,
                "toUserAccount":
                    OTHER_WALLET,
            },
            {
                "mint": TOKEN,
                "tokenAmount": 100,
                "fromUserAccount":
                    OTHER_WALLET,
                "toUserAccount":
                    fee_payer,
            },
        ],
    }


def test_matching_swap_is_stored_and_executed(
    session_factory,
):
    executed = {}

    def fake_executor(
        db,
        *,
        trade,
        origin,
    ):
        executed["trade_id"] = (
            trade.id
        )

        executed["origin"] = origin

        return SimpleNamespace(
            id=99,
            mode="DRY_RUN",
            status="DRY_RUN",
        )

    result = process_live_signature(
        "signature-1",
        WALLET,
        session_factory=(
            session_factory
        ),
        enhanced_transaction_provider=(
            lambda signature: [
                build_swap()
            ]
        ),
        order_executor=fake_executor,
    )

    assert result.outcome == "ORDER"
    assert result.order_id == 99
    assert executed["origin"] == "STREAM"

    db = session_factory()

    try:
        trade = (
            db.query(Trade)
            .one()
        )

        assert trade.side == "BUY"
        assert trade.token_mint == TOKEN
        assert trade.wallet_address == WALLET

    finally:
        db.close()


def test_swap_from_different_fee_payer_is_skipped(
    session_factory,
):
    result = process_live_signature(
        "signature-1",
        WALLET,
        session_factory=(
            session_factory
        ),
        enhanced_transaction_provider=(
            lambda signature: [
                build_swap(
                    fee_payer=(
                        OTHER_WALLET
                    )
                )
            ]
        ),
        order_executor=lambda *args, **kwargs: (
            pytest.fail(
                "Executor non deve "
                "essere chiamato."
            )
        ),
    )

    assert result.outcome == "SKIPPED"


def test_non_swap_transaction_is_skipped(
    session_factory,
):
    result = process_live_signature(
        "signature-1",
        WALLET,
        session_factory=(
            session_factory
        ),
        enhanced_transaction_provider=(
            lambda signature: [
                {
                    "type": "TRANSFER",
                    "feePayer": WALLET,
                }
            ]
        ),
    )

    assert result.outcome == "SKIPPED" 