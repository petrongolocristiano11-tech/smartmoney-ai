from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.database.base import Base
from backend.app.models.candidate_history_backfill import CandidateHistoryBackfillRun
from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.models.trade import Trade
from backend.app.services import candidate_history_service as history


NOW = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
WALLET = "H" * 32
TOKEN = "M" * 32


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    session.add(
        DiscoveredWallet(
            wallet_address=WALLET,
            smart_score=85,
            quality_classification="COPIABILE",
            quality_eligible=True,
            activity_classification="ATTIVO",
            activity_eligible=True,
        )
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def transaction(signature: str, at: datetime, *, side: str = "BUY") -> dict:
    swap = {
        "tokenInputs": [],
        "tokenOutputs": [],
        "nativeInput": None,
        "nativeOutput": None,
    }
    if side == "BUY":
        swap["nativeInput"] = {"account": WALLET, "amount": "50000000"}
        swap["tokenOutputs"] = [
            {
                "userAccount": WALLET,
                "mint": TOKEN,
                "rawTokenAmount": {"tokenAmount": "1000000", "decimals": 6},
            }
        ]
    else:
        swap["nativeOutput"] = {"account": WALLET, "amount": "60000000"}
        swap["tokenInputs"] = [
            {
                "userAccount": WALLET,
                "mint": TOKEN,
                "rawTokenAmount": {"tokenAmount": "1000000", "decimals": 6},
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
        "events": {"swap": swap},
    }


def build_page(prefix: str, count: int, start_days_ago: int) -> list[dict]:
    return [
        transaction(
            f"{prefix}-{index}",
            NOW - timedelta(days=start_days_ago, minutes=index),
            side="BUY" if index % 2 == 0 else "SELL",
        )
        for index in range(count)
    ]


def test_extended_history_paginates_with_before_signature_and_imports(db, monkeypatch):
    first = build_page("p1", 10, 2)
    second = build_page("p2", 5, 12)
    calls = []

    def fake_history(address, **kwargs):
        calls.append((address, kwargs))
        if len(calls) == 1:
            return first
        if len(calls) == 2:
            return second
        return []

    monkeypatch.setattr(history, "get_wallet_history", fake_history)
    monkeypatch.setattr(history, "_recalculate_wallet", lambda *_args, **_kwargs: None)

    run = history.run_extended_candidate_history(
        db,
        wallet_address=WALLET,
        lookback_days=30,
        max_helius_requests=3,
        page_size=10,
        now=NOW,
    )

    assert run.status == "COMPLETED"
    assert run.stop_reason == "LAST_PAGE"
    assert run.helius_requests == 3
    assert run.pages_fetched == 2
    assert run.trades_imported == 15
    assert calls[0][1]["before_signature"] is None
    assert calls[1][1]["before_signature"] == first[-1]["signature"]
    assert calls[0][1]["max_retries"] == 0
    assert db.query(Trade).count() == 15

    wallet = db.query(DiscoveredWallet).filter_by(wallet_address=WALLET).one()
    assert wallet.extended_history_status == "COMPLETED"
    assert wallet.extended_history_helius_requests == 3
    assert wallet.extended_history_trades_imported == 15
    assert db.query(CandidateHistoryBackfillRun).count() == 1


def test_extended_history_stops_at_request_budget(db, monkeypatch):
    calls = []

    def fake_history(_address, **kwargs):
        calls.append(kwargs)
        page_number = len(calls)
        return build_page(f"budget-{page_number}", 10, page_number * 2)

    monkeypatch.setattr(history, "get_wallet_history", fake_history)
    monkeypatch.setattr(history, "_recalculate_wallet", lambda *_args, **_kwargs: None)

    run = history.run_extended_candidate_history(
        db,
        wallet_address=WALLET,
        lookback_days=60,
        max_helius_requests=2,
        page_size=10,
        now=NOW,
    )

    assert run.status == "PARTIAL"
    assert run.stop_reason == "REQUEST_BUDGET_EXHAUSTED"
    assert run.helius_requests == 2
    assert run.trades_imported == 20
    assert len(calls) == 2


def test_extended_history_deduplicates_overlapping_pages(db, monkeypatch):
    first = build_page("dup-a", 10, 2)
    second = [first[-1], *build_page("dup-b", 4, 8)]
    pages = iter((first, second))

    monkeypatch.setattr(history, "get_wallet_history", lambda *_args, **_kwargs: next(pages))
    monkeypatch.setattr(history, "_recalculate_wallet", lambda *_args, **_kwargs: None)

    run = history.run_extended_candidate_history(
        db,
        wallet_address=WALLET,
        lookback_days=30,
        max_helius_requests=3,
        page_size=10,
        now=NOW,
    )

    assert run.duplicate_transactions == 1
    assert run.trades_imported == 14
    assert db.query(Trade).count() == 14


def test_extended_history_rejects_suspicious_without_force(db):
    wallet = db.query(DiscoveredWallet).filter_by(wallet_address=WALLET).one()
    wallet.quality_classification = "SOSPETTO"
    db.commit()

    with pytest.raises(ValueError, match="COPIABILE"):
        history.run_extended_candidate_history(
            db,
            wallet_address=WALLET,
            now=NOW,
        )


def test_extended_history_preserves_completed_pages_on_later_failure(db, monkeypatch):
    first = build_page("partial", 10, 2)
    calls = 0

    def fake_history(_address, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return first
        from backend.app.services.helius import HeliusRequestError

        raise HeliusRequestError(
            message="Helius temporaneamente non disponibile.",
            endpoint="https://mainnet.helius-rpc.com/v0/addresses/test/transactions",
            status_code=503,
            retryable=True,
            attempts=1,
            error_code="HELIUS_HTTP_ERROR",
        )

    monkeypatch.setattr(history, "get_wallet_history", fake_history)
    monkeypatch.setattr(history, "_recalculate_wallet", lambda *_args, **_kwargs: None)

    run = history.run_extended_candidate_history(
        db,
        wallet_address=WALLET,
        lookback_days=30,
        max_helius_requests=3,
        page_size=10,
        now=NOW,
    )

    assert run.status == "PARTIAL"
    assert run.stop_reason == "FAILED"
    assert run.error_code == "HELIUS_HTTP_ERROR"
    assert run.trades_imported == 10
    assert db.query(Trade).count() == 10


def test_extended_history_follows_filter_continuation_signature(db, monkeypatch):
    from backend.app.services.helius import HeliusRequestError

    page = build_page("continued", 4, 15)
    calls = []

    def fake_history(_address, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise HeliusRequestError(
                message="Continuazione richiesta.",
                endpoint="https://mainnet.helius-rpc.com/v0/addresses/test/transactions",
                status_code=400,
                retryable=True,
                attempts=1,
                error_code="HELIUS_CONTINUATION_REQUIRED",
                continuation_signature="C" * 64,
            )
        if len(calls) == 2:
            return page
        return []

    monkeypatch.setattr(history, "get_wallet_history", fake_history)
    monkeypatch.setattr(history, "_recalculate_wallet", lambda *_args, **_kwargs: None)

    run = history.run_extended_candidate_history(
        db,
        wallet_address=WALLET,
        lookback_days=30,
        max_helius_requests=3,
        page_size=10,
        now=NOW,
    )

    assert run.status == "COMPLETED"
    assert run.stop_reason == "LAST_PAGE"
    assert run.helius_requests == 3
    assert run.pages_fetched == 1
    assert run.trades_imported == 4
    assert calls[1]["before_signature"] == "C" * 64


def test_extended_history_counts_failed_request_after_completed_page(db, monkeypatch):
    from backend.app.services.helius import HeliusRequestError

    first = build_page("count-failure", 10, 2)
    calls = 0

    def fake_history(_address, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return first
        raise HeliusRequestError(
            message="Errore Helius.",
            endpoint="https://mainnet.helius-rpc.com/v0/addresses/test/transactions",
            status_code=503,
            retryable=True,
            attempts=1,
            error_code="HELIUS_HTTP_ERROR",
        )

    monkeypatch.setattr(history, "get_wallet_history", fake_history)
    monkeypatch.setattr(history, "_recalculate_wallet", lambda *_args, **_kwargs: None)

    run = history.run_extended_candidate_history(
        db,
        wallet_address=WALLET,
        lookback_days=30,
        max_helius_requests=3,
        page_size=10,
        now=NOW,
    )

    assert run.status == "PARTIAL"
    assert run.helius_requests == 2
    assert run.pages_fetched == 1
    assert run.trades_imported == 10


def test_helius_filtered_history_extracts_continuation_signature(monkeypatch):
    import httpx

    from backend.app.services import helius
    from backend.app.services.helius import HeliusRequestError

    continuation = "7" * 64
    response = httpx.Response(
        400,
        json={
            "error": (
                "Failed to find events. Continue with the before-signature "
                f"parameter set to {continuation}."
            )
        },
        request=httpx.Request("GET", "https://mainnet.helius-rpc.com/test"),
    )
    monkeypatch.setattr(helius.httpx, "request", lambda *_args, **_kwargs: response)

    with pytest.raises(HeliusRequestError) as error:
        helius.get_wallet_history(
            WALLET,
            transaction_type="SWAP",
            max_retries=0,
        )

    assert error.value.error_code == "HELIUS_CONTINUATION_REQUIRED"
    assert error.value.continuation_signature == continuation
    assert error.value.retryable is True
