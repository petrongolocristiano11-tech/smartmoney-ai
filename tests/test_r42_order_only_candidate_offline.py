from __future__ import annotations

import inspect

import pytest

import backend.app.services.gen4_fastpath_shadow_service as fast
import backend.app.services.jupiter_swap_client as jup
from backend.app.services.live_trading_errors import JupiterSwapError


def _valid_order_payload():
    return {
        "requestId": "order-request-1",
        "transaction": "AQIDBA==",
        "inAmount": "10000000",
        "outAmount": "250000000",
        "otherAmountThreshold": "242500000",
        "slippageBps": 300,
        "router": "metis",
        "priceImpact": "0.001",
        "lastValidBlockHeight": 123456,
    }


def test_r42_order_only_shadow_calls_only_order_with_taker_and_critical_priority(monkeypatch):
    client = jup.JupiterSwapClient(
        api_key="test",
        base_url="https://example.invalid",
        persistent_http=False,
        shared_rate_limit=True,
    )
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append(
            {
                "method": method,
                "path": path,
                "params": dict(kwargs.get("params") or {}),
                "priority": kwargs.get("request_priority"),
            }
        )
        sink = kwargs.get("timing_sink")
        if isinstance(sink, dict):
            sink.update(
                {
                    "attempts": 1,
                    "retry_count": 0,
                    "shared_pacing_wait_ms": 0.0,
                    "http_round_trip_ms": 125.0,
                    "retry_sleep_requested_ms": 0.0,
                    "endpoint_total_ms": 125.0,
                    "status_codes": [200],
                    "final_http_status": 200,
                    "success": True,
                    "retryable": True,
                    "shared_rate_limit": True,
                    "used_persistent_http": True,
                }
            )
        return _valid_order_payload()

    monkeypatch.setattr(client, "_request_json", fake_request)
    result = client.get_order_only_shadow(
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="TokenMint",
        amount_raw=10_000_000,
        taker="PublicTaker",
        slippage_bps=300,
    )

    assert len(calls) == 1
    assert calls[0]["path"] == "/order"
    assert calls[0]["priority"] == "critical"
    assert calls[0]["params"]["taker"] == "PublicTaker"
    assert calls[0]["params"]["slippageBps"] == "300"
    assert result.request_id == "order-request-1"
    assert result.out_amount == 250_000_000
    assert result.transaction == "UNSIGNED_ORDER_TRANSACTION_PRESENT_NO_SIGNATURE"
    assert "transaction" not in result.raw
    assert result.raw["rawTransactionPersisted"] is False
    assert result.raw["buildEndpointCalled"] is False
    assert result.raw["executeEndpointCalled"] is False
    assert result.request_timing["order"] is not None
    assert result.request_timing["build"] is None


def test_r42_order_only_shadow_fail_closed_when_transaction_missing(monkeypatch):
    client = jup.JupiterSwapClient(
        api_key="test",
        base_url="https://example.invalid",
        persistent_http=False,
        shared_rate_limit=True,
    )
    payload = _valid_order_payload()
    payload["transaction"] = ""
    payload["errorCode"] = 3
    payload["errorMessage"] = "could not build"

    monkeypatch.setattr(client, "_request_json", lambda *a, **k: payload)
    with pytest.raises(JupiterSwapError) as exc:
        client.get_order_only_shadow(
            input_mint="So11111111111111111111111111111111111111112",
            output_mint="TokenMint",
            amount_raw=10_000_000,
            taker="PublicTaker",
            slippage_bps=300,
        )
    assert exc.value.code == "JUPITER_ORDER_ONLY_TRANSACTION_MISSING"


def test_r42_order_only_shadow_fail_closed_on_signed_artifact(monkeypatch):
    client = jup.JupiterSwapClient(
        api_key="test",
        base_url="https://example.invalid",
        persistent_http=False,
        shared_rate_limit=True,
    )
    payload = _valid_order_payload()
    payload["signature"] = "unexpected"
    monkeypatch.setattr(client, "_request_json", lambda *a, **k: payload)

    with pytest.raises(JupiterSwapError) as exc:
        client.get_order_only_shadow(
            input_mint="So11111111111111111111111111111111111111112",
            output_mint="TokenMint",
            amount_raw=10_000_000,
            taker="PublicTaker",
            slippage_bps=300,
        )
    assert exc.value.code == "JUPITER_ORDER_ONLY_SIGNED_ARTIFACT_FORBIDDEN"


def test_r42_candidate_callsite_uses_order_only_and_m320_deferred_path_stays_inactive():
    source = inspect.getsource(fast.record_fastpath_candidate_notification)
    assert "quote = _candidate_order_only_quote(" in source
    assert "quote = _candidate_entry_quote(" not in source
    assert "PENDING_POST_COMMIT_LOW_PRIORITY" in source
    assert '"candidate_build_priority"' in source

    helper = inspect.getsource(fast._candidate_order_only_quote)
    assert '"candidate_order_only": True' in helper
    assert '"candidate_build_priority": False' in helper


def test_r42_m319_component_timing_accepts_order_only_shape(monkeypatch):
    client = jup.JupiterSwapClient(
        api_key="test",
        base_url="https://example.invalid",
        persistent_http=False,
        shared_rate_limit=True,
    )

    def fake_request(method, path, **kwargs):
        sink = kwargs.get("timing_sink")
        if isinstance(sink, dict):
            sink.update(
                {
                    "attempts": 1,
                    "retry_count": 0,
                    "shared_pacing_wait_ms": 0.0,
                    "http_round_trip_ms": 100.0,
                    "retry_sleep_requested_ms": 0.0,
                    "endpoint_total_ms": 100.0,
                    "status_codes": [200],
                    "final_http_status": 200,
                    "success": True,
                    "retryable": True,
                    "shared_rate_limit": True,
                    "used_persistent_http": True,
                }
            )
        return _valid_order_payload()

    monkeypatch.setattr(client, "_request_json", fake_request)
    result = client.get_order_only_shadow(
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="TokenMint",
        amount_raw=10_000_000,
        taker="PublicTaker",
        slippage_bps=300,
    )
    snap = fast._m319_jupiter_component_timing_snapshot(result)
    assert snap is not None
    assert snap["order"] is not None
    assert snap["build"] is None
    assert snap["order_diagnostic_available"] is True
    assert snap["order_diagnostic_mode"] == "ORDER_IS_CANDIDATE_CRITICAL_PATH_SOURCE"


def test_r42_order_only_method_never_executes_signs_or_persists_raw_transaction():
    source = inspect.getsource(jup.JupiterSwapClient.get_order_only_shadow)
    assert '"/order"' in source
    assert '"/build"' not in source
    assert "execute_order(" not in source
    assert '"/execute"' not in source
    assert '"rawTransactionPersisted": False' in source
    assert '"signedTransactionCreated": False' in source
    assert '"signatureCreated": False' in source


def test_r42_global_jupiter_rate_policy_unchanged():
    assert jup._JUPITER_RATE_LIMIT_HEADROOM_RATIO == 0.80
    assert jup._JUPITER_RATE_LIMIT_FALLBACK_RPS == 10


def test_r42_policy_versions_and_gate_remain_unchanged():
    assert fast.M319_COPYABLE_EDGE_VERSION == "m319-copyable-edge-instrumentation/1"
    assert fast.M320_CANDIDATE_ORDER_DIAGNOSTIC_VERSION == "m320-candidate-deferred-order-diagnostic/1"
    assert fast.M314_CANDIDATE_ROUNDTRIP_GATE_ARMED is False
