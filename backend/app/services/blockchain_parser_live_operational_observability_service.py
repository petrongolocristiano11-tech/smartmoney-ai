from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserControlledLiveSubmission,
    CanonicalParserGovernedLivePosition,
    CanonicalParserLiveIncident,
    CanonicalParserLiveObservabilitySnapshot,
    CanonicalParserLiveOnchainSettlement,
    CanonicalParserLiveOperationalAlert,
    CanonicalParserLiveOperationalAlertEvent,
    CanonicalParserLivePortfolioRiskAssessment,
)
from backend.app.services.blockchain_integrity_service import calculate_payload_hash

POLICY_VERSION = "canonical-parser-live-operational-observability/1"
OBSERVE_PREFIX = "OBSERVE_M43_LIVE_OPERATIONS"
ALERT_PREFIX = "ISSUE_M43_OPERATIONAL_ALERT"
ACK_PREFIX = "ACK_M43_OPERATIONAL_ALERT"
RESOLVE_PREFIX = "RESOLVE_M43_OPERATIONAL_ALERT"
_ACTIVE_ALERT_STATUSES = {"OPEN", "ACKNOWLEDGED"}
_ACTIVE_INCIDENT_STATUSES = {"OPEN", "ACKNOWLEDGED", "RECOVERY_AUTHORIZED"}
_PENDING_SUBMISSION_STATUSES = {"RESERVED", "SUBMITTED", "PROCESSED", "CONFIRMED"}


class CanonicalParserLiveOperationalObservabilityError(ValueError):
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
        "enabled": bool(getattr(settings_object, "CANONICAL_PARSER_LIVE_OBSERVABILITY_ENABLED", False)),
        "alert_ledger_enabled": bool(getattr(settings_object, "CANONICAL_PARSER_LIVE_ALERT_LEDGER_ENABLED", False)),
        "snapshot_ttl_seconds": int(getattr(settings_object, "CANONICAL_PARSER_LIVE_OBSERVABILITY_SNAPSHOT_TTL_SECONDS", 60)),
        "stale_submission_seconds": int(getattr(settings_object, "CANONICAL_PARSER_LIVE_OBSERVABILITY_STALE_SUBMISSION_SECONDS", 300)),
        "critical_open_alert_threshold": int(getattr(settings_object, "CANONICAL_PARSER_LIVE_OBSERVABILITY_CRITICAL_OPEN_ALERT_THRESHOLD", 1)),
        "manual_only": True,
        "external_notification_dispatch": False,
        "automatic_alert_issue": False,
    }


def _serialize_snapshot(row: CanonicalParserLiveObservabilitySnapshot) -> dict[str, Any]:
    return {
        "snapshot_id": row.snapshot_id,
        "snapshot_key": row.snapshot_key,
        "scope": row.scope,
        "status": row.status,
        "uncertain_submission_count": row.uncertain_submission_count,
        "stale_submission_count": row.stale_submission_count,
        "unsettled_count": row.unsettled_count,
        "review_position_count": row.review_position_count,
        "active_incident_count": row.active_incident_count,
        "open_alert_count": row.open_alert_count,
        "reason_codes": row.reason_codes,
        "metric_snapshot": row.metric_snapshot,
        "policy_snapshot": row.policy_snapshot,
        "evidence_hash": row.evidence_hash,
        "actor_label": row.actor_label,
        "note": row.note,
        "observed_at": row.observed_at,
        "expires_at": row.expires_at,
    }


def _serialize_alert(row: CanonicalParserLiveOperationalAlert) -> dict[str, Any]:
    return {
        "alert_id": row.alert_id,
        "alert_key": row.alert_key,
        "fingerprint": row.fingerprint,
        "scope": row.scope,
        "snapshot_id": row.snapshot_id,
        "reason_code": row.reason_code,
        "category": row.category,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "severity": row.severity,
        "status": row.status,
        "alert_snapshot": row.alert_snapshot,
        "evidence_hash": row.evidence_hash,
        "actor_label": row.actor_label,
        "note": row.note,
        "first_seen_at": row.first_seen_at,
        "last_seen_at": row.last_seen_at,
        "acknowledged_at": row.acknowledged_at,
        "resolved_at": row.resolved_at,
        "latest_event_sequence": row.latest_event_sequence,
        "latest_event_hash": row.latest_event_hash,
    }


def _append_alert_event(
    db: Session,
    row: CanonicalParserLiveOperationalAlert,
    *,
    event_type: str,
    payload: dict[str, Any],
    at: datetime,
) -> None:
    sequence = int(row.latest_event_sequence or 0) + 1
    previous_hash = row.latest_event_hash if row.latest_event_sequence else None
    body = {
        "alert_id": row.alert_id,
        "sequence": sequence,
        "event_type": event_type,
        "occurred_at": at.isoformat(),
        "payload": payload,
        "previous_event_hash": previous_hash,
    }
    event_hash = calculate_payload_hash(body)
    db.add(
        CanonicalParserLiveOperationalAlertEvent(
            event_id=str(uuid4()),
            alert_db_id=row.id,
            sequence=sequence,
            event_type=event_type,
            event_payload=body,
            previous_event_hash=previous_hash,
            event_hash=event_hash,
            occurred_at=at,
        )
    )
    row.latest_event_sequence = sequence
    row.latest_event_hash = event_hash


def _collect_metrics(db: Session, *, observed_at: datetime, policy: dict[str, Any]) -> dict[str, Any]:
    submissions = list(db.scalars(select(CanonicalParserControlledLiveSubmission)))
    settlements = list(db.scalars(select(CanonicalParserLiveOnchainSettlement)))
    positions = list(db.scalars(select(CanonicalParserGovernedLivePosition)))
    incidents = list(db.scalars(select(CanonicalParserLiveIncident)))
    alerts = list(db.scalars(select(CanonicalParserLiveOperationalAlert)))
    risk_assessments = list(db.scalars(select(CanonicalParserLivePortfolioRiskAssessment)))

    uncertain = [row for row in submissions if row.status == "RECONCILIATION_REQUIRED"]
    stale = [
        row
        for row in submissions
        if row.status in _PENDING_SUBMISSION_STATUSES
        and (observed_at - _now(row.reserved_at)).total_seconds() > policy["stale_submission_seconds"]
    ]
    unsettled = [row for row in settlements if row.status in {"REVIEW", "BLOCKED", "INSUFFICIENT_DATA"}]
    review_positions = [row for row in positions if row.status == "REVIEW"]
    active_incidents = [row for row in incidents if row.status in _ACTIVE_INCIDENT_STATUSES]
    high_incidents = [row for row in active_incidents if row.severity in {"HIGH", "CRITICAL"}]
    open_alerts = [row for row in alerts if row.status in _ACTIVE_ALERT_STATUSES]
    critical_alerts = [row for row in open_alerts if row.severity == "CRITICAL"]
    blocked_risk = [row for row in risk_assessments if row.status == "BLOCKED" and _now(row.expires_at) > observed_at]

    reason_codes: list[str] = []
    if uncertain:
        reason_codes.append("M38_RECONCILIATION_REQUIRED")
    if stale:
        reason_codes.append("M38_STALE_SUBMISSION")
    if unsettled:
        reason_codes.append("M39_SETTLEMENT_REVIEW_REQUIRED")
    if review_positions:
        reason_codes.append("M39_POSITION_REVIEW_REQUIRED")
    if high_incidents:
        reason_codes.append("M41_ACTIVE_HIGH_SEVERITY_INCIDENT")
    if blocked_risk:
        reason_codes.append("M42_PORTFOLIO_RISK_BLOCKED")
    if len(critical_alerts) >= policy["critical_open_alert_threshold"]:
        reason_codes.append("M43_OPEN_CRITICAL_ALERT")

    status = "HEALTHY"
    critical_reasons = {
        "M38_RECONCILIATION_REQUIRED",
        "M41_ACTIVE_HIGH_SEVERITY_INCIDENT",
        "M43_OPEN_CRITICAL_ALERT",
    }
    if any(reason in critical_reasons for reason in reason_codes):
        status = "CRITICAL"
    elif reason_codes:
        status = "DEGRADED"

    return {
        "status": status,
        "reason_codes": sorted(set(reason_codes)),
        "counts": {
            "submission_total": len(submissions),
            "uncertain_submission_count": len(uncertain),
            "stale_submission_count": len(stale),
            "settlement_total": len(settlements),
            "unsettled_count": len(unsettled),
            "position_total": len(positions),
            "review_position_count": len(review_positions),
            "active_incident_count": len(active_incidents),
            "high_incident_count": len(high_incidents),
            "open_alert_count": len(open_alerts),
            "critical_alert_count": len(critical_alerts),
            "blocked_risk_assessment_count": len(blocked_risk),
        },
        "identifiers": {
            "uncertain_submission_ids": [row.submission_id for row in uncertain][:50],
            "stale_submission_ids": [row.submission_id for row in stale][:50],
            "unsettled_ids": [row.settlement_id for row in unsettled][:50],
            "review_position_ids": [row.position_id for row in review_positions][:50],
            "active_incident_ids": [row.incident_id for row in active_incidents][:50],
            "open_alert_ids": [row.alert_id for row in open_alerts][:50],
        },
    }


def preview_live_operational_observation(
    db: Session,
    *,
    idempotency_token: str,
    settings_object: Any = settings,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    token = str(idempotency_token or "").strip()
    if len(token) < 8:
        raise CanonicalParserLiveOperationalObservabilityError(
            "Idempotency token M43 non valido.", code="M43_IDEMPOTENCY_INVALID"
        )
    now = _now(observed_at)
    policy = _policy(settings_object)
    metrics = _collect_metrics(db, observed_at=now, policy=policy)
    snapshot_key = calculate_payload_hash(
        {
            "idempotency_token": token,
            "metrics": metrics,
            "policy": policy,
        }
    )
    existing = db.scalar(
        select(CanonicalParserLiveObservabilitySnapshot).where(
            CanonicalParserLiveObservabilitySnapshot.snapshot_key == snapshot_key
        )
    )
    evidence = {
        "snapshot_key": snapshot_key,
        "status": metrics["status"],
        "reason_codes": metrics["reason_codes"],
        "metrics": metrics,
        "policy": policy,
        "observed_at": now.isoformat(),
    }
    return {
        "status": metrics["status"],
        "ready": metrics["status"] == "HEALTHY",
        "snapshot_key": snapshot_key,
        "existing_snapshot": None if existing is None else _serialize_snapshot(existing),
        "reason_codes": metrics["reason_codes"],
        "metric_snapshot": metrics,
        "policy": policy,
        "evidence_hash": calculate_payload_hash(evidence),
        "confirmation": f"{OBSERVE_PREFIX}:{snapshot_key}",
        "safety": {
            "manual_only": True,
            "read_only_source_collection": True,
            "automatic_alert_issue": False,
            "external_notification_dispatch": False,
        },
    }


def observe_live_operations(
    db: Session,
    *,
    idempotency_token: str,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    observed_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_LIVE_OBSERVABILITY_ENABLED", False)):
        raise CanonicalParserLiveOperationalObservabilityError(
            "M43 osservabilità disabilitata.", code="M43_DISABLED", status_code=409
        )
    now = _now(observed_at)
    preview = preview_live_operational_observation(
        db,
        idempotency_token=idempotency_token,
        settings_object=settings_object,
        observed_at=now,
    )
    if preview["existing_snapshot"] is not None:
        return preview["existing_snapshot"]
    if confirmation != preview["confirmation"]:
        raise CanonicalParserLiveOperationalObservabilityError(
            "Conferma M43 non valida.", code="M43_CONFIRMATION_REQUIRED", status_code=409
        )
    counts = preview["metric_snapshot"]["counts"]
    row = CanonicalParserLiveObservabilitySnapshot(
        snapshot_id=str(uuid4()),
        snapshot_key=preview["snapshot_key"],
        scope="M43_LIVE_OPERATIONAL_OBSERVABILITY",
        status=preview["status"],
        uncertain_submission_count=counts["uncertain_submission_count"],
        stale_submission_count=counts["stale_submission_count"],
        unsettled_count=counts["unsettled_count"],
        review_position_count=counts["review_position_count"],
        active_incident_count=counts["active_incident_count"],
        open_alert_count=counts["open_alert_count"],
        reason_codes=preview["reason_codes"],
        metric_snapshot=preview["metric_snapshot"],
        policy_snapshot=preview["policy"],
        evidence_hash=preview["evidence_hash"],
        actor_label=_actor(actor_label),
        note=_note(note),
        observed_at=now,
        expires_at=now + timedelta(seconds=preview["policy"]["snapshot_ttl_seconds"]),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.scalar(
            select(CanonicalParserLiveObservabilitySnapshot).where(
                CanonicalParserLiveObservabilitySnapshot.snapshot_key == preview["snapshot_key"]
            )
        )
        if duplicate is not None:
            return _serialize_snapshot(duplicate)
        raise CanonicalParserLiveOperationalObservabilityError(
            "Conflitto snapshot M43.", code="M43_SNAPSHOT_CONFLICT", status_code=409
        ) from exc
    db.refresh(row)
    return _serialize_snapshot(row)


def _alert_descriptor(reason_code: str) -> dict[str, str]:
    mapping = {
        "M38_RECONCILIATION_REQUIRED": ("SUBMISSION_OUTCOME", "CRITICAL"),
        "M38_STALE_SUBMISSION": ("SUBMISSION_STALE", "HIGH"),
        "M39_SETTLEMENT_REVIEW_REQUIRED": ("SETTLEMENT_INTEGRITY", "HIGH"),
        "M39_POSITION_REVIEW_REQUIRED": ("POSITION_INTEGRITY", "HIGH"),
        "M41_ACTIVE_HIGH_SEVERITY_INCIDENT": ("INCIDENT_RESPONSE", "CRITICAL"),
        "M42_PORTFOLIO_RISK_BLOCKED": ("PORTFOLIO_RISK", "HIGH"),
        "M43_OPEN_CRITICAL_ALERT": ("ALERT_BACKLOG", "CRITICAL"),
    }
    category, severity = mapping.get(reason_code, ("OPERATIONAL_OBSERVATION", "MEDIUM"))
    return {"category": category, "severity": severity}


def preview_live_operational_alert(
    db: Session,
    *,
    snapshot_id: str,
    reason_code: str,
    idempotency_token: str,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _now(evaluated_at)
    token = str(idempotency_token or "").strip()
    if len(token) < 8:
        raise CanonicalParserLiveOperationalObservabilityError(
            "Idempotency token alert M43 non valido.", code="M43_ALERT_IDEMPOTENCY_INVALID"
        )
    snapshot = db.scalar(
        select(CanonicalParserLiveObservabilitySnapshot).where(
            CanonicalParserLiveObservabilitySnapshot.snapshot_id == snapshot_id
        )
    )
    if snapshot is None:
        raise CanonicalParserLiveOperationalObservabilityError(
            "Snapshot M43 non trovato.", code="M43_SNAPSHOT_NOT_FOUND", status_code=404
        )
    code = str(reason_code or "").strip().upper()
    reasons: list[str] = []
    if code not in set(snapshot.reason_codes or []):
        reasons.append("M43_REASON_NOT_IN_SNAPSHOT")
    if _now(snapshot.expires_at) <= now:
        reasons.append("M43_SNAPSHOT_EXPIRED")
    descriptor = _alert_descriptor(code)
    fingerprint = calculate_payload_hash(
        {"scope": "M43_OPERATIONAL_ALERT", "reason_code": code, "category": descriptor["category"]}
    )
    alert_key = calculate_payload_hash(
        {"snapshot_id": snapshot.snapshot_id, "reason_code": code, "idempotency_token": token}
    )
    existing = db.scalar(
        select(CanonicalParserLiveOperationalAlert).where(
            CanonicalParserLiveOperationalAlert.alert_key == alert_key
        )
    )
    active_duplicate = db.scalar(
        select(CanonicalParserLiveOperationalAlert)
        .where(
            CanonicalParserLiveOperationalAlert.fingerprint == fingerprint,
            CanonicalParserLiveOperationalAlert.status.in_(sorted(_ACTIVE_ALERT_STATUSES)),
        )
        .order_by(CanonicalParserLiveOperationalAlert.id.desc())
        .limit(1)
    )
    evidence = {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_evidence_hash": snapshot.evidence_hash,
        "reason_code": code,
        "category": descriptor["category"],
        "severity": descriptor["severity"],
        "fingerprint": fingerprint,
        "policy": _policy(settings_object),
        "evaluated_at": now.isoformat(),
    }
    return {
        "status": "READY" if not reasons else "BLOCKED",
        "ready": not reasons,
        "snapshot": _serialize_snapshot(snapshot),
        "reason_code": code,
        "category": descriptor["category"],
        "severity": descriptor["severity"],
        "fingerprint": fingerprint,
        "alert_key": alert_key,
        "existing_alert": None if existing is None else _serialize_alert(existing),
        "active_duplicate": None if active_duplicate is None else _serialize_alert(active_duplicate),
        "reason_codes": reasons,
        "evidence_hash": calculate_payload_hash(evidence),
        "confirmation": f"{ALERT_PREFIX}:{snapshot.snapshot_id}:{alert_key}",
        "policy": _policy(settings_object),
    }


def issue_live_operational_alert(
    db: Session,
    *,
    snapshot_id: str,
    reason_code: str,
    idempotency_token: str,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    issued_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_LIVE_ALERT_LEDGER_ENABLED", False)):
        raise CanonicalParserLiveOperationalObservabilityError(
            "Ledger alert M43 disabilitato.", code="M43_ALERT_LEDGER_DISABLED", status_code=409
        )
    now = _now(issued_at)
    preview = preview_live_operational_alert(
        db,
        snapshot_id=snapshot_id,
        reason_code=reason_code,
        idempotency_token=idempotency_token,
        settings_object=settings_object,
        evaluated_at=now,
    )
    if preview["existing_alert"] is not None:
        return preview["existing_alert"]
    if preview["active_duplicate"] is not None:
        return preview["active_duplicate"]
    if preview["status"] != "READY":
        raise CanonicalParserLiveOperationalObservabilityError(
            "Alert M43 bloccato.", code="M43_ALERT_BLOCKED", status_code=409
        )
    if confirmation != preview["confirmation"]:
        raise CanonicalParserLiveOperationalObservabilityError(
            "Conferma alert M43 non valida.", code="M43_ALERT_CONFIRMATION_REQUIRED", status_code=409
        )
    snapshot = db.scalar(
        select(CanonicalParserLiveObservabilitySnapshot).where(
            CanonicalParserLiveObservabilitySnapshot.snapshot_id == snapshot_id
        )
    )
    assert snapshot is not None
    alert_id = str(uuid4())
    initial_event_body = {
        "alert_id": alert_id,
        "sequence": 1,
        "event_type": "OPENED",
        "occurred_at": now.isoformat(),
        "payload": {"reason_code": preview["reason_code"]},
        "previous_event_hash": None,
    }
    initial_event_hash = calculate_payload_hash(initial_event_body)
    row = CanonicalParserLiveOperationalAlert(
        alert_id=alert_id,
        alert_key=preview["alert_key"],
        fingerprint=preview["fingerprint"],
        scope="M43_MANUAL_OPERATIONAL_ALERT",
        snapshot_db_id=snapshot.id,
        snapshot_id=snapshot.snapshot_id,
        reason_code=preview["reason_code"],
        category=preview["category"],
        source_type="OBSERVABILITY_REASON",
        source_id=preview["reason_code"],
        severity=preview["severity"],
        status="OPEN",
        alert_snapshot={
            "snapshot_evidence_hash": snapshot.evidence_hash,
            "metric_snapshot": snapshot.metric_snapshot,
            "external_notification_dispatched": False,
        },
        evidence_hash=preview["evidence_hash"],
        actor_label=_actor(actor_label),
        note=_note(note),
        first_seen_at=now,
        last_seen_at=now,
        acknowledged_at=None,
        resolved_at=None,
        latest_event_sequence=1,
        latest_event_hash=initial_event_hash,
    )
    db.add(row)
    db.flush()
    db.add(
        CanonicalParserLiveOperationalAlertEvent(
            event_id=str(uuid4()),
            alert_db_id=row.id,
            sequence=1,
            event_type="OPENED",
            event_payload=initial_event_body,
            previous_event_hash=None,
            event_hash=initial_event_hash,
            occurred_at=now,
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.scalar(
            select(CanonicalParserLiveOperationalAlert).where(
                CanonicalParserLiveOperationalAlert.alert_key == preview["alert_key"]
            )
        )
        if duplicate is not None:
            return _serialize_alert(duplicate)
        raise CanonicalParserLiveOperationalObservabilityError(
            "Conflitto alert M43.", code="M43_ALERT_CONFLICT", status_code=409
        ) from exc
    db.refresh(row)
    return _serialize_alert(row)


def acknowledge_live_operational_alert(
    db: Session,
    *,
    alert_id: str,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    acknowledged_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_LIVE_ALERT_LEDGER_ENABLED", False)):
        raise CanonicalParserLiveOperationalObservabilityError(
            "Ledger alert M43 disabilitato.", code="M43_ALERT_LEDGER_DISABLED", status_code=409
        )
    now = _now(acknowledged_at)
    row = db.scalar(
        select(CanonicalParserLiveOperationalAlert)
        .where(CanonicalParserLiveOperationalAlert.alert_id == alert_id)
        .with_for_update()
    )
    if row is None:
        raise CanonicalParserLiveOperationalObservabilityError(
            "Alert M43 non trovato.", code="M43_ALERT_NOT_FOUND", status_code=404
        )
    if row.status == "ACKNOWLEDGED":
        return _serialize_alert(row)
    if row.status != "OPEN":
        raise CanonicalParserLiveOperationalObservabilityError(
            "Alert M43 non riconoscibile nello stato corrente.", code="M43_ALERT_NOT_OPEN", status_code=409
        )
    expected = f"{ACK_PREFIX}:{row.alert_id}:{row.evidence_hash}"
    if confirmation != expected:
        raise CanonicalParserLiveOperationalObservabilityError(
            "Conferma acknowledge M43 non valida.", code="M43_ACK_CONFIRMATION_REQUIRED", status_code=409
        )
    row.status = "ACKNOWLEDGED"
    row.acknowledged_at = now
    row.last_seen_at = now
    row.actor_label = _actor(actor_label)
    row.note = _note(note) or row.note
    _append_alert_event(db, row, event_type="ACKNOWLEDGED", payload={"actor_label": row.actor_label}, at=now)
    db.commit()
    db.refresh(row)
    return _serialize_alert(row)


def resolve_live_operational_alert(
    db: Session,
    *,
    alert_id: str,
    resolution_evidence: str,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    resolved_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_LIVE_ALERT_LEDGER_ENABLED", False)):
        raise CanonicalParserLiveOperationalObservabilityError(
            "Ledger alert M43 disabilitato.", code="M43_ALERT_LEDGER_DISABLED", status_code=409
        )
    now = _now(resolved_at)
    row = db.scalar(
        select(CanonicalParserLiveOperationalAlert)
        .where(CanonicalParserLiveOperationalAlert.alert_id == alert_id)
        .with_for_update()
    )
    if row is None:
        raise CanonicalParserLiveOperationalObservabilityError(
            "Alert M43 non trovato.", code="M43_ALERT_NOT_FOUND", status_code=404
        )
    if row.status == "RESOLVED":
        return _serialize_alert(row)
    evidence = str(resolution_evidence or "").strip()
    if len(evidence) < 8:
        raise CanonicalParserLiveOperationalObservabilityError(
            "Evidenza di risoluzione M43 insufficiente.", code="M43_RESOLUTION_EVIDENCE_INVALID"
        )
    expected = f"{RESOLVE_PREFIX}:{row.alert_id}:{row.evidence_hash}"
    if confirmation != expected:
        raise CanonicalParserLiveOperationalObservabilityError(
            "Conferma resolve M43 non valida.", code="M43_RESOLVE_CONFIRMATION_REQUIRED", status_code=409
        )
    row.status = "RESOLVED"
    row.resolved_at = now
    row.last_seen_at = now
    row.actor_label = _actor(actor_label)
    row.note = _note(note) or row.note
    _append_alert_event(db, row, event_type="RESOLVED", payload={"resolution_evidence": evidence[:500]}, at=now)
    db.commit()
    db.refresh(row)
    return _serialize_alert(row)


def get_live_observability_snapshot(db: Session, snapshot_id: str) -> dict[str, Any]:
    row = db.scalar(
        select(CanonicalParserLiveObservabilitySnapshot).where(
            CanonicalParserLiveObservabilitySnapshot.snapshot_id == snapshot_id
        )
    )
    if row is None:
        raise CanonicalParserLiveOperationalObservabilityError(
            "Snapshot M43 non trovato.", code="M43_SNAPSHOT_NOT_FOUND", status_code=404
        )
    return _serialize_snapshot(row)


def get_live_operational_alert(db: Session, alert_id: str) -> dict[str, Any]:
    row = db.scalar(
        select(CanonicalParserLiveOperationalAlert).where(
            CanonicalParserLiveOperationalAlert.alert_id == alert_id
        )
    )
    if row is None:
        raise CanonicalParserLiveOperationalObservabilityError(
            "Alert M43 non trovato.", code="M43_ALERT_NOT_FOUND", status_code=404
        )
    return _serialize_alert(row)


def get_live_operational_observability_status(
    db: Session, *, settings_object: Any = settings, evaluated_at: datetime | None = None
) -> dict[str, Any]:
    now = _now(evaluated_at)
    latest = db.scalar(
        select(CanonicalParserLiveObservabilitySnapshot)
        .order_by(CanonicalParserLiveObservabilitySnapshot.observed_at.desc())
        .limit(1)
    )
    open_alerts = list(
        db.scalars(
            select(CanonicalParserLiveOperationalAlert).where(
                CanonicalParserLiveOperationalAlert.status.in_(sorted(_ACTIVE_ALERT_STATUSES))
            )
        )
    )
    return {
        "milestone": "M43",
        "policy": _policy(settings_object),
        "latest_snapshot": None if latest is None else _serialize_snapshot(latest),
        "latest_snapshot_fresh": latest is not None and _now(latest.expires_at) > now,
        "open_alert_count": len(open_alerts),
        "critical_open_alert_count": len([row for row in open_alerts if row.severity == "CRITICAL"]),
        "safety": {
            "manual_only": True,
            "read_only_source_collection": True,
            "external_notification_dispatch": False,
            "automatic_alert_issue": False,
            "transaction_built": False,
            "transaction_signed": False,
            "transaction_sent": False,
        },
    }


def resolve_live_operational_observability(
    db: Session, *, settings_object: Any = settings, evaluated_at: datetime | None = None
) -> dict[str, Any]:
    status = get_live_operational_observability_status(
        db, settings_object=settings_object, evaluated_at=evaluated_at
    )
    latest = status["latest_snapshot"]
    status["resolved_status"] = (
        "INSUFFICIENT_DATA"
        if latest is None or not status["latest_snapshot_fresh"]
        else latest["status"]
    )
    return status
