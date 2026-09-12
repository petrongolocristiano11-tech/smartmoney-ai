from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.services.gen4_formal_m74_candidate_admission_service import (
    FORMAL_M74_ADMITTED_WALLETS,
    PENDING_FLAT_M74_ADMITTED_WALLETS,
    PENDING_FLAT_M74_ROOT_CAUSE_REPORT_SHA256,
    PENDING_FLAT_M74_TARGETED_REPORT_SHA256,
    PENDING_FLAT_M74_R8_MAXYIELD_REPORT_SHA256,
    PENDING_FLAT_M74_R4_CURRENT_ROOT_CAUSE_REPORT_SHA256,
    PENDING_FLAT_M74_R2_ADMISSION_READINESS_REPORT_SHA256,
    PENDING_FLAT_M74_LEGACY_ADMISSION_KIND,
    PENDING_FLAT_M74_R8_ADMISSION_KIND,
    R7_FIX1_SCRIPT_SHA256,
    R7_FORMAL_REPORT_SHA256,
    R9_MAXYIELD_FORMAL_REPORT_SHA256,
    R9_FORMAL3_ADMISSION_READINESS_REPORT_SHA256,
    R9_FORMAL_M74_ADMISSION_KIND,
    R10_FORMAL_M74_ADMISSION_KIND,
    R10_MAXYIELD_FORMAL_REPORT_SHA256,
    R10_FORMAL_M74_WALLETS,
    R12_FORMAL_M74_ADMISSION_KIND,
    R12_FORMAL_M74_WALLETS,
    R12_FULL31_REPORT_SHA256,
    R12_PENDING_FLAT_M74_ADMISSION_KIND,
    R12_PENDING_FLAT_M74_WALLETS,
    R12_STATE_SHA256,
    R13_FORMAL_M74_ADMISSION_KIND,
    R13_FORMAL_M74_WALLETS,
    R13_INDEPENDENCE_AUDIT_SHA256,
    R13_REPORT_SHA256,
    R14_DIVERSIFICATION_AUDIT_SHA256,
    R14_FORMAL_M74_ADMISSION_KIND,
    R14_FORMAL_M74_WALLETS,
    R14_REPORT_SHA256,
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
    assert set(FORMAL_M74_ADMITTED_WALLETS) == {"5PA", "3UdE", "EdNc", "GmRK", "3eN9mk", "5949hD", "2Ec754", "HZuErb", "Ayjjfu", "9Epapg", "E9zj6T", "BQ9YY6", "9VhXEPw3", "BQAf3pQz", "yX3wv1tk", "HNULoxt5", "CU4L8"}
    assert len(registry) == 17
    for label in ("3UdE", "EdNc", "GmRK"):
        r9_wallet = FORMAL_M74_ADMITTED_WALLETS[label]
        evidence = registry[r9_wallet]
        assert TARGETS[label] == r9_wallet
        assert evidence["admission_kind"] == R9_FORMAL_M74_ADMISSION_KIND
        assert evidence["formal_m74_pass"] is True
        assert evidence["formal_m74_status"] == "PASS"
        assert evidence["formal_failure_reasons"] == []
        assert evidence["history_complete"] is True
        assert evidence["open_positions"] == 0
        assert evidence["r9_maxyield_report_sha256"] == R9_MAXYIELD_FORMAL_REPORT_SHA256
        assert evidence["r9_admission_readiness_report_sha256"] == R9_FORMAL3_ADMISSION_READINESS_REPORT_SHA256
        assert evidence["candidate_forward_proof_backfilled"] is False

    pending = validate_pending_flat_m74_admission_registry()
    assert len(pending) == 7
    for label, pending_wallet in PENDING_FLAT_M74_ADMITTED_WALLETS.items():
        evidence = pending[pending_wallet]
        assert TARGETS[label] == pending_wallet
        assert evidence["formal_m74_pass"] is False
        assert evidence["formal_failure_reasons"] == ["zero_open_positions"]
        assert evidence["all_non_flatness_m74_checks_passed"] is True
        assert evidence["historical_open_positions_quarantined"] is True
        if label in R12_PENDING_FLAT_M74_WALLETS:
            assert evidence["admission_kind"] == R12_PENDING_FLAT_M74_ADMISSION_KIND
            assert evidence["r12_state_sha256"] == R12_STATE_SHA256
            assert evidence["r12_full31_report_sha256"] == R12_FULL31_REPORT_SHA256
            assert evidence["open_positions"] in {1, 2}
        elif label in {"3N7", "2MQR"}:
            assert evidence["admission_kind"] == PENDING_FLAT_M74_LEGACY_ADMISSION_KIND
            assert evidence["targeted_report_sha256"] == PENDING_FLAT_M74_TARGETED_REPORT_SHA256
            assert evidence["root_cause_report_sha256"] == PENDING_FLAT_M74_ROOT_CAUSE_REPORT_SHA256
            assert evidence["admission_readiness_report_sha256"] is None
        else:
            assert evidence["admission_kind"] == PENDING_FLAT_M74_R8_ADMISSION_KIND
            assert evidence["targeted_report_sha256"] == PENDING_FLAT_M74_R8_MAXYIELD_REPORT_SHA256
            assert evidence["root_cause_report_sha256"] == PENDING_FLAT_M74_R4_CURRENT_ROOT_CAUSE_REPORT_SHA256
            assert evidence["admission_readiness_report_sha256"] == PENDING_FLAT_M74_R2_ADMISSION_READINESS_REPORT_SHA256

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

    for label in ("3UdE", "EdNc", "GmRK"):
        r9_wallet = FORMAL_M74_ADMITTED_WALLETS[label]
        r9_rows = [
            event(r9_wallet, f"{label}-{i}", anchor + timedelta(minutes=i + 1), i < 10)
            for i in range(20)
        ]
        r9_decision = evaluate_candidate_promotion(
            wallet=r9_wallet,
            events=r9_rows,
            anchor_utc=anchor,
            terminal_at=anchor + timedelta(hours=2),
        )
        assert r9_decision["promotion_eligible"] is True
        assert r9_decision["target_admission"]["kind"] == R9_FORMAL_M74_ADMISSION_KIND
        assert r9_decision["target_admission"]["upstream_formal_m74_pass"] is True
        assert r9_decision["target_admission"]["upstream_formal_m74_report_sha256"] == R9_MAXYIELD_FORMAL_REPORT_SHA256
        assert r9_decision["target_admission"]["upstream_admission_readiness_report_sha256"] == R9_FORMAL3_ADMISSION_READINESS_REPORT_SHA256
        assert r9_decision["target_admission"]["candidate_entry_evidence_backfilled"] is False
        validate_m300_decision(r9_decision)

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

    for label, r10_wallet in R10_FORMAL_M74_WALLETS.items():
        assert TARGETS[label] == r10_wallet
        fresh = [event(r10_wallet, f"r10-{label}-{i}", anchor + timedelta(minutes=i + 1), i < 10) for i in range(20)]
        for sample, eligible in (([], False), (fresh[:19], False), (fresh, True)):
            decision = evaluate_candidate_promotion(wallet=r10_wallet, events=sample, anchor_utc=anchor, terminal_at=anchor + timedelta(hours=2))
            assert decision["promotion_eligible"] is eligible
            assert decision["target_admission"]["kind"] == R10_FORMAL_M74_ADMISSION_KIND
            assert decision["target_admission"]["upstream_formal_m74_report_sha256"] == R10_MAXYIELD_FORMAL_REPORT_SHA256
            assert decision["target_admission"]["upstream_admission_readiness_report_sha256"] is None
            assert decision["target_admission"]["candidate_entry_evidence_backfilled"] is False
            assert decision["formal_claims"]["m298_pass_claimed"] is False

    for label, r12_wallet in R12_FORMAL_M74_WALLETS.items():
        assert TARGETS[label] == r12_wallet
        fresh = [event(r12_wallet, f"r12-{label}-{i}", anchor + timedelta(minutes=i + 1), i < 10) for i in range(20)]
        for sample, eligible in (([], False), (fresh[:19], False), (fresh, True)):
            decision = evaluate_candidate_promotion(wallet=r12_wallet, events=sample, anchor_utc=anchor, terminal_at=anchor + timedelta(hours=2))
            assert decision["promotion_eligible"] is eligible
            assert decision["target_admission"]["kind"] == R12_FORMAL_M74_ADMISSION_KIND
            assert decision["target_admission"]["upstream_formal_m74_report_sha256"] == R12_STATE_SHA256
            assert decision["target_admission"]["upstream_admission_readiness_report_sha256"] == R12_FULL31_REPORT_SHA256
            assert decision["target_admission"]["candidate_entry_evidence_backfilled"] is False
            assert decision["formal_claims"]["m298_pass_claimed"] is False

    for label, r13_wallet in R13_FORMAL_M74_WALLETS.items():
        assert TARGETS[label] == r13_wallet
        evidence = registry[r13_wallet]
        assert evidence["formal_m74_pass"] is True
        assert evidence["formal_m74_status"] == "PASS"
        assert evidence["open_positions"] == 0
        assert evidence["r13_report_sha256"] == R13_REPORT_SHA256
        assert evidence["r13_independence_audit_sha256"] == R13_INDEPENDENCE_AUDIT_SHA256
        assert evidence["r13_independence_classification"] == "INDEPENDENCE_CANDIDATE"
        fresh = [event(r13_wallet, f"r13-{label}-{i}", anchor + timedelta(minutes=i + 1), i < 10) for i in range(20)]
        for sample, eligible in (([], False), (fresh[:19], False), (fresh, True)):
            decision = evaluate_candidate_promotion(wallet=r13_wallet, events=sample, anchor_utc=anchor, terminal_at=anchor + timedelta(hours=2))
            assert decision["promotion_eligible"] is eligible
            assert decision["target_admission"]["kind"] == R13_FORMAL_M74_ADMISSION_KIND
            assert decision["target_admission"]["upstream_formal_m74_report_sha256"] == R13_REPORT_SHA256
            assert decision["target_admission"]["upstream_admission_readiness_report_sha256"] == R13_INDEPENDENCE_AUDIT_SHA256
            assert decision["target_admission"]["candidate_entry_evidence_backfilled"] is False
            assert decision["formal_claims"]["m298_pass_claimed"] is False


    for label, r14_wallet in R14_FORMAL_M74_WALLETS.items():
        assert TARGETS[label] == r14_wallet
        evidence = registry[r14_wallet]
        assert evidence["formal_m74_pass"] is True
        assert evidence["formal_m74_status"] == "PASS"
        assert evidence["formal_failure_reasons"] == []
        assert evidence["history_complete"] is True
        assert evidence["open_positions"] == 0
        assert evidence["r14_report_sha256"] == R14_REPORT_SHA256
        assert evidence["r14_diversification_audit_sha256"] == R14_DIVERSIFICATION_AUDIT_SHA256
        assert evidence["r14_diversification_classification"] == "SLOT20_DIVERSIFICATION_CANDIDATE"
        fresh = [event(r14_wallet, f"r14-{label}-{i}", anchor + timedelta(minutes=i + 1), i < 10) for i in range(20)]
        for sample, eligible in (([], False), (fresh[:19], False), (fresh, True)):
            decision = evaluate_candidate_promotion(wallet=r14_wallet, events=sample, anchor_utc=anchor, terminal_at=anchor + timedelta(hours=2))
            assert decision["promotion_eligible"] is eligible
            assert decision["target_admission"]["kind"] == R14_FORMAL_M74_ADMISSION_KIND
            assert decision["target_admission"]["upstream_formal_m74_report_sha256"] == R14_REPORT_SHA256
            assert decision["target_admission"]["upstream_admission_readiness_report_sha256"] == R14_DIVERSIFICATION_AUDIT_SHA256
            assert decision["target_admission"]["candidate_entry_evidence_backfilled"] is False
            assert decision["formal_claims"]["m298_pass_claimed"] is False

    print(
        "FORMAL_M74_CANDIDATE_ADMISSION_VERIFY=PASS;"
        f"wallet={wallet};formal_m74_report_sha={R7_FORMAL_REPORT_SHA256};"
        "m300_target=yes;new_candidate_attempt_floor=20;new_accepted_floor=10;"
        "historical_backfill=no;legacy_gen4_pass_invented=no;"
        "formal_registry_count=17;pending_flat_count=7;r10_selected=3eN9mk|5949hD|2Ec754|HZuErb;r12_formal_selected=Ayjjfu|9Epapg|E9zj6T|BQ9YY6;r12_pending_selected=2SJVK1|EUukvc;r13_independent_selected=9VhXEPw3|BQAf3pQz|yX3wv1tk|HNULoxt5;r14_diversified_selected=CU4L8;historical_positions=quarantined;"
        "watchlist_mutation=manual_future_step;provider_mutation=no;"
        "m75_changed=no;m298_changed=no;pam_changed=no;live=no"
    )


if __name__ == "__main__":
    main()
