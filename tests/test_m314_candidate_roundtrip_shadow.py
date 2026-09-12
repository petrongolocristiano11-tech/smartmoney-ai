from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import inspect

import backend.app.services.gen4_fastpath_shadow_service as service


def _row(event_id: str, state: dict):
    return SimpleNamespace(
        event_id=event_id,
        evidence={service.M314_CANDIDATE_ROUNDTRIP_EVIDENCE_KEY: state},
    )


def _state(*, pnl=None, status="OPEN", closed_at=None, output=1_000_000):
    return {
        "version": service.M314_CANDIDATE_ROUNDTRIP_VERSION,
        "scope": service.M314_CANDIDATE_ROUNDTRIP_SCOPE,
        "status": status,
        "wallet_address": "WALLET",
        "token_mint": "TOKEN",
        "entry_signature": "SIG",
        "opened_at": "2026-09-12T16:00:00+00:00",
        "closed_at": closed_at,
        "entry_input_lamports": 100_000_000,
        "entry_output_token_raw": output,
        "remaining_token_raw": 0 if status == "CLOSED" else output,
        "allocated_entry_fee_lamports": 100_000,
        "realized_output_lamports": 0,
        "allocated_exit_fee_lamports": 0,
        "pnl_lamports": pnl,
        "return_percent": None,
        "exit_copyable": status == "CLOSED",
        "exit_failures": [],
    }


def test_m314_gate_is_disarmed_and_cannot_authorize_m307():
    assert service.M314_CANDIDATE_ROUNDTRIP_GATE_ARMED is False
    result = service._candidate_roundtrip_metrics_from_events([])
    assert result["gate_armed"] is False
    assert result["m307_authorized"] is False
    assert result["safety"]["automatic_promotion"] is False


def test_m314_metrics_require_positive_without_best_trade():
    rows = []
    base = datetime(2026, 9, 12, 16, tzinfo=timezone.utc)
    pnls = [10_000_000] + [-100_000] * 9
    for i, pnl in enumerate(pnls):
        state = _state(
            pnl=pnl,
            status="CLOSED",
            closed_at=(base + timedelta(minutes=i)).isoformat(),
        )
        rows.append(_row(f"E{i}", state))
    result = service._candidate_roundtrip_metrics_from_events(rows)
    assert result["closed_trade_count"] == 10
    assert result["net_pnl_lamports"] > 0
    assert result["net_without_best_trade_lamports"] < 0
    assert result["economic_observation_pass"] is False


def test_m314_metrics_can_pass_observation_without_authorizing_promotion():
    rows = []
    base = datetime(2026, 9, 12, 16, tzinfo=timezone.utc)
    pnls = [2_000_000] * 8 + [-500_000] * 2
    for i, pnl in enumerate(pnls):
        state = _state(
            pnl=pnl,
            status="CLOSED",
            closed_at=(base + timedelta(minutes=i)).isoformat(),
        )
        rows.append(_row(f"E{i}", state))
    result = service._candidate_roundtrip_metrics_from_events(rows)
    assert result["closed_trade_count"] == 10
    assert result["profit_factor"] >= 1.30
    assert result["net_pnl_lamports"] > 0
    assert result["net_without_best_trade_lamports"] > 0
    assert result["economic_observation_pass"] is True
    assert result["m307_authorized"] is False


def test_m314_allocation_closes_full_sell_and_computes_net_pnl():
    state = _state(output=1_000_000)
    row = _row("ENTRY1", state)
    now = datetime(2026, 9, 12, 17, tzinfo=timezone.utc)
    quote = SimpleNamespace(
        latency_ms=100,
        requested_at=now,
        received_at=now + timedelta(milliseconds=100),
        sanitized={"route":"test"},
        result=SimpleNamespace(
            price_impact_percent=0.001,
            transaction="unsigned",
            out_amount=120_000_000,
        ),
    )
    signal = SimpleNamespace(signature="SELL1", sell_fraction=1.0)
    result = service._candidate_roundtrip_apply_allocations(
        [row],
        signal=signal,
        quote=quote,
        conservative_out=120_000_000,
        amount_to_sell=1_000_000,
        fee_lamports=100_000,
    )
    updated = service._candidate_roundtrip_state(row)
    assert result == {"positions_affected":1,"positions_closed":1}
    assert updated is not None
    assert updated["status"] == "CLOSED"
    assert updated["remaining_token_raw"] == 0
    assert updated["pnl_lamports"] == 19_800_000
    assert updated["close_reason"] == "MIRRORED_WALLET_EXIT"


def test_candidate_recorder_keeps_m300_sell_semantics_and_adds_m314_capture():
    source = inspect.getsource(service.record_fastpath_candidate_notification)
    assert 'event.fast_provisional_rejection_reason = "NOT_A_BUY_SIGNAL"' in source
    assert "_apply_candidate_roundtrip_sell_shadow" in source
    assert "sell_fraction" in source
    assert "M314_CANDIDATE_ROUNDTRIP_EVIDENCE_KEY" in source
