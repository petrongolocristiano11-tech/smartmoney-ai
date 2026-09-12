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
    formal_m74_admission_for_wallet,
    pending_flat_m74_admission_for_wallet,
    validate_formal_m74_admission_registry,
    validate_pending_flat_m74_admission_registry,
)
from backend.app.services.gen4_selective_challenger_lifecycle_bridge_design_service import (
    validate_m300_decision,
)
from backend.app.services.gen4_selective_challenger_promotion_service import (
    TARGETS,
    evaluate_candidate_promotion,
    target_admission_provenance,
)


def _event(wallet: str, signature: str, when: datetime, accepted: bool) -> dict:
    row = {
        "wallet_address": wallet,
        "side": "BUY",
        "signature": signature,
        "fast_received_at": when,
        "fast_quote_received_at": when + timedelta(milliseconds=600) if accepted else None,
        "fast_prequote_ms": 20 if accepted else None,
        "fast_quote_latency_ms": 580 if accepted else None,
        "fast_end_to_quote_ms": 600 if accepted else None,
        "fast_price_impact_bps": 25.0 if accepted else None,
        "fast_price_deterioration_bps": 250.0 if accepted else None,
        "fast_transaction_built": accepted,
        "fast_provisional_copyable": accepted,
        "fast_provisional_rejection_reason": None if accepted else "PRICE_ALREADY_MOVED",
        "parse_error_code": None,
        "quote_error_code": None,
    }
    return row


def test_formal_m74_registry_is_exact_disarmed_and_does_not_claim_downstream_passes():
    registry = validate_formal_m74_admission_registry()
    wallet = FORMAL_M74_ADMITTED_WALLETS["5PA"]
    evidence = registry[wallet]
    assert evidence["formal_m74_pass"] is True
    assert evidence["r7_formal_report_sha256"] == R7_FORMAL_REPORT_SHA256
    assert evidence["closed_trade_count"] == 524
    assert evidence["open_positions"] == 0
    assert evidence["candidate_forward_proof_backfilled"] is False
    assert evidence["gen4_copyability_pass_claimed"] is False
    assert evidence["m75_pass_claimed"] is False
    assert evidence["m298_pass_claimed"] is False
    assert set(FORMAL_M74_ADMITTED_WALLETS) == {"5PA", "3UdE", "EdNc", "GmRK", "3eN9mk", "5949hD", "2Ec754", "HZuErb", "Ayjjfu", "9Epapg", "E9zj6T", "BQ9YY6", "9VhXEPw3", "BQAf3pQz", "yX3wv1tk", "HNULoxt5", "CU4L8"}
    assert len(registry) == 17
    for label in ("3UdE", "EdNc", "GmRK"):
        r9_wallet = FORMAL_M74_ADMITTED_WALLETS[label]
        r9_evidence = registry[r9_wallet]
        assert r9_evidence["admission_kind"] == R9_FORMAL_M74_ADMISSION_KIND
        assert r9_evidence["formal_m74_pass"] is True
        assert r9_evidence["formal_m74_status"] == "PASS"
        assert r9_evidence["formal_failure_reasons"] == []
        assert r9_evidence["history_complete"] is True
        assert r9_evidence["open_positions"] == 0
        assert r9_evidence["r9_maxyield_report_sha256"] == R9_MAXYIELD_FORMAL_REPORT_SHA256
        assert r9_evidence["r9_admission_readiness_report_sha256"] == R9_FORMAL3_ADMISSION_READINESS_REPORT_SHA256
        assert r9_evidence["candidate_forward_proof_backfilled"] is False
        assert r9_evidence["gen4_copyability_pass_claimed"] is False
        assert r9_evidence["m75_pass_claimed"] is False
        assert r9_evidence["m298_pass_claimed"] is False
    report = build_formal_m74_admission_report()
    assert report["evaluation"] == "PASS"
    assert report["armed"] is False
    assert report["next_boundary"]["explicit_candidate_watchlist_mutation_required"] is True
    assert report["safety"]["railway_variable_set"] is False
    assert report["safety"]["provider_mutations"] == 0
    assert report["safety"]["live"] is False


def test_5pa_is_an_m300_target_only_through_formal_m74_admission_provenance():
    wallet = FORMAL_M74_ADMITTED_WALLETS["5PA"]
    assert TARGETS["5PA"] == wallet
    admission = target_admission_provenance(wallet)
    assert admission["kind"] == "R7_FORMAL_M74_PASS_ADMISSION"
    assert admission["upstream_formal_m74_pass"] is True
    assert admission["upstream_formal_m74_report_sha256"] == R7_FORMAL_REPORT_SHA256
    assert admission["candidate_entry_evidence_backfilled"] is False
    assert formal_m74_admission_for_wallet("unknown") is None


def test_r9_formal_m74_wallets_are_m300_targets_with_distinct_r9_provenance():
    for label in ("3UdE", "EdNc", "GmRK"):
        wallet = FORMAL_M74_ADMITTED_WALLETS[label]
        assert TARGETS[label] == wallet
        admission = target_admission_provenance(wallet)
        assert admission["kind"] == R9_FORMAL_M74_ADMISSION_KIND
        assert admission["upstream_formal_m74_pass"] is True
        assert admission["upstream_economic_m74_qualification"] is True
        assert admission["upstream_formal_m74_report_sha256"] == R9_MAXYIELD_FORMAL_REPORT_SHA256
        assert admission["upstream_admission_readiness_report_sha256"] == R9_FORMAL3_ADMISSION_READINESS_REPORT_SHA256
        assert admission["historical_open_positions_quarantined"] is False
        assert admission["candidate_entry_evidence_backfilled"] is False


def test_r9_formal_m74_wallets_still_require_fresh_twenty_attempts_and_ten_accepted():
    anchor = datetime(2026, 9, 7, 14, 30, 0, tzinfo=timezone.utc)
    for label in ("3UdE", "EdNc", "GmRK"):
        wallet = FORMAL_M74_ADMITTED_WALLETS[label]
        rows = [
            _event(
                wallet,
                f"{label}-{i}",
                anchor + timedelta(minutes=i + 1),
                accepted=i < 10,
            )
            for i in range(20)
        ]
        result = evaluate_candidate_promotion(
            wallet=wallet,
            events=rows,
            anchor_utc=anchor,
            terminal_at=anchor + timedelta(hours=2),
        )
        assert result["promotion_eligible"] is True
        assert result["clean_window"]["attempts"] == 20
        assert result["clean_window"]["accepted"] == 10
        assert result["target_admission"]["kind"] == R9_FORMAL_M74_ADMISSION_KIND
        assert result["future_selective_lifecycle_bridge"]["candidate_fastpath_entry_evidence_backfilled"] is False
        assert result["formal_claims"]["m74_pass_claimed"] is False
        assert result["formal_claims"]["m298_pass_claimed"] is False
        assert validate_m300_decision(result)["wallet"] == wallet


def test_5pa_m300_still_requires_new_twenty_attempts_and_ten_accepted():
    wallet = FORMAL_M74_ADMITTED_WALLETS["5PA"]
    anchor = datetime(2026, 9, 4, 17, 0, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(20):
        rows.append(
            _event(
                wallet,
                f"5PA-{i}",
                anchor + timedelta(minutes=i + 1),
                accepted=i < 10,
            )
        )
    result = evaluate_candidate_promotion(
        wallet=wallet,
        events=rows,
        anchor_utc=anchor,
        terminal_at=anchor + timedelta(hours=2),
    )
    assert result["promotion_eligible"] is True
    assert result["clean_window"]["attempts"] == 20
    assert result["clean_window"]["accepted"] == 10
    assert result["target_admission"]["upstream_formal_m74_pass"] is True
    assert result["future_selective_lifecycle_bridge"]["candidate_fastpath_entry_evidence_backfilled"] is False
    assert result["formal_claims"]["m74_pass_claimed"] is False
    assert result["formal_claims"]["m298_pass_claimed"] is False
    # M301 accepts the M300 decision without inventing a legacy Gen4 PASS.
    assert validate_m300_decision(result)["wallet"] == wallet


def test_5pa_historical_m74_pass_cannot_substitute_for_missing_new_candidate_attempts():
    wallet = FORMAL_M74_ADMITTED_WALLETS["5PA"]
    anchor = datetime(2026, 9, 4, 17, 0, 0, tzinfo=timezone.utc)
    result = evaluate_candidate_promotion(
        wallet=wallet,
        events=[],
        anchor_utc=anchor,
        terminal_at=anchor + timedelta(hours=2),
    )
    assert result["promotion_eligible"] is False
    assert result["checks"]["minimum_clean_entry_attempts"] is False
    assert result["checks"]["minimum_clean_accepted_attempts"] is False



def test_pending_flat_registry_is_exact_and_never_claims_formal_m74_pass():
    registry = validate_pending_flat_m74_admission_registry()
    assert set(PENDING_FLAT_M74_ADMITTED_WALLETS) == {"3N7", "2MQR", "9rDM", "D9gQ", "37uM", "2SJVK1", "EUukvc"}
    assert len(registry) == 7
    for label, wallet in PENDING_FLAT_M74_ADMITTED_WALLETS.items():
        evidence = registry[wallet]
        assert evidence["qualification_state"] == "QUALIFIED_PENDING_FLAT"
        assert evidence["formal_m74_pass"] is False
        assert evidence["formal_m74_status"] == "FAIL_COMPLETE_HISTORY"
        assert evidence["formal_failure_reasons"] == ["zero_open_positions"]
        assert evidence["history_complete"] is True
        assert evidence["all_non_flatness_m74_checks_passed"] is True
        assert evidence["flatness_only_blocker"] is True
        assert evidence["open_positions"] > 0
        if label in R12_PENDING_FLAT_M74_WALLETS:
            assert evidence["admission_kind"] == R12_PENDING_FLAT_M74_ADMISSION_KIND
            assert evidence["r12_state_sha256"] == R12_STATE_SHA256
            assert evidence["r12_full31_report_sha256"] == R12_FULL31_REPORT_SHA256
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
        assert evidence["parser_gap_positions"] == 0
        assert evidence["position_turnover"] is False
        assert evidence["historical_open_positions_quarantined"] is True
        assert evidence["historical_open_positions_followed_by_candidate_lane"] is False
        assert evidence["candidate_forward_proof_backfilled"] is False
        assert evidence["m298_pass_claimed"] is False
        assert pending_flat_m74_admission_for_wallet(wallet) == evidence


def test_pending_flat_wallets_are_m300_targets_with_fresh_evidence_only():
    anchor = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)
    registry = validate_pending_flat_m74_admission_registry()
    for label, wallet in PENDING_FLAT_M74_ADMITTED_WALLETS.items():
        assert TARGETS[label] == wallet
        evidence = registry[wallet]
        provenance = target_admission_provenance(wallet)
        assert provenance["kind"] == evidence["admission_kind"]
        assert provenance["upstream_formal_m74_pass"] is False
        assert provenance["upstream_economic_m74_qualification"] is True
        assert provenance["upstream_flatness_only_blocker"] is True
        assert provenance["upstream_formal_failure_reasons"] == ["zero_open_positions"]
        assert provenance["historical_open_positions_quarantined"] is True
        assert provenance["historical_open_positions_followed_by_candidate_lane"] is False
        assert provenance["candidate_entry_evidence_backfilled"] is False

        empty = evaluate_candidate_promotion(
            wallet=wallet,
            events=[],
            anchor_utc=anchor,
            terminal_at=anchor + timedelta(hours=1),
        )
        assert empty["promotion_eligible"] is False
        assert empty["checks"]["minimum_clean_entry_attempts"] is False

        rows = [
            _event(
                wallet,
                f"{label}-{i}",
                anchor + timedelta(minutes=i + 1),
                accepted=i < 10,
            )
            for i in range(20)
        ]
        out = evaluate_candidate_promotion(
            wallet=wallet,
            events=rows,
            anchor_utc=anchor,
            terminal_at=anchor + timedelta(hours=2),
        )
        assert out["promotion_eligible"] is True
        assert out["clean_window"]["attempts"] == 20
        assert out["clean_window"]["accepted"] == 10
        assert out["formal_claims"]["m74_pass_claimed"] is False
        assert out["formal_claims"]["m298_pass_claimed"] is False
        assert out["future_selective_lifecycle_bridge"]["candidate_fastpath_entry_evidence_backfilled"] is False
        assert out["future_selective_lifecycle_bridge"]["historical_pre_anchor_positions_carried_forward"] is False
        assert out["future_selective_lifecycle_bridge"]["pending_flat_historical_positions_quarantined"] is True
        assert validate_m300_decision(out)["wallet"] == wallet


def test_r12_selected_formal_wallets_use_exact_snapshot_provenance_and_fresh_m300():
    anchor = datetime(2026, 9, 10, 16, 0, tzinfo=timezone.utc)
    registry = validate_formal_m74_admission_registry()
    for label, wallet in R12_FORMAL_M74_WALLETS.items():
        assert TARGETS[label] == wallet
        evidence = registry[wallet]
        assert evidence["formal_m74_pass"] is True
        assert evidence["history_complete"] is True
        assert evidence["open_positions"] == 0
        assert evidence["r12_state_sha256"] == R12_STATE_SHA256
        assert evidence["r12_full31_report_sha256"] == R12_FULL31_REPORT_SHA256
        rows = [_event(wallet, f"r12-{label}-{i}", anchor + timedelta(minutes=i + 1), accepted=i < 10) for i in range(20)]
        result = evaluate_candidate_promotion(
            wallet=wallet,
            events=rows,
            anchor_utc=anchor,
            terminal_at=anchor + timedelta(hours=2),
        )
        assert result["promotion_eligible"] is True
        assert result["target_admission"]["kind"] == R12_FORMAL_M74_ADMISSION_KIND
        assert result["target_admission"]["upstream_formal_m74_report_sha256"] == R12_STATE_SHA256
        assert result["target_admission"]["upstream_admission_readiness_report_sha256"] == R12_FULL31_REPORT_SHA256
        assert result["target_admission"]["candidate_entry_evidence_backfilled"] is False
        assert result["formal_claims"]["m298_pass_claimed"] is False


def test_r12_selected_pending_wallets_remain_flatness_only_and_quarantined():
    registry = validate_pending_flat_m74_admission_registry()
    expected_open = {"2SJVK1": 1, "EUukvc": 2}
    for label, wallet in R12_PENDING_FLAT_M74_WALLETS.items():
        evidence = registry[wallet]
        assert evidence["formal_m74_pass"] is False
        assert evidence["formal_failure_reasons"] == ["zero_open_positions"]
        assert evidence["open_positions"] == expected_open[label]
        assert evidence["r12_state_sha256"] == R12_STATE_SHA256
        assert evidence["r12_full31_report_sha256"] == R12_FULL31_REPORT_SHA256
        provenance = target_admission_provenance(wallet)
        assert provenance["kind"] == R12_PENDING_FLAT_M74_ADMISSION_KIND
        assert provenance["upstream_formal_m74_pass"] is False
        assert provenance["upstream_flatness_only_blocker"] is True
        assert provenance["historical_open_positions_quarantined"] is True
        assert provenance["candidate_entry_evidence_backfilled"] is False


def test_r10_top3_provenance_and_fresh_sample_boundaries():
    anchor = datetime(2026, 9, 10, 15, 0, tzinfo=timezone.utc)
    for label, wallet in R10_FORMAL_M74_WALLETS.items():
        assert TARGETS[label] == wallet
        fresh = [_event(wallet, f"{label}-{i}", anchor + timedelta(minutes=i + 1), accepted=i < 10) for i in range(20)]
        old = [_event(wallet, f"old-{label}-{i}", anchor - timedelta(minutes=i + 1), accepted=True) for i in range(20)]
        nine = [_event(wallet, f"nine-{label}-{i}", anchor + timedelta(minutes=i + 1), accepted=i < 9) for i in range(20)]
        for sample, eligible in (([], False), (old, False), (fresh[:19], False), (nine, False), (fresh, True)):
            result = evaluate_candidate_promotion(wallet=wallet, events=sample, anchor_utc=anchor, terminal_at=anchor + timedelta(hours=2))
            assert result["promotion_eligible"] is eligible
            admission = result["target_admission"]
            assert admission["kind"] == R10_FORMAL_M74_ADMISSION_KIND
            assert admission["upstream_formal_m74_report_sha256"] == R10_MAXYIELD_FORMAL_REPORT_SHA256
            assert admission["upstream_admission_readiness_report_sha256"] is None
            assert admission["candidate_entry_evidence_backfilled"] is False
            assert result["formal_claims"]["m298_pass_claimed"] is False
            if eligible:
                assert validate_m300_decision(result)["wallet"] == wallet

def test_r13_independent_formal_wallets_have_exact_frozen_provenance_and_fresh_m300():
    anchor = datetime(2026, 9, 11, 10, 30, tzinfo=timezone.utc)
    registry = validate_formal_m74_admission_registry()
    for label, wallet in R13_FORMAL_M74_WALLETS.items():
        assert TARGETS[label] == wallet
        evidence = registry[wallet]
        assert evidence["formal_m74_pass"] is True
        assert evidence["formal_m74_status"] == "PASS"
        assert evidence["open_positions"] == 0
        assert evidence["r13_report_sha256"] == R13_REPORT_SHA256
        assert evidence["r13_independence_audit_sha256"] == R13_INDEPENDENCE_AUDIT_SHA256
        assert evidence["r13_independence_classification"] == "INDEPENDENCE_CANDIDATE"
        fresh = [_event(wallet, f"r13-{label}-{i}", anchor + timedelta(minutes=i + 1), accepted=i < 10) for i in range(20)]
        result = evaluate_candidate_promotion(
            wallet=wallet,
            events=fresh,
            anchor_utc=anchor,
            terminal_at=anchor + timedelta(hours=2),
        )
        assert result["promotion_eligible"] is True
        admission = result["target_admission"]
        assert admission["kind"] == R13_FORMAL_M74_ADMISSION_KIND
        assert admission["upstream_formal_m74_report_sha256"] == R13_REPORT_SHA256
        assert admission["upstream_admission_readiness_report_sha256"] == R13_INDEPENDENCE_AUDIT_SHA256
        assert admission["candidate_entry_evidence_backfilled"] is False
        assert result["formal_claims"]["m298_pass_claimed"] is False

def test_r14_cu4l8_has_exact_frozen_provenance_diversification_and_fresh_m300():
    anchor = datetime(2026, 9, 12, 13, 0, tzinfo=timezone.utc)
    registry = validate_formal_m74_admission_registry()
    assert R14_FORMAL_M74_WALLETS == {"CU4L8": "CU4L8gvTNGVu6FGGaLQKbSKbia5adhhA6ERVTF1DNr4Y"}
    for label, wallet in R14_FORMAL_M74_WALLETS.items():
        assert TARGETS[label] == wallet
        evidence = registry[wallet]
        assert evidence["formal_m74_pass"] is True
        assert evidence["formal_m74_status"] == "PASS"
        assert evidence["formal_failure_reasons"] == []
        assert evidence["history_complete"] is True
        assert evidence["open_positions"] == 0
        assert evidence["r14_report_sha256"] == R14_REPORT_SHA256
        assert evidence["r14_diversification_audit_sha256"] == R14_DIVERSIFICATION_AUDIT_SHA256
        assert evidence["r14_diversification_classification"] == "SLOT20_DIVERSIFICATION_CANDIDATE"
        assert evidence["candidate_forward_proof_backfilled"] is False
        assert evidence["m75_pass_claimed"] is False
        assert evidence["m298_pass_claimed"] is False
        fresh = [_event(wallet, f"r14-{label}-{i}", anchor + timedelta(minutes=i + 1), accepted=i < 10) for i in range(20)]
        result = evaluate_candidate_promotion(
            wallet=wallet,
            events=fresh,
            anchor_utc=anchor,
            terminal_at=anchor + timedelta(hours=2),
        )
        assert result["promotion_eligible"] is True
        admission = result["target_admission"]
        assert admission["kind"] == R14_FORMAL_M74_ADMISSION_KIND
        assert admission["upstream_formal_m74_report_sha256"] == R14_REPORT_SHA256
        assert admission["upstream_admission_readiness_report_sha256"] == R14_DIVERSIFICATION_AUDIT_SHA256
        assert admission["candidate_entry_evidence_backfilled"] is False
        assert result["formal_claims"]["m74_pass_claimed"] is False
        assert result["formal_claims"]["m298_pass_claimed"] is False

