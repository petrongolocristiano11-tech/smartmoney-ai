from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database.base import Base
from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.models.trade import Trade
from backend.app.services import discovery_hydration_service as hydration
from backend.app.services.helius import HeliusRequestError


NOW = datetime(2026, 7, 23, 1, 0, tzinfo=UTC)
WALLET = "A" * 32
TOKEN = "M" * 32


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    yield session
    session.close()
    engine.dispose()


def _transaction(signature: str, at: datetime, *, side: str) -> dict:
    swap_event = {
        "tokenInputs": [],
        "tokenOutputs": [],
        "nativeInput": None,
        "nativeOutput": None,
    }
    if side == "BUY":
        swap_event["nativeInput"] = {
            "account": WALLET,
            "amount": "500000000",
        }
        swap_event["tokenOutputs"] = [
            {
                "userAccount": WALLET,
                "mint": TOKEN,
                "rawTokenAmount": {
                    "tokenAmount": "1000000",
                    "decimals": 6,
                },
            }
        ]
    else:
        swap_event["nativeOutput"] = {
            "account": WALLET,
            "amount": "700000000",
        }
        swap_event["tokenInputs"] = [
            {
                "userAccount": WALLET,
                "mint": TOKEN,
                "rawTokenAmount": {
                    "tokenAmount": "1000000",
                    "decimals": 6,
                },
            }
        ]

    return {
        "type": "SWAP",
        "signature": signature,
        "timestamp": int(at.timestamp()),
        "source": "JUPITER",
        "fee": 5000,
        "feePayer": WALLET,
        "transactionError": None,
        "tokenTransfers": [],
        "nativeTransfers": [],
        "accountData": [],
        "events": {"swap": swap_event},
    }


def _score(wallet_address: str) -> dict:
    return {
        "wallet": wallet_address,
        "smart_score": 82.5,
        "dna": {
            "analytics": {
                "total_roi_percent": 12.0,
                "win_rate_percent": 60.0,
                "total_profit_loss_sol": 1.2,
                "reliable_positions": 4,
            }
        },
    }


def _add_wallet(
    db_session,
    address: str = WALLET,
    score: float = 80,
    *,
    funnel_status: str = "NEEDS_LOCAL_DATA",
    funnel_action: str = "RUN_CONTROLLED_HYDRATION",
    funnel_score: float | None = None,
):
    wallet = DiscoveredWallet(
        wallet_address=address,
        discovered_from_token=TOKEN,
        smart_score=score,
        activity_classification="INATTIVO",
        discovery_funnel_status=funnel_status,
        discovery_funnel_action=funnel_action,
        discovery_funnel_score=(
            score
            if funnel_score is None
            else funnel_score
        ),
    )
    db_session.add(wallet)
    db_session.commit()
    return wallet


def test_hydration_imports_timestamped_swaps_and_refreshes_activity(
    db_session,
    monkeypatch,
):
    _add_wallet(db_session)
    calls = []
    transactions = [
        _transaction("swap-1", NOW - timedelta(hours=2), side="BUY"),
        _transaction("swap-2", NOW - timedelta(hours=8), side="SELL"),
        _transaction("swap-3", NOW - timedelta(days=2), side="BUY"),
        _transaction("swap-4", NOW - timedelta(days=4), side="SELL"),
    ]

    def fake_history(address, **kwargs):
        calls.append((address, kwargs))
        return transactions

    monkeypatch.setattr(hydration, "get_wallet_history", fake_history)
    monkeypatch.setattr(hydration, "calculate_smart_score", lambda _db, address: _score(address))

    result = hydration.run_controlled_discovery_hydration(
        db_session,
        max_wallets=1,
        max_helius_requests=1,
        lookback_days=7,
        transaction_limit=100,
        now=NOW,
    )

    assert result["status"] == "COMPLETED"
    assert result["helius_requests"] == 1
    assert result["retry_attempts_enabled"] is False
    assert result["trades_imported"] == 4
    assert calls[0][1]["max_retries"] == 0
    assert calls[0][1]["transaction_type"] == "SWAP"
    assert calls[0][1]["gte_time"] == int((NOW - timedelta(days=7)).timestamp())

    trades = db_session.query(Trade).order_by(Trade.block_time.asc()).all()
    assert len(trades) == 4
    assert all(trade.block_time is not None for trade in trades)

    wallet = db_session.query(DiscoveredWallet).filter_by(wallet_address=WALLET).one()
    assert wallet.hydration_status == "COMPLETED"
    assert wallet.hydration_swaps_found == 4
    assert wallet.activity_classification == "ATTIVO"
    assert wallet.swaps_24h == 2
    assert wallet.buys_7d == 2
    assert wallet.sells_7d == 2


def test_hydration_is_deduplicated_on_forced_second_run(db_session, monkeypatch):
    _add_wallet(db_session)
    transactions = [
        _transaction("swap-1", NOW - timedelta(hours=2), side="BUY"),
        _transaction("swap-2", NOW - timedelta(days=2), side="SELL"),
        _transaction("swap-3", NOW - timedelta(days=3), side="BUY"),
    ]
    monkeypatch.setattr(hydration, "get_wallet_history", lambda _address, **_kwargs: transactions)
    monkeypatch.setattr(hydration, "calculate_smart_score", lambda _db, address: _score(address))

    first = hydration.run_controlled_discovery_hydration(
        db_session,
        max_wallets=1,
        max_helius_requests=1,
        now=NOW,
    )
    second = hydration.run_controlled_discovery_hydration(
        db_session,
        max_wallets=1,
        max_helius_requests=1,
        force=True,
        now=NOW + timedelta(minutes=5),
    )

    assert first["trades_imported"] == 3
    assert second["trades_imported"] == 0
    assert second["trades_updated"] == 3
    assert db_session.query(Trade).count() == 3


def test_hydration_never_exceeds_request_budget(db_session, monkeypatch):
    for index in range(5):
        _add_wallet(db_session, address=chr(65 + index) * 32, score=90 - index)

    calls = []
    monkeypatch.setattr(
        hydration,
        "get_wallet_history",
        lambda address, **_kwargs: calls.append(address) or [],
    )
    monkeypatch.setattr(hydration, "calculate_smart_score", lambda _db, address: _score(address))

    result = hydration.run_controlled_discovery_hydration(
        db_session,
        max_wallets=5,
        max_helius_requests=2,
        now=NOW,
    )

    assert result["effective_max_wallets"] == 2
    assert result["wallets_attempted"] == 2
    assert result["helius_requests"] == 2
    assert len(calls) == 2
    assert result["wallets_empty"] == 2


def test_hydration_failure_is_persisted_and_run_continues(db_session, monkeypatch):
    _add_wallet(db_session)

    def fail(_address, **_kwargs):
        raise HeliusRequestError(
            message="Helius non disponibile.",
            endpoint="https://mainnet.helius-rpc.com/v0/addresses/test/transactions",
            status_code=503,
            retryable=True,
            attempts=1,
            error_code="HELIUS_HTTP_ERROR",
        )

    monkeypatch.setattr(hydration, "get_wallet_history", fail)

    result = hydration.run_controlled_discovery_hydration(
        db_session,
        max_wallets=1,
        max_helius_requests=1,
        now=NOW,
    )

    assert result["status"] == "FAILED"
    assert result["wallets_failed"] == 1
    assert result["helius_requests"] == 1
    wallet = db_session.query(DiscoveredWallet).filter_by(wallet_address=WALLET).one()
    assert wallet.hydration_status == "FAILED"
    assert wallet.hydration_error_code == "HELIUS_HTTP_ERROR"
    assert "api-key" not in (wallet.hydration_error_message or "").lower()



def test_hydration_skips_terminal_funnel_wallets(
    db_session,
    monkeypatch,
):
    blocked_address = "B" * 32
    target_address = "C" * 32

    _add_wallet(
        db_session,
        address=blocked_address,
        score=99,
        funnel_status="BLOCKED",
        funnel_action="DO_NOT_PROMOTE",
        funnel_score=99,
    )
    _add_wallet(
        db_session,
        address=target_address,
        score=70,
        funnel_status="NEEDS_LOCAL_DATA",
        funnel_action="RUN_CONTROLLED_HYDRATION",
        funnel_score=70,
    )

    calls = []

    monkeypatch.setattr(
        hydration,
        "get_wallet_history",
        lambda address, **_kwargs: (
            calls.append(address) or []
        ),
    )
    monkeypatch.setattr(
        hydration,
        "calculate_smart_score",
        lambda _db, address: _score(address),
    )

    result = hydration.run_controlled_discovery_hydration(
        db_session,
        max_wallets=1,
        max_helius_requests=1,
        now=NOW,
    )

    assert result["wallets_attempted"] == 1
    assert calls == [target_address]
    assert blocked_address not in calls


def test_hydration_prioritizes_funnel_score(
    db_session,
    monkeypatch,
):
    high_smart_address = "D" * 32
    high_funnel_address = "E" * 32

    _add_wallet(
        db_session,
        address=high_smart_address,
        score=95,
        funnel_score=30,
    )
    _add_wallet(
        db_session,
        address=high_funnel_address,
        score=70,
        funnel_score=80,
    )

    calls = []

    monkeypatch.setattr(
        hydration,
        "get_wallet_history",
        lambda address, **_kwargs: (
            calls.append(address) or []
        ),
    )
    monkeypatch.setattr(
        hydration,
        "calculate_smart_score",
        lambda _db, address: _score(address),
    )

    result = hydration.run_controlled_discovery_hydration(
        db_session,
        max_wallets=1,
        max_helius_requests=1,
        now=NOW,
    )

    assert result["wallets_attempted"] == 1
    assert calls == [high_funnel_address]
