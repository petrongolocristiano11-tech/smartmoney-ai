from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.app.services.gen4_formal_m74_candidate_admission_service import (
    FORMAL_M74_ADMITTED_WALLETS,
    PENDING_FLAT_M74_ADMITTED_WALLETS,
)

from backend.app.services.gen4_selective_challenger_promotion_service import (
    TARGETS,
    build_preparation_report,
    evaluate_candidate_promotion,
    validate_report,
)


def _event(wallet, sig, when, kind="ACCEPTED"):
    row = {
        "wallet_address": wallet,
        "side": "BUY",
        "signature": sig,
        "fast_received_at": when,
        "fast_quote_received_at": when + timedelta(milliseconds=700),
        "fast_end_to_quote_ms": 700,
        "fast_price_impact_bps": 20.0,
        "fast_price_deterioration_bps": 300.0,
        "fast_transaction_built": True,
        "fast_provisional_copyable": True,
        "fast_provisional_rejection_reason": None,
        "parse_error_code": None,
        "quote_error_code": None,
    }
    if kind == "PROTECTIVE":
        row.update(
            fast_transaction_built=False,
            fast_provisional_copyable=False,
            fast_provisional_rejection_reason="PRICE_ALREADY_MOVED",
            fast_quote_received_at=None,
            fast_end_to_quote_ms=None,
            fast_price_impact_bps=None,
            fast_price_deterioration_bps=None,
        )
    elif kind == "TECHNICAL":
        row.update(
            fast_transaction_built=False,
            fast_provisional_copyable=False,
            fast_provisional_rejection_reason="QUOTE_TOO_SLOW",
            fast_quote_received_at=None,
            fast_end_to_quote_ms=None,
            fast_price_impact_bps=None,
            fast_price_deterioration_bps=None,
        )
    return row


def _dataset(wallet, anchor, accepted=10, protective=10, prefix="S"):
    rows = []
    for i in range(accepted):
        rows.append(_event(wallet, f"{prefix}A{i}", anchor + timedelta(minutes=3 * (i + 1))))
    for i in range(protective):
        rows.append(_event(wallet, f"{prefix}P{i}", anchor + timedelta(minutes=3 * (accepted + i + 1)), "PROTECTIVE"))
    return rows


def test_high_protective_reject_rate_can_be_promotion_eligible():
    wallet = TARGETS["CGAZ"]
    anchor = datetime(2026, 8, 31, 12, 30, 50, tzinfo=timezone.utc)
    out = evaluate_candidate_promotion(
        wallet=wallet,
        events=_dataset(wallet, anchor),
        anchor_utc=anchor,
        terminal_at=anchor + timedelta(hours=2),
    )
    assert out["promotion_eligible"] is True
    assert out["clean_window"]["protective_rejects"] == 10
    assert out["protective_reject_policy"]["hard_rate_gate"] is False


def test_nine_accepted_is_not_enough_to_start_full_lifecycle_observation():
    wallet = TARGETS["89F3"]
    anchor = datetime(2026, 8, 31, 12, 30, 50, tzinfo=timezone.utc)
    out = evaluate_candidate_promotion(
        wallet=wallet,
        events=_dataset(wallet, anchor, accepted=9, protective=11),
        anchor_utc=anchor,
        terminal_at=anchor + timedelta(hours=2),
    )
    assert out["promotion_eligible"] is False
    assert out["checks"]["minimum_clean_accepted_attempts"] is False


def test_technical_failure_resets_clean_window():
    wallet = TARGETS["CGAZ"]
    anchor = datetime(2026, 8, 31, 12, 30, 50, tzinfo=timezone.utc)
    rows = _dataset(wallet, anchor, prefix="OLD")
    fail_at = anchor + timedelta(hours=3)
    rows.append(_event(wallet, "FAIL", fail_at, "TECHNICAL"))
    rows.extend(_dataset(wallet, fail_at, prefix="NEW"))
    out = evaluate_candidate_promotion(
        wallet=wallet,
        events=rows,
        anchor_utc=anchor,
        terminal_at=fail_at + timedelta(hours=2),
    )
    assert out["promotion_eligible"] is True
    assert out["clean_window"]["technical_reset_applied"] is True
    assert out["clean_window"]["attempts"] == 20
    assert out["clean_window"]["last_technical_failure_utc"] is not None


def test_candidate_runtime_latency_fallback_is_m291_canonical_and_not_a_weaker_gate():
    wallet = TARGETS["89F3"]
    anchor = datetime(2026, 8, 31, 12, 30, 50, tzinfo=timezone.utc)
    rows = _dataset(wallet, anchor)
    for row in rows:
        if row["fast_provisional_copyable"]:
            # Real candidate rows persist received/quote timestamps and quote latency,
            # but fast_end_to_quote_ms can remain NULL without webhook reconciliation.
            row["fast_end_to_quote_ms"] = None
            row["fast_prequote_ms"] = 20
            row["fast_quote_latency_ms"] = 680
    out = evaluate_candidate_promotion(
        wallet=wallet,
        events=rows,
        anchor_utc=anchor,
        terminal_at=anchor + timedelta(hours=2),
    )
    assert out["promotion_eligible"] is True
    assert out["checks"]["accepted_evidence_complete"] is True
    assert out["clean_window"]["p95_accepted_end_to_quote_ms"] == 700.0
    assert out["clean_window"]["accepted_end_to_quote_fallback_derived"] == 10
    assert (
        out["clean_window"]["accepted_end_to_quote_evidence_method"]
        == "M291_CANONICAL_FALLBACK_WITH_RECEIPT_NONE"
    )


def test_quality_p95_fails_closed():
    wallet = TARGETS["89F3"]
    anchor = datetime(2026, 8, 31, 12, 30, 50, tzinfo=timezone.utc)
    rows = _dataset(wallet, anchor)
    rows[0]["fast_end_to_quote_ms"] = 6000
    # With 10 accepted, nearest-rank p95 is the maximum.
    out = evaluate_candidate_promotion(
        wallet=wallet,
        events=rows,
        anchor_utc=anchor,
        terminal_at=anchor + timedelta(hours=2),
    )
    assert out["promotion_eligible"] is False
    assert out["checks"]["accepted_end_to_quote_p95"] is False
    assert out["clean_window"]["p95_accepted_end_to_quote_ms"] == 6000.0


def test_no_backfill_and_no_legacy_endpoint_claim():
    wallet = TARGETS["CGAZ"]
    anchor = datetime(2026, 8, 31, 12, 30, 50, tzinfo=timezone.utc)
    out = evaluate_candidate_promotion(
        wallet=wallet,
        events=_dataset(wallet, anchor),
        anchor_utc=anchor,
        terminal_at=anchor + timedelta(hours=2),
    )
    assert out["legacy_endpoint"]["compatible"] is False
    assert out["legacy_endpoint"]["gen4_copyability_pass_invented"] is False
    assert out["future_selective_lifecycle_bridge"]["candidate_fastpath_entry_evidence_backfilled"] is False
    assert out["future_selective_lifecycle_bridge"]["full_lifecycle_proof_starts_at_promotion_activation"] is True
    assert out["formal_claims"]["m298_pass_claimed"] is False


def test_preparation_report_is_disarmed():
    report = build_preparation_report()
    assert report["safety"]["promotion_armed"] is False
    assert report["safety"]["automatic_promotion"] is False
    assert report["legacy_boundary"]["legacy_endpoint_called"] is False
    assert report["runtime_boundary"]["future_bridge_implemented"] is False
    validate_report(report)



def test_formal_m74_admitted_wallet_uses_same_m300_gate_without_backfill():
    wallet = FORMAL_M74_ADMITTED_WALLETS["5PA"]
    assert TARGETS["5PA"] == wallet
    anchor = datetime(2026, 9, 4, 17, 0, 0, tzinfo=timezone.utc)
    out = evaluate_candidate_promotion(
        wallet=wallet,
        events=_dataset(wallet, anchor, prefix="5PA"),
        anchor_utc=anchor,
        terminal_at=anchor + timedelta(hours=2),
    )
    assert out["promotion_eligible"] is True
    assert out["target_admission"]["kind"] == "R7_FORMAL_M74_PASS_ADMISSION"
    assert out["target_admission"]["upstream_formal_m74_pass"] is True
    assert out["target_admission"]["candidate_entry_evidence_backfilled"] is False
    assert out["formal_claims"]["gen4_copyability_pass_claimed"] is False
    assert out["formal_claims"]["m298_pass_claimed"] is False



def test_pending_flat_m74_admission_uses_identical_m300_gate_and_quarantines_history():
    anchor = datetime(2026, 9, 5, 10, 0, 0, tzinfo=timezone.utc)
    for label, wallet in PENDING_FLAT_M74_ADMITTED_WALLETS.items():
        assert TARGETS[label] == wallet
        out = evaluate_candidate_promotion(
            wallet=wallet,
            events=_dataset(wallet, anchor, prefix=label),
            anchor_utc=anchor,
            terminal_at=anchor + timedelta(hours=2),
        )
        assert out["promotion_eligible"] is True
        assert out["target_admission"]["kind"] == "R7_M74_QUALIFIED_PENDING_FLAT_ADMISSION"
        assert out["target_admission"]["upstream_formal_m74_pass"] is False
        assert out["target_admission"]["upstream_economic_m74_qualification"] is True
        assert out["target_admission"]["upstream_flatness_only_blocker"] is True
        assert out["target_admission"]["historical_open_positions_quarantined"] is True
        assert out["target_admission"]["candidate_entry_evidence_backfilled"] is False
        assert out["formal_claims"]["m74_pass_claimed"] is False
        assert out["formal_claims"]["m298_pass_claimed"] is False
        assert out["future_selective_lifecycle_bridge"]["historical_pre_anchor_positions_carried_forward"] is False
        assert out["future_selective_lifecycle_bridge"]["pending_flat_historical_positions_quarantined"] is True
