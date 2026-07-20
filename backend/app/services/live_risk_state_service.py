from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.live_copy_order import LiveCopyOrder
from backend.app.models.live_platform_config import LivePlatformConfig
from backend.app.models.live_position import LivePosition
from backend.app.models.live_risk_state import LiveRiskState
from backend.app.models.live_trading_policy import LiveTradingPolicy
from backend.app.services.live_trading_errors import LiveTradingError


_COMPLETED_ORDER_STATUSES = ("DRY_RUN", "FILLED")
_PNL_EPSILON = 1e-12


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def resolve_active_generation(policy: LiveTradingPolicy) -> int:
    if policy.mode == "DRY_RUN":
        return max(1, int(policy.dry_run_generation or 1))
    return 1


def _starting_equity(db: Session) -> float:
    value = (
        db.query(LivePlatformConfig.analytics_starting_equity_sol)
        .filter(LivePlatformConfig.name == "default")
        .scalar()
    )
    return max(0.000001, float(value or 1.0))


def _resolve_policy(
    db: Session,
    policy: LiveTradingPolicy | None,
) -> LiveTradingPolicy | None:
    if policy is not None:
        return policy
    return (
        db.query(LiveTradingPolicy)
        .filter(LiveTradingPolicy.name == "default")
        .first()
    )


def get_or_create_risk_state(
    db: Session,
    *,
    mode: str,
    generation: int,
) -> LiveRiskState:
    state = (
        db.query(LiveRiskState)
        .filter(
            LiveRiskState.mode == mode,
            LiveRiskState.generation == generation,
        )
        .first()
    )
    if state is not None:
        return state

    equity = _starting_equity(db)
    state = LiveRiskState(
        mode=mode,
        generation=generation,
        starting_equity_sol=equity,
        current_equity_sol=equity,
        peak_equity_sol=equity,
        realized_pnl_sol=0.0,
        drawdown_percent=0.0,
        loss_streak=0,
    )
    db.add(state)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return (
            db.query(LiveRiskState)
            .filter(
                LiveRiskState.mode == mode,
                LiveRiskState.generation == generation,
            )
            .one()
        )
    return state


def _completed_orders_query(
    db: Session,
    *,
    mode: str,
    generation: int,
):
    return db.query(LiveCopyOrder).filter(
        LiveCopyOrder.mode == mode,
        LiveCopyOrder.generation == generation,
        LiveCopyOrder.status.in_(_COMPLETED_ORDER_STATUSES),
        LiveCopyOrder.executed_at.is_not(None),
    )


def _rebuild_loss_history(
    db: Session,
    *,
    state: LiveRiskState,
    policy: LiveTradingPolicy | None,
    now: datetime,
) -> None:
    """Rebuild consecutive losses from authoritative completed SELL orders.

    This intentionally includes SOURCE_TRADE, MANUAL_CLOSE and AUTO_EXIT orders.
    The rebuild makes old manual closes visible immediately after deployment and
    prevents incremental counters from drifting or double-counting after retries.
    """

    query = _completed_orders_query(
        db,
        mode=state.mode,
        generation=state.generation,
    ).filter(
        LiveCopyOrder.source_side == "SELL",
        LiveCopyOrder.realized_pnl_sol.is_not(None),
    )

    reset_at = _as_utc(state.loss_streak_reset_at)
    if reset_at is not None:
        query = query.filter(LiveCopyOrder.executed_at > reset_at)

    sell_orders = query.order_by(
        LiveCopyOrder.executed_at.asc(),
        LiveCopyOrder.id.asc(),
    ).all()

    latest_fill_at = (
        _completed_orders_query(
            db,
            mode=state.mode,
            generation=state.generation,
        )
        .with_entities(func.max(LiveCopyOrder.executed_at))
        .scalar()
    )
    state.last_fill_at = latest_fill_at

    threshold = max(
        1,
        int(
            policy.loss_streak_cooldown_threshold
            if policy is not None
            else 3
        ),
    )
    cooldown_minutes = max(
        1,
        int(
            policy.cooldown_after_loss_minutes
            if policy is not None
            else 30
        ),
    )

    if sell_orders or reset_at is not None:
        loss_streak = 0
        last_loss_at: datetime | None = None
        for order in sell_orders:
            pnl = float(order.realized_pnl_sol or 0.0)
            executed_at = _as_utc(order.executed_at)
            if pnl < -_PNL_EPSILON:
                loss_streak += 1
                last_loss_at = executed_at or last_loss_at
            elif pnl > _PNL_EPSILON:
                loss_streak = 0

        state.loss_streak = loss_streak
        state.last_loss_at = last_loss_at
    else:
        # Backward compatibility for an explicitly persisted risk state that
        # predates historical SELL rows (or is injected by operational tests).
        loss_streak = max(0, int(state.loss_streak or 0))
        last_loss_at = _as_utc(state.last_loss_at)

    cooldown_until: datetime | None = None
    if loss_streak >= threshold and last_loss_at is not None:
        cooldown_until = last_loss_at + timedelta(minutes=cooldown_minutes)
        if cooldown_until <= now:
            cooldown_until = None
    elif not sell_orders and reset_at is None:
        existing_cooldown = _as_utc(state.cooldown_until)
        if existing_cooldown is not None and existing_cooldown > now:
            cooldown_until = existing_cooldown

    state.cooldown_until = cooldown_until

    drawdown_limit = (
        float(policy.max_portfolio_drawdown_percent)
        if policy is not None
        else None
    )
    drawdown_blocked = (
        drawdown_limit is not None
        and float(state.drawdown_percent or 0.0) >= drawdown_limit
    )

    if cooldown_until is not None:
        state.blocked_reason = (
            "COOLDOWN_LOSS_STREAK: "
            f"{loss_streak} perdite consecutive"
        )
    elif drawdown_blocked:
        state.blocked_reason = (
            "MAX_PORTFOLIO_DRAWDOWN: "
            f"{float(state.drawdown_percent or 0.0):.2f}%"
        )
    elif state.blocked_reason and state.blocked_reason.startswith(
        ("COOLDOWN", "MAX_PORTFOLIO_DRAWDOWN")
    ):
        state.blocked_reason = None


def refresh_risk_state(
    db: Session,
    *,
    mode: str,
    generation: int,
    now: datetime | None = None,
    policy: LiveTradingPolicy | None = None,
    commit: bool = False,
) -> LiveRiskState:
    now = _as_utc(now or utc_now()) or utc_now()
    state = get_or_create_risk_state(
        db,
        mode=mode,
        generation=generation,
    )
    policy = _resolve_policy(db, policy)

    realized = float(
        db.query(
            func.coalesce(func.sum(LiveCopyOrder.realized_pnl_sol), 0.0)
        )
        .filter(
            LiveCopyOrder.mode == mode,
            LiveCopyOrder.generation == generation,
            LiveCopyOrder.status.in_(_COMPLETED_ORDER_STATUSES),
        )
        .scalar()
        or 0.0
    )

    open_positions = (
        db.query(LivePosition)
        .filter(
            LivePosition.mode == mode,
            LivePosition.generation == generation,
            LivePosition.status == "OPEN",
        )
        .all()
    )
    unrealized = sum(
        float(position.unrealized_pnl_sol or 0.0)
        for position in open_positions
    )

    current_equity = max(
        0.0,
        float(state.starting_equity_sol) + realized + unrealized,
    )
    peak_equity = max(
        float(state.peak_equity_sol or state.starting_equity_sol),
        current_equity,
    )
    drawdown = (
        max(0.0, (peak_equity - current_equity) / peak_equity * 100.0)
        if peak_equity > 0
        else 0.0
    )

    state.realized_pnl_sol = realized
    state.current_equity_sol = current_equity
    state.peak_equity_sol = peak_equity
    state.drawdown_percent = drawdown

    _rebuild_loss_history(
        db,
        state=state,
        policy=policy,
        now=now,
    )

    if commit:
        db.commit()
        db.refresh(state)
    else:
        db.flush()
    return state


def register_filled_order(
    db: Session,
    *,
    policy: LiveTradingPolicy,
    order: LiveCopyOrder,
    now: datetime | None = None,
) -> LiveRiskState:
    """Refresh risk state deterministically after any completed order.

    The order is already attached to the current SQLAlchemy session. Query
    autoflush makes it part of the historical rebuild, so manual and automatic
    SELL orders follow exactly the same logic without incremental double-counts.
    """

    return refresh_risk_state(
        db,
        mode=order.mode,
        generation=order.generation,
        now=now,
        policy=policy,
        commit=False,
    )


def assert_buy_risk_allowed(
    policy: LiveTradingPolicy,
    state: LiveRiskState,
    *,
    now: datetime | None = None,
) -> None:
    now = now or utc_now()
    cooldown_until = _as_utc(state.cooldown_until)
    if cooldown_until is not None and cooldown_until > now:
        raise LiveTradingError(
            "Nuovi BUY sospesi dal cooldown dopo una serie di perdite.",
            code="LOSS_STREAK_COOLDOWN",
            status_code=409,
            payload={"cooldown_until": cooldown_until.isoformat()},
        )

    if float(state.drawdown_percent or 0.0) >= float(
        policy.max_portfolio_drawdown_percent
    ):
        state.blocked_reason = (
            "MAX_PORTFOLIO_DRAWDOWN: "
            f"{state.drawdown_percent:.2f}%"
        )
        raise LiveTradingError(
            "Drawdown massimo del portafoglio raggiunto.",
            code="MAX_PORTFOLIO_DRAWDOWN",
            status_code=409,
            payload={
                "drawdown_percent": float(state.drawdown_percent or 0.0),
                "limit_percent": float(policy.max_portfolio_drawdown_percent),
            },
        )


def reset_risk_cooldown(
    db: Session,
    *,
    mode: str,
    generation: int,
) -> LiveRiskState:
    state = get_or_create_risk_state(
        db,
        mode=mode,
        generation=generation,
    )
    reset_at = utc_now()
    state.loss_streak = 0
    state.last_loss_at = None
    state.loss_streak_reset_at = reset_at
    state.cooldown_until = None
    if state.blocked_reason and state.blocked_reason.startswith("COOLDOWN"):
        state.blocked_reason = None
    db.commit()
    db.refresh(state)
    return state


def serialize_risk_state(state: LiveRiskState) -> dict:
    return {
        "id": state.id,
        "mode": state.mode,
        "generation": state.generation,
        "starting_equity_sol": state.starting_equity_sol,
        "current_equity_sol": state.current_equity_sol,
        "peak_equity_sol": state.peak_equity_sol,
        "realized_pnl_sol": state.realized_pnl_sol,
        "drawdown_percent": state.drawdown_percent,
        "loss_streak": state.loss_streak,
        "cooldown_until": state.cooldown_until,
        "blocked_reason": state.blocked_reason,
        "last_loss_at": state.last_loss_at,
        "last_fill_at": state.last_fill_at,
        "loss_streak_reset_at": state.loss_streak_reset_at,
        "updated_at": state.updated_at,
    }
