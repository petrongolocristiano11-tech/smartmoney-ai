from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserGovernedLiveExitIntent,
    CanonicalParserGovernedLiveExitIntentEvent,
    CanonicalParserGovernedLivePosition,
    CanonicalParserGovernedLivePositionAssessment,
    CanonicalParserMicroLiveCanaryPermit,
)
from backend.app.services.blockchain_integrity_service import calculate_payload_hash

POLICY_VERSION = "canonical-parser-governed-live-position-lifecycle/1"
ASSESS_PREFIX = "ASSESS_M40_GOVERNED_LIVE_POSITION"
ISSUE_PREFIX = "ISSUE_M40_GOVERNED_LIVE_EXIT"
REVOKE_PREFIX = "REVOKE_M40_GOVERNED_LIVE_EXIT"
_MONEY = Decimal("0.000000001")
_PERCENT = Decimal("0.0001")


class CanonicalParserGovernedLivePositionError(ValueError):
    def __init__(self, message: str, *, code: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime:
    value = value or _now()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CanonicalParserGovernedLivePositionError("Valore M40 non valido.", code="M40_INVALID_NUMBER") from exc
    if not result.is_finite():
        raise CanonicalParserGovernedLivePositionError("Valore M40 non finito.", code="M40_INVALID_NUMBER")
    return result


def _money(value: Any) -> Decimal:
    return _decimal(value).quantize(_MONEY)


def _pct(value: Any) -> Decimal:
    return _decimal(value).quantize(_PERCENT)


def _actor(value: str | None) -> str:
    return str(value or "MANUAL_OPERATOR").strip()[:80] or "MANUAL_OPERATOR"


def _note(value: str | None) -> str | None:
    value = str(value or "").strip()
    return value[:500] if value else None


def _policy(settings_object: Any = settings) -> dict[str, Any]:
    return {
        "version": POLICY_VERSION,
        "enabled": bool(getattr(settings_object, "CANONICAL_PARSER_GOVERNED_LIVE_POSITION_ENABLED", False)),
        "maximum_quote_age_seconds": int(getattr(settings_object, "CANONICAL_PARSER_GOVERNED_LIVE_POSITION_MAX_QUOTE_AGE_SECONDS", 30)),
        "assessment_ttl_seconds": int(getattr(settings_object, "CANONICAL_PARSER_GOVERNED_LIVE_POSITION_ASSESSMENT_TTL_SECONDS", 30)),
        "maximum_intent_validity_minutes": int(getattr(settings_object, "CANONICAL_PARSER_GOVERNED_LIVE_POSITION_MAX_INTENT_VALIDITY_MINUTES", 10)),
        "stop_loss_percent": _pct(getattr(settings_object, "CANONICAL_PARSER_GOVERNED_LIVE_POSITION_STOP_LOSS_PERCENT", 10)),
        "take_profit_percent": _pct(getattr(settings_object, "CANONICAL_PARSER_GOVERNED_LIVE_POSITION_TAKE_PROFIT_PERCENT", 25)),
        "trailing_stop_percent": _pct(getattr(settings_object, "CANONICAL_PARSER_GOVERNED_LIVE_POSITION_TRAILING_STOP_PERCENT", 8)),
        "maximum_position_age_minutes": int(getattr(settings_object, "CANONICAL_PARSER_GOVERNED_LIVE_POSITION_MAX_AGE_MINUTES", 1440)),
        "maximum_exit_price_impact_percent": _pct(getattr(settings_object, "CANONICAL_PARSER_GOVERNED_LIVE_POSITION_MAX_EXIT_PRICE_IMPACT_PERCENT", 10)),
        "manual_only": True,
        "automatic_exit": False,
        "transaction_build": False,
        "transaction_send": False,
    }


def _position(db: Session, position_id: str, *, lock: bool = False) -> CanonicalParserGovernedLivePosition:
    query = select(CanonicalParserGovernedLivePosition).where(CanonicalParserGovernedLivePosition.position_id == position_id)
    if lock:
        query = query.with_for_update()
    row = db.scalar(query)
    if row is None:
        raise CanonicalParserGovernedLivePositionError("Posizione M39 non trovata.", code="M40_POSITION_NOT_FOUND", status_code=404)
    return row


def _resolved_intent_status(row: CanonicalParserGovernedLiveExitIntent, now: datetime) -> str:
    if row.status == "ACTIVE" and _aware(row.expires_at) <= now:
        return "EXPIRED"
    return row.status


def _serialize_assessment(row: CanonicalParserGovernedLivePositionAssessment) -> dict[str, Any]:
    return {
        "assessment_id": row.assessment_id, "position_id": row.position_id, "status": row.status,
        "quoted_output_sol": format(_money(row.quoted_output_sol), "f"), "current_value_sol": format(_money(row.current_value_sol), "f"),
        "unrealized_pnl_sol": format(_money(row.unrealized_pnl_sol), "f"), "unrealized_roi_percent": str(row.unrealized_roi_percent),
        "high_watermark_value_sol": format(_money(row.high_watermark_value_sol), "f"), "high_watermark_roi_percent": str(row.high_watermark_roi_percent),
        "trailing_drawdown_percent": str(row.trailing_drawdown_percent), "price_impact_percent": str(row.price_impact_percent),
        "sell_route_available": row.sell_route_available, "token_safety_status": row.token_safety_status,
        "source_wallet_sell_detected": row.source_wallet_sell_detected, "emergency_exit_requested": row.emergency_exit_requested,
        "reason_codes": row.reason_codes, "evidence_hash": row.evidence_hash, "quote_observed_at": row.quote_observed_at,
        "assessed_at": row.assessed_at, "expires_at": row.expires_at,
    }


def _serialize_intent(row: CanonicalParserGovernedLiveExitIntent, *, now: datetime | None = None) -> dict[str, Any]:
    resolved = _resolved_intent_status(row, _aware(now))
    return {
        "intent_id": row.intent_id, "position_id": row.position_id, "assessment_id": row.assessment_id,
        "micro_live_permit_id": row.micro_live_permit_id, "decision_result_id": row.decision_result_id,
        "status": row.status, "resolved_status": resolved, "reason_code": row.reason_code,
        "quantity_raw": str(row.quantity_raw), "percentage": str(row.percentage),
        "expected_output_sol": format(_money(row.expected_output_sol), "f"), "minimum_output_sol": format(_money(row.minimum_output_sol), "f"),
        "intent_snapshot": row.intent_snapshot, "evidence_hash": row.evidence_hash,
        "issued_at": row.issued_at, "expires_at": row.expires_at, "revoked_at": row.revoked_at, "consumed_at": row.consumed_at,
        "latest_event_sequence": row.latest_event_sequence, "latest_event_hash": row.latest_event_hash,
    }


def _append_event(db: Session, row: CanonicalParserGovernedLiveExitIntent, *, event_type: str, payload: dict[str, Any], at: datetime) -> None:
    previous_hash = row.latest_event_hash if row.latest_event_sequence else None
    sequence = int(row.latest_event_sequence or 0) + 1
    event_payload = {"intent_id": row.intent_id, "sequence": sequence, "event_type": event_type, "occurred_at": at.isoformat(), "payload": payload, "previous_event_hash": previous_hash}
    event_hash = calculate_payload_hash(event_payload)
    db.add(CanonicalParserGovernedLiveExitIntentEvent(
        event_id=str(uuid4()), intent_db_id=row.id, sequence=sequence, event_type=event_type,
        event_payload=event_payload, previous_event_hash=previous_hash, event_hash=event_hash, occurred_at=at,
    ))
    row.latest_event_sequence = sequence
    row.latest_event_hash = event_hash


def preview_governed_live_position_assessment(
    db: Session, *, position_id: str, quoted_output_sol: Any, price_impact_percent: Any,
    sell_route_available: bool, token_safety_status: str, source_wallet_sell_detected: bool,
    emergency_exit_requested: bool, quote_observed_at: datetime, idempotency_token: str,
    settings_object: Any = settings, evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    quote_time = _aware(quote_observed_at)
    policy = _policy(settings_object)
    position = _position(db, position_id)
    quoted = _money(quoted_output_sol)
    impact = _pct(price_impact_percent)
    safety = str(token_safety_status or "UNKNOWN").strip().upper()
    if safety not in {"SAFE", "REVIEW", "UNSAFE", "UNKNOWN"}:
        raise CanonicalParserGovernedLivePositionError("Token safety M40 non valida.", code="M40_TOKEN_SAFETY_INVALID")
    token = str(idempotency_token or "").strip()
    if len(token) < 8:
        raise CanonicalParserGovernedLivePositionError("Idempotency token M40 non valido.", code="M40_IDEMPOTENCY_INVALID")
    reasons: list[str] = []
    if position.status != "OPEN" or _decimal(position.quantity_raw) <= 0:
        reasons.append("POSITION_NOT_OPEN")
    if quote_time > now + timedelta(seconds=5):
        reasons.append("QUOTE_FROM_FUTURE")
    if now - quote_time > timedelta(seconds=policy["maximum_quote_age_seconds"]):
        reasons.append("QUOTE_STALE")
    if quoted <= 0:
        reasons.append("QUOTE_VALUE_INVALID")
    cost = _money(position.cost_basis_sol)
    pnl = _money(quoted - cost)
    roi = _pct((pnl * Decimal(100) / cost) if cost > 0 else Decimal(0))
    previous_high = _money(position.high_watermark_value_sol or cost)
    high = max(previous_high, quoted)
    high_roi = _pct(((high - cost) * Decimal(100) / cost) if cost > 0 else Decimal(0))
    drawdown = _pct(((high - quoted) * Decimal(100) / high) if high > 0 else Decimal(0))
    age_minutes = (now - _aware(position.opened_at)).total_seconds() / 60
    if not sell_route_available:
        reasons.append("SELL_ROUTE_UNAVAILABLE")
    if safety == "UNSAFE":
        reasons.append("TOKEN_UNSAFE")
    elif safety in {"REVIEW", "UNKNOWN"}:
        reasons.append("TOKEN_SAFETY_UNCERTAIN")
    if impact > policy["maximum_exit_price_impact_percent"]:
        reasons.append("EXIT_PRICE_IMPACT_HIGH")
    if emergency_exit_requested:
        reasons.append("EMERGENCY_EXIT_REQUESTED")
    if source_wallet_sell_detected:
        reasons.append("SOURCE_WALLET_SELL_DETECTED")
    if roi <= -abs(policy["stop_loss_percent"]):
        reasons.append("STOP_LOSS_TRIGGERED")
    if roi >= abs(policy["take_profit_percent"]):
        reasons.append("TAKE_PROFIT_TRIGGERED")
    if high_roi > 0 and drawdown >= abs(policy["trailing_stop_percent"]):
        reasons.append("TRAILING_STOP_TRIGGERED")
    if age_minutes >= policy["maximum_position_age_minutes"]:
        reasons.append("MAX_POSITION_AGE_TRIGGERED")
    trigger_reasons = {"TOKEN_UNSAFE", "EMERGENCY_EXIT_REQUESTED", "SOURCE_WALLET_SELL_DETECTED", "STOP_LOSS_TRIGGERED", "TAKE_PROFIT_TRIGGERED", "TRAILING_STOP_TRIGGERED", "MAX_POSITION_AGE_TRIGGERED"}
    if "POSITION_NOT_OPEN" in reasons or "SELL_ROUTE_UNAVAILABLE" in reasons:
        status = "BLOCKED"
    elif any(r in reasons for r in {"QUOTE_STALE", "QUOTE_FROM_FUTURE", "QUOTE_VALUE_INVALID"}):
        status = "INSUFFICIENT_DATA"
    elif any(r in reasons for r in trigger_reasons):
        status = "EXIT_READY"
    elif any(r in reasons for r in {"TOKEN_SAFETY_UNCERTAIN", "EXIT_PRICE_IMPACT_HIGH"}):
        status = "REVIEW"
    else:
        status = "HOLD"
    assessment_key = calculate_payload_hash({"position_id": position_id, "position_version": position.position_version, "quoted_output_sol": format(quoted, 'f'), "quote_observed_at": quote_time.isoformat(), "token": token, "policy_version": POLICY_VERSION})
    existing = db.scalar(select(CanonicalParserGovernedLivePositionAssessment).where(CanonicalParserGovernedLivePositionAssessment.assessment_key == assessment_key))
    evidence = {"position_id": position_id, "position_version": position.position_version, "quoted_output_sol": format(quoted, "f"), "cost_basis_sol": format(cost, "f"), "roi_percent": str(roi), "high_watermark_value_sol": format(high, "f"), "trailing_drawdown_percent": str(drawdown), "price_impact_percent": str(impact), "sell_route_available": bool(sell_route_available), "token_safety_status": safety, "source_wallet_sell_detected": bool(source_wallet_sell_detected), "emergency_exit_requested": bool(emergency_exit_requested), "reason_codes": sorted(set(reasons)), "policy": {**policy, "stop_loss_percent": str(policy["stop_loss_percent"]), "take_profit_percent": str(policy["take_profit_percent"]), "trailing_stop_percent": str(policy["trailing_stop_percent"]), "maximum_exit_price_impact_percent": str(policy["maximum_exit_price_impact_percent"])}}
    return {"status": status, "ready_to_exit": status == "EXIT_READY", "existing_assessment": None if existing is None else _serialize_assessment(existing), "assessment_key": assessment_key, "position_id": position_id, "quoted_output_sol": format(quoted, "f"), "unrealized_pnl_sol": format(pnl, "f"), "unrealized_roi_percent": str(roi), "high_watermark_value_sol": format(high, "f"), "high_watermark_roi_percent": str(high_roi), "trailing_drawdown_percent": str(drawdown), "reason_codes": sorted(set(reasons)), "evidence": evidence, "evidence_hash": calculate_payload_hash(evidence), "confirmation": f"{ASSESS_PREFIX}:{position_id}:{assessment_key}", "policy": policy}


def assess_governed_live_position(
    db: Session, *, position_id: str, quoted_output_sol: Any, price_impact_percent: Any,
    sell_route_available: bool, token_safety_status: str, source_wallet_sell_detected: bool,
    emergency_exit_requested: bool, quote_observed_at: datetime, idempotency_token: str,
    confirmation: str, actor_label: str | None = None, note: str | None = None,
    settings_object: Any = settings, assessed_at: datetime | None = None,
) -> dict[str, Any]:
    policy = _policy(settings_object)
    if not policy["enabled"]:
        raise CanonicalParserGovernedLivePositionError("M40 è disabilitata.", code="M40_DISABLED", status_code=409)
    now = _aware(assessed_at)
    preview = preview_governed_live_position_assessment(db, position_id=position_id, quoted_output_sol=quoted_output_sol, price_impact_percent=price_impact_percent, sell_route_available=sell_route_available, token_safety_status=token_safety_status, source_wallet_sell_detected=source_wallet_sell_detected, emergency_exit_requested=emergency_exit_requested, quote_observed_at=quote_observed_at, idempotency_token=idempotency_token, settings_object=settings_object, evaluated_at=now)
    if preview["existing_assessment"] is not None:
        return preview["existing_assessment"]
    if confirmation != preview["confirmation"]:
        raise CanonicalParserGovernedLivePositionError("Conferma assessment M40 non valida.", code="M40_ASSESSMENT_CONFIRMATION_REQUIRED", status_code=409)
    position = _position(db, position_id, lock=True)
    expires = now + timedelta(seconds=policy["assessment_ttl_seconds"])
    row = CanonicalParserGovernedLivePositionAssessment(
        assessment_id=str(uuid4()), assessment_key=preview["assessment_key"], scope="M40_GOVERNED_LIVE_POSITION_ASSESSMENT",
        position_db_id=position.id, position_id=position.position_id, status=preview["status"],
        quoted_output_sol=_money(preview["quoted_output_sol"]), current_value_sol=_money(preview["quoted_output_sol"]),
        unrealized_pnl_sol=_money(preview["unrealized_pnl_sol"]), unrealized_roi_percent=_pct(preview["unrealized_roi_percent"]),
        high_watermark_value_sol=_money(preview["high_watermark_value_sol"]), high_watermark_roi_percent=_pct(preview["high_watermark_roi_percent"]),
        trailing_drawdown_percent=_pct(preview["trailing_drawdown_percent"]), price_impact_percent=_pct(price_impact_percent),
        sell_route_available=bool(sell_route_available), token_safety_status=str(token_safety_status).upper(),
        source_wallet_sell_detected=bool(source_wallet_sell_detected), emergency_exit_requested=bool(emergency_exit_requested),
        reason_codes=preview["reason_codes"], assessment_snapshot=preview["evidence"], evidence_hash=preview["evidence_hash"],
        actor_label=_actor(actor_label), note=_note(note), quote_observed_at=_aware(quote_observed_at), assessed_at=now, expires_at=expires,
    )
    db.add(row)
    position.high_watermark_value_sol = row.high_watermark_value_sol
    position.high_watermark_roi_percent = row.high_watermark_roi_percent
    position.last_assessed_at = now
    position.position_version += 1
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.scalar(select(CanonicalParserGovernedLivePositionAssessment).where(CanonicalParserGovernedLivePositionAssessment.assessment_key == preview["assessment_key"]))
        if duplicate is not None:
            return _serialize_assessment(duplicate)
        raise CanonicalParserGovernedLivePositionError("Conflitto assessment M40.", code="M40_ASSESSMENT_CONFLICT", status_code=409) from exc
    db.refresh(row)
    return _serialize_assessment(row)


def preview_governed_live_exit_intent(
    db: Session, *, assessment_id: str, percentage: Any, validity_minutes: int,
    idempotency_token: str, settings_object: Any = settings, evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _policy(settings_object)
    assessment = db.scalar(select(CanonicalParserGovernedLivePositionAssessment).where(CanonicalParserGovernedLivePositionAssessment.assessment_id == assessment_id))
    if assessment is None:
        raise CanonicalParserGovernedLivePositionError("Assessment M40 non trovato.", code="M40_ASSESSMENT_NOT_FOUND", status_code=404)
    position = db.get(CanonicalParserGovernedLivePosition, assessment.position_db_id)
    if position is None:
        raise CanonicalParserGovernedLivePositionError("Posizione M40 non trovata.", code="M40_POSITION_NOT_FOUND", status_code=404)
    pct = _pct(percentage)
    reasons: list[str] = []
    if assessment.status != "EXIT_READY":
        reasons.append("ASSESSMENT_NOT_EXIT_READY")
    if _aware(assessment.expires_at) <= now:
        reasons.append("ASSESSMENT_EXPIRED")
    if position.status != "OPEN" or _decimal(position.quantity_raw) <= 0:
        reasons.append("POSITION_NOT_OPEN")
    if pct <= 0 or pct > 100:
        reasons.append("PERCENTAGE_INVALID")
    if validity_minutes < 1 or validity_minutes > policy["maximum_intent_validity_minutes"]:
        reasons.append("VALIDITY_INVALID")
    active = db.scalar(select(CanonicalParserGovernedLiveExitIntent).where(CanonicalParserGovernedLiveExitIntent.position_db_id == position.id, CanonicalParserGovernedLiveExitIntent.status == "ACTIVE", CanonicalParserGovernedLiveExitIntent.expires_at > now))
    if active is not None:
        reasons.append("ACTIVE_INTENT_EXISTS")
    permit = db.scalar(select(CanonicalParserMicroLiveCanaryPermit).where(CanonicalParserMicroLiveCanaryPermit.permit_id == position.micro_live_permit_id))
    if permit is None or permit.status != "ACTIVE" or _aware(permit.expires_at) <= now:
        reasons.append("MICRO_LIVE_PERMIT_INACTIVE")
    qty = (_decimal(position.quantity_raw) * pct / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_DOWN)
    if qty <= 0:
        reasons.append("EXIT_QUANTITY_ZERO")
    expected = _money(_decimal(assessment.quoted_output_sol) * qty / _decimal(position.quantity_raw)) if _decimal(position.quantity_raw) > 0 else _money(0)
    slippage_fraction = min(Decimal("0.99"), _decimal(assessment.price_impact_percent) / Decimal(100))
    minimum = _money(expected * (Decimal(1) - slippage_fraction))
    reason_code = next((r for r in assessment.reason_codes if r.endswith("TRIGGERED") or r in {"TOKEN_UNSAFE", "EMERGENCY_EXIT_REQUESTED", "SOURCE_WALLET_SELL_DETECTED"}), "MANUAL_GOVERNED_EXIT")
    token = str(idempotency_token or "").strip()
    if len(token) < 8:
        reasons.append("IDEMPOTENCY_INVALID")
    intent_key = calculate_payload_hash({"assessment_id": assessment_id, "position_id": position.position_id, "quantity_raw": str(qty), "token": token, "policy_version": POLICY_VERSION})
    existing = db.scalar(select(CanonicalParserGovernedLiveExitIntent).where(CanonicalParserGovernedLiveExitIntent.intent_key == intent_key))
    evidence = {"assessment_id": assessment_id, "position_id": position.position_id, "position_version": position.position_version, "permit_id": position.micro_live_permit_id, "decision_result_id": position.decision_result_id, "reason_code": reason_code, "quantity_raw": str(qty), "percentage": str(pct), "expected_output_sol": format(expected, "f"), "minimum_output_sol": format(minimum, "f"), "reason_codes": sorted(set(reasons)), "policy": {**policy, "stop_loss_percent": str(policy["stop_loss_percent"]), "take_profit_percent": str(policy["take_profit_percent"]), "trailing_stop_percent": str(policy["trailing_stop_percent"]), "maximum_exit_price_impact_percent": str(policy["maximum_exit_price_impact_percent"])}}
    status = "READY" if not reasons else "BLOCKED"
    return {"status": status, "ready": status == "READY", "existing_intent": None if existing is None else _serialize_intent(existing, now=now), "intent_key": intent_key, "reason_code": reason_code, "quantity_raw": str(qty), "percentage": str(pct), "expected_output_sol": format(expected, "f"), "minimum_output_sol": format(minimum, "f"), "reason_codes": sorted(set(reasons)), "evidence": evidence, "evidence_hash": calculate_payload_hash(evidence), "confirmation": f"{ISSUE_PREFIX}:{assessment_id}:{intent_key}", "policy": policy}


def issue_governed_live_exit_intent(
    db: Session, *, assessment_id: str, percentage: Any, validity_minutes: int,
    idempotency_token: str, confirmation: str, actor_label: str | None = None,
    note: str | None = None, settings_object: Any = settings, issued_at: datetime | None = None,
) -> dict[str, Any]:
    policy = _policy(settings_object)
    if not policy["enabled"]:
        raise CanonicalParserGovernedLivePositionError("M40 è disabilitata.", code="M40_DISABLED", status_code=409)
    now = _aware(issued_at)
    preview = preview_governed_live_exit_intent(db, assessment_id=assessment_id, percentage=percentage, validity_minutes=validity_minutes, idempotency_token=idempotency_token, settings_object=settings_object, evaluated_at=now)
    if preview["existing_intent"] is not None:
        return preview["existing_intent"]
    if not preview["ready"]:
        raise CanonicalParserGovernedLivePositionError("Exit intent M40 bloccato.", code="M40_EXIT_INTENT_BLOCKED", status_code=409)
    if confirmation != preview["confirmation"]:
        raise CanonicalParserGovernedLivePositionError("Conferma exit intent M40 non valida.", code="M40_EXIT_CONFIRMATION_REQUIRED", status_code=409)
    assessment = db.scalar(select(CanonicalParserGovernedLivePositionAssessment).where(CanonicalParserGovernedLivePositionAssessment.assessment_id == assessment_id))
    assert assessment is not None
    position = db.get(CanonicalParserGovernedLivePosition, assessment.position_db_id)
    assert position is not None
    intent_id = str(uuid4())
    initial_event_payload = {
        "intent_id": intent_id,
        "sequence": 1,
        "event_type": "ISSUED",
        "occurred_at": now.isoformat(),
        "payload": {"reason_code": preview["reason_code"], "quantity_raw": preview["quantity_raw"]},
        "previous_event_hash": None,
    }
    initial_event_hash = calculate_payload_hash(initial_event_payload)
    row = CanonicalParserGovernedLiveExitIntent(
        intent_id=intent_id, intent_key=preview["intent_key"], scope="M40_MANUAL_GOVERNED_LIVE_EXIT_INTENT",
        position_db_id=position.id, position_id=position.position_id, assessment_db_id=assessment.id, assessment_id=assessment.assessment_id,
        micro_live_permit_id=position.micro_live_permit_id, decision_result_id=position.decision_result_id,
        status="ACTIVE", reason_code=preview["reason_code"], quantity_raw=_decimal(preview["quantity_raw"]), percentage=_pct(preview["percentage"]),
        expected_output_sol=_money(preview["expected_output_sol"]), minimum_output_sol=_money(preview["minimum_output_sol"]),
        intent_snapshot=preview["evidence"], evidence_hash=preview["evidence_hash"], actor_label=_actor(actor_label), note=_note(note),
        issued_at=now, expires_at=now + timedelta(minutes=validity_minutes), revoked_at=None, consumed_at=None,
        latest_event_sequence=1, latest_event_hash=initial_event_hash,
    )
    db.add(row)
    db.flush()
    db.add(CanonicalParserGovernedLiveExitIntentEvent(
        event_id=str(uuid4()), intent_db_id=row.id, sequence=1, event_type="ISSUED",
        event_payload=initial_event_payload, previous_event_hash=None, event_hash=initial_event_hash, occurred_at=now,
    ))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.scalar(select(CanonicalParserGovernedLiveExitIntent).where(CanonicalParserGovernedLiveExitIntent.intent_key == preview["intent_key"]))
        if duplicate is not None:
            return _serialize_intent(duplicate, now=now)
        raise CanonicalParserGovernedLivePositionError("Conflitto exit intent M40.", code="M40_EXIT_INTENT_CONFLICT", status_code=409) from exc
    db.refresh(row)
    return _serialize_intent(row, now=now)


def resolve_active_governed_live_exit_intent(db: Session, intent_id: str, *, now: datetime | None = None, lock: bool = False) -> CanonicalParserGovernedLiveExitIntent:
    current = _aware(now)
    query = select(CanonicalParserGovernedLiveExitIntent).where(CanonicalParserGovernedLiveExitIntent.intent_id == intent_id)
    if lock:
        query = query.with_for_update()
    row = db.scalar(query)
    if row is None:
        raise CanonicalParserGovernedLivePositionError("Exit intent M40 non trovato.", code="M40_EXIT_INTENT_NOT_FOUND", status_code=404)
    resolved = _resolved_intent_status(row, current)
    if resolved != "ACTIVE":
        if resolved == "EXPIRED" and row.status == "ACTIVE":
            row.status = "EXPIRED"
            _append_event(db, row, event_type="EXPIRED", payload={}, at=current)
            db.commit()
        raise CanonicalParserGovernedLivePositionError(f"Exit intent M40 non attivo: {resolved}.", code="M40_EXIT_INTENT_INACTIVE", status_code=409)
    return row


def consume_governed_live_exit_intent(db: Session, intent_id: str, *, consumed_at: datetime | None = None) -> CanonicalParserGovernedLiveExitIntent:
    now = _aware(consumed_at)
    row = resolve_active_governed_live_exit_intent(db, intent_id, now=now, lock=True)
    row.status = "CONSUMED"
    row.consumed_at = now
    _append_event(db, row, event_type="CONSUMED", payload={}, at=now)
    return row


def revoke_governed_live_exit_intent(db: Session, *, intent_id: str, confirmation: str, reason: str, actor_label: str | None = None, revoked_at: datetime | None = None) -> dict[str, Any]:
    now = _aware(revoked_at)
    row = resolve_active_governed_live_exit_intent(db, intent_id, now=now, lock=True)
    expected = f"{REVOKE_PREFIX}:{row.intent_id}:{row.latest_event_hash}"
    if confirmation != expected:
        raise CanonicalParserGovernedLivePositionError("Conferma revoca M40 non valida.", code="M40_REVOKE_CONFIRMATION_REQUIRED", status_code=409)
    row.status = "REVOKED"
    row.revoked_at = now
    _append_event(db, row, event_type="REVOKED", payload={"reason": str(reason)[:500], "actor_label": _actor(actor_label)}, at=now)
    db.commit()
    db.refresh(row)
    return _serialize_intent(row, now=now)


def get_governed_live_position_assessment(db: Session, assessment_id: str) -> dict[str, Any]:
    row = db.scalar(select(CanonicalParserGovernedLivePositionAssessment).where(CanonicalParserGovernedLivePositionAssessment.assessment_id == assessment_id))
    if row is None:
        raise CanonicalParserGovernedLivePositionError("Assessment M40 non trovato.", code="M40_ASSESSMENT_NOT_FOUND", status_code=404)
    return _serialize_assessment(row)


def get_governed_live_exit_intent(db: Session, intent_id: str) -> dict[str, Any]:
    row = db.scalar(select(CanonicalParserGovernedLiveExitIntent).where(CanonicalParserGovernedLiveExitIntent.intent_id == intent_id))
    if row is None:
        raise CanonicalParserGovernedLivePositionError("Exit intent M40 non trovato.", code="M40_EXIT_INTENT_NOT_FOUND", status_code=404)
    return _serialize_intent(row)


def resolve_governed_live_position(db: Session) -> dict[str, Any]:
    latest = db.scalar(select(CanonicalParserGovernedLivePositionAssessment).order_by(CanonicalParserGovernedLivePositionAssessment.assessed_at.desc()).limit(1))
    active = db.scalars(select(CanonicalParserGovernedLiveExitIntent).where(CanonicalParserGovernedLiveExitIntent.status == "ACTIVE")).all()
    return {"latest_assessment": None if latest is None else _serialize_assessment(latest), "active_exit_intent_count": len(active), "active_exit_intents": [_serialize_intent(row) for row in active[:20]]}


def get_governed_live_position_status(db: Session, *, settings_object: Any = settings) -> dict[str, Any]:
    return {"milestone": "M40", "policy": _policy(settings_object), "assessment_count": len(db.scalars(select(CanonicalParserGovernedLivePositionAssessment)).all()), "active_exit_intent_count": len(db.scalars(select(CanonicalParserGovernedLiveExitIntent).where(CanonicalParserGovernedLiveExitIntent.status == "ACTIVE")).all()), "safety": {"manual_only": True, "automatic_exit": False, "transaction_built": False, "transaction_signed": False, "transaction_sent": False}}
