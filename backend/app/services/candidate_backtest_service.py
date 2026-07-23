from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.core.constants import SOL_MINT
from backend.app.models.candidate_backtest import CandidateBacktestRun
from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.models.trade import Trade
from backend.app.services.candidate_jupiter_compatibility_service import (
    JUPITER_FAILED,
    JUPITER_NOT_CHECKED,
    JUPITER_PASSED,
    JUPITER_UNAVAILABLE,
    check_candidate_jupiter_compatibility,
)
from backend.app.services.jupiter_swap_client import JupiterSwapClient
from backend.app.services.wallet_activity_service import ensure_aware, safe_float


PROMOTION_PROMOTED = "PROMOSSO"
PROMOTION_OBSERVATION = "OSSERVAZIONE"
PROMOTION_REJECTED = "BOCCIATO"
PROMOTION_INSUFFICIENT = "DATI_INSUFFICIENTI"
PROMOTION_NOT_ANALYZED = "NON_ANALIZZATO"

MIN_SMART_SCORE = 60.0
MIN_COMPLETED_POSITIONS = 5
MIN_HISTORY_SPAN_DAYS = 5.0
MIN_ANALYSIS_SOURCE_TRADES = 10
MIN_MATCHED_SELL_RATIO_PERCENT = 50.0
MIN_WIN_RATE_PERCENT = 40.0
MIN_PROFIT_FACTOR = 1.10
MAX_DRAWDOWN_PERCENT = 25.0
MAX_REJECT_DRAWDOWN_PERCENT = 40.0
MIN_EXECUTION_COVERAGE_PERCENT = 40.0
MAX_OPEN_POSITIONS_AT_END = 2
MAX_OPEN_POSITION_RATIO_PERCENT = 50.0
MIN_JUPITER_COMPATIBILITY_PERCENT = 80.0


@dataclass
class SimulatedPosition:
    token_mint: str
    quantity: float
    cost_basis_sol: float
    entry_price_sol: float
    entry_at: datetime
    entry_signature: str
    bootstrap: bool = False


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _round(value: float, digits: int = 8) -> float:
    return round(float(value or 0.0), digits)


def _effective_market_friction_bps(
    *,
    slippage_bps: int,
    copy_delay_seconds: int,
    delay_penalty_bps_per_minute: float,
) -> float:
    delay_penalty = (
        max(0, copy_delay_seconds) / 60.0 * max(0.0, delay_penalty_bps_per_minute)
    )
    return min(2000.0, max(0.0, float(slippage_bps)) + delay_penalty)


def _source_price(trade: Trade) -> float | None:
    sol_amount = abs(safe_float(trade.sol_amount))
    token_amount = abs(safe_float(trade.token_amount))
    if sol_amount <= 0 or token_amount <= 0:
        return None
    return sol_amount / token_amount


def _mark_to_market(
    *,
    cash: float,
    positions: dict[str, SimulatedPosition],
    last_prices: dict[str, float],
    friction_bps: float,
    fee_bps: int,
) -> float:
    value = cash
    friction_ratio = friction_bps / 10_000.0
    fee_ratio = max(0, fee_bps) / 10_000.0
    for token, position in positions.items():
        price = last_prices.get(token, position.entry_price_sol)
        gross = position.quantity * price * max(0.0, 1.0 - friction_ratio)
        value += gross * max(0.0, 1.0 - fee_ratio)
    return max(0.0, value)


def _open_position(
    *,
    token: str,
    trade: Trade,
    timestamp: datetime,
    price: float,
    fixed_buy_size_sol: float,
    friction_ratio: float,
    fee_ratio: float,
) -> SimulatedPosition | None:
    entry_fee = fixed_buy_size_sol * fee_ratio
    net_input = max(0.0, fixed_buy_size_sol - entry_fee)
    execution_price = price * (1.0 + friction_ratio)
    quantity = net_input / execution_price if execution_price > 0 else 0.0
    if quantity <= 0:
        return None
    return SimulatedPosition(
        token_mint=token,
        quantity=quantity,
        cost_basis_sol=fixed_buy_size_sol,
        entry_price_sol=execution_price,
        entry_at=timestamp,
        entry_signature=str(trade.signature),
    )


def _prepare_bootstrap_state(
    trades: list[Trade],
    *,
    cutoff: datetime,
    starting_capital_sol: float,
    fixed_buy_size_sol: float,
    friction_bps: float,
    fee_bps: int,
    max_open_positions: int,
) -> tuple[float, dict[str, SimulatedPosition], dict[str, float], int]:
    friction_ratio = friction_bps / 10_000.0
    fee_ratio = fee_bps / 10_000.0
    cash = float(starting_capital_sol)
    positions: dict[str, SimulatedPosition] = {}
    last_prices: dict[str, float] = {}

    for trade in trades:
        token = str(trade.token_mint or "").strip()
        side = str(trade.side or "UNKNOWN").strip().upper()
        price = _source_price(trade)
        timestamp = ensure_aware(trade.block_time) or cutoff
        if not token or token == SOL_MINT or side not in {"BUY", "SELL"} or price is None:
            continue
        last_prices[token] = price

        if side == "BUY":
            if token in positions or len(positions) >= max_open_positions:
                continue
            if cash + 1e-12 < fixed_buy_size_sol:
                continue
            position = _open_position(
                token=token,
                trade=trade,
                timestamp=timestamp,
                price=price,
                fixed_buy_size_sol=fixed_buy_size_sol,
                friction_ratio=friction_ratio,
                fee_ratio=fee_ratio,
            )
            if position is not None:
                positions[token] = position
                cash -= fixed_buy_size_sol
        else:
            position = positions.get(token)
            if position is None:
                continue
            execution_price = price * max(0.0, 1.0 - friction_ratio)
            gross_proceeds = position.quantity * execution_price
            proceeds = max(0.0, gross_proceeds - gross_proceeds * fee_ratio)
            cash += proceeds
            del positions[token]

    # Rebase carried positions at the start of the analysis window. This prevents
    # warmup-period PnL from leaking into the measured backtest return.
    for token, position in positions.items():
        price = last_prices.get(token, position.entry_price_sol)
        gross = position.quantity * price * max(0.0, 1.0 - friction_ratio)
        marked_value = gross * max(0.0, 1.0 - fee_ratio)
        position.cost_basis_sol = max(0.0, marked_value)
        position.entry_price_sol = price
        position.entry_at = cutoff
        position.entry_signature = f"BOOTSTRAP:{position.entry_signature}"
        position.bootstrap = True

    return cash, positions, last_prices, len(positions)


def _data_sufficiency(metrics: dict[str, Any]) -> tuple[bool, float, list[str]]:
    reasons: list[str] = []
    completed = int(metrics["completed_positions"])
    history_span = safe_float(metrics["history_span_days"])
    analysis_trades = int(metrics["analysis_source_trades"])
    coverage = safe_float(metrics["execution_coverage_percent"])
    matched_sell_ratio = safe_float(metrics["matched_sell_ratio_percent"])
    open_ratio = safe_float(metrics["open_position_ratio_percent"])

    if completed < MIN_COMPLETED_POSITIONS:
        reasons.append("COMPLETED_POSITIONS_BELOW_SUFFICIENCY_MINIMUM")
    if history_span < MIN_HISTORY_SPAN_DAYS:
        reasons.append("HISTORY_SPAN_TOO_SHORT")
    if analysis_trades < MIN_ANALYSIS_SOURCE_TRADES:
        reasons.append("ANALYSIS_SAMPLE_TOO_SMALL")
    if coverage < MIN_EXECUTION_COVERAGE_PERCENT:
        reasons.append("EXECUTION_COVERAGE_TOO_LOW")
    if matched_sell_ratio < MIN_MATCHED_SELL_RATIO_PERCENT:
        reasons.append("MATCHED_SELL_RATIO_TOO_LOW")
    if open_ratio > MAX_OPEN_POSITION_RATIO_PERCENT:
        reasons.append("OPEN_POSITION_RATIO_TOO_HIGH")

    components = (
        min(1.0, completed / MIN_COMPLETED_POSITIONS),
        min(1.0, history_span / MIN_HISTORY_SPAN_DAYS),
        min(1.0, analysis_trades / MIN_ANALYSIS_SOURCE_TRADES),
        min(1.0, coverage / MIN_EXECUTION_COVERAGE_PERCENT),
        min(1.0, matched_sell_ratio / MIN_MATCHED_SELL_RATIO_PERCENT),
        min(1.0, MAX_OPEN_POSITION_RATIO_PERCENT / open_ratio)
        if open_ratio > 0
        else 1.0,
    )
    score = sum(components) / len(components) * 100.0
    return not reasons, _round(score, 4), reasons


def _backtest_score(metrics: dict[str, Any]) -> float:
    total_return = safe_float(metrics["total_return_percent"])
    win_rate = safe_float(metrics["win_rate_percent"])
    profit_factor = metrics["profit_factor"]
    drawdown = safe_float(metrics["max_drawdown_percent"])
    coverage = safe_float(metrics["execution_coverage_percent"])
    completed = int(metrics["completed_positions"])
    jupiter = safe_float(metrics["jupiter_compatibility_percent"])
    sufficiency = safe_float(metrics["data_sufficiency_score"])

    return_component = max(0.0, min(17.5, 8.75 + total_return / 2.0))
    win_component = max(0.0, min(12.5, win_rate / 100.0 * 12.5))
    if profit_factor is None:
        pf_component = 0.0
    else:
        pf_component = max(0.0, min(17.5, safe_float(profit_factor) / 2.0 * 17.5))
    drawdown_component = max(0.0, 12.5 * (1.0 - min(drawdown, 50.0) / 50.0))
    coverage_component = max(0.0, min(10.0, coverage / 100.0 * 10.0))
    sample_component = max(0.0, min(10.0, completed / 10.0 * 10.0))
    jupiter_component = max(0.0, min(10.0, jupiter / 100.0 * 10.0))
    sufficiency_component = max(0.0, min(10.0, sufficiency / 100.0 * 10.0))
    return _round(
        return_component
        + win_component
        + pf_component
        + drawdown_component
        + coverage_component
        + sample_component
        + jupiter_component
        + sufficiency_component,
        4,
    )


def _promotion_decision(
    wallet: DiscoveredWallet,
    metrics: dict[str, Any],
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if wallet.activity_classification != "ATTIVO":
        reasons.append("ACTIVITY_NOT_ACTIVE")
    if wallet.quality_classification != "COPIABILE":
        reasons.append("QUALITY_NOT_COPYABLE")
    if safe_float(wallet.smart_score) < MIN_SMART_SCORE:
        reasons.append("SMART_SCORE_BELOW_PROMOTION_MINIMUM")

    preconditions_passed = (
        wallet.activity_classification == "ATTIVO"
        and wallet.quality_classification == "COPIABILE"
        and safe_float(wallet.smart_score) >= MIN_SMART_SCORE
    )
    if not preconditions_passed:
        return PROMOTION_OBSERVATION, list(dict.fromkeys(reasons))

    if not bool(metrics["data_sufficient"]):
        reasons.extend(metrics["data_sufficiency_reasons"])
        return PROMOTION_INSUFFICIENT, list(dict.fromkeys(reasons))

    completed = int(metrics["completed_positions"])
    total_return = safe_float(metrics["total_return_percent"])
    win_rate = safe_float(metrics["win_rate_percent"])
    profit_factor = metrics["profit_factor"]
    drawdown = safe_float(metrics["max_drawdown_percent"])
    coverage = safe_float(metrics["execution_coverage_percent"])
    open_positions = int(metrics["open_positions"])
    jupiter_status = str(metrics["jupiter_status"])
    jupiter_compatibility = safe_float(metrics["jupiter_compatibility_percent"])

    if total_return <= 0:
        reasons.append("NON_POSITIVE_NET_RETURN")
    if win_rate < MIN_WIN_RATE_PERCENT:
        reasons.append("WIN_RATE_BELOW_PROMOTION_MINIMUM")
    if profit_factor is None:
        reasons.append("PROFIT_FACTOR_NOT_AVAILABLE")
    elif safe_float(profit_factor) < MIN_PROFIT_FACTOR:
        reasons.append("PROFIT_FACTOR_BELOW_PROMOTION_MINIMUM")
    if drawdown > MAX_DRAWDOWN_PERCENT:
        reasons.append("DRAWDOWN_ABOVE_PROMOTION_MAXIMUM")
    if coverage < MIN_EXECUTION_COVERAGE_PERCENT:
        reasons.append("EXECUTION_COVERAGE_TOO_LOW")
    if open_positions > MAX_OPEN_POSITIONS_AT_END:
        reasons.append("TOO_MANY_OPEN_POSITIONS")
    if jupiter_status == JUPITER_NOT_CHECKED:
        reasons.append("JUPITER_CHECK_REQUIRED")
    elif jupiter_status == JUPITER_UNAVAILABLE:
        reasons.append("JUPITER_CHECK_UNAVAILABLE")
    elif jupiter_status != JUPITER_PASSED:
        reasons.append("JUPITER_COMPATIBILITY_FAILED")
    elif jupiter_compatibility < MIN_JUPITER_COMPATIBILITY_PERCENT:
        reasons.append("JUPITER_COMPATIBILITY_TOO_LOW")

    promoted = all(
        (
            completed >= MIN_COMPLETED_POSITIONS,
            total_return > 0,
            win_rate >= MIN_WIN_RATE_PERCENT,
            profit_factor is not None and safe_float(profit_factor) >= MIN_PROFIT_FACTOR,
            drawdown <= MAX_DRAWDOWN_PERCENT,
            coverage >= MIN_EXECUTION_COVERAGE_PERCENT,
            open_positions <= MAX_OPEN_POSITIONS_AT_END,
            jupiter_status == JUPITER_PASSED,
            jupiter_compatibility >= MIN_JUPITER_COMPATIBILITY_PERCENT,
        )
    )
    if promoted:
        return PROMOTION_PROMOTED, []

    hard_rejection = any(
        (
            total_return <= -5.0,
            drawdown > MAX_REJECT_DRAWDOWN_PERCENT,
            profit_factor is not None and safe_float(profit_factor) < 0.80,
            jupiter_status == JUPITER_FAILED and jupiter_compatibility == 0,
        )
    )
    if hard_rejection:
        return PROMOTION_REJECTED, list(dict.fromkeys(reasons))
    return PROMOTION_OBSERVATION, list(dict.fromkeys(reasons))


def run_candidate_backtest(
    db: Session,
    *,
    wallet_address: str,
    lookback_days: int = 30,
    warmup_days: int = 14,
    starting_capital_sol: float = 1.0,
    fixed_buy_size_sol: float = 0.05,
    slippage_bps: int = 100,
    fee_bps: int = 10,
    copy_delay_seconds: int = 8,
    delay_penalty_bps_per_minute: float = 25.0,
    max_open_positions: int = 5,
    check_jupiter: bool = True,
    jupiter_token_limit: int = 10,
    jupiter_cache_ttl_hours: int = 6,
    force_jupiter_refresh: bool = False,
    now: datetime | None = None,
    jupiter_client: JupiterSwapClient | None = None,
) -> CandidateBacktestRun:
    started_at = ensure_aware(now) or utc_now()
    wallet = (
        db.query(DiscoveredWallet)
        .filter(DiscoveredWallet.wallet_address == wallet_address)
        .first()
    )
    if wallet is None:
        raise ValueError("Wallet scoperto non trovato")

    effective_lookback = max(1, min(int(lookback_days), 90))
    effective_warmup = max(0, min(int(warmup_days), 60))
    cutoff = started_at - timedelta(days=effective_lookback)
    warmup_cutoff = cutoff - timedelta(days=effective_warmup)
    trades = (
        db.query(Trade)
        .filter(Trade.wallet_address == wallet_address)
        .filter(Trade.success.is_(True))
        .filter(Trade.block_time.isnot(None))
        .filter(Trade.block_time >= warmup_cutoff)
        .filter(Trade.block_time <= started_at)
        .order_by(Trade.block_time.asc(), Trade.id.asc())
        .all()
    )
    warmup_trades = [
        trade for trade in trades if (ensure_aware(trade.block_time) or started_at) < cutoff
    ]
    analysis_trades = [
        trade for trade in trades if (ensure_aware(trade.block_time) or started_at) >= cutoff
    ]

    friction_bps = _effective_market_friction_bps(
        slippage_bps=slippage_bps,
        copy_delay_seconds=copy_delay_seconds,
        delay_penalty_bps_per_minute=delay_penalty_bps_per_minute,
    )
    friction_ratio = friction_bps / 10_000.0
    fee_ratio = fee_bps / 10_000.0
    cash, positions, last_prices, bootstrap_positions = _prepare_bootstrap_state(
        warmup_trades,
        cutoff=cutoff,
        starting_capital_sol=starting_capital_sol,
        fixed_buy_size_sol=fixed_buy_size_sol,
        friction_bps=friction_bps,
        fee_bps=fee_bps,
        max_open_positions=max_open_positions,
    )
    effective_starting_equity = _mark_to_market(
        cash=cash,
        positions=positions,
        last_prices=last_prices,
        friction_bps=friction_bps,
        fee_bps=fee_bps,
    )
    if effective_starting_equity <= 0:
        effective_starting_equity = float(starting_capital_sol)
        cash = float(starting_capital_sol)
        positions = {}
        last_prices = {}
        bootstrap_positions = 0

    closed_results: list[dict[str, Any]] = []
    all_tokens: set[str] = set(positions)
    bootstrap_closed = 0
    counters = {
        "valid_priced_trades": 0,
        "buy_signals": 0,
        "sell_signals": 0,
        "executed_buys": 0,
        "completed_positions": 0,
        "skipped_invalid": 0,
        "skipped_existing_position": 0,
        "skipped_max_positions": 0,
        "skipped_insufficient_capital": 0,
        "unmatched_sells": 0,
    }
    peak_equity = float(effective_starting_equity)
    max_drawdown_percent = 0.0

    for trade in analysis_trades:
        token = str(trade.token_mint or "").strip()
        side = str(trade.side or "UNKNOWN").strip().upper()
        price = _source_price(trade)
        timestamp = ensure_aware(trade.block_time) or started_at

        if not token or token == SOL_MINT or side not in {"BUY", "SELL"} or price is None:
            counters["skipped_invalid"] += 1
            continue

        counters["valid_priced_trades"] += 1
        all_tokens.add(token)
        last_prices[token] = price

        if side == "BUY":
            counters["buy_signals"] += 1
            if token in positions:
                counters["skipped_existing_position"] += 1
            elif len(positions) >= max_open_positions:
                counters["skipped_max_positions"] += 1
            elif cash + 1e-12 < fixed_buy_size_sol:
                counters["skipped_insufficient_capital"] += 1
            else:
                position = _open_position(
                    token=token,
                    trade=trade,
                    timestamp=timestamp,
                    price=price,
                    fixed_buy_size_sol=fixed_buy_size_sol,
                    friction_ratio=friction_ratio,
                    fee_ratio=fee_ratio,
                )
                if position is None:
                    counters["skipped_invalid"] += 1
                else:
                    positions[token] = position
                    cash -= fixed_buy_size_sol
                    counters["executed_buys"] += 1

        else:
            counters["sell_signals"] += 1
            position = positions.get(token)
            if position is None:
                counters["unmatched_sells"] += 1
            else:
                execution_price = price * max(0.0, 1.0 - friction_ratio)
                gross_proceeds = position.quantity * execution_price
                exit_fee = gross_proceeds * fee_ratio
                proceeds = max(0.0, gross_proceeds - exit_fee)
                pnl = proceeds - position.cost_basis_sol
                cash += proceeds
                counters["completed_positions"] += 1
                if position.bootstrap:
                    bootstrap_closed += 1
                closed_results.append(
                    {
                        "token_mint": token,
                        "entry_at": position.entry_at.isoformat(),
                        "exit_at": timestamp.isoformat(),
                        "entry_signature": position.entry_signature,
                        "exit_signature": str(trade.signature),
                        "bootstrap": position.bootstrap,
                        "cost_basis_sol": _round(position.cost_basis_sol),
                        "proceeds_sol": _round(proceeds),
                        "pnl_sol": _round(pnl),
                        "return_percent": _round(
                            pnl / position.cost_basis_sol * 100.0
                            if position.cost_basis_sol > 0
                            else 0.0,
                            4,
                        ),
                    }
                )
                del positions[token]

        equity = _mark_to_market(
            cash=cash,
            positions=positions,
            last_prices=last_prices,
            friction_bps=friction_bps,
            fee_bps=fee_bps,
        )
        peak_equity = max(peak_equity, equity)
        if peak_equity > 0:
            drawdown = (peak_equity - equity) / peak_equity * 100.0
            max_drawdown_percent = max(max_drawdown_percent, drawdown)

    realized_pnl = sum(safe_float(item["pnl_sol"]) for item in closed_results)
    gross_profit = sum(max(0.0, safe_float(item["pnl_sol"])) for item in closed_results)
    gross_loss = sum(min(0.0, safe_float(item["pnl_sol"])) for item in closed_results)
    winning = sum(1 for item in closed_results if safe_float(item["pnl_sol"]) > 1e-12)
    losing = sum(1 for item in closed_results if safe_float(item["pnl_sol"]) < -1e-12)
    breakeven = len(closed_results) - winning - losing
    win_rate = winning / len(closed_results) * 100.0 if closed_results else 0.0
    profit_factor = (
        gross_profit / abs(gross_loss)
        if gross_loss < 0
        else (999.0 if gross_profit > 0 else None)
    )

    ending_equity = _mark_to_market(
        cash=cash,
        positions=positions,
        last_prices=last_prices,
        friction_bps=friction_bps,
        fee_bps=fee_bps,
    )
    open_cost = sum(position.cost_basis_sol for position in positions.values())
    open_value = max(0.0, ending_equity - cash)
    unrealized_pnl = open_value - open_cost
    net_pnl = ending_equity - effective_starting_equity
    total_return = (
        net_pnl / effective_starting_equity * 100.0
        if effective_starting_equity > 0
        else 0.0
    )
    actionable = counters["buy_signals"] + counters["sell_signals"]
    executed_actions = counters["executed_buys"] + counters["completed_positions"]
    coverage = executed_actions / actionable * 100.0 if actionable else 0.0
    matched_sell_ratio = (
        counters["completed_positions"] / counters["sell_signals"] * 100.0
        if counters["sell_signals"]
        else 0.0
    )
    opened_total = counters["executed_buys"] + bootstrap_positions
    open_position_ratio = len(positions) / opened_total * 100.0 if opened_total else 0.0

    timestamps = [ensure_aware(trade.block_time) for trade in trades]
    timestamps = [item for item in timestamps if item is not None]
    history_oldest_at = min(timestamps) if timestamps else None
    history_newest_at = max(timestamps) if timestamps else None
    history_span_days = (
        (history_newest_at - history_oldest_at).total_seconds() / 86_400.0
        if history_oldest_at and history_newest_at
        else 0.0
    )

    if check_jupiter:
        jupiter = check_candidate_jupiter_compatibility(
            db,
            sorted(all_tokens),
            fixed_buy_size_sol=fixed_buy_size_sol,
            slippage_bps=slippage_bps,
            token_limit=jupiter_token_limit,
            client=jupiter_client or JupiterSwapClient(),
            cache_ttl_hours=jupiter_cache_ttl_hours,
            force_refresh=force_jupiter_refresh,
            minimum_compatibility_percent=MIN_JUPITER_COMPATIBILITY_PERCENT,
            now=started_at,
        )
    else:
        jupiter = {
            "checked": False,
            "status": JUPITER_NOT_CHECKED,
            "tokens_checked": 0,
            "tokens_compatible": 0,
            "requests": 0,
            "cache_hits": 0,
            "live_checks": 0,
            "compatibility_percent": 0.0,
            "results": [],
        }

    metrics: dict[str, Any] = {
        "source_trades": len(trades),
        "warmup_source_trades": len(warmup_trades),
        "analysis_source_trades": len(analysis_trades),
        "bootstrap_positions": bootstrap_positions,
        "bootstrap_positions_closed": bootstrap_closed,
        **counters,
        "winning_positions": winning,
        "losing_positions": losing,
        "breakeven_positions": breakeven,
        "open_positions": len(positions),
        "unique_tokens": len(all_tokens),
        "starting_capital_sol": _round(starting_capital_sol),
        "effective_starting_equity_sol": _round(effective_starting_equity),
        "ending_equity_sol": _round(ending_equity),
        "realized_pnl_sol": _round(realized_pnl),
        "unrealized_pnl_sol": _round(unrealized_pnl),
        "net_pnl_sol": _round(net_pnl),
        "total_return_percent": _round(total_return, 4),
        "win_rate_percent": _round(win_rate, 4),
        "profit_factor": _round(profit_factor, 4) if profit_factor is not None else None,
        "max_drawdown_percent": _round(max_drawdown_percent, 4),
        "execution_coverage_percent": _round(coverage, 4),
        "matched_sell_ratio_percent": _round(matched_sell_ratio, 4),
        "open_position_ratio_percent": _round(open_position_ratio, 4),
        "history_span_days": _round(history_span_days, 4),
        "history_oldest_at": history_oldest_at,
        "history_newest_at": history_newest_at,
        "jupiter_checked": bool(jupiter["checked"]),
        "jupiter_status": jupiter["status"],
        "jupiter_tokens_checked": jupiter["tokens_checked"],
        "jupiter_tokens_compatible": jupiter["tokens_compatible"],
        "jupiter_requests": jupiter["requests"],
        "jupiter_cache_hits": jupiter["cache_hits"],
        "jupiter_live_checks": jupiter["live_checks"],
        "jupiter_compatibility_percent": jupiter["compatibility_percent"],
    }
    data_sufficient, sufficiency_score, sufficiency_reasons = _data_sufficiency(metrics)
    metrics["data_sufficient"] = data_sufficient
    metrics["data_sufficiency_score"] = sufficiency_score
    metrics["data_sufficiency_reasons"] = sufficiency_reasons

    decision, reasons = _promotion_decision(wallet, metrics)
    score = _backtest_score(metrics)
    completed_at = utc_now()

    parameters = {
        "lookback_days": effective_lookback,
        "warmup_days": effective_warmup,
        "starting_capital_sol": starting_capital_sol,
        "fixed_buy_size_sol": fixed_buy_size_sol,
        "slippage_bps": slippage_bps,
        "fee_bps": fee_bps,
        "copy_delay_seconds": copy_delay_seconds,
        "delay_penalty_bps_per_minute": delay_penalty_bps_per_minute,
        "effective_market_friction_bps": _round(friction_bps, 4),
        "max_open_positions": max_open_positions,
        "check_jupiter": check_jupiter,
        "jupiter_token_limit": jupiter_token_limit,
        "jupiter_cache_ttl_hours": max(1, min(int(jupiter_cache_ttl_hours), 24)),
        "force_jupiter_refresh": force_jupiter_refresh,
        "sufficiency_thresholds": {
            "minimum_completed_positions": MIN_COMPLETED_POSITIONS,
            "minimum_history_span_days": MIN_HISTORY_SPAN_DAYS,
            "minimum_analysis_source_trades": MIN_ANALYSIS_SOURCE_TRADES,
            "minimum_execution_coverage_percent": MIN_EXECUTION_COVERAGE_PERCENT,
            "minimum_matched_sell_ratio_percent": MIN_MATCHED_SELL_RATIO_PERCENT,
            "maximum_open_position_ratio_percent": MAX_OPEN_POSITION_RATIO_PERCENT,
        },
    }
    safety = {
        "dry_run_only": True,
        "transactions_signed": False,
        "transactions_submitted": False,
        "live_enabled": False,
        "stream_changed": False,
        "worker_started": False,
        "wallets_applied": False,
        "generation_reset": False,
        "generation_created": False,
        "helius_requests": 0,
    }

    run = CandidateBacktestRun(
        run_id=str(uuid4()),
        wallet_address=wallet_address,
        status="COMPLETED",
        decision=decision,
        score=score,
        reasons=reasons,
        parameters=parameters,
        safety=safety,
        **metrics,
        jupiter_results=jupiter["results"],
        position_results=closed_results,
        started_at=started_at,
        completed_at=completed_at,
    )
    db.add(run)
    db.flush()

    wallet.promotion_status = decision
    wallet.promotion_eligible = decision == PROMOTION_PROMOTED and data_sufficient
    wallet.promotion_reasons = reasons
    wallet.promotion_calculated_at = completed_at
    wallet.latest_backtest_run_id = run.run_id
    wallet.backtest_score = score
    wallet.backtest_total_return_percent = metrics["total_return_percent"]
    wallet.backtest_net_pnl_sol = metrics["net_pnl_sol"]
    wallet.backtest_win_rate_percent = metrics["win_rate_percent"]
    wallet.backtest_profit_factor = metrics["profit_factor"]
    wallet.backtest_max_drawdown_percent = metrics["max_drawdown_percent"]
    wallet.backtest_completed_positions = metrics["completed_positions"]
    wallet.backtest_open_positions = metrics["open_positions"]
    wallet.backtest_execution_coverage_percent = metrics["execution_coverage_percent"]
    wallet.backtest_jupiter_status = metrics["jupiter_status"]
    wallet.backtest_jupiter_compatibility_percent = metrics[
        "jupiter_compatibility_percent"
    ]
    wallet.backtest_data_sufficient = data_sufficient
    wallet.backtest_data_sufficiency_score = sufficiency_score
    wallet.backtest_data_sufficiency_reasons = sufficiency_reasons
    wallet.backtest_history_span_days = metrics["history_span_days"]
    wallet.backtest_bootstrap_positions = bootstrap_positions
    wallet.backtest_matched_sell_ratio_percent = metrics[
        "matched_sell_ratio_percent"
    ]
    wallet.eligible = bool(
        wallet.activity_eligible
        and wallet.quality_eligible
        and wallet.promotion_eligible
        and wallet.backtest_data_sufficient
        and safe_float(wallet.smart_score) >= MIN_SMART_SCORE
    )
    base_reasons = list(wallet.activity_reasons or []) + list(wallet.quality_reasons or [])
    wallet.eligibility_reasons = list(
        dict.fromkeys(base_reasons + sufficiency_reasons + reasons)
    )
    if not wallet.promotion_eligible:
        wallet.eligibility_reasons = list(
            dict.fromkeys([*wallet.eligibility_reasons, "PROMOTION_GATE_NOT_PASSED"])
        )
    if not wallet.backtest_data_sufficient:
        wallet.eligibility_reasons = list(
            dict.fromkeys([*wallet.eligibility_reasons, "BACKTEST_DATA_INSUFFICIENT"])
        )
    wallet.status = "PROMOTED" if wallet.promotion_eligible else "UPDATED"

    db.commit()
    db.refresh(run)
    db.refresh(wallet)
    return run


def get_latest_candidate_backtest(
    db: Session,
    wallet_address: str,
) -> CandidateBacktestRun | None:
    return (
        db.query(CandidateBacktestRun)
        .filter(CandidateBacktestRun.wallet_address == wallet_address)
        .order_by(CandidateBacktestRun.completed_at.desc(), CandidateBacktestRun.id.desc())
        .first()
    )
