from __future__ import annotations

import ast
import inspect
import textwrap

import backend.app.services.jupiter_swap_client as jup
import backend.app.services.gen4_fastpath_shadow_service as fast
import backend.app.services.gen4_fastpath_shadow_runtime as runtime


def _valid_build_payload():
    return {
        "requestId": "build-request",
        "inAmount": "10000000",
        "outAmount": "250000000",
        "otherAmountThreshold": "242500000",
        "slippageBps": 300,
        "router": "metis",
        "priceImpact": "0.001",
        "swapInstruction": {
            "programId": "11111111111111111111111111111111",
            "data": "AA==",
            "accounts": [],
        },
        "blockhashWithMetadata": {
            "blockhash": "abc",
            "lastValidBlockHeight": 123456,
        },
        "setupInstructions": [],
        "computeBudgetInstructions": [],
        "otherInstructions": [],
        "addressesByLookupTableAddress": {},
    }


def test_build_priority_request_is_critical_and_order_diagnostic_is_low_priority(monkeypatch):
    client = jup.JupiterSwapClient(
        api_key="test",
        base_url="https://example.invalid",
        persistent_http=False,
        shared_rate_limit=True,
    )
    calls = []

    def fake_request(method, path, **kwargs):
        calls.append((method, path, kwargs.get("request_priority")))
        sink = kwargs.get("timing_sink")
        if isinstance(sink, dict):
            sink.update(
                {
                    "version": "jupiter-component-timing/1",
                    "path": path,
                    "request_priority": kwargs.get("request_priority"),
                    "endpoint_total_ms": 1.0,
                    "shared_pacing_wait_ms": 0.0,
                    "http_round_trip_ms": 1.0,
                    "retry_sleep_requested_ms": 0.0,
                    "attempts": 1,
                    "retry_count": 0,
                    "status_codes": [200],
                    "final_http_status": 200,
                    "success": True,
                }
            )
        if path == "/build":
            return _valid_build_payload()
        if path == "/order":
            return {
                "requestId": "order-request",
                "inAmount": "10000000",
                "outAmount": "249000000",
                "router": "metis",
                "priceImpact": "0.0012",
            }
        raise AssertionError(path)

    monkeypatch.setattr(client, "_request_json", fake_request)

    result = client.get_build_priority_unsigned(
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="TokenMint",
        amount_raw=10_000_000,
        taker="PublicTaker",
        slippage_bps=300,
        mode="fast",
    )
    diag = client.get_order_diagnostic(
        input_mint="So11111111111111111111111111111111111111112",
        output_mint="TokenMint",
        amount_raw=10_000_000,
        slippage_bps=300,
    )

    assert result.out_amount == 250000000
    assert result.raw["orderDiagnosticAvailable"] is False
    assert diag["outAmount"] == "249000000"
    assert calls == [
        ("GET", "/build", "critical"),
        ("GET", "/order", "diagnostic"),
    ]


def test_shared_coordinator_has_explicit_critical_waiter_priority_contract():
    source = inspect.getsource(jup._SharedJupiterRateLimitCoordinator)
    assert "_critical_waiters" in source
    assert '"diagnostic"' in source
    assert '"critical"' in source
    assert "self._critical_waiters > 0" in source
    assert "JUPITER_RATE_LIMIT_PRIORITY_INVALID" in source


def test_request_timing_persists_priority_without_changing_global_headroom():
    source = inspect.getsource(jup.JupiterSwapClient._request_json)
    assert '"request_priority": normalized_request_priority' in source
    assert 'if normalized_request_priority == "normal"' in source
    assert '_SHARED_JUPITER_RATE_LIMIT_COORDINATOR.acquire()' in source
    assert "priority=normalized_request_priority" in source
    assert jup._JUPITER_RATE_LIMIT_HEADROOM_RATIO == 0.80
    assert jup._JUPITER_RATE_LIMIT_FALLBACK_RPS == 10


def test_candidate_buy_persists_pending_diagnostic_for_accepted_and_rejected_paths():
    source = inspect.getsource(fast.record_fastpath_candidate_notification)
    assert "PENDING_POST_COMMIT_LOW_PRIORITY" in source
    assert '"covers_rejected_buys": True' in source
    assert "candidate_order_diagnostic_request" in source
    assert "deferred_order_diagnostic" in source

    quote_index = source.index("_m319_update_buy_quote(")
    pending_index = source.index("PENDING_POST_COMMIT_LOW_PRIORITY")
    accepted_index = source.index("if reason is None:", pending_index)
    assert quote_index < pending_index < accepted_index


def test_deferred_diagnostic_is_observation_only_and_idempotent():
    source = inspect.getsource(fast.record_candidate_order_diagnostic)
    assert '"affects_entry_decision": False' in source
    assert '"critical_path": False' in source
    assert '"state": "COMPLETE"' in source
    assert "DIAGNOSTIC_ALREADY_COMPLETE" in source
    assert "build_vs_order_out_bps" in source
    assert "live_execution" in source
    assert "signer_access" in source


def test_pending_diagnostics_are_restart_recoverable():
    source = inspect.getsource(fast.load_pending_candidate_order_diagnostics)
    assert "PENDING_POST_COMMIT_LOW_PRIORITY" in source
    assert ".limit(scan_limit)" in source
    assert "pending.reverse()" in source

    runtime_source = inspect.getsource(runtime.EmbeddedGen4FastpathShadowRuntime.start)
    assert "_load_pending_candidate_order_diagnostics" in runtime_source
    assert "_candidate_order_diagnostic_recovered_pending" in runtime_source


def test_runtime_enqueues_diagnostic_after_candidate_lock_and_semaphore_release():
    source = textwrap.dedent(
        inspect.getsource(runtime.EmbeddedGen4FastpathShadowRuntime._handle_candidate)
    )
    tree = ast.parse(source)
    func = tree.body[0]
    assert isinstance(func, ast.AsyncFunctionDef)

    async_with_positions = [
        i for i, node in enumerate(func.body) if isinstance(node, ast.AsyncWith)
    ]
    assert async_with_positions
    outer_index = async_with_positions[0]

    enqueue_indices = []
    for i, node in enumerate(func.body):
        text = ast.unparse(node)
        if "_enqueue_candidate_order_diagnostic" in text:
            enqueue_indices.append(i)
    assert enqueue_indices
    assert min(enqueue_indices) > outer_index


def test_runtime_worker_has_separate_queue_and_never_submits_transactions():
    source = inspect.getsource(runtime.EmbeddedGen4FastpathShadowRuntime)
    assert "asyncio.Queue(maxsize=256)" in source
    assert "_run_candidate_order_diagnostics" in source
    assert "_record_candidate_order_diagnostic" in source
    assert "candidate_order_diagnostic" in source
    # The diagnostic worker only delegates to the observation-only service.
    worker = inspect.getsource(
        runtime.EmbeddedGen4FastpathShadowRuntime._record_candidate_order_diagnostic
    )
    assert "record_candidate_order_diagnostic" in worker
    assert "execute_order" not in worker
