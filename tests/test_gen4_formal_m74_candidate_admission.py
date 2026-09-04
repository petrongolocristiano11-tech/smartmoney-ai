from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.services.gen4_formal_m74_candidate_admission_service import (
    FORMAL_M74_ADMITTED_WALLETS,
    R7_FORMAL_REPORT_SHA256,
    build_formal_m74_admission_report,
    formal_m74_admission_for_wallet,
    validate_formal_m74_admission_registry,
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
