from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserShadowReliabilityAssessment,
    CanonicalParserShadowReliabilityCertification,
    CanonicalParserShadowReliabilityCertificationEvent,
)
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    sanitize_error_message,
    sanitize_technical_metadata,
)
from backend.app.services.blockchain_parser_shadow_reliability_service import (
    resolve_shadow_reliability,
)

SHADOW_RELIABILITY_CERTIFICATION_POLICY_VERSION = "canonical-parser-shadow-reliability-certification/1"
SHADOW_RELIABILITY_CERTIFICATION_PREFIX = "CERTIFY_SHADOW_RELIABILITY"
SHADOW_RELIABILITY_CERTIFICATION_REVOKE_PREFIX = "REVOKE_SHADOW_RELIABILITY_CERTIFICATION"
_MAX_ACTOR_LENGTH = 80
_MAX_NOTE_LENGTH = 500


class CanonicalParserShadowReliabilityCertificationError(ValueError):
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
    return sanitize_error_message(value or "LOCAL_OPERATOR", max_length=_MAX_ACTOR_LENGTH) or "LOCAL_OPERATOR"


def _note(value: str | None) -> str | None:
    if not str(value or "").strip():
        return None
    return sanitize_error_message(value, max_length=_MAX_NOTE_LENGTH)


def _policy_snapshot(settings_object: Any) -> dict[str, Any]:
    return {
        "policy_version": SHADOW_RELIABILITY_CERTIFICATION_POLICY_VERSION,
        "validity_minutes": int(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_RELIABILITY_CERTIFICATION_VALIDITY_MINUTES", 60)
        ),
        "requires_latest_reliability_ready": True,
        "requires_unexpired_reliability_assessment": True,
        "requires_no_evidence_drift": True,
        "manual_certification_only": True,
        "revocable": True,
        "paper_projection_connected": False,
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
        "network_allowed": False,
        "writes_trades": False,
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


def _append_event(
    db: Session,
    certification: CanonicalParserShadowReliabilityCertification,
    *,
    event_type: str,
    previous_status: str | None,
    new_status: str,
    actor_label: str,
    reason: str | None,
    occurred_at: datetime,
) -> CanonicalParserShadowReliabilityCertificationEvent:
    sequence = int(certification.latest_event_sequence or 0) + 1
    previous_hash = certification.latest_event_hash if certification.latest_event_sequence else None
    event_id = str(uuid4())
    payload = _event_payload(
        event_id=event_id,
        certification_id=certification.certification_id,
        sequence=sequence,
        event_type=event_type,
        previous_status=previous_status,
        new_status=new_status,
        actor_label=actor_label,
        reason=reason,
        previous_event_hash=previous_hash,
        occurred_at=occurred_at,
    )
    event_hash = calculate_payload_hash(payload)
    event = CanonicalParserShadowReliabilityCertificationEvent(
        event_id=event_id,
        certification_db_id=certification.id,
        sequence=sequence,
        event_type=event_type,
        previous_status=previous_status,
        new_status=new_status,
        actor_label=actor_label,
        reason=reason,
        event_payload=payload,
        previous_event_hash=previous_hash,
        event_hash=event_hash,
        occurred_at=occurred_at,
    )
    certification.latest_event_sequence = sequence
    certification.latest_event_hash = event_hash
    db.add(event)
    return event


def _verify_event_chain(
    db: Session, certification: CanonicalParserShadowReliabilityCertification
) -> list[str]:
    events = list(
        db.scalars(
            select(CanonicalParserShadowReliabilityCertificationEvent)
            .where(
                CanonicalParserShadowReliabilityCertificationEvent.certification_db_id
                == certification.id
            )
            .order_by(CanonicalParserShadowReliabilityCertificationEvent.sequence.asc())
        )
    )
    reasons: set[str] = set()
    previous_hash: str | None = None
    for expected, event in enumerate(events, start=1):
        if event.sequence != expected:
            reasons.add("SHADOW_RELIABILITY_CERTIFICATION_EVENT_SEQUENCE_INVALID")
        if event.previous_event_hash != previous_hash:
            reasons.add("SHADOW_RELIABILITY_CERTIFICATION_EVENT_PREVIOUS_HASH_INVALID")
        if calculate_payload_hash(event.event_payload) != event.event_hash:
            reasons.add("SHADOW_RELIABILITY_CERTIFICATION_EVENT_HASH_INVALID")
        previous_hash = event.event_hash
    if not events:
        reasons.add("SHADOW_RELIABILITY_CERTIFICATION_EVENT_CHAIN_EMPTY")
    elif certification.latest_event_sequence != events[-1].sequence:
        reasons.add("SHADOW_RELIABILITY_CERTIFICATION_LATEST_SEQUENCE_INVALID")
    elif certification.latest_event_hash != events[-1].event_hash:
        reasons.add("SHADOW_RELIABILITY_CERTIFICATION_LATEST_HASH_INVALID")
    return sorted(reasons)


def _serialize(certification: CanonicalParserShadowReliabilityCertification) -> dict[str, Any]:
    return {
        "certification_id": certification.certification_id,
        "certification_key": certification.certification_key,
        "assessment_id": certification.assessment_id,
        "assessment_key": certification.assessment_key,
        "worker_generation": certification.worker_generation,
        "lease_epoch": certification.lease_epoch,
        "worker_event_hash": certification.worker_event_hash,
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
        "paper_projection_authorized": False,
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
    }


def preview_shadow_reliability_certification(
    db: Session,
    *,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _policy_snapshot(settings_object)
    policy_hash = calculate_payload_hash(policy)
    reliability = resolve_shadow_reliability(
        db, settings_object=settings_object, evaluated_at=now
    )
    blockers: set[str] = set()
    if reliability.get("resolved_status") != "READY":
        blockers.add("SHADOW_RELIABILITY_NOT_READY")
    assessment_id = reliability.get("assessment_id")
    assessment = None
    if assessment_id:
        assessment = db.scalar(
            select(CanonicalParserShadowReliabilityAssessment).where(
                CanonicalParserShadowReliabilityAssessment.assessment_id == assessment_id
            )
        )
    if assessment is None:
        blockers.add("SHADOW_RELIABILITY_ASSESSMENT_MISSING")
    manifest = {
        "assessment_id": assessment_id,
        "assessment_key": reliability.get("assessment_key"),
        "evidence_hash": reliability.get("evidence_hash"),
        "worker_generation": reliability.get("worker_generation", 0),
        "lease_epoch": reliability.get("lease_epoch", 0),
        "worker_event_hash": reliability.get("worker_event_hash"),
        "policy_hash": policy_hash,
    }
    certification_key = calculate_payload_hash(manifest)
    return {
        "eligible": not blockers,
        "reason_codes": sorted(blockers),
        "certification_key": certification_key,
        "confirmation": f"{SHADOW_RELIABILITY_CERTIFICATION_PREFIX}:{certification_key[:16]}",
        "assessment_db_id": assessment.id if assessment else None,
        "assessment": sanitize_technical_metadata(reliability),
        "policy": policy,
        "policy_hash": policy_hash,
        "paper_projection_authorized": False,
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
    }


def certify_shadow_reliability(
    db: Session,
    *,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    certified_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(
        getattr(settings_object, "CANONICAL_PARSER_SHADOW_RELIABILITY_CERTIFICATION_ENABLED", False)
    ):
        raise CanonicalParserShadowReliabilityCertificationError(
            "Shadow reliability certification disabilitata.",
            code="CANONICAL_PARSER_SHADOW_RELIABILITY_CERTIFICATION_DISABLED",
            status_code=409,
        )
    now = _aware(certified_at)
    preview = preview_shadow_reliability_certification(
        db, settings_object=settings_object, evaluated_at=now
    )
    existing = db.scalar(
        select(CanonicalParserShadowReliabilityCertification).where(
            CanonicalParserShadowReliabilityCertification.certification_key
            == preview["certification_key"]
        )
    )
    if existing is not None:
        return _serialize(existing)
    if confirmation != preview["confirmation"]:
        raise CanonicalParserShadowReliabilityCertificationError(
            "Conferma reliability certification non valida.",
            code="SHADOW_RELIABILITY_CERTIFICATION_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if not preview["eligible"]:
        raise CanonicalParserShadowReliabilityCertificationError(
            "Reliability assessment non certificabile.",
            code="SHADOW_RELIABILITY_CERTIFICATION_BLOCKED",
            status_code=409,
        )
    assessment = preview["assessment"]
    certification = CanonicalParserShadowReliabilityCertification(
        certification_id=str(uuid4()),
        certification_key=preview["certification_key"],
        assessment_db_id=preview["assessment_db_id"],
        assessment_id=assessment["assessment_id"],
        assessment_key=assessment["assessment_key"],
        worker_generation=int(assessment.get("worker_generation", 0)),
        lease_epoch=int(assessment.get("lease_epoch", 0)),
        worker_event_hash=assessment.get("worker_event_hash"),
        status="ACTIVE",
        evidence_hash=assessment["evidence_hash"],
        policy_version=SHADOW_RELIABILITY_CERTIFICATION_POLICY_VERSION,
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
            "paper_projection_connected": False,
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
            CanonicalParserShadowReliabilityCertificationEvent(
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
            select(CanonicalParserShadowReliabilityCertification).where(
                CanonicalParserShadowReliabilityCertification.certification_key
                == preview["certification_key"]
            )
        )
        if existing is not None:
            return _serialize(existing)
        raise CanonicalParserShadowReliabilityCertificationError(
            "Conflitto durante la reliability certification.",
            code="SHADOW_RELIABILITY_CERTIFICATION_CONFLICT",
            status_code=409,
        ) from exc
    db.refresh(certification)
    return _serialize(certification)


def revoke_shadow_reliability_certification(
    db: Session,
    *,
    certification_id: str,
    confirmation: str,
    reason: str,
    actor_label: str | None = None,
    revoked_at: datetime | None = None,
) -> dict[str, Any]:
    certification = db.scalar(
        select(CanonicalParserShadowReliabilityCertification).where(
            CanonicalParserShadowReliabilityCertification.certification_id == certification_id
        )
    )
    if certification is None:
        raise CanonicalParserShadowReliabilityCertificationError(
            "Reliability certification non trovata.",
            code="SHADOW_RELIABILITY_CERTIFICATION_NOT_FOUND",
            status_code=404,
        )
    expected = f"{SHADOW_RELIABILITY_CERTIFICATION_REVOKE_PREFIX}:{certification.certification_id}"
    if confirmation != expected:
        raise CanonicalParserShadowReliabilityCertificationError(
            "Conferma revoca non valida.",
            code="SHADOW_RELIABILITY_CERTIFICATION_REVOKE_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if certification.status == "REVOKED":
        return _serialize(certification)
    now = _aware(revoked_at)
    previous = certification.status
    certification.status = "REVOKED"
    certification.revoked_at = now
    certification.revocation_reason = _note(reason)
    _append_event(
        db,
        certification,
        event_type="REVOKED",
        previous_status=previous,
        new_status="REVOKED",
        actor_label=_actor(actor_label),
        reason=certification.revocation_reason,
        occurred_at=now,
    )
    db.commit()
    db.refresh(certification)
    return _serialize(certification)


def get_shadow_reliability_certification(
    db: Session, certification_id: str
) -> dict[str, Any]:
    certification = db.scalar(
        select(CanonicalParserShadowReliabilityCertification).where(
            CanonicalParserShadowReliabilityCertification.certification_id == certification_id
        )
    )
    if certification is None:
        raise CanonicalParserShadowReliabilityCertificationError(
            "Reliability certification non trovata.",
            code="SHADOW_RELIABILITY_CERTIFICATION_NOT_FOUND",
            status_code=404,
        )
    payload = _serialize(certification)
    payload["event_chain_reason_codes"] = _verify_event_chain(db, certification)
    return payload


def resolve_shadow_reliability_certification(
    db: Session,
    *,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    certification = db.scalar(
        select(CanonicalParserShadowReliabilityCertification)
        .order_by(CanonicalParserShadowReliabilityCertification.certified_at.desc())
        .limit(1)
    )
    if certification is None:
        return {
            "resolved_status": "UNCERTIFIED",
            "certification_id": None,
            "paper_projection_authorized": False,
            "paper_execution_authorized": False,
            "live_execution_authorized": False,
        }
    payload = _serialize(certification)
    chain_reasons = _verify_event_chain(db, certification)
    if chain_reasons:
        payload["resolved_status"] = "DRIFTED"
        payload["reason_codes"] = chain_reasons
        return payload
    if certification.status == "REVOKED":
        payload["resolved_status"] = "REVOKED"
        return payload
    if _aware(certification.expires_at) <= now:
        payload["resolved_status"] = "EXPIRED"
        return payload
    reliability = resolve_shadow_reliability(
        db, settings_object=settings_object, evaluated_at=now
    )
    if (
        reliability.get("resolved_status") != "READY"
        or reliability.get("assessment_id") != certification.assessment_id
        or reliability.get("assessment_key") != certification.assessment_key
        or reliability.get("evidence_hash") != certification.evidence_hash
        or int(reliability.get("worker_generation", 0)) != certification.worker_generation
        or int(reliability.get("lease_epoch", 0)) != certification.lease_epoch
        or reliability.get("worker_event_hash") != certification.worker_event_hash
    ):
        payload["resolved_status"] = "DRIFTED"
        payload["reason_codes"] = ["SHADOW_RELIABILITY_CERTIFICATION_EVIDENCE_DRIFT"]
        return payload
    current_policy_hash = calculate_payload_hash(_policy_snapshot(settings_object))
    if current_policy_hash != certification.policy_hash:
        payload["resolved_status"] = "DRIFTED"
        payload["reason_codes"] = ["SHADOW_RELIABILITY_CERTIFICATION_POLICY_DRIFT"]
        return payload
    payload["resolved_status"] = "CERTIFIED"
    payload["paper_projection_authorized"] = True
    return payload


def get_shadow_reliability_certification_status(
    db: Session,
    *,
    settings_object: Any = settings,
) -> dict[str, Any]:
    return {
        "enabled": bool(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_RELIABILITY_CERTIFICATION_ENABLED", False)
        ),
        "policy": _policy_snapshot(settings_object),
        "certification_count": int(
            db.scalar(select(func.count(CanonicalParserShadowReliabilityCertification.id))) or 0
        ),
        "event_count": int(
            db.scalar(select(func.count(CanonicalParserShadowReliabilityCertificationEvent.id))) or 0
        ),
        "operational_guards": {
            "manual_certification_only": True,
            "paper_projection_connected": False,
            "paper_execution_authorized": False,
            "live_execution_authorized": False,
            "network_allowed": False,
            "writes_trades": False,
        },
    }
