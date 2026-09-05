from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.services.gen4_formal_m74_candidate_admission_service import (
    FORMAL_M74_ADMITTED_WALLETS,
    PENDING_FLAT_M74_ADMITTED_WALLETS,
    PENDING_FLAT_M74_ROOT_CAUSE_REPORT_SHA256,
    PENDING_FLAT_M74_TARGETED_REPORT_SHA256,
    R7_FIX1_SCRIPT_SHA256,
    R7_FORMAL_REPORT_SHA256,
    build_formal_m74_admission_report,
    validate_formal_m74_admission_registry,
    validate_pending_flat_m74_admission_registry,
)
from backend.app.services.gen4_selective_challenger_lifecycle_bridge_design_service import (
    validate_m300_decision,
)
from backend.app.services.gen4_selective_challenger_promotion_service import (
    TARGETS,
    evaluate_candidate_promotion,
    validate_policy,
)


def event(wallet, sig, when, accepted=True):
    return {
        "wallet_address": wallet,
        "side": "BUY",
        "signature": sig,
        "fast_received_at": when,
        "fast_quote_received_at": when + timedelta(milliseconds=500) if accepted else None,
        "fast_prequote_ms": 20 if accepted else None,
        "fast_quote_latency_ms": 480 if accepted else None,
        "fast_end_to_quote_ms": 500 if accepted else None,
        "fast_price_impact_bps": 25.0 if accepted else None,
        "fast_price_deterioration_bps": 250.0 if accepted else None,
        "fast_transaction_built": accepted,
        "fast_provisional_copyable": accepted,
        "fast_provisional_rejection_reason": None if accepted else "PRICE_ALREADY_MOVED",
        "parse_error_code": None,
        "quote_error_code": None,
    }


def main():
    wallet = FORMAL_M74_ADMITTED_WALLETS["5PA"]
    registry = validate_formal_m74_admission_registry()
    assert TARGETS["5PA"] == wallet
    assert registry[wallet]["formal_m74_pass"] is True
    assert registry[wallet]["r7_formal_report_sha256"] == R7_FORMAL_REPORT_SHA256
    assert registry[wallet]["r7_fix1_script_sha256"] == R7_FIX1_SCRIPT_SHA256
    assert registry[wallet]["gen4_copyability_pass_claimed"] is False
    assert registry[wallet]["candidate_forward_proof_backfilled"] is False

    pending = validate_pending_flat_m74_admission_registry()
    assert len(pending) == 2
    for label, pending_wallet in PENDING_FLAT_M74_ADMITTED_WALLETS.items():
        evidence = pending[pending_wallet]
        assert TARGETS[label] == pending_wallet
        assert evidence["formal_m74_pass"] is False
        assert evidence["formal_failure_reasons"] == ["zero_open_positions"]
        assert evidence["all_non_flatness_m74_checks_passed"] is True
        assert evidence["historical_open_positions_quarantined"] is True
        assert evidence["targeted_report_sha256"] == PENDING_FLAT_M74_TARGETED_REPORT_SHA256
        assert evidence["root_cause_report_sha256"] == PENDING_FLAT_M74_ROOT_CAUSE_REPORT_SHA256

    policy = validate_policy()
    assert policy["minimum_clean_entry_attempts"] == 20
    assert policy["minimum_clean_accepted_attempts"] == 10

    anchor = datetime(2026, 9, 4, 17, 0, 0, tzinfo=timezone.utc)
    rows = [
        event(wallet, f"5PA-{i}", anchor + timedelta(minutes=i + 1), i < 10)
        for i in range(20)
    ]
    decision = evaluate_candidate_promotion(
        wallet=wallet,
        events=rows,
        anchor_utc=anchor,
        terminal_at=anchor + timedelta(hours=2),
    )
    assert decision["promotion_eligible"] is True
    assert decision["target_admission"]["kind"] == "R7_FORMAL_M74_PASS_ADMISSION"
    assert decision["clean_window"]["attempts"] == 20
    assert decision["clean_window"]["accepted"] == 10
    assert decision["formal_claims"]["m74_pass_claimed"] is False
    assert decision["formal_claims"]["gen4_copyability_pass_claimed"] is False
    assert decision["formal_claims"]["m298_pass_claimed"] is False
    validate_m300_decision(decision)

    empty = evaluate_candidate_promotion(
        wallet=wallet,
        events=[],
        anchor_utc=anchor,
        terminal_at=anchor + timedelta(hours=1),
    )
    assert empty["promotion_eligible"] is False

    report = build_formal_m74_admission_report()
    assert report["armed"] is False
    assert report["next_boundary"]["explicit_candidate_watchlist_mutation_required"] is True
    assert report["safety"]["railway_variable_set"] is False
    assert report["safety"]["provider_mutations"] == 0
    assert report["safety"]["live"] is False

    print(
        "FORMAL_M74_CANDIDATE_ADMISSION_VERIFY=PASS;"
        f"wallet={wallet};formal_m74_report_sha={R7_FORMAL_REPORT_SHA256};"
        "m300_target=yes;new_candidate_attempt_floor=20;new_accepted_floor=10;"
        "historical_backfill=no;legacy_gen4_pass_invented=no;"
        "pending_flat=3N7|2MQR;historical_positions=quarantined;"
        "watchlist_mutation=manual_future_step;provider_mutation=no;"
        "m75_changed=no;m298_changed=no;pam_changed=no;live=no"
    )


if __name__ == "__main__":
    main()
