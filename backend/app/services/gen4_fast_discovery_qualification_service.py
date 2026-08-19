from __future__ import annotations

import math
from typing import Any

from backend.app.services.gen4_closed_trade_readonly_audit_service import canonical_sha256
from backend.app.services import gen4_zero_helius_pre_micro_live_service as m67

M81_VERSION = "canonical-parser-gen4-fast-discovery-qualification/1"
M81_SCOPE = "M81_FAST_DISCOVERY_PARALLEL_ECONOMIC_QUALIFICATION"
M81_CONFIRMATION = "RUN_M81_FAST_DISCOVERY_MAX_8600_HELIUS_CREDITS"

M81_SEEDS: tuple[str, str] = (
    "9MctBmGwpYLeubobAGLXAgXc4eUjR71u9pAg9Ep6oW5F",
    "2GFVxYeK7JR9mdNFjbqT1tiZkNaK6R386k6Rb7Bvauov",
)
M81_SEED_TOKENS_PER_LANE = 8
M81_CANDIDATE_HISTORIES_PER_LANE = 34
M81_DISCOVERY_REQUEST_CAP_PER_LANE = 43
M81_DISCOVERY_REQUEST_CAP_TOTAL = 86
M81_DISCOVERY_CREDIT_CAP_TOTAL = 8600
M81_MAX_TRIAGE_CANDIDATES = 30
M81_PASS1_SIGNATURES = 60
M81_PASS2_SIGNATURES = 300
M81_PASS2_WALLETS = 6
M81_PASS3_SIGNATURES = 1200
M81_PASS3_WALLETS = 4
M81_RPC_WORKERS = 3
M81_RPC_THROTTLE_SECONDS_PER_WORKER = 0.30
M81_RPC_MAXIMUM_ATTEMPTS = 3
M81_REQUIRED_QUALIFIED = 2


class M81FastDiscoveryError(RuntimeError):
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
        raise M81FastDiscoveryError(message)


def validate_lineage(
    old_m66: dict[str, Any],
    m79: dict[str, Any],
    m80: dict[str, Any],
) -> set[str]:
    _require(old_m66.get("scope") == "M66_CONTROLLED_HELIUS_NEW_WALLET_DISCOVERY", "Scope M66 inatteso.")
    _require(m79.get("scope") == "M79_PAID_CANDIDATE_ZERO_HELIUS_ECONOMIC_TRIAGE", "Scope M79 inatteso.")
    _require(m79.get("evaluation") == "PASS", "M79 non PASS.")
    _require(m80.get("scope") == "M80_TARGETED_FOUR_WALLET_ZERO_HELIUS_DEEP_QUALIFICATION", "Scope M80 inatteso.")
    _require(m80.get("evaluation") == "PASS", "M80 non PASS.")
    known: set[str] = set()
    for report, field in ((old_m66, "candidate_results"), (m79, "pass1_ranked"), (m80, "candidate_results")):
        for row in report.get(field) or []:
            if isinstance(row, dict) and row.get("wallet_address"):
                known.add(str(row["wallet_address"]))
    known.update(M81_SEEDS)
    return known


def merge_discovery_candidates(reports: list[dict[str, Any]], excluded: set[str]) -> list[dict[str, Any]]:
    by_wallet: dict[str, dict[str, Any]] = {}
    for report in reports:
        _require(report.get("scope") == "M66_CONTROLLED_HELIUS_NEW_WALLET_DISCOVERY", "Scope discovery lane inatteso.")
        for row in report.get("candidate_results") or []:
            if not isinstance(row, dict):
                continue
            wallet = str(row.get("wallet_address") or "")
            if not wallet or wallet in excluded:
                continue
            if row.get("status") != "PRESCREEN_PASS_NEEDS_CACHED_GEN4_BACKTEST":
                continue
            sample = dict(row.get("sample") or {})
            candidate = {
                "wallet_address": wallet,
                "prescreen_score": round(_finite(row.get("prescreen_score")), 4),
                "m66_sample": sample,
                "m66_discovery_evidence": dict(row.get("discovery_evidence") or {}),
            }
            old = by_wallet.get(wallet)
            if old is None or candidate["prescreen_score"] > _finite(old.get("prescreen_score")):
                by_wallet[wallet] = candidate
    ranked = sorted(
        by_wallet.values(),
        key=lambda row: (
            -_finite(row.get("prescreen_score")),
            -_integer(dict(row.get("m66_sample") or {}).get("causal_closed_cycles_observed")),
            -_integer(dict(row.get("m66_sample") or {}).get("unique_tokens")),
            str(row.get("wallet_address") or ""),
        ),
    )
    return ranked[:M81_MAX_TRIAGE_CANDIDATES]


def build_model_policy(maximum_signatures: int) -> dict[str, Any]:
    _require(maximum_signatures in {M81_PASS1_SIGNATURES, M81_PASS2_SIGNATURES, M81_PASS3_SIGNATURES}, "Profondita M81 inattesa.")
    return m67.validate_policy(
        {
            **m67.M67_M70_DEFAULT_POLICY,
            "maximum_deep_wallets": 3,
            "maximum_signatures_per_deep_wallet": int(maximum_signatures),
            "public_rpc_request_cap": 2000,
            "public_rpc_maximum_attempts": M81_RPC_MAXIMUM_ATTEMPTS,
            "public_rpc_throttle_seconds": M81_RPC_THROTTLE_SECONDS_PER_WORKER,
        }
    )


def build_result(candidate: dict[str, Any], deep: dict[str, Any], *, stage: str, maximum_signatures: int) -> dict[str, Any]:
    wallet = str(candidate.get("wallet_address") or "")
    _require(wallet == str(deep.get("wallet_address") or ""), "Wallet/deep mismatch M81.")
    policy = build_model_policy(maximum_signatures)
    analysis = m67._economic_analysis(dict(deep.get("backtest") or {}), policy)  # noqa: SLF001
    metrics = dict(analysis.get("metrics") or {})
    recent = dict(analysis.get("recent_metrics") or {})
    history_complete = bool(deep.get("history_complete"))
    gate = bool(analysis.get("economic_gate_passed")) and history_complete
    sample = dict(candidate.get("m66_sample") or {})
    if gate:
        disposition = "QUALIFIED_PENDING_SHORT_CANARY"
    elif history_complete:
        disposition = "RESEARCH_ONLY"
    else:
        disposition = "OBSERVE_ONLY"
    return {
        "wallet_address": wallet,
        "stage": stage,
        "maximum_signatures": maximum_signatures,
        "disposition": disposition,
        "history_complete": history_complete,
        "signature_limit_reached": bool(deep.get("signature_limit_reached")),
        "public_rpc_budget_exhausted": bool(deep.get("public_rpc_budget_exhausted")),
        "signature_count": _integer(deep.get("signature_count")),
        "transaction_count": _integer(deep.get("transaction_count")),
        "unavailable_signature_count": len(deep.get("unavailable_signatures") or []),
        "parsed_event_count": _integer(deep.get("parsed_event_count")),
        "prescreen_score": round(_finite(candidate.get("prescreen_score")), 4),
        "m66_observed_wallet_sample": {
            "median_swap_sol": _finite(sample.get("median_swap_sol")),
            "meaningful_swaps": _integer(sample.get("meaningful_swaps")),
            "valid_swaps": _integer(sample.get("valid_swaps")),
            "active_days": _integer(sample.get("active_days")),
            "unique_tokens": _integer(sample.get("unique_tokens")),
        },
        "copy_normalized_model": dict(deep.get("backtest", {}).get("model") or {}),
        "economic_analysis": analysis,
        "closed_trade_count": _integer(metrics.get("closed_trade_count")),
        "history_span_days": _finite(metrics.get("history_span_days")),
        "open_positions": _integer(metrics.get("open_positions")),
        "profit_factor": _finite(metrics.get("profit_factor")),
        "net_pnl_sol": _finite(metrics.get("net_pnl_sol")),
        "win_rate_percent": _finite(metrics.get("win_rate_percent")),
        "maximum_drawdown_percent": _finite(metrics.get("maximum_drawdown_percent"), default=100.0),
        "recent_profit_factor": _finite(recent.get("profit_factor")),
        "recent_net_pnl_sol": _finite(recent.get("net_pnl_sol")),
        "economic_score": _finite(analysis.get("economic_score"), default=-1.0),
        "failure_reasons": list(analysis.get("failure_reasons") or []),
        "short_canary_authorized": False,
        "micro_live_authorized": False,
    }


def rank_results(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    def key(row: dict[str, Any]) -> tuple[Any, ...]:
        qualified = row.get("disposition") == "QUALIFIED_PENDING_SHORT_CANARY"
        metrics_ok = (
            _finite(row.get("net_pnl_sol")) > 0
            and _finite(row.get("profit_factor")) >= 1.10
            and _finite(row.get("maximum_drawdown_percent"), default=100.0) <= 22.0
            and _finite(row.get("win_rate_percent")) >= 30.0
        )
        return (
            -int(qualified),
            -int(metrics_ok),
            -_finite(row.get("economic_score"), default=-1.0),
            -min(_integer(row.get("closed_trade_count")), 100),
            -min(_finite(row.get("profit_factor")), 4.0),
            _finite(row.get("maximum_drawdown_percent"), default=100.0),
            -_finite(row.get("recent_profit_factor")),
            -_finite(row.get("net_pnl_sol")),
            -_finite(row.get("prescreen_score")),
            str(row.get("wallet_address") or ""),
        )
    return sorted([dict(row) for row in rows], key=key)


def stage_result_needs_retry(row: dict[str, Any] | None) -> bool:
    return isinstance(row, dict) and row.get("disposition") == "RPC_RETRY_REQUIRED"


def pass2_eligible(row: dict[str, Any]) -> bool:
    if row.get("disposition") == "QUALIFIED_PENDING_SHORT_CANARY":
        return False
    return (
        _integer(row.get("closed_trade_count")) >= 8
        and _finite(row.get("net_pnl_sol")) > 0
        and _finite(row.get("profit_factor")) >= 1.05
        and _finite(row.get("maximum_drawdown_percent"), default=100.0) <= 25.0
        and _finite(row.get("win_rate_percent")) >= 25.0
    )


def pass3_eligible(row: dict[str, Any]) -> bool:
    if row.get("disposition") == "QUALIFIED_PENDING_SHORT_CANARY":
        return False
    if bool(row.get("history_complete")):
        return False
    return (
        _integer(row.get("closed_trade_count")) >= 20
        and _finite(row.get("net_pnl_sol")) > 0
        and _finite(row.get("profit_factor")) >= 1.22
        and _finite(row.get("maximum_drawdown_percent"), default=100.0) <= 18.0
        and _finite(row.get("win_rate_percent")) >= 30.0
        and _finite(row.get("recent_profit_factor")) >= 1.05
    )


def select_pass2(rows: list[dict[str, Any]]) -> list[str]:
    eligible = [row for row in rank_results(rows) if pass2_eligible(row)]
    return [str(row["wallet_address"]) for row in eligible[:M81_PASS2_WALLETS]]


def select_pass3(rows: list[dict[str, Any]]) -> list[str]:
    eligible = [row for row in rank_results(rows) if pass3_eligible(row)]
    return [str(row["wallet_address"]) for row in eligible[:M81_PASS3_WALLETS]]


def build_final_report(
    *,
    input_hashes: dict[str, str],
    started_at_utc: str,
    completed_at_utc: str,
    discovery_lanes: list[dict[str, Any]],
    discovery_requests: int,
    discovery_credit_reserved_maximum: int,
    candidates: list[dict[str, Any]],
    final_results: list[dict[str, Any]],
    public_rpc_stats: dict[str, Any],
    public_cache_sha256: str,
    early_stop: bool,
) -> dict[str, Any]:
    ranked = rank_results(final_results)
    qualified = [str(row["wallet_address"]) for row in ranked if row.get("disposition") == "QUALIFIED_PENDING_SHORT_CANARY"]
    rpc_retry_wallets = [str(row["wallet_address"]) for row in ranked if stage_result_needs_retry(row)]
    payload: dict[str, Any] = {
        "evaluation": "PASS",
        "scope": M81_SCOPE,
        "version": M81_VERSION,
        "started_at_utc": started_at_utc,
        "completed_at_utc": completed_at_utc,
        "inputs": dict(input_hashes),
        "discovery": {
            "seeds": list(M81_SEEDS),
            "lanes": discovery_lanes,
            "maximum_enhanced_requests": M81_DISCOVERY_REQUEST_CAP_TOTAL,
            "maximum_enhanced_credits": M81_DISCOVERY_CREDIT_CAP_TOTAL,
            "enhanced_requests_executed": int(discovery_requests),
            "enhanced_credits_reserved_maximum": int(discovery_credit_reserved_maximum),
            "candidate_count_for_economic_triage": len(candidates),
        },
        "parallel_economic_qualification": {
            "workers": M81_RPC_WORKERS,
            "per_worker_throttle_seconds": M81_RPC_THROTTLE_SECONDS_PER_WORKER,
            "pass1_signatures": M81_PASS1_SIGNATURES,
            "pass2_signatures": M81_PASS2_SIGNATURES,
            "pass3_signatures": M81_PASS3_SIGNATURES,
            "early_stop_after_qualified_wallets": M81_REQUIRED_QUALIFIED,
            "early_stop_triggered": bool(early_stop),
        },
        "candidate_results": ranked,
        "summary": {
            "qualified_pending_short_canary": len(qualified),
            "qualified_wallets": qualified,
            "m74_minimum_two_wallets_reached": len(qualified) >= M81_REQUIRED_QUALIFIED,
            "rpc_retry_required": len(rpc_retry_wallets),
            "rpc_retry_wallets": rpc_retry_wallets,
        },
        "public_rpc": {**dict(public_rpc_stats), "cache_sha256": public_cache_sha256},
        "safety": {
            "automatic_discovery_rearm": False,
            "database_candidate_writes": 0,
            "backend_posts": 0,
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
            "START_M75_SHORT_REALTIME_CANARY"
            if len(qualified) >= M81_REQUIRED_QUALIFIED
            else (
                "RERUN_M81_PUBLIC_RPC_ONLY_NO_HELIUS_RESPEND"
                if rpc_retry_wallets
                else "M81_NO_TWO_M74_PASSES_REVIEW_NEXT_DISCOVERY_LANE"
            )
        ),
    }
    payload["integrity"] = {"report_payload_sha256": canonical_sha256(payload)}
    return payload


def validate_final_report(report: dict[str, Any]) -> dict[str, Any]:
    _require(report.get("evaluation") == "PASS", "Report M81 non PASS.")
    _require(report.get("scope") == M81_SCOPE, "Scope M81 inatteso.")
    _require(report.get("version") == M81_VERSION, "Versione M81 inattesa.")
    expected = str(dict(report.get("integrity") or {}).get("report_payload_sha256") or "")
    payload = {k: v for k, v in report.items() if k != "integrity"}
    _require(len(expected) == 64 and expected == canonical_sha256(payload), "Hash report M81 non valido.")
    safety = dict(report.get("safety") or {})
    _require(_integer(safety.get("live_orders")) == 0, "M81 contiene LIVE.")
    _require(safety.get("signer_authorized") is False, "M81 signer autorizzato.")
    _require(safety.get("micro_live_execution_authorized") is False, "M81 Micro Live autorizzato.")
    discovery = dict(report.get("discovery") or {})
    _require(_integer(discovery.get("enhanced_requests_executed")) <= M81_DISCOVERY_REQUEST_CAP_TOTAL, "Cap Helius M81 superato.")
    _require(_integer(discovery.get("enhanced_credits_reserved_maximum")) <= M81_DISCOVERY_CREDIT_CAP_TOTAL, "Cap crediti M81 superato.")
    return report
