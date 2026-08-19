from __future__ import annotations

import math
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from backend.app.services.gen4_closed_trade_readonly_audit_service import (
    canonical_sha256,
)
from backend.app.services.gen4_zero_helius_adaptive_continuation_service import (
    M71_SCOPE,
    M71_VERSION,
    validate_continuation_report,
)
from backend.app.services.gen4_zero_helius_pre_micro_live_service import (
    M67_M70_SCOPE,
    M67_M70_VERSION,
    validate_rpc_evidence,
)


M72_VERSION = "canonical-parser-gen4-definitive-discovery-rotation/1"
M72_SCOPE = "M72_DEFINITIVE_DISCOVERY_ROTATION_READ_ONLY"
M72_PLAN_SCOPE = "M72_CONTROLLED_NEW_WALLET_ACQUISITION_PLAN_DISARMED"
M72_RUN_CONFIRMATION = "RUN_M72_DEFINITIVE_DISCOVERY_ROTATION_READ_ONLY"
M72_FUTURE_HELIUS_CONFIRMATION = "AUTHORIZE_M72_CONTROLLED_HELIUS_DISCOVERY_LATER"

DISPOSITION_RETIRE = "RETIRED_FROM_PROMOTION"
DISPOSITION_OBSERVE = "OBSERVE_ONLY"
DISPOSITION_QUALIFIED = "QUALIFIED_PENDING_SHORT_CANARY"
DISPOSITION_RESEARCH = "RESEARCH_ONLY_LOCKED"

M72_DEFAULT_POLICY: dict[str, Any] = {
    "policy_version": M72_VERSION,
    "minimum_closed_trades": 100,
    "minimum_history_span_days": 30.0,
    "minimum_profit_factor": 1.30,
    "minimum_win_rate_percent": 30.0,
    "maximum_drawdown_percent": 15.0,
    "minimum_recent_closed_trades": 20,
    "minimum_recent_profit_factor": 1.10,
    "maximum_recent_drawdown_percent": 15.0,
    "maximum_open_positions": 0,
    "minimum_parser_yield_percent": 10.0,
    "sell_only_minimum_events": 5,
    "sell_to_buy_retirement_ratio": 10.0,
    "observe_minimum_buy_events": 5,
    "controlled_helius_maximum_requests": 6,
    "controlled_helius_credit_cap": 600,
    "controlled_helius_retries": 0,
    "desired_new_wallet_candidates": 12,
    "maximum_new_wallet_candidates": 24,
}


class M72DiscoveryRotationError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise M72DiscoveryRotationError(message)


def _integer(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _finite(value: Any, *, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    return result if math.isfinite(result) else float(default)


def _without_integrity(value: dict[str, Any]) -> dict[str, Any]:
    return {name: item for name, item in value.items() if name != "integrity"}


def _zero_safety() -> dict[str, Any]:
    return {
        "network_requests": 0,
        "public_rpc_requests": 0,
        "helius_requests": 0,
        "helius_credits": 0,
        "database_reads": 0,
        "database_writes": 0,
        "backend_posts": 0,
        "jupiter_requests": 0,
        "paper_orders": 0,
        "live_orders": 0,
        "signed_transactions": 0,
        "submitted_transactions": 0,
        "signer_access": False,
        "automatic_discovery_activation": False,
        "automatic_live_activation": False,
        "micro_live_execution_authorized": False,
    }


def validate_policy(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    result = {**M72_DEFAULT_POLICY, **dict(policy or {})}
    _require(result.get("policy_version") == M72_VERSION, "Policy M72 inattesa.")
    _require(_integer(result["minimum_closed_trades"]) == 100, "Gate 100 trade alterato.")
    _require(
        math.isclose(_finite(result["minimum_profit_factor"]), 1.30, abs_tol=1e-12),
        "Profit factor M72 alterato.",
    )
    _require(
        math.isclose(_finite(result["maximum_drawdown_percent"]), 15.0, abs_tol=1e-12),
        "Drawdown M72 alterato.",
    )
    _require(
        _integer(result["controlled_helius_maximum_requests"]) == 6,
        "Cap richieste Helius controllate alterato.",
    )
    _require(
        _integer(result["controlled_helius_credit_cap"]) == 600,
        "Cap crediti Helius controllati alterato.",
    )
    _require(_integer(result["controlled_helius_retries"]) == 0, "Retry Helius != 0.")
    return result


def validate_m67_report(report: dict[str, Any]) -> dict[str, Any]:
    _require(report.get("scope") == M67_M70_SCOPE, "Scope report M67-M70 inatteso.")
    _require(report.get("version") == M67_M70_VERSION, "Versione report M67-M70 inattesa.")
    _require(report.get("evaluation") == "PASS", "Report M67-M70 non PASS.")
    expected = str(dict(report.get("integrity") or {}).get("report_payload_sha256") or "")
    _require(
        len(expected) == 64 and expected == canonical_sha256(_without_integrity(report)),
        "Hash report M67-M70 non valido.",
    )
    safety = dict(report.get("safety") or {})
    for key in (
        "helius_requests",
        "database_writes",
        "backend_posts",
        "jupiter_requests",
        "paper_orders",
        "live_orders",
        "signed_transactions",
        "submitted_transactions",
    ):
        _require(_integer(safety.get(key)) == 0, f"Safety M67-M70 violata: {key}.")
    _require(safety.get("signer_access") is False, "Signer M67-M70 non disarmato.")
    return {
        "report_payload_sha256": expected,
        "source": dict(report.get("source") or {}),
        "summary": dict(report.get("summary") or {}),
        "policy": dict(report.get("policy") or {}),
        "candidate_results": [dict(item) for item in report.get("candidate_results") or []],
    }


def validate_input_bundle(
    m71_report: dict[str, Any],
    updated_m67_report: dict[str, Any],
    updated_rpc_evidence: dict[str, Any],
) -> dict[str, Any]:
    m71 = validate_continuation_report(m71_report)
    m67 = validate_m67_report(updated_m67_report)
    rpc = validate_rpc_evidence(updated_rpc_evidence)
    _require(m71_report.get("scope") == M71_SCOPE, "Scope input M71 inatteso.")
    _require(m71_report.get("version") == M71_VERSION, "Versione input M71 inattesa.")
    _require(
        m67["source"].get("rpc_evidence_sha256") == rpc["rpc_evidence_sha256"],
        "Report M67-M70 non collegato all'evidenza RPC M71.",
    )
    qualification = dict(m71_report.get("updated_qualification") or {})
    _require(
        canonical_sha256(qualification.get("summary") or {})
        == canonical_sha256(m67["summary"]),
        "Summary M71/M67-M70 incoerente.",
    )
    _require(
        canonical_sha256(qualification.get("candidate_results") or [])
        == canonical_sha256(m67["candidate_results"]),
        "Candidate results M71/M67-M70 incoerenti.",
    )
    m71_safety = dict(m71_report.get("safety") or {})
    _require(
        _integer(m71_safety.get("public_rpc_requests"))
        == _integer(rpc["rpc"].get("requests")),
        "Conteggio RPC M71/evidenza incoerente.",
    )
    correction = dict(m71_report.get("strict_official_counter_correction") or {})
    _require(_integer(correction.get("official_realtime_counter")) == 83, "Ufficiali M71 != 83.")
    _require(correction.get("production_counter_mutated") is False, "M71 ha mutato production.")
    return {
        "m71_report_sha256": m71["report_payload_sha256"],
        "m67_report_sha256": m67["report_payload_sha256"],
        "rpc_evidence_sha256": rpc["rpc_evidence_sha256"],
        "m67": m67,
        "rpc": rpc,
    }


def _gate_snapshot(
    metrics: dict[str, Any],
    economic: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    recent = dict(economic.get("recent_metrics") or {})
    checks = {
        "closed_sample": _integer(metrics.get("closed_trade_count"))
        >= _integer(policy["minimum_closed_trades"]),
        "history_span": _finite(metrics.get("history_span_days"))
        >= _finite(policy["minimum_history_span_days"]),
        "net_pnl": _finite(metrics.get("net_pnl_sol")) > 0,
        "profit_factor": _finite(metrics.get("profit_factor"))
        >= _finite(policy["minimum_profit_factor"]),
        "win_rate": _finite(metrics.get("win_rate_percent"))
        >= _finite(policy["minimum_win_rate_percent"]),
        "drawdown": _finite(metrics.get("maximum_drawdown_percent"), default=100.0)
        <= _finite(policy["maximum_drawdown_percent"]),
        "recent_sample": _integer(recent.get("closed_trade_count"))
        >= _integer(policy["minimum_recent_closed_trades"]),
        "recent_profit_factor": _finite(recent.get("profit_factor"))
        >= _finite(policy["minimum_recent_profit_factor"]),
        "recent_drawdown": _finite(recent.get("maximum_drawdown_percent"), default=100.0)
        <= _finite(policy["maximum_recent_drawdown_percent"]),
        "zero_open_positions": _integer(metrics.get("open_positions"))
        <= _integer(policy["maximum_open_positions"]),
    }
    return {"checks": checks, "passed": all(checks.values())}


def classify_active_candidate(
    candidate: dict[str, Any],
    deep_history: dict[str, Any],
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = validate_policy(policy)
    wallet = str(candidate.get("wallet_address") or "")
    activity = dict(candidate.get("activity") or {})
    events = [dict(item) for item in deep_history.get("events") or []]
    sides = Counter(str(item.get("side") or "").upper() for item in events)
    buys = sides["BUY"]
    sells = sides["SELL"]
    transaction_count = _integer(deep_history.get("transaction_count"))
    parsed_count = _integer(deep_history.get("parsed_event_count"), default=len(events))
    parser_yield = parsed_count / max(1, transaction_count) * 100.0
    history_complete = bool(deep_history.get("history_complete"))
    economic = dict(candidate.get("economic_analysis") or {})
    backtest = dict(deep_history.get("backtest") or {})
    metrics = dict(economic.get("metrics") or backtest.get("metrics") or {})
    closed = _integer(metrics.get("closed_trade_count"))
    open_positions = _integer(metrics.get("open_positions"))
    sell_ratio = sells / max(1, buys)
    gate = _gate_snapshot(metrics, economic, resolved)

    if gate["passed"] and history_complete:
        disposition = DISPOSITION_QUALIFIED
        reason = "COMPLETE_HISTORY_ALL_GEN4_ECONOMIC_GATES_PASS"
    elif not history_complete and (
        sells >= _integer(resolved["sell_only_minimum_events"])
        and buys <= 1
        and sell_ratio >= _finite(resolved["sell_to_buy_retirement_ratio"])
    ):
        disposition = DISPOSITION_RETIRE
        reason = "INCOMPLETE_HISTORY_DEFINITIVE_SELL_ONLY_DISTRIBUTION_PATTERN"
    elif (
        not history_complete
        and transaction_count >= 50
        and parser_yield < _finite(resolved["minimum_parser_yield_percent"])
        and closed == 0
    ):
        disposition = DISPOSITION_RETIRE
        reason = "INCOMPLETE_HISTORY_DEFINITIVE_LOW_CANONICAL_PARSER_YIELD"
    elif history_complete and buys == 0 and sells >= 1:
        disposition = DISPOSITION_RETIRE
        reason = "COMPLETE_HISTORY_NON_COPYABLE_SELL_ONLY"
    elif history_complete and closed == 0 and buys >= _integer(
        resolved["observe_minimum_buy_events"]
    ):
        disposition = DISPOSITION_OBSERVE
        reason = "COMPLETE_HISTORY_ZERO_CLOSED_POSITIONS_OBSERVE_ONLY"
    elif history_complete and closed < _integer(resolved["minimum_closed_trades"]):
        disposition = DISPOSITION_OBSERVE if buys > 0 else DISPOSITION_RETIRE
        reason = (
            "COMPLETE_HISTORY_INSUFFICIENT_CLOSED_SAMPLE_NEGATIVE_ECONOMICS"
            if _finite(metrics.get("net_pnl_sol")) <= 0
            or _finite(metrics.get("profit_factor")) < _finite(resolved["minimum_profit_factor"])
            else "COMPLETE_HISTORY_INSUFFICIENT_CLOSED_SAMPLE"
        )
    else:
        disposition = DISPOSITION_RETIRE
        reason = "NO_DEFENSIBLE_PATH_TO_GEN4_QUALIFICATION"

    return {
        "wallet_address": wallet,
        "disposition": disposition,
        "reason": reason,
        "source_status": str(candidate.get("status") or ""),
        "source_reason": str(candidate.get("reason") or ""),
        "history_complete": history_complete,
        "signature_count": _integer(deep_history.get("signature_count")),
        "transaction_count": transaction_count,
        "parsed_event_count": parsed_count,
        "parser_yield_percent": round(parser_yield, 8),
        "buy_events": buys,
        "sell_events": sells,
        "sell_to_buy_ratio": round(sell_ratio, 8),
        "closed_trade_count": closed,
        "open_positions": open_positions,
        "net_pnl_sol": round(_finite(metrics.get("net_pnl_sol")), 9),
        "net_equity_pnl_sol": round(_finite(metrics.get("net_equity_pnl_sol")), 9),
        "profit_factor": round(_finite(metrics.get("profit_factor")), 8),
        "win_rate_percent": round(_finite(metrics.get("win_rate_percent")), 8),
        "maximum_drawdown_percent": round(
            _finite(metrics.get("maximum_drawdown_percent")), 8
        ),
        "history_span_days": round(_finite(metrics.get("history_span_days")), 8),
        "active_days_7d": _integer(activity.get("active_days_7d")),
        "transactions_7d": _integer(activity.get("transactions_7d")),
        "gate_snapshot": gate,
        "promotion_authorized": disposition == DISPOSITION_QUALIFIED,
        "short_canary_required": disposition == DISPOSITION_QUALIFIED,
        "micro_live_execution_authorized": False,
    }


def build_controlled_acquisition_plan(
    *,
    rotation_rows: list[dict[str, Any]],
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = validate_policy(policy)
    qualified = sum(item.get("disposition") == DISPOSITION_QUALIFIED for item in rotation_rows)
    plan: dict[str, Any] = {
        "scope": M72_PLAN_SCOPE,
        "version": M72_VERSION,
        "state": "PREPARED_DISARMED",
        "required_manual_confirmation": M72_FUTURE_HELIUS_CONFIRMATION,
        "execution_authorized": False,
        "execution_performed": False,
        "provider": {
            "lane": "M66_CONTROLLED_HELIUS_NEW_WALLET_DISCOVERY_MANUAL_ONLY",
            "availability": "PREPARED_NOT_CALLED",
            "maximum_requests": _integer(resolved["controlled_helius_maximum_requests"]),
            "credit_cap": _integer(resolved["controlled_helius_credit_cap"]),
            "retries": _integer(resolved["controlled_helius_retries"]),
            "automatic_enhanced_api": "DISABLED_FAIL_CLOSED",
        },
        "inventory_decision": {
            "qualified_wallets": qualified,
            "new_wallet_discovery_required": qualified < 2,
            "desired_new_candidates": _integer(resolved["desired_new_wallet_candidates"]),
            "maximum_new_candidates": _integer(resolved["maximum_new_wallet_candidates"]),
        },
        "candidate_admission": {
            "signature_activity_is_not_economic_proof": True,
            "canonical_parser_required": True,
            "minimum_parser_yield_percent": _finite(
                resolved["minimum_parser_yield_percent"]
            ),
            "sell_only_wallets_rejected": True,
            "complete_history_required_for_final_gate": True,
            "minimum_closed_trades": _integer(resolved["minimum_closed_trades"]),
            "minimum_profit_factor": _finite(resolved["minimum_profit_factor"]),
            "maximum_drawdown_percent": _finite(
                resolved["maximum_drawdown_percent"]
            ),
            "zero_open_positions_required": True,
            "short_realtime_canary_required": True,
            "multi_wallet_independence_required": True,
        },
        "downstream": {
            "new_wallet_intake": "M66_SIGNED_CONTROLLED_DISCOVERY_OUTPUT",
            "economic_analysis": "M71_PUBLIC_RPC_AND_SHA256_CACHE_ZERO_HELIUS",
            "consensus": "TWO_OR_MORE_INDEPENDENT_QUALIFIED_WALLETS",
            "micro_live": "NOT_AUTHORIZED_BY_THIS_PLAN",
        },
        "safety": _zero_safety(),
    }
    plan["integrity"] = {"plan_payload_sha256": canonical_sha256(plan)}
    return plan


def validate_acquisition_plan(plan: dict[str, Any]) -> dict[str, Any]:
    _require(plan.get("scope") == M72_PLAN_SCOPE, "Scope piano M72 inatteso.")
    _require(plan.get("version") == M72_VERSION, "Versione piano M72 inattesa.")
    expected = str(dict(plan.get("integrity") or {}).get("plan_payload_sha256") or "")
    _require(
        len(expected) == 64 and expected == canonical_sha256(_without_integrity(plan)),
        "Hash piano M72 non valido.",
    )
    _require(plan.get("state") == "PREPARED_DISARMED", "Piano M72 armato.")
    _require(plan.get("execution_authorized") is False, "Esecuzione discovery autorizzata.")
    _require(plan.get("execution_performed") is False, "Discovery M72 eseguita.")
    provider = dict(plan.get("provider") or {})
    _require(_integer(provider.get("maximum_requests")) == 6, "Cap richieste piano != 6.")
    _require(_integer(provider.get("credit_cap")) == 600, "Cap crediti piano != 600.")
    _require(_integer(provider.get("retries")) == 0, "Retry piano != 0.")
    safety = dict(plan.get("safety") or {})
    for key in (
        "network_requests",
        "public_rpc_requests",
        "helius_requests",
        "helius_credits",
        "database_reads",
        "database_writes",
        "backend_posts",
        "jupiter_requests",
        "paper_orders",
        "live_orders",
    ):
        _require(_integer(safety.get(key)) == 0, f"Safety piano M72 violata: {key}.")
    return {"plan_payload_sha256": expected}


def build_rotation_report(
    m71_report: dict[str, Any],
    updated_m67_report: dict[str, Any],
    updated_rpc_evidence: dict[str, Any],
    *,
    policy: dict[str, Any] | None = None,
    evaluated_at: datetime | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    bundle = validate_input_bundle(m71_report, updated_m67_report, updated_rpc_evidence)
    resolved = validate_policy(policy)
    deep = bundle["rpc"]["deep_history"]
    active_results = [
        item
        for item in bundle["m67"]["candidate_results"]
        if bool(dict(item.get("activity") or {}).get("deep_history_candidate"))
    ]
    rotation_rows = [
        classify_active_candidate(
            item,
            dict(deep.get(str(item.get("wallet_address") or "")) or {}),
            policy=resolved,
        )
        for item in active_results
    ]
    order = {
        DISPOSITION_QUALIFIED: 0,
        DISPOSITION_OBSERVE: 1,
        DISPOSITION_RETIRE: 2,
    }
    rotation_rows.sort(
        key=lambda item: (
            order.get(str(item.get("disposition")), 9),
            -_integer(item.get("closed_trade_count")),
            str(item.get("wallet_address")),
        )
    )
    acquisition_plan = build_controlled_acquisition_plan(
        rotation_rows=rotation_rows,
        policy=resolved,
    )
    plan_result = validate_acquisition_plan(acquisition_plan)
    counts = Counter(str(item.get("disposition")) for item in rotation_rows)
    research_locked = [
        {
            "wallet_address": str(item.get("wallet_address") or ""),
            "disposition": DISPOSITION_RESEARCH,
            "reason": str(item.get("reason") or ""),
            "m65_status": str(dict(item.get("m65_gate") or {}).get("status") or ""),
            "micro_live_execution_authorized": False,
        }
        for item in bundle["m67"]["candidate_results"]
        if str(dict(item.get("m65_gate") or {}).get("status") or "") == "FAIL_ECONOMIC"
    ]
    report: dict[str, Any] = {
        "evaluation": "PASS",
        "scope": M72_SCOPE,
        "version": M72_VERSION,
        "evaluated_at_utc": (evaluated_at or datetime.now(timezone.utc)).astimezone(
            timezone.utc
        ).isoformat(),
        "inputs": {
            "m71_report_sha256": bundle["m71_report_sha256"],
            "updated_m67_report_sha256": bundle["m67_report_sha256"],
            "updated_rpc_evidence_sha256": bundle["rpc_evidence_sha256"],
            "acquisition_plan_sha256": plan_result["plan_payload_sha256"],
        },
        "policy": resolved,
        "rotation_summary": {
            "active_wallets_reviewed": len(rotation_rows),
            "qualified_pending_short_canary": counts[DISPOSITION_QUALIFIED],
            "observe_only": counts[DISPOSITION_OBSERVE],
            "retired_from_promotion": counts[DISPOSITION_RETIRE],
            "research_only_locked": len(research_locked),
            "existing_inventory_exhausted_for_micro_live": counts[
                DISPOSITION_QUALIFIED
            ]
            == 0,
        },
        "wallet_rotation": rotation_rows,
        "research_only_locked": research_locked,
        "controlled_acquisition_plan": acquisition_plan,
        "decision": {
            "rerun_m71_same_inputs_recommended": False,
            "new_wallet_discovery_required": counts[DISPOSITION_QUALIFIED] < 2,
            "controlled_discovery_execution_authorized": False,
            "next_step": "WAIT_FOR_EXPLICIT_CONTROLLED_DISCOVERY_AUTHORIZATION",
            "short_canary_state": "PREPARED_DISARMED",
            "micro_live_state": "PREPARED_DISARMED",
            "micro_live_execution_authorized": False,
        },
        "official_evidence": {
            "official_realtime_counter": 83,
            "production_counter_mutated": False,
            "recovery_counts_as_realtime_proof": False,
        },
        "safety": _zero_safety(),
    }
    report["integrity"] = {"report_payload_sha256": canonical_sha256(report)}
    return report, acquisition_plan


def validate_rotation_report(report: dict[str, Any]) -> dict[str, Any]:
    _require(report.get("scope") == M72_SCOPE, "Scope report M72 inatteso.")
    _require(report.get("version") == M72_VERSION, "Versione report M72 inattesa.")
    _require(report.get("evaluation") == "PASS", "Report M72 non PASS.")
    expected = str(dict(report.get("integrity") or {}).get("report_payload_sha256") or "")
    _require(
        len(expected) == 64 and expected == canonical_sha256(_without_integrity(report)),
        "Hash report M72 non valido.",
    )
    validate_acquisition_plan(dict(report.get("controlled_acquisition_plan") or {}))
    official = dict(report.get("official_evidence") or {})
    _require(_integer(official.get("official_realtime_counter")) == 83, "Ufficiali M72 != 83.")
    _require(official.get("production_counter_mutated") is False, "M72 ha mutato production.")
    decision = dict(report.get("decision") or {})
    _require(
        decision.get("controlled_discovery_execution_authorized") is False,
        "Discovery M72 autorizzata.",
    )
    _require(
        decision.get("micro_live_execution_authorized") is False,
        "Micro Live M72 autorizzata.",
    )
    safety = dict(report.get("safety") or {})
    for key in (
        "network_requests",
        "public_rpc_requests",
        "helius_requests",
        "helius_credits",
        "database_reads",
        "database_writes",
        "backend_posts",
        "jupiter_requests",
        "paper_orders",
        "live_orders",
    ):
        _require(_integer(safety.get(key)) == 0, f"Safety report M72 violata: {key}.")
    return {"report_payload_sha256": expected}


__all__ = [
    "DISPOSITION_OBSERVE",
    "DISPOSITION_QUALIFIED",
    "DISPOSITION_RESEARCH",
    "DISPOSITION_RETIRE",
    "M72DiscoveryRotationError",
    "M72_DEFAULT_POLICY",
    "M72_FUTURE_HELIUS_CONFIRMATION",
    "M72_PLAN_SCOPE",
    "M72_RUN_CONFIRMATION",
    "M72_SCOPE",
    "M72_VERSION",
    "build_controlled_acquisition_plan",
    "build_rotation_report",
    "classify_active_candidate",
    "validate_acquisition_plan",
    "validate_input_bundle",
    "validate_m67_report",
    "validate_policy",
    "validate_rotation_report",
]
