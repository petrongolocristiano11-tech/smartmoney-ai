from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.app.services.gen4_selective_copyability_gate_service import (
    SELECTIVE_GATE_FORMAL_ARMED,
    _percentile95,
    classify_buy_attempt,
    evaluate_selective_copyability_gate,
)
from backend.app.services.gen4_zero_helius_final_pre_micro_live_service import validate_policy


def _campaign(formal_m74=True):
    return SimpleNamespace(
        campaign_id="c1",
        selection_snapshot={"formal_m74_pass": formal_m74},
        max_quote_latency_ms=5000,
        max_price_impact_bps=500,
        max_price_deterioration_bps=1000,
    )


def _buy(i, start, *, accepted=True, reason=None, error=None, det=300.0, impact=10.0):
    t = start + timedelta(hours=i * 2)
    return SimpleNamespace(
        wallet_address="w",
        campaign_id="c1",
        side="BUY",
        signature=f"s{i}",
        fast_received_at=t,
        fast_quote_received_at=t + timedelta(milliseconds=500),
        fast_end_to_quote_ms=500.0,
        fast_transaction_built=accepted or bool(reason),
        fast_provisional_copyable=accepted,
        fast_provisional_rejection_reason=reason,
        fast_price_impact_bps=impact,
        fast_price_deterioration_bps=det,
        quote_error_code=error,
        parse_error_code=None,
        policy_snapshot={
            "max_quote_latency_ms": 5000,
            "max_price_impact_bps": 500,
            "max_price_deterioration_bps": 1000,
            "max_signal_age_ms": 20000,
        },
    )


def _receipt(i, start):
    t = start + timedelta(hours=i * 2)
    return SimpleNamespace(
        source="WEBHOOK",
        auth_verified=True,
        signature=f"s{i}",
        received_at=t + timedelta(seconds=2),
        block_time=t,
        parsed_summary={},
    )


def _position(i, start, pnl=1_000_000):
    return SimpleNamespace(
        wallet_address="w",
        campaign_id="c1",
        scope="OFFICIAL_FASTPATH_SELECTIVE",
        position_id=f"p{i}",
        entry_signature=f"s{i}",
        status="CLOSED",
        opened_at=start + timedelta(hours=i * 2),
        closed_at=start + timedelta(hours=i * 2, minutes=5),
        remaining_token_raw=0,
        exit_copyable=True,
        exit_transaction_built=True,
        exit_quote_latency_ms=500,
        exit_price_impact_bps=10,
        pnl_lamports=pnl,
        evidence={"exit_failures": []},
    )



def test_m291_reads_exact_frozen_m75_policy_keys():
    p = validate_policy()
    assert p["canary_minimum_observation_hours"] == 24.0
    assert p["canary_minimum_entry_attempts"] == 20
    assert p["canary_minimum_closed_trades"] == 10
    assert p["canary_minimum_webhook_coverage_percent"] == 95.0
    assert p["canary_minimum_unsigned_build_coverage_percent"] == 100.0
    assert p["canary_maximum_p95_end_to_quote_ms"] == 5000.0
    assert p["canary_maximum_p95_price_impact_bps"] == 500.0
    assert p["canary_maximum_p95_price_deterioration_bps"] == 1000.0


def test_m291_p95_matches_frozen_m75_nearest_rank():
    assert _percentile95([100.0, 200.0, 300.0, 400.0, 500.0]) == 500.0
    assert _percentile95([100.0]) == 100.0
    assert _percentile95([]) is None


def test_m291_is_disarmed():
    assert SELECTIVE_GATE_FORMAL_ARMED is False


def test_market_protective_reject_is_not_technical_failure():
    row = SimpleNamespace(
        fast_provisional_copyable=False,
        fast_transaction_built=True,
        fast_provisional_rejection_reason="PRICE_ALREADY_MOVED",
        parse_error_code=None,
        quote_error_code=None,
    )
    assert classify_buy_attempt(row) == (
        "MARKET_PROTECTIVE_REJECT",
        "PRICE_ALREADY_MOVED",
    )


def test_jupiter_and_quote_too_slow_are_technical():
    jupiter = SimpleNamespace(
        fast_provisional_copyable=False,
        fast_transaction_built=False,
        fast_provisional_rejection_reason=None,
        parse_error_code=None,
        quote_error_code="JUPITER_HTTP_ERROR",
    )
    slow = SimpleNamespace(
        fast_provisional_copyable=False,
        fast_transaction_built=True,
        fast_provisional_rejection_reason="QUOTE_TOO_SLOW",
        parse_error_code=None,
        quote_error_code=None,
    )
    assert classify_buy_attempt(jupiter)[0] == "TECHNICAL_FAILURE"
    assert classify_buy_attempt(slow)[0] == "TECHNICAL_FAILURE"


def test_high_protective_reject_rate_can_still_pass_selective_diagnostic():
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    events = []
    positions = []
    receipts = []
    # 20 attempts over 38h: 10 accepted, 10 protective rejects (50% total reject).
    for i in range(20):
        if i < 10:
            events.append(_buy(i, start, accepted=True))
            positions.append(_position(i, start, pnl=1_000_000))
        else:
            events.append(
                _buy(
                    i,
                    start,
                    accepted=False,
                    reason="PRICE_ALREADY_MOVED",
                    det=3000.0,
                )
            )
        receipts.append(_receipt(i, start))
    result = evaluate_selective_copyability_gate(
        wallet="w",
        events=events,
        positions=positions,
        receipts=receipts,
        campaign=_campaign(True),
        terminal_at=start + timedelta(hours=40),
    )
    assert result["clean_window"]["market_protective_rejects"] == 10
    assert result["hard_checks"]["entry_attempts"] is True
    assert result["hard_checks"]["closed_trades"] is True
    assert result["operational_pass"] is True
    assert result["economic_floor_pass"] is True
    assert result["diagnostic_selective_pass_without_m74"] is True
    assert result["formal_selective_pass"] is False
    assert result["would_be_formal_ready_if_armed"] is False


def test_technical_failure_resets_window_and_old_trades_do_not_count():
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    events = []
    positions = []
    receipts = []
    for i in range(20):
        events.append(_buy(i, start, accepted=True))
        positions.append(_position(i, start))
        receipts.append(_receipt(i, start))
    failure = _buy(20, start, accepted=False, error="JUPITER_HTTP_ERROR")
    events.append(failure)
    receipts.append(_receipt(20, start))
    # Only 3 attempts after the failure.
    for i in range(21, 24):
        events.append(_buy(i, start, accepted=True))
        positions.append(_position(i, start))
        receipts.append(_receipt(i, start))
    result = evaluate_selective_copyability_gate(
        wallet="w",
        events=events,
        positions=positions,
        receipts=receipts,
        campaign=_campaign(True),
        terminal_at=start + timedelta(hours=50),
    )
    assert result["clean_window"]["attempts"] == 3
    assert result["economics"]["closed_trades"] == 3
    assert result["hard_checks"]["entry_attempts"] is False
    assert result["diagnostic_selective_pass_without_m74"] is False


def test_one_accepted_trade_cannot_pass_even_if_profitable():
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    events = [_buy(0, start, accepted=True)]
    positions = [_position(0, start, pnl=5_000_000)]
    receipts = [_receipt(0, start)]
    for i in range(1, 20):
        events.append(
            _buy(
                i,
                start,
                accepted=False,
                reason="PRICE_ALREADY_MOVED",
                det=5000.0,
            )
        )
        receipts.append(_receipt(i, start))
    result = evaluate_selective_copyability_gate(
        wallet="w",
        events=events,
        positions=positions,
        receipts=receipts,
        campaign=_campaign(True),
        terminal_at=start + timedelta(hours=40),
    )
    assert result["hard_checks"]["entry_attempts"] is True
    assert result["hard_checks"]["closed_trades"] is False
    assert result["diagnostic_selective_pass_without_m74"] is False


def test_missing_formal_m74_never_creates_formal_readiness():
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    events = []
    positions = []
    receipts = []
    for i in range(20):
        if i < 10:
            events.append(_buy(i, start, accepted=True))
            positions.append(_position(i, start))
        else:
            events.append(_buy(i, start, accepted=False, reason="PRICE_ALREADY_MOVED", det=4000))
        receipts.append(_receipt(i, start))
    result = evaluate_selective_copyability_gate(
        wallet="w",
        events=events,
        positions=positions,
        receipts=receipts,
        campaign=_campaign(False),
        terminal_at=start + timedelta(hours=40),
    )
    assert result["diagnostic_selective_pass_without_m74"] is True
    assert result["formal_m74_admitted"] is False
    assert result["would_be_formal_ready_if_armed"] is False
    assert result["formal_selective_pass"] is False


def test_negative_economics_fail_floor_even_when_operational_quality_is_good():
    start = datetime(2026, 8, 1, tzinfo=timezone.utc)
    events = []
    positions = []
    receipts = []
    for i in range(20):
        if i < 10:
            events.append(_buy(i, start, accepted=True))
            positions.append(_position(i, start, pnl=-1_000_000))
        else:
            events.append(_buy(i, start, accepted=False, reason="PRICE_ALREADY_MOVED", det=4000))
        receipts.append(_receipt(i, start))
    result = evaluate_selective_copyability_gate(
        wallet="w",
        events=events,
        positions=positions,
        receipts=receipts,
        campaign=_campaign(True),
        terminal_at=start + timedelta(hours=40),
    )
    assert result["operational_pass"] is True
    assert result["economic_floor_pass"] is False
    assert result["diagnostic_selective_pass_without_m74"] is False
