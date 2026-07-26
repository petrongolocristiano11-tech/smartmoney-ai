from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserShadowAutomationPermit,
    CanonicalParserShadowAutomationPermitEvent,
    CanonicalParserShadowReadinessAssessment,
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
from backend.app.services.blockchain_parser_shadow_readiness_service import (
    resolve_shadow_consumer_readiness,
)
from backend.app.services.blockchain_parser_shadow_runtime_lease_service import (
    LEASE_CONSUMER,
)

AUTOMATION_PERMIT_POLICY_VERSION = "canonical-parser-shadow-automation-permit/1"
AUTOMATION_PERMIT_CONFIRMATION_PREFIX = (
    "ISSUE_CERTIFIED_SHADOW_AUTOMATION_PERMIT"
)
AUTOMATION_PERMIT_REVOKE_PREFIX = (
    "REVOKE_CERTIFIED_SHADOW_AUTOMATION_PERMIT"
)
AUTOMATION_PERMIT_CONSUMER = "CERTIFIED_SHADOW_AUTOMATION"
_MAX_ACTOR_LENGTH = 80
_MAX_NOTE_LENGTH = 500


class CanonicalParserShadowAutomationPermitError(ValueError):
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
        "policy_version": AUTOMATION_PERMIT_POLICY_VERSION,
        "scope": RUNTIME_SCOPE,
        "channel": RUNTIME_CHANNEL,
        "runtime_consumer": LEASE_CONSUMER,
        "permit_consumer": AUTOMATION_PERMIT_CONSUMER,
        "maximum_validity_minutes": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_MAX_VALIDITY_MINUTES",
                10,
            )
        ),
        "minimum_readiness_remaining_minutes": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_MIN_READINESS_REMAINING_MINUTES",
                2,
            )
        ),
        "maximum_run_budget": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_MAX_RUN_BUDGET",
                5,
            )
        ),
        "maximum_event_budget": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_MAX_EVENT_BUDGET",
                100,
            )
        ),
        "requires_ready_assessment": True,
        "requires_current_certified_lease": True,
        "bounded_run_budget": True,
        "bounded_event_budget": True,
        "fail_closed_on_drift": True,
        "manual_issue_only": True,
        "manual_revoke_only": True,
        "budget_consumption_connected": False,
        "scheduler_connected": False,
        "worker_connected": False,
        "automatic_execution": False,
        "external_requests_allowed": False,
        "writes_trades": False,
        "writes_canonical_materialization": False,
        "live_execution": False,
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


def _verify_event_chain(
    db: Session, permit: CanonicalParserShadowAutomationPermit
) -> list[str]:
    events = list(
        db.scalars(
            select(CanonicalParserShadowAutomationPermitEvent)
            .where(
                CanonicalParserShadowAutomationPermitEvent.permit_db_id
                == permit.id
            )
            .order_by(
                CanonicalParserShadowAutomationPermitEvent.sequence.asc()
            )
        )
    )
    reasons: set[str] = set()
    previous_hash: str | None = None
    for expected_sequence, event in enumerate(events, start=1):
        if event.sequence != expected_sequence:
            reasons.add("AUTOMATION_PERMIT_EVENT_SEQUENCE_INVALID")
        if event.previous_event_hash != previous_hash:
            reasons.add("AUTOMATION_PERMIT_EVENT_PREVIOUS_HASH_INVALID")
        if calculate_payload_hash(event.event_payload) != event.event_hash:
            reasons.add("AUTOMATION_PERMIT_EVENT_HASH_INVALID")
        previous_hash = event.event_hash
    if not events:
        reasons.add("AUTOMATION_PERMIT_EVENT_CHAIN_EMPTY")
    elif permit.latest_event_sequence != events[-1].sequence:
        reasons.add("AUTOMATION_PERMIT_LATEST_SEQUENCE_INVALID")
    elif permit.latest_event_hash != events[-1].event_hash:
        reasons.add("AUTOMATION_PERMIT_LATEST_HASH_INVALID")
    return sorted(reasons)


def _serialize(permit: CanonicalParserShadowAutomationPermit) -> dict[str, Any]:
    remaining_run_budget = max(
        0, int(permit.run_budget) - int(permit.consumed_run_count)
    )
    remaining_event_budget = max(
        0, int(permit.event_budget) - int(permit.consumed_event_count)
    )
    return {
        "permit_id": permit.permit_id,
        "permit_key": permit.permit_key,
        "permit_generation": permit.permit_generation,
        "assessment_id": permit.assessment_id,
        "assessment_key": permit.assessment_key,
        "lease_id": permit.lease_id,
        "certification_id": permit.certification_id,
        "binding_id": permit.binding_id,
        "promotion_id": permit.promotion_id,
        "scope": permit.scope,
        "channel": permit.channel,
        "consumer": permit.consumer,
        "status": permit.status,
        "parser_name": permit.parser_name,
        "parser_version": permit.parser_version,
        "parser_implementation_hash": permit.parser_implementation_hash,
        "output_schema_version": permit.output_schema_version,
        "release_manifest_hash": permit.release_manifest_hash,
        "lease_event_hash": permit.lease_event_hash,
        "certification_event_hash": permit.certification_event_hash,
        "readiness_policy_hash": permit.readiness_policy_hash,
        "readiness_evidence_hash": permit.readiness_evidence_hash,
        "permit_policy_version": permit.permit_policy_version,
        "permit_policy_hash": permit.permit_policy_hash,
        "permit_policy_snapshot": permit.permit_policy_snapshot,
        "requested_validity_minutes": permit.requested_validity_minutes,
        "run_budget": permit.run_budget,
        "event_budget": permit.event_budget,
        "consumed_run_count": permit.consumed_run_count,
        "consumed_event_count": permit.consumed_event_count,
        "remaining_run_budget": remaining_run_budget,
        "remaining_event_budget": remaining_event_budget,
        "actor_label": permit.actor_label,
        "note": permit.note,
        "issued_at": permit.issued_at,
        "expires_at": permit.expires_at,
        "revoked_at": permit.revoked_at,
        "revocation_reason": permit.revocation_reason,
        "latest_event_sequence": permit.latest_event_sequence,
        "latest_event_hash": permit.latest_event_hash,
        "technical_metadata": permit.technical_metadata,
    }


def _append_terminal_event(
    db: Session,
    *,
    permit: CanonicalParserShadowAutomationPermit,
    event_type: str,
    new_status: str,
    actor_label: str,
    reason: str,
    occurred_at: datetime,
) -> None:
    if _verify_event_chain(db, permit):
        raise CanonicalParserShadowAutomationPermitError(
            "Audit chain automation permit non integra.",
            code="PARSER_SHADOW_AUTOMATION_PERMIT_AUDIT_CHAIN_INVALID",
            status_code=409,
        )
    sequence = permit.latest_event_sequence + 1
    event_id = str(uuid4())
    payload = _event_payload(
        event_id=event_id,
        permit_id=permit.permit_id,
        sequence=sequence,
        event_type=event_type,
        previous_status=permit.status,
        new_status=new_status,
        actor_label=actor_label,
        reason=reason,
        previous_event_hash=permit.latest_event_hash,
        occurred_at=occurred_at,
    )
    event_hash = calculate_payload_hash(payload)
    db.add(
        CanonicalParserShadowAutomationPermitEvent(
            event_id=event_id,
            permit_db_id=permit.id,
            sequence=sequence,
            event_type=event_type,
            previous_status=permit.status,
            new_status=new_status,
            actor_label=actor_label,
            reason=reason,
            event_payload=payload,
            previous_event_hash=permit.latest_event_hash,
            event_hash=event_hash,
            occurred_at=occurred_at,
        )
    )
    permit.status = new_status
    permit.latest_event_sequence = sequence
    permit.latest_event_hash = event_hash
    if new_status == "REVOKED":
        permit.revoked_at = occurred_at
        permit.revocation_reason = reason


def _expire_stale_active_permits(
    db: Session, *, evaluated_at: datetime
) -> list[str]:
    expired_ids: list[str] = []
    permits = list(
        db.scalars(
            select(CanonicalParserShadowAutomationPermit).where(
                CanonicalParserShadowAutomationPermit.consumer
                == AUTOMATION_PERMIT_CONSUMER,
                CanonicalParserShadowAutomationPermit.status == "ACTIVE",
                CanonicalParserShadowAutomationPermit.expires_at <= evaluated_at,
            )
        )
    )
    for permit in permits:
        _append_terminal_event(
            db,
            permit=permit,
            event_type="EXPIRED",
            new_status="EXPIRED",
            actor_label="SYSTEM_EXPIRY",
            reason="AUTOMATION_PERMIT_VALIDITY_WINDOW_ELAPSED",
            occurred_at=evaluated_at,
        )
        expired_ids.append(permit.permit_id)
    return expired_ids


def preview_shadow_automation_permit(
    db: Session,
    *,
    assessment_id: str | None = None,
    validity_minutes: int = 5,
    run_budget: int = 3,
    event_budget: int = 50,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _policy_snapshot(settings_object)
    policy_hash = calculate_payload_hash(policy)
    blockers: set[str] = set()

    requested_validity = int(validity_minutes)
    requested_run_budget = int(run_budget)
    requested_event_budget = int(event_budget)
    if requested_validity < 1:
        blockers.add("AUTOMATION_PERMIT_VALIDITY_BELOW_MINIMUM")
    if requested_validity > policy["maximum_validity_minutes"]:
        blockers.add("AUTOMATION_PERMIT_VALIDITY_ABOVE_MAXIMUM")
    if requested_run_budget < 1:
        blockers.add("AUTOMATION_PERMIT_RUN_BUDGET_BELOW_MINIMUM")
    if requested_run_budget > policy["maximum_run_budget"]:
        blockers.add("AUTOMATION_PERMIT_RUN_BUDGET_ABOVE_MAXIMUM")
    if requested_event_budget < 1:
        blockers.add("AUTOMATION_PERMIT_EVENT_BUDGET_BELOW_MINIMUM")
    if requested_event_budget > policy["maximum_event_budget"]:
        blockers.add("AUTOMATION_PERMIT_EVENT_BUDGET_ABOVE_MAXIMUM")

    readiness_resolution = resolve_shadow_consumer_readiness(
        db,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=now,
    )
    readiness_payload = readiness_resolution.get("assessment") or {}
    resolved_assessment_id = readiness_payload.get("assessment_id")
    if assessment_id and str(assessment_id).strip() != resolved_assessment_id:
        blockers.add("AUTOMATION_PERMIT_ASSESSMENT_ID_MISMATCH")
    if not readiness_resolution.get("resolved"):
        blockers.update(
            readiness_resolution.get("reason_codes")
            or ["SHADOW_READINESS_UNRESOLVED"]
        )
    if not readiness_resolution.get("consumer_authorized"):
        blockers.add("SHADOW_READINESS_NOT_AUTHORIZED")
    if readiness_resolution.get("status") != "READY":
        blockers.add("SHADOW_READINESS_NOT_READY")
    if not resolved_assessment_id:
        blockers.add("SHADOW_READINESS_ASSESSMENT_MISSING")

    assessment = None
    if resolved_assessment_id:
        assessment = db.scalar(
            select(CanonicalParserShadowReadinessAssessment).where(
                CanonicalParserShadowReadinessAssessment.assessment_id
                == resolved_assessment_id
            )
        )
    if assessment is None:
        blockers.add("SHADOW_READINESS_ASSESSMENT_ROW_MISSING")

    readiness_remaining_minutes: float | None = None
    expires_at: datetime | None = None
    if assessment is not None:
        readiness_remaining_minutes = round(
            (_aware(assessment.valid_until) - now).total_seconds() / 60.0,
            4,
        )
        if readiness_remaining_minutes < policy[
            "minimum_readiness_remaining_minutes"
        ]:
            blockers.add("SHADOW_READINESS_REMAINING_WINDOW_TOO_SHORT")
        expires_at = min(
            now + timedelta(minutes=requested_validity),
            _aware(assessment.valid_until),
        )

    active = db.scalar(
        select(CanonicalParserShadowAutomationPermit)
        .where(
            CanonicalParserShadowAutomationPermit.consumer
            == AUTOMATION_PERMIT_CONSUMER,
            CanonicalParserShadowAutomationPermit.status == "ACTIVE",
            CanonicalParserShadowAutomationPermit.expires_at > now,
        )
        .order_by(
            CanonicalParserShadowAutomationPermit.issued_at.desc(),
            CanonicalParserShadowAutomationPermit.id.desc(),
        )
    )
    if active is not None:
        blockers.add("ACTIVE_SHADOW_AUTOMATION_PERMIT_EXISTS")

    permit_manifest = {
        "assessment_id": resolved_assessment_id,
        "assessment_key": readiness_payload.get("assessment_key"),
        "lease_id": readiness_payload.get("lease_id"),
        "certification_id": readiness_payload.get("certification_id"),
        "binding_id": readiness_payload.get("binding_id"),
        "promotion_id": readiness_payload.get("promotion_id"),
        "parser_name": readiness_payload.get("parser_name"),
        "parser_version": readiness_payload.get("parser_version"),
        "parser_implementation_hash": readiness_payload.get(
            "parser_implementation_hash"
        ),
        "output_schema_version": readiness_payload.get("output_schema_version"),
        "release_manifest_hash": readiness_payload.get("release_manifest_hash"),
        "readiness_policy_hash": readiness_payload.get("readiness_policy_hash"),
        "readiness_evidence_hash": readiness_payload.get("evidence_hash"),
        "permit_policy_hash": policy_hash,
        "requested_validity_minutes": requested_validity,
        "run_budget": requested_run_budget,
        "event_budget": requested_event_budget,
        "evaluated_at": now.isoformat(),
        "expires_at": expires_at.isoformat() if expires_at else None,
    }
    permit_key = calculate_payload_hash(permit_manifest)
    confirmation = (
        f"{AUTOMATION_PERMIT_CONFIRMATION_PREFIX}:"
        f"{resolved_assessment_id or 'UNRESOLVED'}:{permit_key[:16]}"
    )
    return {
        "issuable": not blockers,
        "reason_codes": sorted(blockers),
        "assessment_id": resolved_assessment_id,
        "assessment": sanitize_technical_metadata(readiness_payload),
        "readiness_resolution": sanitize_technical_metadata(
            readiness_resolution
        ),
        "readiness_remaining_minutes": readiness_remaining_minutes,
        "requested_validity_minutes": requested_validity,
        "run_budget": requested_run_budget,
        "event_budget": requested_event_budget,
        "expires_at": expires_at,
        "permit_policy": policy,
        "permit_policy_hash": policy_hash,
        "permit_manifest": permit_manifest,
        "permit_key": permit_key,
        "confirmation": confirmation,
        "permit_enabled": bool(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_ENABLED",
                False,
            )
        ),
        "writes_database": False,
        "budget_consumption_connected": False,
        "scheduler_connected": False,
        "worker_connected": False,
        "automatic_execution": False,
        "external_requests": 0,
        "writes_trades": False,
        "writes_canonical_materialization": False,
        "live_execution": False,
    }


def issue_shadow_automation_permit(
    db: Session,
    *,
    confirmation: str,
    assessment_id: str | None = None,
    validity_minutes: int = 5,
    run_budget: int = 3,
    event_budget: int = 50,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    issued_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(
        getattr(
            settings_object,
            "CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_ENABLED",
            False,
        )
    ):
        raise CanonicalParserShadowAutomationPermitError(
            "Shadow automation permit disabilitato.",
            code="CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_DISABLED",
            status_code=409,
        )
    decision_time = _aware(issued_at)
    expired_ids = _expire_stale_active_permits(
        db, evaluated_at=decision_time
    )
    if expired_ids:
        db.commit()

    preview = preview_shadow_automation_permit(
        db,
        assessment_id=assessment_id,
        validity_minutes=validity_minutes,
        run_budget=run_budget,
        event_budget=event_budget,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=decision_time,
    )
    if str(confirmation or "").strip() != preview["confirmation"]:
        raise CanonicalParserShadowAutomationPermitError(
            "Conferma automation permit non valida o non aggiornata.",
            code="SHADOW_AUTOMATION_PERMIT_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if not preview["issuable"]:
        raise CanonicalParserShadowAutomationPermitError(
            "Automation permit non emettibile con l'evidenza corrente.",
            code="SHADOW_AUTOMATION_PERMIT_NOT_ISSUABLE",
            status_code=409,
        )

    existing = db.scalar(
        select(CanonicalParserShadowAutomationPermit).where(
            CanonicalParserShadowAutomationPermit.permit_key
            == preview["permit_key"]
        )
    )
    if existing is not None:
        payload = _serialize(existing)
        payload["created"] = False
        payload["expired_permit_ids"] = expired_ids
        return payload

    assessment = db.scalar(
        select(CanonicalParserShadowReadinessAssessment).where(
            CanonicalParserShadowReadinessAssessment.assessment_id
            == preview["assessment_id"]
        )
    )
    if assessment is None:
        raise CanonicalParserShadowAutomationPermitError(
            "Shadow readiness assessment non trovato.",
            code="SHADOW_AUTOMATION_PERMIT_ASSESSMENT_MISSING",
            status_code=409,
        )

    generation = int(
        db.scalar(
            select(func.max(CanonicalParserShadowAutomationPermit.permit_generation))
            .where(
                CanonicalParserShadowAutomationPermit.consumer
                == AUTOMATION_PERMIT_CONSUMER
            )
        )
        or 0
    ) + 1
    actor = _actor(actor_label)
    permit_id = str(uuid4())
    event_id = str(uuid4())
    event_payload = _event_payload(
        event_id=event_id,
        permit_id=permit_id,
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
    expires_at = _aware(preview["expires_at"])
    permit = CanonicalParserShadowAutomationPermit(
        permit_id=permit_id,
        permit_key=preview["permit_key"],
        permit_generation=generation,
        assessment_db_id=assessment.id,
        assessment_id=assessment.assessment_id,
        assessment_key=assessment.assessment_key,
        lease_id=assessment.lease_id,
        certification_id=assessment.certification_id,
        binding_id=assessment.binding_id,
        promotion_id=assessment.promotion_id,
        scope=assessment.scope,
        channel=assessment.channel,
        consumer=AUTOMATION_PERMIT_CONSUMER,
        status="ACTIVE",
        parser_name=assessment.parser_name,
        parser_version=assessment.parser_version,
        parser_implementation_hash=assessment.parser_implementation_hash,
        output_schema_version=assessment.output_schema_version,
        release_manifest_hash=assessment.release_manifest_hash,
        lease_event_hash=assessment.lease_event_hash,
        certification_event_hash=assessment.certification_event_hash,
        readiness_policy_hash=assessment.readiness_policy_hash,
        readiness_evidence_hash=assessment.evidence_hash,
        permit_policy_version=AUTOMATION_PERMIT_POLICY_VERSION,
        permit_policy_hash=preview["permit_policy_hash"],
        permit_policy_snapshot=preview["permit_policy"],
        requested_validity_minutes=preview["requested_validity_minutes"],
        run_budget=preview["run_budget"],
        event_budget=preview["event_budget"],
        consumed_run_count=0,
        consumed_event_count=0,
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
            "manual_issue_only": True,
            "budget_consumption_connected": False,
            "scheduler_connected": False,
            "worker_connected": False,
            "automatic_execution": False,
            "external_requests": 0,
            "writes_trades": False,
            "writes_canonical_materialization": False,
            "live_execution": False,
        },
    )
    db.add(permit)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(CanonicalParserShadowAutomationPermit).where(
                CanonicalParserShadowAutomationPermit.permit_key
                == preview["permit_key"]
            )
        )
        if existing is not None:
            payload = _serialize(existing)
            payload["created"] = False
            payload["expired_permit_ids"] = expired_ids
            return payload
        raise

    db.add(
        CanonicalParserShadowAutomationPermitEvent(
            event_id=event_id,
            permit_db_id=permit.id,
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
    db.refresh(permit)
    payload = _serialize(permit)
    payload["created"] = True
    payload["expired_permit_ids"] = expired_ids
    return payload


def revoke_shadow_automation_permit(
    db: Session,
    *,
    permit_id: str,
    confirmation: str,
    reason: str,
    actor_label: str | None = None,
    settings_object: Any = settings,
    revoked_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(
        getattr(
            settings_object,
            "CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_ENABLED",
            False,
        )
    ):
        raise CanonicalParserShadowAutomationPermitError(
            "Shadow automation permit disabilitato.",
            code="CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_DISABLED",
            status_code=409,
        )
    permit = db.scalar(
        select(CanonicalParserShadowAutomationPermit).where(
            CanonicalParserShadowAutomationPermit.permit_id
            == str(permit_id or "").strip()
        )
    )
    if permit is None:
        raise CanonicalParserShadowAutomationPermitError(
            "Shadow automation permit non trovato.",
            code="SHADOW_AUTOMATION_PERMIT_NOT_FOUND",
            status_code=404,
        )
    expected = f"{AUTOMATION_PERMIT_REVOKE_PREFIX}:{permit.permit_id}"
    if str(confirmation or "").strip() != expected:
        raise CanonicalParserShadowAutomationPermitError(
            "Conferma revoca automation permit non valida.",
            code="SHADOW_AUTOMATION_PERMIT_REVOKE_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    sanitized_reason = _note(reason)
    if not sanitized_reason:
        raise CanonicalParserShadowAutomationPermitError(
            "Motivazione revoca obbligatoria.",
            code="SHADOW_AUTOMATION_PERMIT_REVOKE_REASON_REQUIRED",
        )
    if permit.status in {"REVOKED", "EXPIRED", "EXHAUSTED"}:
        payload = _serialize(permit)
        payload["updated"] = False
        return payload
    decision_time = _aware(revoked_at)
    _append_terminal_event(
        db,
        permit=permit,
        event_type="REVOKED",
        new_status="REVOKED",
        actor_label=_actor(actor_label),
        reason=sanitized_reason,
        occurred_at=decision_time,
    )
    db.commit()
    db.refresh(permit)
    payload = _serialize(permit)
    payload["updated"] = True
    return payload


def get_shadow_automation_permit(
    db: Session, permit_id: str
) -> dict[str, Any]:
    permit = db.scalar(
        select(CanonicalParserShadowAutomationPermit).where(
            CanonicalParserShadowAutomationPermit.permit_id
            == str(permit_id or "").strip()
        )
    )
    if permit is None:
        raise CanonicalParserShadowAutomationPermitError(
            "Shadow automation permit non trovato.",
            code="SHADOW_AUTOMATION_PERMIT_NOT_FOUND",
            status_code=404,
        )
    payload = _serialize(permit)
    payload["audit_chain_valid"] = not _verify_event_chain(db, permit)
    payload["revoke_confirmation"] = (
        f"{AUTOMATION_PERMIT_REVOKE_PREFIX}:{permit.permit_id}"
    )
    return payload


def resolve_shadow_automation_permit(
    db: Session,
    *,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    permit_enabled = bool(
        getattr(
            settings_object,
            "CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_ENABLED",
            False,
        )
    )
    permit = db.scalar(
        select(CanonicalParserShadowAutomationPermit)
        .where(
            CanonicalParserShadowAutomationPermit.consumer
            == AUTOMATION_PERMIT_CONSUMER,
            CanonicalParserShadowAutomationPermit.status == "ACTIVE",
        )
        .order_by(
            CanonicalParserShadowAutomationPermit.issued_at.desc(),
            CanonicalParserShadowAutomationPermit.id.desc(),
        )
    )
    if permit is None:
        return {
            "resolved": False,
            "status": "UNPERMITTED",
            "reason_codes": ["ACTIVE_SHADOW_AUTOMATION_PERMIT_MISSING"],
            "permit_enabled": permit_enabled,
            "automation_authorized": False,
            "budget_consumption_connected": False,
            "scheduler_connected": False,
            "worker_connected": False,
            "automatic_execution": False,
            "live_execution": False,
        }

    reasons: set[str] = set(_verify_event_chain(db, permit))
    if _aware(permit.expires_at) <= now:
        reasons.add("SHADOW_AUTOMATION_PERMIT_EXPIRED")
    if calculate_payload_hash(permit.permit_policy_snapshot) != permit.permit_policy_hash:
        reasons.add("SHADOW_AUTOMATION_PERMIT_POLICY_HASH_INVALID")
    current_policy_hash = calculate_payload_hash(_policy_snapshot(settings_object))
    if current_policy_hash != permit.permit_policy_hash:
        reasons.add("SHADOW_AUTOMATION_PERMIT_POLICY_DRIFT")
    if permit.consumed_run_count < 0 or permit.consumed_run_count > permit.run_budget:
        reasons.add("SHADOW_AUTOMATION_PERMIT_RUN_BUDGET_INVALID")
    if permit.consumed_event_count < 0 or permit.consumed_event_count > permit.event_budget:
        reasons.add("SHADOW_AUTOMATION_PERMIT_EVENT_BUDGET_INVALID")
    run_exhausted = permit.consumed_run_count >= permit.run_budget
    event_exhausted = permit.consumed_event_count >= permit.event_budget
    if run_exhausted:
        reasons.add("SHADOW_AUTOMATION_PERMIT_RUN_BUDGET_EXHAUSTED")
    if event_exhausted:
        reasons.add("SHADOW_AUTOMATION_PERMIT_EVENT_BUDGET_EXHAUSTED")

    readiness_resolution = resolve_shadow_consumer_readiness(
        db,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=now,
    )
    if not readiness_resolution.get("resolved"):
        reasons.update(
            readiness_resolution.get("reason_codes")
            or ["SHADOW_READINESS_UNRESOLVED"]
        )
    readiness_payload = readiness_resolution.get("assessment") or {}
    comparisons = {
        "SHADOW_AUTOMATION_PERMIT_ASSESSMENT_DRIFT": (
            permit.assessment_id,
            readiness_payload.get("assessment_id"),
        ),
        "SHADOW_AUTOMATION_PERMIT_ASSESSMENT_KEY_DRIFT": (
            permit.assessment_key,
            readiness_payload.get("assessment_key"),
        ),
        "SHADOW_AUTOMATION_PERMIT_LEASE_DRIFT": (
            permit.lease_id,
            readiness_payload.get("lease_id"),
        ),
        "SHADOW_AUTOMATION_PERMIT_CERTIFICATION_DRIFT": (
            permit.certification_id,
            readiness_payload.get("certification_id"),
        ),
        "SHADOW_AUTOMATION_PERMIT_BINDING_DRIFT": (
            permit.binding_id,
            readiness_payload.get("binding_id"),
        ),
        "SHADOW_AUTOMATION_PERMIT_PROMOTION_DRIFT": (
            permit.promotion_id,
            readiness_payload.get("promotion_id"),
        ),
        "SHADOW_AUTOMATION_PERMIT_PARSER_HASH_DRIFT": (
            permit.parser_implementation_hash,
            readiness_payload.get("parser_implementation_hash"),
        ),
        "SHADOW_AUTOMATION_PERMIT_SCHEMA_DRIFT": (
            permit.output_schema_version,
            readiness_payload.get("output_schema_version"),
        ),
        "SHADOW_AUTOMATION_PERMIT_RELEASE_DRIFT": (
            permit.release_manifest_hash,
            readiness_payload.get("release_manifest_hash"),
        ),
        "SHADOW_AUTOMATION_PERMIT_LEASE_EVENT_DRIFT": (
            permit.lease_event_hash,
            readiness_payload.get("lease_event_hash"),
        ),
        "SHADOW_AUTOMATION_PERMIT_CERTIFICATION_EVENT_DRIFT": (
            permit.certification_event_hash,
            readiness_payload.get("certification_event_hash"),
        ),
        "SHADOW_AUTOMATION_PERMIT_READINESS_POLICY_DRIFT": (
            permit.readiness_policy_hash,
            readiness_payload.get("readiness_policy_hash"),
        ),
        "SHADOW_AUTOMATION_PERMIT_READINESS_EVIDENCE_DRIFT": (
            permit.readiness_evidence_hash,
            readiness_payload.get("evidence_hash"),
        ),
    }
    for reason, (expected, actual) in comparisons.items():
        if expected != actual:
            reasons.add(reason)

    assessment = db.get(
        CanonicalParserShadowReadinessAssessment, permit.assessment_db_id
    )
    if assessment is None:
        reasons.add("SHADOW_AUTOMATION_PERMIT_ASSESSMENT_ROW_MISSING")
    else:
        if assessment.status != "READY":
            reasons.add("SHADOW_AUTOMATION_PERMIT_ASSESSMENT_NOT_READY")
        if _aware(assessment.valid_until) <= now:
            reasons.add("SHADOW_AUTOMATION_PERMIT_ASSESSMENT_EXPIRED")
        if assessment.assessment_id != permit.assessment_id:
            reasons.add("SHADOW_AUTOMATION_PERMIT_ASSESSMENT_ID_INVALID")
        if assessment.assessment_key != permit.assessment_key:
            reasons.add("SHADOW_AUTOMATION_PERMIT_ASSESSMENT_KEY_INVALID")
        if calculate_payload_hash(assessment.policy_snapshot) != assessment.readiness_policy_hash:
            reasons.add("SHADOW_AUTOMATION_PERMIT_READINESS_POLICY_HASH_INVALID")
        if calculate_payload_hash(assessment.evidence_snapshot) != assessment.evidence_hash:
            reasons.add("SHADOW_AUTOMATION_PERMIT_READINESS_EVIDENCE_HASH_INVALID")

    if permit.scope != RUNTIME_SCOPE:
        reasons.add("SHADOW_AUTOMATION_PERMIT_SCOPE_INVALID")
    if permit.channel != RUNTIME_CHANNEL:
        reasons.add("SHADOW_AUTOMATION_PERMIT_CHANNEL_INVALID")
    if permit.consumer != AUTOMATION_PERMIT_CONSUMER:
        reasons.add("SHADOW_AUTOMATION_PERMIT_CONSUMER_INVALID")

    exhaustion_reasons = {
        "SHADOW_AUTOMATION_PERMIT_RUN_BUDGET_EXHAUSTED",
        "SHADOW_AUTOMATION_PERMIT_EVENT_BUDGET_EXHAUSTED",
    }
    if not reasons:
        status = "READY"
    elif reasons == {"SHADOW_AUTOMATION_PERMIT_EXPIRED"}:
        status = "EXPIRED"
    elif reasons and reasons.issubset(exhaustion_reasons):
        status = "EXHAUSTED"
    else:
        status = "DRIFTED"
    resolved = status == "READY"
    return {
        "resolved": resolved,
        "status": status,
        "reason_codes": sorted(reasons),
        "permit_enabled": permit_enabled,
        "automation_authorized": bool(
            resolved
            and permit_enabled
            and readiness_resolution.get("consumer_authorized")
        ),
        "budget_consumption_connected": False,
        "scheduler_connected": False,
        "worker_connected": False,
        "automatic_execution": False,
        "live_execution": False,
        "permit": _serialize(permit),
        "readiness_resolution": sanitize_technical_metadata(
            readiness_resolution
        ),
    }


def get_shadow_automation_permit_status(
    db: Session,
    *,
    settings_object: Any = settings,
) -> dict[str, Any]:
    counts = dict(
        db.execute(
            select(
                CanonicalParserShadowAutomationPermit.status,
                func.count(CanonicalParserShadowAutomationPermit.id),
            ).group_by(CanonicalParserShadowAutomationPermit.status)
        ).all()
    )
    return {
        "permit_enabled": bool(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_AUTOMATION_PERMIT_ENABLED",
                False,
            )
        ),
        "policy_version": AUTOMATION_PERMIT_POLICY_VERSION,
        "consumer": AUTOMATION_PERMIT_CONSUMER,
        "permit_count": int(sum(counts.values())),
        "status_counts": {
            status: int(counts.get(status, 0))
            for status in ("ACTIVE", "REVOKED", "EXPIRED", "EXHAUSTED")
        },
        "policy": _policy_snapshot(settings_object),
        "operational_guards": {
            "metadata_only": True,
            "manual_issue_only": True,
            "manual_revoke_only": True,
            "bounded_run_budget": True,
            "bounded_event_budget": True,
            "budget_consumption_connected": False,
            "scheduler_connected": False,
            "worker_connected": False,
            "automatic_execution": False,
            "external_requests": 0,
            "writes_trades": False,
            "writes_canonical_materialization": False,
            "changes_runtime_flags": False,
            "operational_pipeline_consumer": False,
            "live_execution": False,
        },
    }
