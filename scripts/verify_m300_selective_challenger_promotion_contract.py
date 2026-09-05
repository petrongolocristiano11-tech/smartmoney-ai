from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT = Path(r"C:\smartmoney-ai")
sys.path.insert(0, str(PROJECT))

from backend.app.services.gen4_formal_m74_candidate_admission_service import (
    FORMAL_M74_ADMITTED_WALLETS,
    PENDING_FLAT_M74_ADMITTED_WALLETS,
    R7_FORMAL_REPORT_SHA256,
)

from backend.app.services.gen4_selective_challenger_promotion_service import (
    M300_LEGACY_START_QUALIFIED_CANDIDATE_COMPATIBLE,
    M300_PROMOTION_ARMED,
    TARGETS,
    build_preparation_report,
    evaluate_candidate_promotion,
    validate_policy,
    validate_report,
)
from backend.app.services.gen4_selective_micro_live_readiness_service import (
    validate_policy as validate_m298_policy,
)


def event(wallet, sig, when, kind="ACCEPTED"):
    row = {
        "wallet_address": wallet,
        "side": "BUY",
        "signature": sig,
        "fast_received_at": when,
        "fast_quote_received_at": when + timedelta(milliseconds=500),
        "fast_end_to_quote_ms": 500,
        "fast_price_impact_bps": 25.0,
        "fast_price_deterioration_bps": 250.0,
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


def main():
    assert M300_PROMOTION_ARMED is False
    assert M300_LEGACY_START_QUALIFIED_CANDIDATE_COMPATIBLE is False

    m300 = validate_policy()
    m298 = validate_m298_policy()
    assert m300["minimum_clean_entry_attempts"] == m298["minimum_entry_attempts"] == 20
    assert m300["minimum_clean_accepted_attempts"] == m298["minimum_closed_trades"] == 10
    assert m300["minimum_promotion_observation_hours"] == 0.0
    assert m300["protective_reject_rate_hard_gate"] is False

    wallet = TARGETS["CGAZ"]
    anchor = datetime(2026, 8, 31, 12, 30, 50, tzinfo=timezone.utc)

    # 50% protective rejection can still earn promotion eligibility.
    rows = []
    for i in range(20):
        rows.append(
            event(
                wallet,
                f"S{i}",
                anchor + timedelta(minutes=5 * (i + 1)),
                "ACCEPTED" if i < 10 else "PROTECTIVE",
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
    assert result["clean_window"]["protective_rejects"] == 10
    assert result["legacy_endpoint"]["compatible"] is False
    assert result["formal_claims"]["gen4_copyability_pass_claimed"] is False
    assert result["future_selective_lifecycle_bridge"]["implemented_by_m300_pre"] is False

    # Candidate runtime compatibility: fast_end_to_quote_ms may be NULL because
    # candidate rows do not depend on official webhook reconciliation. M300 must
    # reuse the already-canonical M291 fallback without weakening the 5000ms cap.
    fallback_rows = []
    for i in range(20):
        row = event(
            wallet,
            f"F{i}",
            anchor + timedelta(minutes=4 * (i + 1)),
            "ACCEPTED" if i < 10 else "PROTECTIVE",
        )
        if i < 10:
            row["fast_end_to_quote_ms"] = None
            row["fast_prequote_ms"] = 20
            row["fast_quote_latency_ms"] = 480
        fallback_rows.append(row)
    fallback = evaluate_candidate_promotion(
        wallet=wallet,
        events=fallback_rows,
        anchor_utc=anchor,
        terminal_at=anchor + timedelta(hours=2),
    )
    assert fallback["promotion_eligible"] is True
    assert fallback["clean_window"]["p95_accepted_end_to_quote_ms"] == 500.0
    assert fallback["clean_window"]["accepted_end_to_quote_fallback_derived"] == 10
    assert fallback["checks"]["accepted_evidence_complete"] is True

    # Stored evidence remains authoritative: a real 6000ms accepted sample must fail.
    slow_rows = list(fallback_rows)
    slow_rows[0] = dict(slow_rows[0])
    slow_rows[0]["fast_end_to_quote_ms"] = 6000
    slow = evaluate_candidate_promotion(
        wallet=wallet,
        events=slow_rows,
        anchor_utc=anchor,
        terminal_at=anchor + timedelta(hours=2),
    )
    assert slow["promotion_eligible"] is False
    assert slow["checks"]["accepted_end_to_quote_p95"] is False
    assert slow["clean_window"]["p95_accepted_end_to_quote_ms"] == 6000.0

    # A technical failure resets and old good entries no longer count.
    reset_rows = rows[:10]
    fail_at = anchor + timedelta(hours=2)
    reset_rows.append(event(wallet, "FAIL", fail_at, "TECHNICAL"))
    for i in range(20):
        reset_rows.append(
            event(
                wallet,
                f"N{i}",
                fail_at + timedelta(minutes=5 * (i + 1)),
                "ACCEPTED" if i < 10 else "PROTECTIVE",
            )
        )
    reset = evaluate_candidate_promotion(
        wallet=wallet,
        events=reset_rows,
        anchor_utc=anchor,
        terminal_at=fail_at + timedelta(hours=2),
    )
    assert reset["promotion_eligible"] is True
    assert reset["clean_window"]["technical_reset_applied"] is True
    assert reset["clean_window"]["attempts"] == 20

    # Insufficient accepted absolute throughput cannot pass even with many protective rejects.
    weak = []
    for i in range(20):
        weak.append(
            event(
                wallet,
                f"W{i}",
                anchor + timedelta(minutes=3 * (i + 1)),
                "ACCEPTED" if i < 9 else "PROTECTIVE",
            )
        )
    weak_result = evaluate_candidate_promotion(
        wallet=wallet,
        events=weak,
        anchor_utc=anchor,
        terminal_at=anchor + timedelta(hours=2),
    )
    assert weak_result["promotion_eligible"] is False
    assert weak_result["checks"]["minimum_clean_accepted_attempts"] is False

    # A verified R7 formal-M74 PASS may enter the same M300 entry-quality gate,
    # but its historical M74 evidence cannot substitute for fresh candidate attempts.
    formal_wallet = FORMAL_M74_ADMITTED_WALLETS["5PA"]
    assert TARGETS["5PA"] == formal_wallet
    formal_rows = []
    for i in range(20):
        formal_rows.append(
            event(
                formal_wallet,
                f"5PA{i}",
                anchor + timedelta(minutes=4 * (i + 1)),
                "ACCEPTED" if i < 10 else "PROTECTIVE",
            )
        )
    formal_result = evaluate_candidate_promotion(
        wallet=formal_wallet,
        events=formal_rows,
        anchor_utc=anchor,
        terminal_at=anchor + timedelta(hours=2),
    )
    assert formal_result["promotion_eligible"] is True
    assert formal_result["target_admission"]["upstream_formal_m74_pass"] is True
    assert formal_result["target_admission"]["upstream_formal_m74_report_sha256"] == R7_FORMAL_REPORT_SHA256
    assert formal_result["formal_claims"]["m74_pass_claimed"] is False
    assert formal_result["formal_claims"]["gen4_copyability_pass_claimed"] is False
    assert formal_result["formal_claims"]["m298_pass_claimed"] is False

    # Flatness-only historical blockers are admitted as a separate provenance.
    for label, pending_wallet in PENDING_FLAT_M74_ADMITTED_WALLETS.items():
        assert TARGETS[label] == pending_wallet
        pending_rows = []
        for i in range(20):
            pending_rows.append(
                event(
                    pending_wallet,
                    f"{label}{i}",
                    anchor + timedelta(minutes=4 * (i + 1)),
                    "ACCEPTED" if i < 10 else "PROTECTIVE",
                )
            )
        pending_result = evaluate_candidate_promotion(
            wallet=pending_wallet,
            events=pending_rows,
            anchor_utc=anchor,
            terminal_at=anchor + timedelta(hours=2),
        )
        assert pending_result["promotion_eligible"] is True
        assert pending_result["target_admission"]["kind"] == "R7_M74_QUALIFIED_PENDING_FLAT_ADMISSION"
        assert pending_result["target_admission"]["upstream_formal_m74_pass"] is False
        assert pending_result["target_admission"]["upstream_economic_m74_qualification"] is True
        assert pending_result["target_admission"]["historical_open_positions_quarantined"] is True
        assert pending_result["formal_claims"]["m74_pass_claimed"] is False
        assert pending_result["formal_claims"]["m298_pass_claimed"] is False

    prep = build_preparation_report()
    assert prep["legacy_boundary"]["legacy_start_qualified_candidate_compatible"] is False
    assert prep["runtime_boundary"]["future_selective_lifecycle_bridge_required"] is True
    assert prep["runtime_boundary"]["future_bridge_implemented"] is False
    assert prep["runtime_boundary"]["pre_promotion_backfill_allowed"] is False
    assert prep["safety"]["automatic_promotion"] is False
    validate_report(prep)

    print(
        "M300_PRE_VERIFY=PASS;"
        "promotion_disarmed=true;"
        "targets=CGAZ|89F3|5PA|3N7|2MQR;"
        "attempt_floor_from_m298=true;"
        "accepted_floor_from_m298_closed_floor=true;"
        "protective_reject_not_hard_gate=true;"
        "technical_reset=true;"
        "m291_latency_fallback=true;"
        "stored_slow_latency_still_fails=true;"
        "legacy_endpoint_compatible=false;"
        "false_gen4_copyability_pass=false;"
        "future_lifecycle_bridge_required=true;"
        "prepromotion_backfill=false"
    )


if __name__ == "__main__":
    main()
