from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timezone

from backend.app.services import gen4_fastpath_shadow_runtime as runtime_module


WALLET_A = "WalletA111111111111111111111111111111111"
WALLET_B = "WalletB111111111111111111111111111111111"


def _message(signature: str, wallet: str) -> dict:
    return {
        "method": "transactionNotification",
        "params": {
            "result": {
                "signature": signature,
                "slot": 1,
                "transaction": {
                    "meta": {
                        "preTokenBalances": [{"owner": wallet}],
                        "postTokenBalances": [],
                    },
                    "transaction": {
                        "signatures": [signature],
                        "message": {"accountKeys": []},
                    },
                },
            }
        },
    }


def test_candidate_runtime_serializes_same_wallet_buy_sell(monkeypatch):
    runtime = runtime_module.EmbeddedGen4FastpathShadowRuntime()
    monkeypatch.setattr(
        runtime_module,
        "configured_fastpath_candidate_wallets",
        lambda: [WALLET_A, WALLET_B],
    )

    first_entered = threading.Event()
    second_entered = threading.Event()
    release_first = threading.Event()
    order: list[str] = []

    def fake_record(message, received_at):
        signature = str(message["params"]["result"]["signature"])
        order.append(signature)
        if signature == "buy":
            first_entered.set()
            assert release_first.wait(timeout=2.0)
        elif signature == "sell":
            second_entered.set()

    monkeypatch.setattr(runtime, "_record_candidate", fake_record)

    async def scenario():
        semaphore = asyncio.Semaphore(4)
        now = datetime(2026, 9, 13, 14, 0, tzinfo=timezone.utc)

        buy_task = asyncio.create_task(
            runtime._handle_candidate(_message("buy", WALLET_A), semaphore, now)
        )
        assert await asyncio.to_thread(first_entered.wait, 1.0)

        sell_task = asyncio.create_task(
            runtime._handle_candidate(_message("sell", WALLET_A), semaphore, now)
        )
        await asyncio.sleep(0.05)

        assert second_entered.is_set() is False
        assert order == ["buy"]

        release_first.set()
        await asyncio.gather(buy_task, sell_task)

        assert second_entered.is_set() is True
        assert order == ["buy", "sell"]

    asyncio.run(scenario())


def test_candidate_runtime_keeps_different_wallets_parallel(monkeypatch):
    runtime = runtime_module.EmbeddedGen4FastpathShadowRuntime()
    monkeypatch.setattr(
        runtime_module,
        "configured_fastpath_candidate_wallets",
        lambda: [WALLET_A, WALLET_B],
    )

    first_entered = threading.Event()
    second_entered = threading.Event()
    release_first = threading.Event()

    def fake_record(message, received_at):
        signature = str(message["params"]["result"]["signature"])
        if signature == "wallet-a":
            first_entered.set()
            assert release_first.wait(timeout=2.0)
        elif signature == "wallet-b":
            second_entered.set()

    monkeypatch.setattr(runtime, "_record_candidate", fake_record)

    async def scenario():
        semaphore = asyncio.Semaphore(4)
        now = datetime(2026, 9, 13, 14, 0, tzinfo=timezone.utc)

        first_task = asyncio.create_task(
            runtime._handle_candidate(_message("wallet-a", WALLET_A), semaphore, now)
        )
        assert await asyncio.to_thread(first_entered.wait, 1.0)

        second_task = asyncio.create_task(
            runtime._handle_candidate(_message("wallet-b", WALLET_B), semaphore, now)
        )

        assert await asyncio.to_thread(second_entered.wait, 1.0)

        release_first.set()
        await asyncio.gather(first_task, second_task)

    asyncio.run(scenario())


def test_candidate_lock_precedes_global_semaphore():
    import inspect

    source = inspect.getsource(
        runtime_module.EmbeddedGen4FastpathShadowRuntime._handle_candidate
    )
    assert "_candidate_wallet_locks" in source
    assert "_candidate_fallback_lock" in source
    assert "fastpath_notification_wallet_hint" in source
    assert "async with lock" in source
    assert "async with semaphore" in source
    assert source.index("async with lock") < source.index("async with semaphore")


def test_candidate_ordering_fix_does_not_change_official_locking():
    import inspect

    source = inspect.getsource(runtime_module.EmbeddedGen4FastpathShadowRuntime._handle)
    assert "_official_wallet_locks" in source
    assert "_official_fallback_lock" in source
    assert "async with lock" in source
    assert "async with semaphore" in source
    assert source.index("async with lock") < source.index("async with semaphore")
