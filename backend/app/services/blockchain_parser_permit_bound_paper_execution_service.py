from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserPaperExecutionPermit,
    CanonicalParserPermitBoundPaperExecution,
    CanonicalParserPermitBoundPaperExecutionEvent,
    CanonicalParserUnifiedDecisionResult,
    CanonicalParserUnifiedDecisionRun,
)
from backend.app.models.paper_order import PaperOrder
from backend.app.models.paper_position import PaperPosition
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    sanitize_error_message,
)
from backend.app.services.blockchain_parser_paper_execution_permit_service import (
    resolve_paper_execution_permit,
)
from backend.app.services.paper_trading_engine import (
    PaperTradingError,
    buy_paper_token,
    sell_paper_token,
)

PERMIT_BOUND_EXECUTION_POLICY_VERSION = "canonical-parser-permit-bound-paper-execution/1"
PERMIT_BOUND_EXECUTION_PREFIX = "EXECUTE_PERMIT_BOUND_PAPER"
PERMIT_BOUND_RECONCILE_PREFIX = "RECONCILE_PERMIT_BOUND_PAPER"
_MONEY_QUANTUM = Decimal("0.000000001")
_QUANTITY_QUANTUM = Decimal("0.000000000000000001")
_SCORE_QUANTUM = Decimal("0.0001")
_MAX_NOTE_LENGTH = 500


class CanonicalParserPermitBoundPaperExecutionError(ValueError):
    def __init__(self, message: str, *, code: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime:
    resolved = value or _utc_now()
    if resolved.tzinfo is None:
        return resolved.replace(tzinfo=timezone.utc)
    return resolved.astimezone(timezone.utc)


def _decimal(value: Any, *, quantum: Decimal = _MONEY_QUANTUM) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CanonicalParserPermitBoundPaperExecutionError(
            "Valore numerico non valido.", code="PAPER_EXECUTION_INVALID_NUMBER"
        ) from exc
    if not result.is_finite():
        raise CanonicalParserPermitBoundPaperExecutionError(
            "Valore numerico non finito.", code="PAPER_EXECUTION_INVALID_NUMBER"
        )
    return result.quantize(quantum)


def _money_text(value: Decimal | Any) -> str:
    return format(_decimal(value), "f")


def _quantity_text(value: Decimal | Any) -> str:
    return format(_decimal(value, quantum=_QUANTITY_QUANTUM), "f")


def _score_text(value: Decimal | Any) -> str:
    return format(_decimal(value, quantum=_SCORE_QUANTUM), "f")


def _actor(value: str | None) -> str:
    return sanitize_error_message(value or "LOCAL_PERMIT_BOUND_PAPER", max_length=80) or "LOCAL_PERMIT_BOUND_PAPER"


def _note(value: str | None) -> str | None:
    if not str(value or "").strip():
        return None
    return sanitize_error_message(value, max_length=_MAX_NOTE_LENGTH)


def _policy(settings_object: Any) -> dict[str, Any]:
    return {
        "policy_version": PERMIT_BOUND_EXECUTION_POLICY_VERSION,
        "reservation_timeout_minutes": int(
            getattr(settings_object, "CANONICAL_PARSER_PERMIT_BOUND_PAPER_EXECUTION_RESERVATION_TIMEOUT_MINUTES", 10)
        ),
        "maximum_slippage_percent": str(
            getattr(settings_object, "CANONICAL_PARSER_PERMIT_BOUND_PAPER_EXECUTION_MAX_SLIPPAGE_PERCENT", 5.0)
        ),
        "maximum_fee_percent": str(
            getattr(settings_object, "CANONICAL_PARSER_PERMIT_BOUND_PAPER_EXECUTION_MAX_FEE_PERCENT", 2.0)
        ),
        "maximum_decision_age_minutes": int(
            getattr(settings_object, "CANONICAL_PARSER_PERMIT_BOUND_PAPER_EXECUTION_MAX_DECISION_AGE_MINUTES", 30)
        ),
        "manual_only": True,
        "external_requests_allowed": False,
        "live_execution_authorized": False,
    }


def _serialize(row: CanonicalParserPermitBoundPaperExecution) -> dict[str, Any]:
    return {
        "execution_id": row.execution_id,
        "idempotency_key": row.idempotency_key,
        "permit_id": row.permit_id,
        "decision_result_id": row.decision_result_id,
        "decision_hash": row.decision_hash,
        "paper_account_id": row.paper_account_id,
        "paper_order_id": row.paper_order_id,
        "paper_position_id": row.paper_position_id,
        "side": row.side,
        "status": row.status,
        "token_mint": row.token_mint,
        "requested_budget_sol": _money_text(row.requested_budget_sol),
        "reserved_budget_sol": _money_text(row.reserved_budget_sol),
        "settled_budget_sol": _money_text(row.settled_budget_sol),
        "quantity": _quantity_text(row.quantity),
        "market_price_sol": _quantity_text(row.market_price_sol),
        "slippage_percent": _score_text(row.slippage_percent),
        "fee_percent": _score_text(row.fee_percent),
        "signal_score": _score_text(row.signal_score),
        "confidence_score": _score_text(row.confidence_score),
        "permit_budget_before_sol": _money_text(row.permit_budget_before_sol),
        "permit_order_count_before": row.permit_order_count_before,
        "reservation_hash": row.reservation_hash,
        "settlement_hash": row.settlement_hash,
        "failure_code": row.failure_code,
        "failure_message": row.failure_message,
        "actor_label": row.actor_label,
        "note": row.note,
        "reserved_at": row.reserved_at,
        "settled_at": row.settled_at,
        "released_at": row.released_at,
        "technical_metadata": row.technical_metadata,
    }


def _event_payload(
    row: CanonicalParserPermitBoundPaperExecution,
    *,
    event_type: str,
    sequence: int,
    occurred_at: datetime,
    previous_event_hash: str | None,
    details: dict[str, Any],
) -> dict[str, Any]:
    return {
        "execution_id": row.execution_id,
        "event_type": event_type,
        "sequence": sequence,
        "status": row.status,
        "permit_id": row.permit_id,
        "decision_result_id": row.decision_result_id,
        "paper_order_id": row.paper_order_id,
        "paper_position_id": row.paper_position_id,
        "reserved_budget_sol": _money_text(row.reserved_budget_sol),
        "settled_budget_sol": _money_text(row.settled_budget_sol),
        "quantity": _quantity_text(row.quantity),
        "previous_event_hash": previous_event_hash,
        "details": details,
        "occurred_at": occurred_at.isoformat(),
    }


def _append_event(
    db: Session,
    row: CanonicalParserPermitBoundPaperExecution,
    *,
    event_type: str,
    details: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> str:
    events = list(
        db.scalars(
            select(CanonicalParserPermitBoundPaperExecutionEvent)
            .where(CanonicalParserPermitBoundPaperExecutionEvent.execution_db_id == row.id)
            .order_by(CanonicalParserPermitBoundPaperExecutionEvent.sequence.asc())
        )
    )
    sequence = len(events) + 1
    previous_hash = events[-1].event_hash if events else None
    now = _aware(occurred_at)
    payload = _event_payload(
        row,
        event_type=event_type,
        sequence=sequence,
        occurred_at=now,
        previous_event_hash=previous_hash,
        details=details or {},
    )
    event_hash = calculate_payload_hash(payload)
    db.add(
        CanonicalParserPermitBoundPaperExecutionEvent(
            event_id=str(uuid4()),
            execution_db_id=row.id,
            sequence=sequence,
            event_type=event_type,
            event_payload=payload,
            previous_event_hash=previous_hash,
            event_hash=event_hash,
            occurred_at=now,
        )
    )
    return event_hash


def _verify_event_chain(db: Session, row: CanonicalParserPermitBoundPaperExecution) -> list[str]:
    events = list(
        db.scalars(
            select(CanonicalParserPermitBoundPaperExecutionEvent)
            .where(CanonicalParserPermitBoundPaperExecutionEvent.execution_db_id == row.id)
            .order_by(CanonicalParserPermitBoundPaperExecutionEvent.sequence.asc())
        )
    )
    reasons: list[str] = []
    previous: str | None = None
    for expected, event in enumerate(events, start=1):
        if event.sequence != expected:
            reasons.append("EXECUTION_EVENT_SEQUENCE_INVALID")
        if event.previous_event_hash != previous:
            reasons.append("EXECUTION_EVENT_CHAIN_INVALID")
        if calculate_payload_hash(event.event_payload) != event.event_hash:
            reasons.append("EXECUTION_EVENT_HASH_INVALID")
        previous = event.event_hash
    if not events:
        reasons.append("EXECUTION_EVENT_MISSING")
    return sorted(set(reasons))


def _calculate_decision_hash(result: CanonicalParserUnifiedDecisionResult) -> str:
    payload = {
        "token_mint": result.token_mint,
        "decision": result.decision,
        "signal_score": _score_text(result.signal_score),
        "confidence_score": _score_text(result.confidence_score),
        "uncertainty_score": _score_text(result.uncertainty_score),
        "requested_size_sol": _money_text(result.requested_size_sol),
        "approved_size_sol": _money_text(result.approved_size_sol),
        "token_safety_status": result.token_safety_status,
        "timing_status": result.timing_status,
        "reason_codes": sorted(result.reason_codes or []),
        "positive_factors": sorted(result.positive_factors or []),
        "evidence_snapshot": result.evidence_snapshot or {},
    }
    return calculate_payload_hash(payload)


def _load_decision(db: Session, result_id: str, *, now: datetime, policy: dict[str, Any]) -> tuple[CanonicalParserUnifiedDecisionResult, CanonicalParserUnifiedDecisionRun]:
    result = db.scalar(
        select(CanonicalParserUnifiedDecisionResult).where(
            CanonicalParserUnifiedDecisionResult.result_id == result_id
        )
    )
    if result is None:
        raise CanonicalParserPermitBoundPaperExecutionError(
            "Decisione M31 non trovata.", code="PAPER_EXECUTION_DECISION_NOT_FOUND", status_code=404
        )
    run = db.get(CanonicalParserUnifiedDecisionRun, result.run_db_id)
    if run is None:
        raise CanonicalParserPermitBoundPaperExecutionError(
            "Run M31 non trovato.", code="PAPER_EXECUTION_DECISION_RUN_NOT_FOUND", status_code=409
        )
    if result.decision != "APPROVE" or _decimal(result.approved_size_sol) <= 0:
        raise CanonicalParserPermitBoundPaperExecutionError(
            "Solo una decisione M31 APPROVE con size positiva può essere eseguita.",
            code="PAPER_EXECUTION_DECISION_NOT_APPROVED",
            status_code=409,
        )
    if _calculate_decision_hash(result) != result.decision_hash:
        raise CanonicalParserPermitBoundPaperExecutionError(
            "Hash della decisione M31 non valido.",
            code="PAPER_EXECUTION_DECISION_HASH_INVALID",
            status_code=409,
        )
    if not isinstance(result.exit_plan, dict) or not result.exit_plan:
        raise CanonicalParserPermitBoundPaperExecutionError(
            "La decisione M31 non contiene un piano di uscita valido.",
            code="PAPER_EXECUTION_EXIT_PLAN_REQUIRED",
            status_code=409,
        )
    if _aware(run.valid_until) <= now:
        raise CanonicalParserPermitBoundPaperExecutionError(
            "La decisione M31 è scaduta.", code="PAPER_EXECUTION_DECISION_EXPIRED", status_code=409
        )
    age = now - _aware(run.completed_at)
    if age > timedelta(minutes=int(policy["maximum_decision_age_minutes"])):
        raise CanonicalParserPermitBoundPaperExecutionError(
            "La decisione M31 è troppo vecchia per l'esecuzione PAPER.",
            code="PAPER_EXECUTION_DECISION_TOO_OLD",
            status_code=409,
        )
    if result.token_safety_status != "SAFE" or result.timing_status != "COPYABLE":
        raise CanonicalParserPermitBoundPaperExecutionError(
            "La decisione non conserva safety e timing necessari.",
            code="PAPER_EXECUTION_DECISION_GUARDS_FAILED",
            status_code=409,
        )
    return result, run


def _load_active_permit(
    db: Session,
    permit_id: str,
    *,
    now: datetime,
    settings_object: Any,
    lock: bool,
) -> CanonicalParserPaperExecutionPermit:
    query = select(CanonicalParserPaperExecutionPermit).where(
        CanonicalParserPaperExecutionPermit.permit_id == permit_id
    )
    if lock:
        query = query.with_for_update()
    permit = db.scalar(query)
    if permit is None:
        raise CanonicalParserPermitBoundPaperExecutionError(
            "Permit M30 non trovato.", code="PAPER_EXECUTION_PERMIT_NOT_FOUND", status_code=404
        )
    resolved = resolve_paper_execution_permit(db, settings_object=settings_object, evaluated_at=now)
    if resolved.get("permit_id") != permit_id or resolved.get("resolved_status") != "ACTIVE":
        raise CanonicalParserPermitBoundPaperExecutionError(
            "Permit M30 non attivo o non più coerente.", code="PAPER_EXECUTION_PERMIT_NOT_ACTIVE", status_code=409
        )
    return permit


def _validate_inputs(
    *,
    side: str,
    market_price_sol: Any,
    slippage_percent: Any,
    fee_percent: Any,
    idempotency_token: str,
    policy: dict[str, Any],
) -> tuple[str, Decimal, Decimal, Decimal, str]:
    normalized_side = str(side or "").strip().upper()
    if normalized_side not in {"BUY", "SELL"}:
        raise CanonicalParserPermitBoundPaperExecutionError(
            "side deve essere BUY o SELL.", code="PAPER_EXECUTION_INVALID_SIDE"
        )
    market_price = _decimal(market_price_sol, quantum=_QUANTITY_QUANTUM)
    if market_price <= 0:
        raise CanonicalParserPermitBoundPaperExecutionError(
            "market_price_sol deve essere positivo.", code="PAPER_EXECUTION_INVALID_PRICE"
        )
    slippage = _decimal(slippage_percent, quantum=_SCORE_QUANTUM)
    fee = _decimal(fee_percent, quantum=_SCORE_QUANTUM)
    if slippage < 0 or slippage > _decimal(policy["maximum_slippage_percent"], quantum=_SCORE_QUANTUM):
        raise CanonicalParserPermitBoundPaperExecutionError(
            "Slippage oltre il limite M32.", code="PAPER_EXECUTION_SLIPPAGE_LIMIT"
        )
    if fee < 0 or fee > _decimal(policy["maximum_fee_percent"], quantum=_SCORE_QUANTUM):
        raise CanonicalParserPermitBoundPaperExecutionError(
            "Fee oltre il limite M32.", code="PAPER_EXECUTION_FEE_LIMIT"
        )
    clean_token = str(idempotency_token or "").strip()
    if len(clean_token) < 8 or len(clean_token) > 200:
        raise CanonicalParserPermitBoundPaperExecutionError(
            "idempotency_token deve contenere 8-200 caratteri.", code="PAPER_EXECUTION_INVALID_IDEMPOTENCY_TOKEN"
        )
    return normalized_side, market_price, slippage, fee, clean_token


def preview_permit_bound_paper_execution(
    db: Session,
    *,
    permit_id: str,
    decision_result_id: str,
    side: str,
    market_price_sol: Any,
    slippage_percent: Any = 0.5,
    fee_percent: Any = 0.25,
    quantity: Any | None = None,
    idempotency_token: str = "preview-token",
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _policy(settings_object)
    normalized_side, market_price, slippage, fee, clean_token = _validate_inputs(
        side=side,
        market_price_sol=market_price_sol,
        slippage_percent=slippage_percent,
        fee_percent=fee_percent,
        idempotency_token=idempotency_token,
        policy=policy,
    )
    idempotency_key = calculate_payload_hash(
        {
            "permit_id": permit_id,
            "decision_result_id": decision_result_id,
            "side": normalized_side,
            "idempotency_token": clean_token,
        }
    )
    existing = db.scalar(
        select(CanonicalParserPermitBoundPaperExecution).where(
            CanonicalParserPermitBoundPaperExecution.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        return {
            "ready": False,
            "existing_execution": _serialize(existing),
            "idempotency_key": idempotency_key,
            "safety": {
                "manual_only": True,
                "idempotent_replay": True,
                "live_execution_authorized": False,
            },
        }
    decision, run = _load_decision(db, decision_result_id, now=now, policy=policy)
    permit = _load_active_permit(db, permit_id, now=now, settings_object=settings_object, lock=False)
    if permit.paper_account_id <= 0:
        raise CanonicalParserPermitBoundPaperExecutionError(
            "Account PAPER del permit non valido.", code="PAPER_EXECUTION_ACCOUNT_INVALID", status_code=409
        )
    remaining_budget = _decimal(permit.total_budget_sol) - _decimal(permit.consumed_budget_sol)
    remaining_orders = int(permit.max_order_count) - int(permit.consumed_order_count)
    if remaining_orders <= 0:
        raise CanonicalParserPermitBoundPaperExecutionError(
            "Numero massimo di ordini del permit raggiunto.", code="PAPER_EXECUTION_ORDER_LIMIT", status_code=409
        )
    if normalized_side == "BUY":
        requested_budget = _decimal(decision.approved_size_sol)
        reserved_budget = min(requested_budget, _decimal(permit.max_order_budget_sol), remaining_budget)
        if reserved_budget <= 0:
            raise CanonicalParserPermitBoundPaperExecutionError(
                "Budget permit insufficiente.", code="PAPER_EXECUTION_BUDGET_EXHAUSTED", status_code=409
            )
        resolved_quantity = Decimal("0")
    else:
        requested_budget = Decimal("0")
        reserved_budget = Decimal("0")
        position = db.scalar(
            select(PaperPosition).where(
                PaperPosition.account_id == permit.paper_account_id,
                PaperPosition.token_mint == decision.token_mint,
                PaperPosition.status == "OPEN",
            )
        )
        if position is None or Decimal(str(position.quantity or 0)) <= 0:
            raise CanonicalParserPermitBoundPaperExecutionError(
                "Posizione PAPER aperta non trovata per la vendita.",
                code="PAPER_EXECUTION_POSITION_NOT_FOUND",
                status_code=409,
            )
        resolved_quantity = _decimal(quantity if quantity is not None else position.quantity, quantum=_QUANTITY_QUANTUM)
        if resolved_quantity <= 0 or resolved_quantity > _decimal(position.quantity, quantum=_QUANTITY_QUANTUM):
            raise CanonicalParserPermitBoundPaperExecutionError(
                "Quantità SELL non valida.", code="PAPER_EXECUTION_INVALID_QUANTITY", status_code=409
            )
    return {
        "ready": True,
        "existing_execution": None,
        "permit_id": permit_id,
        "decision_result_id": decision_result_id,
        "decision_run_id": run.run_id,
        "decision_hash": decision.decision_hash,
        "paper_account_id": permit.paper_account_id,
        "side": normalized_side,
        "token_mint": decision.token_mint,
        "requested_budget_sol": _money_text(requested_budget),
        "reserved_budget_sol": _money_text(reserved_budget),
        "quantity": _quantity_text(resolved_quantity),
        "market_price_sol": _quantity_text(market_price),
        "slippage_percent": _score_text(slippage),
        "fee_percent": _score_text(fee),
        "remaining_permit_budget_sol": _money_text(remaining_budget),
        "remaining_permit_order_count": remaining_orders,
        "idempotency_key": idempotency_key,
        "confirmation": f"{PERMIT_BOUND_EXECUTION_PREFIX}:{permit_id}:{decision_result_id}:{normalized_side}:{idempotency_key}",
        "policy": policy,
        "safety": {
            "manual_only": True,
            "external_requests_allowed": False,
            "market_price_supplied_by_caller": True,
            "paper_execution_only": True,
            "live_execution_authorized": False,
        },
    }


def _release_reservation(
    db: Session,
    execution_id: str,
    *,
    failure_code: str,
    failure_message: str,
    status: str = "RELEASED",
) -> CanonicalParserPermitBoundPaperExecution:
    row = db.scalar(
        select(CanonicalParserPermitBoundPaperExecution)
        .where(CanonicalParserPermitBoundPaperExecution.execution_id == execution_id)
        .with_for_update()
    )
    if row is None:
        raise CanonicalParserPermitBoundPaperExecutionError(
            "Esecuzione M32 non trovata.", code="PAPER_EXECUTION_NOT_FOUND", status_code=404
        )
    if row.status not in {"RESERVED", "RECONCILIATION_REQUIRED"}:
        return row
    permit = db.scalar(
        select(CanonicalParserPaperExecutionPermit)
        .where(CanonicalParserPaperExecutionPermit.id == row.permit_db_id)
        .with_for_update()
    )
    if permit is not None:
        permit.consumed_budget_sol = max(
            Decimal("0"), _decimal(permit.consumed_budget_sol) - _decimal(row.reserved_budget_sol)
        )
        permit.consumed_order_count = max(0, int(permit.consumed_order_count) - 1)
    row.status = status
    row.failure_code = failure_code
    row.failure_message = sanitize_error_message(failure_message, max_length=500)
    row.released_at = _utc_now()
    _append_event(
        db,
        row,
        event_type=status,
        details={"failure_code": row.failure_code, "failure_message": row.failure_message},
    )
    db.commit()
    db.refresh(row)
    return row


def _mark_reconciliation_required(
    db: Session,
    execution_id: str,
    *,
    failure_code: str,
    failure_message: str,
) -> CanonicalParserPermitBoundPaperExecution:
    row = db.scalar(
        select(CanonicalParserPermitBoundPaperExecution)
        .where(CanonicalParserPermitBoundPaperExecution.execution_id == execution_id)
        .with_for_update()
    )
    if row is None:
        raise CanonicalParserPermitBoundPaperExecutionError(
            "Esecuzione M32 non trovata.", code="PAPER_EXECUTION_NOT_FOUND", status_code=404
        )
    if row.status not in {"RESERVED", "RECONCILIATION_REQUIRED"}:
        return row
    row.status = "RECONCILIATION_REQUIRED"
    row.failure_code = failure_code
    row.failure_message = sanitize_error_message(failure_message, max_length=500)
    _append_event(
        db,
        row,
        event_type="RECONCILIATION_REQUIRED",
        details={
            "failure_code": row.failure_code,
            "failure_message": row.failure_message,
            "reservation_retained": True,
        },
    )
    db.commit()
    db.refresh(row)
    return row


def execute_permit_bound_paper(
    db: Session,
    *,
    permit_id: str,
    decision_result_id: str,
    side: str,
    market_price_sol: Any,
    idempotency_token: str,
    confirmation: str,
    quantity: Any | None = None,
    slippage_percent: Any = 0.5,
    fee_percent: Any = 0.25,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    executed_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_PERMIT_BOUND_PAPER_EXECUTION_ENABLED", False)):
        raise CanonicalParserPermitBoundPaperExecutionError(
            "M32 è disabilitata. Il flag resta false di default.",
            code="PAPER_EXECUTION_DISABLED",
            status_code=409,
        )
    now = _aware(executed_at)
    preview = preview_permit_bound_paper_execution(
        db,
        permit_id=permit_id,
        decision_result_id=decision_result_id,
        side=side,
        market_price_sol=market_price_sol,
        slippage_percent=slippage_percent,
        fee_percent=fee_percent,
        quantity=quantity,
        idempotency_token=idempotency_token,
        settings_object=settings_object,
        evaluated_at=now,
    )
    if preview["existing_execution"] is not None:
        return preview["existing_execution"]
    expected = preview["confirmation"]
    if confirmation != expected:
        raise CanonicalParserPermitBoundPaperExecutionError(
            "Conferma M32 non valida.", code="PAPER_EXECUTION_CONFIRMATION_REQUIRED", status_code=409
        )

    permit = _load_active_permit(db, permit_id, now=now, settings_object=settings_object, lock=True)
    decision, _ = _load_decision(db, decision_result_id, now=now, policy=preview["policy"])
    existing = db.scalar(
        select(CanonicalParserPermitBoundPaperExecution).where(
            CanonicalParserPermitBoundPaperExecution.idempotency_key == preview["idempotency_key"]
        )
    )
    if existing is not None:
        return _serialize(existing)

    reserved_budget = _decimal(preview["reserved_budget_sol"])
    if int(permit.consumed_order_count) >= int(permit.max_order_count):
        raise CanonicalParserPermitBoundPaperExecutionError(
            "Limite ordini permit raggiunto durante la reservation.",
            code="PAPER_EXECUTION_ORDER_LIMIT",
            status_code=409,
        )
    if _decimal(permit.consumed_budget_sol) + reserved_budget > _decimal(permit.total_budget_sol):
        raise CanonicalParserPermitBoundPaperExecutionError(
            "Budget permit esaurito durante la reservation.",
            code="PAPER_EXECUTION_BUDGET_EXHAUSTED",
            status_code=409,
        )

    execution_id = str(uuid4())
    reservation_payload = {
        "execution_id": execution_id,
        "permit_id": permit_id,
        "decision_result_id": decision_result_id,
        "decision_hash": decision.decision_hash,
        "side": preview["side"],
        "token_mint": decision.token_mint,
        "reserved_budget_sol": preview["reserved_budget_sol"],
        "quantity": preview["quantity"],
        "market_price_sol": preview["market_price_sol"],
        "idempotency_key": preview["idempotency_key"],
        "reserved_at": now.isoformat(),
    }
    reservation_hash = calculate_payload_hash(reservation_payload)
    row = CanonicalParserPermitBoundPaperExecution(
        execution_id=execution_id,
        idempotency_key=preview["idempotency_key"],
        permit_db_id=permit.id,
        permit_id=permit.permit_id,
        decision_result_db_id=decision.id,
        decision_result_id=decision.result_id,
        decision_hash=decision.decision_hash,
        paper_account_id=permit.paper_account_id,
        paper_order_id=None,
        paper_position_id=None,
        side=preview["side"],
        status="RESERVED",
        token_mint=decision.token_mint,
        requested_budget_sol=_decimal(preview["requested_budget_sol"]),
        reserved_budget_sol=reserved_budget,
        settled_budget_sol=Decimal("0"),
        quantity=_decimal(preview["quantity"], quantum=_QUANTITY_QUANTUM),
        market_price_sol=_decimal(preview["market_price_sol"], quantum=_QUANTITY_QUANTUM),
        slippage_percent=_decimal(preview["slippage_percent"], quantum=_SCORE_QUANTUM),
        fee_percent=_decimal(preview["fee_percent"], quantum=_SCORE_QUANTUM),
        signal_score=_decimal(decision.signal_score, quantum=_SCORE_QUANTUM),
        confidence_score=_decimal(decision.confidence_score, quantum=_SCORE_QUANTUM),
        permit_budget_before_sol=_decimal(permit.consumed_budget_sol),
        permit_order_count_before=int(permit.consumed_order_count),
        reservation_hash=reservation_hash,
        settlement_hash=None,
        failure_code=None,
        failure_message=None,
        actor_label=_actor(actor_label),
        note=_note(note),
        reserved_at=now,
        settled_at=None,
        released_at=None,
        technical_metadata={
            "manual_only": True,
            "external_requests": 0,
            "paper_execution_connected": True,
            "permit_consumption_connected": True,
            "live_execution_authorized": False,
            "order_reason_marker": f"[M32:{execution_id}]",
        },
    )
    db.add(row)
    permit.consumed_budget_sol = _decimal(permit.consumed_budget_sol) + reserved_budget
    permit.consumed_order_count = int(permit.consumed_order_count) + 1
    try:
        db.flush()
        _append_event(db, row, event_type="RESERVED", details=reservation_payload, occurred_at=now)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.scalar(
            select(CanonicalParserPermitBoundPaperExecution).where(
                CanonicalParserPermitBoundPaperExecution.idempotency_key == preview["idempotency_key"]
            )
        )
        if duplicate is not None:
            return _serialize(duplicate)
        raise CanonicalParserPermitBoundPaperExecutionError(
            "Conflitto idempotenza M32.", code="PAPER_EXECUTION_IDEMPOTENCY_CONFLICT", status_code=409
        ) from exc

    reason = f"[M32:{execution_id}] permit={permit_id} decision={decision_result_id}"
    if row.note:
        reason = f"{reason} {row.note}"
    try:
        if row.side == "BUY":
            result = buy_paper_token(
                db=db,
                account_id=row.paper_account_id,
                token_mint=row.token_mint,
                value_sol=float(row.reserved_budget_sol),
                market_price_sol=float(row.market_price_sol),
                slippage_percent=float(row.slippage_percent),
                fee_percent=float(row.fee_percent),
                signal_score=float(row.signal_score),
                reason=reason,
            )
        else:
            result = sell_paper_token(
                db=db,
                account_id=row.paper_account_id,
                token_mint=row.token_mint,
                market_price_sol=float(row.market_price_sol),
                quantity=float(row.quantity),
                slippage_percent=float(row.slippage_percent),
                fee_percent=float(row.fee_percent),
                signal_score=float(row.signal_score),
                reason=reason,
            )
    except PaperTradingError as exc:
        released = _release_reservation(
            db,
            execution_id,
            failure_code=exc.code,
            failure_message=exc.message,
            status="RELEASED",
        )
        raise CanonicalParserPermitBoundPaperExecutionError(
            exc.message, code=f"PAPER_ENGINE_{exc.code}", status_code=409
        ) from exc
    except Exception as exc:
        # Fail closed: an unexpected error could occur after the PAPER engine
        # committed an order. Keep the reservation and require explicit
        # reconciliation instead of releasing budget and risking a duplicate.
        _mark_reconciliation_required(
            db,
            execution_id,
            failure_code="PAPER_ENGINE_UNEXPECTED_ERROR",
            failure_message=str(exc),
        )
        raise

    row = db.scalar(
        select(CanonicalParserPermitBoundPaperExecution)
        .where(CanonicalParserPermitBoundPaperExecution.execution_id == execution_id)
        .with_for_update()
    )
    order: PaperOrder = result["order"]
    position: PaperPosition = result["position"]
    row.paper_order_id = order.id
    row.paper_position_id = position.id
    row.quantity = _decimal(order.quantity, quantum=_QUANTITY_QUANTUM)
    row.settled_budget_sol = _decimal(row.reserved_budget_sol if row.side == "BUY" else 0)
    row.status = "SETTLED"
    row.settled_at = _utc_now()
    settlement_payload = {
        "execution_id": row.execution_id,
        "paper_order_id": order.id,
        "paper_position_id": position.id,
        "side": row.side,
        "quantity": _quantity_text(row.quantity),
        "settled_budget_sol": _money_text(row.settled_budget_sol),
        "execution_price_sol": _quantity_text(order.execution_price_sol),
        "fee_sol": _money_text(order.fee_sol),
        "realized_pnl_sol": _money_text(order.realized_pnl_sol),
        "settled_at": row.settled_at.isoformat(),
    }
    row.settlement_hash = calculate_payload_hash(settlement_payload)
    _append_event(db, row, event_type="SETTLED", details=settlement_payload, occurred_at=row.settled_at)
    db.commit()
    db.refresh(row)
    payload = _serialize(row)
    payload["paper_order"] = {
        "id": order.id,
        "side": order.side,
        "status": order.status,
        "quantity": order.quantity,
        "execution_price_sol": order.execution_price_sol,
        "gross_value_sol": order.gross_value_sol,
        "fee_sol": order.fee_sol,
        "realized_pnl_sol": order.realized_pnl_sol,
    }
    return payload


def get_permit_bound_paper_execution(db: Session, execution_id: str) -> dict[str, Any]:
    row = db.scalar(
        select(CanonicalParserPermitBoundPaperExecution).where(
            CanonicalParserPermitBoundPaperExecution.execution_id == execution_id
        )
    )
    if row is None:
        raise CanonicalParserPermitBoundPaperExecutionError(
            "Esecuzione M32 non trovata.", code="PAPER_EXECUTION_NOT_FOUND", status_code=404
        )
    payload = _serialize(row)
    payload["audit_reason_codes"] = _verify_event_chain(db, row)
    payload["events"] = [
        {
            "sequence": event.sequence,
            "event_type": event.event_type,
            "event_hash": event.event_hash,
            "previous_event_hash": event.previous_event_hash,
            "occurred_at": event.occurred_at,
        }
        for event in db.scalars(
            select(CanonicalParserPermitBoundPaperExecutionEvent)
            .where(CanonicalParserPermitBoundPaperExecutionEvent.execution_db_id == row.id)
            .order_by(CanonicalParserPermitBoundPaperExecutionEvent.sequence.asc())
        )
    ]
    return payload


def reconcile_permit_bound_paper_execution(
    db: Session,
    *,
    execution_id: str,
    confirmation: str,
    actor_label: str | None = None,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    row = db.scalar(
        select(CanonicalParserPermitBoundPaperExecution)
        .where(CanonicalParserPermitBoundPaperExecution.execution_id == execution_id)
        .with_for_update()
    )
    if row is None:
        raise CanonicalParserPermitBoundPaperExecutionError(
            "Esecuzione M32 non trovata.", code="PAPER_EXECUTION_NOT_FOUND", status_code=404
        )
    expected = f"{PERMIT_BOUND_RECONCILE_PREFIX}:{execution_id}:{row.reservation_hash}"
    if confirmation != expected:
        raise CanonicalParserPermitBoundPaperExecutionError(
            "Conferma reconciliation M32 non valida.", code="PAPER_EXECUTION_RECONCILE_CONFIRMATION_REQUIRED", status_code=409
        )
    if row.status in {"SETTLED", "RELEASED", "FAILED"}:
        return _serialize(row)
    marker = f"[M32:{execution_id}]"
    order = db.scalar(
        select(PaperOrder)
        .where(PaperOrder.account_id == row.paper_account_id, PaperOrder.reason.contains(marker))
        .order_by(PaperOrder.id.desc())
        .limit(1)
    )
    now = _aware(evaluated_at)
    if order is not None:
        row.paper_order_id = order.id
        row.paper_position_id = order.position_id
        row.quantity = _decimal(order.quantity, quantum=_QUANTITY_QUANTUM)
        row.settled_budget_sol = _decimal(row.reserved_budget_sol if row.side == "BUY" else 0)
        row.status = "SETTLED"
        row.settled_at = now
        settlement_payload = {
            "execution_id": execution_id,
            "reconciled": True,
            "paper_order_id": order.id,
            "paper_position_id": order.position_id,
            "quantity": _quantity_text(row.quantity),
            "settled_budget_sol": _money_text(row.settled_budget_sol),
            "actor_label": _actor(actor_label),
            "settled_at": now.isoformat(),
        }
        row.settlement_hash = calculate_payload_hash(settlement_payload)
        _append_event(db, row, event_type="SETTLED", details=settlement_payload, occurred_at=now)
        db.commit()
        db.refresh(row)
        return _serialize(row)
    timeout = timedelta(minutes=int(_policy(settings_object)["reservation_timeout_minutes"]))
    if now - _aware(row.reserved_at) >= timeout:
        return _serialize(
            _release_reservation(
                db,
                execution_id,
                failure_code="RESERVATION_TIMEOUT_WITHOUT_ORDER",
                failure_message="Reservation scaduta senza PaperOrder riconciliabile.",
                status="RELEASED",
            )
        )
    row.status = "RECONCILIATION_REQUIRED"
    row.failure_code = "ORDER_NOT_YET_VISIBLE"
    row.failure_message = "PaperOrder non ancora disponibile; reservation mantenuta."
    _append_event(
        db,
        row,
        event_type="RECONCILIATION_REQUIRED",
        details={"actor_label": _actor(actor_label), "retry_after_minutes": int(_policy(settings_object)["reservation_timeout_minutes"])},
        occurred_at=now,
    )
    db.commit()
    db.refresh(row)
    return _serialize(row)


def resolve_permit_bound_paper_execution(db: Session, *, paper_account_id: int | None = None) -> dict[str, Any]:
    query = select(CanonicalParserPermitBoundPaperExecution)
    if paper_account_id is not None:
        query = query.where(CanonicalParserPermitBoundPaperExecution.paper_account_id == paper_account_id)
    latest = db.scalar(query.order_by(CanonicalParserPermitBoundPaperExecution.created_at.desc()).limit(1))
    return {
        "resolved_status": "EMPTY" if latest is None else latest.status,
        "latest_execution": None if latest is None else _serialize(latest),
    }


def get_permit_bound_paper_execution_status(db: Session, *, settings_object: Any = settings) -> dict[str, Any]:
    counts = {
        status: int(
            db.scalar(
                select(func.count(CanonicalParserPermitBoundPaperExecution.id)).where(
                    CanonicalParserPermitBoundPaperExecution.status == status
                )
            )
            or 0
        )
        for status in ("RESERVED", "SETTLED", "RELEASED", "FAILED", "RECONCILIATION_REQUIRED")
    }
    return {
        "enabled": bool(getattr(settings_object, "CANONICAL_PARSER_PERMIT_BOUND_PAPER_EXECUTION_ENABLED", False)),
        "policy": _policy(settings_object),
        "execution_counts": counts,
        "total_execution_count": sum(counts.values()),
        "operational_guards": {
            "manual_only": True,
            "permit_m30_required": True,
            "decision_m31_approve_required": True,
            "idempotency_required": True,
            "reservation_ledger_connected": True,
            "paper_order_writes": True,
            "paper_position_writes": True,
            "trade_writes": False,
            "external_requests_allowed": False,
            "workers_started": False,
            "schedulers_started": False,
            "streams_started": False,
            "live_execution_authorized": False,
        },
    }
