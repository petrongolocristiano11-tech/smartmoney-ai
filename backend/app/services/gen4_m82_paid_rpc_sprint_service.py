from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable

from backend.app.services import gen4_zero_helius_pre_micro_live_service as m67
from backend.app.services.gen4_closed_trade_readonly_audit_service import canonical_sha256

M82_VERSION = "canonical-parser-gen4-paid-rpc-sprint/1"
M82_SCOPE = "M82_STABLECOIN_HARDENED_PAID_RPC_SPRINT"
M82_CONFIRMATION = "RUN_M82_PAID_RPC_SPRINT_MAX_9000_CREDITS"

M82_GTFA_CREDITS_PER_REQUEST = 50
M82_MAX_RPC_CREDITS = 9_000
M82_DISCOVERY_TOKEN_LIMIT = 12
M82_DISCOVERY_TX_PER_TOKEN = 100
M82_PASS1_CANDIDATES = 50
M82_PASS1_TRANSACTIONS = 100
M82_PASS2_WALLETS = 8
M82_PASS2_TRANSACTIONS = 400
M82_PASS3_WALLETS = 4
M82_PASS3_TRANSACTIONS = 1200
M82_WORKERS = 8
M82_HISTORY_LOOKBACK_DAYS = 31
M82_REQUIRED_QUALIFIED = 2
M82_MAXIMUM_ATTEMPTS = 3

_SOLANA_ADDRESS = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")


class M82PaidRpcSprintError(RuntimeError):
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
        raise M82PaidRpcSprintError(message)


def _valid_address(value: Any) -> bool:
    return bool(_SOLANA_ADDRESS.fullmatch(str(value or "").strip()))


def validate_inputs(
    m66: dict[str, Any],
    m79: dict[str, Any],
    m80: dict[str, Any],
    m81_state: dict[str, Any],
) -> None:
    _require(
        m66.get("scope") == "M66_CONTROLLED_HELIUS_NEW_WALLET_DISCOVERY",
        "Scope M66 inatteso.",
    )
    _require(
        m79.get("scope") == "M79_PAID_CANDIDATE_ZERO_HELIUS_ECONOMIC_TRIAGE"
        and m79.get("evaluation") == "PASS",
        "M79 inatteso o non PASS.",
    )
    _require(
        m80.get("scope") == "M80_TARGETED_FOUR_WALLET_ZERO_HELIUS_DEEP_QUALIFICATION"
        and m80.get("evaluation") == "PASS",
        "M80 inatteso o non PASS.",
    )
    _require(
        m81_state.get("scope") == "M81_FAST_DISCOVERY_PARALLEL_ECONOMIC_QUALIFICATION"
        and m81_state.get("status") == "COMPLETED",
        "State M81 inatteso o incompleto.",
    )
    _require(
        m81_state.get("discovery_inflight") in (None, {}),
        "M81 contiene discovery inflight.",
    )


def known_wallets(
    m66: dict[str, Any],
    m79: dict[str, Any],
    m80: dict[str, Any],
    m81_state: dict[str, Any],
) -> set[str]:
    values: set[str] = set()

    def add_rows(rows: Iterable[Any]) -> None:
        for item in rows or []:
            if isinstance(item, dict):
                wallet = str(item.get("wallet_address") or "").strip()
                if _valid_address(wallet):
                    values.add(wallet)

    add_rows(m66.get("candidate_results") or [])
    add_rows(m79.get("pass1_ranked") or [])
    add_rows(m80.get("candidate_results") or [])
    add_rows(m81_state.get("discovery_candidates") or [])
    for lane in m81_state.get("discovery_lanes") or []:
        if not isinstance(lane, dict):
            continue
        seed = str(lane.get("seed_wallet") or "").strip()
        if _valid_address(seed):
            values.add(seed)
        for wallet in lane.get("candidate_wallets") or []:
            if _valid_address(wallet):
                values.add(str(wallet))
    return values


def select_discovery_tokens(
    m66: dict[str, Any],
    m81_state: dict[str, Any],
    *,
    limit: int = M82_DISCOVERY_TOKEN_LIMIT,
) -> list[dict[str, Any]]:
    score: Counter[str] = Counter()
    latest: dict[str, int] = {}
    source: dict[str, set[str]] = defaultdict(set)

    for row in m66.get("seed_tokens") or []:
        if not isinstance(row, dict):
            continue
        token = str(row.get("token_mint") or "").strip()
        if not _valid_address(token):
            continue
        occurrences = max(1, _integer(row.get("seed_swap_occurrences"), default=1))
        score[token] += occurrences * 3
        latest[token] = max(
            latest.get(token, 0),
            _integer(row.get("latest_seed_swap_timestamp")),
        )
        source[token].add("M66_SEED")

    for row in m81_state.get("discovery_candidates") or []:
        if not isinstance(row, dict):
            continue
        evidence = dict(row.get("m66_discovery_evidence") or {})
        observed_latest = _integer(evidence.get("latest_token_history_timestamp"))
        occurrence_weight = max(1, _integer(evidence.get("token_history_occurrences"), default=1))
        for token in evidence.get("token_overlap") or []:
            token = str(token or "").strip()
            if not _valid_address(token):
                continue
            score[token] += occurrence_weight
            latest[token] = max(latest.get(token, 0), observed_latest)
            source[token].add("M81_OVERLAP")

    ordered = sorted(
        score,
        key=lambda token: (-score[token], -latest.get(token, 0), token),
    )[: max(1, min(int(limit), M82_DISCOVERY_TOKEN_LIMIT))]
    return [
        {
            "token_mint": token,
            "discovery_score": int(score[token]),
            "latest_observed_timestamp": int(latest.get(token, 0)),
            "sources": sorted(source[token]),
        }
        for token in ordered
    ]


def normalize_full_transaction(item: dict[str, Any]) -> dict[str, Any] | None:
    transaction = item.get("transaction")
    meta = item.get("meta")
    if not isinstance(transaction, dict) or not isinstance(meta, dict):
        return None
    payload = {
        "slot": item.get("slot"),
        "blockTime": item.get("blockTime"),
        "meta": meta,
        "transaction": transaction,
    }
    signature = str(item.get("signature") or "").strip()
    if not signature:
        signatures = transaction.get("signatures")
        if isinstance(signatures, list) and signatures:
            signature = str(signatures[0] or "").strip()
    if signature:
        payload["signature"] = signature
    return payload


def transaction_signers(item: dict[str, Any]) -> list[str]:
    transaction = item.get("transaction")
    if not isinstance(transaction, dict):
        return []
    message = transaction.get("message")
    if not isinstance(message, dict):
        return []
    keys = message.get("accountKeys")
    if not isinstance(keys, list) or not keys:
        return []
    result: list[str] = []
    if all(isinstance(value, dict) for value in keys):
        for value in keys:
            if not bool(value.get("signer")):
                continue
            pubkey = str(value.get("pubkey") or "").strip()
            if _valid_address(pubkey):
                result.append(pubkey)
    else:
        first = keys[0]
        if isinstance(first, str) and _valid_address(first):
            result.append(first)
    return sorted(set(result))


def discover_candidates(
    token_histories: dict[str, list[dict[str, Any]]],
    *,
    excluded_wallets: set[str],
    limit: int = M82_PASS1_CANDIDATES,
) -> list[dict[str, Any]]:
    occurrences: Counter[str] = Counter()
    token_overlap: dict[str, set[str]] = defaultdict(set)
    latest: dict[str, int] = {}
    sample_signatures: dict[str, set[str]] = defaultdict(set)

    for token, rows in token_histories.items():
        for raw in rows:
            if not isinstance(raw, dict):
                continue
            block_time = _integer(raw.get("blockTime"))
            transaction = raw.get("transaction")
            signatures = (
                transaction.get("signatures")
                if isinstance(transaction, dict)
                else None
            )
            signature = (
                str(signatures[0] or "")
                if isinstance(signatures, list) and signatures
                else ""
            )
            for wallet in transaction_signers(raw):
                if wallet in excluded_wallets or wallet == token:
                    continue
                occurrences[wallet] += 1
                token_overlap[wallet].add(token)
                latest[wallet] = max(latest.get(wallet, 0), block_time)
                if signature:
                    sample_signatures[wallet].add(signature)

    ranked = sorted(
        occurrences,
        key=lambda wallet: (
            -len(token_overlap[wallet]),
            -occurrences[wallet],
            -latest.get(wallet, 0),
            wallet,
        ),
    )[: max(1, min(int(limit), M82_PASS1_CANDIDATES))]

    return [
        {
            "wallet_address": wallet,
            "prescreen_score": round(
                min(
                    100.0,
                    len(token_overlap[wallet]) * 30.0
                    + min(occurrences[wallet], 20) * 2.5,
                ),
                4,
            ),
            "m66_sample": {},
            "m82_discovery_evidence": {
                "token_overlap": sorted(token_overlap[wallet]),
                "token_overlap_count": len(token_overlap[wallet]),
                "transaction_occurrences": occurrences[wallet],
                "latest_transaction_timestamp": latest.get(wallet, 0),
                "sample_signature_count": len(sample_signatures[wallet]),
            },
        }
        for wallet in ranked
    ]


def build_model_policy(maximum_transactions: int) -> dict[str, Any]:
    _require(
        maximum_transactions
        in {
            M82_PASS1_TRANSACTIONS,
            M82_PASS2_TRANSACTIONS,
            M82_PASS3_TRANSACTIONS,
        },
        "Profondita M82 inattesa.",
    )
    # Keep the shared M67-M70 economic contract intact.  M82 controls its
    # own paid-RPC fanout outside this policy object, so the legacy
    # public-RPC/deep-wallet guardrails must remain inside their canonical
    # bounds even when M82 evaluates more candidates in parallel.
    return m67.validate_policy(
        {
            **m67.M67_M70_DEFAULT_POLICY,
            "maximum_signatures_per_deep_wallet": int(maximum_transactions),
            "activity_lookback_days": 30,
            "public_rpc_maximum_attempts": M82_MAXIMUM_ATTEMPTS,
            "public_rpc_throttle_seconds": 0.0,
        }
    )


def build_result(
    candidate: dict[str, Any],
    deep: dict[str, Any],
    *,
    stage: str,
    maximum_transactions: int,
) -> dict[str, Any]:
    wallet = str(candidate.get("wallet_address") or "")
    _require(wallet == str(deep.get("wallet_address") or ""), "Wallet/deep mismatch M82.")
    policy = build_model_policy(maximum_transactions)
    analysis = m67._economic_analysis(dict(deep.get("backtest") or {}), policy)  # noqa: SLF001
    metrics = dict(analysis.get("metrics") or {})
    recent = dict(analysis.get("recent_metrics") or {})
    history_complete = bool(deep.get("history_complete"))
    gate = bool(analysis.get("economic_gate_passed")) and history_complete
    if gate:
        disposition = "QUALIFIED_PENDING_SHORT_CANARY"
    elif history_complete:
        disposition = "RESEARCH_ONLY"
    else:
        disposition = "OBSERVE_ONLY"
    return {
        "wallet_address": wallet,
        "stage": stage,
        "maximum_transactions": int(maximum_transactions),
        "disposition": disposition,
        "history_complete": history_complete,
        "pagination_remaining": bool(deep.get("pagination_remaining")),
        "transaction_count": _integer(deep.get("transaction_count")),
        "parsed_event_count": _integer(deep.get("parsed_event_count")),
        "rejected_transaction_count": _integer(deep.get("rejected_transaction_count")),
        "prescreen_score": round(_finite(candidate.get("prescreen_score")), 4),
        "discovery_evidence": dict(candidate.get("m82_discovery_evidence") or {}),
        "copy_normalized_model": dict(deep.get("backtest", {}).get("model") or {}),
        "economic_analysis": analysis,
        "closed_trade_count": _integer(metrics.get("closed_trade_count")),
        "history_span_days": _finite(metrics.get("history_span_days")),
        "open_positions": _integer(metrics.get("open_positions")),
        "profit_factor": _finite(metrics.get("profit_factor")),
        "net_pnl_sol": _finite(metrics.get("net_pnl_sol")),
        "net_equity_pnl_sol": _finite(metrics.get("net_equity_pnl_sol")),
        "win_rate_percent": _finite(metrics.get("win_rate_percent")),
        "maximum_drawdown_percent": _finite(
            metrics.get("maximum_drawdown_percent"),
            default=100.0,
        ),
        "recent_profit_factor": _finite(recent.get("profit_factor")),
        "recent_net_pnl_sol": _finite(recent.get("net_pnl_sol")),
        "economic_score": _finite(analysis.get("economic_score"), default=-1.0),
        "failure_reasons": list(analysis.get("failure_reasons") or []),
        "short_canary_authorized": False,
        "micro_live_authorized": False,
    }


def rank_results(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
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


def pass2_eligible(row: dict[str, Any]) -> bool:
    if row.get("disposition") == "QUALIFIED_PENDING_SHORT_CANARY":
        return False
    return (
        _integer(row.get("closed_trade_count")) >= 12
        and _finite(row.get("net_pnl_sol")) > 0
        and _finite(row.get("profit_factor")) >= 1.10
        and _finite(row.get("maximum_drawdown_percent"), default=100.0) <= 22.0
        and _finite(row.get("win_rate_percent")) >= 28.0
    )


def pass3_eligible(row: dict[str, Any]) -> bool:
    if row.get("disposition") == "QUALIFIED_PENDING_SHORT_CANARY":
        return False
    if bool(row.get("history_complete")):
        return False
    return (
        _integer(row.get("closed_trade_count")) >= 25
        and _finite(row.get("net_pnl_sol")) > 0
        and _finite(row.get("profit_factor")) >= 1.22
        and _finite(row.get("maximum_drawdown_percent"), default=100.0) <= 18.0
        and _finite(row.get("win_rate_percent")) >= 30.0
        and _finite(row.get("recent_profit_factor")) >= 1.05
    )


def select_pass2(rows: Iterable[dict[str, Any]]) -> list[str]:
    eligible = [row for row in rank_results(rows) if pass2_eligible(row)]
    return [str(row["wallet_address"]) for row in eligible[:M82_PASS2_WALLETS]]


def select_pass3(rows: Iterable[dict[str, Any]]) -> list[str]:
    eligible = [row for row in rank_results(rows) if pass3_eligible(row)]
    return [str(row["wallet_address"]) for row in eligible[:M82_PASS3_WALLETS]]


def build_final_report(
    *,
    started_at_utc: str,
    completed_at_utc: str,
    input_hashes: dict[str, str],
    seed_tokens: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    final_results: list[dict[str, Any]],
    rpc_stats: dict[str, Any],
    cache_manifest_sha256: str,
    effective_credit_cap: int,
) -> dict[str, Any]:
    ranked = rank_results(final_results)
    qualified = [
        str(row["wallet_address"])
        for row in ranked
        if row.get("disposition") == "QUALIFIED_PENDING_SHORT_CANARY"
    ]
    report: dict[str, Any] = {
        "evaluation": "PASS",
        "scope": M82_SCOPE,
        "version": M82_VERSION,
        "started_at_utc": started_at_utc,
        "completed_at_utc": completed_at_utc,
        "inputs": dict(input_hashes),
        "parser_hardening": {
            "required_parser_version": "canonical-parser-gen4-raw-balance-delta/4",
            "stablecoin_quote_delta_fail_closed": True,
            "minimum_material_sol_input_fail_closed": True,
        },
        "discovery": {
            "strategy": "HELIUS_GET_TRANSACTIONS_FOR_ADDRESS_FULL_DIRECT_TOKEN_SIGNER_DISCOVERY",
            "seed_tokens": seed_tokens,
            "candidate_count": len(candidates),
            "candidate_limit": M82_PASS1_CANDIDATES,
        },
        "qualification": {
            "pass1_transactions": M82_PASS1_TRANSACTIONS,
            "pass2_transactions": M82_PASS2_TRANSACTIONS,
            "pass3_transactions": M82_PASS3_TRANSACTIONS,
            "pass2_wallet_limit": M82_PASS2_WALLETS,
            "pass3_wallet_limit": M82_PASS3_WALLETS,
            "workers": M82_WORKERS,
            "history_query_days": M82_HISTORY_LOOKBACK_DAYS,
            "required_qualified_wallets": M82_REQUIRED_QUALIFIED,
        },
        "candidate_results": ranked,
        "summary": {
            "qualified_pending_short_canary": len(qualified),
            "qualified_wallets": qualified,
            "m74_minimum_two_wallets_reached": len(qualified) >= M82_REQUIRED_QUALIFIED,
        },
        "helius_rpc": {
            **dict(rpc_stats),
            "method": "getTransactionsForAddress",
            "credits_per_network_attempt": M82_GTFA_CREDITS_PER_REQUEST,
            "package_hard_cap_credits": M82_MAX_RPC_CREDITS,
            "effective_runtime_credit_cap": int(effective_credit_cap),
            "cache_manifest_sha256": cache_manifest_sha256,
        },
        "safety": {
            "candidate_database_writes": 0,
            "raw_capture_writes": 0,
            "backend_posts": 0,
            "jupiter_requests": 0,
            "paper_orders": 0,
            "live_orders": 0,
            "signed_transactions": 0,
            "submitted_transactions": 0,
            "signer_authorized": False,
            "short_canary_execution_authorized": False,
            "micro_live_execution_authorized": False,
            "official_realtime_counter": 83,
            "official_realtime_counter_mutated": False,
            "database_write_scope": "HELIUS_CREDIT_GUARD_RESERVATIONS_ONLY",
        },
        "next_step": (
            "START_ACCELERATED_SHORT_CANARY_REVIEW"
            if len(qualified) >= M82_REQUIRED_QUALIFIED
            else "M82_NO_TWO_M74_PASSES_REVIEW_NEXT_DISCOVERY_LANE"
        ),
    }
    report["integrity"] = {"report_payload_sha256": canonical_sha256(report)}
    return report


def validate_final_report(report: dict[str, Any]) -> dict[str, Any]:
    _require(report.get("evaluation") == "PASS", "Report M82 non PASS.")
    _require(report.get("scope") == M82_SCOPE, "Scope M82 inatteso.")
    _require(report.get("version") == M82_VERSION, "Versione M82 inattesa.")
    expected = str(dict(report.get("integrity") or {}).get("report_payload_sha256") or "")
    payload = {key: value for key, value in report.items() if key != "integrity"}
    _require(len(expected) == 64 and expected == canonical_sha256(payload), "Hash report M82 non valido.")
    rpc = dict(report.get("helius_rpc") or {})
    _require(
        _integer(rpc.get("credits_reserved")) <= M82_MAX_RPC_CREDITS,
        "Cap crediti M82 superato.",
    )
    safety = dict(report.get("safety") or {})
    _require(_integer(safety.get("live_orders")) == 0, "M82 contiene LIVE.")
    _require(safety.get("signer_authorized") is False, "M82 signer autorizzato.")
    _require(
        safety.get("micro_live_execution_authorized") is False,
        "M82 Micro Live autorizzato.",
    )
    return report


__all__ = [
    "M82_CONFIRMATION",
    "M82_DISCOVERY_TOKEN_LIMIT",
    "M82_DISCOVERY_TX_PER_TOKEN",
    "M82_GTFA_CREDITS_PER_REQUEST",
    "M82_HISTORY_LOOKBACK_DAYS",
    "M82_MAXIMUM_ATTEMPTS",
    "M82_MAX_RPC_CREDITS",
    "M82_PASS1_CANDIDATES",
    "M82_PASS1_TRANSACTIONS",
    "M82_PASS2_TRANSACTIONS",
    "M82_PASS2_WALLETS",
    "M82_PASS3_TRANSACTIONS",
    "M82_PASS3_WALLETS",
    "M82_REQUIRED_QUALIFIED",
    "M82_SCOPE",
    "M82_VERSION",
    "M82_WORKERS",
    "M82PaidRpcSprintError",
    "build_final_report",
    "build_model_policy",
    "build_result",
    "discover_candidates",
    "known_wallets",
    "normalize_full_transaction",
    "rank_results",
    "select_discovery_tokens",
    "select_pass2",
    "select_pass3",
    "transaction_signers",
    "validate_final_report",
    "validate_inputs",
]
