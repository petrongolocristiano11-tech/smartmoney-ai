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
    CanonicalParserMicroLiveCanaryPermit,
    CanonicalParserMicroLiveCanaryPermitEvent,
    CanonicalParserMicroLiveCanarySimulation,
    CanonicalParserPaperOperationalAssessment,
    CanonicalParserUnifiedDecisionResult,
    CanonicalParserUnifiedDecisionRun,
)
from backend.app.models.live_platform_config import LivePlatformConfig
from backend.app.models.live_trading_policy import LiveTradingPolicy
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    sanitize_error_message,
)
from backend.app.services.blockchain_parser_permit_bound_paper_execution_service import (
    _calculate_decision_hash,
)

MICRO_LIVE_CANARY_POLICY_VERSION = "canonical-parser-micro-live-canary-governance/1"
MICRO_LIVE_PERMIT_PREFIX = "ISSUE_M35_MICRO_LIVE_CANARY"
MICRO_LIVE_REVOKE_PREFIX = "REVOKE_M35_MICRO_LIVE_CANARY"
MICRO_LIVE_SIMULATION_PREFIX = "SIMULATE_M35_MICRO_LIVE_CANARY"
_MONEY_QUANTUM = Decimal("0.000000001")
_PRICE_QUANTUM = Decimal("0.000000000000000001")


class CanonicalParserMicroLiveCanaryError(ValueError):
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


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CanonicalParserMicroLiveCanaryError(
            "Valore numerico M35 non valido.", code="MICRO_LIVE_INVALID_NUMBER"
        ) from exc
    if not result.is_finite():
        raise CanonicalParserMicroLiveCanaryError(
            "Valore numerico M35 non finito.", code="MICRO_LIVE_INVALID_NUMBER"
        )
    return result.quantize(_MONEY_QUANTUM)


def _money(value: Any) -> str:
    return format(_decimal(value), "f")


def _price_decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CanonicalParserMicroLiveCanaryError(
            "Prezzo M35 non valido.", code="MICRO_LIVE_INVALID_NUMBER"
        ) from exc
    if not result.is_finite():
        raise CanonicalParserMicroLiveCanaryError(
            "Prezzo M35 non finito.", code="MICRO_LIVE_INVALID_NUMBER"
        )
    return result.quantize(_PRICE_QUANTUM)


def _price(value: Any) -> str:
    return format(_price_decimal(value), "f")


def _actor(value: str | None) -> str:
    return sanitize_error_message(value or "LOCAL_MICRO_LIVE_CANARY", max_length=80) or "LOCAL_MICRO_LIVE_CANARY"


def _note(value: str | None) -> str | None:
    return None if not str(value or "").strip() else sanitize_error_message(value, max_length=500)


def _policy(settings_object: Any) -> dict[str, Any]:
    return {
        "policy_version": MICRO_LIVE_CANARY_POLICY_VERSION,
        "maximum_validity_minutes": int(
            getattr(settings_object, "CANONICAL_PARSER_MICRO_LIVE_CANARY_MAX_VALIDITY_MINUTES", 15)
        ),
        "maximum_total_budget_sol": str(
            getattr(settings_object, "CANONICAL_PARSER_MICRO_LIVE_CANARY_MAX_TOTAL_BUDGET_SOL", 0.05)
        ),
        "maximum_order_budget_sol": str(
            getattr(settings_object, "CANONICAL_PARSER_MICRO_LIVE_CANARY_MAX_ORDER_BUDGET_SOL", 0.01)
        ),
        "maximum_order_count": int(
            getattr(settings_object, "CANONICAL_PARSER_MICRO_LIVE_CANARY_MAX_ORDER_COUNT", 3)
        ),
        "minimum_assessment_remaining_minutes": int(
            getattr(settings_object, "CANONICAL_PARSER_MICRO_LIVE_CANARY_MIN_ASSESSMENT_REMAINING_MINUTES", 2)
        ),
        "maximum_decision_age_minutes": int(
            getattr(settings_object, "CANONICAL_PARSER_MICRO_LIVE_CANARY_MAX_DECISION_AGE_MINUTES", 15)
        ),
        "live_trading_require_simulation": bool(
            getattr(settings_object, "LIVE_TRADING_REQUIRE_SIMULATION", True)
        ),
        "run_live_stream_worker": bool(
            getattr(settings_object, "RUN_LIVE_STREAM_WORKER", False)
        ),
        "run_live_position_monitor": bool(
            getattr(settings_object, "RUN_LIVE_POSITION_MONITOR", False)
        ),
        "governance_and_simulation_only": True,
        "signer_connected": False,
        "live_engine_connected": False,
        "external_requests_allowed": False,
        "live_execution_authorized": False,
    }


def _live_policy_snapshot(row: LiveTradingPolicy) -> dict[str, Any]:
    return {
        "id": row.id,
        "mode": row.mode,
        "kill_switch": bool(row.kill_switch),
        "stream_execution_enabled": bool(row.stream_execution_enabled),
        "buy_enabled": bool(row.buy_enabled),
        "sell_enabled": bool(row.sell_enabled),
        "max_order_size_sol": str(row.max_order_size_sol),
        "max_daily_buy_sol": str(row.max_daily_buy_sol),
        "max_daily_loss_sol": str(row.max_daily_loss_sol),
        "max_total_exposure_sol": str(row.max_total_exposure_sol),
    }


def _platform_snapshot(row: LivePlatformConfig) -> dict[str, Any]:
    armed_until = row.live_armed_until
    return {
        "id": row.id,
        "live_armed_until": None if armed_until is None else _aware(armed_until).isoformat(),
        "token_safety_enabled": bool(row.token_safety_enabled),
        "token_safety_fail_closed": bool(row.token_safety_fail_closed),
        "max_token_risk_score": int(row.max_token_risk_score),
        "max_top_holder_percent": str(row.max_top_holder_percent),
    }


def _safe_live_control_state(
    db: Session,
    *,
    now: datetime,
    settings_object: Any = settings,
) -> tuple[LiveTradingPolicy, LivePlatformConfig, list[str]]:
    live_policy = db.scalar(select(LiveTradingPolicy).order_by(LiveTradingPolicy.id.asc()).limit(1))
    platform = db.scalar(select(LivePlatformConfig).order_by(LivePlatformConfig.id.asc()).limit(1))
    reasons: list[str] = []
    if live_policy is None:
        reasons.append("LIVE_POLICY_MISSING")
    if platform is None:
        reasons.append("LIVE_PLATFORM_CONFIG_MISSING")
    if live_policy is not None:
        if live_policy.mode == "LIVE":
            reasons.append("LIVE_MODE_ALREADY_ACTIVE")
        if not live_policy.kill_switch:
            reasons.append("KILL_SWITCH_NOT_ENGAGED")
        if live_policy.stream_execution_enabled:
            reasons.append("STREAM_EXECUTION_ENABLED")
    if platform is not None:
        if platform.live_armed_until is not None and _aware(platform.live_armed_until) > now:
            reasons.append("LIVE_PLATFORM_ARMED")
        if not platform.token_safety_enabled:
            reasons.append("TOKEN_SAFETY_DISABLED")
        if not platform.token_safety_fail_closed:
            reasons.append("TOKEN_SAFETY_NOT_FAIL_CLOSED")
    if not bool(getattr(settings_object, "LIVE_TRADING_REQUIRE_SIMULATION", True)):
        reasons.append("LIVE_SIMULATION_NOT_REQUIRED")
    if bool(getattr(settings_object, "RUN_LIVE_STREAM_WORKER", False)):
        reasons.append("LIVE_STREAM_WORKER_ENABLED")
    if bool(getattr(settings_object, "RUN_LIVE_POSITION_MONITOR", False)):
        reasons.append("LIVE_POSITION_MONITOR_ENABLED")
    if reasons:
        raise CanonicalParserMicroLiveCanaryError(
            "Stato di controllo LIVE non sicuro per M35.",
            code="MICRO_LIVE_CONTROL_STATE_UNSAFE",
            status_code=409,
        )
    assert live_policy is not None and platform is not None
    return live_policy, platform, reasons


def _serialize_permit(row: CanonicalParserMicroLiveCanaryPermit, *, now: datetime | None = None) -> dict[str, Any]:
    current = _aware(now)
    resolved_status = row.status
    if row.status == "ACTIVE" and _aware(row.expires_at) <= current:
        resolved_status = "EXPIRED"
    elif row.status == "ACTIVE" and (
        row.simulated_order_count >= row.max_order_count
        or _decimal(row.simulated_budget_sol) >= _decimal(row.total_budget_sol)
    ):
        resolved_status = "EXHAUSTED"
    return {
        "permit_id": row.permit_id,
        "permit_key": row.permit_key,
        "operational_assessment_id": row.operational_assessment_id,
        "assessment_evidence_hash": row.assessment_evidence_hash,
        "scope": row.scope,
        "status": row.status,
        "resolved_status": resolved_status,
        "requested_validity_minutes": row.requested_validity_minutes,
        "total_budget_sol": _money(row.total_budget_sol),
        "max_order_budget_sol": _money(row.max_order_budget_sol),
        "max_order_count": row.max_order_count,
        "simulated_budget_sol": _money(row.simulated_budget_sol),
        "simulated_order_count": row.simulated_order_count,
        "remaining_budget_sol": _money(max(Decimal("0"), _decimal(row.total_budget_sol) - _decimal(row.simulated_budget_sol))),
        "remaining_order_count": max(0, row.max_order_count - row.simulated_order_count),
        "live_policy_snapshot": row.live_policy_snapshot,
        "live_platform_snapshot": row.live_platform_snapshot,
        "policy_version": row.policy_version,
        "policy_hash": row.policy_hash,
        "policy_snapshot": row.policy_snapshot,
        "actor_label": row.actor_label,
        "note": row.note,
        "issued_at": row.issued_at,
        "expires_at": row.expires_at,
        "revoked_at": row.revoked_at,
        "revocation_reason": row.revocation_reason,
        "latest_event_sequence": row.latest_event_sequence,
        "latest_event_hash": row.latest_event_hash,
    }


def _serialize_simulation(row: CanonicalParserMicroLiveCanarySimulation) -> dict[str, Any]:
    return {
        "simulation_id": row.simulation_id,
        "simulation_key": row.simulation_key,
        "permit_id": row.permit_id,
        "decision_result_id": row.decision_result_id,
        "decision_hash": row.decision_hash,
        "side": row.side,
        "status": row.status,
        "token_mint": row.token_mint,
        "requested_budget_sol": _money(row.requested_budget_sol),
        "simulated_budget_sol": _money(row.simulated_budget_sol),
        "market_price_sol": format(row.market_price_sol, "f"),
        "reason_codes": row.reason_codes,
        "evidence_snapshot": row.evidence_snapshot,
        "evidence_hash": row.evidence_hash,
        "actor_label": row.actor_label,
        "note": row.note,
        "simulated_at": row.simulated_at,
    }


def _append_event(
    db: Session,
    permit: CanonicalParserMicroLiveCanaryPermit,
    *,
    event_type: str,
    payload: dict[str, Any],
    occurred_at: datetime | None = None,
) -> CanonicalParserMicroLiveCanaryPermitEvent:
    now = _aware(occurred_at)
    sequence = int(permit.latest_event_sequence or 0) + 1
    event_payload = {
        "permit_id": permit.permit_id,
        "sequence": sequence,
        "event_type": event_type,
        "occurred_at": now.isoformat(),
        "payload": payload,
        "previous_event_hash": permit.latest_event_hash,
    }
    event_hash = calculate_payload_hash(event_payload)
    event = CanonicalParserMicroLiveCanaryPermitEvent(
        event_id=str(uuid4()),
        permit_db_id=permit.id,
        sequence=sequence,
        event_type=event_type,
        event_payload=event_payload,
        previous_event_hash=permit.latest_event_hash,
        event_hash=event_hash,
        occurred_at=now,
    )
    db.add(event)
    permit.latest_event_sequence = sequence
    permit.latest_event_hash = event_hash
    return event


def preview_micro_live_canary_permit(
    db: Session,
    *,
    operational_assessment_id: str,
    validity_minutes: int,
    total_budget_sol: Any,
    max_order_budget_sol: Any,
    max_order_count: int,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _policy(settings_object)
    assessment = db.scalar(
        select(CanonicalParserPaperOperationalAssessment).where(
            CanonicalParserPaperOperationalAssessment.assessment_id == operational_assessment_id
        )
    )
    if assessment is None:
        raise CanonicalParserMicroLiveCanaryError(
            "Assessment M34 non trovato.", code="MICRO_LIVE_ASSESSMENT_NOT_FOUND", status_code=404
        )
    if assessment.status != "READY":
        raise CanonicalParserMicroLiveCanaryError(
            "Assessment M34 non READY.", code="MICRO_LIVE_ASSESSMENT_NOT_READY", status_code=409
        )
    remaining = _aware(assessment.valid_until) - now
    if remaining < timedelta(minutes=policy["minimum_assessment_remaining_minutes"]):
        raise CanonicalParserMicroLiveCanaryError(
            "Assessment M34 scaduto o troppo vicino alla scadenza.",
            code="MICRO_LIVE_ASSESSMENT_STALE",
            status_code=409,
        )
    requested_total = _decimal(total_budget_sol)
    requested_order = _decimal(max_order_budget_sol)
    if validity_minutes < 1 or validity_minutes > policy["maximum_validity_minutes"]:
        raise CanonicalParserMicroLiveCanaryError(
            "Validità M35 oltre limite.", code="MICRO_LIVE_VALIDITY_LIMIT", status_code=409
        )
    if requested_total <= 0 or requested_total > _decimal(policy["maximum_total_budget_sol"]):
        raise CanonicalParserMicroLiveCanaryError(
            "Budget totale M35 oltre limite.", code="MICRO_LIVE_TOTAL_BUDGET_LIMIT", status_code=409
        )
    if requested_order <= 0 or requested_order > _decimal(policy["maximum_order_budget_sol"]) or requested_order > requested_total:
        raise CanonicalParserMicroLiveCanaryError(
            "Budget per ordine M35 oltre limite.", code="MICRO_LIVE_ORDER_BUDGET_LIMIT", status_code=409
        )
    if max_order_count < 1 or max_order_count > policy["maximum_order_count"]:
        raise CanonicalParserMicroLiveCanaryError(
            "Numero ordini simulati M35 oltre limite.", code="MICRO_LIVE_ORDER_COUNT_LIMIT", status_code=409
        )
    live_policy, platform, _ = _safe_live_control_state(
        db, now=now, settings_object=settings_object
    )
    if requested_order > _decimal(live_policy.max_order_size_sol):
        raise CanonicalParserMicroLiveCanaryError(
            "Budget per ordine M35 superiore alla policy LIVE.",
            code="MICRO_LIVE_POLICY_ORDER_LIMIT",
            status_code=409,
        )
    if requested_total > min(
        _decimal(live_policy.max_daily_buy_sol),
        _decimal(live_policy.max_total_exposure_sol),
    ):
        raise CanonicalParserMicroLiveCanaryError(
            "Budget totale M35 superiore alla policy LIVE.",
            code="MICRO_LIVE_POLICY_TOTAL_LIMIT",
            status_code=409,
        )
    if max_order_count > int(live_policy.max_daily_orders):
        raise CanonicalParserMicroLiveCanaryError(
            "Numero simulazioni M35 superiore alla policy LIVE.",
            code="MICRO_LIVE_POLICY_ORDER_COUNT_LIMIT",
            status_code=409,
        )
    live_snapshot = _live_policy_snapshot(live_policy)
    platform_snapshot = _platform_snapshot(platform)
    permit_key = calculate_payload_hash(
        {
            "assessment_id": assessment.assessment_id,
            "assessment_evidence_hash": assessment.evidence_hash,
            "validity_minutes": validity_minutes,
            "total_budget_sol": _money(requested_total),
            "max_order_budget_sol": _money(requested_order),
            "max_order_count": max_order_count,
            "live_policy_snapshot": live_snapshot,
            "live_platform_snapshot": platform_snapshot,
            "policy": policy,
        }
    )
    existing = db.scalar(
        select(CanonicalParserMicroLiveCanaryPermit).where(
            CanonicalParserMicroLiveCanaryPermit.permit_key == permit_key
        )
    )
    return {
        "ready": True,
        "existing_permit": None if existing is None else _serialize_permit(existing, now=now),
        "permit_key": permit_key,
        "operational_assessment_id": assessment.assessment_id,
        "assessment_evidence_hash": assessment.evidence_hash,
        "validity_minutes": validity_minutes,
        "total_budget_sol": _money(requested_total),
        "max_order_budget_sol": _money(requested_order),
        "max_order_count": max_order_count,
        "live_policy_snapshot": live_snapshot,
        "live_platform_snapshot": platform_snapshot,
        "confirmation": f"{MICRO_LIVE_PERMIT_PREFIX}:{assessment.assessment_id}:{permit_key}",
        "policy": policy,
        "safety": {
            "governance_and_simulation_only": True,
            "kill_switch_required_engaged": True,
            "live_platform_required_disarmed": True,
            "signer_connected": False,
            "live_engine_connected": False,
            "external_requests_allowed": False,
            "live_execution_authorized": False,
        },
    }


def issue_micro_live_canary_permit(
    db: Session,
    *,
    operational_assessment_id: str,
    validity_minutes: int,
    total_budget_sol: Any,
    max_order_budget_sol: Any,
    max_order_count: int,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    issued_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_MICRO_LIVE_CANARY_ENABLED", False)):
        raise CanonicalParserMicroLiveCanaryError(
            "M35 è disabilitata. Il flag resta false di default.",
            code="MICRO_LIVE_DISABLED",
            status_code=409,
        )
    now = _aware(issued_at)
    preview = preview_micro_live_canary_permit(
        db,
        operational_assessment_id=operational_assessment_id,
        validity_minutes=validity_minutes,
        total_budget_sol=total_budget_sol,
        max_order_budget_sol=max_order_budget_sol,
        max_order_count=max_order_count,
        settings_object=settings_object,
        evaluated_at=now,
    )
    if preview["existing_permit"] is not None:
        return preview["existing_permit"]
    if confirmation != preview["confirmation"]:
        raise CanonicalParserMicroLiveCanaryError(
            "Conferma permit M35 non valida.", code="MICRO_LIVE_CONFIRMATION_REQUIRED", status_code=409
        )
    assessment = db.scalar(
        select(CanonicalParserPaperOperationalAssessment).where(
            CanonicalParserPaperOperationalAssessment.assessment_id == operational_assessment_id
        )
    )
    assert assessment is not None
    policy_hash = calculate_payload_hash(preview["policy"])
    permit = CanonicalParserMicroLiveCanaryPermit(
        permit_id=str(uuid4()),
        permit_key=preview["permit_key"],
        operational_assessment_db_id=assessment.id,
        operational_assessment_id=assessment.assessment_id,
        assessment_evidence_hash=assessment.evidence_hash,
        scope="MICRO_LIVE_GOVERNANCE_SIMULATION_ONLY",
        status="ACTIVE",
        requested_validity_minutes=validity_minutes,
        total_budget_sol=_decimal(total_budget_sol),
        max_order_budget_sol=_decimal(max_order_budget_sol),
        max_order_count=max_order_count,
        simulated_budget_sol=Decimal("0"),
        simulated_order_count=0,
        live_policy_snapshot=preview["live_policy_snapshot"],
        live_platform_snapshot=preview["live_platform_snapshot"],
        policy_version=MICRO_LIVE_CANARY_POLICY_VERSION,
        policy_hash=policy_hash,
        policy_snapshot=preview["policy"],
        actor_label=_actor(actor_label),
        note=_note(note),
        issued_at=now,
        expires_at=now + timedelta(minutes=validity_minutes),
        revoked_at=None,
        revocation_reason=None,
        latest_event_sequence=0,
        latest_event_hash=None,
        technical_metadata=preview["safety"],
    )
    db.add(permit)
    try:
        db.flush()
        _append_event(db, permit, event_type="ISSUED", payload={"actor_label": permit.actor_label}, occurred_at=now)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.scalar(
            select(CanonicalParserMicroLiveCanaryPermit).where(
                CanonicalParserMicroLiveCanaryPermit.permit_key == preview["permit_key"]
            )
        )
        if duplicate is not None:
            return _serialize_permit(duplicate, now=now)
        raise CanonicalParserMicroLiveCanaryError(
            "Conflitto permit M35.", code="MICRO_LIVE_CONFLICT", status_code=409
        ) from exc
    db.refresh(permit)
    return _serialize_permit(permit, now=now)


def _resolve_active_permit(
    db: Session,
    permit_id: str,
    *,
    now: datetime,
    lock: bool = False,
) -> CanonicalParserMicroLiveCanaryPermit:
    query = select(CanonicalParserMicroLiveCanaryPermit).where(
        CanonicalParserMicroLiveCanaryPermit.permit_id == permit_id
    )
    if lock:
        query = query.with_for_update()
    permit = db.scalar(query)
    if permit is None:
        raise CanonicalParserMicroLiveCanaryError(
            "Permit M35 non trovato.", code="MICRO_LIVE_PERMIT_NOT_FOUND", status_code=404
        )
    resolved = _serialize_permit(permit, now=now)["resolved_status"]
    if resolved != "ACTIVE":
        if permit.status == "ACTIVE" and resolved in {"EXPIRED", "EXHAUSTED"}:
            permit.status = resolved
            _append_event(db, permit, event_type=resolved, payload={"resolved_at": now.isoformat()}, occurred_at=now)
            db.commit()
        raise CanonicalParserMicroLiveCanaryError(
            f"Permit M35 non attivo: {resolved}.", code="MICRO_LIVE_PERMIT_INACTIVE", status_code=409
        )
    return permit


def preview_micro_live_canary_simulation(
    db: Session,
    *,
    permit_id: str,
    decision_result_id: str,
    side: str,
    market_price_sol: Any,
    requested_budget_sol: Any,
    idempotency_token: str,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _policy(settings_object)
    normalized_side = str(side or "").strip().upper()
    if normalized_side not in {"BUY", "SELL"}:
        raise CanonicalParserMicroLiveCanaryError(
            "Side M35 non valido.", code="MICRO_LIVE_INVALID_SIDE"
        )
    normalized_idempotency_token = str(idempotency_token or "").strip()
    if not 8 <= len(normalized_idempotency_token) <= 200:
        raise CanonicalParserMicroLiveCanaryError(
            "Idempotency token M35 non valido.",
            code="MICRO_LIVE_IDEMPOTENCY_TOKEN_INVALID",
        )
    market_price = _price_decimal(market_price_sol)
    requested = _decimal(requested_budget_sol)
    if market_price <= 0 or requested < 0:
        raise CanonicalParserMicroLiveCanaryError(
            "Valori simulazione M35 non validi.", code="MICRO_LIVE_INVALID_VALUES"
        )
    permit = _resolve_active_permit(db, permit_id, now=now)
    live_policy, platform, _ = _safe_live_control_state(
        db, now=now, settings_object=settings_object
    )
    current_live_snapshot = _live_policy_snapshot(live_policy)
    current_platform_snapshot = _platform_snapshot(platform)
    reasons: list[str] = []
    if calculate_payload_hash(current_live_snapshot) != calculate_payload_hash(permit.live_policy_snapshot):
        reasons.append("LIVE_POLICY_DRIFT")
    if calculate_payload_hash(current_platform_snapshot) != calculate_payload_hash(permit.live_platform_snapshot):
        reasons.append("LIVE_PLATFORM_DRIFT")
    decision = db.scalar(
        select(CanonicalParserUnifiedDecisionResult).where(
            CanonicalParserUnifiedDecisionResult.result_id == decision_result_id
        )
    )
    if decision is None:
        raise CanonicalParserMicroLiveCanaryError(
            "Decisione M31 non trovata.", code="MICRO_LIVE_DECISION_NOT_FOUND", status_code=404
        )
    run = db.get(CanonicalParserUnifiedDecisionRun, decision.run_db_id)
    if run is None:
        reasons.append("DECISION_RUN_MISSING")
    else:
        if _aware(run.valid_until) <= now:
            reasons.append("DECISION_EXPIRED")
        if now - _aware(run.completed_at) > timedelta(minutes=policy["maximum_decision_age_minutes"]):
            reasons.append("DECISION_TOO_OLD")
    if decision.decision != "APPROVE":
        reasons.append("DECISION_NOT_APPROVE")
    if decision.decision_hash != _calculate_decision_hash(decision):
        reasons.append("DECISION_HASH_DRIFT")
    if decision.token_safety_status != "SAFE":
        reasons.append("TOKEN_NOT_SAFE")
    if decision.timing_status != "COPYABLE":
        reasons.append("TIMING_NOT_COPYABLE")
    if not decision.exit_plan or decision.exit_plan.get("status") != "PLANNED":
        reasons.append("EXIT_PLAN_MISSING")
    remaining_budget = _decimal(permit.total_budget_sol) - _decimal(permit.simulated_budget_sol)
    remaining_orders = permit.max_order_count - permit.simulated_order_count
    simulated_budget = Decimal("0") if normalized_side == "SELL" else min(
        requested, _decimal(permit.max_order_budget_sol), remaining_budget
    )
    if remaining_orders <= 0:
        reasons.append("PERMIT_ORDER_LIMIT")
    if normalized_side == "BUY" and (requested <= 0 or simulated_budget <= 0):
        reasons.append("PERMIT_BUDGET_EXHAUSTED")
    simulation_key = calculate_payload_hash(
        {
            "permit_id": permit_id,
            "decision_result_id": decision_result_id,
            "side": normalized_side,
            "market_price_sol": _price(market_price),
            "requested_budget_sol": _money(requested),
            "idempotency_token": normalized_idempotency_token,
        }
    )
    existing = db.scalar(
        select(CanonicalParserMicroLiveCanarySimulation).where(
            CanonicalParserMicroLiveCanarySimulation.simulation_key == simulation_key
        )
    )
    if reasons:
        status = "BLOCKED" if any(
            reason in reasons
            for reason in (
                "LIVE_POLICY_DRIFT",
                "LIVE_PLATFORM_DRIFT",
                "DECISION_HASH_DRIFT",
                "TOKEN_NOT_SAFE",
                "EXIT_PLAN_MISSING",
            )
        ) else "INSUFFICIENT_DATA"
    else:
        status = "READY"
    evidence = {
        "permit_id": permit_id,
        "decision_result_id": decision_result_id,
        "decision_hash": decision.decision_hash,
        "side": normalized_side,
        "token_mint": decision.token_mint,
        "market_price_sol": _price(market_price),
        "requested_budget_sol": _money(requested),
        "simulated_budget_sol": _money(simulated_budget),
        "remaining_budget_sol": _money(remaining_budget),
        "remaining_order_count": remaining_orders,
        "reason_codes": reasons,
        "live_policy_snapshot": current_live_snapshot,
        "live_platform_snapshot": current_platform_snapshot,
        "policy": policy,
        "safety": {
            "simulation_only": True,
            "signer_connected": False,
            "live_engine_connected": False,
            "transaction_built": False,
            "transaction_signed": False,
            "transaction_sent": False,
            "live_execution_authorized": False,
        },
    }
    evidence_hash = calculate_payload_hash(evidence)
    return {
        "status": status,
        "ready": status == "READY",
        "existing_simulation": None if existing is None else _serialize_simulation(existing),
        "simulation_key": simulation_key,
        "permit_id": permit_id,
        "decision_result_id": decision_result_id,
        "decision_hash": decision.decision_hash,
        "side": normalized_side,
        "token_mint": decision.token_mint,
        "requested_budget_sol": _money(requested),
        "simulated_budget_sol": _money(simulated_budget),
        "market_price_sol": _price(market_price),
        "reason_codes": reasons,
        "evidence": evidence,
        "evidence_hash": evidence_hash,
        "confirmation": f"{MICRO_LIVE_SIMULATION_PREFIX}:{permit_id}:{simulation_key}",
        "policy": policy,
    }


def simulate_micro_live_canary(
    db: Session,
    *,
    permit_id: str,
    decision_result_id: str,
    side: str,
    market_price_sol: Any,
    requested_budget_sol: Any,
    idempotency_token: str,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    simulated_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_MICRO_LIVE_CANARY_ENABLED", False)):
        raise CanonicalParserMicroLiveCanaryError(
            "M35 è disabilitata.", code="MICRO_LIVE_DISABLED", status_code=409
        )
    now = _aware(simulated_at)
    preview = preview_micro_live_canary_simulation(
        db,
        permit_id=permit_id,
        decision_result_id=decision_result_id,
        side=side,
        market_price_sol=market_price_sol,
        requested_budget_sol=requested_budget_sol,
        idempotency_token=idempotency_token,
        settings_object=settings_object,
        evaluated_at=now,
    )
    if preview["existing_simulation"] is not None:
        return preview["existing_simulation"]
    if confirmation != preview["confirmation"]:
        raise CanonicalParserMicroLiveCanaryError(
            "Conferma simulazione M35 non valida.", code="MICRO_LIVE_SIMULATION_CONFIRMATION_REQUIRED", status_code=409
        )
    permit = _resolve_active_permit(db, permit_id, now=now, lock=True)
    decision = db.scalar(
        select(CanonicalParserUnifiedDecisionResult).where(
            CanonicalParserUnifiedDecisionResult.result_id == decision_result_id
        )
    )
    assert decision is not None
    row = CanonicalParserMicroLiveCanarySimulation(
        simulation_id=str(uuid4()),
        simulation_key=preview["simulation_key"],
        permit_db_id=permit.id,
        permit_id=permit.permit_id,
        decision_result_db_id=decision.id,
        decision_result_id=decision.result_id,
        decision_hash=decision.decision_hash,
        side=preview["side"],
        status=preview["status"],
        token_mint=decision.token_mint,
        requested_budget_sol=_decimal(preview["requested_budget_sol"]),
        simulated_budget_sol=_decimal(preview["simulated_budget_sol"]),
        market_price_sol=_price_decimal(preview["market_price_sol"]),
        reason_codes=preview["reason_codes"],
        evidence_snapshot=preview["evidence"],
        evidence_hash=preview["evidence_hash"],
        actor_label=_actor(actor_label),
        note=_note(note),
        simulated_at=now,
    )
    db.add(row)
    try:
        if row.status == "READY":
            permit.simulated_order_count += 1
            permit.simulated_budget_sol = _decimal(permit.simulated_budget_sol) + _decimal(row.simulated_budget_sol)
        db.flush()
        _append_event(
            db,
            permit,
            event_type="SIMULATED",
            payload={
                "simulation_id": row.simulation_id,
                "status": row.status,
                "simulated_budget_sol": _money(row.simulated_budget_sol),
                "actor_label": row.actor_label,
            },
            occurred_at=now,
        )
        if permit.simulated_order_count >= permit.max_order_count or _decimal(permit.simulated_budget_sol) >= _decimal(permit.total_budget_sol):
            permit.status = "EXHAUSTED"
            _append_event(db, permit, event_type="EXHAUSTED", payload={"simulation_id": row.simulation_id}, occurred_at=now)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.scalar(
            select(CanonicalParserMicroLiveCanarySimulation).where(
                CanonicalParserMicroLiveCanarySimulation.simulation_key == preview["simulation_key"]
            )
        )
        if duplicate is not None:
            return _serialize_simulation(duplicate)
        raise CanonicalParserMicroLiveCanaryError(
            "Conflitto simulazione M35.", code="MICRO_LIVE_SIMULATION_CONFLICT", status_code=409
        ) from exc
    db.refresh(row)
    return _serialize_simulation(row)


def revoke_micro_live_canary_permit(
    db: Session,
    *,
    permit_id: str,
    confirmation: str,
    reason: str,
    actor_label: str | None = None,
    revoked_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(revoked_at)
    permit = db.scalar(
        select(CanonicalParserMicroLiveCanaryPermit)
        .where(CanonicalParserMicroLiveCanaryPermit.permit_id == permit_id)
        .with_for_update()
    )
    if permit is None:
        raise CanonicalParserMicroLiveCanaryError(
            "Permit M35 non trovato.", code="MICRO_LIVE_PERMIT_NOT_FOUND", status_code=404
        )
    expected = f"{MICRO_LIVE_REVOKE_PREFIX}:{permit_id}:{permit.latest_event_hash}"
    if confirmation != expected:
        raise CanonicalParserMicroLiveCanaryError(
            "Conferma revoca M35 non valida.", code="MICRO_LIVE_REVOKE_CONFIRMATION_REQUIRED", status_code=409
        )
    if permit.status == "REVOKED":
        return _serialize_permit(permit, now=now)
    permit.status = "REVOKED"
    permit.revoked_at = now
    permit.revocation_reason = sanitize_error_message(reason, max_length=500)
    _append_event(
        db,
        permit,
        event_type="REVOKED",
        payload={"reason": permit.revocation_reason, "actor_label": _actor(actor_label)},
        occurred_at=now,
    )
    db.commit()
    db.refresh(permit)
    return _serialize_permit(permit, now=now)


def get_micro_live_canary_permit(db: Session, permit_id: str) -> dict[str, Any]:
    permit = db.scalar(
        select(CanonicalParserMicroLiveCanaryPermit).where(
            CanonicalParserMicroLiveCanaryPermit.permit_id == permit_id
        )
    )
    if permit is None:
        raise CanonicalParserMicroLiveCanaryError(
            "Permit M35 non trovato.", code="MICRO_LIVE_PERMIT_NOT_FOUND", status_code=404
        )
    payload = _serialize_permit(permit)
    payload["events"] = [
        {
            "sequence": row.sequence,
            "event_type": row.event_type,
            "event_hash": row.event_hash,
            "previous_event_hash": row.previous_event_hash,
            "event_payload": row.event_payload,
            "occurred_at": row.occurred_at,
        }
        for row in db.scalars(
            select(CanonicalParserMicroLiveCanaryPermitEvent)
            .where(CanonicalParserMicroLiveCanaryPermitEvent.permit_db_id == permit.id)
            .order_by(CanonicalParserMicroLiveCanaryPermitEvent.sequence.asc())
        )
    ]
    payload["simulations"] = [
        _serialize_simulation(row)
        for row in db.scalars(
            select(CanonicalParserMicroLiveCanarySimulation)
            .where(CanonicalParserMicroLiveCanarySimulation.permit_db_id == permit.id)
            .order_by(CanonicalParserMicroLiveCanarySimulation.created_at.asc())
        )
    ]
    return payload


def get_micro_live_canary_simulation(db: Session, simulation_id: str) -> dict[str, Any]:
    row = db.scalar(
        select(CanonicalParserMicroLiveCanarySimulation).where(
            CanonicalParserMicroLiveCanarySimulation.simulation_id == simulation_id
        )
    )
    if row is None:
        raise CanonicalParserMicroLiveCanaryError(
            "Simulazione M35 non trovata.", code="MICRO_LIVE_SIMULATION_NOT_FOUND", status_code=404
        )
    return _serialize_simulation(row)


def resolve_micro_live_canary(db: Session) -> dict[str, Any]:
    latest = db.scalar(
        select(CanonicalParserMicroLiveCanaryPermit)
        .order_by(CanonicalParserMicroLiveCanaryPermit.created_at.desc())
        .limit(1)
    )
    return {
        "resolved_status": "EMPTY" if latest is None else _serialize_permit(latest)["resolved_status"],
        "latest_permit": None if latest is None else _serialize_permit(latest),
    }


def get_micro_live_canary_status(db: Session, *, settings_object: Any = settings) -> dict[str, Any]:
    return {
        "enabled": bool(getattr(settings_object, "CANONICAL_PARSER_MICRO_LIVE_CANARY_ENABLED", False)),
        "permit_count": int(db.scalar(select(func.count(CanonicalParserMicroLiveCanaryPermit.id))) or 0),
        "simulation_count": int(db.scalar(select(func.count(CanonicalParserMicroLiveCanarySimulation.id))) or 0),
        "policy": _policy(settings_object),
        "safety": {
            "governance_and_simulation_only": True,
            "signer_connected": False,
            "live_engine_connected": False,
            "transaction_built": False,
            "transaction_signed": False,
            "transaction_sent": False,
            "live_execution_authorized": False,
            "worker_connected": False,
            "scheduler_connected": False,
            "stream_connected": False,
        },
    }
