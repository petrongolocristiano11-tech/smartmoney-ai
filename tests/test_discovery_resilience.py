from __future__ import annotations

from backend.app.services import discovery_engine
from backend.app.services.helius import HeliusRequestError


class DummySession:
    def __init__(self):
        self.rollback_calls = 0

    def rollback(self):
        self.rollback_calls += 1


def _score(total_trades: int = 2):
    return {
        "dna": {
            "analytics": {
                "total_trades": total_trades,
                "total_roi_percent": 12.5,
                "win_rate_percent": 60.0,
                "total_profit_loss_sol": 1.2,
                "reliable_positions": 4,
            }
        }
    }


def _helius_failure(message: str = "provider unavailable"):
    return HeliusRequestError(
        message=message,
        endpoint="https://api.helius.xyz/v0/test",
        status_code=500,
        retryable=True,
        attempts=4,
        error_code="HELIUS_RETRY_EXHAUSTED",
    )


def test_full_discovery_continues_when_one_discovered_wallet_fails(
    monkeypatch,
):
    db = DummySession()

    def fake_sync(_db, wallet):
        if wallet == "bad-wallet":
            raise _helius_failure()
        return _score()

    monkeypatch.setattr(discovery_engine, "sync_wallet", fake_sync)
    monkeypatch.setattr(
        discovery_engine,
        "get_traded_tokens_by_wallet",
        lambda _db, _wallet: {
            "tokens_found": 1,
            "tokens": ["token-1"],
        },
    )
    monkeypatch.setattr(
        discovery_engine,
        "discover_wallets_from_token_onchain",
        lambda _token: {
            "status": "COMPLETED",
            "wallets_found": 2,
            "wallets": ["good-wallet", "bad-wallet"],
            "errors": [],
        },
    )
    monkeypatch.setattr(
        discovery_engine,
        "build_wallet_profile",
        lambda db, wallet_address: {
            "wallet_address": wallet_address,
            "smart_score": 75.0,
        },
    )
    monkeypatch.setattr(
        discovery_engine,
        "save_discovered_wallet",
        lambda **_kwargs: None,
    )

    result = discovery_engine.discover_full_from_wallet(
        db,
        "seed-wallet",
        max_tokens=1,
        max_wallets_per_token=2,
    )

    assert result["status"] == "PARTIAL"
    assert result["wallets_discovered"] == 2
    assert result["wallets_analyzed"] == 1
    assert result["wallets_failed"] == 1
    assert result["ranking"][0]["wallet_address"] == "good-wallet"
    assert result["errors"][0]["provider"] == "HELIUS"
    assert result["errors"][0]["error_code"] == "HELIUS_RETRY_EXHAUSTED"
    assert db.rollback_calls >= 1


def test_seed_helius_failure_returns_failed_result_instead_of_raising(
    monkeypatch,
):
    db = DummySession()

    monkeypatch.setattr(
        discovery_engine,
        "sync_wallet",
        lambda _db, _wallet: (_ for _ in ()).throw(_helius_failure()),
    )
    monkeypatch.setattr(
        discovery_engine,
        "get_traded_tokens_by_wallet",
        lambda _db, _wallet: {
            "tokens_found": 0,
            "tokens": [],
        },
    )

    result = discovery_engine.discover_full_from_wallet(
        db,
        "seed-wallet",
    )

    assert result["status"] == "FAILED"
    assert result["seed_sync_status"] == "FAILED"
    assert result["ranking"] == []
    assert result["error_count"] == 1
    assert result["errors"][0]["stage"] == "SEED_SYNC"
    assert db.rollback_calls == 1


def test_token_provider_failure_makes_discovery_partial(monkeypatch):
    db = DummySession()

    monkeypatch.setattr(
        discovery_engine,
        "sync_wallet",
        lambda _db, _wallet: _score(),
    )
    monkeypatch.setattr(
        discovery_engine,
        "build_wallet_profile",
        lambda db, wallet_address: {
            "wallet_address": wallet_address,
            "smart_score": 70.0,
        },
    )
    monkeypatch.setattr(
        discovery_engine,
        "get_traded_tokens_by_wallet",
        lambda _db, _wallet: {
            "tokens_found": 1,
            "tokens": ["token-1"],
        },
    )
    monkeypatch.setattr(
        discovery_engine,
        "discover_wallets_from_token_onchain",
        lambda _token: {
            "status": "FAILED",
            "wallets_found": 0,
            "wallets": [],
            "errors": [
                {
                    "stage": "TOKEN_HISTORY",
                    "provider": "HELIUS",
                    "error_code": "HELIUS_RETRY_EXHAUSTED",
                    "message": "temporary failure",
                }
            ],
        },
    )

    result = discovery_engine.discover_full_from_wallet(
        db,
        "seed-wallet",
        max_tokens=1,
    )

    assert result["status"] == "PARTIAL"
    assert result["tokens_attempted"] == 1
    assert result["tokens_processed"] == 0
    assert result["tokens_failed"] == 1
    assert result["error_count"] == 1


def test_token_onchain_failure_is_returned_as_safe_payload(monkeypatch):
    secret = "do-not-log-this"

    monkeypatch.setattr(
        discovery_engine,
        "get_wallet_history",
        lambda _token: (_ for _ in ()).throw(
            HeliusRequestError(
                message=f"failed api-key={secret}",
                endpoint="https://api.helius.xyz/v0/test",
                status_code=500,
                retryable=True,
                attempts=4,
                error_code="HELIUS_RETRY_EXHAUSTED",
            )
        ),
    )

    result = discovery_engine.discover_wallets_from_token_onchain(
        "token-1"
    )

    assert result["status"] == "FAILED"
    assert result["wallets"] == []
    assert secret not in result["errors"][0]["message"]
    assert "REDACTED" in result["errors"][0]["message"]
