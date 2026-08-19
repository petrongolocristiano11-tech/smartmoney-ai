from __future__ import annotations

import math
from typing import Any

from backend.app.services.gen4_closed_trade_readonly_audit_service import canonical_sha256
from backend.app.services import gen4_zero_helius_pre_micro_live_service as m67


M79_VERSION = "canonical-parser-gen4-paid-candidate-zero-helius-triage/1"
M79_SCOPE = "M79_PAID_CANDIDATE_ZERO_HELIUS_ECONOMIC_TRIAGE"
M79_CONFIRMATION = "RUN_M79_PAID_CANDIDATE_ZERO_HELIUS_TRIAGE"

M79_EXPECTED_PAID_PRESCREEN_PASS = 27
M79_EXPECTED_ALREADY_DEEP = 6
M79_EXPECTED_REMAINING = 21
M79_EXPECTED_REMAINING_SET_SHA256 = (
    "6ad613fba2c8f5253d17f914786fe23208ffb5d3c4d7cfe13bbe1ee467c7822c"
)

M79_PASS1_SIGNATURES = 60
M79_PASS2_SIGNATURES = 150
M79_PASS2_WALLETS = 8
M79_FINAL_PRIORITY_WALLETS = 6
M79_PUBLIC_RPC_REQUEST_CAP = 2600
M79_PUBLIC_RPC_MAXIMUM_ATTEMPTS = 4
M79_PUBLIC_RPC_THROTTLE_SECONDS = 0.90
M79_SIGNATURE_PAGE_LIMIT = 100

# Existing M74/M78 preliminary economics: used only to rank which paid candidates
# deserve deeper evidence. M79 never promotes a wallet from these preliminary values.
M79_PRELIMINARY_MINIMUM_CLOSED_TRADES = 40
M79_PRELIMINARY_MINIMUM_PROFIT_FACTOR = 1.15
M79_PRELIMINARY_MAXIMUM_DRAWDOWN_PERCENT = 20.0
M79_MINIMUM_WIN_RATE_PERCENT = 30.0
M79_MINIMUM_RECENT_CLOSED_TRADES = 20
M79_MINIMUM_RECENT_PROFIT_FACTOR = 1.10
M79_MINIMUM_UNIQUE_TOKENS = 10
M79_MAXIMUM_TOKEN_CONCENTRATION_PERCENT = 25.0
M79_MINIMUM_TRANSACTION_COMPLETENESS_PERCENT = 90.0


class M79EconomicTriageError(RuntimeError):
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
        raise M79EconomicTriageError(message)


def extract_paid_remaining_candidates(
    m66_report: dict[str, Any],
    m73_report: dict[str, Any],
) -> list[dict[str, Any]]:
    _require(
        str(m66_report.get("scope") or "")
        == "M66_CONTROLLED_HELIUS_NEW_WALLET_DISCOVERY",
        "Scope M66 inatteso.",
    )
    _require(
        str(m73_report.get("scope") or "")
        == "M73_CONTROLLED_NEW_WALLET_ACQUISITION_AND_QUALIFICATION",
        "Scope M73 inatteso.",
    )
    _require(m73_report.get("evaluation") == "PASS", "Report M73 non PASS.")

    m66_candidates = [
        dict(item)
        for item in m66_report.get("candidate_results") or []
        if isinstance(item, dict)
        and item.get("status") == "PRESCREEN_PASS_NEEDS_CACHED_GEN4_BACKTEST"
    ]
    _require(
        len(m66_candidates) == M79_EXPECTED_PAID_PRESCREEN_PASS,
        "Numero candidati M66 prescreen-pass inatteso.",
    )

    already_deep = {
        str(item.get("wallet_address") or "")
        for item in m73_report.get("candidate_results") or []
        if isinstance(item, dict) and item.get("wallet_address")
    }
    _require(
        len(already_deep) == M79_EXPECTED_ALREADY_DEEP,
        "Numero wallet M73 gia deep inatteso.",
    )

    remaining = [
        {
            "wallet_address": str(item.get("wallet_address") or ""),
            "prescreen_score": round(_finite(item.get("prescreen_score")), 4),
            "m66_sample": dict(item.get("sample") or {}),
            "m66_discovery_evidence": dict(item.get("discovery_evidence") or {}),
        }
        for item in m66_candidates
        if str(item.get("wallet_address") or "") not in already_deep
    ]
    _require(len(remaining) == M79_EXPECTED_REMAINING, "Numero candidati M79 inatteso.")
    wallet_set = sorted(item["wallet_address"] for item in remaining)
    _require(
        canonical_sha256(wallet_set) == M79_EXPECTED_REMAINING_SET_SHA256,
        "Set candidati M79 non coincide con i 21 gia pagati.",
    )
    return remaining


def build_model_policy(*, maximum_signatures: int) -> dict[str, Any]:
    _require(
        maximum_signatures in {M79_PASS1_SIGNATURES, M79_PASS2_SIGNATURES},
        "Numero firme M79 fuori contratto.",
    )
    # Keep the M67 model contract unchanged. The real M79 RPC cap is enforced
    # independently by CachedBudgetedPublicRpc in the runner.
    return m67.validate_policy(
        {
            **m67.M67_M70_DEFAULT_POLICY,
            "maximum_deep_wallets": 3,
            "maximum_signatures_per_deep_wallet": maximum_signatures,
            "public_rpc_request_cap": 2000,
            "public_rpc_maximum_attempts": M79_PUBLIC_RPC_MAXIMUM_ATTEMPTS,
            "public_rpc_throttle_seconds": M79_PUBLIC_RPC_THROTTLE_SECONDS,
        }
    )


def _core_checks(
    analysis: dict[str, Any],
    *,
    transaction_completeness_percent: float,
) -> dict[str, bool]:
    metrics = dict(analysis.get("metrics") or {})
    recent = dict(analysis.get("recent_metrics") or {})
    return {
        "preliminary_closed_sample": _integer(metrics.get("closed_trade_count"))
        >= M79_PRELIMINARY_MINIMUM_CLOSED_TRADES,
        "net_pnl": _finite(metrics.get("net_pnl_sol")) > 0,
        "preliminary_profit_factor": _finite(metrics.get("profit_factor"))
        >= M79_PRELIMINARY_MINIMUM_PROFIT_FACTOR,
        "win_rate": _finite(metrics.get("win_rate_percent"))
        >= M79_MINIMUM_WIN_RATE_PERCENT,
        "preliminary_drawdown": _finite(
            metrics.get("maximum_drawdown_percent"), default=100.0
        )
        <= M79_PRELIMINARY_MAXIMUM_DRAWDOWN_PERCENT,
        "recent_sample": _integer(recent.get("closed_trade_count"))
        >= M79_MINIMUM_RECENT_CLOSED_TRADES,
        "recent_pnl": _finite(recent.get("net_pnl_sol")) > 0,
        "recent_profit_factor": _finite(recent.get("profit_factor"))
        >= M79_MINIMUM_RECENT_PROFIT_FACTOR,
        "positive_without_best": _finite(
            analysis.get("net_pnl_without_best_trade_sol")
        )
        > 0,
        "unique_tokens": _integer(metrics.get("unique_token_count"))
        >= M79_MINIMUM_UNIQUE_TOKENS,
        "token_concentration": _finite(
            analysis.get("top_token_concentration_percent"), default=100.0
        )
        <= M79_MAXIMUM_TOKEN_CONCENTRATION_PERCENT,
        "transaction_completeness": transaction_completeness_percent
        >= M79_MINIMUM_TRANSACTION_COMPLETENESS_PERCENT,
    }


def _priority_tier(checks: dict[str, bool], analysis: dict[str, Any]) -> tuple[int, str]:
    metrics = dict(analysis.get("metrics") or {})
    closed = _integer(metrics.get("closed_trade_count"))
    pf = _finite(metrics.get("profit_factor"))
    net = _finite(metrics.get("net_pnl_sol"))
    dd = _finite(metrics.get("maximum_drawdown_percent"), default=100.0)
    recent = dict(analysis.get("recent_metrics") or {})
    recent_pf = _finite(recent.get("profit_factor"))
    recent_net = _finite(recent.get("net_pnl_sol"))
    without_best = _finite(analysis.get("net_pnl_without_best_trade_sol"))

    robust = (
        closed >= M79_MINIMUM_RECENT_CLOSED_TRADES
        and net > 0
        and pf >= M79_PRELIMINARY_MINIMUM_PROFIT_FACTOR
        and dd <= M79_PRELIMINARY_MAXIMUM_DRAWDOWN_PERCENT
        and recent_net > 0
        and recent_pf >= M79_MINIMUM_RECENT_PROFIT_FACTOR
        and without_best > 0
        and checks.get("win_rate", False)
        and checks.get("transaction_completeness", False)
    )
    if robust:
        return 3, "PRIORITY_A_ROBUST_PRELIMINARY"

    promising = (
        closed >= 10
        and net > 0
        and pf >= 1.0
        and dd <= 25.0
        and checks.get("transaction_completeness", False)
    )
    if promising:
        return 2, "PRIORITY_B_PROMISING_INCOMPLETE"

    mixed = (
        closed > 0
        and (net > 0 or pf >= 1.0)
        and checks.get("transaction_completeness", False)
    )
    if mixed:
        return 1, "PRIORITY_C_MIXED"
    return 0, "DEPRIORITIZE_PRELIMINARY"


def build_triage_result(
    candidate: dict[str, Any],
    deep_history: dict[str, Any],
    *,
    pass_name: str,
    policy: dict[str, Any],
) -> dict[str, Any]:
    wallet = str(candidate.get("wallet_address") or "")
    _require(wallet == str(deep_history.get("wallet_address") or ""), "Wallet mismatch M79.")
    backtest = dict(deep_history.get("backtest") or {})
    analysis = m67._economic_analysis(backtest, policy)  # noqa: SLF001
    signatures = _integer(deep_history.get("signature_count"))
    transactions = _integer(deep_history.get("transaction_count"))
    completeness = (transactions / signatures * 100.0) if signatures else 0.0
    parser_yield = (
        _integer(deep_history.get("parsed_event_count")) / max(1, transactions) * 100.0
    )
    checks = _core_checks(
        analysis,
        transaction_completeness_percent=completeness,
    )
    tier, label = _priority_tier(checks, analysis)
    metrics = dict(analysis.get("metrics") or {})
    recent = dict(analysis.get("recent_metrics") or {})
    core_pass_count = sum(bool(value) for value in checks.values())

    return {
        "wallet_address": wallet,
        "pass": pass_name,
        "prescreen_score": round(_finite(candidate.get("prescreen_score")), 4),
        "priority_tier": tier,
        "priority_label": label,
        "core_checks_passed": core_pass_count,
        "core_checks_total": len(checks),
        "core_checks": checks,
        "signature_count": signatures,
        "transaction_count": transactions,
        "transaction_completeness_percent": round(completeness, 4),
        "parsed_event_count": _integer(deep_history.get("parsed_event_count")),
        "parser_yield_events_per_transaction_percent": round(parser_yield, 4),
        "history_complete": bool(deep_history.get("history_complete")),
        "signature_limit_reached": bool(deep_history.get("signature_limit_reached")),
        "public_rpc_budget_exhausted": bool(
            deep_history.get("public_rpc_budget_exhausted")
        ),
        "unavailable_signature_count": len(
            list(deep_history.get("unavailable_signatures") or [])
        ),
        "metrics": metrics,
        "recent_metrics": recent,
        "net_pnl_without_best_trade_sol": analysis.get(
            "net_pnl_without_best_trade_sol"
        ),
        "top_token_concentration_percent": analysis.get(
            "top_token_concentration_percent"
        ),
        "stability_windows": list(analysis.get("stability_windows") or []),
        "full_gen4_gate_checks": dict(analysis.get("checks") or {}),
        "full_gen4_gate_failure_reasons": list(analysis.get("failure_reasons") or []),
        "full_gen4_gate_passed": bool(analysis.get("economic_gate_passed")),
        "economic_score": analysis.get("economic_score"),
        "m66_sample": dict(candidate.get("m66_sample") or {}),
        "promotion_authorized": False,
        "short_canary_authorized": False,
        "micro_live_authorized": False,
    }


def priority_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    metrics = dict(item.get("metrics") or {})
    recent = dict(item.get("recent_metrics") or {})
    return (
        _integer(item.get("priority_tier")),
        _integer(item.get("core_checks_passed")),
        _finite(item.get("transaction_completeness_percent")),
        min(_integer(metrics.get("closed_trade_count")), M79_PRELIMINARY_MINIMUM_CLOSED_TRADES),
        min(_finite(metrics.get("profit_factor")), 3.0),
        min(_finite(recent.get("profit_factor")), 3.0),
        _finite(item.get("net_pnl_without_best_trade_sol")),
        -_finite(metrics.get("maximum_drawdown_percent"), default=100.0),
        _finite(item.get("economic_score")),
        _finite(item.get("prescreen_score")),
        str(item.get("wallet_address") or ""),
    )


def rank_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked = sorted((dict(item) for item in results), key=priority_sort_key, reverse=True)
    for index, item in enumerate(ranked, start=1):
        item["economic_triage_rank"] = index
    return ranked


def select_pass2_wallets(pass1_results: list[dict[str, Any]]) -> list[str]:
    ranked = rank_results(pass1_results)
    selected = [str(item.get("wallet_address") or "") for item in ranked[:M79_PASS2_WALLETS]]
    _require(len(selected) == M79_PASS2_WALLETS, "Selezione pass2 M79 incompleta.")
    _require(len(set(selected)) == len(selected), "Duplicati selezione pass2 M79.")
    return selected


def existing_m73_reference(m73_report: dict[str, Any]) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for item in m73_report.get("candidate_results") or []:
        if not isinstance(item, dict):
            continue
        analysis = dict(item.get("economic_analysis") or {})
        metrics = dict(analysis.get("metrics") or {})
        recent = dict(analysis.get("recent_metrics") or {})
        references.append(
            {
                "wallet_address": str(item.get("wallet_address") or ""),
                "prescreen_score": item.get("prescreen_score"),
                "disposition": item.get("disposition"),
                "reason": item.get("reason"),
                "closed_trade_count": metrics.get("closed_trade_count"),
                "net_pnl_sol": metrics.get("net_pnl_sol"),
                "profit_factor": metrics.get("profit_factor"),
                "win_rate_percent": metrics.get("win_rate_percent"),
                "maximum_drawdown_percent": metrics.get("maximum_drawdown_percent"),
                "recent_profit_factor": recent.get("profit_factor"),
                "recent_net_pnl_sol": recent.get("net_pnl_sol"),
                "history_span_days": metrics.get("history_span_days"),
                "open_positions": metrics.get("open_positions"),
                "economic_score": analysis.get("economic_score"),
                "failure_reasons": list(analysis.get("failure_reasons") or []),
                "history_complete": bool(item.get("history_complete")),
            }
        )
    return references


def build_final_report(
    *,
    m66_report_sha256: str,
    m73_report_sha256: str,
    base_cache_sha256: str,
    delta_cache_sha256: str,
    started_at_utc: str,
    completed_at_utc: str,
    pass1_results: list[dict[str, Any]],
    pass2_results: list[dict[str, Any]],
    pass2_selected: list[str],
    m73_report: dict[str, Any],
    rpc_stats: dict[str, Any],
) -> dict[str, Any]:
    _require(len(pass1_results) == M79_EXPECTED_REMAINING, "Pass1 M79 incompleto.")
    _require(len(pass2_results) == M79_PASS2_WALLETS, "Pass2 M79 incompleto.")
    _require(len(pass2_selected) == M79_PASS2_WALLETS, "Selezione pass2 incoerente.")
    ranked_pass1 = rank_results(pass1_results)
    ranked_pass2 = rank_results(pass2_results)
    final_priority = [
        str(item.get("wallet_address") or "")
        for item in ranked_pass2[:M79_FINAL_PRIORITY_WALLETS]
    ]
    report = {
        "version": M79_VERSION,
        "scope": M79_SCOPE,
        "evaluation": "PASS",
        "started_at_utc": started_at_utc,
        "completed_at_utc": completed_at_utc,
        "inputs": {
            "m66_report_sha256": m66_report_sha256,
            "m73_report_sha256": m73_report_sha256,
            "m73_public_rpc_base_cache_sha256": base_cache_sha256,
            "remaining_paid_candidate_set_sha256": M79_EXPECTED_REMAINING_SET_SHA256,
        },
        "strategy": {
            "helius_discovery_reexecuted": False,
            "paid_candidates_reused": M79_EXPECTED_REMAINING,
            "pass1_wallets": M79_EXPECTED_REMAINING,
            "pass1_signatures_per_wallet": M79_PASS1_SIGNATURES,
            "pass2_wallets": M79_PASS2_WALLETS,
            "pass2_signatures_per_wallet": M79_PASS2_SIGNATURES,
            "final_priority_wallets": M79_FINAL_PRIORITY_WALLETS,
            "ranking_uses_economics_before_prescreen_score": True,
            "prescreen_score_is_tiebreaker_only": True,
            "promotion_from_triage_allowed": False,
        },
        "preliminary_thresholds": {
            "minimum_closed_trades": M79_PRELIMINARY_MINIMUM_CLOSED_TRADES,
            "minimum_profit_factor": M79_PRELIMINARY_MINIMUM_PROFIT_FACTOR,
            "maximum_drawdown_percent": M79_PRELIMINARY_MAXIMUM_DRAWDOWN_PERCENT,
            "minimum_win_rate_percent": M79_MINIMUM_WIN_RATE_PERCENT,
            "minimum_recent_closed_trades": M79_MINIMUM_RECENT_CLOSED_TRADES,
            "minimum_recent_profit_factor": M79_MINIMUM_RECENT_PROFIT_FACTOR,
            "minimum_unique_tokens": M79_MINIMUM_UNIQUE_TOKENS,
            "maximum_token_concentration_percent": M79_MAXIMUM_TOKEN_CONCENTRATION_PERCENT,
            "minimum_transaction_completeness_percent": M79_MINIMUM_TRANSACTION_COMPLETENESS_PERCENT,
        },
        "pass1_ranked": ranked_pass1,
        "pass2_selected": list(pass2_selected),
        "pass2_ranked": ranked_pass2,
        "recommended_next_deep_wallets": final_priority,
        "existing_m73_deep_reference": existing_m73_reference(m73_report),
        "public_rpc": {
            **dict(rpc_stats),
            "base_cache_sha256": base_cache_sha256,
            "delta_cache_sha256": delta_cache_sha256,
        },
        "safety": {
            "helius_requests": 0,
            "helius_credits": 0,
            "database_reads": 0,
            "database_writes": 0,
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
    }
    report["integrity"] = {
        "report_payload_sha256": canonical_sha256(report),
    }
    return report


def validate_final_report(report: dict[str, Any]) -> dict[str, Any]:
    _require(report.get("version") == M79_VERSION, "Versione report M79 inattesa.")
    _require(report.get("scope") == M79_SCOPE, "Scope report M79 inatteso.")
    _require(report.get("evaluation") == "PASS", "Report M79 non PASS.")
    safety = dict(report.get("safety") or {})
    _require(_integer(safety.get("helius_requests")) == 0, "M79 ha usato Helius.")
    _require(_integer(safety.get("helius_credits")) == 0, "M79 ha usato crediti Helius.")
    _require(_integer(safety.get("database_writes")) == 0, "M79 ha scritto DB.")
    _require(_integer(safety.get("live_orders")) == 0, "M79 ha creato ordini LIVE.")
    _require(safety.get("signer_authorized") is False, "M79 signer autorizzato.")
    _require(
        safety.get("micro_live_execution_authorized") is False,
        "M79 Micro Live autorizzato.",
    )
    _require(
        len(list(report.get("pass1_ranked") or [])) == M79_EXPECTED_REMAINING,
        "Pass1 report M79 incompleto.",
    )
    _require(
        len(list(report.get("pass2_ranked") or [])) == M79_PASS2_WALLETS,
        "Pass2 report M79 incompleto.",
    )
    _require(
        len(list(report.get("recommended_next_deep_wallets") or []))
        == M79_FINAL_PRIORITY_WALLETS,
        "Priorita finali M79 incomplete.",
    )
    integrity = dict(report.get("integrity") or {})
    expected = str(integrity.get("report_payload_sha256") or "")
    payload = {key: value for key, value in report.items() if key != "integrity"}
    # build_final_report hashes the report before adding integrity, so recompute same payload.
    _require(len(expected) == 64, "Hash interno M79 assente.")
    _require(expected == canonical_sha256(payload), "Hash interno M79 non valido.")
    return report
