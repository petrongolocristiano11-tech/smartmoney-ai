from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import backend.app.services.jupiter_swap_client as jupiter
from backend.app.services.gen4_fastpath_shadow_service import (
    _jupiter_error_snapshot,
    _record_jupiter_entry_error,
)
from backend.app.services.gen4_selective_copyability_gate_service import (
    classify_buy_attempt,
)
from backend.app.services.live_trading_errors import JupiterSwapError


class _FakeCoordinator:
    def __init__(self, *, reset_delay: float = 0.0) -> None:
        self.reset_delay = reset_delay
        self.acquire_count = 0
        self.observe_count = 0
        self.block_count = 0
        self.observed_headers: list[dict[str, str]] = []

    def acquire(self) -> None:
        self.acquire_count += 1

    def observe(self, headers) -> None:
        self.observe_count += 1
        self.observed_headers.append(dict(headers))

    def block_until_reset(self, headers) -> float:
        self.block_count += 1
        self.observed_headers.append(dict(headers))
        return self.reset_delay


def _client(*, transport, max_retries: int = 0, sleep_fn=lambda _: None):
    return jupiter.JupiterSwapClient(
        api_key="test-key",
        base_url="https://jupiter.invalid/swap/v2",
        timeout_seconds=1.0,
        max_retries=max_retries,
        retry_base_seconds=0.05,
        retry_max_seconds=4.0,
        sleep_fn=sleep_fn,
        transport=transport,
        shared_rate_limit=True,
    )


def test_shared_coordinator_is_used_across_client_instances(monkeypatch):
    fake = _FakeCoordinator()
    monkeypatch.setattr(
        jupiter,
        "_SHARED_JUPITER_RATE_LIMIT_COORDINATOR",
        fake,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"ok": True},
            headers={
                "x-ratelimit-current": "1",
                "x-ratelimit-remaining": "9",
            },
        )

    transport = httpx.MockTransport(handler)
    first = _client(transport=transport)
    second = _client(transport=transport)

    assert first._request_json("GET", "/order", retryable=True) == {"ok": True}
    assert second._request_json("GET", "/build", retryable=True) == {"ok": True}
    assert fake.acquire_count == 2
    assert fake.observe_count == 2


def test_429_waits_for_gateway_reset_before_retry(monkeypatch):
    fake = _FakeCoordinator(reset_delay=0.75)
    monkeypatch.setattr(
        jupiter,
        "_SHARED_JUPITER_RATE_LIMIT_COORDINATOR",
        fake,
    )
    responses = iter(
        [
            httpx.Response(
                429,
                json={"code": 429, "message": "Too many requests"},
                headers={
                    "x-ratelimit-current": "10",
                    "x-ratelimit-remaining": "0",
                    "x-ratelimit-reset": "2000000000",
                },
            ),
            httpx.Response(
                200,
                json={"ok": True},
                headers={
                    "x-ratelimit-current": "1",
                    "x-ratelimit-remaining": "9",
                },
            ),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return next(responses)

    sleeps: list[float] = []
    client = _client(
        transport=httpx.MockTransport(handler),
        max_retries=1,
        sleep_fn=sleeps.append,
    )

    assert client._request_json("GET", "/order", retryable=True) == {"ok": True}
    assert fake.block_count == 1
    assert sleeps == [pytest.approx(0.75)]
    assert fake.acquire_count == 2


def test_final_429_preserves_sanitized_rate_limit_diagnostics(monkeypatch):
    fake = _FakeCoordinator()
    monkeypatch.setattr(
        jupiter,
        "_SHARED_JUPITER_RATE_LIMIT_COORDINATOR",
        fake,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            json={"code": 429, "message": "[API Gateway] Too many requests"},
            headers={
                "x-ratelimit-current": "10",
                "x-ratelimit-remaining": "0",
                "x-ratelimit-reset": "2000000000",
            },
        )

    client = _client(transport=httpx.MockTransport(handler), max_retries=0)
    with pytest.raises(JupiterSwapError) as raised:
        client._request_json("GET", "/order", retryable=True)

    exc = raised.value
    assert exc.code == "JUPITER_HTTP_ERROR"
    assert exc.payload["http_status"] == 429
    assert exc.payload["attempts"] == 1
    assert exc.payload["rate_limit_headers"] == {
        "x-ratelimit-current": "10",
        "x-ratelimit-remaining": "0",
        "x-ratelimit-reset": "2000000000",
    }


def test_observed_10_rps_uses_eight_rps_headroom():
    coordinator = jupiter._SharedJupiterRateLimitCoordinator()
    coordinator.observe(
        {
            "x-ratelimit-current": "1",
            "x-ratelimit-remaining": "9",
        }
    )
    with coordinator._lock:
        assert coordinator._observed_limit == 10
        assert coordinator._target_rps_locked() == 8


def test_fastpath_persists_only_sanitized_jupiter_error_details():
    exc = JupiterSwapError(
        "Too many requests",
        code="JUPITER_HTTP_ERROR",
        status_code=502,
        payload={
            "http_status": 429,
            "attempts": 3,
            "retryable": True,
            "rate_limit_headers": {
                "x-ratelimit-current": "10",
                "x-ratelimit-remaining": "0",
                "x-ratelimit-reset": "2000000000",
                "authorization": "must-not-leak",
            },
            "response": {
                "code": 429,
                "message": "Too many requests",
                "swapInstruction": {"secret": "must-not-persist"},
            },
        },
    )
    snapshot = _jupiter_error_snapshot(exc)
    assert snapshot == {
        "code": "JUPITER_HTTP_ERROR",
        "internal_status_code": 502,
        "http_status": 429,
        "attempts": 3,
        "retryable": True,
        "rate_limit_headers": {
            "x-ratelimit-current": "10",
            "x-ratelimit-remaining": "0",
            "x-ratelimit-reset": "2000000000",
        },
        "response": {
            "code": 429,
            "message": "Too many requests",
        },
    }


def test_runtime_arms_shared_limit_for_official_and_candidate_clients():
    runtime_source = Path(
        "backend/app/services/gen4_fastpath_shadow_runtime.py"
    ).read_text(encoding="utf-8")
    assert runtime_source.count("shared_rate_limit=True") == 2
    assert runtime_source.count("persistent_http=True") >= 2


def _empty_fastpath_buy_event():
    return SimpleNamespace(
        evidence={},
        parse_error_code=None,
        quote_error_code=None,
        fast_provisional_copyable=False,
        fast_provisional_rejection_reason=None,
        fast_transaction_built=False,
        fast_quote_received_at=None,
        fast_price_impact_bps=None,
        fast_price_deterioration_bps=None,
    )


def test_http400_no_routes_is_forward_liquidity_protective_reject():
    event = _empty_fastpath_buy_event()
    exc = JupiterSwapError(
        "No routes found",
        code="JUPITER_HTTP_ERROR",
        status_code=502,
        payload={
            "http_status": 400,
            "attempts": 1,
            "retryable": True,
            "rate_limit_headers": {
                "x-ratelimit-current": "1",
                "x-ratelimit-remaining": "9",
            },
            "response": {"error": "No routes found"},
        },
    )

    _record_jupiter_entry_error(event, exc)

    assert event.quote_error_code is None
    assert event.fast_provisional_copyable is False
    assert event.fast_provisional_rejection_reason == "NO_EXECUTABLE_OUTPUT"
    assert classify_buy_attempt(event) == (
        "LIQUIDITY_PROTECTIVE_REJECT",
        "NO_EXECUTABLE_OUTPUT",
    )
    assert event.evidence["jupiter_error"]["http_status"] == 400
    assert event.evidence["jupiter_error"]["response"] == {
        "error": "No routes found"
    }
    assert event.evidence["jupiter_entry_classification"] == {
        "version": "jupiter-entry-error-classification/1",
        "provider": "JUPITER",
        "http_status": 400,
        "provider_error": "No routes found",
        "classification": "LIQUIDITY_PROTECTIVE_REJECT",
        "mapped_rejection": "NO_EXECUTABLE_OUTPUT",
        "historical_reclassification": False,
    }


def test_other_http400_remains_technical_failure():
    event = _empty_fastpath_buy_event()
    exc = JupiterSwapError(
        "Invalid request",
        code="JUPITER_HTTP_ERROR",
        status_code=502,
        payload={
            "http_status": 400,
            "attempts": 1,
            "retryable": True,
            "response": {"error": "Invalid request"},
        },
    )

    _record_jupiter_entry_error(event, exc)

    assert event.quote_error_code == "JUPITER_HTTP_ERROR"
    assert event.fast_provisional_rejection_reason is None
    assert classify_buy_attempt(event) == (
        "TECHNICAL_FAILURE",
        "QUOTE:JUPITER_HTTP_ERROR",
    )


def test_http429_remains_technical_failure():
    event = _empty_fastpath_buy_event()
    exc = JupiterSwapError(
        "[API Gateway] Too many requests",
        code="JUPITER_HTTP_ERROR",
        status_code=502,
        payload={
            "http_status": 429,
            "attempts": 3,
            "retryable": True,
            "response": {
                "message": "[API Gateway] Too many requests"
            },
        },
    )

    _record_jupiter_entry_error(event, exc)

    assert event.quote_error_code == "JUPITER_HTTP_ERROR"
    assert event.fast_provisional_rejection_reason is None
    assert classify_buy_attempt(event) == (
        "TECHNICAL_FAILURE",
        "QUOTE:JUPITER_HTTP_ERROR",
    )


def test_no_route_mapping_is_exact_fingerprint_only():
    event = _empty_fastpath_buy_event()
    exc = JupiterSwapError(
        "No route found",
        code="JUPITER_HTTP_ERROR",
        status_code=502,
        payload={
            "http_status": 400,
            "attempts": 1,
            "retryable": True,
            "response": {"error": "No route found"},
        },
    )

    _record_jupiter_entry_error(event, exc)

    assert event.quote_error_code == "JUPITER_HTTP_ERROR"
    assert event.fast_provisional_rejection_reason is None
    assert classify_buy_attempt(event)[0] == "TECHNICAL_FAILURE"
