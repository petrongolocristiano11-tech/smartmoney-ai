from collections import Counter
from datetime import (
    date,
    datetime,
    timedelta,
    timezone,
)

from sqlalchemy.orm import Session

from backend.app.models.paper_autopilot import (
    PaperAutopilotDecision,
    PaperAutopilotManagedPosition,
    PaperAutopilotPolicy,
    PaperAutopilotRun,
)
from backend.app.models.paper_order import (
    PaperOrder,
)
from backend.app.models.paper_position import (
    PaperPosition,
)
from backend.app.services.paper_trading_engine import (
    get_paper_account,
)


RUN_SUCCESS_STATUSES = {
    "COMPLETED",
    "PARTIAL",
}

PNL_EPSILON = 1e-12

AUTOPILOT_STALE_AFTER_HOURS = 2.5


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(
    value: datetime | None,
) -> datetime | None:
    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(
            tzinfo=timezone.utc
        )

    return value.astimezone(
        timezone.utc
    )


def safe_float(
    value,
) -> float:
    try:
        return float(value or 0.0)
    except (
        TypeError,
        ValueError,
    ):
        return 0.0


def rounded(
    value: float,
    digits: int = 8,
) -> float:
    return round(
        safe_float(value),
        digits,
    )


def percentage(
    numerator: float,
    denominator: float,
) -> float:
    denominator_value = safe_float(
        denominator
    )

    if denominator_value <= 0:
        return 0.0

    return rounded(
        (
            safe_float(numerator)
            / denominator_value
        )
        * 100,
        4,
    )


def hours_between(
    started_at: datetime | None,
    finished_at: datetime | None,
) -> float:
    start = ensure_utc(
        started_at
    )

    finish = ensure_utc(
        finished_at
    )

    if (
        start is None
        or finish is None
        or finish <= start
    ):
        return 0.0

    return rounded(
        (
            finish - start
        ).total_seconds()
        / 3600,
        4,
    )


def build_breakdown(
    counter: Counter,
    total: int,
    limit: int = 25,
) -> list[dict]:
    return [
        {
            "code": str(code),
            "count": int(count),
            "percentage": percentage(
                count,
                total,
            ),
        }
        for code, count
        in counter.most_common(limit)
    ]


def build_daily_rows(
    *,
    days: int,
    finished_at: datetime,
    runs: list[
        PaperAutopilotRun
    ],
    decisions: list[
        PaperAutopilotDecision
    ],
    closed_positions: list[
        PaperAutopilotManagedPosition
    ],
    exit_orders: dict[
        int,
        PaperOrder,
    ],
) -> list[dict]:
    start_date = (
        finished_at.date()
        - timedelta(
            days=days - 1
        )
    )

    daily: dict[
        date,
        dict,
    ] = {}

    for offset in range(days):
        current_date = (
            start_date
            + timedelta(days=offset)
        )

        daily[current_date] = {
            "date": current_date,
            "runs": 0,
            "entries": 0,
            "exits": 0,
            "decisions": 0,
            "realized_pnl_sol": 0.0,
            "cumulative_realized_pnl_sol": (
                0.0
            ),
        }

    for run in runs:
        started_at = ensure_utc(
            run.started_at
        )

        if started_at is None:
            continue

        current_date = (
            started_at.date()
        )

        if current_date not in daily:
            continue

        row = daily[current_date]

        row["runs"] += 1
        row["entries"] += int(
            run.entries_opened or 0
        )
        row["exits"] += int(
            run.exits_closed or 0
        )

    for decision in decisions:
        created_at = ensure_utc(
            decision.created_at
        )

        if created_at is None:
            continue

        current_date = (
            created_at.date()
        )

        if current_date in daily:
            daily[current_date][
                "decisions"
            ] += 1

    for managed_position in (
        closed_positions
    ):
        closed_at = ensure_utc(
            managed_position.closed_at
        )

        if closed_at is None:
            continue

        current_date = (
            closed_at.date()
        )

        if current_date not in daily:
            continue

        exit_order = exit_orders.get(
            managed_position.exit_order_id
        )

        if exit_order is None:
            continue

        daily[current_date][
            "realized_pnl_sol"
        ] += safe_float(
            exit_order.realized_pnl_sol
        )

    cumulative_pnl = 0.0

    rows: list[dict] = []

    for current_date in sorted(daily):
        row = daily[current_date]

        row["realized_pnl_sol"] = rounded(
            row["realized_pnl_sol"]
        )

        cumulative_pnl += (
            row["realized_pnl_sol"]
        )

        row[
            "cumulative_realized_pnl_sol"
        ] = rounded(
            cumulative_pnl
        )

        rows.append(row)

    return rows


def calculate_health(
    *,
    policy: (
        PaperAutopilotPolicy
        | None
    ),
    latest_run: (
        PaperAutopilotRun
        | None
    ),
    now: datetime,
) -> dict:
    policy_status = (
        policy.status
        if policy is not None
        else "DISABLED"
    )

    if latest_run is None:
        if policy_status == "DISABLED":
            health_status = "DISABLED"
        else:
            health_status = "STALE"

        return {
            "status": health_status,
            "policy_status": (
                policy_status
            ),
            "last_run_status": None,
            "last_run_at": None,
            "hours_since_last_run": (
                None
            ),
            "last_error_message": (
                None
            ),
        }

    latest_run_at = ensure_utc(
        latest_run.started_at
    )

    hours_since_last_run = (
        hours_between(
            latest_run_at,
            now,
        )
    )

    if policy_status == "DISABLED":
        health_status = "DISABLED"
    elif latest_run.status == "FAILED":
        health_status = "ERROR"
    elif (
        hours_since_last_run
        > AUTOPILOT_STALE_AFTER_HOURS
    ):
        health_status = "STALE"
    else:
        health_status = "HEALTHY"

    return {
        "status": health_status,
        "policy_status": (
            policy_status
        ),
        "last_run_status": (
            latest_run.status
        ),
        "last_run_at": (
            latest_run_at
        ),
        "hours_since_last_run": (
            hours_since_last_run
        ),
        "last_error_message": (
            latest_run.error_message
        ),
    }


def build_paper_autopilot_analytics(
    db: Session,
    account_id: int,
    *,
    days: int = 30,
    now: datetime | None = None,
) -> dict:
    finished_at = ensure_utc(
        now
    ) or utc_now()

    started_at = (
        finished_at
        - timedelta(days=days)
    )

    account = get_paper_account(
        db,
        account_id,
    )

    policy = (
        db.query(
            PaperAutopilotPolicy
        )
        .filter(
            PaperAutopilotPolicy.account_id
            == account_id
        )
        .first()
    )

    latest_run = (
        db.query(
            PaperAutopilotRun
        )
        .filter(
            PaperAutopilotRun.account_id
            == account_id
        )
        .order_by(
            PaperAutopilotRun.started_at
            .desc(),
            PaperAutopilotRun.id.desc(),
        )
        .first()
    )

    runs = (
        db.query(
            PaperAutopilotRun
        )
        .filter(
            PaperAutopilotRun.account_id
            == account_id,
            PaperAutopilotRun.started_at
            >= started_at,
        )
        .order_by(
            PaperAutopilotRun.started_at
            .asc(),
            PaperAutopilotRun.id.asc(),
        )
        .all()
    )

    decisions = (
        db.query(
            PaperAutopilotDecision
        )
        .filter(
            PaperAutopilotDecision.account_id
            == account_id,
            PaperAutopilotDecision.created_at
            >= started_at,
        )
        .order_by(
            PaperAutopilotDecision.created_at
            .asc(),
            PaperAutopilotDecision.id.asc(),
        )
        .all()
    )

    closed_positions = (
        db.query(
            PaperAutopilotManagedPosition
        )
        .filter(
            PaperAutopilotManagedPosition
            .account_id
            == account_id,
            PaperAutopilotManagedPosition
            .status
            == "CLOSED",
            PaperAutopilotManagedPosition
            .closed_at
            .is_not(None),
            PaperAutopilotManagedPosition
            .closed_at
            >= started_at,
        )
        .order_by(
            PaperAutopilotManagedPosition
            .closed_at
            .desc(),
            PaperAutopilotManagedPosition
            .id
            .desc(),
        )
        .all()
    )

    active_managed_positions = (
        db.query(
            PaperAutopilotManagedPosition
        )
        .filter(
            PaperAutopilotManagedPosition
            .account_id
            == account_id,
            PaperAutopilotManagedPosition
            .status
            == "ACTIVE",
        )
        .all()
    )

    order_ids = {
        order_id
        for managed_position
        in (
            closed_positions
            + active_managed_positions
        )
        for order_id in (
            managed_position
            .entry_order_id,
            managed_position
            .exit_order_id,
        )
        if order_id is not None
    }

    orders = (
        db.query(PaperOrder)
        .filter(
            PaperOrder.id.in_(
                order_ids
            )
        )
        .all()
        if order_ids
        else []
    )

    orders_by_id = {
        order.id: order
        for order in orders
    }

    exit_orders = {
        managed_position.exit_order_id:
            orders_by_id.get(
                managed_position.exit_order_id
            )
        for managed_position
        in closed_positions
        if (
            managed_position
            .exit_order_id
            is not None
        )
    }

    exit_orders = {
        order_id: order
        for order_id, order
        in exit_orders.items()
        if order is not None
    }

    active_position_ids = {
        managed_position.paper_position_id
        for managed_position
        in active_managed_positions
    }

    active_positions = (
        db.query(PaperPosition)
        .filter(
            PaperPosition.id.in_(
                active_position_ids
            )
        )
        .all()
        if active_position_ids
        else []
    )

    run_counter = Counter(
        run.status
        for run in runs
    )

    completed_runs = run_counter[
        "COMPLETED"
    ]

    partial_runs = run_counter[
        "PARTIAL"
    ]

    failed_runs = run_counter[
        "FAILED"
    ]

    skipped_runs = run_counter[
        "SKIPPED"
    ]

    running_runs = run_counter[
        "RUNNING"
    ]

    operational_runs = (
        completed_runs
        + partial_runs
        + failed_runs
    )

    run_analytics = {
        "total_runs": len(runs),
        "completed_runs": (
            completed_runs
        ),
        "partial_runs": partial_runs,
        "failed_runs": failed_runs,
        "skipped_runs": skipped_runs,
        "running_runs": running_runs,
        "operational_success_rate_percent": (
            percentage(
                completed_runs
                + partial_runs,
                operational_runs,
            )
        ),
        "signals_evaluated": sum(
            int(
                run.signals_evaluated
                or 0
            )
            for run in runs
        ),
        "entries_opened": sum(
            int(
                run.entries_opened
                or 0
            )
            for run in runs
        ),
        "exits_closed": sum(
            int(
                run.exits_closed
                or 0
            )
            for run in runs
        ),
        "decisions_recorded": sum(
            int(
                run.decisions_count
                or 0
            )
            for run in runs
        ),
        "errors_recorded": sum(
            int(
                run.errors_count
                or 0
            )
            for run in runs
        ),
    }

    decision_counter = Counter(
        decision.action
        for decision in decisions
    )

    entry_decision_total = (
        decision_counter["BUY"]
        + decision_counter["SKIP"]
        + decision_counter["ERROR"]
    )

    decision_analytics = {
        "total_decisions": (
            len(decisions)
        ),
        "buy_decisions": (
            decision_counter["BUY"]
        ),
        "sell_decisions": (
            decision_counter["SELL"]
        ),
        "hold_decisions": (
            decision_counter["HOLD"]
        ),
        "skip_decisions": (
            decision_counter["SKIP"]
        ),
        "error_decisions": (
            decision_counter["ERROR"]
        ),
        "entry_acceptance_rate_percent": (
            percentage(
                decision_counter[
                    "BUY"
                ],
                entry_decision_total,
            )
        ),
    }

    realized_values: list[float] = []

    holding_values: list[float] = []

    recent_closed_trades: list[
        dict
    ] = []

    exit_reason_counter = Counter()

    for managed_position in (
        closed_positions
    ):
        exit_order = exit_orders.get(
            managed_position.exit_order_id
        )

        if exit_order is None:
            continue

        realized_pnl = safe_float(
            exit_order.realized_pnl_sol
        )

        realized_values.append(
            realized_pnl
        )

        holding_hours = hours_between(
            managed_position.opened_at,
            managed_position.closed_at,
        )

        holding_values.append(
            holding_hours
        )

        exit_reason = (
            managed_position.exit_reason
            or "UNKNOWN"
        )

        exit_reason_counter[
            exit_reason
        ] += 1

        entry_order = (
            orders_by_id.get(
                managed_position
                .entry_order_id
            )
        )

        invested_sol = 0.0

        if entry_order is not None:
            invested_sol = (
                safe_float(
                    entry_order
                    .gross_value_sol
                )
                + safe_float(
                    entry_order.fee_sol
                )
            )

        return_percent = (
            percentage(
                realized_pnl,
                invested_sol,
            )
            if invested_sol > 0
            else None
        )

        recent_closed_trades.append(
            {
                "managed_position_id": (
                    managed_position.id
                ),
                "token_mint": (
                    managed_position
                    .token_mint
                ),
                "exit_reason": (
                    managed_position
                    .exit_reason
                ),
                "realized_pnl_sol": (
                    rounded(
                        realized_pnl
                    )
                ),
                "return_percent": (
                    return_percent
                ),
                "holding_hours": (
                    holding_hours
                ),
                "entry_signal_score": (
                    managed_position
                    .entry_signal_score
                ),
                "opened_at": ensure_utc(
                    managed_position
                    .opened_at
                ),
                "closed_at": ensure_utc(
                    managed_position
                    .closed_at
                ),
            }
        )

    winning_values = [
        pnl
        for pnl in realized_values
        if pnl > PNL_EPSILON
    ]

    losing_values = [
        pnl
        for pnl in realized_values
        if pnl < -PNL_EPSILON
    ]

    breakeven_count = (
        len(realized_values)
        - len(winning_values)
        - len(losing_values)
    )

    gross_profit = sum(
        winning_values
    )

    gross_loss = abs(
        sum(losing_values)
    )

    net_realized_pnl = sum(
        realized_values
    )

    if gross_loss > 0:
        profit_factor = rounded(
            gross_profit
            / gross_loss,
            4,
        )
    else:
        profit_factor = None

    trading_analytics = {
        "closed_trades": (
            len(realized_values)
        ),
        "winning_trades": (
            len(winning_values)
        ),
        "losing_trades": (
            len(losing_values)
        ),
        "breakeven_trades": (
            breakeven_count
        ),
        "win_rate_percent": (
            percentage(
                len(winning_values),
                len(realized_values),
            )
        ),
        "net_realized_pnl_sol": (
            rounded(
                net_realized_pnl
            )
        ),
        "gross_profit_sol": (
            rounded(gross_profit)
        ),
        "gross_loss_sol": (
            rounded(gross_loss)
        ),
        "profit_factor": (
            profit_factor
        ),
        "average_trade_pnl_sol": (
            rounded(
                net_realized_pnl
                / len(realized_values)
            )
            if realized_values
            else 0.0
        ),
        "best_trade_pnl_sol": (
            rounded(
                max(realized_values)
            )
            if realized_values
            else 0.0
        ),
        "worst_trade_pnl_sol": (
            rounded(
                min(realized_values)
            )
            if realized_values
            else 0.0
        ),
        "average_holding_hours": (
            rounded(
                sum(holding_values)
                / len(holding_values),
                4,
            )
            if holding_values
            else 0.0
        ),
    }

    open_position_analytics = {
        "active_managed_positions": (
            len(
                active_managed_positions
            )
        ),
        "cost_basis_sol": rounded(
            sum(
                safe_float(
                    position
                    .cost_basis_sol
                )
                for position
                in active_positions
            )
        ),
        "market_value_sol": rounded(
            sum(
                safe_float(
                    position
                    .market_value_sol
                )
                for position
                in active_positions
            )
        ),
        "unrealized_pnl_sol": rounded(
            sum(
                safe_float(
                    position
                    .unrealized_pnl_sol
                )
                for position
                in active_positions
            )
        ),
    }

    decision_reason_counter = Counter(
        decision.reason_code
        or "UNKNOWN"
        for decision in decisions
    )

    return {
        "account_id": account.id,
        "account_name": account.name,
        "generated_at": finished_at,
        "window": {
            "days": days,
            "started_at": started_at,
            "finished_at": (
                finished_at
            ),
        },
        "health": calculate_health(
            policy=policy,
            latest_run=latest_run,
            now=finished_at,
        ),
        "runs": run_analytics,
        "decisions": (
            decision_analytics
        ),
        "trading": (
            trading_analytics
        ),
        "open_positions": (
            open_position_analytics
        ),
        "decision_reasons": (
            build_breakdown(
                decision_reason_counter,
                len(decisions),
            )
        ),
        "exit_reasons": (
            build_breakdown(
                exit_reason_counter,
                len(realized_values),
            )
        ),
        "daily": build_daily_rows(
            days=days,
            finished_at=finished_at,
            runs=runs,
            decisions=decisions,
            closed_positions=(
                closed_positions
            ),
            exit_orders=exit_orders,
        ),
        "recent_closed_trades": (
            recent_closed_trades[
                :50
            ]
        ),
    } 