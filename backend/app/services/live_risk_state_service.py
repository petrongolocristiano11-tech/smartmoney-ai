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


def refresh_risk_state(
    db: Session,
    *,
    mode: str,
    generation: int,
    now: datetime | None = None,
    commit: bool = False,
) -> LiveRiskState:
    now = now or utc_now()
    state = get_or_create_risk_state(
        db,
        mode=mode,
        generation=generation,
    )

    realized = float(
        db.query(
            func.coalesce(func.sum(LiveCopyOrder.realized_pnl_sol), 0.0)
        )
        .filter(
            LiveCopyOrder.mode == mode,
            LiveCopyOrder.generation == generation,
            LiveCopyOrder.status.in_(("DRY_RUN", "FILLED")),
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

    cooldown_until = _as_utc(state.cooldown_until)
    if cooldown_until is not None and cooldown_until <= now:
        state.cooldown_until = None
        if state.blocked_reason and state.blocked_reason.startswith("COOLDOWN"):
            state.blocked_reason = None

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
    now = now or utc_now()
    state = refresh_risk_state(
        db,
        mode=order.mode,
        generation=order.generation,
        now=now,
        commit=False,
    )
    state.last_fill_at = now

    if order.source_side == "SELL":
        pnl = float(order.realized_pnl_sol or 0.0)
        if pnl < 0:
            state.loss_streak = int(state.loss_streak or 0) + 1
            state.last_loss_at = now
            if state.loss_streak >= int(policy.loss_streak_cooldown_threshold):
                state.cooldown_until = now + timedelta(
                    minutes=int(policy.cooldown_after_loss_minutes)
                )
                state.blocked_reason = (
                    "COOLDOWN_LOSS_STREAK: "
                    f"{state.loss_streak} perdite consecutive"
                )
        elif pnl > 0:
            state.loss_streak = 0
            if state.blocked_reason and state.blocked_reason.startswith("COOLDOWN"):
                state.blocked_reason = None
                state.cooldown_until = None

    db.flush()
    return refresh_risk_state(
        db,
        mode=order.mode,
        generation=order.generation,
        now=now,
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
    state.loss_streak = 0
    state.cooldown_until = None
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
        "updated_at": state.updated_at,
    }
