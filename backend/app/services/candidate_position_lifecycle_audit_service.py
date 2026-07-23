from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.models.candidate_position_lifecycle_audit import (
    CandidatePositionLifecycleAuditRun,
)
from backend.app.models.discovered_wallet import DiscoveredWallet
from backend.app.models.trade import Trade
from backend.app.services.candidate_reconstruction_audit_service import (
    AuditPosition,
    _latest_jupiter_map,
    _market_friction_bps,
    _mark_to_market,
    _open_position,
    _parse_trade,
    _round,
    _sell_position,
    utc_now,
)
from backend.app.services.wallet_activity_service import (
    ensure_aware,
    safe_float,
)


HOLDING_PERIOD_SCENARIOS = (
    None,
    24,
    72,
    168,
)
DUST_REMAINDER_SOL = 0.001


@dataclass
class LifecyclePosition(AuditPosition):
    source_buys_total: int = 0
    source_sells_total: int = 0
    analysis_source_buys: int = 0
    analysis_source_sells: int = 0
    source_bought_quantity: float = 0.0
    source_sold_quantity: float = 0.0
    matched_sell_actions: int = 0
    last_source_activity_at: datetime | None = None
    last_source_activity_side: str | None = None
    last_executable_price_sol: float | None = None
    last_executable_price_at: datetime | None = None
    sell_before_analysis_count: int = 0
    lifecycle_events: list[dict] = field(
        default_factory=list
    )


def _as_lifecycle_position(
    position: AuditPosition,
) -> LifecyclePosition:
    return LifecyclePosition(
        token_mint=position.token_mint,
        quantity=position.quantity,
        original_cost_basis_sol=(
            position.original_cost_basis_sol
        ),
        remaining_cost_basis_sol=(
            position.remaining_cost_basis_sol
        ),
        entry_price_sol=position.entry_price_sol,
        entry_at=position.entry_at,
        entry_signature=position.entry_signature,
        bootstrap=position.bootstrap,
        realized_pnl_sol=position.realized_pnl_sol,
        realized_proceeds_sol=(
            position.realized_proceeds_sol
        ),
        partial_exit_count=position.partial_exit_count,
        last_executable_price_sol=(
            position.entry_price_sol
        ),
        last_executable_price_at=position.entry_at,
    )


def _cached_execution_state(
    jupiter_map: dict[str, dict],
    token: str,
) -> tuple[bool, str]:
    row = jupiter_map.get(token)

    if row is None:
        return False, "CACHE_MISSING"

    if row.get("compatible") is True:
        return True, str(
            row.get("status")
            or "CACHED_COMPATIBLE"
        )

    return False, str(
        row.get("status")
        or "CACHE_UNQUOTABLE"
    )


def _position_reason(
    position: LifecyclePosition,
    *,
    jupiter_map: dict[str, dict],
) -> str:
    cached_compatible, _ = (
        _cached_execution_state(
            jupiter_map,
            position.token_mint,
        )
    )

    if not cached_compatible:
        return "CACHE_UNQUOTABLE"

    if (
        position.remaining_cost_basis_sol
        <= DUST_REMAINDER_SOL
        or position.quantity <= 1e-12
    ):
        return "DUST_REMAINDER"

    if (
        position.analysis_source_sells <= 0
        and position.sell_before_analysis_count > 0
    ):
        return "SELL_BEFORE_ANALYSIS_UNMATCHED"

    if position.source_sells_total <= 0:
        return "NO_SOURCE_SELL"

    if (
        position.partial_exit_count > 0
        or position.source_sold_quantity > 0
    ):
        return "PARTIAL_SOURCE_EXIT"

    return "ANALYSIS_WINDOW_END"


def _position_detail(
    position: LifecyclePosition,
    *,
    cutoff: datetime,
    started_at: datetime,
    source_quantity_end: float,
    jupiter_map: dict[str, dict],
) -> dict[str, Any]:
    cached_compatible, cached_status = (
        _cached_execution_state(
            jupiter_map,
            position.token_mint,
        )
    )
    original_cost = max(
        0.0,
        position.original_cost_basis_sol,
    )
    remaining_fraction = (
        position.remaining_cost_basis_sol
        / original_cost
        * 100.0
        if original_cost > 0
        else 0.0
    )
    matched_fraction = max(
        0.0,
        100.0 - remaining_fraction,
    )

    age_at_start = max(
        0.0,
        (
            cutoff - position.entry_at
        ).total_seconds()
        / 3600.0,
    )
    age_at_end = max(
        0.0,
        (
            started_at - position.entry_at
        ).total_seconds()
        / 3600.0,
    )

    return {
        "token_mint": position.token_mint,
        "bootstrap": position.bootstrap,
        "entry_at": position.entry_at.isoformat(),
        "entry_signature": position.entry_signature,
        "age_at_analysis_start_hours": _round(
            age_at_start,
            4,
        ),
        "age_at_analysis_end_hours": _round(
            age_at_end,
            4,
        ),
        "source_buys_total": (
            position.source_buys_total
        ),
        "source_sells_total": (
            position.source_sells_total
        ),
        "analysis_source_buys": (
            position.analysis_source_buys
        ),
        "analysis_source_sells": (
            position.analysis_source_sells
        ),
        "source_bought_quantity": _round(
            position.source_bought_quantity
        ),
        "source_sold_quantity": _round(
            position.source_sold_quantity
        ),
        "source_quantity_end": _round(
            source_quantity_end
        ),
        "matched_sell_actions": (
            position.matched_sell_actions
        ),
        "matched_exit_fraction_percent": _round(
            matched_fraction,
            4,
        ),
        "remaining_fraction_percent": _round(
            remaining_fraction,
            4,
        ),
        "remaining_quantity": _round(
            position.quantity
        ),
        "remaining_cost_basis_sol": _round(
            position.remaining_cost_basis_sol
        ),
        "partial_exit_count": (
            position.partial_exit_count
        ),
        "sell_before_analysis_count": (
            position.sell_before_analysis_count
        ),
        "last_source_activity_at": (
            position.last_source_activity_at
            .isoformat()
            if position.last_source_activity_at
            else None
        ),
        "last_source_activity_side": (
            position.last_source_activity_side
        ),
        "last_executable_price_sol": _round(
            position.last_executable_price_sol
            or 0.0
        ),
        "last_executable_price_at": (
            position.last_executable_price_at
            .isoformat()
            if position.last_executable_price_at
            else None
        ),
        "cached_jupiter_compatible": (
            cached_compatible
        ),
        "cached_jupiter_status": cached_status,
        "reason_still_open": _position_reason(
            position,
            jupiter_map=jupiter_map,
        ),
    }


def _simulate_lifecycle(
    *,
    warmup_trades: list[Trade],
    analysis_trades: list[Trade],
    cutoff: datetime,
    started_at: datetime,
    starting_capital_sol: float,
    fixed_buy_size_sol: float,
    friction_bps: float,
    fee_bps: int,
    max_open_positions: int,
    include_bootstrap: bool,
    holding_period_hours: int | None,
    jupiter_map: dict[str, dict],
    collect_positions: bool,
    max_position_details: int,
) -> dict[str, Any]:
    friction_ratio = (
        max(0.0, friction_bps)
        / 10_000.0
    )
    fee_ratio = (
        max(0, fee_bps)
        / 10_000.0
    )

    cash = float(starting_capital_sol)
    positions: dict[
        str,
        LifecyclePosition
    ] = {}
    source_quantities: dict[str, float] = {}
    last_prices: dict[str, float] = {}
    last_price_times: dict[str, datetime] = {}
    warmup_stats: dict[str, dict[str, Any]] = {}

    counters = {
        "valid_priced_trades": 0,
        "buy_signals": 0,
        "sell_signals": 0,
        "executed_buys": 0,
        "matched_sell_actions": 0,
        "completed_positions": 0,
        "partial_sell_events": 0,
        "bootstrap_positions_closed": 0,
        "skipped_invalid": 0,
        "skipped_existing_position": 0,
        "skipped_max_positions": 0,
        "skipped_insufficient_capital": 0,
        "unmatched_sells": 0,
        "forced_closes": 0,
        "forced_close_skipped_unquotable": 0,
        "positions_freed_by_expiry": 0,
    }
    realized_pnl_total = 0.0
    closed_results: list[dict] = []
    expiry_blocked_tokens: set[str] = set()

    def stats_for(
        token: str,
    ) -> dict[str, Any]:
        return warmup_stats.setdefault(
            token,
            {
                "buys": 0,
                "sells": 0,
                "buy_quantity": 0.0,
                "sell_quantity": 0.0,
                "last_at": None,
                "last_side": None,
            },
        )

    for trade in warmup_trades:
        (
            token,
            side,
            price,
            source_token_amount,
            _source_sol_amount,
            timestamp,
            invalid_reason,
        ) = _parse_trade(
            trade,
            cutoff,
        )

        if invalid_reason is not None:
            continue

        assert price is not None
        last_prices[token] = price
        last_price_times[token] = timestamp
        stats = stats_for(token)
        stats["last_at"] = timestamp
        stats["last_side"] = side
        source_before = source_quantities.get(
            token,
            0.0,
        )

        if side == "BUY":
            stats["buys"] += 1
            stats["buy_quantity"] += (
                source_token_amount
            )
            source_quantities[token] = (
                source_before
                + source_token_amount
            )

            if not include_bootstrap:
                continue
            if token in positions:
                position = positions[token]
                position.source_buys_total += 1
                position.source_bought_quantity += (
                    source_token_amount
                )
                position.last_source_activity_at = (
                    timestamp
                )
                position.last_source_activity_side = (
                    side
                )
                position.last_executable_price_sol = (
                    price
                )
                position.last_executable_price_at = (
                    timestamp
                )
                continue
            if (
                len(positions)
                >= max_open_positions
                or cash + 1e-12
                < fixed_buy_size_sol
            ):
                continue

            opened = _open_position(
                trade=trade,
                token=token,
                timestamp=timestamp,
                price=price,
                fixed_buy_size_sol=(
                    fixed_buy_size_sol
                ),
                friction_ratio=friction_ratio,
                fee_ratio=fee_ratio,
                bootstrap=True,
            )

            if opened is not None:
                position = _as_lifecycle_position(
                    opened
                )
                position.source_buys_total = 1
                position.source_bought_quantity = (
                    source_token_amount
                )
                position.last_source_activity_at = (
                    timestamp
                )
                position.last_source_activity_side = (
                    side
                )
                positions[token] = position
                cash -= fixed_buy_size_sol
        else:
            stats["sells"] += 1
            stats["sell_quantity"] += (
                source_token_amount
            )
            source_fraction = (
                min(
                    1.0,
                    source_token_amount
                    / source_before,
                )
                if source_before > 0
                else 1.0
            )
            source_quantities[token] = max(
                0.0,
                source_before
                - source_token_amount,
            )

            if not include_bootstrap:
                continue

            position = positions.get(token)

            if position is None:
                continue

            position.source_sells_total += 1
            position.source_sold_quantity += (
                source_token_amount
            )
            position.sell_before_analysis_count += 1
            position.last_source_activity_at = (
                timestamp
            )
            position.last_source_activity_side = side
            position.last_executable_price_sol = (
                price
            )
            position.last_executable_price_at = (
                timestamp
            )

            execution_price = (
                price
                * max(
                    0.0,
                    1.0 - friction_ratio,
                )
            )
            proceeds, _, fully_closed = (
                _sell_position(
                    position=position,
                    source_fraction=source_fraction,
                    execution_price=(
                        execution_price
                    ),
                    fee_ratio=fee_ratio,
                )
            )
            cash += proceeds

            if fully_closed:
                del positions[token]

    for token, position in positions.items():
        price = last_prices.get(
            token,
            position.entry_price_sol,
        )
        marked_gross = (
            position.quantity
            * price
            * max(
                0.0,
                1.0 - friction_ratio,
            )
        )
        marked_value = (
            marked_gross
            * max(
                0.0,
                1.0 - fee_ratio,
            )
        )

        position.original_cost_basis_sol = (
            marked_value
        )
        position.remaining_cost_basis_sol = (
            marked_value
        )
        position.entry_price_sol = price
        position.entry_at = cutoff
        position.entry_signature = (
            f"BOOTSTRAP:{position.entry_signature}"
        )
        position.bootstrap = True
        position.realized_pnl_sol = 0.0
        position.realized_proceeds_sol = 0.0
        position.partial_exit_count = 0
        position.last_executable_price_sol = (
            price
        )
        position.last_executable_price_at = (
            last_price_times.get(
                token,
                cutoff,
            )
        )

        stats = warmup_stats.get(token, {})
        position.source_buys_total = int(
            stats.get("buys", 0)
        )
        position.source_sells_total = int(
            stats.get("sells", 0)
        )
        position.source_bought_quantity = (
            safe_float(
                stats.get("buy_quantity")
            )
        )
        position.source_sold_quantity = (
            safe_float(
                stats.get("sell_quantity")
            )
        )
        position.last_source_activity_at = (
            stats.get("last_at")
        )
        position.last_source_activity_side = (
            stats.get("last_side")
        )

    bootstrap_positions = len(positions)
    effective_starting_equity = (
        _mark_to_market(
            cash=cash,
            positions=positions,
            last_prices=last_prices,
            friction_ratio=friction_ratio,
            fee_ratio=fee_ratio,
        )
    )

    if effective_starting_equity <= 0:
        effective_starting_equity = float(
            starting_capital_sol
        )
        cash = float(starting_capital_sol)
        positions = {}
        bootstrap_positions = 0

    peak_equity = float(
        effective_starting_equity
    )
    max_drawdown_percent = 0.0

    def update_drawdown() -> None:
        nonlocal peak_equity
        nonlocal max_drawdown_percent

        equity = _mark_to_market(
            cash=cash,
            positions=positions,
            last_prices=last_prices,
            friction_ratio=friction_ratio,
            fee_ratio=fee_ratio,
        )
        peak_equity = max(
            peak_equity,
            equity,
        )

        if peak_equity > 0:
            drawdown = (
                peak_equity - equity
            ) / peak_equity * 100.0
            max_drawdown_percent = max(
                max_drawdown_percent,
                drawdown,
            )

    def expire_due(
        timestamp: datetime,
    ) -> None:
        nonlocal cash
        nonlocal realized_pnl_total

        if holding_period_hours is None:
            return

        due_tokens = [
            token
            for token, position
            in positions.items()
            if (
                timestamp
                - position.entry_at
            ).total_seconds()
            >= holding_period_hours * 3600
        ]

        for token in due_tokens:
            position = positions.get(token)

            if position is None:
                continue

            if token in expiry_blocked_tokens:
                continue

            cached_compatible, _ = (
                _cached_execution_state(
                    jupiter_map,
                    token,
                )
            )
            cached_price = (
                position
                .last_executable_price_sol
                or last_prices.get(token)
            )

            if (
                not cached_compatible
                or cached_price is None
                or cached_price <= 0
            ):
                counters[
                    "forced_close_skipped_unquotable"
                ] += 1
                expiry_blocked_tokens.add(token)
                continue

            execution_price = (
                cached_price
                * max(
                    0.0,
                    1.0 - friction_ratio,
                )
            )
            proceeds, pnl, _ = (
                _sell_position(
                    position=position,
                    source_fraction=1.0,
                    execution_price=(
                        execution_price
                    ),
                    fee_ratio=fee_ratio,
                )
            )
            cash += proceeds
            realized_pnl_total += pnl
            counters["forced_closes"] += 1
            counters[
                "positions_freed_by_expiry"
            ] += 1
            counters[
                "completed_positions"
            ] += 1

            if position.bootstrap:
                counters[
                    "bootstrap_positions_closed"
                ] += 1

            closed_results.append(
                {
                    "token_mint": token,
                    "entry_at": (
                        position.entry_at
                        .isoformat()
                    ),
                    "exit_at": timestamp.isoformat(),
                    "bootstrap": (
                        position.bootstrap
                    ),
                    "exit_type": "FORCED_EXPIRY",
                    "holding_period_hours": (
                        holding_period_hours
                    ),
                    "pnl_sol": _round(
                        position.realized_pnl_sol
                    ),
                }
            )
            del positions[token]
            expiry_blocked_tokens.discard(token)

        update_drawdown()

    for trade in analysis_trades:
        (
            token,
            side,
            price,
            source_token_amount,
            _source_sol_amount,
            timestamp,
            invalid_reason,
        ) = _parse_trade(
            trade,
            started_at,
        )

        expire_due(timestamp)

        if invalid_reason is not None:
            counters["skipped_invalid"] += 1
            continue

        assert price is not None
        counters["valid_priced_trades"] += 1
        last_prices[token] = price
        last_price_times[token] = timestamp
        source_before = source_quantities.get(
            token,
            0.0,
        )

        current_position = positions.get(token)

        if current_position is not None:
            current_position.last_source_activity_at = (
                timestamp
            )
            current_position.last_source_activity_side = (
                side
            )
            current_position.last_executable_price_sol = (
                price
            )
            current_position.last_executable_price_at = (
                timestamp
            )

        if side == "BUY":
            counters["buy_signals"] += 1
            source_quantities[token] = (
                source_before
                + source_token_amount
            )

            if current_position is not None:
                counters[
                    "skipped_existing_position"
                ] += 1
                current_position.source_buys_total += 1
                current_position.analysis_source_buys += 1
                current_position.source_bought_quantity += (
                    source_token_amount
                )
            elif (
                len(positions)
                >= max_open_positions
            ):
                counters[
                    "skipped_max_positions"
                ] += 1
            elif (
                cash + 1e-12
                < fixed_buy_size_sol
            ):
                counters[
                    "skipped_insufficient_capital"
                ] += 1
            else:
                opened = _open_position(
                    trade=trade,
                    token=token,
                    timestamp=timestamp,
                    price=price,
                    fixed_buy_size_sol=(
                        fixed_buy_size_sol
                    ),
                    friction_ratio=(
                        friction_ratio
                    ),
                    fee_ratio=fee_ratio,
                    bootstrap=False,
                )

                if opened is None:
                    counters[
                        "skipped_invalid"
                    ] += 1
                else:
                    position = (
                        _as_lifecycle_position(
                            opened
                        )
                    )
                    position.source_buys_total = 1
                    position.analysis_source_buys = 1
                    position.source_bought_quantity = (
                        source_token_amount
                    )
                    position.last_source_activity_at = (
                        timestamp
                    )
                    position.last_source_activity_side = (
                        side
                    )
                    positions[token] = position
                    expiry_blocked_tokens.discard(token)
                    cash -= fixed_buy_size_sol
                    counters[
                        "executed_buys"
                    ] += 1
        else:
            counters["sell_signals"] += 1
            source_fraction = (
                min(
                    1.0,
                    source_token_amount
                    / source_before,
                )
                if source_before > 0
                else 1.0
            )
            source_quantities[token] = max(
                0.0,
                source_before
                - source_token_amount,
            )
            position = positions.get(token)

            if position is None:
                counters[
                    "unmatched_sells"
                ] += 1
            else:
                position.source_sells_total += 1
                position.analysis_source_sells += 1
                position.source_sold_quantity += (
                    source_token_amount
                )
                position.matched_sell_actions += 1
                counters[
                    "matched_sell_actions"
                ] += 1

                if source_fraction < 0.999999:
                    counters[
                        "partial_sell_events"
                    ] += 1

                execution_price = (
                    price
                    * max(
                        0.0,
                        1.0 - friction_ratio,
                    )
                )
                proceeds, pnl, fully_closed = (
                    _sell_position(
                        position=position,
                        source_fraction=(
                            source_fraction
                        ),
                        execution_price=(
                            execution_price
                        ),
                        fee_ratio=fee_ratio,
                    )
                )
                cash += proceeds
                realized_pnl_total += pnl

                if fully_closed:
                    counters[
                        "completed_positions"
                    ] += 1

                    if position.bootstrap:
                        counters[
                            "bootstrap_positions_closed"
                        ] += 1

                    closed_results.append(
                        {
                            "token_mint": token,
                            "entry_at": (
                                position.entry_at
                                .isoformat()
                            ),
                            "exit_at": (
                                timestamp.isoformat()
                            ),
                            "bootstrap": (
                                position.bootstrap
                            ),
                            "exit_type": (
                                "SOURCE_SELL"
                            ),
                            "pnl_sol": _round(
                                position
                                .realized_pnl_sol
                            ),
                        }
                    )
                    del positions[token]

        update_drawdown()

    expire_due(started_at)

    ending_equity = _mark_to_market(
        cash=cash,
        positions=positions,
        last_prices=last_prices,
        friction_ratio=friction_ratio,
        fee_ratio=fee_ratio,
    )
    open_cost = sum(
        position.remaining_cost_basis_sol
        for position in positions.values()
    )
    open_value = max(
        0.0,
        ending_equity - cash,
    )
    unrealized_pnl = (
        open_value - open_cost
    )
    net_pnl = (
        ending_equity
        - effective_starting_equity
    )
    total_return = (
        net_pnl
        / effective_starting_equity
        * 100.0
        if effective_starting_equity > 0
        else 0.0
    )

    completed_pnls = [
        safe_float(row.get("pnl_sol"))
        for row in closed_results
    ]
    gross_profit = sum(
        max(0.0, pnl)
        for pnl in completed_pnls
    )
    positive_pnls = sorted(
        (
            pnl
            for pnl in completed_pnls
            if pnl > 0
        ),
        reverse=True,
    )
    best_trade_pnl = (
        positive_pnls[0]
        if positive_pnls
        else 0.0
    )
    top_1_share = (
        best_trade_pnl
        / gross_profit
        * 100.0
        if gross_profit > 0
        else 0.0
    )
    return_without_best = (
        (
            net_pnl - best_trade_pnl
        )
        / effective_starting_equity
        * 100.0
        if effective_starting_equity > 0
        else 0.0
    )

    actionable = (
        counters["buy_signals"]
        + counters["sell_signals"]
    )
    executed_actions = (
        counters["executed_buys"]
        + counters["matched_sell_actions"]
    )
    coverage = (
        executed_actions
        / actionable
        * 100.0
        if actionable
        else 0.0
    )
    matched_sell_ratio = (
        counters["matched_sell_actions"]
        / counters["sell_signals"]
        * 100.0
        if counters["sell_signals"]
        else 0.0
    )
    opened_total = (
        counters["executed_buys"]
        + bootstrap_positions
    )
    open_position_ratio = (
        len(positions)
        / opened_total
        * 100.0
        if opened_total
        else 0.0
    )

    position_details = []

    if collect_positions:
        for token, position in sorted(
            positions.items(),
            key=lambda item: (
                item[1].entry_at,
                item[0],
            ),
        )[:max_position_details]:
            position_details.append(
                _position_detail(
                    position,
                    cutoff=cutoff,
                    started_at=started_at,
                    source_quantity_end=(
                        source_quantities.get(
                            token,
                            0.0,
                        )
                    ),
                    jupiter_map=jupiter_map,
                )
            )

    return {
        **counters,
        "holding_period_hours": (
            holding_period_hours
        ),
        "include_bootstrap": include_bootstrap,
        "starting_capital_sol": _round(
            starting_capital_sol
        ),
        "max_open_positions": (
            max_open_positions
        ),
        "bootstrap_positions": (
            bootstrap_positions
        ),
        "open_positions": len(positions),
        "effective_starting_equity_sol": _round(
            effective_starting_equity
        ),
        "ending_equity_sol": _round(
            ending_equity
        ),
        "realized_pnl_sol": _round(
            realized_pnl_total
        ),
        "unrealized_pnl_sol": _round(
            unrealized_pnl
        ),
        "net_pnl_sol": _round(net_pnl),
        "total_return_percent": _round(
            total_return,
            4,
        ),
        "return_without_best_trade_percent": (
            _round(
                return_without_best,
                4,
            )
        ),
        "top_1_profit_concentration_percent": (
            _round(top_1_share, 4)
        ),
        "max_drawdown_percent": _round(
            max_drawdown_percent,
            4,
        ),
        "execution_coverage_percent": _round(
            coverage,
            4,
        ),
        "matched_sell_ratio_percent": _round(
            matched_sell_ratio,
            4,
        ),
        "open_position_ratio_percent": _round(
            open_position_ratio,
            4,
        ),
        "position_details": position_details,
    }


def _lifecycle_summary(
    position_details: list[dict],
) -> dict[str, int]:
    summary: dict[str, int] = {}

    for row in position_details:
        reason = str(
            row.get("reason_still_open")
            or "ANALYSIS_WINDOW_END"
        )
        summary[reason] = (
            summary.get(reason, 0) + 1
        )

    return dict(
        sorted(
            summary.items(),
            key=lambda item: (
                -item[1],
                item[0],
            ),
        )
    )


def _diagnose(
    *,
    baseline: dict[str, Any],
    lifecycle_summary: dict[str, int],
    scenarios: list[dict],
) -> list[str]:
    diagnoses: list[str] = []

    if lifecycle_summary.get(
        "NO_SOURCE_SELL",
        0,
    ) > 0:
        diagnoses.append(
            "OPEN_POSITIONS_WITHOUT_SOURCE_SELL"
        )

    if lifecycle_summary.get(
        "PARTIAL_SOURCE_EXIT",
        0,
    ) > 0:
        diagnoses.append(
            "PARTIAL_SOURCE_EXITS_LEAVE_RESIDUALS"
        )

    if lifecycle_summary.get(
        "CACHE_UNQUOTABLE",
        0,
    ) > 0:
        diagnoses.append(
            "CACHED_UNQUOTABLE_BLOCKS_FORCED_CLOSE"
        )

    baseline_skipped = int(
        baseline.get(
            "skipped_max_positions",
            0,
        )
    )
    baseline_buys = int(
        baseline.get("executed_buys", 0)
    )
    baseline_open = int(
        baseline.get("open_positions", 0)
    )
    baseline_return = safe_float(
        baseline.get("total_return_percent")
    )

    expiry_rows = [
        row["with_bootstrap"]
        for row in scenarios
        if row.get("holding_period_hours")
        is not None
    ]

    if any(
        int(
            row.get(
                "skipped_max_positions",
                0,
            )
        )
        < baseline_skipped
        or int(
            row.get("executed_buys", 0)
        )
        > baseline_buys
        for row in expiry_rows
    ):
        diagnoses.append(
            "STALE_POSITIONS_BLOCKING_CAPACITY"
        )

    if any(
        abs(
            safe_float(
                row.get(
                    "total_return_percent"
                )
            )
            - baseline_return
        )
        >= 10.0
        for row in expiry_rows
    ):
        diagnoses.append(
            "RETURN_SENSITIVE_TO_HOLDING_PERIOD"
        )

    no_bootstrap = (
        scenarios[0].get(
            "without_bootstrap",
            {},
        )
        if scenarios
        else {}
    )

    if (
        baseline_open
        > int(
            no_bootstrap.get(
                "open_positions",
                0,
            )
        )
        or int(
            baseline.get(
                "skipped_max_positions",
                0,
            )
        )
        > int(
            no_bootstrap.get(
                "skipped_max_positions",
                0,
            )
        )
    ):
        diagnoses.append(
            "BOOTSTRAP_POSITIONS_BIND_CAPACITY"
        )

    if not diagnoses:
        diagnoses.append(
            "NO_STALE_POSITION_PATTERN"
        )

    return diagnoses


def run_candidate_position_lifecycle_audit(
    db: Session,
    *,
    wallet_address: str,
    lookback_days: int = 14,
    warmup_days: int = 14,
    starting_capital_sol: float = 1.0,
    fixed_buy_size_sol: float = 0.05,
    slippage_bps: int = 100,
    fee_bps: int = 10,
    copy_delay_seconds: int = 8,
    delay_penalty_bps_per_minute: float = 25.0,
    max_open_positions: int = 5,
    max_position_details: int = 200,
    now: datetime | None = None,
) -> CandidatePositionLifecycleAuditRun:
    started_at = (
        ensure_aware(now)
        or utc_now()
    )

    wallet = (
        db.query(DiscoveredWallet)
        .filter(
            DiscoveredWallet.wallet_address
            == wallet_address
        )
        .first()
    )

    if wallet is None:
        raise ValueError(
            "Wallet scoperto non trovato"
        )

    effective_lookback = max(
        1,
        min(int(lookback_days), 90),
    )
    effective_warmup = max(
        0,
        min(int(warmup_days), 60),
    )
    effective_capital = max(
        0.001,
        min(
            float(starting_capital_sol),
            1000.0,
        ),
    )
    effective_max_positions = max(
        1,
        min(int(max_open_positions), 50),
    )
    effective_max_details = max(
        1,
        min(int(max_position_details), 1000),
    )

    cutoff = (
        started_at
        - timedelta(
            days=effective_lookback
        )
    )
    warmup_cutoff = (
        cutoff
        - timedelta(
            days=effective_warmup
        )
    )

    trades = (
        db.query(Trade)
        .filter(
            Trade.wallet_address
            == wallet_address
        )
        .filter(Trade.success.is_(True))
        .filter(Trade.block_time.isnot(None))
        .filter(
            Trade.block_time
            >= warmup_cutoff
        )
        .filter(
            Trade.block_time
            <= started_at
        )
        .order_by(
            Trade.block_time.asc(),
            Trade.id.asc(),
        )
        .all()
    )

    warmup_trades = [
        trade
        for trade in trades
        if (
            ensure_aware(trade.block_time)
            or started_at
        )
        < cutoff
    ]
    analysis_trades = [
        trade
        for trade in trades
        if (
            ensure_aware(trade.block_time)
            or started_at
        )
        >= cutoff
    ]

    friction_bps = (
        _market_friction_bps(
            slippage_bps=slippage_bps,
            copy_delay_seconds=(
                copy_delay_seconds
            ),
            delay_penalty_bps_per_minute=(
                delay_penalty_bps_per_minute
            ),
        )
    )
    jupiter_map = _latest_jupiter_map(
        db,
        wallet_address,
    )

    scenarios: list[dict] = []

    for holding_hours in (
        HOLDING_PERIOD_SCENARIOS
    ):
        with_bootstrap = (
            _simulate_lifecycle(
                warmup_trades=warmup_trades,
                analysis_trades=analysis_trades,
                cutoff=cutoff,
                started_at=started_at,
                starting_capital_sol=(
                    effective_capital
                ),
                fixed_buy_size_sol=(
                    fixed_buy_size_sol
                ),
                friction_bps=friction_bps,
                fee_bps=fee_bps,
                max_open_positions=(
                    effective_max_positions
                ),
                include_bootstrap=True,
                holding_period_hours=(
                    holding_hours
                ),
                jupiter_map=jupiter_map,
                collect_positions=(
                    holding_hours is None
                ),
                max_position_details=(
                    effective_max_details
                ),
            )
        )
        without_bootstrap = (
            _simulate_lifecycle(
                warmup_trades=warmup_trades,
                analysis_trades=analysis_trades,
                cutoff=cutoff,
                started_at=started_at,
                starting_capital_sol=(
                    effective_capital
                ),
                fixed_buy_size_sol=(
                    fixed_buy_size_sol
                ),
                friction_bps=friction_bps,
                fee_bps=fee_bps,
                max_open_positions=(
                    effective_max_positions
                ),
                include_bootstrap=False,
                holding_period_hours=(
                    holding_hours
                ),
                jupiter_map=jupiter_map,
                collect_positions=False,
                max_position_details=0,
            )
        )

        scenarios.append(
            {
                "scenario_key": (
                    "no_expiry"
                    if holding_hours is None
                    else (
                        f"max_holding_"
                        f"{holding_hours}h"
                    )
                ),
                "holding_period_hours": (
                    holding_hours
                ),
                "with_bootstrap": (
                    with_bootstrap
                ),
                "without_bootstrap": (
                    without_bootstrap
                ),
                "bootstrap_delta": {
                    "return_percent": _round(
                        safe_float(
                            with_bootstrap.get(
                                "total_return_percent"
                            )
                        )
                        - safe_float(
                            without_bootstrap.get(
                                "total_return_percent"
                            )
                        ),
                        4,
                    ),
                    "open_positions": (
                        int(
                            with_bootstrap.get(
                                "open_positions",
                                0,
                            )
                        )
                        - int(
                            without_bootstrap.get(
                                "open_positions",
                                0,
                            )
                        )
                    ),
                    "skipped_max_positions": (
                        int(
                            with_bootstrap.get(
                                "skipped_max_positions",
                                0,
                            )
                        )
                        - int(
                            without_bootstrap.get(
                                "skipped_max_positions",
                                0,
                            )
                        )
                    ),
                },
            }
        )

    baseline = scenarios[0][
        "with_bootstrap"
    ]
    baseline["source_trades"] = len(trades)
    baseline["warmup_source_trades"] = len(
        warmup_trades
    )
    baseline["analysis_source_trades"] = len(
        analysis_trades
    )

    position_details = list(
        baseline.pop(
            "position_details",
            [],
        )
    )
    lifecycle_summary = (
        _lifecycle_summary(
            position_details
        )
    )
    diagnoses = _diagnose(
        baseline=baseline,
        lifecycle_summary=lifecycle_summary,
        scenarios=scenarios,
    )

    parameters = {
        "lookback_days": (
            effective_lookback
        ),
        "warmup_days": (
            effective_warmup
        ),
        "starting_capital_sol": (
            effective_capital
        ),
        "fixed_buy_size_sol": (
            fixed_buy_size_sol
        ),
        "slippage_bps": slippage_bps,
        "fee_bps": fee_bps,
        "copy_delay_seconds": (
            copy_delay_seconds
        ),
        "delay_penalty_bps_per_minute": (
            delay_penalty_bps_per_minute
        ),
        "effective_market_friction_bps": (
            _round(friction_bps, 4)
        ),
        "max_open_positions": (
            effective_max_positions
        ),
        "holding_period_scenarios_hours": [
            value
            for value
            in HOLDING_PERIOD_SCENARIOS
        ],
        "forced_close_price_policy": (
            "CACHED_JUPITER_COMPATIBLE_"
            "PLUS_LAST_EXECUTABLE_LOCAL_PRICE"
        ),
        "max_position_details": (
            effective_max_details
        ),
    }
    safety = {
        "diagnostic_only": True,
        "cached_data_only": True,
        "promotion_gate_changed": False,
        "wallet_eligibility_changed": False,
        "helius_requests": 0,
        "jupiter_requests": 0,
        "transactions_signed": False,
        "transactions_submitted": False,
        "live_enabled": False,
        "stream_changed": False,
        "worker_started": False,
        "wallets_applied": False,
        "generation_reset": False,
        "generation_created": False,
    }
    completed_at = utc_now()

    run = CandidatePositionLifecycleAuditRun(
        run_id=str(uuid4()),
        wallet_address=wallet_address,
        status="COMPLETED",
        parameters=parameters,
        safety=safety,
        baseline_metrics=baseline,
        lifecycle_summary=(
            lifecycle_summary
        ),
        position_details=position_details,
        scenario_results=scenarios,
        diagnoses=diagnoses,
        started_at=started_at,
        completed_at=completed_at,
    )

    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_latest_candidate_position_lifecycle_audit(
    db: Session,
    wallet_address: str,
) -> (
    CandidatePositionLifecycleAuditRun
    | None
):
    return (
        db.query(
            CandidatePositionLifecycleAuditRun
        )
        .filter(
            CandidatePositionLifecycleAuditRun
            .wallet_address
            == wallet_address
        )
        .order_by(
            CandidatePositionLifecycleAuditRun
            .completed_at.desc(),
            CandidatePositionLifecycleAuditRun
            .id.desc(),
        )
        .first()
    )
