from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any

from backend.app.services.gen4_zero_helius_final_pre_micro_live_service import (
    canonical_sha256,
    evaluate_m76_independence,
    validate_policy as validate_legacy_m74_m78_policy,
)

SELECTIVE_READINESS_VERSION = "canonical-parser-gen4-selective-micro-live-readiness/1"
SELECTIVE_READINESS_SCOPE = "M298_SELECTIVE_FOLLOWER_MICRO_LIVE_READINESS_DISARMED"
SELECTIVE_EVIDENCE_SCOPE = "M298_SELECTIVE_FORWARD_EVIDENCE"
SELECTIVE_EVIDENCE_VERSION = "canonical-parser-gen4-selective-forward-evidence/1"
SELECTIVE_READINESS_ARMED = False

DEFAULT_POLICY: dict[str, Any] = {
    "policy_version": SELECTIVE_READINESS_VERSION,
    "minimum_observation_hours": 24.0,
    "minimum_entry_attempts": 20,
    "minimum_closed_trades": 10,
    "minimum_webhook_coverage_percent": 95.0,
    "minimum_accepted_unsigned_build_coverage_percent": 100.0,
    "maximum_accepted_p95_end_to_quote_ms": 5000.0,
    "maximum_accepted_p95_price_deterioration_bps": 1000.0,
    "maximum_accepted_p95_price_impact_bps": 500.0,
    "maximum_technical_failures": 0,
    "maximum_unmapped_attempts": 0,
    "maximum_accepted_policy_violations": 0,
    "maximum_exit_policy_violations": 0,
    "maximum_exit_failures": 0,
    "require_zero_open_positions": True,
    "require_zero_unresolved_failures": True,
    "minimum_net_pnl_sol_exclusive": 0.0,
    "minimum_profit_factor": 1.30,
    "maximum_drawdown_percent": 15.0,
    "protective_reject_rate_hard_gate": False,
    "minimum_independent_wallets": 2,
    "m35_maximum_total_budget_sol": 0.05,
    "m35_maximum_order_budget_sol": 0.01,
    "m35_maximum_order_count": 3,
    "m35_maximum_validity_minutes": 15,
}

class SelectiveReadinessError(RuntimeError):
    pass

def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SelectiveReadinessError(message)

def _finite(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    return result if math.isfinite(result) else float(default)

def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)

def _aware(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif value not in (None, ""):
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)

def _without_integrity(value: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in value.items() if k != "integrity"}

def zero_safety() -> dict[str, Any]:
    return {
        "network_requests": 0,
        "public_rpc_requests": 0,
        "helius_requests": 0,
        "helius_credits": 0,
        "birdeye_cu": 0,
        "database_reads": 0,
        "database_writes": 0,
        "backend_posts": 0,
        "jupiter_requests": 0,
        "paper_orders": 0,
        "live_orders": 0,
        "signed_transactions": 0,
        "submitted_transactions": 0,
        "signer_access": False,
        "automatic_live_activation": False,
        "micro_live_execution_authorized": False,
        "selective_readiness_armed": False,
    }

def validate_policy(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    p = {**DEFAULT_POLICY, **dict(policy or {})}
    _require(p.get("policy_version") == SELECTIVE_READINESS_VERSION, "Selective readiness policy version inattesa.")
    legacy = validate_legacy_m74_m78_policy()

    exact = {
        "minimum_entry_attempts": int(legacy["canary_minimum_entry_attempts"]),
        "minimum_closed_trades": int(legacy["canary_minimum_closed_trades"]),
        "maximum_technical_failures": 0,
        "maximum_unmapped_attempts": 0,
        "maximum_accepted_policy_violations": 0,
        "maximum_exit_policy_violations": 0,
        "maximum_exit_failures": 0,
        "minimum_independent_wallets": int(legacy["minimum_independent_canary_wallets"]),
        "m35_maximum_order_count": int(legacy["m35_maximum_order_count"]),
        "m35_maximum_validity_minutes": int(legacy["m35_maximum_validity_minutes"]),
    }
    for key, expected in exact.items():
        _require(_integer(p.get(key), -999) == expected, f"Selective policy alterata: {key}.")

    floats = {
        "minimum_observation_hours": float(legacy["canary_minimum_observation_hours"]),
        "minimum_webhook_coverage_percent": float(legacy["canary_minimum_webhook_coverage_percent"]),
        "minimum_accepted_unsigned_build_coverage_percent": float(legacy["canary_minimum_unsigned_build_coverage_percent"]),
        "maximum_accepted_p95_end_to_quote_ms": float(legacy["canary_maximum_p95_end_to_quote_ms"]),
        "maximum_accepted_p95_price_deterioration_bps": float(legacy["canary_maximum_p95_price_deterioration_bps"]),
        "maximum_accepted_p95_price_impact_bps": float(legacy["canary_maximum_p95_price_impact_bps"]),
        "minimum_profit_factor": float(legacy["minimum_profit_factor"]),
        "maximum_drawdown_percent": float(legacy["maximum_drawdown_percent"]),
        "m35_maximum_total_budget_sol": float(legacy["m35_maximum_total_budget_sol"]),
        "m35_maximum_order_budget_sol": float(legacy["m35_maximum_order_budget_sol"]),
    }
    for key, expected in floats.items():
        _require(math.isclose(_finite(p.get(key)), expected, rel_tol=0, abs_tol=1e-9), f"Selective policy alterata: {key}.")

    _require(math.isclose(_finite(p.get("minimum_net_pnl_sol_exclusive")), 0.0, rel_tol=0, abs_tol=1e-12), "Selective policy alterata: minimum_net_pnl_sol_exclusive.")
    _require(p.get("protective_reject_rate_hard_gate") is False, "Protective reject hard gate attivato.")
    _require(p.get("require_zero_open_positions") is True, "Zero open positions non richiesto.")
    _require(p.get("require_zero_unresolved_failures") is True, "Zero unresolved failures non richiesto.")
    return p

def sign_selective_evidence(
    wallet_evidence: dict[str, dict[str, Any]],
    *,
    anchor_utc: str,
    lineage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    anchor = _aware(anchor_utc)
    _require(anchor is not None, "Anchor selective evidence non valido.")
    payload: dict[str, Any] = {
        "scope": SELECTIVE_EVIDENCE_SCOPE,
        "version": SELECTIVE_EVIDENCE_VERSION,
        "anchor_utc": anchor.isoformat(),
        "wallet_evidence": {
            str(wallet): dict(row)
            for wallet, row in dict(wallet_evidence or {}).items()
            if str(wallet)
        },
        "lineage": dict(lineage or {}),
        "safety": zero_safety(),
    }
    _require(bool(payload["wallet_evidence"]), "Selective evidence senza wallet.")
    payload["integrity"] = {"payload_sha256": canonical_sha256(payload)}
    return payload

def validate_selective_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    _require(payload.get("scope") == SELECTIVE_EVIDENCE_SCOPE, "Scope evidence selective inatteso.")
    _require(payload.get("version") == SELECTIVE_EVIDENCE_VERSION, "Version evidence selective inattesa.")
    _require(_aware(payload.get("anchor_utc")) is not None, "Anchor evidence selective non valido.")
    _require(bool(dict(payload.get("wallet_evidence") or {})), "Selective evidence senza wallet.")
    integrity = dict(payload.get("integrity") or {})
    expected = str(integrity.get("payload_sha256") or "")
    _require(len(expected) == 64 and expected == canonical_sha256(_without_integrity(payload)), "Hash evidence selective non valido.")
    safety = dict(payload.get("safety") or {})
    for key in (
        "network_requests", "public_rpc_requests", "helius_requests", "helius_credits",
        "birdeye_cu", "database_writes", "backend_posts", "jupiter_requests",
        "paper_orders", "live_orders", "signed_transactions", "submitted_transactions",
    ):
        _require(_integer(safety.get(key)) == 0, f"Safety evidence selective violata: {key}.")
    _require(safety.get("signer_access") is False, "Signer evidence selective non disarmato.")
    _require(safety.get("micro_live_execution_authorized") is False, "Evidence selective ha autorizzato Micro Live.")
    return payload

def evaluate_selective_wallet(
    wallet: str,
    evidence: dict[str, Any],
    *,
    source_m74_audit: dict[str, Any] | None = None,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    p = validate_policy(policy)
    row = dict(evidence or {})
    wallet_address = str(row.get("wallet_address") or wallet or "")
    _require(wallet_address == str(wallet or ""), "Wallet selective evidence non coerente.")

    attempts = _integer(row.get("entry_attempts"), -1)
    accepted = _integer(row.get("accepted_attempts"), -1)
    protective = _integer(row.get("protective_rejects"), -1)
    technical = _integer(row.get("technical_failures"), -1)
    unmapped = _integer(row.get("unmapped_attempts"), -1)
    closed = _integer(row.get("closed_trades"), -1)

    counts_nonnegative = min(attempts, accepted, protective, technical, unmapped, closed) >= 0
    classification_complete = counts_nonnegative and attempts == accepted + protective + technical + unmapped
    lifecycle_cardinality = counts_nonnegative and closed <= accepted

    webhook = _finite(row.get("webhook_coverage_percent"), -1.0)
    unsigned = _finite(row.get("accepted_unsigned_build_coverage_percent"), -1.0)
    p95_end = _finite(row.get("accepted_p95_end_to_quote_ms"), float("inf"))
    p95_det = _finite(row.get("accepted_p95_price_deterioration_bps"), float("inf"))
    p95_impact = _finite(row.get("accepted_p95_price_impact_bps"), float("inf"))
    net = _finite(row.get("net_pnl_sol"), -float("inf"))
    pf = _finite(row.get("profit_factor"), 0.0)
    dd = _finite(row.get("maximum_drawdown_percent"), float("inf"))

    checks = {
        "count_fields_valid": counts_nonnegative,
        "attempt_classification_complete": classification_complete,
        "closed_not_above_accepted": lifecycle_cardinality,
        "observation_hours": _finite(row.get("observation_hours")) >= p["minimum_observation_hours"],
        "entry_attempts": attempts >= p["minimum_entry_attempts"],
        "closed_trades": closed >= p["minimum_closed_trades"],
        "webhook_coverage": webhook >= p["minimum_webhook_coverage_percent"],
        "accepted_unsigned_build_coverage": unsigned >= p["minimum_accepted_unsigned_build_coverage_percent"],
        "accepted_end_to_quote_p95": p95_end <= p["maximum_accepted_p95_end_to_quote_ms"],
        "accepted_price_deterioration_p95": p95_det <= p["maximum_accepted_p95_price_deterioration_bps"],
        "accepted_price_impact_p95": p95_impact <= p["maximum_accepted_p95_price_impact_bps"],
        "zero_technical_failures": technical <= p["maximum_technical_failures"],
        "zero_unmapped_attempts": unmapped <= p["maximum_unmapped_attempts"],
        "zero_accepted_policy_violations": _integer(row.get("accepted_policy_violations"), -1) <= p["maximum_accepted_policy_violations"],
        "zero_exit_policy_violations": _integer(row.get("exit_policy_violations"), -1) <= p["maximum_exit_policy_violations"],
        "zero_exit_failures": _integer(row.get("exit_failures"), -1) <= p["maximum_exit_failures"],
        "zero_open_positions": _integer(row.get("open_positions"), -1) == 0 if p["require_zero_open_positions"] else True,
        "zero_unresolved_failures": _integer(row.get("unresolved_failures"), -1) == 0 if p["require_zero_unresolved_failures"] else True,
        "positive_net_pnl": net > p["minimum_net_pnl_sol_exclusive"],
        "profit_factor": pf >= p["minimum_profit_factor"],
        "follower_drawdown": dd <= p["maximum_drawdown_percent"],
    }
    passed = all(checks.values())

    source = dict(source_m74_audit or {})
    source_pass = source.get("passed") if isinstance(source.get("passed"), bool) else None
    source_failed_checks = sorted(str(x) for x in (source.get("failed_checks") or []) if str(x))

    reject_rate = 100.0 * protective / attempts if attempts > 0 else 0.0
    accepted_rate = 100.0 * accepted / attempts if attempts > 0 else 0.0

    return {
        "wallet_address": wallet_address,
        "passed": passed,
        "state": "SELECTIVE_FOLLOWER_QUALIFIED_DISARMED" if passed else "SELECTIVE_FOLLOWER_PENDING_OR_FAIL",
        "checks": checks,
        "metrics": {
            "observation_hours": round(_finite(row.get("observation_hours")), 6),
            "entry_attempts": attempts,
            "accepted_attempts": accepted,
            "protective_rejects": protective,
            "protective_reject_rate_percent": round(reject_rate, 6),
            "accepted_rate_percent": round(accepted_rate, 6),
            "technical_failures": technical,
            "unmapped_attempts": unmapped,
            "closed_trades": closed,
            "webhook_coverage_percent": round(webhook, 6),
            "accepted_unsigned_build_coverage_percent": round(unsigned, 6),
            "accepted_p95_end_to_quote_ms": round(p95_end, 6) if math.isfinite(p95_end) else None,
            "accepted_p95_price_deterioration_bps": round(p95_det, 6) if math.isfinite(p95_det) else None,
            "accepted_p95_price_impact_bps": round(p95_impact, 6) if math.isfinite(p95_impact) else None,
            "net_pnl_sol": round(net, 9) if math.isfinite(net) else None,
            "profit_factor": round(pf, 9),
            "maximum_drawdown_percent": round(dd, 6) if math.isfinite(dd) else None,
            "open_positions": _integer(row.get("open_positions"), -1),
            "unresolved_failures": _integer(row.get("unresolved_failures"), -1),
        },
        "source_m74_audit": {
            "passed": source_pass,
            "failed_checks": source_failed_checks,
            "used_as_selective_admission_gate": False,
            "preserved_as_separate_source_risk_audit": True,
        },
        "legacy_claims": {
            "formal_m74_pass_claimed": False,
            "formal_m75_pass_claimed": False,
            "legacy_m75_rewritten": False,
        },
        "protective_reject_policy": {
            "hard_rate_gate": False,
            "absolute_throughput_still_required": True,
        },
        "micro_live_execution_authorized": False,
    }

def evaluate_selective_pool(
    selective_evidence: dict[str, Any],
    independence_evidence: dict[str, Any],
    *,
    source_m74_audits: dict[str, dict[str, Any]] | None = None,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    p = validate_policy()
    validate_selective_evidence(selective_evidence)

    from backend.app.services.gen4_zero_helius_final_pre_micro_live_service import (
        M76_EVIDENCE_SCOPE,
        M76_EVIDENCE_VERSION,
    )
    _require(independence_evidence.get("scope") == M76_EVIDENCE_SCOPE, "Scope independence inatteso.")
    _require(independence_evidence.get("version") == M76_EVIDENCE_VERSION, "Version independence inattesa.")
    integ = dict(independence_evidence.get("integrity") or {})
    expected = str(integ.get("payload_sha256") or "")
    _require(len(expected) == 64 and expected == canonical_sha256(_without_integrity(independence_evidence)), "Hash independence non valido.")

    audits = dict(source_m74_audits or {})
    rows = [
        evaluate_selective_wallet(
            str(wallet), dict(evidence or {}),
            source_m74_audit=dict(audits.get(str(wallet)) or {}),
            policy=p,
        )
        for wallet, evidence in sorted(dict(selective_evidence.get("wallet_evidence") or {}).items())
    ]
    passed_wallets = [row["wallet_address"] for row in rows if row["passed"]]
    passed_set = set(passed_wallets)
    confirmations = [
        dict(row) for row in independence_evidence.get("confirmations") or []
        if str(row.get("wallet_address") or "") in passed_set
    ]
    m76 = evaluate_m76_independence(
        passed_wallets, confirmations, policy=validate_legacy_m74_m78_policy()
    )
    ready = len(passed_wallets) >= p["minimum_independent_wallets"] and m76["passed"] is True
    now = (evaluated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)

    payload: dict[str, Any] = {
        "evaluation": "PASS",
        "scope": SELECTIVE_READINESS_SCOPE,
        "version": SELECTIVE_READINESS_VERSION,
        "evaluated_at_utc": now.isoformat(),
        "anchor_utc": selective_evidence["anchor_utc"],
        "selective_wallet_results": rows,
        "selective_pass_wallets": passed_wallets,
        "m76_independence_reused": m76,
        "micro_live_readiness": {
            "ready_for_explicit_authorization": ready,
            "state": "SELECTIVE_READY_FOR_EXPLICIT_MICRO_LIVE_AUTHORIZATION" if ready else "SELECTIVE_NOT_READY_WAITING_REAL_EVIDENCE",
            "minimum_independent_wallets": p["minimum_independent_wallets"],
            "qualified_wallet_count": len(passed_wallets),
            "automatic_live_activation": False,
            "micro_live_execution_authorized": False,
            "signer_authorized": False,
        },
        "m77_micro_live_envelope": {
            "maximum_total_budget_sol": p["m35_maximum_total_budget_sol"],
            "maximum_order_budget_sol": p["m35_maximum_order_budget_sol"],
            "maximum_order_count": p["m35_maximum_order_count"],
            "maximum_validity_minutes": p["m35_maximum_validity_minutes"],
            "reuses_existing_m35_governance": True,
            "signer_connected": False,
            "live_engine_connected": False,
            "execution_authorized": False,
        },
        "legacy_boundary": {
            "m74_source_audit_preserved": True,
            "m74_thresholds_changed": False,
            "m75_thresholds_changed": False,
            "m75_formal_pass_claimed": False,
            "m74_formal_pass_invented": False,
            "pam_changed": False,
            "selective_lane_is_distinct_contract": True,
        },
        "safety": zero_safety(),
    }
    payload["integrity"] = {"report_payload_sha256": canonical_sha256(payload)}
    return payload

def build_preparation_report(
    *,
    m297_anchor_utc: str,
    m297_report_sha256: str,
    prepared_at: datetime | None = None,
) -> dict[str, Any]:
    p = validate_policy()
    anchor = _aware(m297_anchor_utc)
    _require(anchor is not None, "M297 anchor non valido.")
    _require(len(str(m297_report_sha256 or "")) == 64, "SHA M297 non valido.")
    now = (prepared_at or datetime.now(timezone.utc)).astimezone(timezone.utc)

    payload: dict[str, Any] = {
        "evaluation": "PASS",
        "scope": SELECTIVE_READINESS_SCOPE,
        "version": SELECTIVE_READINESS_VERSION,
        "mode": "PREPARE_SELECTIVE_READINESS_CONTRACT_ZERO_NETWORK",
        "prepared_at_utc": now.isoformat(),
        "m297_lineage": {
            "anchor_utc": anchor.isoformat(),
            "report_sha256": str(m297_report_sha256),
        },
        "wallet_gate": {
            "minimum_observation_hours": p["minimum_observation_hours"],
            "minimum_entry_attempts": p["minimum_entry_attempts"],
            "minimum_closed_trades": p["minimum_closed_trades"],
            "minimum_webhook_coverage_percent": p["minimum_webhook_coverage_percent"],
            "minimum_accepted_unsigned_build_coverage_percent": p["minimum_accepted_unsigned_build_coverage_percent"],
            "maximum_accepted_p95_end_to_quote_ms": p["maximum_accepted_p95_end_to_quote_ms"],
            "maximum_accepted_p95_price_deterioration_bps": p["maximum_accepted_p95_price_deterioration_bps"],
            "maximum_accepted_p95_price_impact_bps": p["maximum_accepted_p95_price_impact_bps"],
            "maximum_technical_failures": p["maximum_technical_failures"],
            "minimum_profit_factor": p["minimum_profit_factor"],
            "maximum_drawdown_percent": p["maximum_drawdown_percent"],
            "positive_net_pnl_required": True,
            "protective_reject_rate_hard_gate": False,
            "absolute_throughput_required": True,
        },
        "pool_gate": {
            "minimum_independent_wallets": p["minimum_independent_wallets"],
            "manual_independence_confirmation_required": True,
            "distinct_cluster_required": True,
            "reuses_existing_m76_independence_semantics": True,
        },
        "legacy_boundary": {
            "m74_source_audit_preserved": True,
            "m74_thresholds_changed": False,
            "m75_thresholds_changed": False,
            "legacy_m75_reject_gate_changed": False,
            "selective_lane_does_not_claim_legacy_m75_pass": True,
            "pam_changed": False,
        },
        "m77_micro_live_envelope": {
            "maximum_total_budget_sol": p["m35_maximum_total_budget_sol"],
            "maximum_order_budget_sol": p["m35_maximum_order_budget_sol"],
            "maximum_order_count": p["m35_maximum_order_count"],
            "maximum_validity_minutes": p["m35_maximum_validity_minutes"],
            "execution_authorized": False,
        },
        "state": "IMPLEMENTED_DISARMED_AWAITING_M297_POST_ANCHOR_EVIDENCE",
        "safety": zero_safety(),
    }
    payload["integrity"] = {"report_payload_sha256": canonical_sha256(payload)}
    return payload

def validate_report(report: dict[str, Any]) -> dict[str, Any]:
    _require(report.get("evaluation") == "PASS", "Selective readiness report non PASS.")
    _require(report.get("scope") == SELECTIVE_READINESS_SCOPE, "Scope selective readiness inatteso.")
    _require(report.get("version") == SELECTIVE_READINESS_VERSION, "Version selective readiness inattesa.")
    integ = dict(report.get("integrity") or {})
    expected = str(integ.get("report_payload_sha256") or "")
    _require(len(expected) == 64 and expected == canonical_sha256(_without_integrity(report)), "Hash selective readiness report non valido.")
    safety = dict(report.get("safety") or {})
    for key in (
        "network_requests", "public_rpc_requests", "helius_requests", "helius_credits",
        "birdeye_cu", "database_reads", "database_writes", "backend_posts",
        "jupiter_requests", "paper_orders", "live_orders", "signed_transactions",
        "submitted_transactions",
    ):
        _require(_integer(safety.get(key)) == 0, f"Safety selective readiness violata: {key}.")
    _require(safety.get("signer_access") is False, "Signer selective readiness non disarmato.")
    _require(safety.get("micro_live_execution_authorized") is False, "Selective readiness ha autorizzato Micro Live.")
    _require(safety.get("selective_readiness_armed") is False, "Selective readiness armato.")
    return report
