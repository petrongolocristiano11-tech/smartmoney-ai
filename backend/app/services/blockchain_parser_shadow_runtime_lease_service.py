from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserRuntimeCertification,
    CanonicalParserShadowRuntimeLease,
    CanonicalParserShadowRuntimeLeaseEvent,
)
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    sanitize_error_message,
    sanitize_technical_metadata,
)
from backend.app.services.blockchain_parser_registry_service import (
    DEFAULT_PARSER_REGISTRY,
    ParserRegistry,
)
from backend.app.services.blockchain_parser_runtime_binding_service import (
    RUNTIME_CHANNEL,
    RUNTIME_SCOPE,
)
from backend.app.services.blockchain_parser_runtime_certification_service import (
    resolve_parser_runtime_certification,
)

LEASE_POLICY_VERSION = "canonical-parser-shadow-runtime-lease/1"
LEASE_CONFIRMATION_PREFIX = "ISSUE_CERTIFIED_SHADOW_LEASE"
LEASE_REVOKE_PREFIX = "REVOKE_CERTIFIED_SHADOW_LEASE"
LEASE_CONSUMER = "CERTIFIED_SHADOW_RUNTIME"
_MAX_ACTOR_LENGTH = 80
_MAX_NOTE_LENGTH = 500


class CanonicalParserShadowRuntimeLeaseError(ValueError):
    def __init__(self, message: str, *, code: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime:
    if value is None:
        return _utc_now()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _actor(value: str | None) -> str:
    return sanitize_error_message(
        value or "LOCAL_OPERATOR", max_length=_MAX_ACTOR_LENGTH
    ) or "LOCAL_OPERATOR"


def _note(value: str | None) -> str | None:
    if not str(value or "").strip():
        return None
    return sanitize_error_message(value, max_length=_MAX_NOTE_LENGTH)


def _policy_snapshot(settings_object: Any) -> dict[str, Any]:
    return {
        "policy_version": LEASE_POLICY_VERSION,
        "scope": RUNTIME_SCOPE,
        "channel": RUNTIME_CHANNEL,
        "consumer": LEASE_CONSUMER,
        "maximum_validity_minutes": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_LEASE_MAX_VALIDITY_MINUTES",
                60,
            )
        ),
        "minimum_certification_remaining_minutes": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_LEASE_MIN_CERTIFICATION_REMAINING_MINUTES",
                15,
            )
        ),
        "requires_certified_runtime": True,
        "requires_healthy_binding": True,
        "fail_closed_on_drift": True,
        "external_requests_allowed": False,
        "trade_writes_allowed": False,
        "runtime_activation": False,
        "consumer_connected": False,
        "operational_pipeline_consumer": False,
    }


def _event_payload(
    *,
    event_id: str,
    lease_id: str,
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
        "lease_id": lease_id,
        "sequence": sequence,
        "event_type": event_type,
        "previous_status": previous_status,
        "new_status": new_status,
        "actor_label": actor_label,
        "reason": reason,
        "previous_event_hash": previous_event_hash,
        "occurred_at": _aware(occurred_at).isoformat(),
    }


def _verify_event_chain(
    db: Session, lease: CanonicalParserShadowRuntimeLease
) -> list[str]:
    events = list(
        db.scalars(
            select(CanonicalParserShadowRuntimeLeaseEvent)
            .where(
                CanonicalParserShadowRuntimeLeaseEvent.lease_db_id == lease.id
            )
            .order_by(CanonicalParserShadowRuntimeLeaseEvent.sequence.asc())
        )
    )
    reasons: list[str] = []
    previous_hash: str | None = None
    for expected_sequence, event in enumerate(events, start=1):
        if event.sequence != expected_sequence:
            reasons.append("LEASE_EVENT_SEQUENCE_INVALID")
        if event.previous_event_hash != previous_hash:
            reasons.append("LEASE_EVENT_PREVIOUS_HASH_INVALID")
        if calculate_payload_hash(event.event_payload) != event.event_hash:
            reasons.append("LEASE_EVENT_HASH_INVALID")
        previous_hash = event.event_hash
    if not events:
        reasons.append("LEASE_EVENT_CHAIN_EMPTY")
    elif lease.latest_event_sequence != events[-1].sequence:
        reasons.append("LEASE_LATEST_SEQUENCE_INVALID")
    elif lease.latest_event_hash != events[-1].event_hash:
        reasons.append("LEASE_LATEST_HASH_INVALID")
    return sorted(set(reasons))


def _serialize(lease: CanonicalParserShadowRuntimeLease) -> dict[str, Any]:
    return {
        "lease_id": lease.lease_id,
        "lease_key": lease.lease_key,
        "lease_generation": lease.lease_generation,
        "certification_id": lease.certification_id,
        "binding_id": lease.binding_id,
        "promotion_id": lease.promotion_id,
        "scope": lease.scope,
        "channel": lease.channel,
        "consumer": lease.consumer,
        "status": lease.status,
        "parser_name": lease.parser_name,
        "parser_version": lease.parser_version,
        "parser_implementation_hash": lease.parser_implementation_hash,
        "output_schema_version": lease.output_schema_version,
        "release_manifest_hash": lease.release_manifest_hash,
        "certification_event_hash": lease.certification_event_hash,
        "lease_policy_version": lease.lease_policy_version,
        "lease_policy_hash": lease.lease_policy_hash,
        "lease_policy_snapshot": lease.lease_policy_snapshot,
        "requested_validity_minutes": lease.requested_validity_minutes,
        "actor_label": lease.actor_label,
        "note": lease.note,
        "issued_at": lease.issued_at,
        "expires_at": lease.expires_at,
        "revoked_at": lease.revoked_at,
        "revocation_reason": lease.revocation_reason,
        "latest_event_sequence": lease.latest_event_sequence,
        "latest_event_hash": lease.latest_event_hash,
        "technical_metadata": lease.technical_metadata,
    }


def _append_terminal_event(
    db: Session,
    *,
    lease: CanonicalParserShadowRuntimeLease,
    event_type: str,
    new_status: str,
    actor_label: str,
    reason: str,
    occurred_at: datetime,
) -> None:
    chain_errors = _verify_event_chain(db, lease)
    if chain_errors:
        raise CanonicalParserShadowRuntimeLeaseError(
            "Audit chain lease non integra.",
            code="PARSER_SHADOW_LEASE_AUDIT_CHAIN_INVALID",
            status_code=409,
        )
    sequence = lease.latest_event_sequence + 1
    event_id = str(uuid4())
    payload = _event_payload(
        event_id=event_id,
        lease_id=lease.lease_id,
        sequence=sequence,
        event_type=event_type,
        previous_status=lease.status,
        new_status=new_status,
        actor_label=actor_label,
        reason=reason,
        previous_event_hash=lease.latest_event_hash,
        occurred_at=occurred_at,
    )
    event_hash = calculate_payload_hash(payload)
    db.add(
        CanonicalParserShadowRuntimeLeaseEvent(
            event_id=event_id,
            lease_db_id=lease.id,
            sequence=sequence,
            event_type=event_type,
            previous_status=lease.status,
            new_status=new_status,
            actor_label=actor_label,
            reason=reason,
            event_payload=payload,
            previous_event_hash=lease.latest_event_hash,
            event_hash=event_hash,
            occurred_at=occurred_at,
        )
    )
    lease.status = new_status
    lease.latest_event_sequence = sequence
    lease.latest_event_hash = event_hash
    if new_status == "REVOKED":
        lease.revoked_at = occurred_at
        lease.revocation_reason = reason


def _expire_stale_active_leases(
    db: Session, *, evaluated_at: datetime
) -> list[str]:
    expired_ids: list[str] = []
    leases = list(
        db.scalars(
            select(CanonicalParserShadowRuntimeLease).where(
                CanonicalParserShadowRuntimeLease.consumer == LEASE_CONSUMER,
                CanonicalParserShadowRuntimeLease.status == "ACTIVE",
                CanonicalParserShadowRuntimeLease.expires_at <= evaluated_at,
            )
        )
    )
    for lease in leases:
        _append_terminal_event(
            db,
            lease=lease,
            event_type="EXPIRED",
            new_status="EXPIRED",
            actor_label="SYSTEM_EXPIRY",
            reason="LEASE_VALIDITY_WINDOW_ELAPSED",
            occurred_at=evaluated_at,
        )
        expired_ids.append(lease.lease_id)
    return expired_ids


def preview_shadow_runtime_lease(
    db: Session,
    *,
    certification_id: str | None = None,
    validity_minutes: int = 30,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _policy_snapshot(settings_object)
    policy_hash = calculate_payload_hash(policy)
    blockers: set[str] = set()

    requested_validity = int(validity_minutes)
    if requested_validity < 5:
        blockers.add("LEASE_VALIDITY_TOO_SHORT")
    if requested_validity > policy["maximum_validity_minutes"]:
        blockers.add("LEASE_VALIDITY_EXCEEDS_POLICY")

    certification_resolution = resolve_parser_runtime_certification(
        db,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=now,
    )
    if not certification_resolution.get("resolved"):
        blockers.update(
            certification_resolution.get("reason_codes")
            or ["RUNTIME_CERTIFICATION_UNRESOLVED"]
        )
    certification_payload = certification_resolution.get("certification") or {}
    resolved_certification_id = certification_payload.get("certification_id")
    if certification_id and certification_id != resolved_certification_id:
        blockers.add("CERTIFICATION_ID_MISMATCH")

    certification = None
    if resolved_certification_id:
        certification = db.scalar(
            select(CanonicalParserRuntimeCertification).where(
                CanonicalParserRuntimeCertification.certification_id
                == resolved_certification_id
            )
        )
    if certification is None:
        blockers.add("CERTIFICATION_MISSING")

    remaining_seconds = 0.0
    if certification is not None:
        remaining_seconds = (
            _aware(certification.expires_at) - now
        ).total_seconds()
        required_seconds = 60 * (
            requested_validity
            + policy["minimum_certification_remaining_minutes"]
        )
        if remaining_seconds < required_seconds:
            blockers.add("CERTIFICATION_REMAINING_WINDOW_INSUFFICIENT")

    active_leases = list(
        db.scalars(
            select(CanonicalParserShadowRuntimeLease).where(
                CanonicalParserShadowRuntimeLease.consumer == LEASE_CONSUMER,
                CanonicalParserShadowRuntimeLease.status == "ACTIVE",
            )
        )
    )
    unexpired_active = [
        lease for lease in active_leases if _aware(lease.expires_at) > now
    ]
    if unexpired_active:
        blockers.add("ACTIVE_SHADOW_LEASE_EXISTS")

    lease_generation = int(
        db.scalar(
            select(func.count(CanonicalParserShadowRuntimeLease.id)).where(
                CanonicalParserShadowRuntimeLease.consumer == LEASE_CONSUMER
            )
        )
        or 0
    ) + 1

    certification_snapshot = {
        "certification_id": certification.certification_id if certification else None,
        "certification_status": certification.status if certification else None,
        "certification_event_hash": certification.latest_event_hash if certification else None,
        "certification_expires_at": (
            _aware(certification.expires_at).isoformat() if certification else None
        ),
        "binding_id": certification.binding_id if certification else None,
        "promotion_id": certification.promotion_id if certification else None,
        "scope": certification.scope if certification else None,
        "channel": certification.channel if certification else None,
        "parser_name": certification.parser_name if certification else None,
        "parser_version": certification.parser_version if certification else None,
        "parser_implementation_hash": (
            certification.parser_implementation_hash if certification else None
        ),
        "output_schema_version": (
            certification.output_schema_version if certification else None
        ),
        "release_manifest_hash": (
            certification.release_manifest_hash if certification else None
        ),
    }
    lease_key = calculate_payload_hash(
        {
            "consumer": LEASE_CONSUMER,
            "lease_generation": lease_generation,
            "certification_snapshot": certification_snapshot,
            "lease_policy_hash": policy_hash,
            "requested_validity_minutes": requested_validity,
        }
    )
    confirmation = (
        f"{LEASE_CONFIRMATION_PREFIX}:"
        f"{resolved_certification_id or 'UNCERTIFIED'}:{lease_key[:12]}"
    )
    return {
        "dry_run": True,
        "lease_enabled": bool(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_LEASE_ENABLED", False)
        ),
        "eligible": not blockers,
        "blocker_codes": sorted(blockers),
        "scope": RUNTIME_SCOPE,
        "channel": RUNTIME_CHANNEL,
        "consumer": LEASE_CONSUMER,
        "lease_generation": lease_generation,
        "requested_validity_minutes": requested_validity,
        "lease_policy": policy,
        "lease_policy_hash": policy_hash,
        "certification_resolution": sanitize_technical_metadata(
            certification_resolution
        ),
        "certification_snapshot": certification_snapshot,
        "certification_remaining_minutes": round(remaining_seconds / 60, 4),
        "lease_key": lease_key,
        "confirmation": confirmation,
        "writes_database": False,
        "writes_trades": False,
        "external_requests": 0,
        "runtime_activation": False,
        "consumer_connected": False,
    }


def issue_shadow_runtime_lease(
    db: Session,
    *,
    confirmation: str,
    certification_id: str | None = None,
    validity_minutes: int = 30,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    issued_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(
        getattr(settings_object, "CANONICAL_PARSER_SHADOW_LEASE_ENABLED", False)
    ):
        raise CanonicalParserShadowRuntimeLeaseError(
            "Shadow runtime lease disabilitata.",
            code="CANONICAL_PARSER_SHADOW_LEASE_DISABLED",
            status_code=409,
        )
    decision_time = _aware(issued_at)
    preview = preview_shadow_runtime_lease(
        db,
        certification_id=certification_id,
        validity_minutes=validity_minutes,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=decision_time,
    )
    if str(confirmation or "").strip() != preview["confirmation"]:
        raise CanonicalParserShadowRuntimeLeaseError(
            "Conferma shadow runtime lease non valida o non aggiornata.",
            code="PARSER_SHADOW_LEASE_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if not preview["eligible"]:
        raise CanonicalParserShadowRuntimeLeaseError(
            "Shadow runtime lease non idonea.",
            code="PARSER_SHADOW_LEASE_NOT_ELIGIBLE",
            status_code=409,
        )

    expired_ids = _expire_stale_active_leases(db, evaluated_at=decision_time)
    certification = db.scalar(
        select(CanonicalParserRuntimeCertification).where(
            CanonicalParserRuntimeCertification.certification_id
            == preview["certification_snapshot"]["certification_id"]
        )
    )
    if certification is None:
        db.rollback()
        raise CanonicalParserShadowRuntimeLeaseError(
            "Runtime certification non trovata.",
            code="PARSER_SHADOW_LEASE_CERTIFICATION_MISSING",
            status_code=409,
        )

    existing = db.scalar(
        select(CanonicalParserShadowRuntimeLease).where(
            CanonicalParserShadowRuntimeLease.lease_key == preview["lease_key"]
        )
    )
    if existing is not None:
        result = _serialize(existing)
        result["created"] = False
        result["expired_lease_ids"] = expired_ids
        return result

    active = db.scalar(
        select(CanonicalParserShadowRuntimeLease).where(
            CanonicalParserShadowRuntimeLease.consumer == LEASE_CONSUMER,
            CanonicalParserShadowRuntimeLease.status == "ACTIVE",
        )
    )
    if active is not None:
        db.rollback()
        raise CanonicalParserShadowRuntimeLeaseError(
            "Esiste già una shadow runtime lease attiva.",
            code="PARSER_SHADOW_LEASE_ACTIVE_EXISTS",
            status_code=409,
        )

    lease_id = str(uuid4())
    event_id = str(uuid4())
    actor = _actor(actor_label)
    event_payload = _event_payload(
        event_id=event_id,
        lease_id=lease_id,
        sequence=1,
        event_type="ISSUED",
        previous_status=None,
        new_status="ACTIVE",
        actor_label=actor,
        reason=None,
        previous_event_hash=None,
        occurred_at=decision_time,
    )
    event_hash = calculate_payload_hash(event_payload)
    expires_at = decision_time + timedelta(
        minutes=preview["requested_validity_minutes"]
    )
    lease = CanonicalParserShadowRuntimeLease(
        lease_id=lease_id,
        lease_key=preview["lease_key"],
        lease_generation=preview["lease_generation"],
        certification_db_id=certification.id,
        certification_id=certification.certification_id,
        binding_id=certification.binding_id,
        promotion_id=certification.promotion_id,
        scope=RUNTIME_SCOPE,
        channel=RUNTIME_CHANNEL,
        consumer=LEASE_CONSUMER,
        status="ACTIVE",
        parser_name=certification.parser_name,
        parser_version=certification.parser_version,
        parser_implementation_hash=certification.parser_implementation_hash,
        output_schema_version=certification.output_schema_version,
        release_manifest_hash=certification.release_manifest_hash,
        certification_event_hash=certification.latest_event_hash,
        lease_policy_version=LEASE_POLICY_VERSION,
        lease_policy_hash=preview["lease_policy_hash"],
        lease_policy_snapshot=preview["lease_policy"],
        requested_validity_minutes=preview["requested_validity_minutes"],
        actor_label=actor,
        note=_note(note),
        issued_at=decision_time,
        expires_at=expires_at,
        revoked_at=None,
        revocation_reason=None,
        latest_event_sequence=1,
        latest_event_hash=event_hash,
        technical_metadata={
            "metadata_only": True,
            "consumer_connected": False,
            "runtime_activation": False,
            "external_requests": 0,
            "writes_trades": False,
        },
    )
    db.add(lease)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(CanonicalParserShadowRuntimeLease).where(
                CanonicalParserShadowRuntimeLease.lease_key
                == preview["lease_key"]
            )
        )
        if existing is not None:
            result = _serialize(existing)
            result["created"] = False
            result["expired_lease_ids"] = expired_ids
            return result
        raise

    db.add(
        CanonicalParserShadowRuntimeLeaseEvent(
            event_id=event_id,
            lease_db_id=lease.id,
            sequence=1,
            event_type="ISSUED",
            previous_status=None,
            new_status="ACTIVE",
            actor_label=actor,
            reason=None,
            event_payload=event_payload,
            previous_event_hash=None,
            event_hash=event_hash,
            occurred_at=decision_time,
        )
    )
    db.commit()
    db.refresh(lease)
    result = _serialize(lease)
    result["created"] = True
    result["expired_lease_ids"] = expired_ids
    return result


def revoke_shadow_runtime_lease(
    db: Session,
    *,
    lease_id: str,
    confirmation: str,
    reason: str,
    actor_label: str | None = None,
    settings_object: Any = settings,
    revoked_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(
        getattr(settings_object, "CANONICAL_PARSER_SHADOW_LEASE_ENABLED", False)
    ):
        raise CanonicalParserShadowRuntimeLeaseError(
            "Shadow runtime lease disabilitata.",
            code="CANONICAL_PARSER_SHADOW_LEASE_DISABLED",
            status_code=409,
        )
    lease = db.scalar(
        select(CanonicalParserShadowRuntimeLease).where(
            CanonicalParserShadowRuntimeLease.lease_id
            == str(lease_id or "").strip()
        )
    )
    if lease is None:
        raise CanonicalParserShadowRuntimeLeaseError(
            "Shadow runtime lease non trovata.",
            code="PARSER_SHADOW_LEASE_NOT_FOUND",
            status_code=404,
        )
    expected = f"{LEASE_REVOKE_PREFIX}:{lease.lease_id}"
    if str(confirmation or "").strip() != expected:
        raise CanonicalParserShadowRuntimeLeaseError(
            "Conferma revoca lease non valida.",
            code="PARSER_SHADOW_LEASE_REVOKE_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    sanitized_reason = _note(reason)
    if not sanitized_reason:
        raise CanonicalParserShadowRuntimeLeaseError(
            "Motivazione revoca obbligatoria.",
            code="PARSER_SHADOW_LEASE_REVOKE_REASON_REQUIRED",
        )
    if lease.status in {"REVOKED", "EXPIRED"}:
        result = _serialize(lease)
        result["updated"] = False
        return result
    decision_time = _aware(revoked_at)
    _append_terminal_event(
        db,
        lease=lease,
        event_type="REVOKED",
        new_status="REVOKED",
        actor_label=_actor(actor_label),
        reason=sanitized_reason,
        occurred_at=decision_time,
    )
    db.commit()
    db.refresh(lease)
    result = _serialize(lease)
    result["updated"] = True
    return result


def get_shadow_runtime_lease(db: Session, lease_id: str) -> dict[str, Any]:
    lease = db.scalar(
        select(CanonicalParserShadowRuntimeLease).where(
            CanonicalParserShadowRuntimeLease.lease_id
            == str(lease_id or "").strip()
        )
    )
    if lease is None:
        raise CanonicalParserShadowRuntimeLeaseError(
            "Shadow runtime lease non trovata.",
            code="PARSER_SHADOW_LEASE_NOT_FOUND",
            status_code=404,
        )
    payload = _serialize(lease)
    payload["audit_chain_valid"] = not _verify_event_chain(db, lease)
    payload["revoke_confirmation"] = f"{LEASE_REVOKE_PREFIX}:{lease.lease_id}"
    return payload


def resolve_shadow_runtime_lease(
    db: Session,
    *,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    lease = db.scalar(
        select(CanonicalParserShadowRuntimeLease)
        .where(
            CanonicalParserShadowRuntimeLease.consumer == LEASE_CONSUMER,
            CanonicalParserShadowRuntimeLease.status == "ACTIVE",
        )
        .order_by(
            CanonicalParserShadowRuntimeLease.issued_at.desc(),
            CanonicalParserShadowRuntimeLease.id.desc(),
        )
    )
    lease_enabled = bool(
        getattr(settings_object, "CANONICAL_PARSER_SHADOW_LEASE_ENABLED", False)
    )
    if lease is None:
        return {
            "resolved": False,
            "status": "UNLEASED",
            "reason_codes": ["ACTIVE_SHADOW_LEASE_MISSING"],
            "lease_enabled": lease_enabled,
            "consumer_authorized": False,
            "consumer_connected": False,
            "runtime_activation": False,
        }

    reasons = set(_verify_event_chain(db, lease))
    if _aware(lease.expires_at) <= now:
        reasons.add("LEASE_EXPIRED")
    if calculate_payload_hash(lease.lease_policy_snapshot) != lease.lease_policy_hash:
        reasons.add("LEASE_POLICY_HASH_INVALID")

    certification_resolution = resolve_parser_runtime_certification(
        db,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=now,
    )
    if not certification_resolution.get("resolved"):
        reasons.update(
            certification_resolution.get("reason_codes")
            or ["RUNTIME_CERTIFICATION_UNRESOLVED"]
        )
    certification_payload = certification_resolution.get("certification") or {}
    comparisons = {
        "CERTIFICATION_ID_DRIFT": (
            lease.certification_id,
            certification_payload.get("certification_id"),
        ),
        "CERTIFICATION_EVENT_HASH_DRIFT": (
            lease.certification_event_hash,
            certification_payload.get("latest_event_hash"),
        ),
        "LEASE_BINDING_DRIFT": (
            lease.binding_id,
            certification_payload.get("binding_id"),
        ),
        "LEASE_PROMOTION_DRIFT": (
            lease.promotion_id,
            certification_payload.get("promotion_id"),
        ),
        "LEASE_PARSER_HASH_DRIFT": (
            lease.parser_implementation_hash,
            certification_payload.get("parser_implementation_hash"),
        ),
        "LEASE_SCHEMA_DRIFT": (
            lease.output_schema_version,
            certification_payload.get("output_schema_version"),
        ),
        "LEASE_RELEASE_DRIFT": (
            lease.release_manifest_hash,
            certification_payload.get("release_manifest_hash"),
        ),
    }
    for reason, (expected, actual) in comparisons.items():
        if expected != actual:
            reasons.add(reason)
    if lease.scope != RUNTIME_SCOPE:
        reasons.add("LEASE_SCOPE_INVALID")
    if lease.channel != RUNTIME_CHANNEL:
        reasons.add("LEASE_CHANNEL_INVALID")
    if lease.consumer != LEASE_CONSUMER:
        reasons.add("LEASE_CONSUMER_INVALID")

    if not reasons:
        status = "READY"
    elif reasons == {"LEASE_EXPIRED"}:
        status = "EXPIRED"
    else:
        status = "DRIFTED"
    resolved = status == "READY"
    return {
        "resolved": resolved,
        "status": status,
        "reason_codes": sorted(reasons),
        "lease_enabled": lease_enabled,
        "consumer_authorized": bool(resolved and lease_enabled),
        "consumer_connected": False,
        "runtime_activation": False,
        "lease": _serialize(lease),
        "certification_resolution": sanitize_technical_metadata(
            certification_resolution
        ),
    }


def get_shadow_runtime_lease_status(
    db: Session,
    *,
    settings_object: Any = settings,
) -> dict[str, Any]:
    counts = dict(
        db.execute(
            select(
                CanonicalParserShadowRuntimeLease.status,
                func.count(CanonicalParserShadowRuntimeLease.id),
            ).group_by(CanonicalParserShadowRuntimeLease.status)
        ).all()
    )
    return {
        "lease_enabled": bool(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_LEASE_ENABLED", False)
        ),
        "policy_version": LEASE_POLICY_VERSION,
        "consumer": LEASE_CONSUMER,
        "lease_count": int(sum(counts.values())),
        "status_counts": {
            status: int(counts.get(status, 0))
            for status in ("ACTIVE", "REVOKED", "EXPIRED")
        },
        "policy": _policy_snapshot(settings_object),
        "operational_guards": {
            "metadata_only": True,
            "manual_only": True,
            "external_requests": 0,
            "writes_trades": False,
            "starts_workers": False,
            "changes_runtime_flags": False,
            "runtime_activation": False,
            "consumer_connected": False,
            "operational_pipeline_consumer": False,
        },
    }
