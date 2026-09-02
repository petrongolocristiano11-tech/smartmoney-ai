from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.app.services.gen4_fastpath_native_m75_evidence_service import (
    FASTPATH_NATIVE_M75_FORMAL_ARMED,
    build_fastpath_native_m75_bridge,
)

BASE = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
WALLET = "A" * 32
CAMPAIGN_ID = "11111111-1111-1111-1111-111111111111"


def campaign(formal=True):
    return SimpleNamespace(
        id=1,
        campaign_id=CAMPAIGN_ID,
        selection_snapshot={"formal_m74_pass": formal},
        max_quote_latency_ms=5000,
        max_price_impact_bps=500,
        max_price_deterioration_bps=1000,
    )


def event(i, *, accepted=True, det=100.0, impact=5.0, built=True, quote_error=None, parse_error=None):
    received = BASE + timedelta(minutes=i)
    return SimpleNamespace(
        signature=f"sig{i}",
        wallet_address=WALLET,
        campaign_id=CAMPAIGN_ID,
        side="BUY",
        fast_received_at=received,
        fast_quote_received_at=received + timedelta(milliseconds=900),
        fast_end_to_quote_ms=None,
        fast_prequote_ms=300,
        fast_quote_latency_ms=600,
        fast_price_deterioration_bps=det,
        fast_price_impact_bps=impact,
        fast_transaction_built=built,
        fast_provisional_copyable=accepted,
        fast_provisional_rejection_reason=None if accepted else "PRICE_ALREADY_MOVED",
        parse_error_code=parse_error,
        quote_error_code=quote_error,
        policy_snapshot={
            "max_signal_age_ms": 20000,
            "max_quote_latency_ms": 5000,
            "max_price_impact_bps": 500,
            "max_price_deterioration_bps": 1000,
        },
    )


def receipt(i):
    return SimpleNamespace(
        signature=f"sig{i}",
        source="WEBHOOK",
        auth_verified=True,
        block_time=BASE + timedelta(minutes=i) - timedelta(milliseconds=100),
        received_at=BASE + timedelta(minutes=i, seconds=2),
    )


def position(i, *, pnl=1_000_000, exit_failure=None):
    evidence = {}
    if exit_failure:
        evidence["exit_failures"] = [
            {"signature": f"sell{i}", "code": exit_failure, "observed_at": (BASE + timedelta(hours=2)).isoformat()}
        ]
    return SimpleNamespace(
        position_id=f"pos{i}",
        scope="OFFICIAL_FASTPATH_SELECTIVE",
        campaign_id=CAMPAIGN_ID,
        wallet_address=WALLET,
        entry_signature=f"sig{i}",
        status="CLOSED",
        opened_at=BASE + timedelta(minutes=i, seconds=1),
        closed_at=BASE + timedelta(hours=1, minutes=i),
        remaining_token_raw=0,
        exit_copyable=True,
        exit_transaction_built=True,
        exit_quote_latency_ms=500,
        exit_price_impact_bps=10.0,
        pnl_lamports=pnl,
        evidence=evidence,
    )


def healthy_inputs(formal=True):
    events = [event(i, accepted=i >= 4) for i in range(20)]  # exact 20% reject
    positions = [position(i) for i in range(4, 14)]
    receipts = [receipt(i) for i in range(19)]  # exact 95% coverage
    return events, positions, receipts, campaign(formal=formal)


def test_bridge_is_permanently_disarmed_in_m282():
    assert FASTPATH_NATIVE_M75_FORMAL_ARMED is False


def test_exact_m75_boundaries_project_pass_but_never_claim_formal_m75():
    events, positions, receipts, camp = healthy_inputs(formal=True)
    out = build_fastpath_native_m75_bridge(
        wallet=WALLET,
        events=events,
        positions=positions,
        receipts=receipts,
        campaign=camp,
        terminal_at=BASE + timedelta(hours=24),
    )
    assert out["evaluation_with_actual_m74"]["passed"] is True
    assert out["formal_m75_claimed"] is False
    assert out["formal_m75_pass"] is False
    assert out["micro_live_execution_authorized"] is False
    assert out["evaluation_with_actual_m74"]["metrics"]["webhook_coverage_percent"] == 95.0
    assert out["evaluation_with_actual_m74"]["metrics"]["entry_reject_rate_percent"] == 20.0
    assert out["evaluation_with_actual_m74"]["metrics"]["terminal_state_count"] == 1


def test_formal_m74_is_never_bypassed():
    events, positions, receipts, camp = healthy_inputs(formal=False)
    out = build_fastpath_native_m75_bridge(
        wallet=WALLET,
        events=events,
        positions=positions,
        receipts=receipts,
        campaign=camp,
        terminal_at=BASE + timedelta(hours=24),
    )
    assert out["formal_m74_admitted"] is False
    assert out["evaluation_with_actual_m74"]["passed"] is False
    assert out["evaluation_with_actual_m74"]["checks"]["m74_admitted"] is False
    assert out["diagnostic_evaluation_assuming_m74_only"]["passed"] is True
    assert out["formal_m75_pass"] is False


def test_posthoc_webhook_reconciliation_uses_authenticated_receipts():
    events, positions, receipts, camp = healthy_inputs(formal=True)
    receipts[0].auth_verified = False
    out = build_fastpath_native_m75_bridge(
        wallet=WALLET, events=events, positions=positions, receipts=receipts,
        campaign=camp, terminal_at=BASE + timedelta(hours=24),
    )
    assert out["evaluation_with_actual_m74"]["metrics"]["webhook_coverage_percent"] == 90.0
    assert out["evaluation_with_actual_m74"]["checks"]["webhook_coverage"] is False


def test_quote_error_maps_to_worker_failure_and_unresolved_terminal_failure():
    events, positions, receipts, camp = healthy_inputs(formal=True)
    events[10].quote_error_code = "JUPITER_TIMEOUT"
    events[10].fast_quote_received_at = None
    events[10].fast_transaction_built = False
    events[10].fast_provisional_copyable = False
    out = build_fastpath_native_m75_bridge(
        wallet=WALLET, events=events, positions=positions, receipts=receipts,
        campaign=camp, terminal_at=BASE + timedelta(hours=24),
    )
    ev = out["evaluation_with_actual_m74"]
    assert ev["checks"]["worker_failures"] is False
    assert ev["checks"]["zero_unresolved_failures"] is False
    assert ev["metrics"]["unresolved_failure_count"] >= 1


def test_exit_failure_maps_to_worker_failure():
    events, positions, receipts, camp = healthy_inputs(formal=True)
    positions[0].evidence = {"exit_failures": [{
        "signature": "sell-x", "code": "JUPITER_TIMEOUT", "observed_at": (BASE + timedelta(hours=2)).isoformat()
    }]}
    out = build_fastpath_native_m75_bridge(
        wallet=WALLET, events=events, positions=positions, receipts=receipts,
        campaign=camp, terminal_at=BASE + timedelta(hours=24),
    )
    assert out["evaluation_with_actual_m74"]["checks"]["worker_failures"] is False


def test_accepted_entry_over_policy_is_a_policy_violation():
    events, positions, receipts, camp = healthy_inputs(formal=True)
    events[10].fast_price_deterioration_bps = 1200.0
    events[10].fast_provisional_copyable = True
    out = build_fastpath_native_m75_bridge(
        wallet=WALLET, events=events, positions=positions, receipts=receipts,
        campaign=camp, terminal_at=BASE + timedelta(hours=24),
    )
    ev = out["evaluation_with_actual_m74"]
    assert ev["checks"]["policy_violations"] is False
    # One bad sample out of 20 can still sit above the nearest-rank p95 boundary;
    # the dedicated policy-violation ledger must fail the canary regardless.
    assert out["formal_m75_pass"] is False


def test_missing_timing_fails_closed_instead_of_becoming_zero_ms():
    events, positions, receipts, camp = healthy_inputs(formal=True)
    events[5].fast_quote_received_at = None
    events[5].fast_end_to_quote_ms = None
    events[5].fast_prequote_ms = None
    events[5].fast_quote_latency_ms = None
    events[5].quote_error_code = "MISSING_QUOTE"
    events[5].fast_transaction_built = False
    events[5].fast_provisional_copyable = False
    out = build_fastpath_native_m75_bridge(
        wallet=WALLET, events=events, positions=positions, receipts=receipts,
        campaign=camp, terminal_at=BASE + timedelta(hours=24),
    )
    entry = next(r for r in out["records"] if r.get("signature") == "sig5" and r["event_type"] == "ENTRY_ATTEMPT")
    assert entry["end_to_quote_ms"] > 5000
    assert entry["worker_failure"] is True
    assert out["evaluation_with_actual_m74"]["checks"]["worker_failures"] is False


def test_signed_evidence_integrity_is_present():
    events, positions, receipts, camp = healthy_inputs(formal=True)
    out = build_fastpath_native_m75_bridge(
        wallet=WALLET, events=events, positions=positions, receipts=receipts,
        campaign=camp, terminal_at=BASE + timedelta(hours=24),
    )
    sha = out["signed_m75_evidence"]["integrity"]["payload_sha256"]
    assert isinstance(sha, str) and len(sha) == 64
    assert out["integrity"]["m75_evidence_payload_sha256"] == sha
