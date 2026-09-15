from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.app.services import gen4_fastpath_shadow_runtime as runtime_module
import backend.app.services.gen4_fastpath_shadow_service as service


WALLET = "D7Z3ZkAjMnbvjq151vAd8xGfxA636zYz8WMb8DuvEqjd"
TOKEN = "5mHL4MEaATdQoTwLPgAbk9boaK2SUk18WEGB7okZpump"


def _signal(slot=123):
    return SimpleNamespace(
        signature="SIG1",
        slot=slot,
        block_time=None,
        wallet_address=WALLET,
        side="BUY",
        token_mint=TOKEN,
        token_decimals=6,
        token_delta_raw=1_000_000,
        token_pre_raw=0,
        sol_equivalent_delta_lamports=-10_100_000,
        wallet_effective_price_sol=0.01,
        sell_fraction=None,
        evidence={"fee_lamports": 100_000},
    )


def _notification(slot=123):
    return {
        "params": {
            "result": {
                "slot": slot,
                "signature": "SIG1",
                "transaction": {
                    "meta": {},
                    "transaction": {
                        "signatures": ["SIG1"],
                        "message": {"accountKeys": []},
                    },
                },
            }
        }
    }


def test_r18_m319_observation_uses_exact_provider_slot_clock_without_calling_it_block_time():
    provider_time = datetime(2026, 9, 15, 11, 2, 6, 723000, tzinfo=timezone.utc)
    received = provider_time + timedelta(milliseconds=314)
    parsed = received + timedelta(milliseconds=2)
    event = SimpleNamespace(slot=123, fast_received_at=received, evidence={})
    clock = {
        "slot": 123,
        "server_timestamp_ms": int(provider_time.timestamp() * 1000),
        "type": "firstShredReceived",
        "local_received_at_utc": (provider_time + timedelta(milliseconds=25)).isoformat(),
    }
    observation = service._new_m319_candidate_observation(
        event=event,
        signal=_signal(),
        received_at=received,
        parsed_at=parsed,
        provider_slot_clock=clock,
    )
    assert observation["source_block_time_utc"] is None
    assert observation["chain_to_receive_ms"] is None
    assert observation["source_provider_slot_type"] == "firstShredReceived"
    assert observation["provider_slot_to_receive_ms"] == 314
    assert observation["provider_slot_clock"]["origin"] == "HELIUS_SLOTS_UPDATES_SERVER_TIMESTAMP"
    assert observation["provider_slot_clock"]["true_chain_block_time"] is False


def test_r18_provider_slot_clock_must_match_transaction_slot_exactly():
    received = datetime(2026, 9, 15, 11, 2, 7, tzinfo=timezone.utc)
    observation = service._new_m319_candidate_observation(
        event=SimpleNamespace(slot=123),
        signal=_signal(slot=123),
        received_at=received,
        parsed_at=received,
        provider_slot_clock={
            "slot": 122,
            "server_timestamp_ms": int((received - timedelta(seconds=1)).timestamp() * 1000),
            "type": "completed",
            "local_received_at_utc": received.isoformat(),
        },
    )
    assert observation["source_provider_slot_time_utc"] is None
    assert observation["provider_slot_to_receive_ms"] is None
    assert observation["provider_slot_clock"] is None


def test_r18_buy_quote_adds_provider_slot_to_quote_metric_separate_from_chain_metric():
    provider_time = datetime(2026, 9, 15, 11, 2, 6, 700000, tzinfo=timezone.utc)
    received = provider_time + timedelta(milliseconds=300)
    event = SimpleNamespace(slot=123, fast_received_at=received, evidence={})
    observation = service._new_m319_candidate_observation(
        event=event,
        signal=_signal(),
        received_at=received,
        parsed_at=received + timedelta(milliseconds=2),
        provider_slot_clock={
            "slot": 123,
            "server_timestamp_ms": int(provider_time.timestamp() * 1000),
            "type": "firstShredReceived",
            "local_received_at_utc": (provider_time + timedelta(milliseconds=20)).isoformat(),
        },
    )
    service._m319_set_candidate_observation(event, observation)
    quote = SimpleNamespace(
        requested_at=received + timedelta(milliseconds=12),
        received_at=received + timedelta(milliseconds=462),
        latency_ms=450,
        result=SimpleNamespace(transaction="unsigned"),
    )
    service._m319_update_buy_quote(
        event,
        quote=quote,
        deterioration_bps=80.0,
        price_impact_bps=20.0,
        rejection_reason=None,
    )
    entry = event.evidence[service.M319_COPYABLE_EDGE_EVIDENCE_KEY]["follower_entry"]
    assert entry["chain_to_quote_received_ms"] is None
    assert entry["provider_slot_to_quote_received_ms"] == 762
    assert entry["receive_to_quote_received_ms"] == 462


def test_r18_runtime_slot_cache_prefers_first_shred_and_is_bounded_observation_only():
    rt = runtime_module.EmbeddedGen4FastpathShadowRuntime()
    base = datetime(2026, 9, 15, 11, 2, 6, tzinfo=timezone.utc)
    completed = {
        "params": {"result": {"slot": 123, "timestamp": 1_789_470_126_900, "type": "completed"}}
    }
    first = {
        "params": {"result": {"slot": 123, "timestamp": 1_789_470_126_700, "type": "firstShredReceived"}}
    }
    rt._record_candidate_slot_update(completed, base)
    rt._record_candidate_slot_update(first, base + timedelta(milliseconds=5))
    clock = rt._candidate_slot_clock_for_message(_notification(123))
    assert clock is not None
    assert clock["type"] == "firstShredReceived"
    assert clock["server_timestamp_ms"] == 1_789_470_126_700
    assert rt._candidate_slot_clock_hits == 1
    assert rt._candidate_slot_clock_updates == 2
    assert rt._candidate_slot_clock_for_message(_notification(124)) is None
    assert rt._candidate_slot_clock_misses == 1


def test_r18_candidate_wss_uses_dual_subscription_on_same_connection_without_waiting_for_slot_clock():
    source = inspect.getsource(runtime_module.EmbeddedGen4FastpathShadowRuntime._run_candidate)
    assert source.count("async with connect(") == 1
    assert '"method": "transactionSubscribe"' in source
    assert '"method": "slotsUpdatesSubscribe"' in source
    slot_branch = source.index('message.get("method") == "slotsUpdatesNotification"')
    transaction_branch = source.index('message.get("method") != "transactionNotification"')
    dispatch = source.index("self._candidate_messages += 1")
    assert slot_branch < transaction_branch < dispatch
    assert "await asyncio.sleep" not in source[slot_branch:dispatch]


def test_r18_preserves_m317_two_argument_record_contract_and_passes_clock_via_internal_metadata():
    handle = inspect.getsource(runtime_module.EmbeddedGen4FastpathShadowRuntime._handle_candidate)
    record = inspect.getsource(runtime_module.EmbeddedGen4FastpathShadowRuntime._record_candidate)
    assert handle.index("provider_slot_clock =") < handle.index("async with lock:")
    assert handle.index("async with lock:") < handle.index("async with semaphore:")
    assert '"_m319_provider_slot_clock": provider_slot_clock' in handle
    assert "record_message," in handle
    assert "provider_slot_clock," not in handle[handle.index("await asyncio.to_thread("):]
    runtime_signature = inspect.signature(
        runtime_module.EmbeddedGen4FastpathShadowRuntime._record_candidate
    )
    assert list(runtime_signature.parameters) == ["self", "message", "received_at"]
    assert 'message.get("_m319_provider_slot_clock")' in record
    signature = inspect.signature(service.record_fastpath_candidate_notification)
    assert signature.parameters["provider_slot_clock"].default is None
    assert service.M314_CANDIDATE_ROUNDTRIP_GATE_ARMED is False
    assert service.M319_COPYABLE_EDGE_VERSION == "m319-copyable-edge-instrumentation/1"


def test_r18_slot_stream_cannot_starve_candidate_wallet_refresh():
    source = inspect.getsource(runtime_module.EmbeddedGen4FastpathShadowRuntime._run_candidate)
    assert "next_wallet_refresh =" in source
    assert "now_monotonic >= next_wallet_refresh" in source
    assert "recv_timeout = max(" in source
    assert "await asyncio.to_thread(self._candidate_wallets)" in source


def test_r18_status_truthfully_reports_slot_clock_on_same_candidate_connection():
    rt = runtime_module.EmbeddedGen4FastpathShadowRuntime()
    status = rt.status["candidate"]
    assert status["slot_clock_source"] == "HELIUS_SLOTS_UPDATES_SERVER_TIMESTAMP"
    assert status["slot_clock_true_chain_block_time"] is False
    assert status["separate_wss_connection"] is False
