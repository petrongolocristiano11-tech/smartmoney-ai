from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserPaperAdmissionCertification,
    CanonicalParserPaperAdmissionCertificationEvent,
    CanonicalParserPaperProjectionReadinessAssessment,
)
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    sanitize_error_message,
    sanitize_technical_metadata,
)
from backend.app.services.blockchain_parser_paper_projection_readiness_service import (
    resolve_paper_projection_readiness,
)

PAPER_ADMISSION_CERTIFICATION_POLICY_VERSION = "canonical-parser-paper-admission-certification/1"
PAPER_ADMISSION_CERTIFICATION_PREFIX = "CERTIFY_PAPER_ADMISSION"
PAPER_ADMISSION_CERTIFICATION_REVOKE_PREFIX = "REVOKE_PAPER_ADMISSION_CERTIFICATION"
_MAX_ACTOR_LENGTH = 80
_MAX_NOTE_LENGTH = 500


class CanonicalParserPaperAdmissionCertificationError(ValueError):
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
    return sanitize_error_message(value or "LOCAL_PAPER_ADMISSION", max_length=_MAX_ACTOR_LENGTH) or "LOCAL_PAPER_ADMISSION"


def _note(value: str | None) -> str | None:
    if not str(value or "").strip():
        return None
    return sanitize_error_message(value, max_length=_MAX_NOTE_LENGTH)


def _policy_snapshot(settings_object: Any) -> dict[str, Any]:
    return {
        "policy_version": PAPER_ADMISSION_CERTIFICATION_POLICY_VERSION,
        "validity_minutes": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_ADMISSION_CERTIFICATION_VALIDITY_MINUTES", 60)),
        "requires_paper_projection_readiness": "READY",
        "manual_certification_only": True,
        "revocable": True,
        "paper_runtime_connected": False,
        "paper_account_reads": False,
        "paper_account_writes": False,
        "paper_order_writes": False,
        "paper_position_writes": False,
        "trade_writes": False,
        "external_requests_allowed": False,
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
    }


def _event_payload(
    *,
    event_id: str,
    certification_id: str,
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
        "certification_id": certification_id,
        "sequence": sequence,
        "event_type": event_type,
        "previous_status": previous_status,
        "new_status": new_status,
        "actor_label": actor_label,
        "reason": reason,
        "previous_event_hash": previous_event_hash,
        "occurred_at": _aware(occurred_at).isoformat(),
    }


def _audit_reasons(db: Session, certification: CanonicalParserPaperAdmissionCertification) -> list[str]:
    events = list(
        db.scalars(
            select(CanonicalParserPaperAdmissionCertificationEvent)
            .where(CanonicalParserPaperAdmissionCertificationEvent.certification_db_id == certification.id)
            .order_by(CanonicalParserPaperAdmissionCertificationEvent.sequence.asc())
        )
    )
    reasons: set[str] = set()
    previous_hash: str | None = None
    for expected_sequence, event in enumerate(events, start=1):
        if event.sequence != expected_sequence:
            reasons.add("PAPER_ADMISSION_CERTIFICATION_EVENT_SEQUENCE_INVALID")
        if event.previous_event_hash != previous_hash:
            reasons.add("PAPER_ADMISSION_CERTIFICATION_EVENT_CHAIN_INVALID")
        expected_payload = _event_payload(
            event_id=event.event_id,
            certification_id=certification.certification_id,
            sequence=event.sequence,
            event_type=event.event_type,
            previous_status=event.previous_status,
            new_status=event.new_status,
            actor_label=event.actor_label,
            reason=event.reason,
            previous_event_hash=event.previous_event_hash,
            occurred_at=event.occurred_at,
        )
        if calculate_payload_hash(expected_payload) != event.event_hash:
            reasons.add("PAPER_ADMISSION_CERTIFICATION_EVENT_HASH_INVALID")
        previous_hash = event.event_hash
    if not events:
        reasons.add("PAPER_ADMISSION_CERTIFICATION_EVENTS_MISSING")
    elif certification.latest_event_sequence != events[-1].sequence:
        reasons.add("PAPER_ADMISSION_CERTIFICATION_LATEST_SEQUENCE_INVALID")
    elif certification.latest_event_hash != events[-1].event_hash:
        reasons.add("PAPER_ADMISSION_CERTIFICATION_LATEST_HASH_INVALID")
    return sorted(reasons)


def _serialize(certification: CanonicalParserPaperAdmissionCertification) -> dict[str, Any]:
    return {
        "certification_id": certification.certification_id,
        "certification_key": certification.certification_key,
        "assessment_id": certification.assessment_id,
        "assessment_key": certification.assessment_key,
        "reliability_certification_id": certification.reliability_certification_id,
        "reliability_certification_event_hash": certification.reliability_certification_event_hash,
        "status": certification.status,
        "evidence_hash": certification.evidence_hash,
        "policy_version": certification.policy_version,
        "policy_hash": certification.policy_hash,
        "policy_snapshot": certification.policy_snapshot,
        "actor_label": certification.actor_label,
        "note": certification.note,
        "certified_at": certification.certified_at,
        "expires_at": certification.expires_at,
        "revoked_at": certification.revoked_at,
        "revocation_reason": certification.revocation_reason,
        "latest_event_sequence": certification.latest_event_sequence,
        "latest_event_hash": certification.latest_event_hash,
        "technical_metadata": certification.technical_metadata,
        "paper_admission_certified": certification.status == "ACTIVE",
        "paper_runtime_connected": False,
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
    }


def preview_paper_admission_certification(
    db: Session,
    *,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _policy_snapshot(settings_object)
    policy_hash = calculate_payload_hash(policy)
    readiness = resolve_paper_projection_readiness(db, settings_object=settings_object, evaluated_at=now)
    blockers: set[str] = set()
    if readiness.get("resolved_status") != "READY":
        blockers.add("PAPER_ADMISSION_READINESS_NOT_READY")
    assessment_id = readiness.get("assessment_id")
    assessment = None
    if assessment_id:
        assessment = db.scalar(
            select(CanonicalParserPaperProjectionReadinessAssessment).where(
                CanonicalParserPaperProjectionReadinessAssessment.assessment_id == assessment_id
            )
        )
    if assessment is None:
        blockers.add("PAPER_ADMISSION_ASSESSMENT_MISSING")
    manifest = {
        "assessment_id": assessment_id,
        "assessment_key": readiness.get("assessment_key"),
        "evidence_hash": readiness.get("evidence_hash"),
        "reliability_certification_id": readiness.get("certification_id"),
        "reliability_certification_event_hash": readiness.get("certification_event_hash"),
        "policy_hash": policy_hash,
    }
    certification_key = calculate_payload_hash(manifest)
    return {
        "eligible": not blockers,
        "reason_codes": sorted(blockers),
        "certification_key": certification_key,
        "confirmation": f"{PAPER_ADMISSION_CERTIFICATION_PREFIX}:{certification_key[:16]}",
        "assessment_db_id": assessment.id if assessment else None,
        "assessment": sanitize_technical_metadata(readiness),
        "policy": policy,
        "policy_hash": policy_hash,
        "paper_admission_certified": False,
        "paper_runtime_connected": False,
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
    }


def certify_paper_admission(
    db: Session,
    *,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    certified_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_PAPER_ADMISSION_CERTIFICATION_ENABLED", False)):
        raise CanonicalParserPaperAdmissionCertificationError(
            "PAPER admission certification disabilitata.",
            code="CANONICAL_PARSER_PAPER_ADMISSION_CERTIFICATION_DISABLED",
            status_code=409,
        )
    now = _aware(certified_at)
    preview = preview_paper_admission_certification(db, settings_object=settings_object, evaluated_at=now)
    existing = db.scalar(
        select(CanonicalParserPaperAdmissionCertification).where(
            CanonicalParserPaperAdmissionCertification.certification_key == preview["certification_key"]
        )
    )
    if existing is not None:
        return _serialize(existing)
    if confirmation != preview["confirmation"]:
        raise CanonicalParserPaperAdmissionCertificationError(
            "Conferma PAPER admission certification non valida.",
            code="PAPER_ADMISSION_CERTIFICATION_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if not preview["eligible"] or preview["assessment_db_id"] is None:
        raise CanonicalParserPaperAdmissionCertificationError(
            "PAPER projection readiness non certificabile.",
            code="PAPER_ADMISSION_CERTIFICATION_BLOCKED",
            status_code=409,
        )
    assessment = preview["assessment"]
    certification = CanonicalParserPaperAdmissionCertification(
        certification_id=str(uuid4()),
        certification_key=preview["certification_key"],
        assessment_db_id=preview["assessment_db_id"],
        assessment_id=assessment["assessment_id"],
        assessment_key=assessment["assessment_key"],
        reliability_certification_id=assessment["certification_id"],
        reliability_certification_event_hash=assessment["certification_event_hash"],
        status="ACTIVE",
        evidence_hash=assessment["evidence_hash"],
        policy_version=PAPER_ADMISSION_CERTIFICATION_POLICY_VERSION,
        policy_hash=preview["policy_hash"],
        policy_snapshot=preview["policy"],
        actor_label=_actor(actor_label),
        note=_note(note),
        certified_at=now,
        expires_at=now + timedelta(minutes=preview["policy"]["validity_minutes"]),
        revoked_at=None,
        revocation_reason=None,
        latest_event_sequence=1,
        latest_event_hash="0" * 64,
        technical_metadata={
            "manual_certification_only": True,
            "paper_runtime_connected": False,
            "paper_execution_authorized": False,
            "live_execution_authorized": False,
        },
    )
    event_id = str(uuid4())
    event_payload = _event_payload(
        event_id=event_id,
        certification_id=certification.certification_id,
        sequence=1,
        event_type="CERTIFIED",
        previous_status=None,
        new_status="ACTIVE",
        actor_label=certification.actor_label,
        reason=certification.note,
        previous_event_hash=None,
        occurred_at=now,
    )
    certification.latest_event_hash = calculate_payload_hash(event_payload)
    db.add(certification)
    try:
        db.flush()
        db.add(
            CanonicalParserPaperAdmissionCertificationEvent(
                event_id=event_id,
                certification_db_id=certification.id,
                sequence=1,
                event_type="CERTIFIED",
                previous_status=None,
                new_status="ACTIVE",
                actor_label=certification.actor_label,
                reason=certification.note,
                event_payload=event_payload,
                previous_event_hash=None,
                event_hash=certification.latest_event_hash,
                occurred_at=now,
            )
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(
            select(CanonicalParserPaperAdmissionCertification).where(
                CanonicalParserPaperAdmissionCertification.certification_key == preview["certification_key"]
            )
        )
        if existing is not None:
            return _serialize(existing)
        raise CanonicalParserPaperAdmissionCertificationError(
            "Conflitto durante la PAPER admission certification.",
            code="PAPER_ADMISSION_CERTIFICATION_CONFLICT",
            status_code=409,
        ) from exc
    db.refresh(certification)
    return _serialize(certification)


def revoke_paper_admission_certification(
    db: Session,
    *,
    certification_id: str,
    confirmation: str,
    reason: str,
    actor_label: str | None = None,
    revoked_at: datetime | None = None,
) -> dict[str, Any]:
    certification = db.scalar(
        select(CanonicalParserPaperAdmissionCertification).where(
            CanonicalParserPaperAdmissionCertification.certification_id == certification_id
        )
    )
    if certification is None:
        raise CanonicalParserPaperAdmissionCertificationError(
            "PAPER admission certification non trovata.",
            code="PAPER_ADMISSION_CERTIFICATION_NOT_FOUND",
            status_code=404,
        )
    expected = f"{PAPER_ADMISSION_CERTIFICATION_REVOKE_PREFIX}:{certification.certification_id}"
    if confirmation != expected:
        raise CanonicalParserPaperAdmissionCertificationError(
            "Conferma revoca PAPER admission non valida.",
            code="PAPER_ADMISSION_CERTIFICATION_REVOKE_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if certification.status == "REVOKED":
        return _serialize(certification)
    now = _aware(revoked_at)
    previous_status = certification.status
    certification.status = "REVOKED"
    certification.revoked_at = now
    certification.revocation_reason = sanitize_error_message(reason, max_length=_MAX_NOTE_LENGTH)
    certification.latest_event_sequence += 1
    event_id = str(uuid4())
    event_payload = _event_payload(
        event_id=event_id,
        certification_id=certification.certification_id,
        sequence=certification.latest_event_sequence,
        event_type="REVOKED",
        previous_status=previous_status,
        new_status="REVOKED",
        actor_label=_actor(actor_label),
        reason=certification.revocation_reason,
        previous_event_hash=certification.latest_event_hash,
        occurred_at=now,
    )
    event_hash = calculate_payload_hash(event_payload)
    db.add(
        CanonicalParserPaperAdmissionCertificationEvent(
            event_id=event_id,
            certification_db_id=certification.id,
            sequence=certification.latest_event_sequence,
            event_type="REVOKED",
            previous_status=previous_status,
            new_status="REVOKED",
            actor_label=event_payload["actor_label"],
            reason=certification.revocation_reason,
            event_payload=event_payload,
            previous_event_hash=certification.latest_event_hash,
            event_hash=event_hash,
            occurred_at=now,
        )
    )
    certification.latest_event_hash = event_hash
    db.commit()
    db.refresh(certification)
    return _serialize(certification)


def get_paper_admission_certification(db: Session, certification_id: str) -> dict[str, Any]:
    certification = db.scalar(
        select(CanonicalParserPaperAdmissionCertification).where(
            CanonicalParserPaperAdmissionCertification.certification_id == certification_id
        )
    )
    if certification is None:
        raise CanonicalParserPaperAdmissionCertificationError(
            "PAPER admission certification non trovata.",
            code="PAPER_ADMISSION_CERTIFICATION_NOT_FOUND",
            status_code=404,
        )
    return _serialize(certification)


def resolve_paper_admission_certification(
    db: Session,
    *,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    certification = db.scalar(
        select(CanonicalParserPaperAdmissionCertification)
        .order_by(CanonicalParserPaperAdmissionCertification.certified_at.desc())
        .limit(1)
    )
    if certification is None:
        return {
            "resolved_status": "UNCERTIFIED",
            "certification_id": None,
            "paper_admission_certified": False,
            "paper_runtime_connected": False,
            "paper_execution_authorized": False,
            "live_execution_authorized": False,
        }
    payload = _serialize(certification)
    audit_reasons = _audit_reasons(db, certification)
    if audit_reasons:
        payload["resolved_status"] = "AUDIT_INVALID"
        payload["reason_codes"] = audit_reasons
        payload["paper_admission_certified"] = False
        return payload
    if certification.status == "REVOKED":
        payload["resolved_status"] = "REVOKED"
        payload["paper_admission_certified"] = False
        return payload
    if _aware(certification.expires_at) <= now:
        payload["resolved_status"] = "EXPIRED"
        payload["paper_admission_certified"] = False
        return payload
    readiness = resolve_paper_projection_readiness(db, settings_object=settings_object, evaluated_at=now)
    policy_hash = calculate_payload_hash(_policy_snapshot(settings_object))
    if (
        readiness.get("resolved_status") != "READY"
        or readiness.get("assessment_id") != certification.assessment_id
        or readiness.get("evidence_hash") != certification.evidence_hash
        or readiness.get("certification_event_hash") != certification.reliability_certification_event_hash
        or policy_hash != certification.policy_hash
    ):
        payload["resolved_status"] = "DRIFTED"
        payload["paper_admission_certified"] = False
        return payload
    payload["resolved_status"] = "CERTIFIED"
    payload["paper_admission_certified"] = True
    return payload


def get_paper_admission_certification_status(
    db: Session,
    *,
    settings_object: Any = settings,
) -> dict[str, Any]:
    return {
        "enabled": bool(getattr(settings_object, "CANONICAL_PARSER_PAPER_ADMISSION_CERTIFICATION_ENABLED", False)),
        "policy": _policy_snapshot(settings_object),
        "certification_count": int(db.scalar(select(func.count(CanonicalParserPaperAdmissionCertification.id))) or 0),
        "event_count": int(db.scalar(select(func.count(CanonicalParserPaperAdmissionCertificationEvent.id))) or 0),
        "operational_guards": {
            "manual_certification_only": True,
            "revocable": True,
            "paper_runtime_connected": False,
            "paper_account_reads": False,
            "paper_account_writes": False,
            "paper_order_writes": False,
            "paper_position_writes": False,
            "trade_writes": False,
            "external_requests_allowed": False,
            "paper_execution_authorized": False,
            "live_execution_authorized": False,
        },
    }
