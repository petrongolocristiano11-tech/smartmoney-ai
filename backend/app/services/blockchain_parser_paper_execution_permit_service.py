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
    CanonicalParserPaperCanaryReadinessAssessment,
    CanonicalParserPaperExecutionPermit,
    CanonicalParserPaperExecutionPermitEvent,
    CanonicalParserPaperRuntimeBinding,
)
from backend.app.models.paper_account import PaperAccount
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    sanitize_error_message,
    sanitize_technical_metadata,
)
from backend.app.services.blockchain_parser_paper_canary_readiness_service import (
    resolve_paper_canary_readiness,
)
from backend.app.services.blockchain_parser_paper_runtime_binding_service import (
    resolve_paper_runtime_binding,
)

PAPER_EXECUTION_PERMIT_POLICY_VERSION = "canonical-parser-paper-execution-permit/1"
PAPER_EXECUTION_PERMIT_SCOPE = "PAPER_EXECUTION_METADATA_ONLY"
PAPER_EXECUTION_PERMIT_PREFIX = "ISSUE_PAPER_EXECUTION_PERMIT"
PAPER_EXECUTION_PERMIT_REVOKE_PREFIX = "REVOKE_PAPER_EXECUTION_PERMIT"
_MAX_ACTOR_LENGTH = 80
_MAX_NOTE_LENGTH = 500


class CanonicalParserPaperExecutionPermitError(ValueError):
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


def _actor(value: str | None) -> str:
    return sanitize_error_message(value or "LOCAL_PAPER_EXECUTION_PERMIT", max_length=_MAX_ACTOR_LENGTH) or "LOCAL_PAPER_EXECUTION_PERMIT"


def _note(value: str | None) -> str | None:
    if not str(value or "").strip():
        return None
    return sanitize_error_message(value, max_length=_MAX_NOTE_LENGTH)


def _decimal(value: Any) -> Decimal | None:
    try:
        resolved = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not resolved.is_finite():
        return None
    return resolved.quantize(Decimal("0.000000001"))


def _decimal_text(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000000001")), "f")


def _policy_snapshot(settings_object: Any) -> dict[str, Any]:
    return {
        "policy_version": PAPER_EXECUTION_PERMIT_POLICY_VERSION,
        "maximum_validity_minutes": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_EXECUTION_PERMIT_MAX_VALIDITY_MINUTES", 60)),
        "maximum_total_budget_sol": str(getattr(settings_object, "CANONICAL_PARSER_PAPER_EXECUTION_PERMIT_MAX_TOTAL_BUDGET_SOL", 1.0)),
        "maximum_order_budget_sol": str(getattr(settings_object, "CANONICAL_PARSER_PAPER_EXECUTION_PERMIT_MAX_ORDER_BUDGET_SOL", 0.25)),
        "maximum_order_count": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_EXECUTION_PERMIT_MAX_ORDER_COUNT", 20)),
        "minimum_readiness_remaining_minutes": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_EXECUTION_PERMIT_MIN_READINESS_REMAINING_MINUTES", 2)),
        "scope": PAPER_EXECUTION_PERMIT_SCOPE,
        "requires_ready_m29_assessment": True,
        "requires_current_read_only_paper_binding": True,
        "single_active_permit_per_paper_account": True,
        "manual_issue_only": True,
        "manual_revoke_only": True,
        "bounded_total_budget": True,
        "bounded_order_budget": True,
        "bounded_order_count": True,
        "budget_consumption_connected": False,
        "paper_execution_connected": False,
        "paper_execution_authorized": False,
        "paper_autopilot_connected": False,
        "paper_worker_connected": False,
        "scheduler_connected": False,
        "stream_connected": False,
        "position_monitor_connected": False,
        "live_execution_authorized": False,
        "paper_order_writes": False,
        "paper_account_writes": False,
        "paper_position_writes": False,
        "trade_writes": False,
        "external_requests_allowed": False,
    }


def _event_payload(
    *,
    event_id: str,
    permit_id: str,
    sequence: int,
    event_type: str,
    previous_status: str | None,
    new_status: str,
    actor_label: str,
    reason: str | None,
    previous_event_hash: str | None,
    occurred_at: datetime,
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "permit_id": permit_id,
        "sequence": sequence,
        "event_type": event_type,
        "previous_status": previous_status,
        "new_status": new_status,
        "actor_label": actor_label,
        "reason": reason,
        "previous_event_hash": previous_event_hash,
        "occurred_at": _aware(occurred_at).isoformat(),
    }


def _verify_event_chain(db: Session, permit: CanonicalParserPaperExecutionPermit) -> list[str]:
    events = list(
        db.scalars(
            select(CanonicalParserPaperExecutionPermitEvent)
            .where(CanonicalParserPaperExecutionPermitEvent.permit_db_id == permit.id)
            .order_by(CanonicalParserPaperExecutionPermitEvent.sequence.asc())
        )
    )
    reasons: set[str] = set()
    previous_hash: str | None = None
    for expected_sequence, event in enumerate(events, start=1):
        if event.sequence != expected_sequence:
            reasons.add("PAPER_EXECUTION_PERMIT_EVENT_SEQUENCE_INVALID")
        if event.previous_event_hash != previous_hash:
            reasons.add("PAPER_EXECUTION_PERMIT_EVENT_PREVIOUS_HASH_INVALID")
        if calculate_payload_hash(event.event_payload) != event.event_hash:
            reasons.add("PAPER_EXECUTION_PERMIT_EVENT_HASH_INVALID")
        previous_hash = event.event_hash
    if not events:
        reasons.add("PAPER_EXECUTION_PERMIT_EVENT_CHAIN_EMPTY")
    elif permit.latest_event_sequence != events[-1].sequence:
        reasons.add("PAPER_EXECUTION_PERMIT_LATEST_SEQUENCE_INVALID")
    elif permit.latest_event_hash != events[-1].event_hash:
        reasons.add("PAPER_EXECUTION_PERMIT_LATEST_HASH_INVALID")
    return sorted(reasons)


def _serialize(permit: CanonicalParserPaperExecutionPermit) -> dict[str, Any]:
    total = Decimal(permit.total_budget_sol)
    consumed = Decimal(permit.consumed_budget_sol)
    remaining = max(Decimal("0"), total - consumed)
    remaining_orders = max(0, int(permit.max_order_count) - int(permit.consumed_order_count))
    return {
        "permit_id": permit.permit_id,
        "permit_key": permit.permit_key,
        "readiness_assessment_id": permit.readiness_assessment_id,
        "readiness_evidence_hash": permit.readiness_evidence_hash,
        "binding_id": permit.binding_id,
        "binding_event_hash": permit.binding_event_hash,
        "certification_id": permit.certification_id,
        "paper_account_id": permit.paper_account_id,
        "paper_account_name": permit.paper_account_name,
        "scope": permit.scope,
        "status": permit.status,
        "requested_validity_minutes": permit.requested_validity_minutes,
        "total_budget_sol": _decimal_text(total),
        "max_order_budget_sol": _decimal_text(Decimal(permit.max_order_budget_sol)),
        "max_order_count": permit.max_order_count,
        "consumed_budget_sol": _decimal_text(consumed),
        "consumed_order_count": permit.consumed_order_count,
        "remaining_budget_sol": _decimal_text(remaining),
        "remaining_order_count": remaining_orders,
        "policy_version": permit.policy_version,
        "policy_hash": permit.policy_hash,
        "policy_snapshot": permit.policy_snapshot,
        "actor_label": permit.actor_label,
        "note": permit.note,
        "issued_at": permit.issued_at,
        "expires_at": permit.expires_at,
        "revoked_at": permit.revoked_at,
        "revocation_reason": permit.revocation_reason,
        "latest_event_sequence": permit.latest_event_sequence,
        "latest_event_hash": permit.latest_event_hash,
        "technical_metadata": permit.technical_metadata,
        "paper_execution_connected": False,
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
    }


def preview_paper_execution_permit(
    db: Session,
    *,
    readiness_assessment_id: str | None = None,
    validity_minutes: int = 15,
    total_budget_sol: Any = 0.5,
    max_order_budget_sol: Any = 0.1,
    max_order_count: int = 5,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _policy_snapshot(settings_object)
    policy_hash = calculate_payload_hash(policy)
    blockers: set[str] = set()

    requested_validity = int(validity_minutes)
    total_budget = _decimal(total_budget_sol)
    order_budget = _decimal(max_order_budget_sol)
    requested_order_count = int(max_order_count)
    policy_total = _decimal(policy["maximum_total_budget_sol"]) or Decimal("0")
    policy_order = _decimal(policy["maximum_order_budget_sol"]) or Decimal("0")

    if requested_validity < 1:
        blockers.add("PAPER_EXECUTION_PERMIT_VALIDITY_BELOW_MINIMUM")
    if requested_validity > int(policy["maximum_validity_minutes"]):
        blockers.add("PAPER_EXECUTION_PERMIT_VALIDITY_ABOVE_MAXIMUM")
    if total_budget is None or total_budget <= 0:
        blockers.add("PAPER_EXECUTION_PERMIT_TOTAL_BUDGET_INVALID")
    elif total_budget > policy_total:
        blockers.add("PAPER_EXECUTION_PERMIT_TOTAL_BUDGET_ABOVE_MAXIMUM")
    if order_budget is None or order_budget <= 0:
        blockers.add("PAPER_EXECUTION_PERMIT_ORDER_BUDGET_INVALID")
    elif order_budget > policy_order:
        blockers.add("PAPER_EXECUTION_PERMIT_ORDER_BUDGET_ABOVE_MAXIMUM")
    if total_budget is not None and order_budget is not None and order_budget > total_budget:
        blockers.add("PAPER_EXECUTION_PERMIT_ORDER_BUDGET_EXCEEDS_TOTAL")
    if requested_order_count < 1:
        blockers.add("PAPER_EXECUTION_PERMIT_ORDER_COUNT_BELOW_MINIMUM")
    if requested_order_count > int(policy["maximum_order_count"]):
        blockers.add("PAPER_EXECUTION_PERMIT_ORDER_COUNT_ABOVE_MAXIMUM")

    readiness = resolve_paper_canary_readiness(db, settings_object=settings_object, evaluated_at=now)
    if readiness.get("resolved_status") != "READY":
        blockers.add("PAPER_EXECUTION_PERMIT_READINESS_NOT_READY")
    resolved_assessment_id = readiness.get("assessment_id")
    if readiness_assessment_id and readiness_assessment_id != resolved_assessment_id:
        blockers.add("PAPER_EXECUTION_PERMIT_ASSESSMENT_NOT_CURRENT")
    selected_assessment_id = readiness_assessment_id or resolved_assessment_id
    assessment = None
    if selected_assessment_id:
        assessment = db.scalar(
            select(CanonicalParserPaperCanaryReadinessAssessment).where(
                CanonicalParserPaperCanaryReadinessAssessment.assessment_id == selected_assessment_id
            )
        )
    if assessment is None:
        blockers.add("PAPER_EXECUTION_PERMIT_ASSESSMENT_MISSING")
    elif assessment.status != "READY":
        blockers.add("PAPER_EXECUTION_PERMIT_ASSESSMENT_NOT_READY")
    elif _aware(assessment.valid_until) <= now + timedelta(minutes=int(policy["minimum_readiness_remaining_minutes"])):
        blockers.add("PAPER_EXECUTION_PERMIT_READINESS_REMAINING_WINDOW_TOO_SHORT")
    elif now + timedelta(minutes=requested_validity) > _aware(assessment.valid_until):
        blockers.add("PAPER_EXECUTION_PERMIT_EXCEEDS_READINESS_VALIDITY")

    binding_resolution = resolve_paper_runtime_binding(db, settings_object=settings_object, evaluated_at=now)
    if binding_resolution.get("resolved_status") != "BOUND":
        blockers.add("PAPER_EXECUTION_PERMIT_BINDING_NOT_BOUND")
    binding = None
    if assessment is not None:
        binding = db.get(CanonicalParserPaperRuntimeBinding, assessment.binding_db_id)
    if binding is None:
        blockers.add("PAPER_EXECUTION_PERMIT_BINDING_MISSING")
    elif (
        binding_resolution.get("binding_id") != binding.binding_id
        or binding_resolution.get("latest_event_hash") != binding.latest_event_hash
        or assessment is not None and assessment.binding_event_hash != binding.latest_event_hash
    ):
        blockers.add("PAPER_EXECUTION_PERMIT_BINDING_DRIFTED")

    account = db.get(PaperAccount, assessment.paper_account_id) if assessment is not None else None
    if account is None:
        blockers.add("PAPER_EXECUTION_PERMIT_ACCOUNT_MISSING")
    elif account.status != "ACTIVE":
        blockers.add("PAPER_EXECUTION_PERMIT_ACCOUNT_NOT_ACTIVE")

    total_text = _decimal_text(total_budget) if total_budget is not None else None
    order_text = _decimal_text(order_budget) if order_budget is not None else None
    manifest = {
        "readiness_assessment_id": assessment.assessment_id if assessment else None,
        "readiness_evidence_hash": assessment.evidence_hash if assessment else None,
        "binding_id": binding.binding_id if binding else None,
        "binding_event_hash": binding.latest_event_hash if binding else None,
        "certification_id": assessment.certification_id if assessment else None,
        "paper_account_id": assessment.paper_account_id if assessment else None,
        "scope": PAPER_EXECUTION_PERMIT_SCOPE,
        "validity_minutes": requested_validity,
        "total_budget_sol": total_text,
        "max_order_budget_sol": order_text,
        "max_order_count": requested_order_count,
        "policy_hash": policy_hash,
    }
    permit_key = calculate_payload_hash(manifest)

    active_permit = None
    if assessment is not None:
        active_permit = db.scalar(
            select(CanonicalParserPaperExecutionPermit)
            .where(
                CanonicalParserPaperExecutionPermit.paper_account_id == assessment.paper_account_id,
                CanonicalParserPaperExecutionPermit.status == "ACTIVE",
                CanonicalParserPaperExecutionPermit.expires_at > now,
            )
            .order_by(CanonicalParserPaperExecutionPermit.issued_at.desc())
            .limit(1)
        )
    if active_permit is not None and active_permit.permit_key != permit_key:
        blockers.add("PAPER_EXECUTION_PERMIT_ACTIVE_PERMIT_EXISTS")

    return {
        "eligible": not blockers and assessment is not None and binding is not None and account is not None,
        "reason_codes": sorted(blockers),
        "permit_key": permit_key,
        "confirmation": f"{PAPER_EXECUTION_PERMIT_PREFIX}:{permit_key[:16]}",
        "readiness_assessment_db_id": assessment.id if assessment else None,
        "readiness": sanitize_technical_metadata(readiness),
        "readiness_assessment_id": assessment.assessment_id if assessment else None,
        "readiness_evidence_hash": assessment.evidence_hash if assessment else None,
        "binding_db_id": binding.id if binding else None,
        "binding": sanitize_technical_metadata(binding_resolution),
        "certification_id": assessment.certification_id if assessment else None,
        "paper_account": {
            "paper_account_id": account.id,
            "paper_account_name": account.name,
            "status": account.status,
        } if account else None,
        "scope": PAPER_EXECUTION_PERMIT_SCOPE,
        "validity_minutes": requested_validity,
        "total_budget_sol": total_text,
        "max_order_budget_sol": order_text,
        "max_order_count": requested_order_count,
        "policy": policy,
        "policy_hash": policy_hash,
        "existing_permit_id": active_permit.permit_id if active_permit and active_permit.permit_key == permit_key else None,
        "paper_execution_connected": False,
        "paper_execution_authorized": False,
        "budget_consumption_connected": False,
        "live_execution_authorized": False,
    }


def issue_paper_execution_permit(
    db: Session,
    *,
    readiness_assessment_id: str | None = None,
    validity_minutes: int = 15,
    total_budget_sol: Any = 0.5,
    max_order_budget_sol: Any = 0.1,
    max_order_count: int = 5,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_PAPER_EXECUTION_PERMIT_ENABLED", False)):
        raise CanonicalParserPaperExecutionPermitError(
            "PAPER execution permit governance disabilitata.",
            code="CANONICAL_PARSER_PAPER_EXECUTION_PERMIT_DISABLED",
            status_code=409,
        )
    now = _aware(evaluated_at)
    preview = preview_paper_execution_permit(
        db,
        readiness_assessment_id=readiness_assessment_id,
        validity_minutes=validity_minutes,
        total_budget_sol=total_budget_sol,
        max_order_budget_sol=max_order_budget_sol,
        max_order_count=max_order_count,
        settings_object=settings_object,
        evaluated_at=now,
    )
    existing = db.scalar(
        select(CanonicalParserPaperExecutionPermit).where(
            CanonicalParserPaperExecutionPermit.permit_key == preview["permit_key"]
        )
    )
    if existing is not None:
        return _serialize(existing)
    if confirmation != preview["confirmation"]:
        raise CanonicalParserPaperExecutionPermitError(
            "Conferma PAPER execution permit non valida.",
            code="PAPER_EXECUTION_PERMIT_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if not preview["eligible"]:
        raise CanonicalParserPaperExecutionPermitError(
            "PAPER execution permit non idoneo.",
            code=preview["reason_codes"][0],
            status_code=409,
        )

    permit_id = str(uuid4())
    actor = _actor(actor_label)
    event_id = str(uuid4())
    event_payload = _event_payload(
        event_id=event_id,
        permit_id=permit_id,
        sequence=1,
        event_type="ISSUED",
        previous_status=None,
        new_status="ACTIVE",
        actor_label=actor,
        reason=_note(note),
        previous_event_hash=None,
        occurred_at=now,
    )
    event_hash = calculate_payload_hash(event_payload)
    permit = CanonicalParserPaperExecutionPermit(
        permit_id=permit_id,
        permit_key=preview["permit_key"],
        readiness_assessment_db_id=preview["readiness_assessment_db_id"],
        readiness_assessment_id=preview["readiness_assessment_id"],
        readiness_evidence_hash=preview["readiness_evidence_hash"],
        binding_db_id=preview["binding_db_id"],
        binding_id=preview["binding"]["binding_id"],
        binding_event_hash=preview["binding"]["latest_event_hash"],
        certification_id=preview["certification_id"],
        paper_account_id=preview["paper_account"]["paper_account_id"],
        paper_account_name=preview["paper_account"]["paper_account_name"],
        scope=PAPER_EXECUTION_PERMIT_SCOPE,
        status="ACTIVE",
        requested_validity_minutes=preview["validity_minutes"],
        total_budget_sol=Decimal(preview["total_budget_sol"]),
        max_order_budget_sol=Decimal(preview["max_order_budget_sol"]),
        max_order_count=preview["max_order_count"],
        consumed_budget_sol=Decimal("0"),
        consumed_order_count=0,
        policy_version=PAPER_EXECUTION_PERMIT_POLICY_VERSION,
        policy_hash=preview["policy_hash"],
        policy_snapshot=preview["policy"],
        actor_label=actor,
        note=_note(note),
        issued_at=now,
        expires_at=now + timedelta(minutes=preview["validity_minutes"]),
        revoked_at=None,
        revocation_reason=None,
        latest_event_sequence=1,
        latest_event_hash=event_hash,
        technical_metadata={
            "scope": PAPER_EXECUTION_PERMIT_SCOPE,
            "metadata_only": True,
            "budget_consumption_connected": False,
            "paper_execution_connected": False,
            "paper_execution_authorized": False,
            "paper_autopilot_connected": False,
            "paper_worker_connected": False,
            "scheduler_connected": False,
            "stream_connected": False,
            "position_monitor_connected": False,
            "live_execution_authorized": False,
        },
    )
    db.add(permit)
    try:
        db.flush()
        db.add(
            CanonicalParserPaperExecutionPermitEvent(
                event_id=event_id,
                permit_db_id=permit.id,
                sequence=1,
                event_type="ISSUED",
                previous_status=None,
                new_status="ACTIVE",
                actor_label=actor,
                reason=permit.note,
                event_payload=event_payload,
                previous_event_hash=None,
                event_hash=event_hash,
                occurred_at=now,
            )
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(
            select(CanonicalParserPaperExecutionPermit).where(
                CanonicalParserPaperExecutionPermit.permit_key == preview["permit_key"]
            )
        )
        if existing is not None:
            return _serialize(existing)
        raise CanonicalParserPaperExecutionPermitError(
            "Conflitto durante l'emissione del PAPER execution permit.",
            code="PAPER_EXECUTION_PERMIT_CONFLICT",
            status_code=409,
        ) from exc
    db.refresh(permit)
    return _serialize(permit)


def revoke_paper_execution_permit(
    db: Session,
    *,
    permit_id: str,
    confirmation: str,
    reason: str,
    actor_label: str | None = None,
    revoked_at: datetime | None = None,
) -> dict[str, Any]:
    permit = db.scalar(
        select(CanonicalParserPaperExecutionPermit).where(
            CanonicalParserPaperExecutionPermit.permit_id == permit_id
        )
    )
    if permit is None:
        raise CanonicalParserPaperExecutionPermitError(
            "PAPER execution permit non trovato.",
            code="PAPER_EXECUTION_PERMIT_NOT_FOUND",
            status_code=404,
        )
    expected = f"{PAPER_EXECUTION_PERMIT_REVOKE_PREFIX}:{permit.permit_id}"
    if confirmation != expected:
        raise CanonicalParserPaperExecutionPermitError(
            "Conferma revoca PAPER execution permit non valida.",
            code="PAPER_EXECUTION_PERMIT_REVOKE_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if permit.status == "REVOKED":
        return _serialize(permit)
    audit_reasons = _verify_event_chain(db, permit)
    if audit_reasons:
        raise CanonicalParserPaperExecutionPermitError(
            "Audit chain PAPER execution permit non integra.",
            code="PAPER_EXECUTION_PERMIT_AUDIT_INVALID",
            status_code=409,
        )
    now = _aware(revoked_at)
    clean_reason = sanitize_error_message(reason, max_length=_MAX_NOTE_LENGTH)
    actor = _actor(actor_label)
    sequence = permit.latest_event_sequence + 1
    event_id = str(uuid4())
    payload = _event_payload(
        event_id=event_id,
        permit_id=permit.permit_id,
        sequence=sequence,
        event_type="REVOKED",
        previous_status=permit.status,
        new_status="REVOKED",
        actor_label=actor,
        reason=clean_reason,
        previous_event_hash=permit.latest_event_hash,
        occurred_at=now,
    )
    event_hash = calculate_payload_hash(payload)
    db.add(
        CanonicalParserPaperExecutionPermitEvent(
            event_id=event_id,
            permit_db_id=permit.id,
            sequence=sequence,
            event_type="REVOKED",
            previous_status=permit.status,
            new_status="REVOKED",
            actor_label=actor,
            reason=clean_reason,
            event_payload=payload,
            previous_event_hash=permit.latest_event_hash,
            event_hash=event_hash,
            occurred_at=now,
        )
    )
    permit.status = "REVOKED"
    permit.revoked_at = now
    permit.revocation_reason = clean_reason
    permit.latest_event_sequence = sequence
    permit.latest_event_hash = event_hash
    db.commit()
    db.refresh(permit)
    return _serialize(permit)


def get_paper_execution_permit(db: Session, permit_id: str) -> dict[str, Any]:
    permit = db.scalar(
        select(CanonicalParserPaperExecutionPermit).where(
            CanonicalParserPaperExecutionPermit.permit_id == permit_id
        )
    )
    if permit is None:
        raise CanonicalParserPaperExecutionPermitError(
            "PAPER execution permit non trovato.",
            code="PAPER_EXECUTION_PERMIT_NOT_FOUND",
            status_code=404,
        )
    payload = _serialize(permit)
    events = list(
        db.scalars(
            select(CanonicalParserPaperExecutionPermitEvent)
            .where(CanonicalParserPaperExecutionPermitEvent.permit_db_id == permit.id)
            .order_by(CanonicalParserPaperExecutionPermitEvent.sequence.asc())
        )
    )
    payload["events"] = [
        {
            "event_id": event.event_id,
            "sequence": event.sequence,
            "event_type": event.event_type,
            "previous_status": event.previous_status,
            "new_status": event.new_status,
            "actor_label": event.actor_label,
            "reason": event.reason,
            "previous_event_hash": event.previous_event_hash,
            "event_hash": event.event_hash,
            "occurred_at": event.occurred_at,
        }
        for event in events
    ]
    return payload


def resolve_paper_execution_permit(
    db: Session,
    *,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    permit = db.scalar(
        select(CanonicalParserPaperExecutionPermit)
        .order_by(CanonicalParserPaperExecutionPermit.issued_at.desc(), CanonicalParserPaperExecutionPermit.id.desc())
        .limit(1)
    )
    if permit is None:
        return {
            "resolved_status": "UNPERMITTED",
            "permit_id": None,
            "paper_execution_connected": False,
            "paper_execution_authorized": False,
            "live_execution_authorized": False,
        }
    payload = _serialize(permit)
    audit_reasons = _verify_event_chain(db, permit)
    if audit_reasons:
        payload.update(resolved_status="AUDIT_INVALID", resolution_reason_codes=audit_reasons)
        return payload
    if permit.status == "REVOKED":
        payload["resolved_status"] = "REVOKED"
        return payload
    if _aware(permit.expires_at) <= now:
        payload["resolved_status"] = "EXPIRED"
        return payload
    readiness = resolve_paper_canary_readiness(db, settings_object=settings_object, evaluated_at=now)
    binding = resolve_paper_runtime_binding(db, settings_object=settings_object, evaluated_at=now)
    policy_hash = calculate_payload_hash(_policy_snapshot(settings_object))
    if (
        readiness.get("resolved_status") != "READY"
        or readiness.get("assessment_id") != permit.readiness_assessment_id
        or readiness.get("evidence_hash") != permit.readiness_evidence_hash
        or binding.get("resolved_status") != "BOUND"
        or binding.get("binding_id") != permit.binding_id
        or binding.get("latest_event_hash") != permit.binding_event_hash
        or policy_hash != permit.policy_hash
    ):
        payload["resolved_status"] = "DRIFTED"
        return payload
    payload["resolved_status"] = "ACTIVE"
    return payload


def get_paper_execution_permit_status(db: Session, *, settings_object: Any = settings) -> dict[str, Any]:
    return {
        "enabled": bool(getattr(settings_object, "CANONICAL_PARSER_PAPER_EXECUTION_PERMIT_ENABLED", False)),
        "policy": _policy_snapshot(settings_object),
        "permit_count": int(db.scalar(select(func.count(CanonicalParserPaperExecutionPermit.id))) or 0),
        "event_count": int(db.scalar(select(func.count(CanonicalParserPaperExecutionPermitEvent.id))) or 0),
        "operational_guards": {
            "metadata_only": True,
            "manual_issue_only": True,
            "manual_revoke_only": True,
            "budget_consumption_connected": False,
            "paper_execution_connected": False,
            "paper_execution_authorized": False,
            "paper_autopilot_connected": False,
            "paper_worker_connected": False,
            "scheduler_connected": False,
            "stream_connected": False,
            "position_monitor_connected": False,
            "paper_account_writes": False,
            "paper_order_writes": False,
            "paper_position_writes": False,
            "trade_writes": False,
            "external_requests_allowed": False,
            "live_execution_authorized": False,
        },
    }
