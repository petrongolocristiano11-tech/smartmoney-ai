from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.services.gen4_selective_micro_live_readiness_service import (
    SELECTIVE_READINESS_ARMED,
    SELECTIVE_READINESS_SCOPE,
    SELECTIVE_READINESS_VERSION,
    SelectiveReadinessError,
    build_preparation_report,
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

def evidence(wallet: str, **overrides):
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
        "accepted_p95_end_to_quote_ms": 1800.0,
        "accepted_p95_price_deterioration_bps": 600.0,
        "accepted_p95_price_impact_bps": 20.0,
        "accepted_policy_violations": 0,
        "exit_policy_violations": 0,
        "exit_failures": 0,
        "open_positions": 0,
        "unresolved_failures": 0,
        "net_pnl_sol": 0.05,
        "profit_factor": 2.0,
        "maximum_drawdown_percent": 8.0,
    }
    row.update(overrides)
    return row

def main():
    assert SELECTIVE_READINESS_ARMED is False
    assert SELECTIVE_READINESS_SCOPE == "M298_SELECTIVE_FOLLOWER_MICRO_LIVE_READINESS_DISARMED"
    assert SELECTIVE_READINESS_VERSION == "canonical-parser-gen4-selective-micro-live-readiness/1"
    p = validate_policy()
    legacy = validate_legacy_policy()
    assert p["minimum_entry_attempts"] == legacy["canary_minimum_entry_attempts"] == 20
    assert p["minimum_closed_trades"] == legacy["canary_minimum_closed_trades"] == 10
    assert p["minimum_webhook_coverage_percent"] == 95.0
    assert p["minimum_accepted_unsigned_build_coverage_percent"] == 100.0
    assert p["maximum_accepted_p95_end_to_quote_ms"] == 5000.0
    assert p["maximum_accepted_p95_price_deterioration_bps"] == 1000.0
    assert p["maximum_accepted_p95_price_impact_bps"] == 500.0
    assert p["minimum_profit_factor"] == legacy["minimum_profit_factor"] == 1.30
    assert p["maximum_drawdown_percent"] == legacy["maximum_drawdown_percent"] == 15.0
    assert p["protective_reject_rate_hard_gate"] is False
    assert legacy["canary_maximum_entry_reject_rate_percent"] == 20.0

    w1 = "WALLET_A"
    result = evaluate_selective_wallet(
        w1, evidence(w1),
        source_m74_audit={"passed": False, "failed_checks": ["drawdown"]},
    )
    assert result["passed"] is True
    assert result["metrics"]["protective_reject_rate_percent"] == 50.0
    assert result["source_m74_audit"]["passed"] is False
    assert result["source_m74_audit"]["used_as_selective_admission_gate"] is False
    assert result["legacy_claims"]["formal_m74_pass_claimed"] is False
    assert result["legacy_claims"]["formal_m75_pass_claimed"] is False

    bad = evaluate_selective_wallet(
        w1, evidence(w1, accepted_attempts=9, protective_rejects=10,
                     technical_failures=1, closed_trades=9),
    )
    assert bad["passed"] is False
    assert bad["checks"]["zero_technical_failures"] is False

    bad_pf = evaluate_selective_wallet(w1, evidence(w1, profit_factor=1.29))
    assert bad_pf["passed"] is False

    anchor = "2026-08-31T12:30:50.267406+00:00"
    signed = sign_selective_evidence(
        {
            "WALLET_A": evidence("WALLET_A"),
            "WALLET_B": evidence("WALLET_B", protective_rejects=12, accepted_attempts=8, closed_trades=8),
            "WALLET_C": evidence("WALLET_C"),
        },
        anchor_utc=anchor,
        lineage={"m297_report_sha256": "0" * 64},
    )
    validate_selective_evidence(signed)
    indep = sign_independence_evidence([
        {"wallet_address": "WALLET_A", "independence_confirmed": True, "cluster_id": "A"},
        {"wallet_address": "WALLET_C", "independence_confirmed": True, "cluster_id": "C"},
    ])
    pool = evaluate_selective_pool(
        signed, indep,
        source_m74_audits={
            "WALLET_A": {"passed": False, "failed_checks": ["drawdown"]},
            "WALLET_C": {"passed": True, "failed_checks": []},
        },
    )
    assert set(pool["selective_pass_wallets"]) == {"WALLET_A", "WALLET_C"}
    assert pool["m76_independence_reused"]["passed"] is True
    assert pool["micro_live_readiness"]["ready_for_explicit_authorization"] is True
    assert pool["micro_live_readiness"]["micro_live_execution_authorized"] is False
    assert pool["m77_micro_live_envelope"]["execution_authorized"] is False
    validate_report(pool)

    collision = sign_independence_evidence([
        {"wallet_address": "WALLET_A", "independence_confirmed": True, "cluster_id": "SAME"},
        {"wallet_address": "WALLET_C", "independence_confirmed": True, "cluster_id": "SAME"},
    ])
    pool2 = evaluate_selective_pool(signed, collision)
    assert pool2["micro_live_readiness"]["ready_for_explicit_authorization"] is False

    tampered = dict(signed)
    tampered["wallet_evidence"] = dict(tampered["wallet_evidence"])
    tampered["wallet_evidence"]["WALLET_A"] = dict(tampered["wallet_evidence"]["WALLET_A"])
    tampered["wallet_evidence"]["WALLET_A"]["profit_factor"] = 99
    try:
        validate_selective_evidence(tampered)
    except SelectiveReadinessError:
        pass
    else:
        raise AssertionError("Tampered selective evidence accepted")

    prep = build_preparation_report(
        m297_anchor_utc=anchor,
        m297_report_sha256="0" * 64,
        prepared_at=datetime(2026, 8, 31, 12, 31, tzinfo=timezone.utc),
    )
    assert prep["state"] == "IMPLEMENTED_DISARMED_AWAITING_M297_POST_ANCHOR_EVIDENCE"
    assert prep["wallet_gate"]["protective_reject_rate_hard_gate"] is False
    assert prep["legacy_boundary"]["m74_thresholds_changed"] is False
    assert prep["legacy_boundary"]["m75_thresholds_changed"] is False
    assert prep["m77_micro_live_envelope"]["execution_authorized"] is False
    validate_report(prep)

    print("M298_PRE_VERIFY=PASS;"
          "disarmed=true;"
          "m74_unchanged=true;"
          "m75_unchanged=true;"
          "protective_reject_not_hard_gate=true;"
          "absolute_throughput_required=true;"
          "follower_pf_floor=1.30;"
          "follower_dd_cap=15;"
          "technical_failures_fail_closed=true;"
          "m76_independence_reused=true;"
          "explicit_authorization_only=true")

if __name__ == "__main__":
    main()
