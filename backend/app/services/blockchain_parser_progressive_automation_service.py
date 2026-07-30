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
    CanonicalParserAssistedMicroLivePilot,
    CanonicalParserControlledLiveSubmission,
    CanonicalParserLiveIncident,
    CanonicalParserLiveObservabilitySnapshot,
    CanonicalParserLiveOperationalAlert,
    CanonicalParserProductionCircuitBreaker,
    CanonicalParserProductionCircuitBreakerEvent,
    CanonicalParserProductionHardeningAssessment,
    CanonicalParserProgressiveAutomationLease,
    CanonicalParserProgressiveAutomationLeaseEvent,
)
from backend.app.services.blockchain_integrity_service import calculate_payload_hash

PROGRESSIVE_AUTOMATION_POLICY_VERSION = "canonical-parser-progressive-automation-production-hardening/1"
ASSESS_PREFIX = "ASSESS_M46_PRODUCTION_HARDENING"
LEASE_PREFIX = "ISSUE_M46_PROGRESSIVE_AUTOMATION_LEASE"
REVOKE_PREFIX = "REVOKE_M46_PROGRESSIVE_AUTOMATION_LEASE"
TRIP_PREFIX = "TRIP_M46_PRODUCTION_CIRCUIT_BREAKER"
RESET_PREFIX = "RESET_M46_PRODUCTION_CIRCUIT_BREAKER"
_MONEY_QUANTUM = Decimal("0.000000001")
_STAGE_ORDER = {
    "OBSERVE_ONLY": 0,
    "ASSISTED": 1,
    "SUPERVISED": 2,
    "AUTOMATION_CANDIDATE": 3,
}
_ACTIVE_PILOT_STATUSES = {
    "PLANNED",
    "ARMED",
    "ENTRY_SUBMITTED",
    "ENTRY_RECONCILED",
    "ENTRY_SETTLED",
    "EXIT_READY",
    "EXIT_SUBMITTED",
    "EXIT_RECONCILED",
    "EXIT_SETTLED",
}
_OPEN_SUBMISSION_STATUSES = {
    "RESERVED",
    "SUBMITTED",
    "PROCESSED",
    "CONFIRMED",
    "RECONCILIATION_REQUIRED",
}


class CanonicalParserProgressiveAutomationError(ValueError):
    def __init__(self, message: str, *, code: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _now(value: datetime | None = None) -> datetime:
    resolved = value or datetime.now(timezone.utc)
    if resolved.tzinfo is None:
        return resolved.replace(tzinfo=timezone.utc)
    return resolved.astimezone(timezone.utc)


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CanonicalParserProgressiveAutomationError(
            "Valore monetario M46 non valido.", code="M46_INVALID_MONEY_VALUE"
        ) from exc
    if not result.is_finite():
        raise CanonicalParserProgressiveAutomationError(
            "Valore monetario M46 non finito.", code="M46_INVALID_MONEY_VALUE"
        )
    return result.quantize(_MONEY_QUANTUM)


def _money(value: Any) -> str:
    return format(_decimal(value), "f")


def _actor(value: str | None) -> str:
    return str(value or "MANUAL_OPERATOR").strip()[:80] or "MANUAL_OPERATOR"


def _note(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized[:500] if normalized else None


def _policy(settings_object: Any = settings) -> dict[str, Any]:
    return {
        "version": PROGRESSIVE_AUTOMATION_POLICY_VERSION,
        "enabled": bool(getattr(settings_object, "CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_ENABLED", False)),
        "guard_enabled": bool(getattr(settings_object, "CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_GUARD_ENABLED", False)),
        "circuit_breaker_enabled": bool(getattr(settings_object, "CANONICAL_PARSER_PRODUCTION_CIRCUIT_BREAKER_ENABLED", False)),
        "assessment_ttl_minutes": int(getattr(settings_object, "CANONICAL_PARSER_PRODUCTION_HARDENING_ASSESSMENT_TTL_MINUTES", 15)),
        "lookback_days": int(getattr(settings_object, "CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_PILOT_LOOKBACK_DAYS", 30)),
        "min_completed_assisted": int(getattr(settings_object, "CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_MIN_COMPLETED_PILOTS_ASSISTED", 1)),
        "min_completed_supervised": int(getattr(settings_object, "CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_MIN_COMPLETED_PILOTS_SUPERVISED", 3)),
        "min_completed_candidate": int(getattr(settings_object, "CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_MIN_COMPLETED_PILOTS_CANDIDATE", 5)),
        "max_validity_minutes": int(getattr(settings_object, "CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_MAX_VALIDITY_MINUTES", 60)),
        "max_budget_sol": _money(getattr(settings_object, "CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_MAX_BUDGET_SOL", 0.01)),
        "max_submissions": int(getattr(settings_object, "CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_MAX_SUBMISSIONS", 10)),
        "require_healthy_observability": bool(getattr(settings_object, "CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_REQUIRE_HEALTHY_OBSERVABILITY", True)),
        "require_zero_active_incidents": bool(getattr(settings_object, "CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_REQUIRE_ZERO_ACTIVE_INCIDENTS", True)),
        "require_zero_uncertain_submissions": bool(getattr(settings_object, "CANONICAL_PARSER_PROGRESSIVE_AUTOMATION_REQUIRE_ZERO_UNCERTAIN_SUBMISSIONS", True)),
        "manual_trigger_only": True,
        "automatic_dispatch": False,
        "worker_connected": False,
        "scheduler_connected": False,
    }


def _resolved_lease_status(row: CanonicalParserProgressiveAutomationLease, now: datetime) -> str:
    if row.status == "ACTIVE" and _now(row.expires_at) <= now:
        return "EXPIRED"
    if row.status == "ACTIVE" and int(row.used_submission_count) >= int(row.max_submission_count):
        return "EXHAUSTED"
    return row.status


def _health_snapshot(db: Session, *, now: datetime) -> dict[str, Any]:
    snapshot = db.scalar(
        select(CanonicalParserLiveObservabilitySnapshot)
        .order_by(CanonicalParserLiveObservabilitySnapshot.observed_at.desc())
        .limit(1)
    )
    active_incident_count = int(
        db.scalar(
            select(func.count(CanonicalParserLiveIncident.id)).where(
                CanonicalParserLiveIncident.status != "RESOLVED"
            )
        )
        or 0
    )
    open_critical_alert_count = int(
        db.scalar(
            select(func.count(CanonicalParserLiveOperationalAlert.id)).where(
                CanonicalParserLiveOperationalAlert.status != "RESOLVED",
                CanonicalParserLiveOperationalAlert.severity == "CRITICAL",
            )
        )
        or 0
    )
    unresolved_submission_count = int(
        db.scalar(
            select(func.count(CanonicalParserControlledLiveSubmission.id)).where(
                CanonicalParserControlledLiveSubmission.status.in_(tuple(sorted(_OPEN_SUBMISSION_STATUSES)))
            )
        )
        or 0
    )
    snapshot_expired = True if snapshot is None else _now(snapshot.expires_at) <= now
    healthy = (
        snapshot is not None
        and snapshot.status == "HEALTHY"
        and not snapshot_expired
        and active_incident_count == 0
        and open_critical_alert_count == 0
        and unresolved_submission_count == 0
    )
    return {
        "healthy": healthy,
        "snapshot_id": None if snapshot is None else snapshot.snapshot_id,
        "snapshot_status": None if snapshot is None else snapshot.status,
        "snapshot_expired": snapshot_expired,
        "active_incident_count": active_incident_count,
        "open_critical_alert_count": open_critical_alert_count,
        "unresolved_submission_count": unresolved_submission_count,
    }


def _pilot_evidence(
    db: Session,
    *,
    wallet_address: str,
    token_mint: str,
    now: datetime,
    lookback_days: int,
) -> dict[str, Any]:
    cutoff = now - timedelta(days=max(1, int(lookback_days)))
    rows = list(
        db.scalars(
            select(CanonicalParserAssistedMicroLivePilot).where(
                CanonicalParserAssistedMicroLivePilot.wallet_address == wallet_address,
                CanonicalParserAssistedMicroLivePilot.token_mint == token_mint,
                CanonicalParserAssistedMicroLivePilot.issued_at >= cutoff,
            )
        )
    )
    completed = [row for row in rows if row.status == "COMPLETED"]
    aborted = [row for row in rows if row.status == "ABORTED"]
    expired = [row for row in rows if row.status == "EXPIRED" or (row.status in _ACTIVE_PILOT_STATUSES and _now(row.expires_at) <= now)]
    active = [row for row in rows if row.status in _ACTIVE_PILOT_STATUSES and _now(row.expires_at) > now]
    proven_budget = max((Decimal(row.max_entry_budget_sol) for row in completed), default=Decimal("0"))
    total_realized_pnl = Decimal("0")
    total_fee = Decimal("0")
    for row in completed:
        completion = row.completion_snapshot or {}
        try:
            total_realized_pnl += _decimal(completion.get("realized_pnl_sol", "0"))
        except CanonicalParserProgressiveAutomationError:
            pass
        try:
            total_fee += _decimal(completion.get("total_fee_sol", "0"))
        except CanonicalParserProgressiveAutomationError:
            pass
    return {
        "completed_count": len(completed),
        "aborted_count": len(aborted),
        "expired_count": len(expired),
        "active_count": len(active),
        "completed_pilot_ids": [row.pilot_id for row in completed],
        "proven_budget_sol": _money(proven_budget),
        "total_realized_pnl_sol": _money(total_realized_pnl),
        "total_fee_sol": _money(total_fee),
        "lookback_cutoff": cutoff.isoformat(),
    }


def _eligible_stage(completed_count: int, policy: dict[str, Any]) -> str:
    if completed_count >= policy["min_completed_candidate"]:
        return "AUTOMATION_CANDIDATE"
    if completed_count >= policy["min_completed_supervised"]:
        return "SUPERVISED"
    if completed_count >= policy["min_completed_assisted"]:
        return "ASSISTED"
    return "OBSERVE_ONLY"


def _recommended_submission_count(stage: str, policy: dict[str, Any]) -> int:
    defaults = {
        "OBSERVE_ONLY": 0,
        "ASSISTED": 2,
        "SUPERVISED": 6,
        "AUTOMATION_CANDIDATE": 10,
    }
    return min(defaults[stage], int(policy["max_submissions"]))


def _recommended_budget(stage: str, pilot: dict[str, Any], policy: dict[str, Any]) -> Decimal:
    if stage == "OBSERVE_ONLY":
        return Decimal("0")
    proven = _decimal(pilot["proven_budget_sol"])
    if proven <= 0:
        return Decimal("0")
    multiplier = {
        "ASSISTED": Decimal("1"),
        "SUPERVISED": Decimal("1.25"),
        "AUTOMATION_CANDIDATE": Decimal("1.50"),
    }[stage]
    return min(_decimal(policy["max_budget_sol"]), (proven * multiplier).quantize(_MONEY_QUANTUM))


def _serialize_assessment(row: CanonicalParserProductionHardeningAssessment) -> dict[str, Any]:
    return {
        "assessment_id": row.assessment_id,
        "assessment_key": row.assessment_key,
        "scope": row.scope,
        "status": row.status,
        "wallet_address": row.wallet_address,
        "network": row.network,
        "token_mint": row.token_mint,
        "requested_stage": row.requested_stage,
        "eligible_stage": row.eligible_stage,
        "completed_pilot_count": row.completed_pilot_count,
        "aborted_pilot_count": row.aborted_pilot_count,
        "expired_pilot_count": row.expired_pilot_count,
        "unresolved_submission_count": row.unresolved_submission_count,
        "active_incident_count": row.active_incident_count,
        "open_critical_alert_count": row.open_critical_alert_count,
        "latest_observability_snapshot_id": row.latest_observability_snapshot_id,
        "requested_max_budget_sol": _money(row.requested_max_budget_sol),
        "recommended_max_budget_sol": _money(row.recommended_max_budget_sol),
        "requested_max_submissions": row.requested_max_submissions,
        "recommended_max_submissions": row.recommended_max_submissions,
        "reason_codes": row.reason_codes,
        "evidence_snapshot": row.evidence_snapshot,
        "policy_snapshot": row.policy_snapshot,
        "evidence_hash": row.evidence_hash,
        "actor_label": row.actor_label,
        "note": row.note,
        "assessed_at": row.assessed_at,
        "expires_at": row.expires_at,
    }


def _serialize_lease(row: CanonicalParserProgressiveAutomationLease, *, now: datetime) -> dict[str, Any]:
    return {
        "lease_id": row.lease_id,
        "lease_key": row.lease_key,
        "scope": row.scope,
        "assessment_id": row.assessment_id,
        "wallet_address": row.wallet_address,
        "network": row.network,
        "token_mint": row.token_mint,
        "stage": row.stage,
        "status": row.status,
        "resolved_status": _resolved_lease_status(row, now),
        "max_budget_sol": _money(row.max_budget_sol),
        "max_submission_count": row.max_submission_count,
        "used_submission_count": row.used_submission_count,
        "automatic_dispatch_permitted": bool(row.automatic_dispatch_permitted),
        "lease_snapshot": row.lease_snapshot,
        "evidence_hash": row.evidence_hash,
        "actor_label": row.actor_label,
        "note": row.note,
        "issued_at": row.issued_at,
        "expires_at": row.expires_at,
        "revoked_at": row.revoked_at,
        "tripped_at": row.tripped_at,
        "exhausted_at": row.exhausted_at,
        "latest_event_sequence": row.latest_event_sequence,
        "latest_event_hash": row.latest_event_hash,
        "safety": {
            "manual_trigger_only": True,
            "automatic_dispatch": False,
            "worker_connected": False,
            "scheduler_connected": False,
        },
    }


def _serialize_breaker(row: CanonicalParserProductionCircuitBreaker | None, *, wallet_address: str, now: datetime) -> dict[str, Any]:
    if row is None:
        return {
            "breaker_id": None,
            "wallet_address": wallet_address,
            "network": "mainnet-beta",
            "status": "CLEAR",
            "reason_codes": [],
            "trip_count": 0,
            "reset_count": 0,
            "evaluated_at": now,
        }
    return {
        "breaker_id": row.breaker_id,
        "breaker_key": row.breaker_key,
        "scope": row.scope,
        "wallet_address": row.wallet_address,
        "network": row.network,
        "status": row.status,
        "reason_codes": row.reason_codes,
        "source_type": row.source_type,
        "source_id": row.source_id,
        "trip_count": row.trip_count,
        "reset_count": row.reset_count,
        "breaker_snapshot": row.breaker_snapshot,
        "evidence_hash": row.evidence_hash,
        "actor_label": row.actor_label,
        "note": row.note,
        "tripped_at": row.tripped_at,
        "reset_at": row.reset_at,
        "latest_event_sequence": row.latest_event_sequence,
        "latest_event_hash": row.latest_event_hash,
    }


def _append_lease_event(db: Session, row: CanonicalParserProgressiveAutomationLease, *, event_type: str, payload: dict[str, Any], at: datetime) -> None:
    sequence = int(row.latest_event_sequence) + 1
    body = {
        "lease_id": row.lease_id,
        "sequence": sequence,
        "event_type": event_type,
        "occurred_at": at.isoformat(),
        "payload": payload,
        "previous_event_hash": row.latest_event_hash,
    }
    event_hash = calculate_payload_hash(body)
    db.add(CanonicalParserProgressiveAutomationLeaseEvent(
        event_id=str(uuid4()), lease_db_id=row.id, sequence=sequence,
        event_type=event_type, event_payload=body,
        previous_event_hash=row.latest_event_hash, event_hash=event_hash,
        occurred_at=at,
    ))
    row.latest_event_sequence = sequence
    row.latest_event_hash = event_hash


def _append_breaker_event(db: Session, row: CanonicalParserProductionCircuitBreaker, *, event_type: str, payload: dict[str, Any], at: datetime) -> None:
    sequence = int(row.latest_event_sequence) + 1
    body = {
        "breaker_id": row.breaker_id,
        "sequence": sequence,
        "event_type": event_type,
        "occurred_at": at.isoformat(),
        "payload": payload,
        "previous_event_hash": row.latest_event_hash,
    }
    event_hash = calculate_payload_hash(body)
    db.add(CanonicalParserProductionCircuitBreakerEvent(
        event_id=str(uuid4()), breaker_db_id=row.id, sequence=sequence,
        event_type=event_type, event_payload=body,
        previous_event_hash=row.latest_event_hash, event_hash=event_hash,
        occurred_at=at,
    ))
    row.latest_event_sequence = sequence
    row.latest_event_hash = event_hash


def get_progressive_automation_status(db: Session, *, settings_object: Any = settings, evaluated_at: datetime | None = None) -> dict[str, Any]:
    now = _now(evaluated_at)
    leases = list(db.scalars(select(CanonicalParserProgressiveAutomationLease)))
    counts: dict[str, int] = {}
    for row in leases:
        status = _resolved_lease_status(row, now)
        counts[status] = counts.get(status, 0) + 1
    tripped = int(db.scalar(select(func.count(CanonicalParserProductionCircuitBreaker.id)).where(CanonicalParserProductionCircuitBreaker.status == "TRIPPED")) or 0)
    return {
        "policy": _policy(settings_object),
        "assessment_count": int(db.scalar(select(func.count(CanonicalParserProductionHardeningAssessment.id))) or 0),
        "lease_count": len(leases),
        "lease_status_counts": counts,
        "tripped_breaker_count": tripped,
        "health": _health_snapshot(db, now=now),
        "stage_order": list(_STAGE_ORDER),
        "safety": {
            "manual_trigger_only": True,
            "automatic_dispatch": False,
            "worker_connected": False,
            "scheduler_connected": False,
            "stream_connected": False,
        },
    }


def preview_production_hardening_assessment(
    db: Session,
    *,
    wallet_address: str,
    token_mint: str,
    requested_stage: str,
    requested_max_budget_sol: Any,
    requested_max_submissions: int,
    idempotency_token: str,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _now(evaluated_at)
    policy = _policy(settings_object)
    stage = str(requested_stage).strip().upper()
    if stage not in _STAGE_ORDER:
        raise CanonicalParserProgressiveAutomationError("Stage M46 non valido.", code="M46_INVALID_STAGE")
    if len(str(idempotency_token or "").strip()) < 8:
        raise CanonicalParserProgressiveAutomationError("Idempotency token M46 non valido.", code="M46_IDEMPOTENCY_INVALID")
    budget = _decimal(requested_max_budget_sol)
    submissions = int(requested_max_submissions)
    pilot = _pilot_evidence(db, wallet_address=str(wallet_address), token_mint=str(token_mint), now=now, lookback_days=policy["lookback_days"])
    health = _health_snapshot(db, now=now)
    eligible = _eligible_stage(pilot["completed_count"], policy)
    recommended_budget = _recommended_budget(eligible, pilot, policy)
    recommended_submissions = _recommended_submission_count(eligible, policy)
    reasons: list[str] = []
    data_reasons: list[str] = []
    if stage != "OBSERVE_ONLY" and pilot["completed_count"] < policy["min_completed_assisted"]:
        data_reasons.append("M46_COMPLETED_PILOT_EVIDENCE_INSUFFICIENT")
    if _STAGE_ORDER[stage] > _STAGE_ORDER[eligible]:
        data_reasons.append("M46_REQUESTED_STAGE_EXCEEDS_EVIDENCE")
    if pilot["aborted_count"] > 0:
        reasons.append("M46_ABORTED_PILOT_PRESENT")
    if pilot["expired_count"] > 0:
        reasons.append("M46_EXPIRED_PILOT_PRESENT")
    if pilot["active_count"] > 0:
        reasons.append("M46_ACTIVE_PILOT_PRESENT")
    if policy["require_healthy_observability"] and not health["healthy"]:
        reasons.append("M46_OPERATIONAL_HEALTH_NOT_READY")
    if policy["require_zero_active_incidents"] and health["active_incident_count"] > 0:
        reasons.append("M46_ACTIVE_INCIDENTS_PRESENT")
    if health["open_critical_alert_count"] > 0:
        reasons.append("M46_CRITICAL_ALERTS_PRESENT")
    if policy["require_zero_uncertain_submissions"] and health["unresolved_submission_count"] > 0:
        reasons.append("M46_UNRESOLVED_SUBMISSIONS_PRESENT")
    if budget < 0:
        reasons.append("M46_BUDGET_NEGATIVE")
    if stage == "OBSERVE_ONLY" and budget != 0:
        reasons.append("M46_OBSERVE_ONLY_BUDGET_MUST_BE_ZERO")
    if stage != "OBSERVE_ONLY" and budget <= 0:
        reasons.append("M46_BUDGET_NOT_POSITIVE")
    if budget > _decimal(policy["max_budget_sol"]):
        reasons.append("M46_POLICY_BUDGET_EXCEEDED")
    if _STAGE_ORDER[stage] <= _STAGE_ORDER[eligible] and budget > recommended_budget:
        reasons.append("M46_PROVEN_BUDGET_EXCEEDED")
    if submissions < 0:
        reasons.append("M46_SUBMISSION_COUNT_NEGATIVE")
    if stage == "OBSERVE_ONLY" and submissions != 0:
        reasons.append("M46_OBSERVE_ONLY_SUBMISSIONS_MUST_BE_ZERO")
    if _STAGE_ORDER[stage] <= _STAGE_ORDER[eligible] and submissions > recommended_submissions:
        reasons.append("M46_RECOMMENDED_SUBMISSION_COUNT_EXCEEDED")
    assessment_key = calculate_payload_hash({
        "wallet_address": str(wallet_address), "network": "mainnet-beta", "token_mint": str(token_mint),
        "requested_stage": stage, "requested_max_budget_sol": _money(budget),
        "requested_max_submissions": submissions, "idempotency_token": str(idempotency_token).strip(), "policy": policy,
    })
    existing = db.scalar(select(CanonicalParserProductionHardeningAssessment).where(CanonicalParserProductionHardeningAssessment.assessment_key == assessment_key))
    status = "READY"
    if data_reasons:
        status = "INSUFFICIENT_DATA"
    if reasons:
        status = "BLOCKED"
    all_reasons = sorted(set(data_reasons + reasons))
    evidence = {
        "wallet_address": str(wallet_address), "network": "mainnet-beta", "token_mint": str(token_mint),
        "requested_stage": stage, "eligible_stage": eligible,
        "requested_max_budget_sol": _money(budget), "recommended_max_budget_sol": _money(recommended_budget),
        "requested_max_submissions": submissions, "recommended_max_submissions": recommended_submissions,
        "pilot_evidence": pilot, "operational_health": health, "reason_codes": all_reasons,
        "evaluated_at": now.isoformat(),
    }
    evidence_hash = calculate_payload_hash(evidence)
    return {
        "status": status,
        "ready": status == "READY",
        "assessment_key": assessment_key,
        "existing_assessment": None if existing is None else _serialize_assessment(existing),
        "requested_stage": stage,
        "eligible_stage": eligible,
        "requested_max_budget_sol": _money(budget),
        "recommended_max_budget_sol": _money(recommended_budget),
        "requested_max_submissions": submissions,
        "recommended_max_submissions": recommended_submissions,
        "pilot_evidence": pilot,
        "operational_health": health,
        "reason_codes": all_reasons,
        "evidence_snapshot": evidence,
        "evidence_hash": evidence_hash,
        "confirmation": f"{ASSESS_PREFIX}:{assessment_key}:{evidence_hash}",
        "policy": policy,
    }


def assess_production_hardening(
    db: Session,
    *,
    wallet_address: str,
    token_mint: str,
    requested_stage: str,
    requested_max_budget_sol: Any,
    requested_max_submissions: int,
    idempotency_token: str,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    assessed_at: datetime | None = None,
) -> dict[str, Any]:
    if not _policy(settings_object)["enabled"]:
        raise CanonicalParserProgressiveAutomationError("M46 disabilitata.", code="M46_DISABLED", status_code=409)
    now = _now(assessed_at)
    preview = preview_production_hardening_assessment(
        db, wallet_address=wallet_address, token_mint=token_mint, requested_stage=requested_stage,
        requested_max_budget_sol=requested_max_budget_sol, requested_max_submissions=requested_max_submissions,
        idempotency_token=idempotency_token, settings_object=settings_object, evaluated_at=now,
    )
    if preview["existing_assessment"] is not None:
        return preview["existing_assessment"]
    if confirmation != preview["confirmation"]:
        raise CanonicalParserProgressiveAutomationError("Conferma assessment M46 non valida.", code="M46_ASSESS_CONFIRMATION_REQUIRED", status_code=409)
    policy = preview["policy"]
    row = CanonicalParserProductionHardeningAssessment(
        assessment_id=str(uuid4()), assessment_key=preview["assessment_key"],
        scope="M46_PRODUCTION_HARDENING_ASSESSMENT", status=preview["status"],
        wallet_address=str(wallet_address), network="mainnet-beta", token_mint=str(token_mint),
        requested_stage=preview["requested_stage"], eligible_stage=preview["eligible_stage"],
        completed_pilot_count=preview["pilot_evidence"]["completed_count"],
        aborted_pilot_count=preview["pilot_evidence"]["aborted_count"],
        expired_pilot_count=preview["pilot_evidence"]["expired_count"],
        unresolved_submission_count=preview["operational_health"]["unresolved_submission_count"],
        active_incident_count=preview["operational_health"]["active_incident_count"],
        open_critical_alert_count=preview["operational_health"]["open_critical_alert_count"],
        latest_observability_snapshot_id=preview["operational_health"]["snapshot_id"],
        requested_max_budget_sol=_decimal(preview["requested_max_budget_sol"]),
        recommended_max_budget_sol=_decimal(preview["recommended_max_budget_sol"]),
        requested_max_submissions=preview["requested_max_submissions"],
        recommended_max_submissions=preview["recommended_max_submissions"],
        reason_codes=preview["reason_codes"], evidence_snapshot=preview["evidence_snapshot"],
        policy_snapshot=policy, evidence_hash=preview["evidence_hash"], actor_label=_actor(actor_label), note=_note(note),
        assessed_at=now, expires_at=now + timedelta(minutes=policy["assessment_ttl_minutes"]),
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.scalar(select(CanonicalParserProductionHardeningAssessment).where(CanonicalParserProductionHardeningAssessment.assessment_key == preview["assessment_key"]))
        if duplicate is not None:
            return _serialize_assessment(duplicate)
        raise CanonicalParserProgressiveAutomationError("Conflitto assessment M46.", code="M46_ASSESSMENT_CONFLICT", status_code=409) from exc
    db.refresh(row)
    return _serialize_assessment(row)


def preview_progressive_automation_lease(
    db: Session,
    *,
    assessment_id: str,
    validity_minutes: int,
    idempotency_token: str,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _now(evaluated_at)
    policy = _policy(settings_object)
    assessment = db.scalar(select(CanonicalParserProductionHardeningAssessment).where(CanonicalParserProductionHardeningAssessment.assessment_id == assessment_id))
    reasons: list[str] = []
    if assessment is None:
        reasons.append("M46_ASSESSMENT_NOT_FOUND")
    else:
        if assessment.status != "READY":
            reasons.append("M46_ASSESSMENT_NOT_READY")
        if _now(assessment.expires_at) <= now:
            reasons.append("M46_ASSESSMENT_EXPIRED")
        if assessment.requested_stage == "OBSERVE_ONLY":
            reasons.append("M46_OBSERVE_ONLY_LEASE_NOT_REQUIRED")
    validity = int(validity_minutes)
    if validity < 1:
        reasons.append("M46_LEASE_VALIDITY_TOO_SHORT")
    if validity > policy["max_validity_minutes"]:
        reasons.append("M46_LEASE_VALIDITY_EXCEEDED")
    if assessment is not None and now + timedelta(minutes=validity) > _now(assessment.expires_at):
        reasons.append("M46_LEASE_EXCEEDS_ASSESSMENT")
    active = None
    if assessment is not None:
        active = db.scalar(select(CanonicalParserProgressiveAutomationLease).where(
            CanonicalParserProgressiveAutomationLease.wallet_address == assessment.wallet_address,
            CanonicalParserProgressiveAutomationLease.token_mint == assessment.token_mint,
            CanonicalParserProgressiveAutomationLease.status == "ACTIVE",
        ))
        if active is not None and _resolved_lease_status(active, now) == "ACTIVE":
            reasons.append("M46_ACTIVE_LEASE_ALREADY_EXISTS")
    lease_key = calculate_payload_hash({
        "assessment_id": assessment_id, "validity_minutes": validity,
        "idempotency_token": str(idempotency_token).strip(), "policy": policy,
    })
    existing = db.scalar(select(CanonicalParserProgressiveAutomationLease).where(CanonicalParserProgressiveAutomationLease.lease_key == lease_key))
    snapshot = {
        "assessment_id": assessment_id,
        "wallet_address": None if assessment is None else assessment.wallet_address,
        "network": None if assessment is None else assessment.network,
        "token_mint": None if assessment is None else assessment.token_mint,
        "stage": None if assessment is None else assessment.requested_stage,
        "max_budget_sol": None if assessment is None else _money(assessment.requested_max_budget_sol),
        "max_submission_count": None if assessment is None else assessment.requested_max_submissions,
        "validity_minutes": validity, "reason_codes": sorted(set(reasons)),
        "automatic_dispatch_permitted": False, "evaluated_at": now.isoformat(),
    }
    evidence_hash = calculate_payload_hash(snapshot)
    return {
        "status": "READY" if not reasons else "BLOCKED", "ready": not reasons,
        "lease_key": lease_key,
        "existing_lease": None if existing is None else _serialize_lease(existing, now=now),
        "assessment": None if assessment is None else _serialize_assessment(assessment),
        "lease_snapshot": snapshot, "reason_codes": sorted(set(reasons)),
        "evidence_hash": evidence_hash,
        "confirmation": f"{LEASE_PREFIX}:{lease_key}:{evidence_hash}", "policy": policy,
    }


def issue_progressive_automation_lease(
    db: Session,
    *,
    assessment_id: str,
    validity_minutes: int,
    idempotency_token: str,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    issued_at: datetime | None = None,
) -> dict[str, Any]:
    if not _policy(settings_object)["enabled"]:
        raise CanonicalParserProgressiveAutomationError("M46 disabilitata.", code="M46_DISABLED", status_code=409)
    now = _now(issued_at)
    preview = preview_progressive_automation_lease(db, assessment_id=assessment_id, validity_minutes=validity_minutes, idempotency_token=idempotency_token, settings_object=settings_object, evaluated_at=now)
    if preview["existing_lease"] is not None:
        return preview["existing_lease"]
    if preview["status"] != "READY":
        raise CanonicalParserProgressiveAutomationError("Lease M46 bloccata.", code="M46_LEASE_BLOCKED", status_code=409)
    if confirmation != preview["confirmation"]:
        raise CanonicalParserProgressiveAutomationError("Conferma lease M46 non valida.", code="M46_LEASE_CONFIRMATION_REQUIRED", status_code=409)
    assessment = db.scalar(select(CanonicalParserProductionHardeningAssessment).where(CanonicalParserProductionHardeningAssessment.assessment_id == assessment_id).with_for_update())
    assert assessment is not None
    lease_id = str(uuid4())
    initial_body = {
        "lease_id": lease_id, "sequence": 1, "event_type": "ISSUED", "occurred_at": now.isoformat(),
        "payload": {"assessment_id": assessment.assessment_id, "stage": assessment.requested_stage}, "previous_event_hash": None,
    }
    initial_hash = calculate_payload_hash(initial_body)
    row = CanonicalParserProgressiveAutomationLease(
        lease_id=lease_id, lease_key=preview["lease_key"], scope="M46_PROGRESSIVE_AUTOMATION_LEASE",
        assessment_db_id=assessment.id, assessment_id=assessment.assessment_id,
        wallet_address=assessment.wallet_address, network=assessment.network, token_mint=assessment.token_mint,
        stage=assessment.requested_stage, status="ACTIVE", max_budget_sol=assessment.requested_max_budget_sol,
        max_submission_count=assessment.requested_max_submissions, used_submission_count=0,
        automatic_dispatch_permitted=False, lease_snapshot={**preview["lease_snapshot"], "consumed_submission_ids": []}, evidence_hash=preview["evidence_hash"],
        actor_label=_actor(actor_label), note=_note(note), issued_at=now,
        expires_at=now + timedelta(minutes=int(validity_minutes)), revoked_at=None, tripped_at=None, exhausted_at=None,
        latest_event_sequence=1, latest_event_hash=initial_hash,
    )
    db.add(row)
    db.flush()
    db.add(CanonicalParserProgressiveAutomationLeaseEvent(
        event_id=str(uuid4()), lease_db_id=row.id, sequence=1, event_type="ISSUED", event_payload=initial_body,
        previous_event_hash=None, event_hash=initial_hash, occurred_at=now,
    ))
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.scalar(select(CanonicalParserProgressiveAutomationLease).where(CanonicalParserProgressiveAutomationLease.lease_key == preview["lease_key"]))
        if duplicate is not None:
            return _serialize_lease(duplicate, now=now)
        raise CanonicalParserProgressiveAutomationError("Conflitto lease M46.", code="M46_LEASE_CONFLICT", status_code=409) from exc
    db.refresh(row)
    return _serialize_lease(row, now=now)


def revoke_progressive_automation_lease(db: Session, *, lease_id: str, reason: str, confirmation: str, actor_label: str | None = None, settings_object: Any = settings, revoked_at: datetime | None = None) -> dict[str, Any]:
    if not _policy(settings_object)["enabled"]:
        raise CanonicalParserProgressiveAutomationError("M46 disabilitata.", code="M46_DISABLED", status_code=409)
    now = _now(revoked_at)
    row = db.scalar(select(CanonicalParserProgressiveAutomationLease).where(CanonicalParserProgressiveAutomationLease.lease_id == lease_id).with_for_update())
    if row is None:
        raise CanonicalParserProgressiveAutomationError("Lease M46 non trovata.", code="M46_LEASE_NOT_FOUND", status_code=404)
    if row.status in {"REVOKED", "EXPIRED", "EXHAUSTED", "TRIPPED"}:
        return _serialize_lease(row, now=now)
    expected = f"{REVOKE_PREFIX}:{row.lease_id}:{row.evidence_hash}"
    if confirmation != expected:
        raise CanonicalParserProgressiveAutomationError("Conferma revoca M46 non valida.", code="M46_REVOKE_CONFIRMATION_REQUIRED", status_code=409)
    row.status = "REVOKED"; row.revoked_at = now; row.actor_label = _actor(actor_label); row.note = _note(reason)
    _append_lease_event(db, row, event_type="REVOKED", payload={"reason": str(reason).strip()[:500]}, at=now)
    db.commit(); db.refresh(row)
    return _serialize_lease(row, now=now)


def preview_trip_production_circuit_breaker(db: Session, *, wallet_address: str, reason_codes: list[str], source_type: str, source_id: str | None, idempotency_token: str, evaluated_at: datetime | None = None) -> dict[str, Any]:
    now = _now(evaluated_at)
    normalized_reasons = sorted({str(item).strip()[:96] for item in reason_codes if str(item).strip()})
    if not normalized_reasons:
        normalized_reasons = ["MANUAL_TRIP"]
    source = str(source_type).strip().upper()
    if source not in {"MANUAL", "INCIDENT", "OBSERVABILITY", "SUBMISSION"}:
        raise CanonicalParserProgressiveAutomationError("Source type breaker M46 non valido.", code="M46_INVALID_BREAKER_SOURCE")
    breaker = db.scalar(select(CanonicalParserProductionCircuitBreaker).where(CanonicalParserProductionCircuitBreaker.wallet_address == str(wallet_address)))
    key = calculate_payload_hash({"wallet_address": str(wallet_address), "reason_codes": normalized_reasons, "source_type": source, "source_id": source_id, "idempotency_token": str(idempotency_token).strip()})
    snapshot = {"wallet_address": str(wallet_address), "network": "mainnet-beta", "reason_codes": normalized_reasons, "source_type": source, "source_id": source_id, "breaker_key": key, "evaluated_at": now.isoformat()}
    evidence_hash = calculate_payload_hash(snapshot)
    return {"status": "READY", "ready": True, "breaker_key": key, "existing_breaker": _serialize_breaker(breaker, wallet_address=str(wallet_address), now=now), "breaker_snapshot": snapshot, "evidence_hash": evidence_hash, "confirmation": f"{TRIP_PREFIX}:{key}:{evidence_hash}"}


def trip_production_circuit_breaker(db: Session, *, wallet_address: str, reason_codes: list[str], source_type: str, source_id: str | None, idempotency_token: str, confirmation: str, actor_label: str | None = None, note: str | None = None, settings_object: Any = settings, tripped_at: datetime | None = None) -> dict[str, Any]:
    if not _policy(settings_object)["circuit_breaker_enabled"]:
        raise CanonicalParserProgressiveAutomationError("Circuit breaker M46 disabilitato.", code="M46_BREAKER_DISABLED", status_code=409)
    now = _now(tripped_at)
    preview = preview_trip_production_circuit_breaker(db, wallet_address=wallet_address, reason_codes=reason_codes, source_type=source_type, source_id=source_id, idempotency_token=idempotency_token, evaluated_at=now)
    if confirmation != preview["confirmation"]:
        raise CanonicalParserProgressiveAutomationError("Conferma trip M46 non valida.", code="M46_TRIP_CONFIRMATION_REQUIRED", status_code=409)
    row = db.scalar(select(CanonicalParserProductionCircuitBreaker).where(CanonicalParserProductionCircuitBreaker.wallet_address == str(wallet_address)).with_for_update())
    if row is not None and row.status == "TRIPPED" and row.breaker_key == preview["breaker_key"]:
        return _serialize_breaker(row, wallet_address=str(wallet_address), now=now)
    if row is None:
        breaker_id = str(uuid4())
        body = {"breaker_id": breaker_id, "sequence": 1, "event_type": "TRIPPED", "occurred_at": now.isoformat(), "payload": preview["breaker_snapshot"], "previous_event_hash": None}
        event_hash = calculate_payload_hash(body)
        row = CanonicalParserProductionCircuitBreaker(
            breaker_id=breaker_id, breaker_key=preview["breaker_key"], scope="M46_PRODUCTION_CIRCUIT_BREAKER",
            wallet_address=str(wallet_address), network="mainnet-beta", status="TRIPPED",
            reason_codes=preview["breaker_snapshot"]["reason_codes"], source_type=preview["breaker_snapshot"]["source_type"], source_id=source_id,
            trip_count=1, reset_count=0, breaker_snapshot=preview["breaker_snapshot"], evidence_hash=preview["evidence_hash"],
            actor_label=_actor(actor_label), note=_note(note), tripped_at=now, reset_at=None,
            latest_event_sequence=1, latest_event_hash=event_hash,
        )
        db.add(row); db.flush()
        db.add(CanonicalParserProductionCircuitBreakerEvent(event_id=str(uuid4()), breaker_db_id=row.id, sequence=1, event_type="TRIPPED", event_payload=body, previous_event_hash=None, event_hash=event_hash, occurred_at=now))
    else:
        row.breaker_key = preview["breaker_key"]; row.status = "TRIPPED"; row.reason_codes = preview["breaker_snapshot"]["reason_codes"]
        row.source_type = preview["breaker_snapshot"]["source_type"]; row.source_id = source_id; row.trip_count = int(row.trip_count) + 1
        row.breaker_snapshot = preview["breaker_snapshot"]; row.evidence_hash = preview["evidence_hash"]; row.actor_label = _actor(actor_label); row.note = _note(note); row.tripped_at = now
        _append_breaker_event(db, row, event_type="TRIPPED", payload=preview["breaker_snapshot"], at=now)
    leases = list(db.scalars(select(CanonicalParserProgressiveAutomationLease).where(CanonicalParserProgressiveAutomationLease.wallet_address == str(wallet_address), CanonicalParserProgressiveAutomationLease.status == "ACTIVE").with_for_update()))
    for lease in leases:
        lease.status = "TRIPPED"; lease.tripped_at = now
        _append_lease_event(db, lease, event_type="TRIPPED", payload={"breaker_id": row.breaker_id, "reason_codes": row.reason_codes}, at=now)
    db.commit(); db.refresh(row)
    return _serialize_breaker(row, wallet_address=str(wallet_address), now=now)


def preview_reset_production_circuit_breaker(db: Session, *, breaker_id: str, resolution_evidence: str, evaluated_at: datetime | None = None) -> dict[str, Any]:
    now = _now(evaluated_at)
    row = db.scalar(select(CanonicalParserProductionCircuitBreaker).where(CanonicalParserProductionCircuitBreaker.breaker_id == breaker_id))
    reasons: list[str] = []
    if row is None:
        reasons.append("M46_BREAKER_NOT_FOUND")
    elif row.status != "TRIPPED":
        reasons.append("M46_BREAKER_NOT_TRIPPED")
    health = _health_snapshot(db, now=now)
    if not health["healthy"]:
        reasons.append("M46_RESET_HEALTH_NOT_READY")
    if len(str(resolution_evidence or "").strip()) < 8:
        reasons.append("M46_RESET_EVIDENCE_INSUFFICIENT")
    snapshot = {"breaker_id": breaker_id, "wallet_address": None if row is None else row.wallet_address, "resolution_evidence": str(resolution_evidence).strip()[:500], "operational_health": health, "reason_codes": sorted(set(reasons)), "evaluated_at": now.isoformat()}
    evidence_hash = calculate_payload_hash(snapshot)
    return {"status": "READY" if not reasons else "BLOCKED", "ready": not reasons, "reset_snapshot": snapshot, "reason_codes": sorted(set(reasons)), "evidence_hash": evidence_hash, "confirmation": f"{RESET_PREFIX}:{breaker_id}:{evidence_hash}"}


def reset_production_circuit_breaker(db: Session, *, breaker_id: str, resolution_evidence: str, confirmation: str, actor_label: str | None = None, note: str | None = None, settings_object: Any = settings, reset_at: datetime | None = None) -> dict[str, Any]:
    if not _policy(settings_object)["circuit_breaker_enabled"]:
        raise CanonicalParserProgressiveAutomationError("Circuit breaker M46 disabilitato.", code="M46_BREAKER_DISABLED", status_code=409)
    now = _now(reset_at)
    preview = preview_reset_production_circuit_breaker(db, breaker_id=breaker_id, resolution_evidence=resolution_evidence, evaluated_at=now)
    if preview["status"] != "READY":
        raise CanonicalParserProgressiveAutomationError("Reset breaker M46 bloccato.", code="M46_RESET_BLOCKED", status_code=409)
    if confirmation != preview["confirmation"]:
        raise CanonicalParserProgressiveAutomationError("Conferma reset M46 non valida.", code="M46_RESET_CONFIRMATION_REQUIRED", status_code=409)
    row = db.scalar(select(CanonicalParserProductionCircuitBreaker).where(CanonicalParserProductionCircuitBreaker.breaker_id == breaker_id).with_for_update())
    assert row is not None
    row.status = "CLEAR"; row.reset_count = int(row.reset_count) + 1; row.reset_at = now; row.reason_codes = []
    row.breaker_snapshot = preview["reset_snapshot"]; row.evidence_hash = preview["evidence_hash"]; row.actor_label = _actor(actor_label); row.note = _note(note)
    _append_breaker_event(db, row, event_type="RESET", payload=preview["reset_snapshot"], at=now)
    db.commit(); db.refresh(row)
    return _serialize_breaker(row, wallet_address=row.wallet_address, now=now)


def validate_progressive_automation_lease_for_submission(
    db: Session,
    *,
    lease_id: str | None,
    side: str,
    token_mint: str,
    requested_budget_sol: Any,
    wallet_address: str | None,
    assisted_micro_live_pilot_id: str | None,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _now(evaluated_at)
    policy = _policy(settings_object)
    if not policy["guard_enabled"]:
        return {"required": False, "ready": True, "reason_codes": [], "lease": None, "snapshot": {"guard_enabled": False, "manual_trigger_only": True, "automatic_dispatch": False}}
    reasons: list[str] = []
    row = None
    if not lease_id:
        reasons.append("M46_PROGRESSIVE_AUTOMATION_LEASE_REQUIRED")
    else:
        row = db.scalar(select(CanonicalParserProgressiveAutomationLease).where(CanonicalParserProgressiveAutomationLease.lease_id == lease_id).with_for_update())
        if row is None:
            reasons.append("M46_PROGRESSIVE_AUTOMATION_LEASE_NOT_FOUND")
    budget = _decimal(requested_budget_sol)
    breaker = None
    if row is not None:
        resolved = _resolved_lease_status(row, now)
        if resolved != "ACTIVE":
            reasons.append(f"M46_PROGRESSIVE_AUTOMATION_LEASE_{resolved}")
        if row.wallet_address != str(wallet_address or ""):
            reasons.append("M46_PROGRESSIVE_AUTOMATION_WALLET_MISMATCH")
        if row.token_mint != str(token_mint):
            reasons.append("M46_PROGRESSIVE_AUTOMATION_TOKEN_MISMATCH")
        if budget > Decimal(row.max_budget_sol):
            reasons.append("M46_PROGRESSIVE_AUTOMATION_BUDGET_EXCEEDED")
        if int(row.used_submission_count) >= int(row.max_submission_count):
            reasons.append("M46_PROGRESSIVE_AUTOMATION_SUBMISSION_LIMIT_EXCEEDED")
        if row.stage == "OBSERVE_ONLY":
            reasons.append("M46_OBSERVE_ONLY_SUBMISSION_BLOCKED")
        if row.stage == "ASSISTED" and not assisted_micro_live_pilot_id:
            reasons.append("M46_ASSISTED_STAGE_REQUIRES_M45_PILOT")
        if row.automatic_dispatch_permitted:
            reasons.append("M46_AUTOMATIC_DISPATCH_FORBIDDEN")
        breaker = db.scalar(select(CanonicalParserProductionCircuitBreaker).where(CanonicalParserProductionCircuitBreaker.wallet_address == row.wallet_address))
        if breaker is not None and breaker.status == "TRIPPED":
            reasons.append("M46_PRODUCTION_CIRCUIT_BREAKER_TRIPPED")
    snapshot = {
        "guard_enabled": True,
        "lease_id": lease_id,
        "lease_status": None if row is None else _resolved_lease_status(row, now),
        "wallet_address": wallet_address,
        "token_mint": token_mint,
        "side": str(side).upper(),
        "requested_budget_sol": _money(budget),
        "stage": None if row is None else row.stage,
        "max_budget_sol": None if row is None else _money(row.max_budget_sol),
        "used_submission_count": None if row is None else row.used_submission_count,
        "max_submission_count": None if row is None else row.max_submission_count,
        "breaker_status": "CLEAR" if breaker is None else breaker.status,
        "manual_trigger_only": True,
        "automatic_dispatch": False,
        "reason_codes": sorted(set(reasons)),
        "evaluated_at": now.isoformat(),
    }
    return {"required": True, "ready": not reasons, "reason_codes": sorted(set(reasons)), "lease": row, "snapshot": snapshot}


def consume_progressive_automation_lease_submission_slot(
    db: Session,
    *,
    lease_id: str,
    submission_id: str,
    side: str,
    token_mint: str,
    requested_budget_sol: Any,
    wallet_address: str | None,
    assisted_micro_live_pilot_id: str | None,
    settings_object: Any = settings,
    consumed_at: datetime | None = None,
) -> dict[str, Any]:
    now = _now(consumed_at)
    row = db.scalar(
        select(CanonicalParserProgressiveAutomationLease)
        .where(CanonicalParserProgressiveAutomationLease.lease_id == lease_id)
        .with_for_update()
    )
    if row is not None:
        lease_snapshot = dict(row.lease_snapshot or {})
        consumed_ids = list(lease_snapshot.get("consumed_submission_ids") or [])
        if str(submission_id) in consumed_ids:
            return _serialize_lease(row, now=now)

    validation = validate_progressive_automation_lease_for_submission(
        db, lease_id=lease_id, side=side, token_mint=token_mint, requested_budget_sol=requested_budget_sol,
        wallet_address=wallet_address, assisted_micro_live_pilot_id=assisted_micro_live_pilot_id,
        settings_object=settings_object, evaluated_at=now,
    )
    if not validation["ready"]:
        raise CanonicalParserProgressiveAutomationError("Consumo lease M46 bloccato.", code="M46_LEASE_CONSUMPTION_BLOCKED", status_code=409)
    row = validation["lease"]
    assert row is not None
    lease_snapshot = dict(row.lease_snapshot or {})
    consumed_ids = list(lease_snapshot.get("consumed_submission_ids") or [])
    consumed_ids.append(str(submission_id))
    lease_snapshot["consumed_submission_ids"] = consumed_ids[-100:]
    row.lease_snapshot = lease_snapshot
    row.used_submission_count = int(row.used_submission_count) + 1
    event_type = "CONSUMED"
    if row.used_submission_count >= row.max_submission_count:
        row.status = "EXHAUSTED"; row.exhausted_at = now; event_type = "EXHAUSTED"
    _append_lease_event(db, row, event_type=event_type, payload={"submission_id": submission_id, "side": str(side).upper(), "token_mint": token_mint, "requested_budget_sol": _money(requested_budget_sol), "used_submission_count": row.used_submission_count}, at=now)
    db.flush()
    return _serialize_lease(row, now=now)


def get_production_hardening_assessment(db: Session, assessment_id: str) -> dict[str, Any]:
    row = db.scalar(select(CanonicalParserProductionHardeningAssessment).where(CanonicalParserProductionHardeningAssessment.assessment_id == assessment_id))
    if row is None:
        raise CanonicalParserProgressiveAutomationError("Assessment M46 non trovato.", code="M46_ASSESSMENT_NOT_FOUND", status_code=404)
    return _serialize_assessment(row)


def get_progressive_automation_lease(db: Session, lease_id: str, *, evaluated_at: datetime | None = None) -> dict[str, Any]:
    now = _now(evaluated_at)
    row = db.scalar(select(CanonicalParserProgressiveAutomationLease).where(CanonicalParserProgressiveAutomationLease.lease_id == lease_id))
    if row is None:
        raise CanonicalParserProgressiveAutomationError("Lease M46 non trovata.", code="M46_LEASE_NOT_FOUND", status_code=404)
    return _serialize_lease(row, now=now)


def get_production_circuit_breaker(db: Session, *, wallet_address: str, evaluated_at: datetime | None = None) -> dict[str, Any]:
    now = _now(evaluated_at)
    row = db.scalar(select(CanonicalParserProductionCircuitBreaker).where(CanonicalParserProductionCircuitBreaker.wallet_address == wallet_address))
    return _serialize_breaker(row, wallet_address=wallet_address, now=now)


def resolve_progressive_automation(db: Session, *, wallet_address: str | None = None, token_mint: str | None = None, limit: int = 50, evaluated_at: datetime | None = None) -> dict[str, Any]:
    now = _now(evaluated_at)
    query = select(CanonicalParserProgressiveAutomationLease)
    if wallet_address:
        query = query.where(CanonicalParserProgressiveAutomationLease.wallet_address == wallet_address)
    if token_mint:
        query = query.where(CanonicalParserProgressiveAutomationLease.token_mint == token_mint)
    leases = list(db.scalars(query.order_by(CanonicalParserProgressiveAutomationLease.issued_at.desc()).limit(max(1, min(int(limit), 200)))))
    return {"items": [_serialize_lease(row, now=now) for row in leases], "count": len(leases), "evaluated_at": now}
