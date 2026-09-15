from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import time

import httpx
import pytest

import backend.app.services.jupiter_swap_client as jupiter
import backend.app.services.gen4_fastpath_shadow_service as fast


def _client(
    *,
    transport: httpx.BaseTransport,
    max_retries: int = 0,
    retry_base_seconds: float = 0.5,
    retry_max_seconds: float = 4.0,
    sleep_fn=lambda _seconds: None,
    shared_rate_limit: bool = False,
) -> jupiter.JupiterSwapClient:
    return jupiter.JupiterSwapClient(
        api_key="test-key",
        base_url="https://jupiter.invalid/swap/v2",
        timeout_seconds=1.0,
        max_retries=max_retries,
        retry_base_seconds=retry_base_seconds,
        retry_max_seconds=retry_max_seconds,
        sleep_fn=sleep_fn,
        transport=transport,
        persistent_http=True,
        shared_rate_limit=shared_rate_limit,
    )


def test_r29_request_timing_success_separates_http_from_retry_and_pacing() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    client = _client(transport=httpx.MockTransport(handler))
    timing: dict[str, object] = {}
    try:
        payload = client._request_json(
            "GET",
            "/order",
            retryable=True,
            timing_sink=timing,
        )
    finally:
        client.close()

    assert payload == {"ok": True}
    assert timing["version"] == "jupiter-component-timing/1"
    assert timing["attempts"] == 1
    assert timing["retry_count"] == 0
    assert timing["retry_sleep_requested_ms"] == pytest.approx(0.0)
    assert timing["shared_pacing_wait_ms"] == pytest.approx(0.0)
    assert float(timing["http_round_trip_ms"]) >= 0.0
    assert float(timing["endpoint_total_ms"]) >= float(timing["http_round_trip_ms"])
    assert timing["status_codes"] == [200]
    assert timing["success"] is True
    assert timing["used_persistent_http"] is True
    assert timing["observation_only"] is True


def test_r29_request_timing_records_retry_backoff_without_changing_sleep_contract() -> None:
    calls = {"count": 0}
    sleeps: list[float] = []

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(503, json={"error": "temporary"})
        return httpx.Response(200, json={"ok": True})

    client = _client(
        transport=httpx.MockTransport(handler),
        max_retries=1,
        retry_base_seconds=0.5,
        retry_max_seconds=0.5,
        sleep_fn=sleeps.append,
    )
    timing: dict[str, object] = {}
    try:
        payload = client._request_json(
            "GET",
            "/order",
            retryable=True,
            timing_sink=timing,
        )
    finally:
        client.close()

    assert payload == {"ok": True}
    assert calls["count"] == 2
    assert sleeps == [pytest.approx(0.5)]
    assert timing["attempts"] == 2
    assert timing["retry_count"] == 1
    assert timing["retry_sleep_requested_ms"] == pytest.approx(500.0)
    assert timing["status_codes"] == [503, 200]
    assert timing["success"] is True


def test_r29_request_timing_measures_existing_shared_pacing_wait(monkeypatch) -> None:
    class SlowCoordinator:
        def acquire(self) -> None:
            time.sleep(0.01)

        def observe(self, _headers) -> None:
            return None

        def block_until_reset(self, _headers) -> float:
            return 0.0

    monkeypatch.setattr(
        jupiter,
        "_SHARED_JUPITER_RATE_LIMIT_COORDINATOR",
        SlowCoordinator(),
    )

    client = _client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json={"ok": True})
        ),
        shared_rate_limit=True,
    )
    timing: dict[str, object] = {}
    try:
        client._request_json(
            "GET",
            "/order",
            retryable=True,
            timing_sink=timing,
        )
    finally:
        client.close()

    assert float(timing["shared_pacing_wait_ms"]) >= 5.0
    assert timing["shared_rate_limit"] is True
    assert timing["attempts"] == 1


def test_r29_parallel_order_build_returns_component_timing_without_changing_contract(
    monkeypatch,
) -> None:
    client = _client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(500, json={"unused": True})
        )
    )

    def fake_request(
        method: str,
        path: str,
        *,
        params=None,
        json=None,
        retryable: bool = False,
        timing_sink=None,
    ):
        assert method == "GET"
        assert retryable is True
        assert timing_sink is not None
        timing_sink.update(
            {
                "version": "jupiter-component-timing/1",
                "method": "GET",
                "path": path,
                "attempts": 1,
                "retry_count": 0,
                "shared_pacing_wait_ms": 12.0 if path == "/build" else 3.0,
                "http_round_trip_ms": 40.0 if path == "/build" else 30.0,
                "retry_sleep_requested_ms": 0.0,
                "endpoint_total_ms": 52.0 if path == "/build" else 33.0,
                "status_codes": [200],
                "final_http_status": 200,
                "success": True,
                "retryable": True,
                "shared_rate_limit": False,
                "used_persistent_http": True,
                "observation_only": True,
            }
        )
        if path == "/order":
            return {
                "requestId": "req-1",
                "transaction": None,
                "inAmount": "10000000",
                "outAmount": "1000000",
                "slippageBps": 300,
                "router": "metis",
                "priceImpact": 0.01,
            }
        if path == "/build":
            return {
                "requestId": "req-1",
                "inAmount": "10000000",
                "outAmount": "999000",
                "otherAmountThreshold": "969030",
                "slippageBps": 300,
                "router": "metis",
                "priceImpact": 0.01,
                "swapInstruction": {
                    "programId": "program",
                    "data": "AA==",
                    "accounts": [],
                },
                "blockhashWithMetadata": {
                    "lastValidBlockHeight": 123,
                },
                "setupInstructions": [],
                "computeBudgetInstructions": [],
                "otherInstructions": [],
                "addressesByLookupTableAddress": {},
            }
        raise AssertionError(path)

    monkeypatch.setattr(client, "_request_json", fake_request)
    try:
        result = client.get_quote_and_unsigned_build(
            input_mint="So11111111111111111111111111111111111111112",
            output_mint="TokenMint",
            amount_raw=10_000_000,
            taker="PublicTaker",
            slippage_bps=300,
            mode="fast",
        )
    finally:
        client.close()

    timing = result.request_timing
    assert isinstance(timing, dict)
    assert timing["version"] == "jupiter-component-timing/1"
    assert timing["order"]["path"] == "/order"
    assert timing["build"]["path"] == "/build"
    assert float(timing["parallel_wall_ms"]) >= 0.0
    assert timing["pacing_changed"] is False
    assert timing["retry_changed"] is False
    assert timing["request_concurrency_changed"] is False
    assert result.transaction == "UNSIGNED_INSTRUCTIONS_BUILT_NO_SIGNATURE"
    assert result.raw["componentTiming"] == timing


def test_r29_m319_persists_only_sanitized_jupiter_component_timing() -> None:
    base = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)
    event = SimpleNamespace(
        fast_received_at=base,
        evidence={
            fast.M319_COPYABLE_EDGE_EVIDENCE_KEY: {
                "version": fast.M319_COPYABLE_EDGE_VERSION,
                "source_block_time_utc": None,
                "source_provider_slot_time_utc": None,
            }
        },
    )
    component = {
        "version": "jupiter-component-timing/1",
        "parallel_wall_ms": 410.0,
        "order": {
            "attempts": 1,
            "retry_count": 0,
            "shared_pacing_wait_ms": 15.0,
            "http_round_trip_ms": 380.0,
            "retry_sleep_requested_ms": 0.0,
            "endpoint_total_ms": 395.0,
            "status_codes": [200],
            "final_http_status": 200,
            "success": True,
            "retryable": True,
            "shared_rate_limit": True,
            "used_persistent_http": True,
            "method": "GET",
            "path": "/order",
            "error_type": None,
            "observation_only": True,
        },
        "build": {
            "attempts": 1,
            "retry_count": 0,
            "shared_pacing_wait_ms": 25.0,
            "http_round_trip_ms": 360.0,
            "retry_sleep_requested_ms": 0.0,
            "endpoint_total_ms": 390.0,
            "status_codes": [200],
            "final_http_status": 200,
            "success": True,
            "retryable": True,
            "shared_rate_limit": True,
            "used_persistent_http": True,
            "method": "GET",
            "path": "/build",
            "error_type": None,
            "observation_only": True,
        },
        "observation_only": True,
        "pacing_changed": False,
        "retry_changed": False,
        "request_concurrency_changed": False,
    }
    quote = SimpleNamespace(
        requested_at=base + timedelta(milliseconds=10),
        received_at=base + timedelta(milliseconds=420),
        latency_ms=410,
        result=SimpleNamespace(
            transaction="UNSIGNED_INSTRUCTIONS_BUILT_NO_SIGNATURE",
            request_timing=component,
        ),
    )

    fast._m319_update_buy_quote(
        event,
        quote=quote,
        deterioration_bps=120.0,
        price_impact_bps=4.0,
        rejection_reason=None,
    )

    entry = event.evidence[
        fast.M319_COPYABLE_EDGE_EVIDENCE_KEY
    ]["follower_entry"]
    saved = entry["jupiter_component_timing"]
    assert saved["version"] == "jupiter-component-timing/1"
    assert saved["parallel_wall_ms"] == pytest.approx(410.0)
    assert saved["order"]["shared_pacing_wait_ms"] == pytest.approx(15.0)
    assert saved["build"]["http_round_trip_ms"] == pytest.approx(360.0)
    assert "path" not in saved["order"]
    assert "method" not in saved["order"]
    assert "error_type" not in saved["order"]
    assert saved["observation_only"] is True
    assert saved["pacing_changed"] is False
    assert saved["retry_changed"] is False
    assert saved["request_concurrency_changed"] is False
