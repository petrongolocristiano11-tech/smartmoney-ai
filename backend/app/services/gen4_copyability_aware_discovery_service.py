from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from backend.app.models.candidate_backtest import CandidateBacktestRun
from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.models.trade import Trade
from backend.app.models.wallet_edge import WalletEdge
from backend.app.services.gen4_closed_trade_readonly_audit_service import (
    canonical_sha256,
    write_json_atomic,
)
from backend.app.services.wallet_activity_service import (
    analyze_wallet_activity_from_trades,
)
from backend.app.services.wallet_quality_service import (
    QUALITY_CLASS_NOT_COPYABLE,
    QUALITY_CLASS_SUSPICIOUS,
    analyze_wallet_quality_from_trades,
)


M66_DISCOVERY_VERSION = "canonical-parser-gen4-copyability-aware-discovery/1"
M66_SCOPE = "M66_GEN4_DEFINITIVE_COPYABILITY_AWARE_DISCOVERY_READ_ONLY"
M66_SNAPSHOT_SCOPE = "M66_CACHED_DISCOVERY_EVIDENCE_SNAPSHOT_READ_ONLY"
M66_RUN_CONFIRMATION = "RUN_M66_GEN4_COPYABILITY_AWARE_DISCOVERY_READ_ONLY"
M66_CACHED_TRADE_ENRICHMENT_VERSION = (
    "canonical-parser-gen4-cached-trade-zero-credit-enrichment/1"
)

STATUS_QUALIFIED = "QUALIFIED_FOR_SHORT_CANARY"
STATUS_NEEDS_HISTORY = "NEEDS_TARGETED_HISTORY"
STATUS_NEEDS_FRESH_EVIDENCE = "NEEDS_FRESH_COPYABILITY_EVIDENCE"
STATUS_RESEARCH_ONLY = "RESEARCH_ONLY"
STATUS_BLOCKED = "BLOCKED"

ACTION_SHORT_CANARY = "COLLECT_SHORT_REALTIME_CANARY"
ACTION_TARGETED_HISTORY = "QUEUE_PUBLIC_RPC_HISTORY_READ_ONLY"
ACTION_REFRESH_EVIDENCE = "REFRESH_COPYABILITY_EVIDENCE_READ_ONLY"
ACTION_RESEARCH_ONLY = "DO_NOT_PROMOTE"

M66_DEFAULT_POLICY: dict[str, Any] = {
    "policy_version": M66_DISCOVERY_VERSION,
    "maximum_selected_wallets": 3,
    "minimum_closed_trades": 100,
    "minimum_history_span_days": 30.0,
    "minimum_recent_closed_trades": 20,
    "minimum_net_pnl_sol": 0.0,
    "minimum_profit_factor": 1.30,
    "minimum_recent_net_pnl_sol": 0.0,
    "minimum_recent_profit_factor": 1.10,
    "maximum_drawdown_percent": 15.0,
    "maximum_recent_drawdown_percent": 15.0,
    "minimum_win_rate_percent": 30.0,
    "minimum_unique_tokens": 10,
    "maximum_token_concentration_percent": 25.0,
    "require_positive_net_without_best_trade": True,
    "stability_window_size": 20,
    "minimum_stability_windows": 5,
    "minimum_positive_stability_windows": 4,
    "minimum_worst_stability_profit_factor": 0.80,
    "minimum_preliminary_closed_trades": 40,
    "minimum_preliminary_profit_factor": 1.15,
    "maximum_preliminary_drawdown_percent": 20.0,
    "minimum_activity_score": 60.0,
    "minimum_swaps_7d": 6,
    "maximum_swaps_7d": 80,
    "minimum_active_days_7d": 3,
    "maximum_activity_evidence_age_hours": 72.0,
    "minimum_quality_score": 70.0,
    "maximum_dust_ratio": 0.20,
    "minimum_size_compatibility_ratio": 0.70,
    "minimum_execution_coverage_percent": 80.0,
    "minimum_matched_sell_ratio_percent": 90.0,
    "maximum_open_positions": 0,
    "minimum_exitability_score": 80.0,
    "minimum_current_route_coverage_percent": 80.0,
    "minimum_jupiter_compatibility_percent": 80.0,
    "maximum_backtest_evidence_age_hours": 168.0,
    "maximum_exitability_evidence_age_hours": 168.0,
    "required_backtest_starting_capital_sol": 1.0,
    "required_backtest_fixed_buy_size_sol": 0.05,
    "required_backtest_slippage_bps": 100,
    "required_backtest_fee_bps": 10,
    "required_backtest_copy_delay_seconds": 8,
    "required_backtest_delay_penalty_bps_per_minute": 25.0,
    "required_backtest_max_open_positions": 5,
    "required_effective_market_friction_bps": 103.3333,
    "daily_public_rpc_request_budget": 120,
    "maximum_public_rpc_requests_per_wallet": 40,
    "maximum_history_queue_wallets": 3,
    "shared_token_cluster_threshold": 3,
    "canary_minimum_observation_hours": 24.0,
    "canary_minimum_entry_attempts": 20,
    "canary_minimum_closed_trades": 10,
    "canary_minimum_webhook_coverage_percent": 95.0,
    "canary_minimum_unsigned_build_coverage_percent": 100.0,
    "canary_maximum_entry_reject_rate_percent": 20.0,
    "canary_maximum_p95_end_to_quote_ms": 5000.0,
    "canary_maximum_p95_price_impact_bps": 500.0,
    "canary_maximum_p95_price_deterioration_bps": 1000.0,
    "consensus_window_seconds": 180,
    "consensus_minimum_independent_wallets": 2,
    "consensus_maximum_wallets": 3,
    "consensus_maximum_token_exposure_sol": 0.10,
}

_SOLANA_ADDRESS = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
_HIGH_RISK_EDGE_TYPES = frozenset(
    {
        "COPY_CHAIN",
        "MIRROR",
        "SAME_CONTROLLER",
        "SAME_FUNDER",
        "FUNDING",
        "TRANSFER",
    }
)


class M66DiscoveryError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        result = value
    else:
        try:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=timezone.utc)
    return result.astimezone(timezone.utc)


def _age_hours(value: Any, now: datetime) -> float | None:
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    return round(max(0.0, (now - parsed).total_seconds() / 3600.0), 6)


def _finite(value: Any, *, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if math.isfinite(number) else float(default)


def _integer(value: Any, *, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _clip(value: Any, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, _finite(value)))


def _without_key(value: dict[str, Any], key: str) -> dict[str, Any]:
    return {name: item for name, item in value.items() if name != key}


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise M66DiscoveryError(message)


def _profit_factor(values: Iterable[float]) -> float:
    rows = list(values)
    gross_profit = sum(max(0.0, item) for item in rows)
    gross_loss = abs(sum(min(0.0, item) for item in rows))
    if gross_loss > 0:
        return gross_profit / gross_loss
    return 999.0 if gross_profit > 0 else 0.0


def _position_metrics(
    positions: Iterable[dict[str, Any]],
    *,
    starting_equity_sol: float,
) -> dict[str, Any]:
    rows = sorted(
        [dict(item) for item in positions],
        key=lambda item: (
            str(item.get("exit_at") or ""),
            str(item.get("entry_at") or ""),
            str(item.get("entry_signature") or ""),
        ),
    )
    pnl_values = [_finite(item.get("pnl_sol")) for item in rows]
    gross_profit = sum(max(0.0, item) for item in pnl_values)
    gross_loss = abs(sum(min(0.0, item) for item in pnl_values))
    net_pnl = sum(pnl_values)
    winning = sum(item > 1e-12 for item in pnl_values)
    losing = sum(item < -1e-12 for item in pnl_values)
    breakeven = len(rows) - winning - losing
    equity = max(1e-9, starting_equity_sol)
    peak = equity
    maximum_drawdown = 0.0
    for pnl in pnl_values:
        equity += pnl
        peak = max(peak, equity)
        if peak > 0:
            maximum_drawdown = max(
                maximum_drawdown,
                (peak - equity) / peak * 100.0,
            )
    return {
        "closed_trade_count": len(rows),
        "winning_trades": winning,
        "losing_trades": losing,
        "breakeven_trades": breakeven,
        "gross_profit_sol": round(gross_profit, 9),
        "gross_loss_sol": round(gross_loss, 9),
        "net_pnl_sol": round(net_pnl, 9),
        "profit_factor": round(_profit_factor(pnl_values), 8),
        "win_rate_percent": round(winning / len(rows) * 100.0, 8)
        if rows
        else 0.0,
        "maximum_drawdown_percent": round(maximum_drawdown, 8),
    }


def _stability_windows(
    positions: list[dict[str, Any]],
    *,
    size: int,
    starting_equity_sol: float,
) -> list[dict[str, Any]]:
    rows = sorted(
        [dict(item) for item in positions],
        key=lambda item: (
            str(item.get("exit_at") or ""),
            str(item.get("entry_at") or ""),
            str(item.get("entry_signature") or ""),
        ),
    )
    result: list[dict[str, Any]] = []
    for start in range(0, len(rows), max(1, size)):
        chunk = rows[start : start + max(1, size)]
        if len(chunk) < max(1, size):
            continue
        metrics = _position_metrics(
            chunk,
            starting_equity_sol=starting_equity_sol,
        )
        result.append(
            {
                "window": len(result) + 1,
                "trade_start": start + 1,
                "trade_end": start + len(chunk),
                "net_pnl_sol": metrics["net_pnl_sol"],
                "profit_factor": metrics["profit_factor"],
                "win_rate_percent": metrics["win_rate_percent"],
                "maximum_drawdown_percent": metrics[
                    "maximum_drawdown_percent"
                ],
            }
        )
    return result


class _DisjointSet:
    def __init__(self, values: Iterable[str]) -> None:
        self.parent = {value: value for value in values}

    def find(self, value: str) -> str:
        parent = self.parent.setdefault(value, value)
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        if left_root < right_root:
            self.parent[right_root] = left_root
        else:
            self.parent[left_root] = right_root


def _cluster_evidence(
    addresses: list[str],
    edges: list[WalletEdge],
    *,
    shared_token_threshold: int,
) -> dict[str, dict[str, Any]]:
    address_set = set(addresses)
    disjoint = _DisjointSet(addresses)
    shared_tokens: dict[tuple[str, str], set[str]] = defaultdict(set)
    high_risk_counts: Counter[str] = Counter()
    relevant_edge_counts: Counter[str] = Counter()

    for edge in edges:
        left = str(edge.source_wallet or "")
        right = str(edge.target_wallet or "")
        if left not in address_set or right not in address_set or left == right:
            continue
        relevant_edge_counts[left] += 1
        relevant_edge_counts[right] += 1
        edge_type = str(edge.edge_type or "SHARED_TOKEN").upper()
        if edge_type in _HIGH_RISK_EDGE_TYPES:
            disjoint.union(left, right)
            high_risk_counts[left] += 1
            high_risk_counts[right] += 1
        elif edge_type == "SHARED_TOKEN" and edge.token_mint:
            pair = tuple(sorted((left, right)))
            shared_tokens[pair].add(str(edge.token_mint))

    for pair, tokens in shared_tokens.items():
        if len(tokens) >= max(1, shared_token_threshold):
            disjoint.union(pair[0], pair[1])

    components: dict[str, list[str]] = defaultdict(list)
    for address in addresses:
        components[disjoint.find(address)].append(address)

    result: dict[str, dict[str, Any]] = {}
    for members in components.values():
        ordered = sorted(members)
        cluster_id = "cluster-" + canonical_sha256(ordered)[:16]
        for address in ordered:
            shared_relationships = sum(
                len(tokens)
                for pair, tokens in shared_tokens.items()
                if address in pair
            )
            result[address] = {
                "cluster_id": cluster_id,
                "cluster_size": len(ordered),
                "cluster_members": ordered,
                "high_risk_edge_count": high_risk_counts[address],
                "shared_token_relationship_count": shared_relationships,
                "relevant_edge_count": relevant_edge_counts[address],
                "relationship_status": (
                    "RELATED_CLUSTER_DETECTED"
                    if len(ordered) > 1
                    else "NO_HIGH_RISK_RELATIONSHIP_DETECTED"
                ),
                "independence_verified": False,
                "consensus_eligible": False,
            }
    return result


def _local_trade_evidence(
    *,
    inventory: dict[str, Any],
    activity: dict[str, Any],
    quality: dict[str, Any],
    policy: dict[str, Any],
) -> dict[str, Any]:
    lifetime_rows = _integer(inventory.get("lifetime_swap_rows"))
    recent_rows = _integer(quality.get("quality_sample_swaps_7d"))
    checks = {
        "has_cached_trade_rows": lifetime_rows > 0,
        "activity_is_active": str(
            activity.get("activity_classification")
        ) == "ATTIVO",
        "activity_score_sufficient": _finite(
            activity.get("activity_score")
        ) >= float(policy["minimum_activity_score"]),
        "recent_swaps_sufficient": recent_rows
        >= int(policy["minimum_swaps_7d"]),
        "recent_swaps_not_hyperactive": recent_rows
        <= int(policy["maximum_swaps_7d"]),
        "active_days_sufficient": _integer(
            activity.get("active_days_7d")
        ) >= int(policy["minimum_active_days_7d"]),
        "dust_ratio_acceptable": _finite(
            quality.get("dust_ratio_7d"),
            default=1.0,
        ) <= float(policy["maximum_dust_ratio"]),
        "size_compatibility_sufficient": _finite(
            quality.get("size_compatibility_ratio_7d")
        ) >= float(policy["minimum_size_compatibility_ratio"]),
        "quality_score_sufficient": _finite(
            quality.get("quality_score")
        ) >= float(policy["minimum_quality_score"]),
        "buy_and_sell_present": _integer(activity.get("buys_7d")) > 0
        and _integer(activity.get("sells_7d")) > 0,
        "token_diversity_present": _integer(
            quality.get("unique_tokens_7d")
        ) >= 2,
        "completed_pair_present": _integer(
            quality.get("completed_token_pairs_7d")
        ) >= 1,
        "round_trip_ratio_sufficient": _finite(
            quality.get("round_trip_token_ratio_7d")
        ) >= 0.25,
        "token_concentration_acceptable": _finite(
            quality.get("top_token_concentration_7d"),
            default=1.0,
        ) <= 0.85,
        "no_invalid_amounts": _integer(
            quality.get("invalid_amount_swaps_7d")
        ) == 0,
    }
    passed = lifetime_rows > 0 and all(checks.values())
    if lifetime_rows <= 0:
        status = "NO_CACHED_TRADE_EVIDENCE"
    elif passed:
        status = "PASS_ZERO_CREDIT_COPYABILITY_PRESCREEN"
    else:
        status = "FAIL_ZERO_CREDIT_COPYABILITY_PRESCREEN"
    return {
        "enrichment_version": M66_CACHED_TRADE_ENRICHMENT_VERSION,
        "available": lifetime_rows > 0,
        "prescreen_passed": passed,
        "prescreen_status": status,
        "lifetime_swap_rows": lifetime_rows,
        "recent_swap_rows_7d": recent_rows,
        "lifetime_unique_tokens": _integer(
            inventory.get("lifetime_unique_tokens")
        ),
        "oldest_swap_at": _iso(inventory["oldest_swap_at"])
        if inventory.get("oldest_swap_at")
        else None,
        "latest_swap_at": _iso(inventory["latest_swap_at"])
        if inventory.get("latest_swap_at")
        else None,
        "cached_history_span_days": round(
            _finite(inventory.get("cached_history_span_days")),
            8,
        ),
        "checks": checks,
        "failed_checks": sorted(
            name for name, passed_check in checks.items() if not passed_check
        ),
        "economic_metrics_inferred": False,
        "historical_jupiter_quotes_invented": False,
    }


def _candidate_from_models(
    wallet: DiscoveredWallet,
    run: CandidateBacktestRun | None,
    independence: dict[str, Any],
    *,
    policy: dict[str, Any],
    activity_override: dict[str, Any] | None = None,
    quality_override: dict[str, Any] | None = None,
    local_trade_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    positions = [dict(item) for item in (run.position_results or [])] if run else []
    starting_equity = _finite(
        getattr(run, "effective_starting_equity_sol", None),
        default=_finite(getattr(run, "starting_capital_sol", 1.0), default=1.0),
    )
    if starting_equity <= 0:
        starting_equity = 1.0
    recent_size = int(policy["minimum_recent_closed_trades"])
    recent_positions = positions[-recent_size:]
    position_metrics = _position_metrics(
        positions,
        starting_equity_sol=starting_equity,
    )
    recent_metrics = _position_metrics(
        recent_positions,
        starting_equity_sol=starting_equity,
    )
    stability = _stability_windows(
        positions,
        size=int(policy["stability_window_size"]),
        starting_equity_sol=starting_equity,
    )
    token_counts = Counter(
        str(item.get("token_mint") or "")
        for item in positions
        if str(item.get("token_mint") or "")
    )
    top_token, top_count = token_counts.most_common(1)[0] if token_counts else (None, 0)
    top_concentration = (
        top_count / len(positions) * 100.0 if positions else 0.0
    )
    best_pnl = max(
        (_finite(item.get("pnl_sol")) for item in positions),
        default=0.0,
    )
    stored_closed = _integer(
        getattr(run, "completed_positions", None)
        if run
        else wallet.backtest_completed_positions
    )
    stored_net = _finite(
        getattr(run, "net_pnl_sol", None)
        if run
        else wallet.backtest_net_pnl_sol
    )
    stored_profit_factor = (
        None
        if (run and run.profit_factor is None)
        or (not run and wallet.backtest_profit_factor is None)
        else _finite(
            run.profit_factor if run else wallet.backtest_profit_factor
        )
    )
    stored_drawdown = _finite(
        run.max_drawdown_percent if run else wallet.backtest_max_drawdown_percent
    )
    stored_win_rate = _finite(
        run.win_rate_percent if run else wallet.backtest_win_rate_percent
    )
    parameters = dict(run.parameters or {}) if run else {}
    run_completed_at = (
        run.completed_at or run.started_at if run is not None else wallet.promotion_calculated_at
    )
    activity = dict(activity_override or {})
    quality = dict(quality_override or {})
    activity_from_trade_cache = activity_override is not None
    quality_from_trade_cache = quality_override is not None

    return {
        "wallet_address": wallet.wallet_address,
        "source": {
            "discovered_from_token": wallet.discovered_from_token,
            "discovered_wallet_id": wallet.id,
            "latest_backtest_run_id": run.run_id if run else wallet.latest_backtest_run_id,
            "backtest_decision": run.decision if run else wallet.promotion_status,
            "backtest_status": run.status if run else "MISSING",
            "smart_score": _finite(wallet.smart_score),
            "ranking_score": _finite(wallet.ranking_score),
            "activity_evidence_source": (
                "DERIVED_IN_MEMORY_FROM_CACHED_TRADE_ROWS"
                if activity_from_trade_cache
                else "DISCOVERED_WALLET_STORED_FIELDS"
            ),
            "quality_evidence_source": (
                "DERIVED_IN_MEMORY_FROM_CACHED_TRADE_ROWS"
                if quality_from_trade_cache
                else "DISCOVERED_WALLET_STORED_FIELDS"
            ),
        },
        "activity": {
            "classification": activity.get(
                "activity_classification",
                wallet.activity_classification,
            ),
            "score": _finite(
                activity.get("activity_score", wallet.activity_score)
            ),
            "last_swap_at": _iso(
                activity.get("last_swap_at", wallet.last_swap_at)
            )
            if activity.get("last_swap_at", wallet.last_swap_at)
            else None,
            "swaps_24h": _integer(
                activity.get("swaps_24h", wallet.swaps_24h)
            ),
            "swaps_7d": _integer(activity.get("swaps_7d", wallet.swaps_7d)),
            "buys_7d": _integer(activity.get("buys_7d", wallet.buys_7d)),
            "sells_7d": _integer(activity.get("sells_7d", wallet.sells_7d)),
            "active_days_7d": _integer(
                activity.get("active_days_7d", wallet.active_days_7d)
            ),
            "calculated_at": _iso(
                activity.get(
                    "activity_calculated_at",
                    wallet.activity_calculated_at,
                )
            )
            if activity.get(
                "activity_calculated_at",
                wallet.activity_calculated_at,
            )
            else None,
        },
        "quality": {
            "classification": quality.get(
                "quality_classification",
                wallet.quality_classification,
            ),
            "score": _finite(
                quality.get("quality_score", wallet.quality_score)
            ),
            "sample_swaps_7d": _integer(
                quality.get(
                    "quality_sample_swaps_7d",
                    wallet.quality_sample_swaps_7d,
                )
            ),
            "meaningful_swaps_7d": _integer(
                quality.get(
                    "meaningful_swaps_7d",
                    wallet.meaningful_swaps_7d,
                )
            ),
            "dust_ratio_7d": _finite(
                quality.get("dust_ratio_7d", wallet.dust_ratio_7d)
            ),
            "size_compatibility_ratio_7d": _finite(
                quality.get(
                    "size_compatibility_ratio_7d",
                    wallet.size_compatibility_ratio_7d,
                )
            ),
            "invalid_amount_swaps_7d": _integer(
                quality.get(
                    "invalid_amount_swaps_7d",
                    wallet.invalid_amount_swaps_7d,
                )
            ),
            "unique_tokens_7d": _integer(
                quality.get("unique_tokens_7d", wallet.unique_tokens_7d)
            ),
            "completed_token_pairs_7d": _integer(
                quality.get(
                    "completed_token_pairs_7d",
                    wallet.completed_token_pairs_7d,
                )
            ),
            "calculated_at": _iso(
                quality.get(
                    "quality_calculated_at",
                    wallet.quality_calculated_at,
                )
            )
            if quality.get(
                "quality_calculated_at",
                wallet.quality_calculated_at,
            )
            else None,
        },
        "economics": {
            "evidence_class": "CACHED_GEN4_COSTED_BACKTEST_PROXY"
            if run
            else "MISSING",
            "position_level_evidence_complete": bool(
                run and stored_closed > 0 and len(positions) == stored_closed
            ),
            "closed_trade_count": stored_closed,
            "position_result_count": len(positions),
            "history_span_days": _finite(
                run.history_span_days if run else wallet.backtest_history_span_days
            ),
            "net_pnl_sol": stored_net,
            "profit_factor": stored_profit_factor,
            "win_rate_percent": stored_win_rate,
            "maximum_drawdown_percent": stored_drawdown,
            "recent": recent_metrics,
            "unique_token_count": len(token_counts),
            "top_token_mint": top_token,
            "top_token_trade_concentration_percent": round(
                top_concentration,
                8,
            ),
            "best_trade_pnl_sol": round(best_pnl, 9),
            "net_pnl_without_best_trade_sol": round(stored_net - best_pnl, 9),
            "stability_windows": stability,
            "positive_stability_window_count": sum(
                _finite(item.get("net_pnl_sol")) > 0 for item in stability
            ),
            "worst_stability_window_profit_factor": min(
                (_finite(item.get("profit_factor")) for item in stability),
                default=0.0,
            ),
            "calculated_at": _iso(run_completed_at) if run_completed_at else None,
        },
        "copyability": {
            "execution_coverage_percent": _finite(
                run.execution_coverage_percent
                if run
                else wallet.backtest_execution_coverage_percent
            ),
            "matched_sell_ratio_percent": _finite(
                run.matched_sell_ratio_percent
                if run
                else wallet.backtest_matched_sell_ratio_percent
            ),
            "open_positions": _integer(
                run.open_positions if run else wallet.backtest_open_positions
            ),
            "jupiter_status": str(
                run.jupiter_status if run else wallet.backtest_jupiter_status
            ),
            "jupiter_compatibility_percent": _finite(
                run.jupiter_compatibility_percent
                if run
                else wallet.backtest_jupiter_compatibility_percent
            ),
            "jupiter_evidence_class": "CURRENT_ROUTE_CACHE_ONLY_NOT_HISTORICAL_QUOTE",
            "exitability_gate_status": wallet.exitability_gate_status,
            "exitability_gate_score": _finite(wallet.exitability_gate_score),
            "current_route_coverage_percent": _finite(
                wallet.exit_price_current_route_percent
            ),
            "exitability_calculated_at": _iso(
                wallet.exitability_gate_calculated_at
            )
            if wallet.exitability_gate_calculated_at
            else None,
            "backtest_starting_capital_sol": _finite(
                parameters.get("starting_capital_sol")
            ),
            "backtest_fixed_buy_size_sol": _finite(
                parameters.get("fixed_buy_size_sol")
            ),
            "backtest_slippage_bps": _integer(parameters.get("slippage_bps")),
            "backtest_fee_bps": _integer(parameters.get("fee_bps")),
            "backtest_copy_delay_seconds": _integer(
                parameters.get("copy_delay_seconds")
            ),
            "backtest_delay_penalty_bps_per_minute": _finite(
                parameters.get("delay_penalty_bps_per_minute")
            ),
            "backtest_max_open_positions": _integer(
                parameters.get("max_open_positions")
            ),
            "backtest_effective_market_friction_bps": _finite(
                parameters.get("effective_market_friction_bps")
            ),
            "historical_jupiter_quotes_invented": False,
        },
        "local_trade_evidence": dict(local_trade_evidence or {}),
        "independence": independence,
    }


def build_cached_discovery_snapshot(
    db: Session,
    *,
    limit: int = 500,
    policy: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    resolved_policy = {**M66_DEFAULT_POLICY, **dict(policy or {})}
    effective_limit = max(1, min(int(limit), 500))
    snapshot_at = now or utc_now()
    wallet_rows_total = int(
        db.query(func.count(DiscoveredWallet.id)).scalar() or 0
    )
    wallets = (
        db.query(DiscoveredWallet)
        .order_by(
            DiscoveredWallet.ranking_score.desc(),
            DiscoveredWallet.smart_score.desc(),
            DiscoveredWallet.wallet_address.asc(),
        )
        .limit(effective_limit)
        .all()
    )
    addresses = [str(wallet.wallet_address) for wallet in wallets]
    runs: list[CandidateBacktestRun] = []
    edges: list[WalletEdge] = []
    trade_inventory_rows: list[Any] = []
    recent_trade_rows: list[Trade] = []
    if addresses:
        runs = (
            db.query(CandidateBacktestRun)
            .filter(CandidateBacktestRun.wallet_address.in_(addresses))
            .filter(CandidateBacktestRun.status == "COMPLETED")
            .order_by(
                CandidateBacktestRun.wallet_address.asc(),
                CandidateBacktestRun.completed_at.desc(),
                CandidateBacktestRun.id.desc(),
            )
            .all()
        )
        edges = (
            db.query(WalletEdge)
            .filter(
                or_(
                    WalletEdge.source_wallet.in_(addresses),
                    WalletEdge.target_wallet.in_(addresses),
                )
            )
            .order_by(WalletEdge.id.asc())
            .all()
        )
        trade_inventory_rows = (
            db.query(
                Trade.wallet_address,
                func.count(Trade.id),
                func.min(Trade.block_time),
                func.max(Trade.block_time),
                func.count(func.distinct(Trade.token_mint)),
            )
            .filter(Trade.wallet_address.in_(addresses))
            .filter(Trade.success.is_(True))
            .filter(Trade.block_time.isnot(None))
            .group_by(Trade.wallet_address)
            .order_by(Trade.wallet_address.asc())
            .all()
        )
        recent_trade_rows = (
            db.query(Trade)
            .filter(Trade.wallet_address.in_(addresses))
            .filter(Trade.success.is_(True))
            .filter(Trade.block_time.isnot(None))
            .filter(Trade.block_time >= snapshot_at - timedelta(days=7))
            .order_by(
                Trade.wallet_address.asc(),
                Trade.block_time.asc(),
                Trade.id.asc(),
            )
            .all()
        )
    latest_by_wallet: dict[str, CandidateBacktestRun] = {}
    for run in runs:
        latest_by_wallet.setdefault(str(run.wallet_address), run)
    independence = _cluster_evidence(
        addresses,
        edges,
        shared_token_threshold=int(
            resolved_policy["shared_token_cluster_threshold"]
        ),
    )
    inventory_by_wallet: dict[str, dict[str, Any]] = {}
    for (
        wallet_address,
        lifetime_rows,
        oldest_swap_at,
        latest_swap_at,
        lifetime_unique_tokens,
    ) in trade_inventory_rows:
        oldest = _parse_datetime(oldest_swap_at)
        latest = _parse_datetime(latest_swap_at)
        history_span_days = (
            max(0.0, (latest - oldest).total_seconds() / 86400.0)
            if oldest is not None and latest is not None
            else 0.0
        )
        inventory_by_wallet[str(wallet_address)] = {
            "lifetime_swap_rows": _integer(lifetime_rows),
            "oldest_swap_at": oldest,
            "latest_swap_at": latest,
            "lifetime_unique_tokens": _integer(lifetime_unique_tokens),
            "cached_history_span_days": history_span_days,
        }
    recent_by_wallet: dict[str, list[Trade]] = defaultdict(list)
    for trade in recent_trade_rows:
        recent_by_wallet[str(trade.wallet_address)].append(trade)

    candidates: list[dict[str, Any]] = []
    for wallet in wallets:
        address = str(wallet.wallet_address)
        inventory = inventory_by_wallet.get(
            address,
            {
                "lifetime_swap_rows": 0,
                "oldest_swap_at": None,
                "latest_swap_at": None,
                "lifetime_unique_tokens": 0,
                "cached_history_span_days": 0.0,
            },
        )
        local_rows = recent_by_wallet.get(address, [])
        activity = analyze_wallet_activity_from_trades(
            address,
            local_rows,
            latest_trade_at=inventory.get("latest_swap_at"),
            now=snapshot_at,
        )
        quality = analyze_wallet_quality_from_trades(
            address,
            local_rows,
            smart_score=_finite(wallet.smart_score),
            activity=activity,
            now=snapshot_at,
        )
        local_evidence = _local_trade_evidence(
            inventory=inventory,
            activity=activity,
            quality=quality,
            policy=resolved_policy,
        )
        candidates.append(
            _candidate_from_models(
                wallet,
                latest_by_wallet.get(address),
                independence[address],
                policy=resolved_policy,
                activity_override=activity,
                quality_override=quality,
                local_trade_evidence=local_evidence,
            )
        )
    snapshot: dict[str, Any] = {
        "scope": M66_SNAPSHOT_SCOPE,
        "discovery_version": M66_DISCOVERY_VERSION,
        "snapshot_at_utc": _iso(snapshot_at),
        "source": {
            "mode": "CACHED_DATABASE_READ_ONLY",
            "wallet_limit": effective_limit,
            "wallet_rows_total": wallet_rows_total,
            "wallet_rows_read": len(wallets),
            "wallet_rows_truncated": wallet_rows_total > len(wallets),
            "backtest_rows_read": len(runs),
            "wallet_edge_rows_read": len(edges),
            "cached_trade_rows_lifetime": sum(
                _integer(item.get("lifetime_swap_rows"))
                for item in inventory_by_wallet.values()
            ),
            "cached_trade_rows_7d": len(recent_trade_rows),
            "wallets_with_cached_trade_evidence": len(inventory_by_wallet),
            "wallets_with_cached_recent_trade_evidence": len(
                recent_by_wallet
            ),
            "database_query_count": 6 if addresses else 2,
            "network_requests": 0,
            "helius_requests": 0,
            "jupiter_requests": 0,
        },
        "candidates": candidates,
        "safety": {
            "cached_only": True,
            "database_writes": 0,
            "backend_posts": 0,
            "public_rpc_requests": 0,
            "helius_requests": 0,
            "jupiter_requests": 0,
            "paper_orders": 0,
            "live_orders": 0,
            "signed_transactions": 0,
            "submitted_transactions": 0,
            "signer_access": False,
            "discovery_cron_changed": False,
            "wallets_applied": False,
        },
    }
    snapshot["integrity"] = {
        "snapshot_payload_sha256": canonical_sha256(snapshot)
    }
    return snapshot


def validate_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    _require(snapshot.get("scope") == M66_SNAPSHOT_SCOPE, "Scope snapshot M66 inatteso.")
    _require(
        snapshot.get("discovery_version") == M66_DISCOVERY_VERSION,
        "Versione snapshot M66 inattesa.",
    )
    integrity = dict(snapshot.get("integrity") or {})
    expected_hash = str(integrity.get("snapshot_payload_sha256") or "")
    _require(len(expected_hash) == 64, "Hash snapshot M66 assente.")
    _require(
        expected_hash == canonical_sha256(_without_key(snapshot, "integrity")),
        "Hash snapshot M66 non valido.",
    )
    safety = dict(snapshot.get("safety") or {})
    for field in (
        "network_requests",
        "database_writes",
        "backend_posts",
        "public_rpc_requests",
        "helius_requests",
        "jupiter_requests",
        "paper_orders",
        "live_orders",
        "signed_transactions",
        "submitted_transactions",
    ):
        _require(
            _integer(safety.get(field)) == 0,
            f"Vincolo snapshot M66 violato: {field}.",
        )
    _require(safety.get("signer_access") is False, "Snapshot M66 con signer access.")
    _require(safety.get("cached_only") is True, "Snapshot M66 non cached-only.")
    _require(
        safety.get("wallets_applied") is False,
        "Snapshot M66 ha applicato wallet.",
    )
    _require(
        safety.get("discovery_cron_changed") is False,
        "Snapshot M66 ha modificato Discovery cron.",
    )
    candidates = [dict(item) for item in snapshot.get("candidates") or []]
    source = dict(snapshot.get("source") or {})
    wallet_rows_read = _integer(
        source.get("wallet_rows_read"),
        default=len(candidates),
    )
    wallet_rows_total = _integer(
        source.get("wallet_rows_total"),
        default=wallet_rows_read,
    )
    _require(
        wallet_rows_read == len(candidates),
        "Conteggio wallet letti M66 incoerente con i candidati.",
    )
    _require(
        wallet_rows_total >= wallet_rows_read,
        "Inventario wallet totale M66 inferiore alle righe lette.",
    )
    _require(
        bool(source.get("wallet_rows_truncated", False))
        == (wallet_rows_total > wallet_rows_read),
        "Flag troncamento inventario wallet M66 incoerente.",
    )
    seen: set[str] = set()
    local_lifetime_total = 0
    local_recent_total = 0
    local_wallets_with_evidence = 0
    local_wallets_with_recent_evidence = 0
    for index, candidate in enumerate(candidates, start=1):
        address = str(candidate.get("wallet_address") or "")
        _require(bool(address), f"Wallet assente nel candidato M66 #{index}.")
        _require(address not in seen, f"Wallet duplicato nello snapshot M66: {address}.")
        seen.add(address)
        local = dict(candidate.get("local_trade_evidence") or {})
        if local:
            _require(
                local.get("enrichment_version")
                == M66_CACHED_TRADE_ENRICHMENT_VERSION,
                f"Versione enrichment Trade cached inattesa: {address}.",
            )
            lifetime_rows = _integer(local.get("lifetime_swap_rows"))
            recent_rows = _integer(local.get("recent_swap_rows_7d"))
            _require(
                lifetime_rows >= 0 and 0 <= recent_rows <= lifetime_rows,
                f"Conteggi Trade cached incoerenti: {address}.",
            )
            _require(
                bool(local.get("available")) == (lifetime_rows > 0),
                f"Flag disponibilita Trade cached incoerente: {address}.",
            )
            _require(
                local.get("economic_metrics_inferred") is False,
                f"Metriche economiche inferite dai Trade cached: {address}.",
            )
            _require(
                local.get("historical_jupiter_quotes_invented") is False,
                f"Quote Jupiter storiche inventate: {address}.",
            )
            local_lifetime_total += lifetime_rows
            local_recent_total += recent_rows
            local_wallets_with_evidence += int(lifetime_rows > 0)
            local_wallets_with_recent_evidence += int(recent_rows > 0)
    if any("local_trade_evidence" in candidate for candidate in candidates):
        _require(
            _integer(source.get("cached_trade_rows_lifetime"))
            == local_lifetime_total,
            "Totale Trade cached lifetime incoerente.",
        )
        _require(
            _integer(source.get("cached_trade_rows_7d")) == local_recent_total,
            "Totale Trade cached 7d incoerente.",
        )
        _require(
            _integer(source.get("wallets_with_cached_trade_evidence"))
            == local_wallets_with_evidence,
            "Copertura wallet con Trade cached incoerente.",
        )
        _require(
            _integer(source.get("wallets_with_cached_recent_trade_evidence"))
            == local_wallets_with_recent_evidence,
            "Copertura wallet con Trade cached recenti incoerente.",
        )
    return {
        "snapshot_payload_sha256": expected_hash,
        "candidate_count": len(candidates),
        "wallet_rows_total": wallet_rows_total,
        "wallet_rows_read": wallet_rows_read,
        "local_lifetime_trade_rows": local_lifetime_total,
        "local_recent_trade_rows": local_recent_total,
        "local_wallets_with_evidence": local_wallets_with_evidence,
        "local_wallets_with_recent_evidence": local_wallets_with_recent_evidence,
        "candidates": candidates,
    }


def _add_check(
    checks: list[dict[str, Any]],
    failures: set[str],
    *,
    category: str,
    code: str,
    passed: bool,
    actual: Any,
    operator: str,
    threshold: Any,
) -> None:
    checks.append(
        {
            "category": category,
            "code": code,
            "status": "PASS" if passed else "FAIL",
            "actual": actual,
            "operator": operator,
            "threshold": threshold,
        }
    )
    if not passed:
        failures.add(code)


def _candidate_score(candidate: dict[str, Any], policy: dict[str, Any]) -> dict[str, float]:
    economics = dict(candidate.get("economics") or {})
    recent = dict(economics.get("recent") or {})
    activity = dict(candidate.get("activity") or {})
    quality = dict(candidate.get("quality") or {})
    copyability = dict(candidate.get("copyability") or {})
    independence = dict(candidate.get("independence") or {})

    pf = _finite(economics.get("profit_factor"))
    recent_pf = _finite(recent.get("profit_factor"))
    drawdown = _finite(economics.get("maximum_drawdown_percent"), default=100.0)
    economic_score = (
        min(100.0, pf / float(policy["minimum_profit_factor"]) * 60.0)
        + min(20.0, recent_pf / float(policy["minimum_recent_profit_factor"]) * 20.0)
        + max(0.0, 20.0 - drawdown)
    )
    copyability_score = (
        _clip(activity.get("score")) * 0.20
        + _clip(quality.get("score")) * 0.30
        + _clip(copyability.get("execution_coverage_percent")) * 0.20
        + _clip(copyability.get("matched_sell_ratio_percent")) * 0.15
        + _clip(copyability.get("exitability_gate_score")) * 0.15
    )
    sample_score = min(
        100.0,
        _integer(economics.get("closed_trade_count"))
        / max(1, int(policy["minimum_closed_trades"]))
        * 100.0,
    )
    independence_score = (
        100.0
        if _integer(independence.get("cluster_size"), default=1) == 1
        else 20.0
    )
    total = (
        economic_score * 0.45
        + copyability_score * 0.35
        + sample_score * 0.10
        + independence_score * 0.10
    )
    return {
        "total": round(_clip(total), 4),
        "economic": round(_clip(economic_score), 4),
        "copyability": round(_clip(copyability_score), 4),
        "data_completeness": round(_clip(sample_score), 4),
        "independence": round(_clip(independence_score), 4),
    }


def evaluate_candidate(
    candidate: dict[str, Any],
    *,
    policy: dict[str, Any],
    evaluated_at: datetime,
) -> dict[str, Any]:
    address = str(candidate.get("wallet_address") or "")
    activity = dict(candidate.get("activity") or {})
    quality = dict(candidate.get("quality") or {})
    economics = dict(candidate.get("economics") or {})
    recent = dict(economics.get("recent") or {})
    copyability = dict(candidate.get("copyability") or {})
    independence = dict(candidate.get("independence") or {})
    local_trade_evidence = dict(candidate.get("local_trade_evidence") or {})
    checks: list[dict[str, Any]] = []
    failures: set[str] = set()

    address_valid = bool(_SOLANA_ADDRESS.fullmatch(address))
    _add_check(
        checks,
        failures,
        category="INTEGRITY",
        code="INVALID_SOLANA_WALLET_ADDRESS",
        passed=address_valid,
        actual=address,
        operator="MATCHES",
        threshold="BASE58_32_TO_44",
    )

    economics_missing = str(economics.get("evidence_class")) == "MISSING"
    local_evidence_declared = bool(local_trade_evidence)
    if local_evidence_declared and economics_missing:
        _add_check(
            checks,
            failures,
            category="LOCAL_EVIDENCE",
            code="NO_CACHED_TRADE_EVIDENCE",
            passed=bool(local_trade_evidence.get("available")),
            actual=_integer(local_trade_evidence.get("lifetime_swap_rows")),
            operator=">",
            threshold=0,
        )
        _add_check(
            checks,
            failures,
            category="LOCAL_EVIDENCE",
            code="CACHED_TRADE_PRESCREEN_FAILED",
            passed=bool(local_trade_evidence.get("prescreen_passed")),
            actual=local_trade_evidence.get("prescreen_status"),
            operator="==",
            threshold="PASS_ZERO_CREDIT_COPYABILITY_PRESCREEN",
        )

    closed = _integer(economics.get("closed_trade_count"))
    history_days = _finite(economics.get("history_span_days"))
    recent_closed = _integer(recent.get("closed_trade_count"))
    position_complete = bool(economics.get("position_level_evidence_complete"))
    _add_check(checks, failures, category="SAMPLE", code="HISTORICAL_CLOSED_SAMPLE_BELOW_MINIMUM", passed=closed >= int(policy["minimum_closed_trades"]), actual=closed, operator=">=", threshold=int(policy["minimum_closed_trades"]))
    _add_check(checks, failures, category="SAMPLE", code="HISTORY_SPAN_BELOW_MINIMUM", passed=history_days >= float(policy["minimum_history_span_days"]), actual=history_days, operator=">=", threshold=float(policy["minimum_history_span_days"]))
    _add_check(checks, failures, category="SAMPLE", code="RECENT_CLOSED_SAMPLE_BELOW_MINIMUM", passed=recent_closed >= int(policy["minimum_recent_closed_trades"]), actual=recent_closed, operator=">=", threshold=int(policy["minimum_recent_closed_trades"]))
    _add_check(checks, failures, category="SAMPLE", code="POSITION_LEVEL_EVIDENCE_INCOMPLETE", passed=position_complete, actual=position_complete, operator="==", threshold=True)

    net_pnl = _finite(economics.get("net_pnl_sol"))
    pf = _finite(economics.get("profit_factor"))
    win_rate = _finite(economics.get("win_rate_percent"))
    drawdown = _finite(economics.get("maximum_drawdown_percent"), default=100.0)
    recent_net = _finite(recent.get("net_pnl_sol"))
    recent_pf = _finite(recent.get("profit_factor"))
    recent_drawdown = _finite(recent.get("maximum_drawdown_percent"), default=100.0)
    unique_tokens = _integer(economics.get("unique_token_count"))
    concentration = _finite(economics.get("top_token_trade_concentration_percent"), default=100.0)
    net_without_best = _finite(economics.get("net_pnl_without_best_trade_sol"))
    windows = list(economics.get("stability_windows") or [])
    positive_windows = _integer(economics.get("positive_stability_window_count"))
    worst_pf = _finite(economics.get("worst_stability_window_profit_factor"))
    _add_check(checks, failures, category="ECONOMIC", code="NET_PNL_NOT_POSITIVE", passed=net_pnl > float(policy["minimum_net_pnl_sol"]), actual=net_pnl, operator=">", threshold=float(policy["minimum_net_pnl_sol"]))
    _add_check(checks, failures, category="ECONOMIC", code="PROFIT_FACTOR_BELOW_DISCOVERY_BUFFER", passed=pf >= float(policy["minimum_profit_factor"]), actual=pf, operator=">=", threshold=float(policy["minimum_profit_factor"]))
    _add_check(checks, failures, category="ECONOMIC", code="WIN_RATE_BELOW_MINIMUM", passed=win_rate >= float(policy["minimum_win_rate_percent"]), actual=win_rate, operator=">=", threshold=float(policy["minimum_win_rate_percent"]))
    _add_check(checks, failures, category="ECONOMIC", code="DRAWDOWN_ABOVE_MAXIMUM", passed=drawdown <= float(policy["maximum_drawdown_percent"]), actual=drawdown, operator="<=", threshold=float(policy["maximum_drawdown_percent"]))
    _add_check(checks, failures, category="ECONOMIC", code="RECENT_NET_PNL_NOT_POSITIVE", passed=recent_net > float(policy["minimum_recent_net_pnl_sol"]), actual=recent_net, operator=">", threshold=float(policy["minimum_recent_net_pnl_sol"]))
    _add_check(checks, failures, category="ECONOMIC", code="RECENT_PROFIT_FACTOR_BELOW_MINIMUM", passed=recent_pf >= float(policy["minimum_recent_profit_factor"]), actual=recent_pf, operator=">=", threshold=float(policy["minimum_recent_profit_factor"]))
    _add_check(checks, failures, category="ECONOMIC", code="RECENT_DRAWDOWN_ABOVE_MAXIMUM", passed=recent_drawdown <= float(policy["maximum_recent_drawdown_percent"]), actual=recent_drawdown, operator="<=", threshold=float(policy["maximum_recent_drawdown_percent"]))
    _add_check(checks, failures, category="ECONOMIC", code="UNIQUE_TOKEN_SAMPLE_BELOW_MINIMUM", passed=unique_tokens >= int(policy["minimum_unique_tokens"]), actual=unique_tokens, operator=">=", threshold=int(policy["minimum_unique_tokens"]))
    _add_check(checks, failures, category="ECONOMIC", code="TOKEN_CONCENTRATION_ABOVE_MAXIMUM", passed=concentration <= float(policy["maximum_token_concentration_percent"]), actual=concentration, operator="<=", threshold=float(policy["maximum_token_concentration_percent"]))
    if bool(policy["require_positive_net_without_best_trade"]):
        _add_check(checks, failures, category="ECONOMIC", code="BEST_TRADE_DEPENDENCY_EXCESSIVE", passed=net_without_best > 0, actual=net_without_best, operator=">", threshold=0)
    _add_check(checks, failures, category="ECONOMIC", code="STABILITY_WINDOWS_BELOW_MINIMUM", passed=len(windows) >= int(policy["minimum_stability_windows"]), actual=len(windows), operator=">=", threshold=int(policy["minimum_stability_windows"]))
    _add_check(checks, failures, category="ECONOMIC", code="POSITIVE_STABILITY_WINDOWS_BELOW_MINIMUM", passed=positive_windows >= int(policy["minimum_positive_stability_windows"]), actual=positive_windows, operator=">=", threshold=int(policy["minimum_positive_stability_windows"]))
    _add_check(checks, failures, category="ECONOMIC", code="WORST_STABILITY_PROFIT_FACTOR_BELOW_MINIMUM", passed=worst_pf >= float(policy["minimum_worst_stability_profit_factor"]), actual=worst_pf, operator=">=", threshold=float(policy["minimum_worst_stability_profit_factor"]))

    activity_age = _age_hours(activity.get("calculated_at"), evaluated_at)
    backtest_age = _age_hours(economics.get("calculated_at"), evaluated_at)
    exitability_age = _age_hours(copyability.get("exitability_calculated_at"), evaluated_at)
    _add_check(checks, failures, category="COPYABILITY", code="ACTIVITY_NOT_ACTIVE", passed=str(activity.get("classification")) == "ATTIVO", actual=activity.get("classification"), operator="==", threshold="ATTIVO")
    _add_check(checks, failures, category="COPYABILITY", code="ACTIVITY_SCORE_BELOW_MINIMUM", passed=_finite(activity.get("score")) >= float(policy["minimum_activity_score"]), actual=_finite(activity.get("score")), operator=">=", threshold=float(policy["minimum_activity_score"]))
    _add_check(checks, failures, category="COPYABILITY", code="SWAPS_7D_BELOW_MINIMUM", passed=_integer(activity.get("swaps_7d")) >= int(policy["minimum_swaps_7d"]), actual=_integer(activity.get("swaps_7d")), operator=">=", threshold=int(policy["minimum_swaps_7d"]))
    _add_check(checks, failures, category="COPYABILITY", code="SWAPS_7D_ABOVE_MAXIMUM", passed=_integer(activity.get("swaps_7d")) <= int(policy["maximum_swaps_7d"]), actual=_integer(activity.get("swaps_7d")), operator="<=", threshold=int(policy["maximum_swaps_7d"]))
    _add_check(checks, failures, category="COPYABILITY", code="ACTIVE_DAYS_7D_BELOW_MINIMUM", passed=_integer(activity.get("active_days_7d")) >= int(policy["minimum_active_days_7d"]), actual=_integer(activity.get("active_days_7d")), operator=">=", threshold=int(policy["minimum_active_days_7d"]))
    _add_check(checks, failures, category="FRESHNESS", code="ACTIVITY_EVIDENCE_STALE_OR_MISSING", passed=activity_age is not None and activity_age <= float(policy["maximum_activity_evidence_age_hours"]), actual=activity_age, operator="<=", threshold=float(policy["maximum_activity_evidence_age_hours"]))
    _add_check(checks, failures, category="COPYABILITY", code="QUALITY_NOT_COPYABLE", passed=str(quality.get("classification")) == "COPIABILE", actual=quality.get("classification"), operator="==", threshold="COPIABILE")
    _add_check(checks, failures, category="COPYABILITY", code="QUALITY_SCORE_BELOW_MINIMUM", passed=_finite(quality.get("score")) >= float(policy["minimum_quality_score"]), actual=_finite(quality.get("score")), operator=">=", threshold=float(policy["minimum_quality_score"]))
    _add_check(checks, failures, category="COPYABILITY", code="DUST_RATIO_ABOVE_MAXIMUM", passed=_finite(quality.get("dust_ratio_7d"), default=1.0) <= float(policy["maximum_dust_ratio"]), actual=_finite(quality.get("dust_ratio_7d"), default=1.0), operator="<=", threshold=float(policy["maximum_dust_ratio"]))
    _add_check(checks, failures, category="COPYABILITY", code="SIZE_COMPATIBILITY_BELOW_MINIMUM", passed=_finite(quality.get("size_compatibility_ratio_7d")) >= float(policy["minimum_size_compatibility_ratio"]), actual=_finite(quality.get("size_compatibility_ratio_7d")), operator=">=", threshold=float(policy["minimum_size_compatibility_ratio"]))
    _add_check(checks, failures, category="COPYABILITY", code="INVALID_SWAP_AMOUNTS_PRESENT", passed=_integer(quality.get("invalid_amount_swaps_7d")) == 0, actual=_integer(quality.get("invalid_amount_swaps_7d")), operator="==", threshold=0)
    _add_check(checks, failures, category="COPYABILITY", code="EXECUTION_COVERAGE_BELOW_MINIMUM", passed=_finite(copyability.get("execution_coverage_percent")) >= float(policy["minimum_execution_coverage_percent"]), actual=_finite(copyability.get("execution_coverage_percent")), operator=">=", threshold=float(policy["minimum_execution_coverage_percent"]))
    _add_check(checks, failures, category="COPYABILITY", code="MATCHED_SELL_RATIO_BELOW_MINIMUM", passed=_finite(copyability.get("matched_sell_ratio_percent")) >= float(policy["minimum_matched_sell_ratio_percent"]), actual=_finite(copyability.get("matched_sell_ratio_percent")), operator=">=", threshold=float(policy["minimum_matched_sell_ratio_percent"]))
    _add_check(checks, failures, category="COPYABILITY", code="OPEN_POSITIONS_PRESENT", passed=_integer(copyability.get("open_positions")) <= int(policy["maximum_open_positions"]), actual=_integer(copyability.get("open_positions")), operator="<=", threshold=int(policy["maximum_open_positions"]))
    _add_check(checks, failures, category="COPYABILITY", code="EXITABILITY_NOT_READY", passed=str(copyability.get("exitability_gate_status")) == "READY", actual=copyability.get("exitability_gate_status"), operator="==", threshold="READY")
    _add_check(checks, failures, category="COPYABILITY", code="EXITABILITY_SCORE_BELOW_MINIMUM", passed=_finite(copyability.get("exitability_gate_score")) >= float(policy["minimum_exitability_score"]), actual=_finite(copyability.get("exitability_gate_score")), operator=">=", threshold=float(policy["minimum_exitability_score"]))
    _add_check(checks, failures, category="COPYABILITY", code="CURRENT_ROUTE_COVERAGE_BELOW_MINIMUM", passed=_finite(copyability.get("current_route_coverage_percent")) >= float(policy["minimum_current_route_coverage_percent"]), actual=_finite(copyability.get("current_route_coverage_percent")), operator=">=", threshold=float(policy["minimum_current_route_coverage_percent"]))
    _add_check(checks, failures, category="COPYABILITY", code="JUPITER_CURRENT_ROUTE_NOT_PASSED", passed=str(copyability.get("jupiter_status")) == "PASSED", actual=copyability.get("jupiter_status"), operator="==", threshold="PASSED")
    _add_check(checks, failures, category="COPYABILITY", code="JUPITER_CURRENT_ROUTE_COMPATIBILITY_BELOW_MINIMUM", passed=_finite(copyability.get("jupiter_compatibility_percent")) >= float(policy["minimum_jupiter_compatibility_percent"]), actual=_finite(copyability.get("jupiter_compatibility_percent")), operator=">=", threshold=float(policy["minimum_jupiter_compatibility_percent"]))
    _add_check(checks, failures, category="FRESHNESS", code="BACKTEST_EVIDENCE_STALE_OR_MISSING", passed=backtest_age is not None and backtest_age <= float(policy["maximum_backtest_evidence_age_hours"]), actual=backtest_age, operator="<=", threshold=float(policy["maximum_backtest_evidence_age_hours"]))
    _add_check(checks, failures, category="FRESHNESS", code="EXITABILITY_EVIDENCE_STALE_OR_MISSING", passed=exitability_age is not None and exitability_age <= float(policy["maximum_exitability_evidence_age_hours"]), actual=exitability_age, operator="<=", threshold=float(policy["maximum_exitability_evidence_age_hours"]))
    _add_check(checks, failures, category="MODEL", code="BACKTEST_STARTING_CAPITAL_NOT_GEN4", passed=math.isclose(_finite(copyability.get("backtest_starting_capital_sol")), float(policy["required_backtest_starting_capital_sol"]), rel_tol=0.0, abs_tol=1e-9), actual=_finite(copyability.get("backtest_starting_capital_sol")), operator="==", threshold=float(policy["required_backtest_starting_capital_sol"]))
    _add_check(checks, failures, category="MODEL", code="BACKTEST_FIXED_BUY_SIZE_NOT_GEN4", passed=math.isclose(_finite(copyability.get("backtest_fixed_buy_size_sol")), float(policy["required_backtest_fixed_buy_size_sol"]), rel_tol=0.0, abs_tol=1e-9), actual=_finite(copyability.get("backtest_fixed_buy_size_sol")), operator="==", threshold=float(policy["required_backtest_fixed_buy_size_sol"]))
    _add_check(checks, failures, category="MODEL", code="BACKTEST_SLIPPAGE_NOT_GEN4", passed=_integer(copyability.get("backtest_slippage_bps")) == int(policy["required_backtest_slippage_bps"]), actual=_integer(copyability.get("backtest_slippage_bps")), operator="==", threshold=int(policy["required_backtest_slippage_bps"]))
    _add_check(checks, failures, category="MODEL", code="BACKTEST_FEE_NOT_GEN4", passed=_integer(copyability.get("backtest_fee_bps")) == int(policy["required_backtest_fee_bps"]), actual=_integer(copyability.get("backtest_fee_bps")), operator="==", threshold=int(policy["required_backtest_fee_bps"]))
    _add_check(checks, failures, category="MODEL", code="BACKTEST_COPY_DELAY_NOT_GEN4", passed=_integer(copyability.get("backtest_copy_delay_seconds")) == int(policy["required_backtest_copy_delay_seconds"]), actual=_integer(copyability.get("backtest_copy_delay_seconds")), operator="==", threshold=int(policy["required_backtest_copy_delay_seconds"]))
    _add_check(checks, failures, category="MODEL", code="BACKTEST_DELAY_PENALTY_NOT_GEN4", passed=math.isclose(_finite(copyability.get("backtest_delay_penalty_bps_per_minute")), float(policy["required_backtest_delay_penalty_bps_per_minute"]), rel_tol=0.0, abs_tol=1e-9), actual=_finite(copyability.get("backtest_delay_penalty_bps_per_minute")), operator="==", threshold=float(policy["required_backtest_delay_penalty_bps_per_minute"]))
    _add_check(checks, failures, category="MODEL", code="BACKTEST_MAX_OPEN_POSITIONS_NOT_GEN4", passed=_integer(copyability.get("backtest_max_open_positions")) == int(policy["required_backtest_max_open_positions"]), actual=_integer(copyability.get("backtest_max_open_positions")), operator="==", threshold=int(policy["required_backtest_max_open_positions"]))
    _add_check(checks, failures, category="MODEL", code="BACKTEST_EFFECTIVE_FRICTION_NOT_GEN4", passed=math.isclose(_finite(copyability.get("backtest_effective_market_friction_bps")), float(policy["required_effective_market_friction_bps"]), rel_tol=0.0, abs_tol=1e-4), actual=_finite(copyability.get("backtest_effective_market_friction_bps")), operator="==", threshold=float(policy["required_effective_market_friction_bps"]))

    sample_codes = {
        "HISTORICAL_CLOSED_SAMPLE_BELOW_MINIMUM",
        "HISTORY_SPAN_BELOW_MINIMUM",
        "RECENT_CLOSED_SAMPLE_BELOW_MINIMUM",
        "POSITION_LEVEL_EVIDENCE_INCOMPLETE",
        "STABILITY_WINDOWS_BELOW_MINIMUM",
    }
    hard_integrity_codes = {"INVALID_SOLANA_WALLET_ADDRESS"}
    hard_copyability_codes = {
        "INVALID_SWAP_AMOUNTS_PRESENT",
        "OPEN_POSITIONS_PRESENT",
    }
    quality_is_hard_failure = bool(
        "QUALITY_NOT_COPYABLE" in failures
        and (
            not economics_missing
            or str(quality.get("classification"))
            in {QUALITY_CLASS_NOT_COPYABLE, QUALITY_CLASS_SUSPICIOUS}
        )
    )
    hard_local_evidence_codes = {
        "NO_CACHED_TRADE_EVIDENCE",
        "CACHED_TRADE_PRESCREEN_FAILED",
    }
    severe_economic = bool(
        closed >= int(policy["minimum_preliminary_closed_trades"])
        and (
            net_pnl <= 0
            or pf < float(policy["minimum_preliminary_profit_factor"])
            or drawdown > float(policy["maximum_preliminary_drawdown_percent"])
            or (
                bool(policy["require_positive_net_without_best_trade"])
                and position_complete
                and net_without_best <= 0
            )
        )
    )

    if failures & hard_integrity_codes:
        status = STATUS_BLOCKED
        action = ACTION_RESEARCH_ONLY
    elif failures & hard_local_evidence_codes:
        status = STATUS_BLOCKED
        action = ACTION_RESEARCH_ONLY
    elif failures & hard_copyability_codes or quality_is_hard_failure:
        status = STATUS_BLOCKED
        action = ACTION_RESEARCH_ONLY
    elif severe_economic:
        status = STATUS_RESEARCH_ONLY
        action = ACTION_RESEARCH_ONLY
    elif failures & sample_codes:
        status = STATUS_NEEDS_HISTORY
        action = ACTION_TARGETED_HISTORY
    elif any(
        item["category"] == "ECONOMIC" and item["status"] == "FAIL"
        for item in checks
    ):
        status = STATUS_RESEARCH_ONLY
        action = ACTION_RESEARCH_ONLY
    elif failures:
        status = STATUS_NEEDS_FRESH_EVIDENCE
        action = ACTION_REFRESH_EVIDENCE
    else:
        status = STATUS_QUALIFIED
        action = ACTION_SHORT_CANARY

    scores = _candidate_score(candidate, policy)
    return {
        "wallet_address": address,
        "status": status,
        "recommended_action": action,
        "score": scores["total"],
        "score_components": scores,
        "failure_reasons": sorted(failures),
        "checks": checks,
        "analytics": {
            "closed_trade_count": closed,
            "history_span_days": history_days,
            "net_pnl_sol": net_pnl,
            "profit_factor": pf,
            "win_rate_percent": win_rate,
            "maximum_drawdown_percent": drawdown,
            "recent_closed_trade_count": recent_closed,
            "recent_net_pnl_sol": recent_net,
            "recent_profit_factor": recent_pf,
            "recent_maximum_drawdown_percent": recent_drawdown,
            "unique_token_count": unique_tokens,
            "top_token_trade_concentration_percent": concentration,
            "net_pnl_without_best_trade_sol": net_without_best,
            "positive_stability_window_count": positive_windows,
            "worst_stability_window_profit_factor": worst_pf,
            "cached_lifetime_swap_rows": _integer(
                local_trade_evidence.get("lifetime_swap_rows")
            ),
            "cached_recent_swap_rows_7d": _integer(
                local_trade_evidence.get("recent_swap_rows_7d")
            ),
            "cached_trade_prescreen_status": local_trade_evidence.get(
                "prescreen_status"
            ),
            "cached_trade_prescreen_passed": bool(
                local_trade_evidence.get("prescreen_passed")
            ),
            "economic_metrics_inferred_from_cached_trades": False,
        },
        "freshness": {
            "activity_evidence_age_hours": activity_age,
            "backtest_evidence_age_hours": backtest_age,
            "exitability_evidence_age_hours": exitability_age,
        },
        "independence": independence,
        "selection": {
            "selected": False,
            "rank": None,
            "cluster_collision": False,
            "manual_independence_confirmation_required": True,
        },
        "short_canary_required": status == STATUS_QUALIFIED,
        "micro_live_execution_authorized": False,
    }


def _select_wallets(
    results: list[dict[str, Any]],
    *,
    maximum_wallets: int,
) -> list[dict[str, Any]]:
    qualified = sorted(
        [item for item in results if item["status"] == STATUS_QUALIFIED],
        key=lambda item: (-_finite(item["score"]), item["wallet_address"]),
    )
    used_clusters: set[str] = set()
    selected: list[dict[str, Any]] = []
    for result in qualified:
        cluster_id = str(result.get("independence", {}).get("cluster_id") or "")
        if cluster_id in used_clusters:
            result["selection"]["cluster_collision"] = True
            continue
        if len(selected) >= maximum_wallets:
            continue
        used_clusters.add(cluster_id)
        result["selection"]["selected"] = True
        result["selection"]["rank"] = len(selected) + 1
        selected.append(
            {
                "rank": len(selected) + 1,
                "wallet_address": result["wallet_address"],
                "score": result["score"],
                "cluster_id": cluster_id,
                "status": result["status"],
                "next_step": ACTION_SHORT_CANARY,
                "manual_independence_confirmation_required": True,
                "micro_live_execution_authorized": False,
            }
        )
    return selected


def _recommended_requests(result: dict[str, Any], policy: dict[str, Any]) -> int:
    analytics = dict(result.get("analytics") or {})
    closed_gap = max(
        0,
        int(policy["minimum_closed_trades"])
        - _integer(analytics.get("closed_trade_count")),
    )
    history_gap = max(
        0.0,
        float(policy["minimum_history_span_days"])
        - _finite(analytics.get("history_span_days")),
    )
    base = max(5, math.ceil(closed_gap / 3.0), math.ceil(history_gap / 2.0))
    if result["status"] == STATUS_NEEDS_FRESH_EVIDENCE:
        base = max(8, min(base, 12))
    return min(int(policy["maximum_public_rpc_requests_per_wallet"]), base)


def _allocate_budget(
    results: list[dict[str, Any]],
    *,
    policy: dict[str, Any],
) -> dict[str, Any]:
    eligible_statuses = {STATUS_NEEDS_HISTORY, STATUS_NEEDS_FRESH_EVIDENCE}
    candidates = sorted(
        [item for item in results if item["status"] in eligible_statuses],
        key=lambda item: (-_finite(item["score"]), item["wallet_address"]),
    )[: int(policy["maximum_history_queue_wallets"])]
    budget = int(policy["daily_public_rpc_request_budget"])
    requested = {
        item["wallet_address"]: _recommended_requests(item, policy)
        for item in candidates
    }
    allocated = {item["wallet_address"]: 0 for item in candidates}
    remaining = budget
    while remaining > 0:
        changed = False
        for item in candidates:
            address = item["wallet_address"]
            if allocated[address] >= requested[address] or remaining <= 0:
                continue
            allocated[address] += 1
            remaining -= 1
            changed = True
        if not changed:
            break
    queue = [
        {
            "priority": index,
            "wallet_address": item["wallet_address"],
            "status": item["status"],
            "score": item["score"],
            "purpose": item["recommended_action"],
            "recommended_requests": requested[item["wallet_address"]],
            "allocated_requests": allocated[item["wallet_address"]],
            "provider": "PUBLIC_SOLANA_RPC_ONLY",
            "execution_authorized": False,
            "automatic": False,
        }
        for index, item in enumerate(candidates, start=1)
        if allocated[item["wallet_address"]] > 0
    ]
    total_allocated = sum(item["allocated_requests"] for item in queue)
    return {
        "daily_request_budget": budget,
        "maximum_requests_per_wallet": int(
            policy["maximum_public_rpc_requests_per_wallet"]
        ),
        "maximum_wallets": int(policy["maximum_history_queue_wallets"]),
        "wallets_queued": len(queue),
        "requests_allocated": total_allocated,
        "requests_unallocated": budget - total_allocated,
        "queue": queue,
        "execution_authorized": False,
        "automatic_enhanced_polling": False,
        "helius_requests": 0,
    }


def evaluate_copyability_aware_discovery(
    snapshot: dict[str, Any],
    *,
    policy: dict[str, Any] | None = None,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    validated = validate_snapshot(snapshot)
    resolved_policy = {**M66_DEFAULT_POLICY, **dict(policy or {})}
    _require(
        resolved_policy.get("policy_version") == M66_DISCOVERY_VERSION,
        "Versione policy M66 inattesa.",
    )
    now = evaluated_at or _parse_datetime(snapshot.get("snapshot_at_utc")) or utc_now()
    results = [
        evaluate_candidate(candidate, policy=resolved_policy, evaluated_at=now)
        for candidate in validated["candidates"]
    ]
    results.sort(
        key=lambda item: (
            {
                STATUS_QUALIFIED: 0,
                STATUS_NEEDS_FRESH_EVIDENCE: 1,
                STATUS_NEEDS_HISTORY: 2,
                STATUS_RESEARCH_ONLY: 3,
                STATUS_BLOCKED: 4,
            }[item["status"]],
            -_finite(item["score"]),
            item["wallet_address"],
        )
    )
    selected = _select_wallets(
        results,
        maximum_wallets=int(resolved_policy["maximum_selected_wallets"]),
    )
    acquisition_plan = _allocate_budget(results, policy=resolved_policy)
    status_counts = Counter(item["status"] for item in results)
    output: dict[str, Any] = {
        "discovery": "PASS",
        "scope": M66_SCOPE,
        "discovery_version": M66_DISCOVERY_VERSION,
        "evaluated_at_utc": _iso(now),
        "source": {
            "snapshot_payload_sha256": validated["snapshot_payload_sha256"],
            "candidate_count": validated["candidate_count"],
            "mode": snapshot.get("source", {}).get("mode"),
            "cached_wallets_total": _integer(
                validated["wallet_rows_total"],
            ),
            "cached_wallets_evaluated": _integer(
                validated["wallet_rows_read"],
            ),
            "cached_wallets_truncated": bool(
                snapshot.get("source", {}).get("wallet_rows_truncated", False)
            ),
            "database_query_count": _integer(
                snapshot.get("source", {}).get("database_query_count")
            ),
            "cached_trade_enrichment_version": (
                M66_CACHED_TRADE_ENRICHMENT_VERSION
            ),
            "cached_trade_rows_lifetime": _integer(
                snapshot.get("source", {}).get("cached_trade_rows_lifetime")
            ),
            "cached_trade_rows_7d": _integer(
                snapshot.get("source", {}).get("cached_trade_rows_7d")
            ),
        },
        "policy": resolved_policy,
        "policy_sha256": canonical_sha256(resolved_policy),
        "summary": {
            "cached_wallets_total_zero_helius_credits": _integer(
                validated["wallet_rows_total"],
            ),
            "cached_wallets_scanned_zero_helius_credits": len(results),
            "cached_wallets_with_completed_backtest": sum(
                str(item.get("source", {}).get("backtest_status")) == "COMPLETED"
                for item in validated["candidates"]
            ),
            "cached_wallets_with_complete_position_evidence": sum(
                bool(
                    item.get("economics", {}).get(
                        "position_level_evidence_complete"
                    )
                )
                for item in validated["candidates"]
            ),
            "cached_trade_rows_lifetime_zero_helius_credits": _integer(
                validated.get("local_lifetime_trade_rows")
            ),
            "cached_trade_rows_7d_zero_helius_credits": _integer(
                validated.get("local_recent_trade_rows")
            ),
            "cached_wallets_with_local_trade_evidence": _integer(
                validated.get("local_wallets_with_evidence")
            ),
            "cached_wallets_with_recent_local_trade_evidence": _integer(
                validated.get("local_wallets_with_recent_evidence")
            ),
            "cached_wallets_passing_zero_credit_trade_prescreen": sum(
                bool(
                    item.get("local_trade_evidence", {}).get(
                        "prescreen_passed"
                    )
                )
                for item in validated["candidates"]
            ),
            "cached_wallets_without_local_trade_evidence": sum(
                bool(item.get("local_trade_evidence"))
                and not bool(
                    item.get("local_trade_evidence", {}).get("available")
                )
                for item in validated["candidates"]
            ),
            "wallets_evaluated": len(results),
            "wallets_qualified_for_short_canary": status_counts[STATUS_QUALIFIED],
            "wallets_selected_for_short_canary": len(selected),
            "wallets_needing_targeted_history": status_counts[STATUS_NEEDS_HISTORY],
            "wallets_needing_fresh_copyability_evidence": status_counts[
                STATUS_NEEDS_FRESH_EVIDENCE
            ],
            "wallets_research_only": status_counts[STATUS_RESEARCH_ONLY],
            "wallets_blocked": status_counts[STATUS_BLOCKED],
            "maximum_selected_wallets": int(
                resolved_policy["maximum_selected_wallets"]
            ),
        },
        "selected_wallets": selected,
        "candidate_results": results,
        "acquisition_plan": acquisition_plan,
        "short_canary_contract": {
            "required": True,
            "minimum_observation_hours": resolved_policy[
                "canary_minimum_observation_hours"
            ],
            "minimum_entry_attempts": resolved_policy[
                "canary_minimum_entry_attempts"
            ],
            "minimum_closed_trades": resolved_policy[
                "canary_minimum_closed_trades"
            ],
            "minimum_webhook_coverage_percent": resolved_policy[
                "canary_minimum_webhook_coverage_percent"
            ],
            "minimum_unsigned_build_coverage_percent": resolved_policy[
                "canary_minimum_unsigned_build_coverage_percent"
            ],
            "maximum_entry_reject_rate_percent": resolved_policy[
                "canary_maximum_entry_reject_rate_percent"
            ],
            "maximum_p95_end_to_quote_ms": resolved_policy[
                "canary_maximum_p95_end_to_quote_ms"
            ],
            "maximum_p95_price_impact_bps": resolved_policy[
                "canary_maximum_p95_price_impact_bps"
            ],
            "maximum_p95_price_deterioration_bps": resolved_policy[
                "canary_maximum_p95_price_deterioration_bps"
            ],
            "zero_open_positions_required": True,
            "zero_unresolved_failures_required": True,
            "recovery_counts_as_realtime_proof": False,
        },
        "multi_wallet_consensus_readiness": {
            "implementation_phase": "M67_AFTER_M66_SELECTION",
            "activation_authorized": False,
            "window_seconds": resolved_policy["consensus_window_seconds"],
            "minimum_independent_wallets": resolved_policy[
                "consensus_minimum_independent_wallets"
            ],
            "maximum_wallets": resolved_policy["consensus_maximum_wallets"],
            "maximum_token_exposure_sol": resolved_policy[
                "consensus_maximum_token_exposure_sol"
            ],
            "same_cluster_signals_count": False,
            "copy_chain_signals_count": False,
            "deduplication_required": True,
            "manual_independence_confirmation_required": True,
        },
        "activation": {
            "discovery_cron_reactivation_authorized": False,
            "helius_reactivation_authorized": False,
            "micro_live_preparation_authorized": False,
            "micro_live_execution_authorized": False,
            "automatic_live_activation": False,
            "signer_authorized": False,
            "next_step": (
                "COLLECT_SHORT_REALTIME_CANARY_FOR_SELECTED_WALLETS"
                if selected
                else "EXECUTE_SEPARATELY_APPROVED_BUDGETED_DISCOVERY_ACQUISITION"
            ),
        },
        "safety": {
            "cached_only_evaluation": True,
            "network_requests": 0,
            "helius_requests": 0,
            "database_writes": 0,
            "backend_posts": 0,
            "jupiter_requests": 0,
            "paper_orders": 0,
            "live_orders": 0,
            "signed_transactions": 0,
            "submitted_transactions": 0,
            "signer_access": False,
            "official_realtime_counter_mutated": False,
            "recovery_counted_as_realtime_proof": False,
            "historical_jupiter_quotes_invented": False,
            "discovery_cron_changed": False,
            "primary_campaign_changed": False,
            "legacy_forward_feed_changed": False,
        },
    }
    output["integrity"] = {
        "decision_input_sha256": canonical_sha256(
            {
                "snapshot_payload_sha256": validated[
                    "snapshot_payload_sha256"
                ],
                "policy_sha256": output["policy_sha256"],
            }
        ),
        "report_payload_sha256": canonical_sha256(output),
    }
    return output


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise M66DiscoveryError(f"JSON M66 non leggibile: {path.name}.") from error
    if not isinstance(value, dict):
        raise M66DiscoveryError(f"JSON M66 root non oggetto: {path.name}.")
    return value


__all__ = [
    "ACTION_REFRESH_EVIDENCE",
    "ACTION_RESEARCH_ONLY",
    "ACTION_SHORT_CANARY",
    "ACTION_TARGETED_HISTORY",
    "M66_CACHED_TRADE_ENRICHMENT_VERSION",
    "M66_DEFAULT_POLICY",
    "M66_DISCOVERY_VERSION",
    "M66DiscoveryError",
    "M66_RUN_CONFIRMATION",
    "M66_SCOPE",
    "M66_SNAPSHOT_SCOPE",
    "STATUS_BLOCKED",
    "STATUS_NEEDS_FRESH_EVIDENCE",
    "STATUS_NEEDS_HISTORY",
    "STATUS_QUALIFIED",
    "STATUS_RESEARCH_ONLY",
    "build_cached_discovery_snapshot",
    "evaluate_candidate",
    "evaluate_copyability_aware_discovery",
    "load_json",
    "validate_snapshot",
    "write_json_atomic",
]
