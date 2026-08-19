from __future__ import annotations

import math
from typing import Any

from backend.app.services.gen4_closed_trade_readonly_audit_service import canonical_sha256
from backend.app.services import gen4_zero_helius_pre_micro_live_service as m67

M80_VERSION = "canonical-parser-gen4-targeted-four-wallet-deep-qualification/1"
M80_SCOPE = "M80_TARGETED_FOUR_WALLET_ZERO_HELIUS_DEEP_QUALIFICATION"
M80_CONFIRMATION = "RUN_M80_TARGETED_FOUR_WALLET_ZERO_HELIUS_DEEP_QUALIFICATION"

TARGET_WALLETS: tuple[str, ...] = (
    "TH5KpPyqJ8SBE9Sya7YVzY8217MQGmjrjgG9WusW4M7",
    "6onSjcGDusjeU5phv7pDQS5srQBwNcyrd4ntKmeNBySm",
    "9MctBmGwpYLeubobAGLXAgXc4eUjR71u9pAg9Ep6oW5F",
    "2GFVxYeK7JR9mdNFjbqT1tiZkNaK6R386k6Rb7Bvauov",
)

MAX_SIGNATURES_BY_WALLET: dict[str, int] = {
    TARGET_WALLETS[0]: 1400,
    TARGET_WALLETS[1]: 1400,
    TARGET_WALLETS[2]: 2600,
    TARGET_WALLETS[3]: 700,
}

M80_PUBLIC_RPC_REQUEST_CAP = 6000
M80_PUBLIC_RPC_MAXIMUM_ATTEMPTS = 4
M80_PUBLIC_RPC_THROTTLE_SECONDS = 0.90
M80_SIGNATURE_PAGE_LIMIT = 100
M80_REQUIRED_QUALIFIED_WALLETS = 2


class M80DeepQualificationError(RuntimeError):
    pass


def _finite(value: Any, *, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float(default)
    return result if math.isfinite(result) else float(default)


def _integer(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise M80DeepQualificationError(message)


def build_model_policy(*, maximum_signatures: int) -> dict[str, Any]:
    _require(100 <= int(maximum_signatures) <= 3000, "Profondita firme M80 fuori contratto.")
    # M67 keeps the canonical Gen4 economics. Its historical runner cap remains
    # a model-level legacy value; the M80 process-level cap is enforced by RPC.
    return m67.validate_policy(
        {
            **m67.M67_M70_DEFAULT_POLICY,
            "maximum_deep_wallets": 3,
            "maximum_signatures_per_deep_wallet": int(maximum_signatures),
            "public_rpc_request_cap": 2000,
            "public_rpc_maximum_attempts": M80_PUBLIC_RPC_MAXIMUM_ATTEMPTS,
            "public_rpc_throttle_seconds": M80_PUBLIC_RPC_THROTTLE_SECONDS,
        }
    )


def _m66_candidates(m66_report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    _require(
        m66_report.get("scope") == "M66_CONTROLLED_HELIUS_NEW_WALLET_DISCOVERY",
        "Scope report M66 inatteso.",
    )
    result = {
        str(item.get("wallet_address") or ""): dict(item)
        for item in m66_report.get("candidate_results") or []
        if isinstance(item, dict) and item.get("wallet_address")
    }
    for wallet in TARGET_WALLETS:
        _require(wallet in result, f"Wallet target assente dal report M66: {wallet}.")
    return result


def validate_sources(
    m66_report: dict[str, Any],
    m73_report: dict[str, Any],
    m79_report: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    candidates = _m66_candidates(m66_report)
    _require(
        m73_report.get("scope") == "M73_CONTROLLED_NEW_WALLET_ACQUISITION_AND_QUALIFICATION",
        "Scope report M73 inatteso.",
    )
    _require(m73_report.get("evaluation") == "PASS", "Report M73 non PASS.")
    _require(
        m79_report.get("scope") == "M79_PAID_CANDIDATE_ZERO_HELIUS_ECONOMIC_TRIAGE",
        "Scope report M79 inatteso.",
    )
    _require(m79_report.get("evaluation") == "PASS", "Report M79 non PASS.")

    m73_wallets = {
        str(item.get("wallet_address") or "")
        for item in m73_report.get("candidate_results") or []
        if isinstance(item, dict)
    }
    _require(TARGET_WALLETS[0] in m73_wallets, "TH5 non appartiene al deep M73.")
    _require(TARGET_WALLETS[1] in m73_wallets, "6onS non appartiene al deep M73.")
    _require(TARGET_WALLETS[3] in m73_wallets, "2GFV non appartiene al deep M73.")

    m79_wallets = {
        str(item.get("wallet_address") or "")
        for item in m79_report.get("pass2_ranked") or []
        if isinstance(item, dict)
    }
    _require(TARGET_WALLETS[2] in m79_wallets, "9Mct non appartiene al deep M79.")
    return candidates


def build_candidate_result(
    wallet: str,
    deep_history: dict[str, Any],
    *,
    m66_candidate: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    _require(wallet in TARGET_WALLETS, "Wallet M80 fuori target.")
    _require(str(deep_history.get("wallet_address") or "") == wallet, "Wallet/deep history mismatch.")
    analysis = m67._economic_analysis(dict(deep_history.get("backtest") or {}), policy)  # noqa: SLF001
    metrics = dict(analysis.get("metrics") or {})
    history_complete = bool(deep_history.get("history_complete"))
    gate = bool(analysis.get("economic_gate_passed")) and history_complete
    if gate:
        disposition = "QUALIFIED_PENDING_SHORT_CANARY"
        reason = "M80_FULL_30D_GEN4_GATE_PASS"
    elif not history_complete:
        disposition = "OBSERVE_ONLY"
        reason = "NEEDS_MORE_PUBLIC_RPC_HISTORY"
    else:
        disposition = "RESEARCH_ONLY"
        reason = "COMPLETE_HISTORY_GEN4_GATE_FAIL"

    sample = dict(m66_candidate.get("sample") or {})
    return {
        "wallet_address": wallet,
        "disposition": disposition,
        "reason": reason,
        "history_complete": history_complete,
        "signature_limit_reached": bool(deep_history.get("signature_limit_reached")),
        "public_rpc_budget_exhausted": bool(deep_history.get("public_rpc_budget_exhausted")),
        "signature_count": _integer(deep_history.get("signature_count")),
        "transaction_count": _integer(deep_history.get("transaction_count")),
        "unavailable_signature_count": len(deep_history.get("unavailable_signatures") or []),
        "parsed_event_count": _integer(deep_history.get("parsed_event_count")),
        "m66_observed_wallet_sample": {
            "median_swap_sol": _finite(sample.get("median_swap_sol")),
            "meaningful_swaps": _integer(sample.get("meaningful_swaps")),
            "valid_swaps": _integer(sample.get("valid_swaps")),
            "active_days": _integer(sample.get("active_days")),
            "unique_tokens": _integer(sample.get("unique_tokens")),
        },
        "copy_normalized_model": dict(deep_history.get("backtest", {}).get("model") or {}),
        "economic_analysis": analysis,
        "closed_trade_count": _integer(metrics.get("closed_trade_count")),
        "history_span_days": _finite(metrics.get("history_span_days")),
        "open_positions": _integer(metrics.get("open_positions")),
        "profit_factor": _finite(metrics.get("profit_factor")),
        "net_pnl_sol": _finite(metrics.get("net_pnl_sol")),
        "win_rate_percent": _finite(metrics.get("win_rate_percent")),
        "maximum_drawdown_percent": _finite(metrics.get("maximum_drawdown_percent"), default=100.0),
        "recent_profit_factor": _finite(dict(analysis.get("recent_metrics") or {}).get("profit_factor")),
        "micro_live_authorized": False,
        "short_canary_authorized": False,
    }


def build_final_report(
    *,
    input_hashes: dict[str, str],
    started_at_utc: str,
    completed_at_utc: str,
    results: list[dict[str, Any]],
    delta_cache_sha256: str,
    rpc_stats: dict[str, Any],
) -> dict[str, Any]:
    by_wallet = {str(row.get("wallet_address") or ""): dict(row) for row in results}
    _require(set(by_wallet) == set(TARGET_WALLETS), "Risultati M80 incompleti.")
    ordered = [by_wallet[wallet] for wallet in TARGET_WALLETS]
    qualified = [row["wallet_address"] for row in ordered if row.get("disposition") == "QUALIFIED_PENDING_SHORT_CANARY"]
    payload: dict[str, Any] = {
        "evaluation": "PASS",
        "scope": M80_SCOPE,
        "version": M80_VERSION,
        "started_at_utc": started_at_utc,
        "completed_at_utc": completed_at_utc,
        "inputs": dict(input_hashes),
        "targets": list(TARGET_WALLETS),
        "maximum_signatures_by_wallet": dict(MAX_SIGNATURES_BY_WALLET),
        "candidate_results": ordered,
        "summary": {
            "targets_analyzed": len(ordered),
            "qualified_pending_short_canary": len(qualified),
            "qualified_wallets": qualified,
            "minimum_required_for_m76": M80_REQUIRED_QUALIFIED_WALLETS,
            "m74_minimum_wallet_count_reached": len(qualified) >= M80_REQUIRED_QUALIFIED_WALLETS,
        },
        "public_rpc": {
            **dict(rpc_stats),
            "delta_cache_sha256": delta_cache_sha256,
            "helius_requests": 0,
        },
        "safety": {
            "m66_reexecution": False,
            "helius_requests": 0,
            "helius_credits": 0,
            "database_reads": 0,
            "database_writes": 0,
            "jupiter_requests": 0,
            "paper_orders": 0,
            "live_orders": 0,
            "signer_authorized": False,
            "short_canary_execution_authorized": False,
            "micro_live_execution_authorized": False,
            "official_realtime_counter": 83,
            "official_realtime_counter_mutated": False,
        },
        "next_step": (
            "BUILD_M74_M75_QUALIFICATION_BRIDGE_AND_START_SHORT_CANARY"
            if len(qualified) >= M80_REQUIRED_QUALIFIED_WALLETS
            else "NO_TWO_M74_PASSES_ROTATE_OR_RUN_NEW_DISCOVERY"
        ),
    }
    payload["integrity"] = {"report_payload_sha256": canonical_sha256(payload)}
    return payload


def validate_final_report(report: dict[str, Any]) -> dict[str, Any]:
    _require(report.get("evaluation") == "PASS", "Report M80 non PASS.")
    _require(report.get("scope") == M80_SCOPE, "Scope M80 inatteso.")
    _require(report.get("version") == M80_VERSION, "Versione M80 inattesa.")
    expected = str(dict(report.get("integrity") or {}).get("report_payload_sha256") or "")
    payload = {key: value for key, value in report.items() if key != "integrity"}
    _require(len(expected) == 64 and expected == canonical_sha256(payload), "Hash report M80 non valido.")
    _require(list(report.get("targets") or []) == list(TARGET_WALLETS), "Target M80 alterati.")
    safety = dict(report.get("safety") or {})
    _require(_integer(safety.get("helius_requests")) == 0, "M80 contiene richieste Helius.")
    _require(_integer(safety.get("helius_credits")) == 0, "M80 contiene crediti Helius.")
    _require(_integer(safety.get("live_orders")) == 0, "M80 contiene ordini LIVE.")
    _require(safety.get("signer_authorized") is False, "M80 signer autorizzato.")
    _require(safety.get("micro_live_execution_authorized") is False, "M80 Micro Live autorizzato.")
    return report
