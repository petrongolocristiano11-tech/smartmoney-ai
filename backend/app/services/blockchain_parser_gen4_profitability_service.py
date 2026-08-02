from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import median
from typing import Any, Iterable
from uuid import uuid4

from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.constants import GEN4_MANDATORY_EXCLUDED_PRICE_MINTS
from backend.app.models.candidate_backtest import CandidateBacktestRun
from backend.app.models.gen4_profitability import (
    CanonicalParserGen4ProfitabilityRun,
    CanonicalParserGen4ProfitabilityTrade,
    CanonicalParserGen4ProfitabilityWindow,
)
from backend.app.models.token_safety_snapshot import TokenSafetySnapshot
from backend.app.models.trade import Trade
from backend.app.models.wallet_edge import WalletEdge
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    sanitize_error_message,
)

GEN4_PROFITABILITY_POLICY_VERSION = "canonical-parser-gen4-walk-forward-profitability/2"
GEN4_PROFITABILITY_SCOPE = "HISTORICAL_SHADOW_ANALYTICS_ONLY"
GEN4_PROFITABILITY_CONFIRMATION = "RUN_GEN4_PROFITABILITY_VALIDATION"

LANE_STRICT = "STRICT_GEN4"
LANE_PROXY = "SIGNAL_ONLY_PROXY"
LANE_BASELINE = "SIMPLE_COPY_BASELINE"

VERDICT_NOT_EVALUABLE = "NOT_EVALUABLE"
VERDICT_NEGATIVE = "NEGATIVE_EVIDENCE"
VERDICT_PROXY_PROMISING = "PROXY_PROMISING_STRICT_EVIDENCE_MISSING"
VERDICT_PROMISING = "PROMISING_NOT_PROVEN"
VERDICT_PROFITABLE = "PROFITABLE_EVIDENCE"


class CanonicalParserGen4ProfitabilityError(ValueError):
    def __init__(self, message: str, *, code: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class PricePoint:
    trade_id: int
    signature: str
    wallet_address: str
    token_mint: str
    side: str
    occurred_at: datetime
    price_sol: float


@dataclass(frozen=True)
class Signal:
    lane: str
    token_mint: str
    signal_at: datetime
    contributing_wallets: tuple[str, ...]
    independent_cluster_count: int
    source_trade_ids: tuple[int, ...]
    source_signatures: tuple[str, ...]
    evidence: dict[str, Any]


@dataclass(frozen=True)
class CandidateOutcome:
    lane: str
    token_mint: str
    signal_at: datetime
    entry_at: datetime | None
    exit_at: datetime | None
    entry_price_sol: float | None
    exit_price_sol: float | None
    order_size_sol: float
    pnl_sol: float | None
    return_percent: float | None
    exit_reason: str | None
    contributing_wallets: tuple[str, ...]
    independent_cluster_count: int
    source_trade_ids: tuple[int, ...]
    evidence: dict[str, Any]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime:
    resolved = value or _utc_now()
    if resolved.tzinfo is None:
        return resolved.replace(tzinfo=timezone.utc)
    return resolved.astimezone(timezone.utc)


def _round(value: Any, digits: int = 8) -> float:
    try:
        resolved = float(value or 0.0)
    except (TypeError, ValueError):
        resolved = 0.0
    return round(resolved, digits)


def _actor(value: str | None) -> str:
    return (
        sanitize_error_message(value or "LOCAL_GEN4_PROFITABILITY_VALIDATION", max_length=80)
        or "LOCAL_GEN4_PROFITABILITY_VALIDATION"
    )


def _note(value: str | None) -> str | None:
    if not str(value or "").strip():
        return None
    return sanitize_error_message(value, max_length=500)


def _price(trade: Trade) -> float | None:
    try:
        sol_amount = abs(float(trade.sol_amount or 0.0))
        token_amount = abs(float(trade.token_amount or 0.0))
    except (TypeError, ValueError):
        return None
    if sol_amount <= 0 or token_amount <= 0:
        return None
    resolved = sol_amount / token_amount
    return resolved if resolved > 0 else None


def _configured_excluded_price_mints(settings_object: Any) -> set[str]:
    raw = str(
        getattr(
            settings_object,
            "CANONICAL_PARSER_GEN4_PROFITABILITY_EXCLUDED_TOKEN_MINTS",
            "",
        )
        or ""
    )
    configured = {item.strip() for item in raw.split(",") if item.strip()}
    return set(GEN4_MANDATORY_EXCLUDED_PRICE_MINTS) | configured


def _price_ratio(first: float, second: float) -> float:
    low = min(float(first), float(second))
    high = max(float(first), float(second))
    if low <= 0:
        return float("inf")
    return high / low


def _policy_snapshot(settings_object: Any) -> dict[str, Any]:
    return {
        "policy_version": GEN4_PROFITABILITY_POLICY_VERSION,
        "scope": GEN4_PROFITABILITY_SCOPE,
        "training_days": int(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_TRAINING_DAYS", 14)
        ),
        "test_days": int(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_TEST_DAYS", 7)
        ),
        "step_days": int(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_STEP_DAYS", 7)
        ),
        "max_windows": int(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_WINDOWS", 4)
        ),
        "max_source_trades": int(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_SOURCE_TRADES", 100000)
        ),
        "minimum_training_source_trades": int(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_TRAINING_SOURCE_TRADES", 10)
        ),
        "minimum_training_closed_positions": int(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_TRAINING_CLOSED_POSITIONS", 5)
        ),
        "minimum_wallet_win_rate_percent": float(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_WALLET_WIN_RATE_PERCENT", 40.0)
        ),
        "minimum_wallet_profit_factor": float(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_WALLET_PROFIT_FACTOR", 1.10)
        ),
        "maximum_wallet_drawdown_percent": float(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_WALLET_DRAWDOWN_PERCENT", 25.0)
        ),
        "maximum_wallet_open_positions": int(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_WALLET_OPEN_POSITIONS", 2)
        ),
        "consensus_window_seconds": int(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_CONSENSUS_WINDOW_SECONDS", 180)
        ),
        "minimum_qualified_wallets": int(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_QUALIFIED_WALLETS", 2)
        ),
        "minimum_independent_clusters": int(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_INDEPENDENT_CLUSTERS", 2)
        ),
        "minimum_edge_strength": float(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_EDGE_STRENGTH", 60.0)
        ),
        "token_snapshot_max_age_minutes": int(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_TOKEN_SNAPSHOT_MAX_AGE_MINUTES", 30)
        ),
        "minimum_token_liquidity_usd": float(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_TOKEN_LIQUIDITY_USD", 25000.0)
        ),
        "maximum_token_risk_score": int(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_TOKEN_RISK_SCORE", 35)
        ),
        "maximum_top_holder_percent": float(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_TOP_HOLDER_PERCENT", 25.0)
        ),
        "starting_capital_sol": float(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_STARTING_CAPITAL_SOL", 1.0)
        ),
        "order_size_sol": float(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_ORDER_SIZE_SOL", 0.005)
        ),
        "slippage_bps": int(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_SLIPPAGE_BPS", 100)
        ),
        "fee_bps": int(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_FEE_BPS", 10)
        ),
        "copy_delay_seconds": int(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_COPY_DELAY_SECONDS", 8)
        ),
        "maximum_execution_lag_seconds": int(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_EXECUTION_LAG_SECONDS", 180)
        ),
        "maximum_open_positions": int(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_OPEN_POSITIONS", 5)
        ),
        "stop_loss_percent": float(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_STOP_LOSS_PERCENT", 15.0)
        ),
        "take_profit_percent": float(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_TAKE_PROFIT_PERCENT", 30.0)
        ),
        "maximum_hold_minutes": int(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_HOLD_MINUTES", 240)
        ),
        "minimum_evaluable_closed_trades": int(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_EVALUABLE_CLOSED_TRADES", 30)
        ),
        "minimum_proof_closed_trades": int(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_PROOF_CLOSED_TRADES", 100)
        ),
        "minimum_portfolio_profit_factor": float(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_PORTFOLIO_PROFIT_FACTOR", 1.30)
        ),
        "maximum_portfolio_drawdown_percent": float(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_PORTFOLIO_DRAWDOWN_PERCENT", 25.0)
        ),
        "minimum_positive_window_percent": float(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_MIN_POSITIVE_WINDOW_PERCENT", 60.0)
        ),
        "maximum_wallet_profit_concentration_percent": float(
            getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_WALLET_PROFIT_CONCENTRATION_PERCENT", 40.0)
        ),
        "excluded_price_mints": sorted(_configured_excluded_price_mints(settings_object)),
        "mandatory_excluded_price_mints": sorted(GEN4_MANDATORY_EXCLUDED_PRICE_MINTS),
        "price_continuity_window_seconds": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_GEN4_PROFITABILITY_PRICE_CONTINUITY_WINDOW_SECONDS",
                3600,
            )
        ),
        "maximum_price_discontinuity_ratio": float(
            getattr(
                settings_object,
                "CANONICAL_PARSER_GEN4_PROFITABILITY_MAX_PRICE_DISCONTINUITY_RATIO",
                25.0,
            )
        ),
        "take_profit_fill_method": "THRESHOLD_PRICE_WITH_EXIT_FRICTION",
        "stop_loss_fill_method": "THRESHOLD_PRICE_WITH_EXIT_FRICTION",
        "price_integrity_version": "gen4-price-integrity/1",
        "manual_run_only": True,
        "external_requests_allowed": False,
        "source_tables_read_only": [
            "trades",
            "candidate_backtest_runs",
            "wallet_edges",
            "token_safety_snapshots",
        ],
        "writes_only_metadata_tables": [
            "canonical_parser_gen4_profitability_runs",
            "canonical_parser_gen4_profitability_windows",
            "canonical_parser_gen4_profitability_trades",
        ],
        "paper_execution_connected": False,
        "live_execution_authorized": False,
        "worker_connected": False,
        "scheduler_connected": False,
        "stream_connected": False,
        "signer_connected": False,
        "transaction_submission_connected": False,
    }


def _safety_contract() -> dict[str, Any]:
    return {
        "scope": GEN4_PROFITABILITY_SCOPE,
        "preview_writes_performed": False,
        "run_writes_metadata_only": True,
        "external_requests": 0,
        "helius_requests": 0,
        "jupiter_requests": 0,
        "paper_orders_created": 0,
        "paper_positions_created": 0,
        "live_orders_created": 0,
        "transactions_built": 0,
        "transactions_signed": 0,
        "transactions_sent": 0,
        "live_execution_authorized": False,
        "worker_started": False,
        "scheduler_started": False,
        "stream_started": False,
        "signer_connected": False,
    }


def _effective_parameters(
    policy: dict[str, Any],
    *,
    training_days: int | None,
    test_days: int | None,
    step_days: int | None,
    max_windows: int | None,
) -> dict[str, int]:
    return {
        "training_days": min(max(int(training_days or policy["training_days"]), 3), 365),
        "test_days": min(max(int(test_days or policy["test_days"]), 1), 90),
        "step_days": min(max(int(step_days or policy["step_days"]), 1), 90),
        "max_windows": min(max(int(max_windows or policy["max_windows"]), 1), 24),
    }


def _load_trades(
    db: Session,
    *,
    start_at: datetime,
    end_at: datetime,
    max_source_trades: int,
) -> list[Trade]:
    query = (
        select(Trade)
        .where(
            Trade.success.is_(True),
            Trade.block_time.isnot(None),
            Trade.block_time >= start_at,
            Trade.block_time <= end_at,
        )
        .order_by(Trade.block_time.asc(), Trade.id.asc())
        .limit(max_source_trades)
    )
    return list(db.scalars(query))


def _valid_price_points(
    trades: Iterable[Trade],
    *,
    policy: dict[str, Any],
) -> tuple[list[PricePoint], dict[str, Any]]:
    excluded_mints = set(policy["excluded_price_mints"])
    raw_by_token: dict[str, list[PricePoint]] = defaultdict(list)
    audit: dict[str, Any] = {
        "source_trade_count": 0,
        "accepted_price_point_count": 0,
        "excluded_quote_asset_count": 0,
        "invalid_amount_count": 0,
        "unsupported_side_count": 0,
        "missing_token_count": 0,
        "price_discontinuity_rejected_count": 0,
        "excluded_mint_counts": defaultdict(int),
        "price_discontinuity_rejected_trade_ids": [],
    }

    for trade in trades:
        audit["source_trade_count"] += 1
        token = str(trade.token_mint or "").strip()
        side = str(trade.side or "").strip().upper()
        if not token:
            audit["missing_token_count"] += 1
            continue
        if token in excluded_mints:
            audit["excluded_quote_asset_count"] += 1
            audit["excluded_mint_counts"][token] += 1
            continue
        if side not in {"BUY", "SELL"}:
            audit["unsupported_side_count"] += 1
            continue
        price = _price(trade)
        if price is None:
            audit["invalid_amount_count"] += 1
            continue
        raw_by_token[token].append(
            PricePoint(
                trade_id=int(trade.id),
                signature=str(trade.signature),
                wallet_address=str(trade.wallet_address),
                token_mint=token,
                side=side,
                occurred_at=_aware(trade.block_time),
                price_sol=price,
            )
        )

    accepted: list[PricePoint] = []
    continuity_seconds = int(policy["price_continuity_window_seconds"])
    maximum_ratio = float(policy["maximum_price_discontinuity_ratio"])

    for token in sorted(raw_by_token):
        recent: deque[PricePoint] = deque()
        for point in sorted(
            raw_by_token[token],
            key=lambda item: (item.occurred_at, item.trade_id),
        ):
            cutoff = point.occurred_at - timedelta(seconds=continuity_seconds)
            while recent and recent[0].occurred_at < cutoff:
                recent.popleft()

            if recent:
                reference = median(item.price_sol for item in recent)
                if _price_ratio(point.price_sol, reference) > maximum_ratio:
                    audit["price_discontinuity_rejected_count"] += 1
                    rejected_ids = audit["price_discontinuity_rejected_trade_ids"]
                    if len(rejected_ids) < 50:
                        rejected_ids.append(point.trade_id)
                    continue

            accepted.append(point)
            recent.append(point)

    accepted.sort(key=lambda item: (item.occurred_at, item.trade_id))
    audit["accepted_price_point_count"] = len(accepted)
    audit["excluded_mint_counts"] = dict(sorted(audit["excluded_mint_counts"].items()))
    return accepted, audit


def _wallet_training_metrics(points: list[PricePoint], policy: dict[str, Any]) -> dict[str, Any]:
    order_size = float(policy["order_size_sol"])
    fee_ratio = float(policy["fee_bps"]) / 10000.0
    friction_ratio = float(policy["slippage_bps"]) / 10000.0
    starting_capital = float(policy["starting_capital_sol"])
    max_positions = int(policy["maximum_open_positions"])

    cash = starting_capital
    positions: dict[str, tuple[float, float]] = {}
    pnls: list[float] = []
    source_trades = 0
    peak = starting_capital
    equity = starting_capital
    max_drawdown = 0.0

    for point in points:
        source_trades += 1
        if point.side == "BUY":
            if point.token_mint in positions or len(positions) >= max_positions or cash + 1e-12 < order_size:
                continue
            entry_price = point.price_sol * (1.0 + friction_ratio)
            quantity = order_size * (1.0 - fee_ratio) / entry_price
            if quantity <= 0:
                continue
            positions[point.token_mint] = (quantity, order_size)
            cash -= order_size
        else:
            position = positions.pop(point.token_mint, None)
            if position is None:
                continue
            quantity, cost_basis = position
            exit_price = point.price_sol * max(0.0, 1.0 - friction_ratio)
            proceeds = quantity * exit_price * max(0.0, 1.0 - fee_ratio)
            pnl = proceeds - cost_basis
            pnls.append(pnl)
            cash += proceeds
            equity = starting_capital + sum(pnls)
            peak = max(peak, equity)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - equity) / peak * 100.0)

    gross_profit = sum(max(0.0, item) for item in pnls)
    gross_loss = sum(min(0.0, item) for item in pnls)
    wins = sum(1 for item in pnls if item > 1e-12)
    profit_factor = gross_profit / abs(gross_loss) if gross_loss < 0 else (999.0 if gross_profit > 0 else None)
    net_pnl = sum(pnls)
    return {
        "source_trades": source_trades,
        "closed_positions": len(pnls),
        "open_positions": len(positions),
        "net_pnl_sol": _round(net_pnl),
        "return_percent": _round(net_pnl / starting_capital * 100.0 if starting_capital > 0 else 0.0, 4),
        "win_rate_percent": _round(wins / len(pnls) * 100.0 if pnls else 0.0, 4),
        "profit_factor": None if profit_factor is None else _round(profit_factor, 4),
        "max_drawdown_percent": _round(max_drawdown, 4),
    }


def _proxy_qualified_wallets(
    points: list[PricePoint],
    *,
    train_start: datetime,
    train_end: datetime,
    policy: dict[str, Any],
) -> tuple[set[str], dict[str, dict[str, Any]]]:
    by_wallet: dict[str, list[PricePoint]] = defaultdict(list)
    for point in points:
        if train_start <= point.occurred_at < train_end:
            by_wallet[point.wallet_address].append(point)

    qualified: set[str] = set()
    metrics_by_wallet: dict[str, dict[str, Any]] = {}
    for wallet, rows in by_wallet.items():
        metrics = _wallet_training_metrics(rows, policy)
        reasons: list[str] = []
        if metrics["source_trades"] < int(policy["minimum_training_source_trades"]):
            reasons.append("TRAINING_SOURCE_TRADES_BELOW_MINIMUM")
        if metrics["closed_positions"] < int(policy["minimum_training_closed_positions"]):
            reasons.append("TRAINING_CLOSED_POSITIONS_BELOW_MINIMUM")
        if metrics["return_percent"] <= 0:
            reasons.append("TRAINING_RETURN_NOT_POSITIVE")
        if metrics["win_rate_percent"] < float(policy["minimum_wallet_win_rate_percent"]):
            reasons.append("TRAINING_WIN_RATE_BELOW_MINIMUM")
        if metrics["profit_factor"] is None or metrics["profit_factor"] < float(policy["minimum_wallet_profit_factor"]):
            reasons.append("TRAINING_PROFIT_FACTOR_BELOW_MINIMUM")
        if metrics["max_drawdown_percent"] > float(policy["maximum_wallet_drawdown_percent"]):
            reasons.append("TRAINING_DRAWDOWN_ABOVE_MAXIMUM")
        if metrics["open_positions"] > int(policy["maximum_wallet_open_positions"]):
            reasons.append("TRAINING_OPEN_POSITIONS_ABOVE_MAXIMUM")
        metrics["qualified"] = not reasons
        metrics["reason_codes"] = reasons
        metrics_by_wallet[wallet] = metrics
        if not reasons:
            qualified.add(wallet)
    return qualified, metrics_by_wallet


def _strict_qualified_wallets(
    db: Session,
    wallets: set[str],
    *,
    train_end: datetime,
    policy: dict[str, Any],
) -> tuple[set[str], dict[str, dict[str, Any]], list[str]]:
    qualified: set[str] = set()
    evidence: dict[str, dict[str, Any]] = {}
    gaps: set[str] = set()
    for wallet in sorted(wallets):
        run = db.scalar(
            select(CandidateBacktestRun)
            .where(
                CandidateBacktestRun.wallet_address == wallet,
                CandidateBacktestRun.completed_at.isnot(None),
                CandidateBacktestRun.completed_at <= train_end,
            )
            .order_by(desc(CandidateBacktestRun.completed_at), desc(CandidateBacktestRun.id))
            .limit(1)
        )
        if run is None:
            evidence[wallet] = {
                "qualified": False,
                "reason_codes": ["POINT_IN_TIME_CANDIDATE_BACKTEST_MISSING"],
                "run_id": None,
            }
            gaps.add("POINT_IN_TIME_WALLET_BACKTEST_COVERAGE_INCOMPLETE")
            continue
        reasons: list[str] = []
        if str(run.status) != "COMPLETED":
            reasons.append("POINT_IN_TIME_BACKTEST_NOT_COMPLETED")
        if str(run.decision) != "PROMOSSO":
            reasons.append("POINT_IN_TIME_BACKTEST_NOT_PROMOTED")
        if not bool(run.data_sufficient):
            reasons.append("POINT_IN_TIME_BACKTEST_DATA_INSUFFICIENT")
        if int(run.completed_positions or 0) < int(policy["minimum_training_closed_positions"]):
            reasons.append("POINT_IN_TIME_CLOSED_POSITIONS_BELOW_MINIMUM")
        if float(run.total_return_percent or 0) <= 0:
            reasons.append("POINT_IN_TIME_RETURN_NOT_POSITIVE")
        if float(run.win_rate_percent or 0) < float(policy["minimum_wallet_win_rate_percent"]):
            reasons.append("POINT_IN_TIME_WIN_RATE_BELOW_MINIMUM")
        if run.profit_factor is None or float(run.profit_factor) < float(policy["minimum_wallet_profit_factor"]):
            reasons.append("POINT_IN_TIME_PROFIT_FACTOR_BELOW_MINIMUM")
        if float(run.max_drawdown_percent or 0) > float(policy["maximum_wallet_drawdown_percent"]):
            reasons.append("POINT_IN_TIME_DRAWDOWN_ABOVE_MAXIMUM")
        if int(run.open_positions or 0) > int(policy["maximum_wallet_open_positions"]):
            reasons.append("POINT_IN_TIME_OPEN_POSITIONS_ABOVE_MAXIMUM")
        evidence[wallet] = {
            "qualified": not reasons,
            "reason_codes": reasons,
            "run_id": run.run_id,
            "completed_at": _aware(run.completed_at).isoformat(),
            "decision": run.decision,
            "completed_positions": int(run.completed_positions or 0),
            "return_percent": _round(run.total_return_percent, 4),
            "profit_factor": None if run.profit_factor is None else _round(run.profit_factor, 4),
            "max_drawdown_percent": _round(run.max_drawdown_percent, 4),
        }
        if not reasons:
            qualified.add(wallet)
    return qualified, evidence, sorted(gaps)


def _components(wallets: set[str], edges: list[WalletEdge], *, at: datetime, minimum_strength: float) -> dict[str, str]:
    graph: dict[str, set[str]] = {wallet: set() for wallet in wallets}
    for edge in edges:
        created_at = _aware(edge.created_at)
        source = str(edge.source_wallet)
        target = str(edge.target_wallet)
        if created_at > at or float(edge.strength or 0) < minimum_strength:
            continue
        if source not in graph or target not in graph:
            continue
        graph[source].add(target)
        graph[target].add(source)
    mapping: dict[str, str] = {}
    visited: set[str] = set()
    for wallet in sorted(wallets):
        if wallet in visited:
            continue
        stack = [wallet]
        component: list[str] = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            stack.extend(sorted(graph[current] - visited))
        key = calculate_payload_hash({"wallets": sorted(component), "at": at.isoformat()})
        for item in component:
            mapping[item] = key
    return mapping


def _strict_token_safety(
    snapshot: TokenSafetySnapshot | None,
    *,
    signal_at: datetime,
    policy: dict[str, Any],
) -> dict[str, Any]:
    if snapshot is None:
        return {"safe": False, "reason_codes": ["POINT_IN_TIME_TOKEN_SAFETY_MISSING"], "snapshot": None}
    fetched_at = _aware(snapshot.fetched_at)
    if fetched_at > signal_at:
        return {
            "safe": False,
            "reason_codes": ["POINT_IN_TIME_TOKEN_SAFETY_FROM_FUTURE"],
            "snapshot": {"fetched_at": fetched_at.isoformat()},
        }
    age_minutes = (signal_at - fetched_at).total_seconds() / 60.0
    reasons: list[str] = []
    if age_minutes > int(policy["token_snapshot_max_age_minutes"]):
        reasons.append("POINT_IN_TIME_TOKEN_SAFETY_EXPIRED")
    if bool(snapshot.honeypot):
        reasons.append("TOKEN_HONEYPOT")
    if bool(snapshot.mint_authority_enabled):
        reasons.append("TOKEN_MINT_AUTHORITY_ENABLED")
    if bool(snapshot.freeze_authority_enabled):
        reasons.append("TOKEN_FREEZE_AUTHORITY_ENABLED")
    if snapshot.rugged is True:
        reasons.append("TOKEN_RUGGED")
    if snapshot.rugcheck_passed is not True:
        reasons.append("TOKEN_RUGCHECK_NOT_PASSED")
    if float(snapshot.liquidity_usd or 0) < float(policy["minimum_token_liquidity_usd"]):
        reasons.append("TOKEN_LIQUIDITY_BELOW_MINIMUM")
    if int(snapshot.risk_score or 100) > int(policy["maximum_token_risk_score"]):
        reasons.append("TOKEN_RISK_SCORE_ABOVE_MAXIMUM")
    if float(snapshot.top_holder_percent or 100) > float(policy["maximum_top_holder_percent"]):
        reasons.append("TOKEN_HOLDER_CONCENTRATION_ABOVE_MAXIMUM")
    return {
        "safe": not reasons,
        "reason_codes": reasons,
        "snapshot": {
            "fetched_at": fetched_at.isoformat(),
            "age_minutes": _round(max(0.0, age_minutes), 4),
            "liquidity_usd": _round(snapshot.liquidity_usd, 2),
            "risk_score": int(snapshot.risk_score or 0),
            "top_holder_percent": _round(snapshot.top_holder_percent, 4),
        },
    }


def _build_signals(
    points: list[PricePoint],
    *,
    lane: str,
    qualified_wallets: set[str],
    test_start: datetime,
    test_end: datetime,
    edges: list[WalletEdge],
    token_snapshots: dict[str, TokenSafetySnapshot],
    policy: dict[str, Any],
    minimum_wallets: int,
    minimum_clusters: int,
    strict_token_safety: bool,
) -> tuple[list[Signal], dict[str, Any]]:
    buys_by_token: dict[str, list[PricePoint]] = defaultdict(list)
    for point in points:
        if (
            point.side == "BUY"
            and point.wallet_address in qualified_wallets
            and test_start <= point.occurred_at < test_end
        ):
            buys_by_token[point.token_mint].append(point)

    signals: list[Signal] = []
    skipped = defaultdict(int)
    strict_safety_attempts = 0
    strict_safety_passes = 0
    window_seconds = int(policy["consensus_window_seconds"])

    for token in sorted(buys_by_token):
        rows = sorted(buys_by_token[token], key=lambda item: (item.occurred_at, item.trade_id))
        left = 0
        right = 0
        while right < len(rows):
            while left <= right and (rows[right].occurred_at - rows[left].occurred_at).total_seconds() > window_seconds:
                left += 1
            current = rows[left : right + 1]
            first_by_wallet: dict[str, PricePoint] = {}
            for row in current:
                first_by_wallet.setdefault(row.wallet_address, row)
            if len(first_by_wallet) < minimum_wallets:
                right += 1
                continue

            wallets = set(first_by_wallet)
            mapping = _components(
                wallets,
                edges,
                at=rows[right].occurred_at,
                minimum_strength=float(policy["minimum_edge_strength"]),
            )
            independent_clusters = len(set(mapping.values()))
            if independent_clusters < minimum_clusters:
                skipped["INDEPENDENT_CLUSTERS_BELOW_MINIMUM"] += 1
                right += 1
                continue

            safety = {"safe": True, "reason_codes": [], "snapshot": None}
            if strict_token_safety:
                strict_safety_attempts += 1
                safety = _strict_token_safety(
                    token_snapshots.get(token),
                    signal_at=rows[right].occurred_at,
                    policy=policy,
                )
                if not safety["safe"]:
                    for code in safety["reason_codes"]:
                        skipped[code] += 1
                    right += 1
                    continue
                strict_safety_passes += 1

            selected = sorted(first_by_wallet.values(), key=lambda item: (item.occurred_at, item.trade_id))
            signal = Signal(
                lane=lane,
                token_mint=token,
                signal_at=rows[right].occurred_at,
                contributing_wallets=tuple(sorted(wallets)),
                independent_cluster_count=independent_clusters,
                source_trade_ids=tuple(item.trade_id for item in selected),
                source_signatures=tuple(item.signature for item in selected),
                evidence={
                    "wallet_count": len(wallets),
                    "independent_cluster_count": independent_clusters,
                    "token_safety": safety,
                    "point_in_time_guard": True,
                    "selection_uses_training_window_only": True,
                    "market_price_source": "RECORDED_SOURCE_TRADE_PROXY",
                },
            )
            signals.append(signal)
            # Prevent overlapping reuse of the same consensus burst.
            next_at = signal.signal_at + timedelta(seconds=window_seconds)
            right += 1
            while right < len(rows) and rows[right].occurred_at <= next_at:
                right += 1
            left = right

    return signals, {
        "candidate_token_count": len(buys_by_token),
        "signal_count": len(signals),
        "strict_token_safety_attempts": strict_safety_attempts,
        "strict_token_safety_passes": strict_safety_passes,
        "skipped_reason_counts": dict(sorted(skipped.items())),
    }


def _simulate_signal(
    signal: Signal,
    *,
    token_points: list[PricePoint],
    policy: dict[str, Any],
) -> CandidateOutcome:
    delayed_at = signal.signal_at + timedelta(seconds=int(policy["copy_delay_seconds"]))
    max_entry_at = signal.signal_at + timedelta(seconds=int(policy["maximum_execution_lag_seconds"]))
    entry_point = next(
        (
            point
            for point in token_points
            if delayed_at <= point.occurred_at <= max_entry_at
        ),
        None,
    )
    base_evidence = {
        **signal.evidence,
        "source_signatures": list(signal.source_signatures),
        "copy_delay_seconds": int(policy["copy_delay_seconds"]),
        "maximum_execution_lag_seconds": int(policy["maximum_execution_lag_seconds"]),
        "price_integrity_version": policy["price_integrity_version"],
        "maximum_price_discontinuity_ratio": float(
            policy["maximum_price_discontinuity_ratio"]
        ),
        "threshold_fill_enforced": True,
    }
    if entry_point is None:
        return CandidateOutcome(
            lane=signal.lane,
            token_mint=signal.token_mint,
            signal_at=signal.signal_at,
            entry_at=None,
            exit_at=None,
            entry_price_sol=None,
            exit_price_sol=None,
            order_size_sol=float(policy["order_size_sol"]),
            pnl_sol=None,
            return_percent=None,
            exit_reason="NO_EXECUTION_PRICE",
            contributing_wallets=signal.contributing_wallets,
            independent_cluster_count=signal.independent_cluster_count,
            source_trade_ids=signal.source_trade_ids,
            evidence=base_evidence,
        )

    fee_ratio = float(policy["fee_bps"]) / 10000.0
    friction_ratio = float(policy["slippage_bps"]) / 10000.0
    order_size = float(policy["order_size_sol"])
    entry_price = entry_point.price_sol * (1.0 + friction_ratio)
    quantity = order_size * max(0.0, 1.0 - fee_ratio) / entry_price
    deadline = entry_point.occurred_at + timedelta(minutes=int(policy["maximum_hold_minutes"]))
    stop_price = entry_price * (1.0 - float(policy["stop_loss_percent"]) / 100.0)
    take_price = entry_price * (1.0 + float(policy["take_profit_percent"]) / 100.0)
    source_wallets = set(signal.contributing_wallets)
    maximum_ratio = float(policy["maximum_price_discontinuity_ratio"])

    exit_point: PricePoint | None = None
    exit_reason: str | None = None
    exit_reference_price: float | None = None
    last_after_entry: PricePoint | None = None
    min_observed_return = 0.0
    max_observed_return = 0.0
    rejected_discontinuities = 0

    for point in token_points:
        if point.occurred_at <= entry_point.occurred_at:
            continue
        if point.occurred_at > deadline:
            break
        if _price_ratio(point.price_sol, entry_point.price_sol) > maximum_ratio:
            rejected_discontinuities += 1
            continue

        last_after_entry = point
        observed_return = (point.price_sol / entry_price - 1.0) * 100.0
        min_observed_return = min(min_observed_return, observed_return)
        max_observed_return = max(max_observed_return, observed_return)

        if point.price_sol <= stop_price:
            exit_point = point
            exit_reason = "STOP_LOSS"
            exit_reference_price = stop_price
            break
        if point.price_sol >= take_price:
            exit_point = point
            exit_reason = "TAKE_PROFIT"
            exit_reference_price = take_price
            break
        if point.side == "SELL" and point.wallet_address in source_wallets:
            exit_point = point
            exit_reason = "SOURCE_WALLET_SELL"
            exit_reference_price = point.price_sol
            break

    if exit_point is None and last_after_entry is not None:
        exit_point = last_after_entry
        exit_reason = "MAX_HOLD_OBSERVED_PRICE"
        exit_reference_price = last_after_entry.price_sol

    evidence = {
        **base_evidence,
        "entry_source_trade_id": entry_point.trade_id,
        "entry_signature": entry_point.signature,
        "entry_lag_seconds": _round((entry_point.occurred_at - signal.signal_at).total_seconds(), 4),
        "minimum_observed_return_percent": _round(min_observed_return, 4),
        "maximum_observed_return_percent": _round(max_observed_return, 4),
        "deadline_at": deadline.isoformat(),
        "price_discontinuity_rejected_points": rejected_discontinuities,
    }
    if exit_point is None or exit_reference_price is None:
        return CandidateOutcome(
            lane=signal.lane,
            token_mint=signal.token_mint,
            signal_at=signal.signal_at,
            entry_at=entry_point.occurred_at,
            exit_at=None,
            entry_price_sol=_round(entry_price, 18),
            exit_price_sol=None,
            order_size_sol=order_size,
            pnl_sol=None,
            return_percent=None,
            exit_reason=(
                "PRICE_INTEGRITY_NO_VALID_EXIT"
                if rejected_discontinuities
                else "NO_EXIT_PRICE"
            ),
            contributing_wallets=signal.contributing_wallets,
            independent_cluster_count=signal.independent_cluster_count,
            source_trade_ids=signal.source_trade_ids,
            evidence=evidence,
        )

    exit_price = exit_reference_price * max(0.0, 1.0 - friction_ratio)
    proceeds = quantity * exit_price * max(0.0, 1.0 - fee_ratio)
    pnl = proceeds - order_size
    return_percent = pnl / order_size * 100.0 if order_size > 0 else 0.0
    evidence["exit_source_trade_id"] = exit_point.trade_id
    evidence["exit_signature"] = exit_point.signature
    evidence["exit_trigger_observed_price_sol"] = _round(exit_point.price_sol, 18)
    evidence["exit_execution_reference_price_sol"] = _round(exit_reference_price, 18)
    evidence["threshold_fill_applied"] = exit_reason in {"STOP_LOSS", "TAKE_PROFIT"}
    return CandidateOutcome(
        lane=signal.lane,
        token_mint=signal.token_mint,
        signal_at=signal.signal_at,
        entry_at=entry_point.occurred_at,
        exit_at=exit_point.occurred_at,
        entry_price_sol=_round(entry_price, 18),
        exit_price_sol=_round(exit_price, 18),
        order_size_sol=order_size,
        pnl_sol=_round(pnl),
        return_percent=_round(return_percent, 4),
        exit_reason=exit_reason,
        contributing_wallets=signal.contributing_wallets,
        independent_cluster_count=signal.independent_cluster_count,
        source_trade_ids=signal.source_trade_ids,
        evidence=evidence,
    )


def _portfolio_metrics(outcomes: list[CandidateOutcome], policy: dict[str, Any]) -> tuple[dict[str, Any], list[CandidateOutcome]]:
    starting_capital = float(policy["starting_capital_sol"])
    order_size = float(policy["order_size_sol"])
    max_open = int(policy["maximum_open_positions"])
    cash = starting_capital
    active: list[CandidateOutcome] = []
    active_tokens: set[str] = set()
    accepted: list[CandidateOutcome] = []
    skipped = defaultdict(int)
    realized_equity = starting_capital
    peak = starting_capital
    max_drawdown = 0.0

    def close_due(until: datetime) -> None:
        nonlocal cash, realized_equity, peak, max_drawdown, active
        due = sorted(
            [item for item in active if item.exit_at is not None and item.exit_at <= until],
            key=lambda item: item.exit_at or until,
        )
        for item in due:
            cash += order_size + float(item.pnl_sol or 0.0)
            realized_equity += float(item.pnl_sol or 0.0)
            peak = max(peak, realized_equity)
            if peak > 0:
                max_drawdown = max(max_drawdown, (peak - realized_equity) / peak * 100.0)
            active.remove(item)
            active_tokens.discard(item.token_mint)

    for outcome in sorted(
        outcomes,
        key=lambda item: (item.entry_at or datetime.max.replace(tzinfo=timezone.utc), item.token_mint),
    ):
        if outcome.entry_at is None or outcome.exit_at is None or outcome.pnl_sol is None:
            skipped[outcome.exit_reason or "UNRESOLVED"] += 1
            continue
        close_due(outcome.entry_at)
        if outcome.token_mint in active_tokens:
            skipped["TOKEN_POSITION_ALREADY_OPEN"] += 1
            continue
        if len(active) >= max_open:
            skipped["MAX_OPEN_POSITIONS"] += 1
            continue
        if cash + 1e-12 < order_size:
            skipped["INSUFFICIENT_CAPITAL"] += 1
            continue
        cash -= order_size
        active.append(outcome)
        active_tokens.add(outcome.token_mint)
        accepted.append(outcome)

    close_due(datetime.max.replace(tzinfo=timezone.utc))
    pnls = [float(item.pnl_sol or 0.0) for item in accepted]
    gross_profit = sum(max(0.0, item) for item in pnls)
    gross_loss = sum(min(0.0, item) for item in pnls)
    wins = sum(1 for item in pnls if item > 1e-12)
    losses = sum(1 for item in pnls if item < -1e-12)
    profit_factor = gross_profit / abs(gross_loss) if gross_loss < 0 else (999.0 if gross_profit > 0 else None)
    net_pnl = sum(pnls)

    contributions: dict[str, float] = defaultdict(float)
    for outcome in accepted:
        wallets = outcome.contributing_wallets or ("UNKNOWN",)
        share = float(outcome.pnl_sol or 0.0) / len(wallets)
        for wallet in wallets:
            contributions[wallet] += share
    positive_contributions = [max(0.0, value) for value in contributions.values()]
    positive_total = sum(positive_contributions)
    concentration = max(positive_contributions) / positive_total * 100.0 if positive_total > 0 else 0.0

    metrics = {
        "candidate_outcomes": len(outcomes),
        "closed_trades": len(accepted),
        "winning_trades": wins,
        "losing_trades": losses,
        "breakeven_trades": len(accepted) - wins - losses,
        "net_pnl_sol": _round(net_pnl),
        "total_return_percent": _round(net_pnl / starting_capital * 100.0 if starting_capital > 0 else 0.0, 4),
        "win_rate_percent": _round(wins / len(accepted) * 100.0 if accepted else 0.0, 4),
        "profit_factor": None if profit_factor is None else _round(profit_factor, 4),
        "max_drawdown_percent": _round(max_drawdown, 4),
        "wallet_profit_concentration_percent": _round(concentration, 4),
        "unique_wallet_contributors": len(contributions),
        "unique_tokens": len({item.token_mint for item in accepted}),
        "skipped_reason_counts": dict(sorted(skipped.items())),
        "starting_capital_sol": _round(starting_capital),
        "ending_equity_sol": _round(starting_capital + net_pnl),
        "order_size_sol": _round(order_size),
        "market_price_source": "RECORDED_SOURCE_TRADE_PROXY",
        "drawdown_method": "REALIZED_EQUITY_WITH_INTRATRADE_ADVERSE_EXCURSION_REPORTED_PER_TRADE",
    }
    return metrics, accepted


def _aggregate_metrics(window_metrics: list[dict[str, Any]], accepted: list[CandidateOutcome], policy: dict[str, Any]) -> dict[str, Any]:
    metrics, _ = _portfolio_metrics(accepted, policy)
    windows_with_trades = [item for item in window_metrics if int(item.get("closed_trades", 0)) > 0]
    positive_windows = [item for item in windows_with_trades if float(item.get("net_pnl_sol", 0)) > 0]
    metrics["window_count"] = len(window_metrics)
    metrics["windows_with_closed_trades"] = len(windows_with_trades)
    metrics["positive_windows"] = len(positive_windows)
    metrics["positive_window_percent"] = _round(
        len(positive_windows) / len(windows_with_trades) * 100.0 if windows_with_trades else 0.0,
        4,
    )
    return metrics


def _verdict(
    *,
    strict_metrics: dict[str, Any],
    proxy_metrics: dict[str, Any],
    policy: dict[str, Any],
) -> tuple[str, str, list[str]]:
    strict_closed = int(strict_metrics["closed_trades"])
    min_evaluable = int(policy["minimum_evaluable_closed_trades"])
    min_proof = int(policy["minimum_proof_closed_trades"])
    gaps: list[str] = []
    required_windows = max(1, min(2, int(policy["max_windows"])))
    if strict_closed < min_evaluable or int(strict_metrics["windows_with_closed_trades"]) < required_windows:
        gaps.append("STRICT_GEN4_CLOSED_SAMPLE_BELOW_EVALUABLE_MINIMUM")
        if (
            int(proxy_metrics["closed_trades"]) >= min_evaluable
            and float(proxy_metrics["total_return_percent"]) > 0
            and proxy_metrics["profit_factor"] is not None
            and float(proxy_metrics["profit_factor"]) >= float(policy["minimum_portfolio_profit_factor"])
            and float(proxy_metrics["max_drawdown_percent"]) <= float(policy["maximum_portfolio_drawdown_percent"])
        ):
            return VERDICT_PROXY_PROMISING, "INSUFFICIENT", gaps
        return VERDICT_NOT_EVALUABLE, "INSUFFICIENT", gaps

    passes_economics = all(
        (
            float(strict_metrics["total_return_percent"]) > 0,
            strict_metrics["profit_factor"] is not None,
            float(strict_metrics["profit_factor"] or 0) >= float(policy["minimum_portfolio_profit_factor"]),
            float(strict_metrics["max_drawdown_percent"]) <= float(policy["maximum_portfolio_drawdown_percent"]),
            float(strict_metrics["positive_window_percent"]) >= float(policy["minimum_positive_window_percent"]),
        )
    )
    if not passes_economics:
        return VERDICT_NEGATIVE, "EVALUABLE", gaps
    if strict_closed < min_proof:
        gaps.append("STRICT_GEN4_CLOSED_SAMPLE_BELOW_PROOF_MINIMUM")
        return VERDICT_PROMISING, "EVALUABLE", gaps
    if float(strict_metrics["wallet_profit_concentration_percent"]) > float(
        policy["maximum_wallet_profit_concentration_percent"]
    ):
        gaps.append("WALLET_PROFIT_CONCENTRATION_ABOVE_MAXIMUM")
        return VERDICT_PROMISING, "EVALUABLE", gaps
    return VERDICT_PROFITABLE, "SUFFICIENT", gaps


def _serialize_outcome(outcome: CandidateOutcome) -> dict[str, Any]:
    return {
        "lane": outcome.lane,
        "token_mint": outcome.token_mint,
        "signal_at": outcome.signal_at.isoformat(),
        "entry_at": None if outcome.entry_at is None else outcome.entry_at.isoformat(),
        "exit_at": None if outcome.exit_at is None else outcome.exit_at.isoformat(),
        "entry_price_sol": outcome.entry_price_sol,
        "exit_price_sol": outcome.exit_price_sol,
        "order_size_sol": outcome.order_size_sol,
        "pnl_sol": outcome.pnl_sol,
        "return_percent": outcome.return_percent,
        "exit_reason": outcome.exit_reason,
        "contributing_wallets": list(outcome.contributing_wallets),
        "independent_cluster_count": outcome.independent_cluster_count,
        "source_trade_ids": list(outcome.source_trade_ids),
        "evidence": outcome.evidence,
    }


def _build_report(
    db: Session,
    *,
    training_days: int | None,
    test_days: int | None,
    step_days: int | None,
    max_windows: int | None,
    settings_object: Any,
    evaluated_at: datetime | None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _policy_snapshot(settings_object)
    parameters = _effective_parameters(
        policy,
        training_days=training_days,
        test_days=test_days,
        step_days=step_days,
        max_windows=max_windows,
    )
    latest_trade_at = db.scalar(
        select(func.max(Trade.block_time)).where(Trade.success.is_(True), Trade.block_time.isnot(None))
    )
    oldest_trade_at = db.scalar(
        select(func.min(Trade.block_time)).where(Trade.success.is_(True), Trade.block_time.isnot(None))
    )
    if latest_trade_at is None or oldest_trade_at is None:
        return {
            "enabled": bool(getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_ENABLED", False)),
            "evaluated_at": now.isoformat(),
            "policy_version": GEN4_PROFITABILITY_POLICY_VERSION,
            "policy_hash": calculate_payload_hash(policy),
            "policy_snapshot": policy,
            "parameters": parameters,
            "verdict": VERDICT_NOT_EVALUABLE,
            "strict_evidence_status": "INSUFFICIENT",
            "summary": {"source_trade_count": 0, "window_count": 0},
            "strict_metrics": _aggregate_metrics([], [], policy),
            "proxy_metrics": _aggregate_metrics([], [], policy),
            "baseline_metrics": _aggregate_metrics([], [], policy),
            "evidence_gaps": ["NO_HISTORICAL_TRADES_AVAILABLE"],
            "windows": [],
            "safety": _safety_contract(),
            "writes_performed": False,
        }

    latest = min(_aware(latest_trade_at), now)
    oldest = _aware(oldest_trade_at)
    total_days = (
        parameters["training_days"]
        + parameters["test_days"]
        + (parameters["max_windows"] - 1) * parameters["step_days"]
    )
    requested_start = latest - timedelta(days=total_days)
    start_at = max(oldest, requested_start)
    exit_buffer_end = latest + timedelta(minutes=int(policy["maximum_hold_minutes"]))
    trades = _load_trades(
        db,
        start_at=start_at,
        end_at=min(exit_buffer_end, now),
        max_source_trades=int(policy["max_source_trades"]),
    )
    points, price_integrity_audit = _valid_price_points(trades, policy=policy)
    edges = list(db.scalars(select(WalletEdge)))
    token_snapshots = {row.token_mint: row for row in db.scalars(select(TokenSafetySnapshot))}

    windows: list[dict[str, Any]] = []
    for reverse_index in range(parameters["max_windows"]):
        test_end = latest - timedelta(days=reverse_index * parameters["step_days"])
        test_start = test_end - timedelta(days=parameters["test_days"])
        train_end = test_start
        train_start = train_end - timedelta(days=parameters["training_days"])
        if train_start < oldest:
            continue
        windows.append(
            {
                "train_start_at": train_start,
                "train_end_at": train_end,
                "test_start_at": test_start,
                "test_end_at": test_end,
            }
        )
    windows.reverse()

    by_token: dict[str, list[PricePoint]] = defaultdict(list)
    for point in points:
        by_token[point.token_mint].append(point)

    strict_all: list[CandidateOutcome] = []
    proxy_all: list[CandidateOutcome] = []
    baseline_all: list[CandidateOutcome] = []
    strict_window_metrics: list[dict[str, Any]] = []
    proxy_window_metrics: list[dict[str, Any]] = []
    baseline_window_metrics: list[dict[str, Any]] = []
    window_payloads: list[dict[str, Any]] = []
    global_gaps: set[str] = set()

    for sequence, window in enumerate(windows, start=1):
        test_wallets = {
            point.wallet_address
            for point in points
            if window["test_start_at"] <= point.occurred_at < window["test_end_at"] and point.side == "BUY"
        }
        proxy_wallets, proxy_training = _proxy_qualified_wallets(
            points,
            train_start=window["train_start_at"],
            train_end=window["train_end_at"],
            policy=policy,
        )
        strict_wallets, strict_wallet_evidence, strict_wallet_gaps = _strict_qualified_wallets(
            db,
            test_wallets,
            train_end=window["train_end_at"],
            policy=policy,
        )
        global_gaps.update(strict_wallet_gaps)

        strict_signals, strict_signal_audit = _build_signals(
            points,
            lane=LANE_STRICT,
            qualified_wallets=strict_wallets,
            test_start=window["test_start_at"],
            test_end=window["test_end_at"],
            edges=edges,
            token_snapshots=token_snapshots,
            policy=policy,
            minimum_wallets=int(policy["minimum_qualified_wallets"]),
            minimum_clusters=int(policy["minimum_independent_clusters"]),
            strict_token_safety=True,
        )
        proxy_signals, proxy_signal_audit = _build_signals(
            points,
            lane=LANE_PROXY,
            qualified_wallets=proxy_wallets,
            test_start=window["test_start_at"],
            test_end=window["test_end_at"],
            edges=edges,
            token_snapshots=token_snapshots,
            policy=policy,
            minimum_wallets=int(policy["minimum_qualified_wallets"]),
            minimum_clusters=int(policy["minimum_independent_clusters"]),
            strict_token_safety=False,
        )
        baseline_signals, baseline_signal_audit = _build_signals(
            points,
            lane=LANE_BASELINE,
            qualified_wallets=proxy_wallets,
            test_start=window["test_start_at"],
            test_end=window["test_end_at"],
            edges=edges,
            token_snapshots=token_snapshots,
            policy=policy,
            minimum_wallets=1,
            minimum_clusters=1,
            strict_token_safety=False,
        )

        for code, count in strict_signal_audit["skipped_reason_counts"].items():
            if count > 0 and code.startswith("POINT_IN_TIME_TOKEN_SAFETY"):
                global_gaps.add("POINT_IN_TIME_TOKEN_SAFETY_COVERAGE_INCOMPLETE")

        strict_candidates = [
            _simulate_signal(signal, token_points=by_token[signal.token_mint], policy=policy)
            for signal in strict_signals
        ]
        proxy_candidates = [
            _simulate_signal(signal, token_points=by_token[signal.token_mint], policy=policy)
            for signal in proxy_signals
        ]
        baseline_candidates = [
            _simulate_signal(signal, token_points=by_token[signal.token_mint], policy=policy)
            for signal in baseline_signals
        ]
        strict_metrics, strict_accepted = _portfolio_metrics(strict_candidates, policy)
        proxy_metrics, proxy_accepted = _portfolio_metrics(proxy_candidates, policy)
        baseline_metrics, baseline_accepted = _portfolio_metrics(baseline_candidates, policy)
        strict_all.extend(strict_candidates)
        proxy_all.extend(proxy_candidates)
        baseline_all.extend(baseline_candidates)
        strict_window_metrics.append(strict_metrics)
        proxy_window_metrics.append(proxy_metrics)
        baseline_window_metrics.append(baseline_metrics)

        window_evidence = {
            "test_wallet_count": len(test_wallets),
            "strict_wallet_evidence_coverage_percent": _round(
                len([item for item in strict_wallet_evidence.values() if item.get("run_id")])
                / len(test_wallets)
                * 100.0
                if test_wallets
                else 0.0,
                4,
            ),
            "strict_wallet_evidence": strict_wallet_evidence,
            "proxy_training_wallet_metrics": proxy_training,
            "strict_signal_audit": strict_signal_audit,
            "proxy_signal_audit": proxy_signal_audit,
            "baseline_signal_audit": baseline_signal_audit,
            "point_in_time_guard": True,
            "strict_lane_requires_historical_candidate_runs": True,
            "strict_lane_requires_historical_token_safety": True,
            "proxy_lane_bypasses_token_safety": True,
            "proxy_lane_is_not_profitability_proof": True,
            "price_integrity": {
                "excluded_price_mints": policy["excluded_price_mints"],
                "maximum_price_discontinuity_ratio": policy[
                    "maximum_price_discontinuity_ratio"
                ],
                "threshold_fill_enforced": True,
            },
        }
        window_hash = calculate_payload_hash(
            {
                "sequence": sequence,
                "train_start_at": window["train_start_at"].isoformat(),
                "train_end_at": window["train_end_at"].isoformat(),
                "test_start_at": window["test_start_at"].isoformat(),
                "test_end_at": window["test_end_at"].isoformat(),
                "strict_metrics": strict_metrics,
                "proxy_metrics": proxy_metrics,
                "baseline_metrics": baseline_metrics,
                "evidence": window_evidence,
            }
        )
        window_payloads.append(
            {
                "sequence": sequence,
                "train_start_at": window["train_start_at"].isoformat(),
                "train_end_at": window["train_end_at"].isoformat(),
                "test_start_at": window["test_start_at"].isoformat(),
                "test_end_at": window["test_end_at"].isoformat(),
                "strict_qualified_wallet_count": len(strict_wallets),
                "proxy_qualified_wallet_count": len(proxy_wallets),
                "strict_signal_count": len(strict_signals),
                "proxy_signal_count": len(proxy_signals),
                "baseline_signal_count": len(baseline_signals),
                "strict_metrics": strict_metrics,
                "proxy_metrics": proxy_metrics,
                "baseline_metrics": baseline_metrics,
                "evidence": window_evidence,
                "window_hash": window_hash,
                "trades": {
                    LANE_STRICT: [_serialize_outcome(item) for item in strict_candidates],
                    LANE_PROXY: [_serialize_outcome(item) for item in proxy_candidates],
                    LANE_BASELINE: [_serialize_outcome(item) for item in baseline_candidates],
                },
            }
        )

    strict_metrics = _aggregate_metrics(strict_window_metrics, strict_all, policy)
    proxy_metrics = _aggregate_metrics(proxy_window_metrics, proxy_all, policy)
    baseline_metrics = _aggregate_metrics(baseline_window_metrics, baseline_all, policy)
    verdict, strict_status, verdict_gaps = _verdict(
        strict_metrics=strict_metrics,
        proxy_metrics=proxy_metrics,
        policy=policy,
    )
    global_gaps.update(verdict_gaps)
    if not windows:
        global_gaps.add("INSUFFICIENT_HISTORY_FOR_WALK_FORWARD_WINDOWS")
    if len(token_snapshots) > 0:
        global_gaps.add("TOKEN_SAFETY_TABLE_STORES_ONLY_CURRENT_ROW_PER_TOKEN")

    summary = {
        "source_trade_count": len(trades),
        "valid_price_point_count": len(points),
        "price_integrity_audit": price_integrity_audit,
        "source_wallet_count": len({item.wallet_address for item in points}),
        "source_token_count": len({item.token_mint for item in points}),
        "window_count": len(window_payloads),
        "strict_closed_trade_count": strict_metrics["closed_trades"],
        "proxy_closed_trade_count": proxy_metrics["closed_trades"],
        "baseline_closed_trade_count": baseline_metrics["closed_trades"],
        "strict_vs_baseline_net_pnl_delta_sol": _round(
            float(strict_metrics["net_pnl_sol"]) - float(baseline_metrics["net_pnl_sol"])
        ),
        "proxy_vs_baseline_net_pnl_delta_sol": _round(
            float(proxy_metrics["net_pnl_sol"]) - float(baseline_metrics["net_pnl_sol"])
        ),
        "data_start_at": start_at.isoformat(),
        "data_end_at": latest.isoformat(),
        "interpretation": {
            "strict_lane": "Closest available Gen4 historical replay. Requires point-in-time wallet backtests and token-safety evidence.",
            "proxy_lane": "Consensus/economics proxy built only from prior training trades. It cannot prove Gen4 profitability.",
            "baseline_lane": "Single qualified-wallet copy baseline using the same execution and exit assumptions.",
        },
    }
    report_core = {
        "evaluated_at": now.isoformat(),
        "policy_version": GEN4_PROFITABILITY_POLICY_VERSION,
        "policy_hash": calculate_payload_hash(policy),
        "parameters": parameters,
        "verdict": verdict,
        "strict_evidence_status": strict_status,
        "summary": summary,
        "strict_metrics": strict_metrics,
        "proxy_metrics": proxy_metrics,
        "baseline_metrics": baseline_metrics,
        "evidence_gaps": sorted(global_gaps),
        "windows": window_payloads,
        "safety": _safety_contract(),
    }
    report_hash = calculate_payload_hash(report_core)
    return {
        "enabled": bool(getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_ENABLED", False)),
        "policy_snapshot": policy,
        **report_core,
        "report_hash": report_hash,
        "confirmation_required": GEN4_PROFITABILITY_CONFIRMATION,
        "writes_performed": False,
    }


def preview_gen4_profitability(
    db: Session,
    *,
    training_days: int | None = None,
    test_days: int | None = None,
    step_days: int | None = None,
    max_windows: int | None = None,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    return _build_report(
        db,
        training_days=training_days,
        test_days=test_days,
        step_days=step_days,
        max_windows=max_windows,
        settings_object=settings_object,
        evaluated_at=evaluated_at,
    )


def _serialize_persisted_run(db: Session, run: CanonicalParserGen4ProfitabilityRun) -> dict[str, Any]:
    windows = list(
        db.scalars(
            select(CanonicalParserGen4ProfitabilityWindow)
            .where(CanonicalParserGen4ProfitabilityWindow.run_db_id == run.id)
            .order_by(CanonicalParserGen4ProfitabilityWindow.sequence.asc())
        )
    )
    payload_windows: list[dict[str, Any]] = []
    for window in windows:
        trades = list(
            db.scalars(
                select(CanonicalParserGen4ProfitabilityTrade)
                .where(CanonicalParserGen4ProfitabilityTrade.window_db_id == window.id)
                .order_by(
                    CanonicalParserGen4ProfitabilityTrade.lane.asc(),
                    CanonicalParserGen4ProfitabilityTrade.sequence.asc(),
                )
            )
        )
        payload_windows.append(
            {
                "window_id": window.window_id,
                "sequence": window.sequence,
                "train_start_at": window.train_start_at,
                "train_end_at": window.train_end_at,
                "test_start_at": window.test_start_at,
                "test_end_at": window.test_end_at,
                "strict_qualified_wallet_count": window.strict_qualified_wallet_count,
                "proxy_qualified_wallet_count": window.proxy_qualified_wallet_count,
                "strict_signal_count": window.strict_signal_count,
                "proxy_signal_count": window.proxy_signal_count,
                "baseline_signal_count": window.baseline_signal_count,
                "strict_metrics": window.strict_metrics,
                "proxy_metrics": window.proxy_metrics,
                "baseline_metrics": window.baseline_metrics,
                "evidence": window.evidence,
                "window_hash": window.window_hash,
                "trades": [
                    {
                        "trade_id": item.trade_id,
                        "lane": item.lane,
                        "sequence": item.sequence,
                        "token_mint": item.token_mint,
                        "signal_at": item.signal_at,
                        "entry_at": item.entry_at,
                        "exit_at": item.exit_at,
                        "entry_price_sol": item.entry_price_sol,
                        "exit_price_sol": item.exit_price_sol,
                        "order_size_sol": item.order_size_sol,
                        "pnl_sol": item.pnl_sol,
                        "return_percent": item.return_percent,
                        "exit_reason": item.exit_reason,
                        "wallet_count": item.wallet_count,
                        "independent_cluster_count": item.independent_cluster_count,
                        "contributing_wallets": item.contributing_wallets,
                        "source_trade_ids": item.source_trade_ids,
                        "evidence": item.evidence,
                        "trade_hash": item.trade_hash,
                    }
                    for item in trades
                ],
            }
        )
    return {
        "run_id": run.run_id,
        "scope": run.scope,
        "status": run.status,
        "verdict": run.verdict,
        "strict_evidence_status": run.strict_evidence_status,
        "policy_version": run.policy_version,
        "policy_hash": run.policy_hash,
        "policy_snapshot": run.policy_snapshot,
        "parameters": run.parameters,
        "summary": run.summary,
        "strict_metrics": run.strict_metrics,
        "proxy_metrics": run.proxy_metrics,
        "baseline_metrics": run.baseline_metrics,
        "evidence_gaps": run.evidence_gaps,
        "safety": run.safety,
        "source_trade_count": run.source_trade_count,
        "source_wallet_count": run.source_wallet_count,
        "source_token_count": run.source_token_count,
        "window_count": run.window_count,
        "strict_closed_trade_count": run.strict_closed_trade_count,
        "proxy_closed_trade_count": run.proxy_closed_trade_count,
        "data_start_at": run.data_start_at,
        "data_end_at": run.data_end_at,
        "evaluated_at": run.evaluated_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "report_hash": run.report_hash,
        "actor_label": run.actor_label,
        "note": run.note,
        "technical_metadata": run.technical_metadata,
        "windows": payload_windows,
        "live_execution_authorized": False,
    }


def run_gen4_profitability_validation(
    db: Session,
    *,
    confirmation: str,
    training_days: int | None = None,
    test_days: int | None = None,
    step_days: int | None = None,
    max_windows: int | None = None,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_ENABLED", False)):
        raise CanonicalParserGen4ProfitabilityError(
            "M47 Gen4 Profitability Validation è disabilitato.",
            code="GEN4_PROFITABILITY_DISABLED",
            status_code=409,
        )
    if str(confirmation or "").strip() != GEN4_PROFITABILITY_CONFIRMATION:
        raise CanonicalParserGen4ProfitabilityError(
            f"Conferma richiesta: {GEN4_PROFITABILITY_CONFIRMATION}",
            code="GEN4_PROFITABILITY_CONFIRMATION_REQUIRED",
        )

    report = _build_report(
        db,
        training_days=training_days,
        test_days=test_days,
        step_days=step_days,
        max_windows=max_windows,
        settings_object=settings_object,
        evaluated_at=evaluated_at,
    )
    run_key = calculate_payload_hash(
        {
            "policy_hash": report["policy_hash"],
            "parameters": report["parameters"],
            "data_start_at": report["summary"].get("data_start_at"),
            "data_end_at": report["summary"].get("data_end_at"),
            "report_hash": report["report_hash"],
        }
    )
    existing = db.scalar(
        select(CanonicalParserGen4ProfitabilityRun).where(
            CanonicalParserGen4ProfitabilityRun.run_key == run_key
        )
    )
    if existing is not None:
        return _serialize_persisted_run(db, existing) | {"idempotent_replay": True}

    now = _aware(evaluated_at)
    run = CanonicalParserGen4ProfitabilityRun(
        run_id=str(uuid4()),
        run_key=run_key,
        scope=GEN4_PROFITABILITY_SCOPE,
        status="COMPLETED",
        verdict=report["verdict"],
        strict_evidence_status=report["strict_evidence_status"],
        policy_version=GEN4_PROFITABILITY_POLICY_VERSION,
        policy_hash=report["policy_hash"],
        policy_snapshot=report["policy_snapshot"],
        parameters=report["parameters"],
        summary=report["summary"],
        strict_metrics=report["strict_metrics"],
        proxy_metrics=report["proxy_metrics"],
        baseline_metrics=report["baseline_metrics"],
        evidence_gaps=report["evidence_gaps"],
        safety=_safety_contract(),
        source_trade_count=int(report["summary"]["source_trade_count"]),
        source_wallet_count=int(report["summary"]["source_wallet_count"]),
        source_token_count=int(report["summary"]["source_token_count"]),
        window_count=int(report["summary"]["window_count"]),
        strict_closed_trade_count=int(report["strict_metrics"]["closed_trades"]),
        proxy_closed_trade_count=int(report["proxy_metrics"]["closed_trades"]),
        data_start_at=(
            None
            if not report["summary"].get("data_start_at")
            else datetime.fromisoformat(report["summary"]["data_start_at"])
        ),
        data_end_at=(
            None
            if not report["summary"].get("data_end_at")
            else datetime.fromisoformat(report["summary"]["data_end_at"])
        ),
        evaluated_at=now,
        started_at=now,
        completed_at=now,
        report_hash=report["report_hash"],
        actor_label=_actor(actor_label),
        note=_note(note),
        technical_metadata={
            "source": "LOCAL_DATABASE_ONLY",
            "point_in_time_guard": True,
            "strict_lane": LANE_STRICT,
            "proxy_lane": LANE_PROXY,
            "baseline_lane": LANE_BASELINE,
            "external_requests": 0,
            "live_execution_authorized": False,
        },
    )
    db.add(run)
    try:
        db.flush()
        for window_payload in report["windows"]:
            window = CanonicalParserGen4ProfitabilityWindow(
                window_id=str(uuid4()),
                run_db_id=run.id,
                sequence=int(window_payload["sequence"]),
                train_start_at=datetime.fromisoformat(window_payload["train_start_at"]),
                train_end_at=datetime.fromisoformat(window_payload["train_end_at"]),
                test_start_at=datetime.fromisoformat(window_payload["test_start_at"]),
                test_end_at=datetime.fromisoformat(window_payload["test_end_at"]),
                strict_qualified_wallet_count=int(window_payload["strict_qualified_wallet_count"]),
                proxy_qualified_wallet_count=int(window_payload["proxy_qualified_wallet_count"]),
                strict_signal_count=int(window_payload["strict_signal_count"]),
                proxy_signal_count=int(window_payload["proxy_signal_count"]),
                baseline_signal_count=int(window_payload["baseline_signal_count"]),
                strict_metrics=window_payload["strict_metrics"],
                proxy_metrics=window_payload["proxy_metrics"],
                baseline_metrics=window_payload["baseline_metrics"],
                evidence=window_payload["evidence"],
                window_hash=window_payload["window_hash"],
            )
            db.add(window)
            db.flush()
            for lane in (LANE_STRICT, LANE_PROXY, LANE_BASELINE):
                for sequence, trade_payload in enumerate(window_payload["trades"][lane], start=1):
                    trade_hash = calculate_payload_hash(
                        {
                            "window_hash": window.window_hash,
                            "lane": lane,
                            "sequence": sequence,
                            "trade": trade_payload,
                        }
                    )
                    db.add(
                        CanonicalParserGen4ProfitabilityTrade(
                            trade_id=str(uuid4()),
                            window_db_id=window.id,
                            lane=lane,
                            sequence=sequence,
                            token_mint=trade_payload["token_mint"],
                            signal_at=datetime.fromisoformat(trade_payload["signal_at"]),
                            entry_at=(
                                None
                                if trade_payload["entry_at"] is None
                                else datetime.fromisoformat(trade_payload["entry_at"])
                            ),
                            exit_at=(
                                None
                                if trade_payload["exit_at"] is None
                                else datetime.fromisoformat(trade_payload["exit_at"])
                            ),
                            entry_price_sol=trade_payload["entry_price_sol"],
                            exit_price_sol=trade_payload["exit_price_sol"],
                            order_size_sol=float(trade_payload["order_size_sol"]),
                            pnl_sol=trade_payload["pnl_sol"],
                            return_percent=trade_payload["return_percent"],
                            exit_reason=trade_payload["exit_reason"],
                            wallet_count=len(trade_payload["contributing_wallets"]),
                            independent_cluster_count=int(trade_payload["independent_cluster_count"]),
                            contributing_wallets=trade_payload["contributing_wallets"],
                            source_trade_ids=trade_payload["source_trade_ids"],
                            evidence=trade_payload["evidence"],
                            trade_hash=trade_hash,
                        )
                    )
        db.flush()
    except IntegrityError as exception:
        db.rollback()
        existing = db.scalar(
            select(CanonicalParserGen4ProfitabilityRun).where(
                CanonicalParserGen4ProfitabilityRun.run_key == run_key
            )
        )
        if existing is not None:
            return _serialize_persisted_run(db, existing) | {"idempotent_replay": True}
        raise CanonicalParserGen4ProfitabilityError(
            "Impossibile persistere la validazione Gen4.",
            code="GEN4_PROFITABILITY_PERSISTENCE_CONFLICT",
            status_code=409,
        ) from exception
    return _serialize_persisted_run(db, run) | {"idempotent_replay": False}


def get_gen4_profitability_status(
    db: Session,
    *,
    settings_object: Any = settings,
) -> dict[str, Any]:
    policy = _policy_snapshot(settings_object)
    latest = db.scalar(
        select(CanonicalParserGen4ProfitabilityRun)
        .order_by(desc(CanonicalParserGen4ProfitabilityRun.completed_at), desc(CanonicalParserGen4ProfitabilityRun.id))
        .limit(1)
    )
    verdict_counts = {
        str(verdict): int(count)
        for verdict, count in db.execute(
            select(
                CanonicalParserGen4ProfitabilityRun.verdict,
                func.count(CanonicalParserGen4ProfitabilityRun.id),
            ).group_by(CanonicalParserGen4ProfitabilityRun.verdict)
        )
    }
    return {
        "enabled": bool(getattr(settings_object, "CANONICAL_PARSER_GEN4_PROFITABILITY_ENABLED", False)),
        "policy_version": GEN4_PROFITABILITY_POLICY_VERSION,
        "policy_hash": calculate_payload_hash(policy),
        "policy": policy,
        "run_count": int(db.scalar(select(func.count(CanonicalParserGen4ProfitabilityRun.id))) or 0),
        "window_count": int(db.scalar(select(func.count(CanonicalParserGen4ProfitabilityWindow.id))) or 0),
        "trade_evidence_count": int(db.scalar(select(func.count(CanonicalParserGen4ProfitabilityTrade.id))) or 0),
        "verdict_counts": verdict_counts,
        "latest_run": None if latest is None else _serialize_persisted_run(db, latest),
        "confirmation_required": GEN4_PROFITABILITY_CONFIRMATION,
        "safety": _safety_contract(),
    }


def get_gen4_profitability_run(db: Session, run_id: str) -> dict[str, Any]:
    run = db.scalar(
        select(CanonicalParserGen4ProfitabilityRun).where(
            CanonicalParserGen4ProfitabilityRun.run_id == run_id
        )
    )
    if run is None:
        raise CanonicalParserGen4ProfitabilityError(
            "Validazione Gen4 non trovata.",
            code="GEN4_PROFITABILITY_RUN_NOT_FOUND",
            status_code=404,
        )
    return _serialize_persisted_run(db, run)
