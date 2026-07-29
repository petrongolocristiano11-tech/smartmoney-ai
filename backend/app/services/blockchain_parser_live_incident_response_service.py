from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserControlledLiveSubmission,
    CanonicalParserGovernedLivePosition,
    CanonicalParserLiveIncident,
    CanonicalParserLiveIncidentEvent,
    CanonicalParserLiveOnchainSettlement,
    CanonicalParserLiveRecoveryAuthorization,
)
from backend.app.services.blockchain_integrity_service import calculate_payload_hash

POLICY_VERSION = "canonical-parser-live-incident-response/1"
DECLARE_PREFIX = "DECLARE_M41_LIVE_INCIDENT"
ACK_PREFIX = "ACK_M41_LIVE_INCIDENT"
RECOVERY_PREFIX = "AUTHORIZE_M41_LIVE_RECOVERY"
REVOKE_PREFIX = "REVOKE_M41_LIVE_RECOVERY"
RESOLVE_PREFIX = "RESOLVE_M41_LIVE_INCIDENT"
_ACTIVE_INCIDENT_STATUSES = {"OPEN", "ACKNOWLEDGED", "RECOVERY_AUTHORIZED"}
_ACTIVE_RECOVERY_STATUSES = {"ACTIVE"}
_ACTIONS = {
    "RECONCILE_SUBMISSION",
    "RETRY_SETTLEMENT_READ",
    "MANUAL_POSITION_REVIEW",
    "FREEZE_NEW_SUBMISSIONS",
    "UNFREEZE_NEW_SUBMISSIONS",
}


class CanonicalParserLiveIncidentResponseError(ValueError):
    def __init__(self, message: str, *, code: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _now(value: datetime | None = None) -> datetime:
    resolved = value or datetime.now(timezone.utc)
    if resolved.tzinfo is None:
        return resolved.replace(tzinfo=timezone.utc)
    return resolved.astimezone(timezone.utc)


def _actor(value: str | None) -> str:
    return str(value or "MANUAL_OPERATOR").strip()[:80] or "MANUAL_OPERATOR"


def _note(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized[:500] if normalized else None


def _policy(settings_object: Any = settings) -> dict[str, Any]:
    return {
        "version": POLICY_VERSION,
        "enabled": bool(getattr(settings_object, "CANONICAL_PARSER_LIVE_INCIDENT_RESPONSE_ENABLED", False)),
        "submission_guard_enabled": bool(getattr(settings_object, "CANONICAL_PARSER_LIVE_INCIDENT_SUBMISSION_GUARD_ENABLED", False)),
        "stale_submission_seconds": int(getattr(settings_object, "CANONICAL_PARSER_LIVE_INCIDENT_STALE_SUBMISSION_SECONDS", 300)),
        "maximum_recovery_validity_minutes": int(getattr(settings_object, "CANONICAL_PARSER_LIVE_INCIDENT_MAX_RECOVERY_VALIDITY_MINUTES", 15)),
        "manual_only": True,
        "automatic_recovery": False,
    }


def _serialize_incident(row: CanonicalParserLiveIncident) -> dict[str, Any]:
    return {
        "incident_id": row.incident_id,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "category": row.category,
        "severity": row.severity,
        "status": row.status,
        "freeze_new_submissions": row.freeze_new_submissions,
        "reason_codes": row.reason_codes,
        "incident_snapshot": row.incident_snapshot,
        "evidence_hash": row.evidence_hash,
        "detected_at": row.detected_at,
        "acknowledged_at": row.acknowledged_at,
        "resolved_at": row.resolved_at,
        "latest_event_sequence": row.latest_event_sequence,
        "latest_event_hash": row.latest_event_hash,
    }


def _resolved_recovery_status(row: CanonicalParserLiveRecoveryAuthorization, now: datetime) -> str:
    if row.status == "ACTIVE" and _now(row.expires_at) <= now:
        return "EXPIRED"
    return row.status


def _serialize_recovery(row: CanonicalParserLiveRecoveryAuthorization, *, now: datetime | None = None) -> dict[str, Any]:
    return {
        "recovery_id": row.recovery_id,
        "incident_id": row.incident_id,
        "action": row.action,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "status": row.status,
        "resolved_status": _resolved_recovery_status(row, _now(now)),
        "recovery_snapshot": row.recovery_snapshot,
        "evidence_hash": row.evidence_hash,
        "issued_at": row.issued_at,
        "expires_at": row.expires_at,
        "revoked_at": row.revoked_at,
        "consumed_at": row.consumed_at,
    }


def _append_event(db: Session, row: CanonicalParserLiveIncident, *, event_type: str, payload: dict[str, Any], at: datetime) -> None:
    sequence = int(row.latest_event_sequence or 0) + 1
    previous_hash = row.latest_event_hash if row.latest_event_sequence else None
    body = {
        "incident_id": row.incident_id,
        "sequence": sequence,
        "event_type": event_type,
        "occurred_at": at.isoformat(),
        "payload": payload,
        "previous_event_hash": previous_hash,
    }
    event_hash = calculate_payload_hash(body)
    db.add(CanonicalParserLiveIncidentEvent(
        event_id=str(uuid4()), incident_db_id=row.id, sequence=sequence,
        event_type=event_type, event_payload=body, previous_event_hash=previous_hash,
        event_hash=event_hash, occurred_at=at,
    ))
    row.latest_event_sequence = sequence
    row.latest_event_hash = event_hash


def _source_snapshot(db: Session, *, source_type: str, source_id: str, now: datetime, policy: dict[str, Any]) -> dict[str, Any]:
    source_type = str(source_type).strip().upper()
    source_id = str(source_id).strip()
    if source_type == "SUBMISSION":
        row = db.scalar(select(CanonicalParserControlledLiveSubmission).where(CanonicalParserControlledLiveSubmission.submission_id == source_id))
        if row is None:
            raise CanonicalParserLiveIncidentResponseError("Submission M38 non trovata.", code="M41_SOURCE_NOT_FOUND", status_code=404)
        age = max(0, int((now - _now(row.reserved_at)).total_seconds()))
        reasons: list[str] = []
        category = "SUBMISSION_OBSERVATION"
        severity = "LOW"
        freeze = False
        if row.status == "RECONCILIATION_REQUIRED":
            category, severity, freeze = "SUBMISSION_OUTCOME_UNCERTAIN", "HIGH", True
            reasons.append("M38_RECONCILIATION_REQUIRED")
        elif row.status == "FAILED":
            category, severity = "SUBMISSION_ONCHAIN_FAILED", "MEDIUM"
            reasons.append("M38_SUBMISSION_FAILED")
        elif row.status in {"RESERVED", "SUBMITTED", "PROCESSED", "CONFIRMED"} and age > policy["stale_submission_seconds"]:
            category, severity, freeze = "SUBMISSION_STALE", "HIGH", True
            reasons.append("M38_SUBMISSION_STALE")
        return {"category": category, "severity": severity, "freeze_new_submissions": freeze, "reason_codes": reasons,
                "source": {"submission_id": row.submission_id, "status": row.status, "side": row.side, "token_mint": row.token_mint, "reserved_budget_sol": str(row.reserved_budget_sol), "age_seconds": age}}
    if source_type == "SETTLEMENT":
        row = db.scalar(select(CanonicalParserLiveOnchainSettlement).where(CanonicalParserLiveOnchainSettlement.settlement_id == source_id))
        if row is None:
            raise CanonicalParserLiveIncidentResponseError("Settlement M39 non trovato.", code="M41_SOURCE_NOT_FOUND", status_code=404)
        severity = "HIGH" if row.status == "BLOCKED" else "MEDIUM" if row.status in {"REVIEW", "INSUFFICIENT_DATA"} else "LOW"
        reasons = [] if row.status == "SETTLED" else [f"M39_SETTLEMENT_{row.status}"]
        return {"category": "SETTLEMENT_INTEGRITY", "severity": severity, "freeze_new_submissions": severity == "HIGH", "reason_codes": reasons,
                "source": {"settlement_id": row.settlement_id, "status": row.status, "side": row.side, "token_mint": row.token_mint, "submission_id": row.submission_id}}
    if source_type == "POSITION":
        row = db.scalar(select(CanonicalParserGovernedLivePosition).where(CanonicalParserGovernedLivePosition.position_id == source_id))
        if row is None:
            raise CanonicalParserLiveIncidentResponseError("Posizione M39 non trovata.", code="M41_SOURCE_NOT_FOUND", status_code=404)
        severity = "HIGH" if row.status == "REVIEW" else "LOW"
        reasons = ["M39_POSITION_REVIEW"] if row.status == "REVIEW" else []
        return {"category": "POSITION_INTEGRITY", "severity": severity, "freeze_new_submissions": severity == "HIGH", "reason_codes": reasons,
                "source": {"position_id": row.position_id, "status": row.status, "token_mint": row.token_mint, "quantity_raw": str(row.quantity_raw), "position_version": row.position_version}}
    if source_type == "MANUAL":
        return {"category": "MANUAL_INCIDENT", "severity": "MEDIUM", "freeze_new_submissions": False, "reason_codes": ["MANUAL_DECLARATION"], "source": {"reference": source_id}}
    raise CanonicalParserLiveIncidentResponseError("Source type M41 non valido.", code="M41_SOURCE_TYPE_INVALID")


def preview_live_incident_declaration(
    db: Session, *, source_type: str, source_id: str, category: str | None = None,
    severity: str | None = None, freeze_new_submissions: bool | None = None,
    reason_codes: list[str] | None = None, idempotency_token: str,
    settings_object: Any = settings, evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _now(evaluated_at)
    token = str(idempotency_token or "").strip()
    if len(token) < 8:
        raise CanonicalParserLiveIncidentResponseError("Idempotency token M41 non valido.", code="M41_IDEMPOTENCY_INVALID")
    policy = _policy(settings_object)
    source_type = str(source_type).strip().upper()
    source = _source_snapshot(db, source_type=source_type, source_id=source_id, now=now, policy=policy)
    resolved_severity = str(severity or source["severity"]).upper()
    if resolved_severity not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
        raise CanonicalParserLiveIncidentResponseError("Severity M41 non valida.", code="M41_SEVERITY_INVALID")
    resolved_category = str(category or source["category"]).strip().upper()[:80]
    resolved_freeze = source["freeze_new_submissions"] if freeze_new_submissions is None else bool(freeze_new_submissions)
    merged_reasons = sorted(set(source["reason_codes"] + [str(x).strip().upper()[:80] for x in (reason_codes or []) if str(x).strip()]))
    incident_key = calculate_payload_hash({"source_type": source_type, "source_id": source_id, "category": resolved_category, "idempotency_token": token, "policy_version": POLICY_VERSION})
    existing = db.scalar(select(CanonicalParserLiveIncident).where(CanonicalParserLiveIncident.incident_key == incident_key))
    snapshot = {"source_type": source_type, "source_id": source_id, "category": resolved_category, "severity": resolved_severity,
                "freeze_new_submissions": resolved_freeze, "reason_codes": merged_reasons, "source_snapshot": source["source"], "policy": policy}
    return {"status": "READY", "incident_key": incident_key, "existing_incident": None if existing is None else _serialize_incident(existing),
            "source_type": source_type, "source_id": source_id, "category": resolved_category, "severity": resolved_severity,
            "freeze_new_submissions": resolved_freeze, "reason_codes": merged_reasons, "evidence": snapshot,
            "evidence_hash": calculate_payload_hash(snapshot), "confirmation": f"{DECLARE_PREFIX}:{source_type}:{source_id}:{incident_key}", "policy": policy}


def declare_live_incident(db: Session, *, confirmation: str, actor_label: str | None = None, note: str | None = None,
                          declared_at: datetime | None = None, settings_object: Any = settings, **kwargs: Any) -> dict[str, Any]:
    policy = _policy(settings_object)
    if not policy["enabled"]:
        raise CanonicalParserLiveIncidentResponseError("M41 è disabilitata.", code="M41_DISABLED", status_code=409)
    now = _now(declared_at)
    preview = preview_live_incident_declaration(db, settings_object=settings_object, evaluated_at=now, **kwargs)
    if preview["existing_incident"] is not None:
        return preview["existing_incident"]
    if confirmation != preview["confirmation"]:
        raise CanonicalParserLiveIncidentResponseError("Conferma M41 non valida.", code="M41_CONFIRMATION_REQUIRED", status_code=409)
    incident_id = str(uuid4())
    initial_payload = {"severity": preview["severity"], "freeze_new_submissions": preview["freeze_new_submissions"]}
    initial_event_body = {
        "incident_id": incident_id,
        "sequence": 1,
        "event_type": "DECLARED",
        "occurred_at": now.isoformat(),
        "payload": initial_payload,
        "previous_event_hash": None,
    }
    initial_event_hash = calculate_payload_hash(initial_event_body)
    row = CanonicalParserLiveIncident(
        incident_id=incident_id, incident_key=preview["incident_key"], scope="M41_LIVE_INCIDENT_RESPONSE",
        source_type=preview["source_type"], source_id=preview["source_id"], category=preview["category"], severity=preview["severity"],
        status="OPEN", freeze_new_submissions=preview["freeze_new_submissions"], reason_codes=preview["reason_codes"],
        incident_snapshot=preview["evidence"], evidence_hash=preview["evidence_hash"], actor_label=_actor(actor_label), note=_note(note),
        detected_at=now, acknowledged_at=None, resolved_at=None, latest_event_sequence=1, latest_event_hash=initial_event_hash,
    )
    db.add(row); db.flush()
    db.add(CanonicalParserLiveIncidentEvent(
        event_id=str(uuid4()), incident_db_id=row.id, sequence=1, event_type="DECLARED",
        event_payload=initial_event_body, previous_event_hash=None, event_hash=initial_event_hash, occurred_at=now,
    ))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(select(CanonicalParserLiveIncident).where(CanonicalParserLiveIncident.incident_key == preview["incident_key"]))
        if existing is not None:
            return _serialize_incident(existing)
        raise CanonicalParserLiveIncidentResponseError("Conflitto incident M41.", code="M41_INCIDENT_CONFLICT", status_code=409) from exc
    db.refresh(row); return _serialize_incident(row)


def _incident(db: Session, incident_id: str, *, lock: bool = False) -> CanonicalParserLiveIncident:
    stmt = select(CanonicalParserLiveIncident).where(CanonicalParserLiveIncident.incident_id == incident_id)
    if lock: stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if row is None:
        raise CanonicalParserLiveIncidentResponseError("Incident M41 non trovato.", code="M41_INCIDENT_NOT_FOUND", status_code=404)
    return row


def acknowledge_live_incident(db: Session, *, incident_id: str, confirmation: str, actor_label: str | None = None,
                              note: str | None = None, acknowledged_at: datetime | None = None, settings_object: Any = settings) -> dict[str, Any]:
    if not _policy(settings_object)["enabled"]:
        raise CanonicalParserLiveIncidentResponseError("M41 è disabilitata.", code="M41_DISABLED", status_code=409)
    now = _now(acknowledged_at); row = _incident(db, incident_id, lock=True)
    if row.status == "RESOLVED": return _serialize_incident(row)
    expected = f"{ACK_PREFIX}:{row.incident_id}:{row.evidence_hash}"
    if confirmation != expected:
        raise CanonicalParserLiveIncidentResponseError("Conferma acknowledge M41 non valida.", code="M41_ACK_CONFIRMATION_REQUIRED", status_code=409)
    row.status = "ACKNOWLEDGED"; row.acknowledged_at = now; row.actor_label = _actor(actor_label); row.note = _note(note) or row.note
    _append_event(db, row, event_type="ACKNOWLEDGED", payload={"actor_label": row.actor_label}, at=now)
    db.commit(); db.refresh(row); return _serialize_incident(row)


def preview_live_recovery_authorization(db: Session, *, incident_id: str, action: str, validity_minutes: int,
                                         idempotency_token: str, settings_object: Any = settings, evaluated_at: datetime | None = None) -> dict[str, Any]:
    now = _now(evaluated_at); policy = _policy(settings_object); row = _incident(db, incident_id)
    action = str(action).strip().upper(); token = str(idempotency_token or "").strip()
    if action not in _ACTIONS:
        raise CanonicalParserLiveIncidentResponseError("Action M41 non valida.", code="M41_RECOVERY_ACTION_INVALID")
    if len(token) < 8:
        raise CanonicalParserLiveIncidentResponseError("Idempotency token recovery M41 non valido.", code="M41_IDEMPOTENCY_INVALID")
    minutes = int(validity_minutes)
    reasons: list[str] = []
    if row.status == "RESOLVED": reasons.append("INCIDENT_ALREADY_RESOLVED")
    if minutes < 1 or minutes > policy["maximum_recovery_validity_minutes"]: reasons.append("RECOVERY_VALIDITY_OUT_OF_RANGE")
    target_type = row.source_type; target_id = row.source_id
    expected_action = {"SUBMISSION": "RECONCILE_SUBMISSION", "SETTLEMENT": "RETRY_SETTLEMENT_READ", "POSITION": "MANUAL_POSITION_REVIEW"}.get(row.source_type)
    if action not in {expected_action, "FREEZE_NEW_SUBMISSIONS", "UNFREEZE_NEW_SUBMISSIONS"}:
        reasons.append("RECOVERY_ACTION_SOURCE_MISMATCH")
    key = calculate_payload_hash({"incident_id": incident_id, "action": action, "target_type": target_type, "target_id": target_id, "token": token, "policy_version": POLICY_VERSION})
    existing = db.scalar(select(CanonicalParserLiveRecoveryAuthorization).where(CanonicalParserLiveRecoveryAuthorization.recovery_key == key))
    snapshot = {"incident_id": incident_id, "action": action, "target_type": target_type, "target_id": target_id, "incident_evidence_hash": row.evidence_hash, "policy": policy}
    return {"status": "READY" if not reasons else "BLOCKED", "ready": not reasons, "recovery_key": key,
            "existing_recovery": None if existing is None else _serialize_recovery(existing, now=now), "incident_id": incident_id,
            "action": action, "target_type": target_type, "target_id": target_id, "reason_codes": sorted(set(reasons)),
            "expires_at": now + timedelta(minutes=minutes), "evidence": snapshot, "evidence_hash": calculate_payload_hash(snapshot),
            "confirmation": f"{RECOVERY_PREFIX}:{incident_id}:{action}:{key}", "policy": policy}


def authorize_live_recovery(db: Session, *, incident_id: str, action: str, validity_minutes: int, idempotency_token: str,
                            confirmation: str, actor_label: str | None = None, note: str | None = None,
                            issued_at: datetime | None = None, settings_object: Any = settings) -> dict[str, Any]:
    if not _policy(settings_object)["enabled"]:
        raise CanonicalParserLiveIncidentResponseError("M41 è disabilitata.", code="M41_DISABLED", status_code=409)
    now = _now(issued_at)
    preview = preview_live_recovery_authorization(db, incident_id=incident_id, action=action, validity_minutes=validity_minutes,
                                                  idempotency_token=idempotency_token, settings_object=settings_object, evaluated_at=now)
    if preview["existing_recovery"] is not None: return preview["existing_recovery"]
    if not preview["ready"]:
        raise CanonicalParserLiveIncidentResponseError("Recovery M41 bloccata.", code="M41_RECOVERY_BLOCKED", status_code=409)
    if confirmation != preview["confirmation"]:
        raise CanonicalParserLiveIncidentResponseError("Conferma recovery M41 non valida.", code="M41_RECOVERY_CONFIRMATION_REQUIRED", status_code=409)
    incident = _incident(db, incident_id, lock=True)
    row = CanonicalParserLiveRecoveryAuthorization(
        recovery_id=str(uuid4()), recovery_key=preview["recovery_key"], scope="M41_MANUAL_LIVE_RECOVERY_AUTHORIZATION",
        incident_db_id=incident.id, incident_id=incident.incident_id, action=preview["action"], target_type=preview["target_type"],
        target_id=preview["target_id"], status="ACTIVE", recovery_snapshot=preview["evidence"], evidence_hash=preview["evidence_hash"],
        actor_label=_actor(actor_label), note=_note(note), issued_at=now, expires_at=preview["expires_at"], revoked_at=None, consumed_at=None,
    )
    db.add(row); db.flush(); incident.status = "RECOVERY_AUTHORIZED"
    if row.action == "FREEZE_NEW_SUBMISSIONS": incident.freeze_new_submissions = True
    if row.action == "UNFREEZE_NEW_SUBMISSIONS": incident.freeze_new_submissions = False
    _append_event(db, incident, event_type="RECOVERY_AUTHORIZED", payload={"recovery_id": row.recovery_id, "action": row.action}, at=now)
    db.commit(); db.refresh(row); return _serialize_recovery(row, now=now)


def revoke_live_recovery(db: Session, *, recovery_id: str, confirmation: str, reason: str, actor_label: str | None = None,
                         revoked_at: datetime | None = None, settings_object: Any = settings) -> dict[str, Any]:
    if not _policy(settings_object)["enabled"]:
        raise CanonicalParserLiveIncidentResponseError("M41 è disabilitata.", code="M41_DISABLED", status_code=409)
    now = _now(revoked_at)
    row = db.scalar(select(CanonicalParserLiveRecoveryAuthorization).where(CanonicalParserLiveRecoveryAuthorization.recovery_id == recovery_id).with_for_update())
    if row is None: raise CanonicalParserLiveIncidentResponseError("Recovery M41 non trovata.", code="M41_RECOVERY_NOT_FOUND", status_code=404)
    if row.status != "ACTIVE": return _serialize_recovery(row, now=now)
    expected = f"{REVOKE_PREFIX}:{row.recovery_id}:{row.evidence_hash}"
    if confirmation != expected: raise CanonicalParserLiveIncidentResponseError("Conferma revoca M41 non valida.", code="M41_RECOVERY_REVOKE_CONFIRMATION_REQUIRED", status_code=409)
    row.status = "REVOKED"; row.revoked_at = now
    incident = _incident(db, row.incident_id, lock=True)
    if incident.status != "RESOLVED": incident.status = "ACKNOWLEDGED"
    _append_event(db, incident, event_type="RECOVERY_REVOKED", payload={"recovery_id": row.recovery_id, "reason": str(reason)[:500], "actor_label": _actor(actor_label)}, at=now)
    db.commit(); db.refresh(row); return _serialize_recovery(row, now=now)


def resolve_live_incident(db: Session, *, incident_id: str, resolution_evidence: str, confirmation: str,
                          actor_label: str | None = None, note: str | None = None, resolved_at: datetime | None = None,
                          settings_object: Any = settings) -> dict[str, Any]:
    if not _policy(settings_object)["enabled"]:
        raise CanonicalParserLiveIncidentResponseError("M41 è disabilitata.", code="M41_DISABLED", status_code=409)
    now = _now(resolved_at); row = _incident(db, incident_id, lock=True)
    if row.status == "RESOLVED": return _serialize_incident(row)
    evidence = str(resolution_evidence or "").strip()
    if len(evidence) < 8: raise CanonicalParserLiveIncidentResponseError("Evidenza risoluzione M41 insufficiente.", code="M41_RESOLUTION_EVIDENCE_REQUIRED")
    expected = f"{RESOLVE_PREFIX}:{row.incident_id}:{row.evidence_hash}"
    if confirmation != expected: raise CanonicalParserLiveIncidentResponseError("Conferma resolve M41 non valida.", code="M41_RESOLVE_CONFIRMATION_REQUIRED", status_code=409)
    row.status = "RESOLVED"; row.freeze_new_submissions = False; row.resolved_at = now; row.actor_label = _actor(actor_label); row.note = _note(note) or row.note
    _append_event(db, row, event_type="RESOLVED", payload={"resolution_evidence_hash": calculate_payload_hash({"evidence": evidence}), "actor_label": row.actor_label}, at=now)
    db.commit(); db.refresh(row); return _serialize_incident(row)


def get_live_submission_incident_guard(db: Session, *, side: str, settings_object: Any = settings, evaluated_at: datetime | None = None) -> dict[str, Any]:
    policy = _policy(settings_object); now = _now(evaluated_at)
    if not policy["submission_guard_enabled"] or str(side).upper() != "BUY":
        return {"blocked": False, "reason_codes": [], "active_incident_ids": [], "policy": policy}
    rows = list(db.scalars(select(CanonicalParserLiveIncident).where(CanonicalParserLiveIncident.status.in_(sorted(_ACTIVE_INCIDENT_STATUSES)), CanonicalParserLiveIncident.freeze_new_submissions.is_(True)).order_by(CanonicalParserLiveIncident.detected_at.asc())))
    ids = [row.incident_id for row in rows]
    return {"blocked": bool(rows), "reason_codes": ["M41_ACTIVE_INCIDENT_SUBMISSION_FREEZE"] if rows else [], "active_incident_ids": ids, "evaluated_at": now, "policy": policy}


def get_live_incident(db: Session, incident_id: str) -> dict[str, Any]:
    row = _incident(db, incident_id); result = _serialize_incident(row)
    result["events"] = [{"sequence": e.sequence, "event_type": e.event_type, "event_hash": e.event_hash, "previous_event_hash": e.previous_event_hash, "event_payload": e.event_payload, "occurred_at": e.occurred_at}
                        for e in db.scalars(select(CanonicalParserLiveIncidentEvent).where(CanonicalParserLiveIncidentEvent.incident_db_id == row.id).order_by(CanonicalParserLiveIncidentEvent.sequence.asc()))]
    return result


def get_live_recovery(db: Session, recovery_id: str) -> dict[str, Any]:
    row = db.scalar(select(CanonicalParserLiveRecoveryAuthorization).where(CanonicalParserLiveRecoveryAuthorization.recovery_id == recovery_id))
    if row is None: raise CanonicalParserLiveIncidentResponseError("Recovery M41 non trovata.", code="M41_RECOVERY_NOT_FOUND", status_code=404)
    return _serialize_recovery(row)


def resolve_live_incident_response(db: Session) -> dict[str, Any]:
    row = db.scalar(select(CanonicalParserLiveIncident).order_by(CanonicalParserLiveIncident.detected_at.desc()).limit(1))
    return {"latest_incident": None if row is None else _serialize_incident(row), "resolved_status": "EMPTY" if row is None else row.status}


def get_live_incident_response_status(db: Session, *, settings_object: Any = settings) -> dict[str, Any]:
    policy = _policy(settings_object)
    active = int(db.scalar(select(func.count(CanonicalParserLiveIncident.id)).where(CanonicalParserLiveIncident.status.in_(sorted(_ACTIVE_INCIDENT_STATUSES)))) or 0)
    frozen = int(db.scalar(select(func.count(CanonicalParserLiveIncident.id)).where(CanonicalParserLiveIncident.status.in_(sorted(_ACTIVE_INCIDENT_STATUSES)), CanonicalParserLiveIncident.freeze_new_submissions.is_(True))) or 0)
    return {"enabled": policy["enabled"], "active_incident_count": active, "submission_freeze_incident_count": frozen,
            "recovery_authorization_count": int(db.scalar(select(func.count(CanonicalParserLiveRecoveryAuthorization.id))) or 0), "policy": policy,
            "safety": {"manual_only": True, "automatic_recovery": False, "automatic_retry": False, "worker_connected": False, "scheduler_connected": False, "stream_connected": False}}
