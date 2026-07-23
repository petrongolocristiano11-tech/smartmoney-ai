from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from backend.app.core.constants import SOL_MINT
from backend.app.models.candidate_backtest import (
    CandidateBacktestRun,
)
from backend.app.models.candidate_reconstruction_audit import (
    CandidateReconstructionAuditRun,
)
from backend.app.models.discovered_wallet import (
    DiscoveredWallet,
)
from backend.app.models.trade import Trade
from backend.app.services.wallet_activity_service import (
    ensure_aware,
    safe_float,
)


CAPITAL_SCENARIOS = (1.0, 2.0, 5.0)
POSITION_SCENARIOS = (5, 10, 20)
DUST_SOL_THRESHOLD = 0.001


@dataclass
class AuditPosition:
    token_mint: str
    quantity: float
    original_cost_basis_sol: float
    remaining_cost_basis_sol: float
    entry_price_sol: float
    entry_at: datetime
    entry_signature: str
    bootstrap: bool = False
    realized_pnl_sol: float = 0.0
    realized_proceeds_sol: float = 0.0
    partial_exit_count: int = 0


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _round(
    value: float,
    digits: int = 8,
) -> float:
    return round(float(value or 0.0), digits)


def _source_price(
    trade: Trade,
) -> float | None:
    sol_amount = abs(safe_float(trade.sol_amount))
    token_amount = abs(safe_float(trade.token_amount))

    if sol_amount <= 0 or token_amount <= 0:
        return None

    return sol_amount / token_amount


def _market_friction_bps(
    *,
    slippage_bps: int,
    copy_delay_seconds: int,
    delay_penalty_bps_per_minute: float,
) -> float:
    delay_penalty = (
        max(0, copy_delay_seconds)
        / 60.0
        * max(
            0.0,
            delay_penalty_bps_per_minute,
        )
    )

    return min(
        2000.0,
        max(0.0, float(slippage_bps))
        + delay_penalty,
    )


def _mark_to_market(
    *,
    cash: float,
    positions: dict[str, AuditPosition],
    last_prices: dict[str, float],
    friction_ratio: float,
    fee_ratio: float,
) -> float:
    equity = cash

    for token, position in positions.items():
        price = last_prices.get(
            token,
            position.entry_price_sol,
        )
        gross = (
            position.quantity
            * price
            * max(0.0, 1.0 - friction_ratio)
        )
        equity += gross * max(
            0.0,
            1.0 - fee_ratio,
        )

    return max(0.0, equity)


def _open_position(
    *,
    trade: Trade,
    token: str,
    timestamp: datetime,
    price: float,
    fixed_buy_size_sol: float,
    friction_ratio: float,
    fee_ratio: float,
    bootstrap: bool,
) -> AuditPosition | None:
    entry_fee = fixed_buy_size_sol * fee_ratio
    net_input = max(
        0.0,
        fixed_buy_size_sol - entry_fee,
    )
    execution_price = (
        price * (1.0 + friction_ratio)
    )
    quantity = (
        net_input / execution_price
        if execution_price > 0
        else 0.0
    )

    if quantity <= 0:
        return None

    return AuditPosition(
        token_mint=token,
        quantity=quantity,
        original_cost_basis_sol=fixed_buy_size_sol,
        remaining_cost_basis_sol=fixed_buy_size_sol,
        entry_price_sol=execution_price,
        entry_at=timestamp,
        entry_signature=str(trade.signature),
        bootstrap=bootstrap,
    )


def _sell_position(
    *,
    position: AuditPosition,
    source_fraction: float,
    execution_price: float,
    fee_ratio: float,
) -> tuple[float, float, bool]:
    fraction = max(
        0.0,
        min(1.0, source_fraction),
    )

    if fraction <= 0:
        return 0.0, 0.0, False

    sold_quantity = position.quantity * fraction
    released_cost = (
        position.remaining_cost_basis_sol
        * fraction
    )
    gross_proceeds = sold_quantity * execution_price
    proceeds = max(
        0.0,
        gross_proceeds
        - gross_proceeds * fee_ratio,
    )
    pnl = proceeds - released_cost

    position.quantity = max(
        0.0,
        position.quantity - sold_quantity,
    )
    position.remaining_cost_basis_sol = max(
        0.0,
        position.remaining_cost_basis_sol
        - released_cost,
    )
    position.realized_pnl_sol += pnl
    position.realized_proceeds_sol += proceeds

    fully_closed = (
        fraction >= 0.999999
        or position.quantity <= 1e-18
        or position.remaining_cost_basis_sol <= 1e-12
    )

    if fully_closed:
        position.quantity = 0.0
        position.remaining_cost_basis_sol = 0.0
    else:
        position.partial_exit_count += 1

    return proceeds, pnl, fully_closed


def _parse_trade(
    trade: Trade,
    fallback_time: datetime,
) -> tuple[
    str,
    str,
    float | None,
    float,
    float,
    datetime,
    str | None,
]:
    token = str(
        trade.token_mint or ""
    ).strip()
    side = str(
        trade.side or "UNKNOWN"
    ).strip().upper()
    price = _source_price(trade)
    source_token_amount = abs(
        safe_float(trade.token_amount)
    )
    source_sol_amount = abs(
        safe_float(trade.sol_amount)
    )
    timestamp = (
        ensure_aware(trade.block_time)
        or fallback_time
    )

    reason = None

    if not token:
        reason = "MISSING_TOKEN_MINT"
    elif token == SOL_MINT:
        reason = "SOL_MINT_NOT_COPY_TARGET"
    elif side not in {"BUY", "SELL"}:
        reason = "UNSUPPORTED_SIDE"
    elif price is None:
        reason = "INVALID_SOURCE_PRICE"
    elif source_token_amount <= 0:
        reason = "INVALID_SOURCE_TOKEN_AMOUNT"

    return (
        token,
        side,
        price,
        source_token_amount,
        source_sol_amount,
        timestamp,
        reason,
    )


def _latest_jupiter_map(
    db: Session,
    wallet_address: str,
) -> dict[str, dict]:
    latest = (
        db.query(CandidateBacktestRun)
        .filter(
            CandidateBacktestRun.wallet_address
            == wallet_address
        )
        .order_by(
            CandidateBacktestRun.completed_at.desc(),
            CandidateBacktestRun.id.desc(),
        )
        .first()
    )

    if latest is None:
        return {}

    result: dict[str, dict] = {}

    for row in list(
        latest.jupiter_results or []
    ):
        token = str(
            row.get("token_mint")
            or row.get("token")
            or ""
        ).strip()

        if token:
            result[token] = dict(row)

    return result


def _simulate(
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
    jupiter_map: dict[str, dict],
    collect_details: bool,
    max_excluded_trades: int,
) -> dict[str, Any]:
    friction_ratio = friction_bps / 10_000.0
    fee_ratio = max(0, fee_bps) / 10_000.0

    cash = float(starting_capital_sol)
    positions: dict[str, AuditPosition] = {}
    source_quantities: dict[str, float] = {}
    last_prices: dict[str, float] = {}

    summary: dict[str, int] = {}
    details: list[dict] = []

    def record(
        reason: str,
        trade: Trade | None,
        *,
        outcome: str = "EXCLUDED",
        token: str = "",
        side: str = "",
        timestamp: datetime | None = None,
        extra: dict | None = None,
    ) -> None:
        summary[reason] = (
            summary.get(reason, 0) + 1
        )

        if (
            not collect_details
            or len(details) >= max_excluded_trades
        ):
            return

        payload = {
            "reason": reason,
            "outcome": outcome,
            "signature": (
                str(trade.signature)
                if trade is not None
                else None
            ),
            "token_mint": token,
            "side": side,
            "timestamp": (
                timestamp.isoformat()
                if timestamp is not None
                else None
            ),
            "source_sol_amount": (
                _round(
                    abs(
                        safe_float(
                            trade.sol_amount
                        )
                    )
                )
                if trade is not None
                else 0.0
            ),
            "source_token_amount": (
                _round(
                    abs(
                        safe_float(
                            trade.token_amount
                        )
                    )
                )
                if trade is not None
                else 0.0
            ),
        }

        if extra:
            payload.update(extra)

        details.append(payload)

    # Ricostruisce sempre le quantit? sorgente del warmup.
    # Le posizioni copiate vengono create solo quando
    # include_bootstrap ? True.
    for trade in warmup_trades:
        (
            token,
            side,
            price,
            source_token_amount,
            source_sol_amount,
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
        source_before = source_quantities.get(
            token,
            0.0,
        )

        if side == "BUY":
            source_quantities[token] = (
                source_before
                + source_token_amount
            )

            if not include_bootstrap:
                continue

            if token in positions:
                continue

            if (
                len(positions)
                >= max_open_positions
            ):
                continue

            if (
                cash + 1e-12
                < fixed_buy_size_sol
            ):
                continue

            position = _open_position(
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

            if position is not None:
                positions[token] = position
                cash -= fixed_buy_size_sol

        else:
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

    # Rebase delle posizioni trasportate all'inizio
    # della finestra di analisi.
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
            f"BOOTSTRAP:"
            f"{position.entry_signature}"
        )
        position.realized_pnl_sol = 0.0
        position.realized_proceeds_sol = 0.0
        position.partial_exit_count = 0

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
        "dust_source_trades": 0,
        "cached_unquotable_signals": 0,
    }

    closed_results: list[dict] = []
    closed_tokens: set[str] = set()
    skipped_buy_reason: dict[str, str] = {}
    realized_pnl_total = 0.0

    peak_equity = float(
        effective_starting_equity
    )
    max_drawdown_percent = 0.0

    for trade in analysis_trades:
        (
            token,
            side,
            price,
            source_token_amount,
            source_sol_amount,
            timestamp,
            invalid_reason,
        ) = _parse_trade(
            trade,
            started_at,
        )

        if invalid_reason is not None:
            counters["skipped_invalid"] += 1
            record(
                invalid_reason,
                trade,
                token=token,
                side=side,
                timestamp=timestamp,
            )
            continue

        assert price is not None
        counters["valid_priced_trades"] += 1
        last_prices[token] = price

        if (
            source_sol_amount
            < DUST_SOL_THRESHOLD
        ):
            counters[
                "dust_source_trades"
            ] += 1
            record(
                "DUST_SOURCE_TRADE",
                trade,
                outcome="WARNING",
                token=token,
                side=side,
                timestamp=timestamp,
            )

        jupiter_row = jupiter_map.get(token)

        if (
            jupiter_row is not None
            and jupiter_row.get("compatible")
            is False
        ):
            counters[
                "cached_unquotable_signals"
            ] += 1
            record(
                "CACHED_JUPITER_UNQUOTABLE",
                trade,
                outcome="WARNING",
                token=token,
                side=side,
                timestamp=timestamp,
                extra={
                    "jupiter_status": (
                        jupiter_row.get("status")
                    ),
                },
            )

        source_before = (
            source_quantities.get(
                token,
                0.0,
            )
        )

        if side == "BUY":
            counters["buy_signals"] += 1
            source_quantities[token] = (
                source_before
                + source_token_amount
            )

            if token in positions:
                counters[
                    "skipped_existing_position"
                ] += 1
                skipped_buy_reason[token] = (
                    "BUY_SCALE_IN_SKIPPED"
                )
                record(
                    "BUY_SCALE_IN_SKIPPED",
                    trade,
                    token=token,
                    side=side,
                    timestamp=timestamp,
                    extra={
                        "open_positions": len(
                            positions
                        ),
                        "cash_sol": _round(cash),
                    },
                )

            elif (
                len(positions)
                >= max_open_positions
            ):
                counters[
                    "skipped_max_positions"
                ] += 1
                skipped_buy_reason[token] = (
                    "MAX_OPEN_POSITIONS_REACHED"
                )
                record(
                    "MAX_OPEN_POSITIONS_REACHED",
                    trade,
                    token=token,
                    side=side,
                    timestamp=timestamp,
                    extra={
                        "open_positions": len(
                            positions
                        ),
                        "max_open_positions": (
                            max_open_positions
                        ),
                        "cash_sol": _round(cash),
                    },
                )

            elif (
                cash + 1e-12
                < fixed_buy_size_sol
            ):
                counters[
                    "skipped_insufficient_capital"
                ] += 1
                skipped_buy_reason[token] = (
                    "INSUFFICIENT_CAPITAL"
                )
                record(
                    "INSUFFICIENT_CAPITAL",
                    trade,
                    token=token,
                    side=side,
                    timestamp=timestamp,
                    extra={
                        "cash_sol": _round(cash),
                        "required_sol": _round(
                            fixed_buy_size_sol
                        ),
                    },
                )

            else:
                position = _open_position(
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

                if position is None:
                    counters[
                        "skipped_invalid"
                    ] += 1
                    record(
                        "COPY_QUANTITY_ZERO",
                        trade,
                        token=token,
                        side=side,
                        timestamp=timestamp,
                    )
                else:
                    positions[token] = position
                    cash -= fixed_buy_size_sol
                    counters[
                        "executed_buys"
                    ] += 1
                    skipped_buy_reason.pop(
                        token,
                        None,
                    )

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

                if token in skipped_buy_reason:
                    reason = (
                        "SELL_FOR_SKIPPED_BUY"
                    )
                elif token in closed_tokens:
                    reason = (
                        "SELL_AFTER_POSITION_CLOSED"
                    )
                else:
                    reason = (
                        "UNMATCHED_SELL_NO_POSITION"
                    )

                record(
                    reason,
                    trade,
                    token=token,
                    side=side,
                    timestamp=timestamp,
                    extra={
                        "source_quantity_before": (
                            _round(source_before)
                        ),
                        "latest_buy_skip_reason": (
                            skipped_buy_reason.get(
                                token
                            )
                        ),
                    },
                )

            else:
                counters[
                    "matched_sell_actions"
                ] += 1

                if source_before <= 0:
                    record(
                        "SELL_SOURCE_POSITION_UNKNOWN",
                        trade,
                        outcome="WARNING",
                        token=token,
                        side=side,
                        timestamp=timestamp,
                    )

                if source_fraction < 0.999999:
                    counters[
                        "partial_sell_events"
                    ] += 1
                    record(
                        "PARTIAL_SOURCE_SELL",
                        trade,
                        outcome="PARTIAL_EXIT",
                        token=token,
                        side=side,
                        timestamp=timestamp,
                        extra={
                            "source_sell_fraction": (
                                _round(
                                    source_fraction
                                    * 100.0,
                                    4,
                                )
                            ),
                            "source_quantity_before": (
                                _round(
                                    source_before
                                )
                            ),
                        },
                    )

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
                            "entry_signature": (
                                position.entry_signature
                            ),
                            "exit_signature": str(
                                trade.signature
                            ),
                            "bootstrap": (
                                position.bootstrap
                            ),
                            "partial_exit_count": (
                                position
                                .partial_exit_count
                            ),
                            "cost_basis_sol": _round(
                                position
                                .original_cost_basis_sol
                            ),
                            "proceeds_sol": _round(
                                position
                                .realized_proceeds_sol
                            ),
                            "pnl_sol": _round(
                                position
                                .realized_pnl_sol
                            ),
                            "return_percent": _round(
                                (
                                    position
                                    .realized_pnl_sol
                                    / position
                                    .original_cost_basis_sol
                                    * 100.0
                                )
                                if position
                                .original_cost_basis_sol
                                > 0
                                else 0.0,
                                4,
                            ),
                        }
                    )

                    del positions[token]
                    closed_tokens.add(token)
                    skipped_buy_reason.pop(
                        token,
                        None,
                    )

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

    for token, position in positions.items():
        record(
            "OPEN_POSITION_AT_END",
            None,
            outcome="OPEN",
            token=token,
            side="BUY",
            timestamp=position.entry_at,
            extra={
                "entry_signature": (
                    position.entry_signature
                ),
                "remaining_cost_basis_sol": (
                    _round(
                        position
                        .remaining_cost_basis_sol
                    )
                ),
                "bootstrap": position.bootstrap,
            },
        )

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
    unrealized_pnl = open_value - open_cost
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
        safe_float(row["pnl_sol"])
        for row in closed_results
    ]
    gross_profit = sum(
        max(0.0, pnl)
        for pnl in completed_pnls
    )
    gross_loss = sum(
        min(0.0, pnl)
        for pnl in completed_pnls
    )
    winning = sum(
        pnl > 1e-12
        for pnl in completed_pnls
    )
    losing = sum(
        pnl < -1e-12
        for pnl in completed_pnls
    )
    breakeven = (
        len(completed_pnls)
        - winning
        - losing
    )
    win_rate = (
        winning
        / len(completed_pnls)
        * 100.0
        if completed_pnls
        else 0.0
    )
    profit_factor = (
        gross_profit / abs(gross_loss)
        if gross_loss < 0
        else (
            999.0
            if gross_profit > 0
            else None
        )
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
    top_3_pnl = sum(
        positive_pnls[:3]
    )

    top_1_share = (
        best_trade_pnl
        / gross_profit
        * 100.0
        if gross_profit > 0
        else 0.0
    )
    top_3_share = (
        top_3_pnl
        / gross_profit
        * 100.0
        if gross_profit > 0
        else 0.0
    )
    return_without_best = (
        (
            net_pnl
            - best_trade_pnl
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
    raw_coverage = (
        executed_actions
        / actionable
        * 100.0
        if actionable
        else 0.0
    )

    resource_opportunities = (
        executed_actions
        + counters[
            "skipped_max_positions"
        ]
        + counters[
            "skipped_insufficient_capital"
        ]
    )
    resource_coverage = (
        executed_actions
        / resource_opportunities
        * 100.0
        if resource_opportunities
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

    return {
        **counters,
        "starting_capital_sol": _round(
            starting_capital_sol
        ),
        "max_open_positions": (
            max_open_positions
        ),
        "include_bootstrap": (
            include_bootstrap
        ),
        "bootstrap_positions": (
            bootstrap_positions
        ),
        "open_positions": len(positions),
        "winning_positions": winning,
        "losing_positions": losing,
        "breakeven_positions": breakeven,
        "effective_starting_equity_sol": (
            _round(
                effective_starting_equity
            )
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
        "best_trade_pnl_sol": _round(
            best_trade_pnl
        ),
        "top_1_profit_concentration_percent": (
            _round(top_1_share, 4)
        ),
        "top_3_profit_concentration_percent": (
            _round(top_3_share, 4)
        ),
        "win_rate_percent": _round(
            win_rate,
            4,
        ),
        "profit_factor": (
            _round(
                profit_factor,
                4,
            )
            if profit_factor is not None
            else None
        ),
        "max_drawdown_percent": _round(
            max_drawdown_percent,
            4,
        ),
        "raw_execution_coverage_percent": (
            _round(raw_coverage, 4)
        ),
        "resource_constrained_coverage_percent": (
            _round(resource_coverage, 4)
        ),
        "matched_sell_ratio_percent": (
            _round(
                matched_sell_ratio,
                4,
            )
        ),
        "open_position_ratio_percent": (
            _round(
                open_position_ratio,
                4,
            )
        ),
        "exclusion_summary": dict(
            sorted(
                summary.items(),
                key=lambda item: (
                    -item[1],
                    item[0],
                ),
            )
        ),
        "excluded_trades": details,
        "position_results": closed_results,
    }


def _diagnose(
    baseline: dict[str, Any],
    scenarios: list[dict],
) -> list[str]:
    diagnoses: list[str] = []

    base_capital = safe_float(
        baseline["starting_capital_sol"]
    )
    base_positions = int(
        baseline["max_open_positions"]
    )
    base_coverage = safe_float(
        baseline[
            "resource_constrained_coverage_percent"
        ]
    )

    same_capital = [
        scenario["with_bootstrap"]
        for scenario in scenarios
        if safe_float(
            scenario["starting_capital_sol"]
        )
        == base_capital
    ]
    same_positions = [
        scenario["with_bootstrap"]
        for scenario in scenarios
        if int(
            scenario["max_open_positions"]
        )
        == base_positions
    ]

    if same_capital:
        best_position_coverage = max(
            safe_float(
                row[
                    "resource_constrained_coverage_percent"
                ]
            )
            for row in same_capital
        )
        if (
            best_position_coverage
            - base_coverage
            >= 5.0
        ):
            diagnoses.append(
                "POSITION_LIMIT_BINDING"
            )

    if same_positions:
        best_capital_coverage = max(
            safe_float(
                row[
                    "resource_constrained_coverage_percent"
                ]
            )
            for row in same_positions
        )
        if (
            best_capital_coverage
            - base_coverage
            >= 5.0
        ):
            diagnoses.append(
                "CAPITAL_LIMIT_BINDING"
            )

    if int(
        baseline["partial_sell_events"]
    ) > 0:
        diagnoses.append(
            "PARTIAL_SELL_RECONSTRUCTION_MATERIAL"
        )

    if safe_float(
        baseline[
            "top_1_profit_concentration_percent"
        ]
    ) >= 50.0:
        diagnoses.append(
            "PNL_CONCENTRATED_IN_TOP_TRADE"
        )

    if safe_float(
        baseline[
            "return_without_best_trade_percent"
        ]
    ) <= 0:
        diagnoses.append(
            "RETURN_DEPENDS_ON_BEST_TRADE"
        )

    if int(
        baseline[
            "cached_unquotable_signals"
        ]
    ) > 0:
        diagnoses.append(
            "CACHED_JUPITER_INCOMPATIBILITIES_PRESENT"
        )

    if not diagnoses:
        diagnoses.append(
            "NO_SINGLE_DOMINANT_CONSTRAINT"
        )

    return diagnoses


def run_candidate_reconstruction_audit(
    db: Session,
    *,
    wallet_address: str,
    lookback_days: int = 14,
    warmup_days: int = 14,
    fixed_buy_size_sol: float = 0.05,
    slippage_bps: int = 100,
    fee_bps: int = 10,
    copy_delay_seconds: int = 8,
    delay_penalty_bps_per_minute: float = 25.0,
    baseline_starting_capital_sol: float = 1.0,
    baseline_max_open_positions: int = 5,
    max_excluded_trades: int = 500,
    now: datetime | None = None,
) -> CandidateReconstructionAuditRun:
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
    effective_max_details = max(
        0,
        min(int(max_excluded_trades), 2000),
    )
    baseline_positions = max(
        1,
        min(
            int(baseline_max_open_positions),
            50,
        ),
    )
    baseline_capital = max(
        0.001,
        min(
            float(
                baseline_starting_capital_sol
            ),
            1000.0,
        ),
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

    baseline = _simulate(
        warmup_trades=warmup_trades,
        analysis_trades=analysis_trades,
        cutoff=cutoff,
        started_at=started_at,
        starting_capital_sol=(
            baseline_capital
        ),
        fixed_buy_size_sol=(
            fixed_buy_size_sol
        ),
        friction_bps=friction_bps,
        fee_bps=fee_bps,
        max_open_positions=(
            baseline_positions
        ),
        include_bootstrap=True,
        jupiter_map=jupiter_map,
        collect_details=True,
        max_excluded_trades=(
            effective_max_details
        ),
    )

    baseline_without_bootstrap = _simulate(
        warmup_trades=warmup_trades,
        analysis_trades=analysis_trades,
        cutoff=cutoff,
        started_at=started_at,
        starting_capital_sol=(
            baseline_capital
        ),
        fixed_buy_size_sol=(
            fixed_buy_size_sol
        ),
        friction_bps=friction_bps,
        fee_bps=fee_bps,
        max_open_positions=(
            baseline_positions
        ),
        include_bootstrap=False,
        jupiter_map=jupiter_map,
        collect_details=False,
        max_excluded_trades=0,
    )

    baseline[
        "without_bootstrap"
    ] = baseline_without_bootstrap
    baseline[
        "source_trades"
    ] = len(trades)
    baseline[
        "warmup_source_trades"
    ] = len(warmup_trades)
    baseline[
        "analysis_source_trades"
    ] = len(analysis_trades)

    scenarios: list[dict] = []

    for capital in CAPITAL_SCENARIOS:
        for max_positions in POSITION_SCENARIOS:
            with_bootstrap = _simulate(
                warmup_trades=warmup_trades,
                analysis_trades=analysis_trades,
                cutoff=cutoff,
                started_at=started_at,
                starting_capital_sol=capital,
                fixed_buy_size_sol=(
                    fixed_buy_size_sol
                ),
                friction_bps=friction_bps,
                fee_bps=fee_bps,
                max_open_positions=(
                    max_positions
                ),
                include_bootstrap=True,
                jupiter_map=jupiter_map,
                collect_details=False,
                max_excluded_trades=0,
            )
            without_bootstrap = _simulate(
                warmup_trades=warmup_trades,
                analysis_trades=analysis_trades,
                cutoff=cutoff,
                started_at=started_at,
                starting_capital_sol=capital,
                fixed_buy_size_sol=(
                    fixed_buy_size_sol
                ),
                friction_bps=friction_bps,
                fee_bps=fee_bps,
                max_open_positions=(
                    max_positions
                ),
                include_bootstrap=False,
                jupiter_map=jupiter_map,
                collect_details=False,
                max_excluded_trades=0,
            )

            scenarios.append(
                {
                    "scenario_key": (
                        f"capital_{capital:g}_"
                        f"positions_{max_positions}"
                    ),
                    "starting_capital_sol": (
                        capital
                    ),
                    "max_open_positions": (
                        max_positions
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
                                with_bootstrap[
                                    "total_return_percent"
                                ]
                            )
                            - safe_float(
                                without_bootstrap[
                                    "total_return_percent"
                                ]
                            ),
                            4,
                        ),
                        "net_pnl_sol": _round(
                            safe_float(
                                with_bootstrap[
                                    "net_pnl_sol"
                                ]
                            )
                            - safe_float(
                                without_bootstrap[
                                    "net_pnl_sol"
                                ]
                            )
                        ),
                        "completed_positions": (
                            int(
                                with_bootstrap[
                                    "completed_positions"
                                ]
                            )
                            - int(
                                without_bootstrap[
                                    "completed_positions"
                                ]
                            )
                        ),
                    },
                }
            )

    diagnoses = _diagnose(
        baseline,
        scenarios,
    )
    completed_at = utc_now()

    parameters = {
        "lookback_days": (
            effective_lookback
        ),
        "warmup_days": (
            effective_warmup
        ),
        "fixed_buy_size_sol": (
            fixed_buy_size_sol
        ),
        "slippage_bps": (
            slippage_bps
        ),
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
        "baseline_starting_capital_sol": (
            baseline_capital
        ),
        "baseline_max_open_positions": (
            baseline_positions
        ),
        "capital_scenarios": list(
            CAPITAL_SCENARIOS
        ),
        "position_scenarios": list(
            POSITION_SCENARIOS
        ),
        "partial_sell_mode": (
            "SOURCE_PROPORTIONAL"
        ),
        "max_excluded_trades": (
            effective_max_details
        ),
    }

    safety = {
        "diagnostic_only": True,
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

    run = CandidateReconstructionAuditRun(
        run_id=str(uuid4()),
        wallet_address=wallet_address,
        status="COMPLETED",
        parameters=parameters,
        safety=safety,
        baseline_metrics=baseline,
        exclusion_summary=baseline[
            "exclusion_summary"
        ],
        excluded_trades=baseline[
            "excluded_trades"
        ],
        scenario_results=scenarios,
        diagnoses=diagnoses,
        started_at=started_at,
        completed_at=completed_at,
    )

    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def get_latest_candidate_reconstruction_audit(
    db: Session,
    wallet_address: str,
) -> CandidateReconstructionAuditRun | None:
    return (
        db.query(
            CandidateReconstructionAuditRun
        )
        .filter(
            CandidateReconstructionAuditRun
            .wallet_address
            == wallet_address
        )
        .order_by(
            CandidateReconstructionAuditRun
            .completed_at.desc(),
            CandidateReconstructionAuditRun
            .id.desc(),
        )
        .first()
    )
