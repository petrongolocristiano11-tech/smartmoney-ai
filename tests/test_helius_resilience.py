from __future__ import annotations

import httpx
import pytest

from backend.app.core.config import settings
from backend.app.services import helius


def _response(status_code: int, payload):
    request = httpx.Request(
        "GET",
        "https://api.helius.xyz/v0/test",
    )
    return httpx.Response(
        status_code,
        json=payload,
        request=request,
    )


def test_wallet_history_retries_500_then_recovers(monkeypatch):
    responses = iter(
        [
            _response(500, {"error": "temporary"}),
            _response(200, [{"type": "SWAP"}]),
        ]
    )
    calls = []

    def fake_request(*args, **kwargs):
        calls.append((args, kwargs))
        return next(responses)

    monkeypatch.setattr(settings, "HELIUS_MAX_RETRIES", 3)
    monkeypatch.setattr(helius.httpx, "request", fake_request)
    monkeypatch.setattr(helius.time, "sleep", lambda _seconds: None)

    result = helius.get_wallet_history("wallet-address")

    assert result == [{"type": "SWAP"}]
    assert len(calls) == 2
    assert calls[0][1]["params"]["api-key"] == settings.HELIUS_API_KEY


def test_wallet_history_retries_timeout_then_recovers(monkeypatch):
    calls = 0

    def fake_request(method, url, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout(
                "temporary timeout",
                request=httpx.Request(method, url),
            )
        return _response(200, [])

    monkeypatch.setattr(settings, "HELIUS_MAX_RETRIES", 1)
    monkeypatch.setattr(helius.httpx, "request", fake_request)
    monkeypatch.setattr(helius.time, "sleep", lambda _seconds: None)

    assert helius.get_wallet_history("wallet-address") == []
    assert calls == 2


def test_persistent_helius_error_is_sanitized(monkeypatch):
    exposed_key = "helius-secret-that-must-not-appear"

    def fake_request(*_args, **_kwargs):
        return _response(500, {"api-key": exposed_key})

    monkeypatch.setattr(settings, "HELIUS_API_KEY", exposed_key)
    monkeypatch.setattr(settings, "HELIUS_MAX_RETRIES", 2)
    monkeypatch.setattr(helius.httpx, "request", fake_request)
    monkeypatch.setattr(helius.time, "sleep", lambda _seconds: None)

    with pytest.raises(helius.HeliusRequestError) as raised:
        helius.get_wallet_history("wallet-address")

    error = raised.value
    assert error.status_code == 500
    assert error.retryable is True
    assert error.attempts == 3
    assert error.error_code == "HELIUS_RETRY_EXHAUSTED"
    assert exposed_key not in str(error)
    assert exposed_key not in error.endpoint
    assert "api-key" not in error.endpoint


def test_non_retryable_401_fails_immediately(monkeypatch):
    calls = 0

    def fake_request(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return _response(401, {"error": "unauthorized"})

    monkeypatch.setattr(settings, "HELIUS_MAX_RETRIES", 3)
    monkeypatch.setattr(helius.httpx, "request", fake_request)
    monkeypatch.setattr(helius.time, "sleep", lambda _seconds: None)

    with pytest.raises(helius.HeliusRequestError) as raised:
        helius.get_wallet_history("wallet-address")

    assert calls == 1
    assert raised.value.error_code == "HELIUS_HTTP_ERROR"
    assert raised.value.retryable is False
