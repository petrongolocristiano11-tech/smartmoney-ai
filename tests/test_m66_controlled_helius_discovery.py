from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone

import pytest

from backend.app.services import helius as helius_service
from backend.app.services.gen4_controlled_helius_discovery_service import (
    M66_DEFAULT_SEED_WALLET,
    M66_HELIUS_CONFIRMATION,
    M66_MAX_ENHANCED_CREDITS,
    M66_MAX_ENHANCED_REQUESTS,
    M66ControlledHeliusDiscoveryError,
    build_controlled_helius_plan,
    execute_controlled_helius_discovery,
    validate_helius_request_cache,
)


NOW = datetime(2026, 8, 14, 21, 30, tzinfo=timezone.utc)
TOKEN_A = "A" * 44
TOKEN_B = "B" * 44
CANDIDATE_A = "8" * 44
CANDIDATE_B = "9" * 44
CACHED_WALLET = "C" * 44


def swap(
    wallet: str,
    token: str,
    side: str,
    at: datetime,
    sequence: int,
    *,
    fee_payer: str | None = None,
) -> dict:
    event = {
        "tokenInputs": [],
        "tokenOutputs": [],
        "nativeInput": None,
        "nativeOutput": None,
    }
    if side == "BUY":
        event["nativeInput"] = {"account": wallet, "amount": "50000000"}
        event["tokenOutputs"] = [
            {
                "userAccount": wallet,
                "mint": token,
                "rawTokenAmount": {"tokenAmount": "1000000", "decimals": 6},
            }
        ]
    else:
        event["nativeOutput"] = {"account": wallet, "amount": "60000000"}
        event["tokenInputs"] = [
            {
                "userAccount": wallet,
                "mint": token,
                "rawTokenAmount": {"tokenAmount": "1000000", "decimals": 6},
            }
        ]
    return {
        "type": "SWAP",
        "signature": f"sig-{wallet[:4]}-{token[:4]}-{sequence}",
        "timestamp": int(at.timestamp()),
        "source": "JUPITER",
        "fee": 5000,
        "feePayer": fee_payer or wallet,
        "transactionError": None,
        "tokenTransfers": [],
        "nativeTransfers": [],
        "accountData": [],
        "events": {"swap": event},
    }


def token_history_row(wallet: str, at: datetime, sequence: int) -> dict:
    return {
        "type": "SWAP",
        "signature": f"token-history-{wallet[:4]}-{sequence}",
        "timestamp": int(at.timestamp()),
        "feePayer": wallet,
    }


def candidate_history(wallet: str) -> list[dict]:
    rows = []
    for index in range(4):
        token = TOKEN_A if index % 2 == 0 else TOKEN_B
        at = NOW - timedelta(days=index % 2, hours=index)
        rows.append(swap(wallet, token, "BUY", at, index * 2))
        rows.append(
            swap(
                wallet,
                token,
                "SELL",
                at + timedelta(minutes=5),
                index * 2 + 1,
            )
        )
    return rows


def histories() -> dict[str, list[dict]]:
    return {
        M66_DEFAULT_SEED_WALLET: [
            swap(M66_DEFAULT_SEED_WALLET, TOKEN_A, "BUY", NOW, 1),
            swap(M66_DEFAULT_SEED_WALLET, TOKEN_A, "SELL", NOW, 2),
            swap(M66_DEFAULT_SEED_WALLET, TOKEN_B, "BUY", NOW, 3),
            swap(M66_DEFAULT_SEED_WALLET, TOKEN_B, "SELL", NOW, 4),
        ],
        TOKEN_A: [
            token_history_row(CANDIDATE_A, NOW, 1),
            token_history_row(CANDIDATE_A, NOW, 2),
            token_history_row(CANDIDATE_B, NOW, 3),
            token_history_row(CACHED_WALLET, NOW, 4),
            token_history_row(M66_DEFAULT_SEED_WALLET, NOW, 5),
        ],
        TOKEN_B: [
            token_history_row(CANDIDATE_A, NOW, 6),
        ],
        CANDIDATE_A: candidate_history(CANDIDATE_A),
        CANDIDATE_B: [
            swap(CANDIDATE_B, TOKEN_A, "BUY", NOW, 1),
        ],
    }


def test_plan_is_hard_bounded_and_keeps_automatic_enhanced_disabled():
    plan = build_controlled_helius_plan()
    assert plan["enhanced_request_cap"] == M66_MAX_ENHANCED_REQUESTS == 90
    assert plan["enhanced_credit_cap"] == M66_MAX_ENHANCED_CREDITS == 9000
    assert plan["execution"]["automatic_enhanced_api"] is False
    assert plan["execution"]["maximum_retries"] == 0
    assert plan["execution"]["discovery_cron_reactivation"] is False


def test_confirmation_is_mandatory_before_fetcher_can_run():
    calls = []

    def forbidden_fetch(*args, **kwargs):
        calls.append((args, kwargs))
        return []

    with pytest.raises(M66ControlledHeliusDiscoveryError, match="Conferma Helius"):
        execute_controlled_helius_discovery(
            confirmation="NO",
            fetch_history=forbidden_fetch,
        )
    assert calls == []


def test_controlled_discovery_deduplicates_cached_wallets_and_never_promotes():
    source = histories()
    calls: list[tuple[str, dict]] = []

    def fake_fetch(address, **kwargs):
        calls.append((address, kwargs))
        return copy.deepcopy(source[address])

    report, cache = execute_controlled_helius_discovery(
        confirmation=M66_HELIUS_CONFIRMATION,
        cached_wallet_addresses={CACHED_WALLET},
        fetch_history=fake_fetch,
        executed_at=NOW,
    )
    assert report["discovery"] == "PASS"
    assert report["candidate_pool"]["new_wallets_found_before_limit"] == 2
    assert report["summary"]["new_wallets_prescreened"] == 2
    assert report["summary"]["prescreen_pass_needing_full_gen4_history"] == 1
    assert report["summary"]["qualified_for_short_canary"] == 0
    assert report["summary"]["micro_live_ready"] == 0
    assert report["candidate_results"][0]["wallet_address"] == CANDIDATE_A
    assert report["candidate_results"][0]["economics"]["net_pnl_sol"] is None
    assert report["activation"]["micro_live_execution_authorized"] is False
    assert report["budget"]["enhanced_requests_executed"] == 5
    assert report["budget"]["enhanced_credits_reserved_maximum"] == 500
    assert len(calls) == 5
    for _, kwargs in calls:
        assert kwargs["automatic"] is False
        assert kwargs["max_retries"] == 0
        assert kwargs["capture_response"] is False
        assert kwargs["transaction_type"] == "SWAP"
    cached = validate_helius_request_cache(cache)
    assert set(cached) == {
        M66_DEFAULT_SEED_WALLET,
        TOKEN_A,
        TOKEN_B,
        CANDIDATE_A,
        CANDIDATE_B,
    }


def test_valid_cache_replay_uses_zero_helius_requests():
    source = histories()

    def fake_fetch(address, **kwargs):
        return copy.deepcopy(source[address])

    original_report, cache = execute_controlled_helius_discovery(
        confirmation=M66_HELIUS_CONFIRMATION,
        cached_wallet_addresses={CACHED_WALLET},
        fetch_history=fake_fetch,
        executed_at=NOW,
    )

    def no_network(*args, **kwargs):
        raise AssertionError("La cache completa non deve chiamare Helius.")

    replay, replay_cache = execute_controlled_helius_discovery(
        confirmation=M66_HELIUS_CONFIRMATION,
        cached_wallet_addresses={CACHED_WALLET},
        request_cache=cache,
        fetch_history=no_network,
        executed_at=NOW,
    )
    assert replay["budget"]["enhanced_requests_executed"] == 0
    assert replay["budget"]["enhanced_credits_reserved_maximum"] == 0
    assert replay["budget"]["cache_hits"] == 5
    assert replay["summary"] == original_report["summary"]
    validate_helius_request_cache(replay_cache)


def test_tampered_cache_fails_before_network():
    source = histories()

    def fake_fetch(address, **kwargs):
        return copy.deepcopy(source[address])

    _, cache = execute_controlled_helius_discovery(
        confirmation=M66_HELIUS_CONFIRMATION,
        cached_wallet_addresses={CACHED_WALLET},
        fetch_history=fake_fetch,
        executed_at=NOW,
    )
    cache["histories"][M66_DEFAULT_SEED_WALLET][0]["signature"] = "tampered"
    with pytest.raises(M66ControlledHeliusDiscoveryError, match="Hash cache"):
        execute_controlled_helius_discovery(
            confirmation=M66_HELIUS_CONFIRMATION,
            request_cache=cache,
            fetch_history=lambda *_args, **_kwargs: [],
        )


def test_provider_failure_is_not_retried_by_the_service():
    calls = 0

    def failing_fetch(*args, **kwargs):
        nonlocal calls
        calls += 1
        assert kwargs["max_retries"] == 0
        raise RuntimeError("provider down")

    with pytest.raises(RuntimeError, match="provider down"):
        execute_controlled_helius_discovery(
            confirmation=M66_HELIUS_CONFIRMATION,
            fetch_history=failing_fetch,
        )
    assert calls == 1


def test_wallet_history_can_disable_raw_capture_without_changing_default(monkeypatch):
    captures = []
    monkeypatch.setattr(helius_service, "_request_json", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        helius_service,
        "_capture_helius_payload",
        lambda *args, **kwargs: captures.append((args, kwargs)),
    )
    assert (
        helius_service.get_wallet_history(
            TOKEN_A,
            max_retries=0,
            automatic=False,
            capture_response=False,
        )
        == []
    )
    assert captures == []
    helius_service.get_wallet_history(TOKEN_A)
    assert len(captures) == 1
