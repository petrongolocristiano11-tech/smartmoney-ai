from __future__ import annotations

import copy
import math
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from backend.app.services.gen4_closed_trade_readonly_audit_service import (
    canonical_sha256,
)
from backend.app.services.gen4_zero_helius_pre_micro_live_service import (
    M67_M70_SCOPE,
    M67_M70_VERSION,
    M67M70ZeroHeliusError,
    validate_local_snapshot,
    validate_rpc_evidence,
)


M71_VERSION = "canonical-parser-gen4-zero-helius-adaptive-continuation/1"
M71_SCOPE = "M71_ZERO_HELIUS_ADAPTIVE_CONTINUATION_READ_ONLY"
M71_RUN_CONFIRMATION = "RUN_M71_ZERO_HELIUS_ADAPTIVE_CONTINUATION_READ_ONLY"
M71_STRICT_OFFICIAL_FILTER = "CLOSED_WEBHOOK_ENTRY_AND_EXIT_COPYABLE_WITH_PNL"

M71_DEFAULT_POLICY: dict[str, Any] = {
    "policy_version": M71_VERSION,
    "maximum_wallets_per_batch": 4,
    "extension_signature_target": 500,
    "new_candidate_signature_target": 300,
    "public_rpc_request_cap": 1800,
    "public_rpc_maximum_attempts": 4,
    "public_rpc_throttle_seconds": 0.75,
    "minimum_parser_yield_percent": 10.0,
    "sell_only_minimum_events": 10,
    "sell_to_buy_deprioritization_ratio": 10.0,
}


class M71AdaptiveContinuationError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise M71AdaptiveContinuationError(message)


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


def _zero_safety(*, public_rpc_requests: int) -> dict[str, Any]:
    return {
        "network_requests": int(public_rpc_requests),
        "public_rpc_requests": int(public_rpc_requests),
        "helius_requests": 0,
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
    }


def validate_policy(policy: dict[str, Any] | None = None) -> dict[str, Any]:
    result = {**M71_DEFAULT_POLICY, **dict(policy or {})}
    _require(result.get("policy_version") == M71_VERSION, "Policy M71 inattesa.")
    _require(
        1 <= _integer(result.get("maximum_wallets_per_batch")) <= 4,
        "Batch wallet M71 fuori contratto.",
    )
    _require(
        150 <= _integer(result.get("extension_signature_target")) <= 1000,
        "Target firme estensione M71 fuori contratto.",
    )
    _require(
        100 <= _integer(result.get("new_candidate_signature_target")) <= 500,
        "Target firme nuovo candidato M71 fuori contratto.",
    )
    _require(
        300 <= _integer(result.get("public_rpc_request_cap")) <= 2000,
        "Cap RPC M71 fuori contratto.",
    )
    _require(
        1 <= _integer(result.get("public_rpc_maximum_attempts")) <= 4,
        "Retry M71 fuori contratto.",
    )
    _require(
        0.60 <= _finite(result.get("public_rpc_throttle_seconds")) <= 5.0,
        "Throttle M71 fuori contratto.",
    )
    return result


def validate_previous_report(report: dict[str, Any]) -> dict[str, Any]:
    _require(report.get("scope") == M67_M70_SCOPE, "Scope report M67-M70 inatteso.")
    _require(report.get("version") == M67_M70_VERSION, "Versione report M67-M70 inattesa.")
    _require(report.get("evaluation") == "PASS", "Report M67-M70 non PASS.")
    integrity = dict(report.get("integrity") or {})
    expected = str(integrity.get("report_payload_sha256") or "")
    _require(len(expected) == 64, "Hash report M67-M70 assente.")
    _require(
        expected == canonical_sha256(_without_integrity(report)),
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
    _require(
        safety.get("micro_live_execution_authorized") is False,
        "Micro Live M67-M70 non disarmata.",
    )
    _require(
        _integer(safety.get("network_requests"))
        == _integer(safety.get("public_rpc_requests")),
        "Rete M67-M70 diversa dal solo RPC pubblico.",
    )
    return {
        "report_payload_sha256": expected,
        "source": dict(report.get("source") or {}),
        "summary": dict(report.get("summary") or {}),
        "candidate_results": [dict(item) for item in report.get("candidate_results") or []],
    }


def validate_input_bundle(
    snapshot: dict[str, Any],
    rpc_evidence: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    local = validate_local_snapshot(snapshot)
    rpc = validate_rpc_evidence(rpc_evidence)
    previous = validate_previous_report(report)
    source = previous["source"]
    _require(
        source.get("local_snapshot_sha256") == local["snapshot_payload_sha256"],
        "Report M67-M70 non collegato allo snapshot fornito.",
    )
    _require(
        source.get("rpc_evidence_sha256") == rpc["rpc_evidence_sha256"],
        "Report M67-M70 non collegato all'evidenza RPC fornita.",
    )
    _require(
        report.get("policy_sha256") == rpc_evidence.get("policy_sha256"),
        "Policy report/evidenza RPC M67-M70 incoerente.",
    )
    return {
        "snapshot_payload_sha256": local["snapshot_payload_sha256"],
        "rpc_evidence_sha256": rpc["rpc_evidence_sha256"],
        "report_payload_sha256": previous["report_payload_sha256"],
        "candidate_results": previous["candidate_results"],
        "activity": rpc["activity"],
        "deep_history": rpc["deep_history"],
    }


def correct_local_snapshot_official_filter(
    snapshot: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    validate_local_snapshot(snapshot)
    corrected = copy.deepcopy(snapshot)
    corrections: list[dict[str, Any]] = []
    for candidate in corrected.get("candidates") or []:
        m64 = dict(candidate.get("m64_audit") or {})
        copyability = dict(candidate.get("copyability_campaign") or {})
        if not m64 or not copyability:
            continue
        official = _integer(dict(m64.get("official") or {}).get("closed_trade_count"))
        observed = _integer(copyability.get("official_realtime_closed_trades"))
        _require(official == 83, "Il report M64 firmato non certifica 83 ufficiali.")
        _require(observed >= official, "Riepilogo copyability inferiore agli 83 ufficiali.")
        excluded = observed - official
        copyability["source_closed_rows_before_strict_filter"] = observed
        copyability["official_realtime_closed_trades"] = official
        copyability["non_official_closed_rows_excluded"] = excluded
        copyability["official_filter"] = M71_STRICT_OFFICIAL_FILTER
        copyability["m71_strict_filter_reapplied"] = True
        candidate["copyability_campaign"] = copyability
        if excluded:
            corrections.append(
                {
                    "wallet_address": str(candidate.get("wallet_address") or ""),
                    "source_closed_rows": observed,
                    "official_realtime_closed_trades": official,
                    "excluded_non_official_closed_rows": excluded,
                    "reason": "M64_STRICT_OFFICIAL_FILTER_REAPPLIED",
                }
            )
    corrected.setdefault("source", {})["m71_strict_filter_corrections"] = len(corrections)
    corrected.setdefault("contracts", {})["copyability_official_filter"] = (
        M71_STRICT_OFFICIAL_FILTER
    )
    corrected["integrity"] = {
        "snapshot_payload_sha256": canonical_sha256(_without_integrity(corrected))
    }
    validate_local_snapshot(corrected)
    return corrected, corrections


def profile_deep_history(deep: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    events = [dict(item) for item in deep.get("events") or []]
    sides = Counter(str(item.get("side") or "") for item in events)
    buys = sides["BUY"]
    sells = sides["SELL"]
    transactions = _integer(deep.get("transaction_count"))
    parsed = _integer(deep.get("parsed_event_count"), default=len(events))
    parser_yield = parsed / max(1, transactions) * 100.0
    metrics = dict(dict(deep.get("backtest") or {}).get("metrics") or {})
    closed = _integer(metrics.get("closed_trade_count"))
    history_complete = bool(deep.get("history_complete"))
    sell_ratio = sells / max(1, buys)

    if history_complete:
        classification = "COMPLETE_HISTORY_RETAINED"
        selected = False
    elif (
        sells >= _integer(policy["sell_only_minimum_events"])
        and buys <= 1
        and sell_ratio >= _finite(policy["sell_to_buy_deprioritization_ratio"])
        and closed == 0
    ):
        classification = "DEPRIORITIZED_SELL_ONLY_OR_DISTRIBUTION_PATTERN"
        selected = False
    elif (
        transactions >= 50
        and parser_yield < _finite(policy["minimum_parser_yield_percent"])
        and closed == 0
    ):
        classification = "DEPRIORITIZED_LOW_CANONICAL_PARSER_YIELD"
        selected = False
    else:
        classification = "EXTEND_INCOMPLETE_POSITION_HISTORY"
        selected = True

    return {
        "classification": classification,
        "selected_for_continuation": selected,
        "history_complete": history_complete,
        "signature_count": _integer(deep.get("signature_count")),
        "transaction_count": transactions,
        "parsed_event_count": parsed,
        "parser_yield_percent": round(parser_yield, 8),
        "buy_events": buys,
        "sell_events": sells,
        "sell_to_buy_ratio": round(sell_ratio, 8),
        "closed_trade_count": closed,
        "open_positions": _integer(metrics.get("open_positions")),
    }


def build_adaptive_plan(
    previous_report: dict[str, Any],
    previous_rpc_evidence: dict[str, Any],
    *,
    policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resolved = validate_policy(policy)
    previous = validate_previous_report(previous_report)
    rpc = validate_rpc_evidence(previous_rpc_evidence)
    rows: list[dict[str, Any]] = []
    for candidate in previous["candidate_results"]:
        wallet = str(candidate.get("wallet_address") or "")
        activity = dict(rpc["activity"].get(wallet) or {})
        if not activity.get("deep_history_candidate"):
            continue
        deep = dict(rpc["deep_history"].get(wallet) or {})
        if deep:
            profile = profile_deep_history(deep, resolved)
            action = profile["classification"]
            target = _integer(resolved["extension_signature_target"])
            action_rank = 0 if profile["selected_for_continuation"] else 2
        else:
            profile = None
            action = "NEW_ACTIVE_CANDIDATE_DEEP_SCAN"
            target = _integer(resolved["new_candidate_signature_target"])
            action_rank = 1
        rows.append(
            {
                "wallet_address": wallet,
                "action": action,
                "target_signatures": target,
                "transactions_7d": _integer(activity.get("transactions_7d")),
                "transactions_30d": _integer(activity.get("transactions_30d")),
                "active_days_7d": _integer(activity.get("active_days_7d")),
                "previous_deep_profile": profile,
                "eligible_for_batch": action in {
                    "EXTEND_INCOMPLETE_POSITION_HISTORY",
                    "NEW_ACTIVE_CANDIDATE_DEEP_SCAN",
                },
                "_action_rank": action_rank,
            }
        )

    ranked = sorted(
        rows,
        key=lambda item: (
            item["_action_rank"],
            -item["active_days_7d"],
            -item["transactions_7d"],
            item["wallet_address"],
        ),
    )
    selected_wallets = [
        item["wallet_address"]
        for item in ranked
        if item["eligible_for_batch"]
    ][:_integer(resolved["maximum_wallets_per_batch"])]
    for item in rows:
        item["selected_for_batch"] = item["wallet_address"] in selected_wallets
        item.pop("_action_rank", None)
    rows.sort(
        key=lambda item: (
            0 if item["selected_for_batch"] else 1,
            selected_wallets.index(item["wallet_address"])
            if item["wallet_address"] in selected_wallets
            else 999,
            item["wallet_address"],
        )
    )
    plan: dict[str, Any] = {
        "scope": "M71_ZERO_HELIUS_ADAPTIVE_PLAN",
        "version": M71_VERSION,
        "policy": resolved,
        "active_candidate_count": len(rows),
        "selected_wallet_count": len(selected_wallets),
        "selected_wallets": selected_wallets,
        "candidate_actions": rows,
        "contracts": {
            "prior_cache_required": True,
            "helius_requests": 0,
            "database_reads": 0,
            "database_writes": 0,
            "backend_posts": 0,
            "jupiter_requests": 0,
            "micro_live_execution_authorized": False,
        },
    }
    plan["integrity"] = {"plan_payload_sha256": canonical_sha256(plan)}
    return plan


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    _require(plan.get("scope") == "M71_ZERO_HELIUS_ADAPTIVE_PLAN", "Scope piano M71 inatteso.")
    _require(plan.get("version") == M71_VERSION, "Versione piano M71 inattesa.")
    expected = str(dict(plan.get("integrity") or {}).get("plan_payload_sha256") or "")
    _require(
        len(expected) == 64 and expected == canonical_sha256(_without_integrity(plan)),
        "Hash piano M71 non valido.",
    )
    selected = [str(item) for item in plan.get("selected_wallets") or []]
    _require(
        len(selected) == _integer(plan.get("selected_wallet_count")),
        "Conteggio selezione M71 incoerente.",
    )
    _require(len(selected) == len(set(selected)), "Wallet M71 selezionato due volte.")
    return {"plan_payload_sha256": expected, "selected_wallets": selected}


def build_continuation_report(
    *,
    input_bundle: dict[str, Any],
    corrected_snapshot: dict[str, Any],
    corrections: list[dict[str, Any]],
    plan: dict[str, Any],
    updated_rpc_evidence: dict[str, Any],
    updated_m67_report: dict[str, Any],
    previous_deep_history: dict[str, dict[str, Any]],
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    plan_result = validate_plan(plan)
    corrected = validate_local_snapshot(corrected_snapshot)
    updated_rpc = validate_rpc_evidence(updated_rpc_evidence)
    updated_report = validate_previous_report(updated_m67_report)
    source = updated_report["source"]
    _require(
        source.get("local_snapshot_sha256") == corrected["snapshot_payload_sha256"],
        "Report aggiornato non collegato allo snapshot corretto.",
    )
    _require(
        source.get("rpc_evidence_sha256") == updated_rpc["rpc_evidence_sha256"],
        "Report aggiornato non collegato all'evidenza RPC M71.",
    )

    outcomes: list[dict[str, Any]] = []
    for wallet in plan_result["selected_wallets"]:
        before = dict(previous_deep_history.get(wallet) or {})
        after = dict(updated_rpc["deep_history"].get(wallet) or {})
        profile = profile_deep_history(after, dict(plan.get("policy") or {}))
        metrics = dict(dict(after.get("backtest") or {}).get("metrics") or {})
        outcomes.append(
            {
                "wallet_address": wallet,
                "previous_signature_count": _integer(before.get("signature_count")),
                "current_signature_count": _integer(after.get("signature_count")),
                "new_signature_coverage": max(
                    0,
                    _integer(after.get("signature_count"))
                    - _integer(before.get("signature_count")),
                ),
                "history_complete": bool(after.get("history_complete")),
                "signature_limit_reached": bool(after.get("signature_limit_reached")),
                "public_rpc_budget_exhausted": bool(
                    after.get("public_rpc_budget_exhausted")
                ),
                "canonical_profile": profile,
                "gen4_metrics": metrics,
            }
        )

    safety = _zero_safety(
        public_rpc_requests=_integer(updated_rpc["rpc"].get("requests"))
    )
    summary = dict(updated_m67_report.get("summary") or {})
    report: dict[str, Any] = {
        "evaluation": "PASS",
        "scope": M71_SCOPE,
        "version": M71_VERSION,
        "evaluated_at_utc": (evaluated_at or datetime.now(timezone.utc)).astimezone(
            timezone.utc
        ).isoformat(),
        "inputs": {
            "previous_snapshot_sha256": input_bundle["snapshot_payload_sha256"],
            "previous_rpc_evidence_sha256": input_bundle["rpc_evidence_sha256"],
            "previous_report_sha256": input_bundle["report_payload_sha256"],
            "adaptive_plan_sha256": plan_result["plan_payload_sha256"],
        },
        "strict_official_counter_correction": {
            "filter": M71_STRICT_OFFICIAL_FILTER,
            "correction_count": len(corrections),
            "corrections": corrections,
            "production_counter_mutated": False,
            "official_realtime_counter": 83,
        },
        "adaptive_plan": plan,
        "continuation_outcomes": outcomes,
        "updated_qualification": {
            "summary": summary,
            "candidate_results": updated_m67_report.get("candidate_results") or [],
            "selected_wallets": updated_m67_report.get("selected_wallets") or [],
            "multi_wallet_consensus": updated_m67_report.get("multi_wallet_consensus") or {},
        },
        "decision": {
            "qualified_pending_short_canary": _integer(
                summary.get("wallets_qualified_pending_canary")
            ),
            "selected_wallets": _integer(summary.get("selected_wallets")),
            "next_step": (
                "PREPARE_EXPLICIT_SHORT_CANARY_PACKAGE"
                if _integer(summary.get("selected_wallets")) >= 2
                else "CONTINUE_ZERO_HELIUS_RESEARCH_OR_LATER_CONTROLLED_DISCOVERY"
            ),
            "short_canary_state": "PREPARED_DISARMED",
            "micro_live_state": "PREPARED_DISARMED",
            "micro_live_execution_authorized": False,
        },
        "safety": safety,
    }
    report["integrity"] = {"report_payload_sha256": canonical_sha256(report)}
    return report


def validate_continuation_report(report: dict[str, Any]) -> dict[str, Any]:
    _require(report.get("scope") == M71_SCOPE, "Scope report M71 inatteso.")
    _require(report.get("version") == M71_VERSION, "Versione report M71 inattesa.")
    _require(report.get("evaluation") == "PASS", "Report M71 non PASS.")
    expected = str(dict(report.get("integrity") or {}).get("report_payload_sha256") or "")
    _require(
        len(expected) == 64 and expected == canonical_sha256(_without_integrity(report)),
        "Hash report M71 non valido.",
    )
    correction = dict(report.get("strict_official_counter_correction") or {})
    _require(_integer(correction.get("official_realtime_counter")) == 83, "M71 ufficiali != 83.")
    _require(correction.get("production_counter_mutated") is False, "M71 ha mutato production.")
    safety = dict(report.get("safety") or {})
    for key in (
        "helius_requests",
        "database_reads",
        "database_writes",
        "backend_posts",
        "jupiter_requests",
        "paper_orders",
        "live_orders",
        "signed_transactions",
        "submitted_transactions",
    ):
        _require(_integer(safety.get(key)) == 0, f"Safety M71 violata: {key}.")
    _require(safety.get("signer_access") is False, "Signer M71 non disarmato.")
    _require(
        safety.get("micro_live_execution_authorized") is False,
        "Micro Live M71 non disarmata.",
    )
    return {"report_payload_sha256": expected}


__all__ = [
    "M71AdaptiveContinuationError",
    "M71_DEFAULT_POLICY",
    "M71_RUN_CONFIRMATION",
    "M71_SCOPE",
    "M71_STRICT_OFFICIAL_FILTER",
    "M71_VERSION",
    "build_adaptive_plan",
    "build_continuation_report",
    "correct_local_snapshot_official_filter",
    "profile_deep_history",
    "validate_continuation_report",
    "validate_input_bundle",
    "validate_plan",
    "validate_policy",
    "validate_previous_report",
]
