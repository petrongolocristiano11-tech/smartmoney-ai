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
POOL = "P" * 32
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


def build_wsol_swap(
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
                "fromUserAccount": WALLET,
                "toUserAccount": POOL,
            },
            {
                "mint": TOKEN,
                "tokenAmount": 100,
                "fromUserAccount": POOL,
                "toUserAccount": WALLET,
            },
        ],
    }


def build_native_swap(
    *,
    fee_payer=OTHER_WALLET,
    wallet=WALLET,
):
    return {
        "type": "UNKNOWN",
        "signature": "signature-native",
        "timestamp": 1_800_000_000,
        "source": "PUMP_FUN",
        "fee": 5000,
        "feePayer": fee_payer,
        "transactionError": None,
        "nativeTransfers": [
            {
                "fromUserAccount": wallet,
                "toUserAccount": POOL,
                "amount": 150_000_000,
            }
        ],
        "tokenTransfers": [
            {
                "mint": TOKEN,
                "tokenAmount": 300,
                "fromUserAccount": POOL,
                "toUserAccount": wallet,
            }
        ],
    }


def execute_successfully(
    executed: dict,
):
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

    return fake_executor


def test_matching_wsol_swap_is_stored_and_executed(
    session_factory,
):
    executed = {}

    result = process_live_signature(
        "signature-1",
        WALLET,
        session_factory=(
            session_factory
        ),
        enhanced_transaction_provider=(
            lambda signature: [
                build_wsol_swap()
            ]
        ),
        order_executor=(
            execute_successfully(
                executed
            )
        ),
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


def test_sponsored_native_swap_is_stored_when_fee_payer_differs(
    session_factory,
):
    executed = {}

    result = process_live_signature(
        "signature-native",
        WALLET,
        session_factory=(
            session_factory
        ),
        enhanced_transaction_provider=(
            lambda signature: [
                build_native_swap()
            ]
        ),
        order_executor=(
            execute_successfully(
                executed
            )
        ),
    )

    assert result.outcome == "ORDER"

    db = session_factory()

    try:
        trade = (
            db.query(Trade)
            .one()
        )

        assert trade.wallet_address == WALLET
        assert trade.side == "BUY"
        assert trade.sol_amount == 0.15
        assert trade.token_amount == 300

    finally:
        db.close()


def test_transaction_not_involving_expected_wallet_is_skipped(
    session_factory,
):
    result = process_live_signature(
        "signature-native",
        WALLET,
        session_factory=(
            session_factory
        ),
        enhanced_transaction_provider=(
            lambda signature: [
                build_native_swap(
                    wallet=(
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
        "signature-transfer",
        WALLET,
        session_factory=(
            session_factory
        ),
        enhanced_transaction_provider=(
            lambda signature: [
                {
                    "type": "TRANSFER",
                    "signature": (
                        "signature-transfer"
                    ),
                    "feePayer": WALLET,
                    "transactionError": None,
                    "nativeTransfers": [],
                    "tokenTransfers": [
                        {
                            "mint": TOKEN,
                            "tokenAmount": 1,
                            "fromUserAccount": (
                                OTHER_WALLET
                            ),
                            "toUserAccount": WALLET,
                        }
                    ],
                }
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


def test_failed_swap_is_skipped(
    session_factory,
):
    transaction = build_native_swap()
    transaction[
        "transactionError"
    ] = {
        "error": "failed"
    }

    result = process_live_signature(
        "signature-native",
        WALLET,
        session_factory=(
            session_factory
        ),
        enhanced_transaction_provider=(
            lambda signature: [
                transaction
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
