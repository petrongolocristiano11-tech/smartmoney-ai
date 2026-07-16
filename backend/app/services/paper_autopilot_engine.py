from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Any, Callable

from sqlalchemy.orm import Session

from backend.app.models.paper_account import PaperAccount
from backend.app.models.paper_autopilot import (
    PaperAutopilotDecision,
    PaperAutopilotManagedPosition,
    PaperAutopilotPolicy,
    PaperAutopilotRun,
)
from backend.app.models.paper_position import PaperPosition
from backend.app.services.paper_trading_engine import (
    PaperTradingError,
    get_paper_account,
    get_paper_account_summary,
)
from backend.app.services.paper_trading_pricing_service import (
    buy_paper_token_with_oracle,
    sell_paper_token_with_oracle,
)
from backend.app.services.price_oracle import (
    JupiterPriceOracle,
    PriceOracleError,
)
from backend.app.services.signals_engine import get_token_signals


MAX_RUNNING_AGE_MINUTES = 30
CONFIDENCE_RANK = {"LOW": 1, "MEDIUM": 2, "HIGH": 3}
EXPECTED_PRICE_SKIP_CODES = {
    "PRICE_NOT_AVAILABLE",
    "INVALID_TOKEN_MINT",
    "EMPTY_PRICE_REQUEST",
}


class PaperAutopilotError(Exception):
    def __init__(
        self,
        message: str,
        code: str = "PAPER_AUTOPILOT_ERROR",
    ):
        super().__init__(message)
        self.message = message
        self.code = code


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def _normalize_trigger(trigger: str) -> str:
    normalized = str(trigger or "").strip().upper()
    if normalized not in {"MANUAL", "AUTOMATION"}:
        raise PaperAutopilotError(
            "Il trigger deve essere MANUAL o AUTOMATION.",
            code="INVALID_AUTOPILOT_TRIGGER",
        )
    return normalized


def get_or_create_autopilot_policy(
    db: Session,
    account_id: int,
) -> PaperAutopilotPolicy:
    get_paper_account(db, account_id)

    policy = (
        db.query(PaperAutopilotPolicy)
        .filter(PaperAutopilotPolicy.account_id == account_id)
        .first()
    )
    if policy is not None:
        return policy

    policy = PaperAutopilotPolicy(account_id=account_id)
    db.add(policy)
    try:
        db.commit()
    except Exception:
        db.rollback()
        policy = (
            db.query(PaperAutopilotPolicy)
            .filter(PaperAutopilotPolicy.account_id == account_id)
            .first()
        )
        if policy is None:
            raise

    db.refresh(policy)
    return policy


def list_autopilot_runs(
    db: Session,
    account_id: int,
    limit: int = 50,
) -> list[PaperAutopilotRun]:
    get_paper_account(db, account_id)
    normalized_limit = max(1, min(int(limit), 500))
    return (
        db.query(PaperAutopilotRun)
        .filter(PaperAutopilotRun.account_id == account_id)
        .order_by(PaperAutopilotRun.started_at.desc())
        .limit(normalized_limit)
        .all()
    )


def list_autopilot_decisions(
    db: Session,
    account_id: int,
    limit: int = 200,
) -> list[PaperAutopilotDecision]:
    get_paper_account(db, account_id)
    normalized_limit = max(1, min(int(limit), 1000))
    return (
        db.query(PaperAutopilotDecision)
        .filter(PaperAutopilotDecision.account_id == account_id)
        .order_by(PaperAutopilotDecision.created_at.desc())
        .limit(normalized_limit)
        .all()
    )


def list_managed_positions(
    db: Session,
    account_id: int,
    status: str | None = None,
) -> list[PaperAutopilotManagedPosition]:
    get_paper_account(db, account_id)
    query = db.query(PaperAutopilotManagedPosition).filter(
        PaperAutopilotManagedPosition.account_id == account_id
    )
    if status is not None:
        normalized = str(status).strip().upper()
        if normalized not in {"ACTIVE", "CLOSED"}:
            raise PaperAutopilotError(
                "Lo stato deve essere ACTIVE o CLOSED.",
                code="INVALID_MANAGED_POSITION_STATUS",
            )
        query = query.filter(PaperAutopilotManagedPosition.status == normalized)

    return query.order_by(PaperAutopilotManagedPosition.updated_at.desc()).all()


def _record_decision(
    db: Session,
    run: PaperAutopilotRun,
    *,
    action: str,
    reason_code: str,
    reason: str,
    token_mint: str | None = None,
    managed_position: PaperAutopilotManagedPosition | None = None,
    paper_position: PaperPosition | None = None,
    paper_order_id: int | None = None,
    signal: dict[str, Any] | None = None,
    market_price_sol: float | None = None,
    quantity: float | None = None,
    value_sol: float | None = None,
) -> PaperAutopilotDecision:
    signal = signal or {}
    decision = PaperAutopilotDecision(
        run_id=run.id,
        account_id=run.account_id,
        managed_position_id=(managed_position.id if managed_position else None),
        paper_position_id=(paper_position.id if paper_position else None),
        paper_order_id=paper_order_id,
        token_mint=token_mint,
        action=action,
        reason_code=reason_code,
        reason=reason,
        signal_score=(
            _as_float(signal.get("signal_score"))
            if signal.get("signal_score") is not None
            else None
        ),
        evidence_score=(
            _as_float(signal.get("evidence_score"))
            if signal.get("evidence_score") is not None
            else None
        ),
        buyers=(
            _as_int(signal.get("buyers"))
            if signal.get("buyers") is not None
            else None
        ),
        confidence=(
            str(signal.get("confidence")).upper()
            if signal.get("confidence") is not None
            else None
        ),
        market_price_sol=market_price_sol,
        quantity=quantity,
        value_sol=value_sol,
        signal_snapshot=_json_safe(signal) if signal else None,
    )
    db.add(decision)
    run.decisions_count = int(run.decisions_count or 0) + 1
    return decision


def _close_stale_runs(
    db: Session,
    account_id: int,
    now: datetime,
) -> None:
    stale_before = now - timedelta(minutes=MAX_RUNNING_AGE_MINUTES)
    stale_runs = (
        db.query(PaperAutopilotRun)
        .filter(
            PaperAutopilotRun.account_id == account_id,
            PaperAutopilotRun.status == "RUNNING",
            PaperAutopilotRun.started_at < stale_before,
        )
        .all()
    )
    for stale_run in stale_runs:
        stale_run.status = "FAILED"
        stale_run.finished_at = now
        stale_run.errors_count = max(int(stale_run.errors_count or 0), 1)
        stale_run.error_message = "Run Autopilot rimasto RUNNING oltre il limite."
    if stale_runs:
        db.commit()


def _create_run(
    db: Session,
    account_id: int,
    policy: PaperAutopilotPolicy,
    trigger: str,
    now: datetime,
) -> PaperAutopilotRun:
    _close_stale_runs(db, account_id, now)

    active_run = (
        db.query(PaperAutopilotRun)
        .filter(
            PaperAutopilotRun.account_id == account_id,
            PaperAutopilotRun.status == "RUNNING",
        )
        .first()
    )
    if active_run is not None:
        raise PaperAutopilotError(
            "Un'esecuzione Autopilot è già in corso.",
            code="AUTOPILOT_RUN_ALREADY_ACTIVE",
        )

    run = PaperAutopilotRun(
        account_id=account_id,
        policy_id=policy.id,
        trigger=trigger,
        status="RUNNING",
        started_at=now,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _daily_entry_count(
    db: Session,
    account_id: int,
    now: datetime,
) -> int:
    day_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)
    return (
        db.query(PaperAutopilotDecision)
        .filter(
            PaperAutopilotDecision.account_id == account_id,
            PaperAutopilotDecision.action == "BUY",
            PaperAutopilotDecision.created_at >= day_start,
            PaperAutopilotDecision.created_at < day_end,
        )
        .count()
    )


def _token_is_on_cooldown(
    db: Session,
    account_id: int,
    token_mint: str,
    cooldown_hours: int,
    now: datetime,
) -> bool:
    if cooldown_hours <= 0:
        return False
    cutoff = now - timedelta(hours=cooldown_hours)
    return (
        db.query(PaperAutopilotDecision)
        .filter(
            PaperAutopilotDecision.account_id == account_id,
            PaperAutopilotDecision.token_mint == token_mint,
            PaperAutopilotDecision.action == "BUY",
            PaperAutopilotDecision.created_at >= cutoff,
        )
        .first()
        is not None
    )


def _signal_rejection(
    db: Session,
    account_id: int,
    policy: PaperAutopilotPolicy,
    signal: dict[str, Any],
    now: datetime,
) -> tuple[str, str] | None:
    token_mint = str(signal.get("token_mint") or "").strip()
    if not token_mint:
        return "INVALID_SIGNAL_TOKEN", "Il segnale non contiene un token mint."

    excluded = {str(item).strip() for item in (policy.excluded_token_mints or [])}
    if token_mint in excluded:
        return "TOKEN_EXCLUDED", "Token escluso dalla politica Autopilot."

    signal_score = _as_float(signal.get("signal_score"))
    if signal_score < float(policy.min_signal_score):
        return "SIGNAL_SCORE_TOO_LOW", "Signal score inferiore alla soglia."

    evidence_score = _as_float(signal.get("evidence_score"))
    if evidence_score < float(policy.min_evidence_score):
        return "EVIDENCE_SCORE_TOO_LOW", "Evidence score inferiore alla soglia."

    buyers = _as_int(signal.get("buyers"))
    if buyers < int(policy.min_buyers):
        return "BUYERS_TOO_LOW", "Numero di smart buyer insufficiente."

    confidence = str(signal.get("confidence") or "LOW").upper()
    minimum_confidence = str(policy.minimum_confidence or "HIGH").upper()
    if CONFIDENCE_RANK.get(confidence, 0) < CONFIDENCE_RANK.get(minimum_confidence, 3):
        return "CONFIDENCE_TOO_LOW", "Confidenza inferiore alla soglia."

    age_hours = _as_float(signal.get("age_hours"), default=10**9)
    if age_hours > float(policy.max_signal_age_hours):
        return "SIGNAL_TOO_OLD", "Segnale troppo vecchio."

    smart_share = _as_float(signal.get("smart_volume_share_percent"))
    if smart_share < float(policy.min_smart_volume_share_percent):
        return "SMART_VOLUME_SHARE_TOO_LOW", "Quota di volume smart insufficiente."

    concentration = _as_float(signal.get("volume_concentration_percent"), default=100.0)
    if concentration > float(policy.max_volume_concentration_percent):
        return "VOLUME_TOO_CONCENTRATED", "Volume troppo concentrato su pochi wallet."

    blocked_flags = {str(item).upper() for item in (policy.blocked_risk_flags or [])}
    signal_flags = {str(item).upper() for item in (signal.get("risk_flags") or [])}
    matching_flags = sorted(blocked_flags.intersection(signal_flags))
    if matching_flags:
        return (
            "BLOCKED_RISK_FLAG",
            "Risk flag bloccante: " + ", ".join(matching_flags),
        )

    existing_position = (
        db.query(PaperPosition)
        .filter(
            PaperPosition.account_id == account_id,
            PaperPosition.token_mint == token_mint,
            PaperPosition.status == "OPEN",
        )
        .first()
    )
    if existing_position is not None:
        return "POSITION_ALREADY_OPEN", "Esiste già una posizione aperta sul token."

    if _token_is_on_cooldown(
        db,
        account_id,
        token_mint,
        int(policy.token_cooldown_hours),
        now,
    ):
        return "TOKEN_COOLDOWN", "Il token è ancora nel periodo di cooldown."

    return None


def _calculate_order_size(
    account: PaperAccount,
    summary: dict[str, Any],
    policy: PaperAutopilotPolicy,
    signal: dict[str, Any],
) -> float:
    equity = max(_as_float(summary.get("equity_sol")), 0.0)
    cash = max(_as_float(summary.get("cash_balance_sol")), 0.0)
    market_value = max(_as_float(summary.get("market_value_sol")), 0.0)
    fee_multiplier = 1 + float(policy.fee_percent) / 100

    policy_position_limit = equity * float(policy.max_position_percent_of_equity) / 100
    account_position_limit = float(account.max_position_size_sol) / fee_multiplier
    exposure_limit = equity * float(policy.max_total_exposure_percent) / 100
    exposure_room = max(0.0, exposure_limit - market_value)
    reserve = equity * float(policy.minimum_cash_reserve_percent) / 100
    cash_room = max(0.0, cash - reserve) / fee_multiplier

    score_range = max(100.0 - float(policy.min_signal_score), 1.0)
    evidence_range = max(100.0 - float(policy.min_evidence_score), 1.0)
    score_strength = min(
        1.0,
        max(0.0, (_as_float(signal.get("signal_score")) - float(policy.min_signal_score)) / score_range),
    )
    evidence_strength = min(
        1.0,
        max(
            0.0,
            (_as_float(signal.get("evidence_score")) - float(policy.min_evidence_score))
            / evidence_range,
        ),
    )
    allocation_multiplier = 0.5 + 0.5 * ((score_strength + evidence_strength) / 2)

    base_limit = min(
        policy_position_limit,
        account_position_limit,
        exposure_room,
        cash_room,
    )
    return round(max(0.0, base_limit * allocation_multiplier), 12)


def _manage_exits(
    db: Session,
    oracle: JupiterPriceOracle,
    account: PaperAccount,
    policy: PaperAutopilotPolicy,
    run: PaperAutopilotRun,
    now: datetime,
) -> None:
    managed_positions = (
        db.query(PaperAutopilotManagedPosition)
        .filter(
            PaperAutopilotManagedPosition.account_id == account.id,
            PaperAutopilotManagedPosition.status == "ACTIVE",
        )
        .all()
    )
    if not managed_positions:
        return

    token_mints = list(dict.fromkeys(item.token_mint for item in managed_positions))
    try:
        batch = oracle.get_prices(token_mints, force_refresh=True)
    except PriceOracleError as exception:
        run.errors_count = int(run.errors_count or 0) + 1
        _record_decision(
            db,
            run,
            action="ERROR",
            reason_code=exception.code,
            reason=exception.message,
        )
        db.commit()
        return

    for managed in managed_positions:
        position = (
            db.query(PaperPosition)
            .filter(PaperPosition.id == managed.paper_position_id)
            .first()
        )
        if position is None or position.status != "OPEN" or float(position.quantity or 0.0) <= 0:
            managed.status = "CLOSED"
            managed.closed_at = now
            managed.exit_reason = "POSITION_ALREADY_CLOSED"
            _record_decision(
                db,
                run,
                action="SKIP",
                reason_code="POSITION_ALREADY_CLOSED",
                reason="La posizione è stata chiusa fuori dall'Autopilot.",
                token_mint=managed.token_mint,
                managed_position=managed,
                paper_position=position,
            )
            db.commit()
            continue

        quote = batch.prices.get(managed.token_mint)
        if quote is None:
            run.errors_count = int(run.errors_count or 0) + 1
            _record_decision(
                db,
                run,
                action="ERROR",
                reason_code="PRICE_NOT_AVAILABLE",
                reason="Prezzo non disponibile per una posizione gestita.",
                token_mint=managed.token_mint,
                managed_position=managed,
                paper_position=position,
            )
            db.commit()
            continue

        market_price = float(quote.sol_price)
        position.last_price_sol = market_price
        position.market_value_sol = float(position.quantity or 0.0) * market_price
        position.unrealized_pnl_sol = (
            float(position.market_value_sol or 0.0) - float(position.cost_basis_sol or 0.0)
        )
        managed.peak_price_sol = max(float(managed.peak_price_sol), market_price)

        fixed_stop = float(managed.stop_loss_price_sol)
        trailing_stop = fixed_stop
        if managed.trailing_stop_enabled and float(managed.peak_price_sol) > float(managed.entry_price_sol):
            trailing_stop = float(managed.peak_price_sol) * (
                1 - float(managed.trailing_stop_percent) / 100
            )
        effective_stop = max(fixed_stop, trailing_stop)

        exit_code: str | None = None
        exit_reason: str | None = None
        if market_price <= effective_stop:
            if trailing_stop > fixed_stop:
                exit_code = "TRAILING_STOP"
                exit_reason = "Prezzo sceso sotto il trailing stop."
            else:
                exit_code = "STOP_LOSS"
                exit_reason = "Prezzo sceso sotto lo stop loss."
        elif market_price >= float(managed.take_profit_price_sol):
            exit_code = "TAKE_PROFIT"
            exit_reason = "Prezzo arrivato al take profit."
        elif now >= (_to_utc(managed.max_holding_until) or now):
            exit_code = "MAX_HOLDING_TIME"
            exit_reason = "Tempo massimo di mantenimento raggiunto."

        if exit_code is None:
            _record_decision(
                db,
                run,
                action="HOLD",
                reason_code="EXIT_CONDITIONS_NOT_MET",
                reason="Nessuna condizione di uscita raggiunta.",
                token_mint=managed.token_mint,
                managed_position=managed,
                paper_position=position,
                market_price_sol=market_price,
                quantity=float(position.quantity or 0.0),
                value_sol=float(position.market_value_sol or 0.0),
            )
            db.commit()
            continue

        try:
            result = sell_paper_token_with_oracle(
                db=db,
                oracle=oracle,
                account_id=account.id,
                token_mint=managed.token_mint,
                quantity=None,
                slippage_percent=float(policy.slippage_percent),
                fee_percent=float(policy.fee_percent),
                signal_score=managed.entry_signal_score,
                reason=f"Autopilot: {exit_code}",
            )
        except (PaperTradingError, PriceOracleError) as exception:
            run.errors_count = int(run.errors_count or 0) + 1
            _record_decision(
                db,
                run,
                action="ERROR",
                reason_code=getattr(exception, "code", "EXIT_EXECUTION_ERROR"),
                reason=getattr(exception, "message", str(exception)),
                token_mint=managed.token_mint,
                managed_position=managed,
                paper_position=position,
                market_price_sol=market_price,
            )
            db.commit()
            continue

        sold_position = result["position"]
        order = result["order"]
        execution_price = float(result["price"]["sol_price"])
        managed.status = "CLOSED"
        managed.exit_order_id = order.id
        managed.exit_run_id = run.id
        managed.exit_reason = exit_code
        managed.closed_at = now
        run.exits_closed = int(run.exits_closed or 0) + 1
        _record_decision(
            db,
            run,
            action="SELL",
            reason_code=exit_code,
            reason=exit_reason or exit_code,
            token_mint=managed.token_mint,
            managed_position=managed,
            paper_position=sold_position,
            paper_order_id=order.id,
            market_price_sol=execution_price,
            quantity=float(order.quantity or 0.0),
            value_sol=float(order.gross_value_sol or 0.0),
        )
        db.commit()


def _evaluate_entries(
    db: Session,
    oracle: JupiterPriceOracle,
    account: PaperAccount,
    policy: PaperAutopilotPolicy,
    run: PaperAutopilotRun,
    now: datetime,
    signal_provider: Callable[..., dict[str, Any]],
) -> None:
    if account.status != "ACTIVE":
        _record_decision(
            db,
            run,
            action="SKIP",
            reason_code="ACCOUNT_NOT_ACTIVE",
            reason="Il conto non è ACTIVE: nuove entrate bloccate.",
        )
        db.commit()
        return

    if policy.status != "ENABLED":
        _record_decision(
            db,
            run,
            action="SKIP",
            reason_code="POLICY_NOT_ENABLED",
            reason="La politica non consente nuove entrate.",
        )
        db.commit()
        return

    summary = get_paper_account_summary(db, account.id)
    if float(summary["daily_loss_used_sol"]) >= float(summary["daily_loss_limit_sol"]):
        _record_decision(
            db,
            run,
            action="SKIP",
            reason_code="DAILY_LOSS_LIMIT",
            reason="Limite di perdita giornaliera raggiunto.",
        )
        db.commit()
        return

    daily_entries = _daily_entry_count(db, account.id, now)
    if daily_entries >= int(policy.max_entries_per_day):
        _record_decision(
            db,
            run,
            action="SKIP",
            reason_code="MAX_ENTRIES_PER_DAY",
            reason="Numero massimo di entrate giornaliere raggiunto.",
        )
        db.commit()
        return

    lookback_hours = max(1, int(ceil(float(policy.max_signal_age_hours))))
    payload = signal_provider(db, min_buyers=1, lookback_hours=lookback_hours)
    signals = list(payload.get("signals") or [])[: int(policy.max_signals_per_run)]

    entries_opened = 0
    for signal in signals:
        if entries_opened >= int(policy.max_entries_per_run):
            break
        if daily_entries + entries_opened >= int(policy.max_entries_per_day):
            break

        run.signals_evaluated = int(run.signals_evaluated or 0) + 1
        token_mint = str(signal.get("token_mint") or "").strip() or None
        rejection = _signal_rejection(db, account.id, policy, signal, now)
        if rejection is not None:
            reason_code, reason = rejection
            _record_decision(
                db,
                run,
                action="SKIP",
                reason_code=reason_code,
                reason=reason,
                token_mint=token_mint,
                signal=signal,
            )
            db.commit()
            continue

        summary = get_paper_account_summary(db, account.id)
        if int(summary["open_positions"]) >= int(summary["max_open_positions"]):
            _record_decision(
                db,
                run,
                action="SKIP",
                reason_code="MAX_OPEN_POSITIONS",
                reason="Numero massimo di posizioni aperte raggiunto.",
                token_mint=token_mint,
                signal=signal,
            )
            db.commit()
            break

        value_sol = _calculate_order_size(account, summary, policy, signal)
        if value_sol < float(policy.minimum_order_size_sol):
            _record_decision(
                db,
                run,
                action="SKIP",
                reason_code="ORDER_SIZE_TOO_SMALL",
                reason="Capitale disponibile inferiore all'ordine minimo.",
                token_mint=token_mint,
                signal=signal,
                value_sol=value_sol,
            )
            db.commit()
            continue

        try:
            result = buy_paper_token_with_oracle(
                db=db,
                oracle=oracle,
                account_id=account.id,
                token_mint=token_mint or "",
                value_sol=value_sol,
                slippage_percent=float(policy.slippage_percent),
                fee_percent=float(policy.fee_percent),
                signal_score=_as_float(signal.get("signal_score")),
                reason="Autopilot: segnale conforme alla politica",
            )
        except PaperTradingError as exception:
            _record_decision(
                db,
                run,
                action="SKIP",
                reason_code=exception.code,
                reason=exception.message,
                token_mint=token_mint,
                signal=signal,
                value_sol=value_sol,
            )
            db.commit()
            continue
        except PriceOracleError as exception:
            action = "SKIP" if exception.code in EXPECTED_PRICE_SKIP_CODES else "ERROR"
            if action == "ERROR":
                run.errors_count = int(run.errors_count or 0) + 1
            _record_decision(
                db,
                run,
                action=action,
                reason_code=exception.code,
                reason=exception.message,
                token_mint=token_mint,
                signal=signal,
                value_sol=value_sol,
            )
            db.commit()
            continue

        position = result["position"]
        order = result["order"]
        market_price = float(result["price"]["sol_price"])
        entry_price = float(position.average_entry_price_sol)
        managed = PaperAutopilotManagedPosition(
            account_id=account.id,
            paper_position_id=position.id,
            entry_order_id=order.id,
            entry_run_id=run.id,
            token_mint=token_mint or "",
            status="ACTIVE",
            entry_price_sol=entry_price,
            peak_price_sol=max(entry_price, market_price),
            stop_loss_price_sol=entry_price * (1 - float(policy.stop_loss_percent) / 100),
            take_profit_price_sol=entry_price * (1 + float(policy.take_profit_percent) / 100),
            trailing_stop_enabled=bool(policy.trailing_stop_enabled),
            trailing_stop_percent=float(policy.trailing_stop_percent),
            entry_signal_score=_as_float(signal.get("signal_score")),
            entry_evidence_score=_as_float(signal.get("evidence_score")),
            entry_confidence=str(signal.get("confidence") or "LOW").upper(),
            max_holding_until=now + timedelta(hours=int(policy.max_holding_hours)),
            opened_at=now,
        )
        db.add(managed)
        db.flush()
        run.entries_opened = int(run.entries_opened or 0) + 1
        entries_opened += 1
        _record_decision(
            db,
            run,
            action="BUY",
            reason_code="SIGNAL_ACCEPTED",
            reason="Segnale conforme a filtri, rischio e disponibilità di capitale.",
            token_mint=token_mint,
            managed_position=managed,
            paper_position=position,
            paper_order_id=order.id,
            signal=signal,
            market_price_sol=market_price,
            quantity=float(order.quantity or 0.0),
            value_sol=float(order.gross_value_sol or 0.0),
        )
        db.commit()

    if not signals:
        _record_decision(
            db,
            run,
            action="SKIP",
            reason_code="NO_SIGNALS",
            reason="Nessun segnale disponibile nel periodo configurato.",
        )
        db.commit()


def _finish_run(
    db: Session,
    policy: PaperAutopilotPolicy,
    run: PaperAutopilotRun,
    now: datetime,
) -> None:
    run.finished_at = now
    policy.last_run_at = now

    if int(run.errors_count or 0) > 0:
        run.status = "PARTIAL" if (
            int(run.entries_opened or 0) > 0 or int(run.exits_closed or 0) > 0
        ) else "FAILED"
        policy.consecutive_errors = int(policy.consecutive_errors or 0) + 1
        policy.last_error_at = now
        run.error_message = f"{run.errors_count} errore/i durante l'esecuzione."
        if int(policy.consecutive_errors) >= int(policy.max_consecutive_errors):
            policy.status = "PAUSED"
            policy.paused_reason = (
                f"Pausa automatica dopo {policy.consecutive_errors} esecuzioni con errori."
            )
    else:
        if run.status != "SKIPPED":
            run.status = "COMPLETED"
        policy.consecutive_errors = 0
        if policy.status == "ENABLED":
            policy.paused_reason = None

    db.commit()
    db.refresh(run)
    db.refresh(policy)


def run_paper_autopilot(
    db: Session,
    oracle: JupiterPriceOracle,
    account_id: int,
    trigger: str = "MANUAL",
    *,
    now: datetime | None = None,
    signal_provider: Callable[..., dict[str, Any]] = get_token_signals,
) -> dict[str, Any]:
    current_time = _to_utc(now) or utc_now()
    normalized_trigger = _normalize_trigger(trigger)
    account = get_paper_account(db, account_id)
    policy = get_or_create_autopilot_policy(db, account_id)
    run = _create_run(db, account_id, policy, normalized_trigger, current_time)

    try:
        if policy.status == "DISABLED":
            run.status = "SKIPPED"
            _record_decision(
                db,
                run,
                action="SKIP",
                reason_code="POLICY_DISABLED",
                reason="Autopilot disabilitato.",
            )
            db.commit()
        else:
            _manage_exits(db, oracle, account, policy, run, current_time)
            _evaluate_entries(
                db,
                oracle,
                account,
                policy,
                run,
                current_time,
                signal_provider,
            )

        _finish_run(db, policy, run, current_time)

    except Exception as exception:
        db.rollback()
        failed_run = db.query(PaperAutopilotRun).filter(PaperAutopilotRun.id == run.id).first()
        failed_policy = (
            db.query(PaperAutopilotPolicy)
            .filter(PaperAutopilotPolicy.id == policy.id)
            .first()
        )
        if failed_run is not None:
            failed_run.status = "FAILED"
            failed_run.finished_at = current_time
            failed_run.errors_count = max(int(failed_run.errors_count or 0), 1)
            failed_run.error_message = str(exception)[:2000]
        if failed_policy is not None:
            failed_policy.last_run_at = current_time
            failed_policy.last_error_at = current_time
            failed_policy.consecutive_errors = int(failed_policy.consecutive_errors or 0) + 1
            if int(failed_policy.consecutive_errors) >= int(failed_policy.max_consecutive_errors):
                failed_policy.status = "PAUSED"
                failed_policy.paused_reason = "Pausa automatica per errori consecutivi."
        db.commit()
        raise

    decisions = (
        db.query(PaperAutopilotDecision)
        .filter(PaperAutopilotDecision.run_id == run.id)
        .order_by(PaperAutopilotDecision.created_at.asc())
        .all()
    )
    managed_positions = list_managed_positions(db, account.id)
    return {
        "account": account,
        "policy": policy,
        "run": run,
        "decisions": decisions,
        "managed_positions": managed_positions,
        "summary": get_paper_account_summary(db, account.id),
    }
