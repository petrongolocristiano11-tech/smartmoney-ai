from __future__ import annotations

import pytest

from backend.app.services.gen4_selective_micro_live_readiness_service import (
    SELECTIVE_READINESS_ARMED,
    SelectiveReadinessError,
    evaluate_selective_pool,
    evaluate_selective_wallet,
    sign_selective_evidence,
    validate_policy,
    validate_report,
    validate_selective_evidence,
)
from backend.app.services.gen4_zero_helius_final_pre_micro_live_service import (
    sign_independence_evidence,
    validate_policy as validate_legacy_policy,
)

def _row(wallet: str, **overrides):
    row = {
        "wallet_address": wallet,
        "observation_hours": 25.0,
        "entry_attempts": 20,
        "accepted_attempts": 10,
        "protective_rejects": 10,
        "technical_failures": 0,
        "unmapped_attempts": 0,
        "closed_trades": 10,
        "webhook_coverage_percent": 100.0,
        "accepted_unsigned_build_coverage_percent": 100.0,
        "accepted_p95_end_to_quote_ms": 2000.0,
        "accepted_p95_price_deterioration_bps": 700.0,
        "accepted_p95_price_impact_bps": 50.0,
        "accepted_policy_violations": 0,
        "exit_policy_violations": 0,
        "exit_failures": 0,
        "open_positions": 0,
        "unresolved_failures": 0,
        "net_pnl_sol": 0.04,
        "profit_factor": 1.8,
        "maximum_drawdown_percent": 9.0,
    }
    row.update(overrides)
    return row

def test_contract_disarmed_and_reuses_frozen_thresholds():
    assert SELECTIVE_READINESS_ARMED is False
    p = validate_policy()
    legacy = validate_legacy_policy()
    assert p["minimum_entry_attempts"] == legacy["canary_minimum_entry_attempts"] == 20
    assert p["minimum_closed_trades"] == legacy["canary_minimum_closed_trades"] == 10
    assert p["minimum_profit_factor"] == legacy["minimum_profit_factor"] == 1.30
    assert p["maximum_drawdown_percent"] == legacy["maximum_drawdown_percent"] == 15.0
    assert p["protective_reject_rate_hard_gate"] is False
    assert legacy["canary_maximum_entry_reject_rate_percent"] == 20.0

def test_fifty_percent_protective_reject_can_pass():
    result = evaluate_selective_wallet(
        "A", _row("A"),
        source_m74_audit={"passed": False, "failed_checks": ["drawdown"]},
    )
    assert result["passed"] is True
    assert result["metrics"]["protective_reject_rate_percent"] == 50.0
    assert result["source_m74_audit"]["passed"] is False
    assert result["source_m74_audit"]["used_as_selective_admission_gate"] is False
    assert result["legacy_claims"]["formal_m74_pass_claimed"] is False
    assert result["legacy_claims"]["formal_m75_pass_claimed"] is False

def test_protective_reject_not_gate_but_throughput_is():
    result = evaluate_selective_wallet(
        "A",
        _row("A", accepted_attempts=4, protective_rejects=16, closed_trades=4),
    )
    assert result["metrics"]["protective_reject_rate_percent"] == 80.0
    assert result["checks"]["closed_trades"] is False
    assert result["passed"] is False

def test_technical_failure_fails_closed():
    result = evaluate_selective_wallet(
        "A",
        _row("A", accepted_attempts=9, protective_rejects=10,
             technical_failures=1, closed_trades=9),
    )
    assert result["checks"]["zero_technical_failures"] is False
    assert result["passed"] is False

@pytest.mark.parametrize(
    ("field", "value", "check"),
    [
        ("profit_factor", 1.29, "profit_factor"),
        ("maximum_drawdown_percent", 15.01, "follower_drawdown"),
        ("net_pnl_sol", 0.0, "positive_net_pnl"),
        ("accepted_p95_end_to_quote_ms", 5000.01, "accepted_end_to_quote_p95"),
        ("accepted_p95_price_deterioration_bps", 1000.01, "accepted_price_deterioration_p95"),
        ("accepted_p95_price_impact_bps", 500.01, "accepted_price_impact_p95"),
    ],
)
def test_economic_and_quality_floors_fail_closed(field, value, check):
    result = evaluate_selective_wallet("A", _row("A", **{field: value}))
    assert result["checks"][check] is False
    assert result["passed"] is False

def test_attempt_classification_must_be_complete():
    result = evaluate_selective_wallet(
        "A", _row("A", accepted_attempts=10, protective_rejects=9)
    )
    assert result["checks"]["attempt_classification_complete"] is False
    assert result["passed"] is False

def test_two_independent_selective_pass_wallets_ready_but_never_authorized():
    evidence = sign_selective_evidence(
        {"A": _row("A"), "B": _row("B")},
        anchor_utc="2026-08-31T12:30:50.267406+00:00",
        lineage={"m297": "R3"},
    )
    independence = sign_independence_evidence([
        {"wallet_address": "A", "independence_confirmed": True, "cluster_id": "alpha"},
        {"wallet_address": "B", "independence_confirmed": True, "cluster_id": "beta"},
    ])
    report = evaluate_selective_pool(
        evidence, independence,
        source_m74_audits={
            "A": {"passed": False, "failed_checks": ["drawdown"]},
            "B": {"passed": False, "failed_checks": ["history_span"]},
        },
    )
    assert report["m76_independence_reused"]["passed"] is True
    assert report["micro_live_readiness"]["ready_for_explicit_authorization"] is True
    assert report["micro_live_readiness"]["micro_live_execution_authorized"] is False
    assert report["m77_micro_live_envelope"]["execution_authorized"] is False
    assert all(
        row["source_m74_audit"]["used_as_selective_admission_gate"] is False
        for row in report["selective_wallet_results"]
    )
    validate_report(report)

def test_cluster_collision_blocks_readiness():
    evidence = sign_selective_evidence(
        {"A": _row("A"), "B": _row("B")},
        anchor_utc="2026-08-31T12:30:50.267406+00:00",
    )
    independence = sign_independence_evidence([
        {"wallet_address": "A", "independence_confirmed": True, "cluster_id": "same"},
        {"wallet_address": "B", "independence_confirmed": True, "cluster_id": "same"},
    ])
    report = evaluate_selective_pool(evidence, independence)
    assert report["m76_independence_reused"]["passed"] is False
    assert report["micro_live_readiness"]["ready_for_explicit_authorization"] is False

def test_one_wallet_never_makes_pool_ready():
    evidence = sign_selective_evidence(
        {"A": _row("A")},
        anchor_utc="2026-08-31T12:30:50.267406+00:00",
    )
    independence = sign_independence_evidence([
        {"wallet_address": "A", "independence_confirmed": True, "cluster_id": "a"}
    ])
    report = evaluate_selective_pool(evidence, independence)
    assert report["micro_live_readiness"]["ready_for_explicit_authorization"] is False

def test_evidence_hash_fail_closed():
    payload = sign_selective_evidence(
        {"A": _row("A")},
        anchor_utc="2026-08-31T12:30:50.267406+00:00",
    )
    payload["wallet_evidence"]["A"]["profit_factor"] = 99.0
    with pytest.raises(SelectiveReadinessError):
        validate_selective_evidence(payload)
