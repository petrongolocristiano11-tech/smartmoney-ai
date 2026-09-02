from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Iterable

from backend.app.services.gen4_post_anchor_selective_evidence_service import (
    CHALLENGER_WALLETS,
    M297_ANCHOR_UTC,
    M297_REPORT_SHA256,
    M298_PRE_REPORT_SHA256,
)
from backend.app.services.gen4_selective_copyability_gate_service import (
    _end_to_quote_ms,
    classify_buy_attempt,
)
from backend.app.services.gen4_selective_micro_live_readiness_service import (
    validate_policy as validate_selective_readiness_policy,
)
from backend.app.services.gen4_zero_helius_final_pre_micro_live_service import (
    canonical_sha256,
)

M300_VERSION = "canonical-parser-gen4-selective-challenger-promotion-contract/1"
M300_SCOPE = "M300_SELECTIVE_CHALLENGER_PROMOTION_CONTRACT_DISARMED"
M300_PROMOTION_ARMED = False
M300_LEGACY_START_QUALIFIED_CANDIDATE_COMPATIBLE = False

M296_REPORT_SHA256 = "914bf15250adcb319359efb022f6bbc73954db6aee09dc05381b8ce0e1bfe1f2"
M299_PRE_REPORT_SHA256 = "a3a9f0cac44efd02f514ea5b0a4a2fa8525c37a9b65271fc6737ba50de3a68ea"

TARGETS = dict(CHALLENGER_WALLETS)

DEFAULT_POLICY: dict[str, Any] = {
    "policy_version": M300_VERSION,

    # These are not arbitrary new sample cliffs:
    # - attempts reuse M298's final attempt floor;
    # - accepted attempts reuse M298's minimum CLOSED requirement, because fewer
    #   accepted entries cannot possibly produce the minimum 10 closed trades.
    "minimum_clean_entry_attempts": 20,
    "minimum_clean_accepted_attempts": 10,

    # Entry-quality ceilings are inherited exactly from M298.
    "minimum_accepted_unsigned_build_coverage_percent": 100.0,
    "maximum_accepted_p95_end_to_quote_ms": 5000.0,
    "maximum_accepted_p95_price_deterioration_bps": 1000.0,
    "maximum_accepted_p95_price_impact_bps": 500.0,

    # Protective rejection is selective behavior, not a percentage failure gate.
    "protective_reject_rate_hard_gate": False,

    # Technical failures reset the clean window. Unknown/unmapped outcomes remain
    # fail-closed in the clean promotion sample.
    "technical_failure_policy": "RESET_CLEAN_WINDOW_AND_REQUALIFY",
    "maximum_clean_unmapped_attempts": 0,

    # Promotion starts new full-lifecycle evidence. Candidate entry history cannot
    # be backfilled into selective positions or M298 economics.
    "pre_promotion_backfill_allowed": False,
    "full_lifecycle_proof_starts_at_promotion_activation": True,

    # 24h is deliberately NOT duplicated here. It remains a final M298
    # qualification gate after full-lifecycle activation.
    "minimum_promotion_observation_hours": 0.0,
}


class M300Error(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise M300Error(message)


def _get(row: Any, key: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(key, default)
    return getattr(row, key, default)


def _aware(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif value not in (None, ""):
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _finite(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _percentile95(values: Iterable[float]) -> float | None:
    clean = sorted(
        float(v)
        for v in values
        if _finite(v) is not None
    )
    if not clean:
        return None
    return clean[max(0, math.ceil(len(clean) * 0.95) - 1)]


def validate_policy(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    p = {**DEFAULT_POLICY, **dict(policy or {})}
    _require(p.get("policy_version") == M300_VERSION, "M300 policy version inattesa.")

    m298 = validate_selective_readiness_policy()

    exact = {
        "minimum_clean_entry_attempts": int(m298["minimum_entry_attempts"]),
        "minimum_clean_accepted_attempts": int(m298["minimum_closed_trades"]),
        "maximum_clean_unmapped_attempts": 0,
    }
    for key, expected in exact.items():
        _require(int(p.get(key, -1)) == expected, f"M300 policy alterata: {key}.")

    floats = {
        "minimum_accepted_unsigned_build_coverage_percent": float(
            m298["minimum_accepted_unsigned_build_coverage_percent"]
        ),
        "maximum_accepted_p95_end_to_quote_ms": float(
            m298["maximum_accepted_p95_end_to_quote_ms"]
        ),
        "maximum_accepted_p95_price_deterioration_bps": float(
            m298["maximum_accepted_p95_price_deterioration_bps"]
        ),
        "maximum_accepted_p95_price_impact_bps": float(
            m298["maximum_accepted_p95_price_impact_bps"]
        ),
        "minimum_promotion_observation_hours": 0.0,
    }
    for key, expected in floats.items():
        actual = _finite(p.get(key))
        _require(
            actual is not None and math.isclose(actual, expected, rel_tol=0, abs_tol=1e-9),
            f"M300 policy alterata: {key}.",
        )

    _require(
        p.get("protective_reject_rate_hard_gate") is False,
        "M300 protective reject hard gate attivato.",
    )
    _require(
        p.get("technical_failure_policy") == "RESET_CLEAN_WINDOW_AND_REQUALIFY",
        "M300 technical failure policy inattesa.",
    )
    _require(
        p.get("pre_promotion_backfill_allowed") is False,
        "M300 pre-promotion backfill non consentito.",
    )
    _require(
        p.get("full_lifecycle_proof_starts_at_promotion_activation") is True,
        "M300 full-lifecycle anchor non fail-closed.",
    )
    return p


def evaluate_candidate_promotion(
    *,
    wallet: str,
    events: list[Any],
    anchor_utc: datetime | str,
    terminal_at: datetime | str,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    p = validate_policy(policy)
    _require(wallet in TARGETS.values(), "M300 wallet non appartenente ai challenger approvati.")

    anchor = _aware(anchor_utc)
    terminal = _aware(terminal_at)
    _require(anchor is not None, "M300 anchor non valido.")
    _require(terminal is not None, "M300 terminal non valido.")
    _require(terminal >= anchor, "M300 terminal precedente all'anchor.")

    post_anchor: list[dict[str, Any]] = []
    for event in events:
        if str(_get(event, "wallet_address", "") or "") != wallet:
            continue
        if str(_get(event, "side", "") or "").upper() != "BUY":
            continue
        when = _aware(_get(event, "fast_received_at"))
        if when is None or when <= anchor or when > terminal:
            continue
        category, code = classify_buy_attempt(event)
        post_anchor.append(
            {
                "event": event,
                "timestamp": when,
                "category": category,
                "code": code,
                "signature": str(_get(event, "signature", "") or ""),
            }
        )
    post_anchor.sort(key=lambda x: (x["timestamp"], x["signature"]))

    technical_all = [
        row for row in post_anchor
        if row["category"] == "TECHNICAL_FAILURE"
    ]
    last_technical = (
        max(row["timestamp"] for row in technical_all)
        if technical_all else None
    )
    effective_anchor = max(
        x for x in (anchor, last_technical) if x is not None
    )

    clean = [
        row for row in post_anchor
        if row["timestamp"] > effective_anchor
    ]
    accepted = [x for x in clean if x["category"] == "ACCEPTED"]
    market = [
        x for x in clean if x["category"] == "MARKET_PROTECTIVE_REJECT"
    ]
    liquidity = [
        x for x in clean if x["category"] == "LIQUIDITY_PROTECTIVE_REJECT"
    ]
    clean_technical = [
        x for x in clean if x["category"] == "TECHNICAL_FAILURE"
    ]
    unmapped = [
        x for x in clean
        if x["category"] not in {
            "ACCEPTED",
            "MARKET_PROTECTIVE_REJECT",
            "LIQUIDITY_PROTECTIVE_REJECT",
            "TECHNICAL_FAILURE",
        }
    ]

    accepted_end: list[float] = []
    accepted_det: list[float] = []
    accepted_impact: list[float] = []
    incomplete_accepted: list[str] = []
    accepted_end_fallback_derived = 0

    for row in accepted:
        event = row["event"]
        stored_end = _finite(_get(event, "fast_end_to_quote_ms"))
        end = _finite(_end_to_quote_ms(event, None, p))
        if stored_end is None and end is not None:
            accepted_end_fallback_derived += 1
        det = _finite(_get(event, "fast_price_deterioration_bps"))
        impact = _finite(_get(event, "fast_price_impact_bps"))
        built = bool(_get(event, "fast_transaction_built", False))
        if end is None or det is None or impact is None or not built:
            incomplete_accepted.append(row["signature"] or "UNKNOWN")
            continue
        accepted_end.append(end)
        accepted_det.append(det)
        accepted_impact.append(impact)

    attempts = len(clean)
    accepted_count = len(accepted)
    protective_count = len(market) + len(liquidity)
    classified = accepted_count + protective_count + len(clean_technical) + len(unmapped)

    unsigned_pct = (
        100.0
        * sum(bool(_get(x["event"], "fast_transaction_built", False)) for x in accepted)
        / accepted_count
        if accepted_count else 0.0
    )
    p95_end = _percentile95(accepted_end)
    p95_det = _percentile95(accepted_det)
    p95_impact = _percentile95(accepted_impact)

    times = [row["timestamp"] for row in clean]
    observation_hours = (
        max(0.0, (max(times) - min(times)).total_seconds() / 3600.0)
        if len(times) >= 2 else 0.0
    )

    checks = {
        "target_is_approved_challenger": wallet in TARGETS.values(),
        "clean_attempt_classification_complete": attempts == classified,
        "minimum_clean_entry_attempts": attempts >= p["minimum_clean_entry_attempts"],
        "minimum_clean_accepted_attempts": accepted_count >= p["minimum_clean_accepted_attempts"],
        "accepted_unsigned_build_coverage": (
            unsigned_pct >= p["minimum_accepted_unsigned_build_coverage_percent"]
        ),
        "accepted_evidence_complete": len(incomplete_accepted) == 0,
        "accepted_end_to_quote_p95": (
            p95_end is not None
            and p95_end <= p["maximum_accepted_p95_end_to_quote_ms"]
        ),
        "accepted_price_deterioration_p95": (
            p95_det is not None
            and p95_det <= p["maximum_accepted_p95_price_deterioration_bps"]
        ),
        "accepted_price_impact_p95": (
            p95_impact is not None
            and p95_impact <= p["maximum_accepted_p95_price_impact_bps"]
        ),
        "zero_technical_failures_in_effective_clean_window": len(clean_technical) == 0,
        "zero_unmapped_attempts": len(unmapped) <= p["maximum_clean_unmapped_attempts"],
    }

    eligible = all(checks.values())

    return {
        "scope": M300_SCOPE,
        "version": M300_VERSION,
        "wallet": wallet,
        "state": (
            "PROMOTION_ELIGIBLE_DISARMED"
            if eligible else "PROMOTION_PENDING_OR_FAIL"
        ),
        "promotion_eligible": eligible,
        "promotion_armed": False,
        "promotion_executed": False,
        "clean_window": {
            "m297_anchor_utc": anchor.isoformat(),
            "last_technical_failure_utc": (
                last_technical.isoformat() if last_technical else None
            ),
            "effective_anchor_utc": effective_anchor.isoformat(),
            "technical_reset_applied": bool(last_technical and last_technical > anchor),
            "observation_hours": round(observation_hours, 6),
            "attempts": attempts,
            "accepted": accepted_count,
            "market_protective_rejects": len(market),
            "liquidity_protective_rejects": len(liquidity),
            "protective_rejects": protective_count,
            "technical_failures": len(clean_technical),
            "unmapped_attempts": len(unmapped),
            "accepted_unsigned_build_coverage_percent": round(unsigned_pct, 6),
            "p95_accepted_end_to_quote_ms": p95_end,
            "p95_accepted_price_deterioration_bps": p95_det,
            "p95_accepted_price_impact_bps": p95_impact,
            "accepted_end_to_quote_evidence_method": (
                "M291_CANONICAL_FALLBACK_WITH_RECEIPT_NONE"
            ),
            "accepted_end_to_quote_fallback_derived": accepted_end_fallback_derived,
            "incomplete_accepted_evidence": incomplete_accepted,
        },
        "checks": checks,
        "protective_reject_policy": {
            "hard_rate_gate": False,
            "absolute_clean_throughput_required": True,
        },
        "legacy_endpoint": {
            "path": "/integrity/parser-gen4-copyability/start-qualified-candidate",
            "compatible": False,
            "reason": (
                "LEGACY_ENDPOINT_REQUIRES_GEN4_COPYABILITY_PASS_AND_RIGID_SELECTION_SNAPSHOT"
            ),
            "gen4_copyability_pass_invented": False,
            "must_not_be_called_from_m300": True,
        },
        "future_selective_lifecycle_bridge": {
            "required": True,
            "implemented_by_m300_pre": False,
            "requires_explicit_code_change_and_deploy": True,
            "candidate_fastpath_entry_evidence_backfilled": False,
            "full_lifecycle_proof_starts_at_promotion_activation": True,
            "future_m298_observation_hours_still_required": 24.0,
            "future_m298_entry_attempts_still_required": 20,
            "future_m298_closed_trades_still_required": 10,
        },
        "formal_claims": {
            "m74_pass_claimed": False,
            "legacy_m75_pass_claimed": False,
            "gen4_copyability_pass_claimed": False,
            "m298_pass_claimed": False,
            "micro_live_ready_claimed": False,
        },
        "safety": {
            "database_writes": 0,
            "backend_mutations": 0,
            "railway_variable_set": False,
            "provider_mutations": 0,
            "helius_calls": 0,
            "birdeye_cu": 0,
            "jupiter_requests": 0,
            "live_execution": False,
            "signer_access": False,
            "submitted_transactions": 0,
            "paper_orders": 0,
            "m74_changed": False,
            "m75_changed": False,
            "pam_changed": False,
        },
    }


def build_preparation_report() -> dict[str, Any]:
    p = validate_policy()
    payload: dict[str, Any] = {
        "evaluation": "PASS",
        "scope": M300_SCOPE,
        "version": M300_VERSION,
        "state": "IMPLEMENTED_DISARMED_AWAITING_CANDIDATE_ENTRY_EVIDENCE",
        "targets": TARGETS,
        "lineage": {
            "m296_report_sha256": M296_REPORT_SHA256,
            "m297_anchor_utc": M297_ANCHOR_UTC,
            "m297_report_sha256": M297_REPORT_SHA256,
            "m298_pre_report_sha256": M298_PRE_REPORT_SHA256,
            "m299_pre_report_sha256": M299_PRE_REPORT_SHA256,
        },
        "promotion_gate": {
            "minimum_clean_entry_attempts": p["minimum_clean_entry_attempts"],
            "minimum_clean_accepted_attempts": p["minimum_clean_accepted_attempts"],
            "minimum_promotion_observation_hours": p["minimum_promotion_observation_hours"],
            "observation_hours_is_promotion_gate": False,
            "minimum_accepted_unsigned_build_coverage_percent": p[
                "minimum_accepted_unsigned_build_coverage_percent"
            ],
            "maximum_accepted_p95_end_to_quote_ms": p[
                "maximum_accepted_p95_end_to_quote_ms"
            ],
            "maximum_accepted_p95_price_deterioration_bps": p[
                "maximum_accepted_p95_price_deterioration_bps"
            ],
            "maximum_accepted_p95_price_impact_bps": p[
                "maximum_accepted_p95_price_impact_bps"
            ],
            "technical_failure_policy": p["technical_failure_policy"],
            "maximum_clean_unmapped_attempts": p[
                "maximum_clean_unmapped_attempts"
            ],
            "protective_reject_rate_hard_gate": False,
        },
        "threshold_rationale": {
            "attempts_floor_source": "M298_MINIMUM_ENTRY_ATTEMPTS",
            "accepted_floor_source": (
                "M298_MINIMUM_CLOSED_TRADES;FEWER_ACCEPTED_CANNOT_PRODUCE_10_CLOSED"
            ),
            "quality_ceilings_source": "M298_ACCEPTED_ENTRY_QUALITY_LIMITS",
            "accepted_end_to_quote_evidence": (
                "M291_CANONICAL_FALLBACK_WITH_RECEIPT_NONE;"
                "STORED_FAST_END_PREFERRED;"
                "THEN_FAST_RECEIVED_TO_QUOTE;"
                "THEN_PREQUOTE_PLUS_QUOTE_LATENCY"
            ),
            "24h_not_duplicated": (
                "PROMOTION_ONLY_STARTS_FULL_LIFECYCLE;M298_24H_REMAINS_AFTER_ACTIVATION"
            ),
        },
        "legacy_boundary": {
            "legacy_start_qualified_candidate_compatible": False,
            "legacy_endpoint_requires_gen4_copyability_pass": True,
            "gen4_copyability_pass_invented": False,
            "m74_pass_invented": False,
            "m75_pass_invented": False,
            "legacy_endpoint_called": False,
        },
        "runtime_boundary": {
            "candidate_lane_currently_entry_only": True,
            "candidate_watchlist_selective_positions_created": 0,
            "official_selective_position_scope": "OFFICIAL_FASTPATH_SELECTIVE",
            "future_selective_lifecycle_bridge_required": True,
            "future_bridge_implemented": False,
            "pre_promotion_backfill_allowed": False,
            "full_lifecycle_proof_starts_at_promotion_activation": True,
        },
        "safety": {
            "promotion_armed": False,
            "automatic_promotion": False,
            "database_reads": 0,
            "database_writes": 0,
            "backend_calls": 0,
            "railway_variable_set": False,
            "provider_mutations": 0,
            "helius_calls": 0,
            "birdeye_cu": 0,
            "jupiter_requests": 0,
            "commit": False,
            "push": False,
            "deploy": False,
            "live": False,
            "signer": False,
            "submission": False,
            "paper_orders": 0,
            "m74_changed": False,
            "m75_changed": False,
            "pam_changed": False,
        },
    }
    payload["integrity"] = {"report_payload_sha256": canonical_sha256(payload)}
    return payload


def validate_report(report: dict[str, Any]) -> dict[str, Any]:
    _require(report.get("evaluation") == "PASS", "M300 report non PASS.")
    _require(report.get("scope") == M300_SCOPE, "M300 report scope inatteso.")
    _require(report.get("version") == M300_VERSION, "M300 report version inattesa.")
    integ = dict(report.get("integrity") or {})
    expected = str(integ.get("report_payload_sha256") or "")
    raw = {k: v for k, v in report.items() if k != "integrity"}
    _require(
        len(expected) == 64 and expected == canonical_sha256(raw),
        "M300 report hash non valido.",
    )
    safety = dict(report.get("safety") or {})
    _require(safety.get("promotion_armed") is False, "M300 promotion armata.")
    _require(safety.get("automatic_promotion") is False, "M300 automatic promotion attiva.")
    for key in (
        "database_reads", "database_writes", "backend_calls", "provider_mutations",
        "helius_calls", "birdeye_cu", "jupiter_requests", "paper_orders",
    ):
        _require(int(safety.get(key, -1)) == 0, f"M300 safety violata: {key}.")
    for key in ("commit", "push", "deploy", "live", "signer", "submission"):
        _require(safety.get(key) is False, f"M300 safety violata: {key}.")
    return report
