import csv
import io
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.orm import Session

from backend.app.models.live_copy_order import LiveCopyOrder
from backend.app.models.live_position import LivePosition
from backend.app.services.live_platform_config_service import get_or_create_platform_config


PNL_EPSILON = 1e-12


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def safe_float(value) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def rounded(value, digits: int = 8) -> float:
    return round(safe_float(value), digits)


def percentage(numerator, denominator) -> float:
    denominator_value = safe_float(denominator)
    if denominator_value <= 0:
        return 0.0
    return round(safe_float(numerator) / denominator_value * 100, 4)


def resolve_generation(db: Session, mode: str, generation: int | None) -> int:
    if generation is not None:
        return max(1, int(generation))

    if mode == "LIVE":
        return 1

    from backend.app.services.live_trading_policy_service import get_or_create_live_policy

    policy = get_or_create_live_policy(db)
    return max(1, int(policy.dry_run_generation or 1))


def build_live_trading_analytics(
    db: Session,
    *,
    days: int = 30,
    mode: str = "DRY_RUN",
    generation: int | None = None,
    now: datetime | None = None,
) -> dict:
    finished_at = ensure_utc(now) or utc_now()
    started_at = finished_at - timedelta(days=days)
    mode = str(mode).strip().upper()
    active_generation = resolve_generation(db, mode, generation)
    config = get_or_create_platform_config(db)

    orders = (
        db.query(LiveCopyOrder)
        .filter(
            LiveCopyOrder.mode == mode,
            LiveCopyOrder.generation == active_generation,
            LiveCopyOrder.created_at >= started_at,
        )
        .order_by(LiveCopyOrder.created_at.asc(), LiveCopyOrder.id.asc())
        .all()
    )

    positions = (
        db.query(LivePosition)
        .filter(
            LivePosition.mode == mode,
            LivePosition.generation == active_generation,
        )
        .order_by(LivePosition.opened_at.asc(), LivePosition.id.asc())
        .all()
    )

    completed_statuses = {"DRY_RUN", "FILLED"}
    completed_orders = [order for order in orders if order.status in completed_statuses]
    sell_orders = [
        order
        for order in completed_orders
        if order.source_side == "SELL" and order.realized_pnl_sol is not None
    ]
    buy_orders = [order for order in completed_orders if order.source_side == "BUY"]

    pnl_values = [safe_float(order.realized_pnl_sol) for order in sell_orders]
    wins = [value for value in pnl_values if value > PNL_EPSILON]
    losses = [value for value in pnl_values if value < -PNL_EPSILON]
    breakeven = [value for value in pnl_values if abs(value) <= PNL_EPSILON]

    gross_profit = sum(wins)
    gross_loss_abs = abs(sum(losses))
    net_pnl = sum(pnl_values)
    invested_sol = sum(max(0.0, safe_float(order.requested_value_sol)) for order in buy_orders)

    daily_by_date: dict[date, dict] = {}
    first_date = finished_at.date() - timedelta(days=days - 1)
    for offset in range(days):
        current_date = first_date + timedelta(days=offset)
        daily_by_date[current_date] = {
            "date": current_date,
            "buys": 0,
            "sells": 0,
            "realized_pnl_sol": 0.0,
            "cumulative_pnl_sol": 0.0,
            "equity_sol": 0.0,
            "drawdown_sol": 0.0,
            "drawdown_percent": 0.0,
        }

    for order in completed_orders:
        event_at = ensure_utc(order.executed_at or order.created_at)
        if event_at is None or event_at.date() not in daily_by_date:
            continue
        row = daily_by_date[event_at.date()]
        if order.source_side == "BUY":
            row["buys"] += 1
        else:
            row["sells"] += 1
            row["realized_pnl_sol"] += safe_float(order.realized_pnl_sol)

    cumulative = 0.0
    starting_equity = max(0.000000001, safe_float(config.analytics_starting_equity_sol))
    peak_equity = starting_equity
    max_drawdown_sol = 0.0
    max_drawdown_percent = 0.0
    daily_rows: list[dict] = []

    for current_date in sorted(daily_by_date):
        row = daily_by_date[current_date]
        row["realized_pnl_sol"] = rounded(row["realized_pnl_sol"])
        cumulative += row["realized_pnl_sol"]
        equity = starting_equity + cumulative
        peak_equity = max(peak_equity, equity)
        drawdown = max(0.0, peak_equity - equity)
        drawdown_percent = percentage(drawdown, peak_equity)
        max_drawdown_sol = max(max_drawdown_sol, drawdown)
        max_drawdown_percent = max(max_drawdown_percent, drawdown_percent)
        row["cumulative_pnl_sol"] = rounded(cumulative)
        row["equity_sol"] = rounded(equity)
        row["drawdown_sol"] = rounded(drawdown)
        row["drawdown_percent"] = rounded(drawdown_percent, 4)
        daily_rows.append(row)

    wallet_rows: dict[str, dict] = defaultdict(
        lambda: {
            "source_wallet": "",
            "orders": 0,
            "buys": 0,
            "sells": 0,
            "wins": 0,
            "losses": 0,
            "realized_pnl_sol": 0.0,
            "invested_sol": 0.0,
        }
    )
    token_rows: dict[str, dict] = defaultdict(
        lambda: {
            "token_mint": "",
            "orders": 0,
            "buys": 0,
            "sells": 0,
            "wins": 0,
            "losses": 0,
            "realized_pnl_sol": 0.0,
            "invested_sol": 0.0,
        }
    )

    for order in completed_orders:
        wallet_key = str(order.source_wallet or "UNKNOWN")
        token_key = str(order.source_token_mint or "UNKNOWN")
        pnl = safe_float(order.realized_pnl_sol)

        for row, key_field, key_value in (
            (wallet_rows[wallet_key], "source_wallet", wallet_key),
            (token_rows[token_key], "token_mint", token_key),
        ):
            row[key_field] = key_value
            row["orders"] += 1
            if order.source_side == "BUY":
                row["buys"] += 1
                row["invested_sol"] += max(0.0, safe_float(order.requested_value_sol))
            else:
                row["sells"] += 1
                row["realized_pnl_sol"] += pnl
                if pnl > PNL_EPSILON:
                    row["wins"] += 1
                elif pnl < -PNL_EPSILON:
                    row["losses"] += 1

    def finalize_breakdown(rows: dict[str, dict], key_field: str) -> list[dict]:
        result = []
        for row in rows.values():
            closed = row["wins"] + row["losses"]
            row["realized_pnl_sol"] = rounded(row["realized_pnl_sol"])
            row["invested_sol"] = rounded(row["invested_sol"])
            row["win_rate_percent"] = percentage(row["wins"], closed)
            row["roi_percent"] = percentage(row["realized_pnl_sol"], row["invested_sol"])
            result.append(row)
        result.sort(key=lambda item: (item["realized_pnl_sol"], item[key_field]), reverse=True)
        return result

    open_positions = [position for position in positions if position.status == "OPEN"]
    closed_positions = [position for position in positions if position.status == "CLOSED"]
    exposure = sum(safe_float(position.cost_basis_sol) for position in open_positions)

    recent_closed = []
    for position in sorted(
        closed_positions,
        key=lambda item: ensure_utc(item.closed_at) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:50]:
        recent_closed.append(
            {
                "position_id": position.id,
                "token_mint": position.token_mint,
                "realized_pnl_sol": rounded(position.realized_pnl_sol),
                "opened_at": position.opened_at,
                "closed_at": position.closed_at,
            }
        )

    status_counts: dict[str, int] = defaultdict(int)
    for order in orders:
        status_counts[str(order.status)] += 1

    return {
        "generated_at": finished_at,
        "mode": mode,
        "generation": active_generation,
        "window": {
            "days": days,
            "started_at": started_at,
            "finished_at": finished_at,
        },
        "summary": {
            "orders_total": len(orders),
            "orders_completed": len(completed_orders),
            "buy_orders": len(buy_orders),
            "sell_orders": len(sell_orders),
            "open_positions": len(open_positions),
            "closed_positions": len(closed_positions),
            "open_exposure_sol": rounded(exposure),
            "invested_sol": rounded(invested_sol),
            "net_realized_pnl_sol": rounded(net_pnl),
            "roi_percent": percentage(net_pnl, invested_sol),
            "winning_trades": len(wins),
            "losing_trades": len(losses),
            "breakeven_trades": len(breakeven),
            "win_rate_percent": percentage(len(wins), len(sell_orders)),
            "gross_profit_sol": rounded(gross_profit),
            "gross_loss_sol": rounded(gross_loss_abs),
            "profit_factor": (
                rounded(gross_profit / gross_loss_abs, 4)
                if gross_loss_abs > PNL_EPSILON
                else None
            ),
            "average_trade_pnl_sol": rounded(net_pnl / len(sell_orders)) if sell_orders else 0.0,
            "best_trade_pnl_sol": rounded(max(pnl_values)) if pnl_values else 0.0,
            "worst_trade_pnl_sol": rounded(min(pnl_values)) if pnl_values else 0.0,
            "max_drawdown_sol": rounded(max_drawdown_sol),
            "max_drawdown_percent": rounded(max_drawdown_percent, 4),
            "starting_equity_sol": rounded(starting_equity),
            "ending_equity_sol": rounded(starting_equity + net_pnl),
        },
        "order_statuses": dict(sorted(status_counts.items())),
        "daily": daily_rows,
        "wallet_performance": finalize_breakdown(wallet_rows, "source_wallet"),
        "token_performance": finalize_breakdown(token_rows, "token_mint"),
        "recent_closed_positions": recent_closed,
    }


def build_live_trading_csv(payload: dict) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "date",
        "mode",
        "generation",
        "buys",
        "sells",
        "realized_pnl_sol",
        "cumulative_pnl_sol",
        "equity_sol",
        "drawdown_sol",
        "drawdown_percent",
    ])

    for row in payload.get("daily", []):
        writer.writerow([
            row["date"].isoformat() if hasattr(row["date"], "isoformat") else row["date"],
            payload["mode"],
            payload["generation"],
            row["buys"],
            row["sells"],
            row["realized_pnl_sol"],
            row["cumulative_pnl_sol"],
            row["equity_sol"],
            row["drawdown_sol"],
            row["drawdown_percent"],
        ])

    return output.getvalue()
