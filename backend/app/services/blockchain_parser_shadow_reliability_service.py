from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserShadowReliabilityAssessment,
    CanonicalParserShadowReliabilityEvidenceLoop,
    CanonicalParserShadowSchedulerWorkerState,
    CanonicalParserShadowWorkerLoopRun,
    CanonicalParserShadowWorkerRecoveryAction,
    CanonicalParserShadowWorkerRecoveryRun,
)
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    sanitize_error_message,
    sanitize_technical_metadata,
)
from backend.app.services.blockchain_parser_shadow_worker_service import (
    SHADOW_WORKER_NAME,
    get_shadow_worker_state,
)

SHADOW_RELIABILITY_POLICY_VERSION = "canonical-parser-shadow-reliability/1"
SHADOW_RELIABILITY_PREFIX = "ASSESS_SHADOW_AUTOMATION_RELIABILITY"
_MAX_ACTOR_LENGTH = 80
_MAX_NOTE_LENGTH = 500


class CanonicalParserShadowReliabilityError(ValueError):
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
    return sanitize_error_message(value or "LOCAL_RELIABILITY", max_length=_MAX_ACTOR_LENGTH) or "LOCAL_RELIABILITY"


def _note(value: str | None) -> str | None:
    if not str(value or "").strip():
        return None
    return sanitize_error_message(value, max_length=_MAX_NOTE_LENGTH)


def _policy_snapshot(settings_object: Any) -> dict[str, Any]:
    return {
        "policy_version": SHADOW_RELIABILITY_POLICY_VERSION,
        "lookback_minutes": int(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_RELIABILITY_LOOKBACK_MINUTES", 60)
        ),
        "minimum_loop_runs": int(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_RELIABILITY_MIN_LOOP_RUNS", 3)
        ),
        "minimum_completed_iterations": int(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_RELIABILITY_MIN_ITERATIONS", 10)
        ),
        "minimum_pass_rate": float(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_RELIABILITY_MIN_PASS_RATE", 95.0)
        ),
        "maximum_failed_iterations": int(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_RELIABILITY_MAX_FAILED_ITERATIONS", 0)
        ),
        "maximum_circuit_open_runs": int(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_RELIABILITY_MAX_CIRCUIT_OPEN_RUNS", 0)
        ),
        "maximum_recovery_actions": int(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_RELIABILITY_MAX_RECOVERY_ACTIONS", 0)
        ),
        "minimum_observation_minutes": int(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_RELIABILITY_MIN_OBSERVATION_MINUTES", 5)
        ),
        "validity_minutes": int(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_RELIABILITY_VALIDITY_MINUTES", 15)
        ),
        "manual_assessment_only": True,
        "paper_admission_connected": False,
        "live_admission_connected": False,
        "network_allowed": False,
        "writes_trades": False,
    }


def _loop_payload(loop: CanonicalParserShadowWorkerLoopRun) -> dict[str, Any]:
    return {
        "loop_id": loop.loop_id,
        "loop_key": loop.loop_key,
        "worker_generation": loop.worker_generation,
        "lease_epoch": loop.lease_epoch,
        "owner_id": loop.owner_id,
        "status": loop.status,
        "requested_iterations": loop.requested_iterations,
        "completed_iterations": loop.completed_iterations,
        "passed_iterations": loop.passed_iterations,
        "partial_iterations": loop.partial_iterations,
        "idle_iterations": loop.idle_iterations,
        "failed_iterations": loop.failed_iterations,
        "skipped_iterations": loop.skipped_iterations,
        "observed_consecutive_failures": loop.observed_consecutive_failures,
        "circuit_breaker_open": loop.circuit_breaker_open,
        "kill_switch_enforced": loop.kill_switch_enforced,
        "policy_snapshot": loop.policy_snapshot,
        "summary": loop.summary,
        "started_at": _aware(loop.started_at).isoformat(),
        "completed_at": _aware(loop.completed_at).isoformat() if loop.completed_at else None,
    }


def _serialize_assessment(db: Session, assessment: CanonicalParserShadowReliabilityAssessment) -> dict[str, Any]:
    evidence = list(
        db.scalars(
            select(CanonicalParserShadowReliabilityEvidenceLoop)
            .where(CanonicalParserShadowReliabilityEvidenceLoop.assessment_db_id == assessment.id)
            .order_by(CanonicalParserShadowReliabilityEvidenceLoop.sequence.asc())
        )
    )
    return {
        "assessment_id": assessment.assessment_id,
        "assessment_key": assessment.assessment_key,
        "status": assessment.status,
        "worker_generation": assessment.worker_generation,
        "lease_epoch": assessment.lease_epoch,
        "worker_event_hash": assessment.worker_event_hash,
        "loop_count": assessment.loop_count,
        "completed_iteration_count": assessment.completed_iteration_count,
        "passed_iteration_count": assessment.passed_iteration_count,
        "partial_iteration_count": assessment.partial_iteration_count,
        "idle_iteration_count": assessment.idle_iteration_count,
        "failed_iteration_count": assessment.failed_iteration_count,
        "skipped_iteration_count": assessment.skipped_iteration_count,
        "circuit_open_count": assessment.circuit_open_count,
        "recovery_run_count": assessment.recovery_run_count,
        "recovery_action_count": assessment.recovery_action_count,
        "pass_rate": float(assessment.pass_rate),
        "observation_started_at": assessment.observation_started_at,
        "observation_completed_at": assessment.observation_completed_at,
        "reason_codes": assessment.reason_codes,
        "policy_snapshot": assessment.policy_snapshot,
        "evidence_hash": assessment.evidence_hash,
        "evidence_snapshot": assessment.evidence_snapshot,
        "metrics_snapshot": assessment.metrics_snapshot,
        "actor_label": assessment.actor_label,
        "note": assessment.note,
        "evaluated_at": assessment.evaluated_at,
        "valid_until": assessment.valid_until,
        "evidence_loops": [
            {
                "sequence": item.sequence,
                "loop_id": item.loop_id,
                "status": item.status,
                "completed_iterations": item.completed_iterations,
                "passed_iterations": item.passed_iterations,
                "partial_iterations": item.partial_iterations,
                "idle_iterations": item.idle_iterations,
                "failed_iterations": item.failed_iterations,
                "skipped_iterations": item.skipped_iterations,
                "circuit_breaker_open": item.circuit_breaker_open,
                "loop_evidence_hash": item.loop_evidence_hash,
                "started_at": item.started_at,
                "completed_at": item.completed_at,
            }
            for item in evidence
        ],
        "paper_authorized": False,
        "live_authorized": False,
    }


def preview_shadow_reliability_assessment(
    db: Session,
    *,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _policy_snapshot(settings_object)
    cutoff = now - timedelta(minutes=policy["lookback_minutes"])
    state_model = db.scalar(
        select(CanonicalParserShadowSchedulerWorkerState).where(
            CanonicalParserShadowSchedulerWorkerState.worker_name == SHADOW_WORKER_NAME
        )
    )
    state = get_shadow_worker_state(db, settings_object=settings_object, evaluated_at=now)
    loops = list(
        db.scalars(
            select(CanonicalParserShadowWorkerLoopRun)
            .where(
                CanonicalParserShadowWorkerLoopRun.completed_at.is_not(None),
                CanonicalParserShadowWorkerLoopRun.completed_at >= cutoff,
            )
            .order_by(CanonicalParserShadowWorkerLoopRun.started_at.asc())
        )
    )
    recovery_runs = list(
        db.scalars(
            select(CanonicalParserShadowWorkerRecoveryRun).where(
                CanonicalParserShadowWorkerRecoveryRun.started_at >= cutoff
            )
        )
    )
    recovery_ids = [item.id for item in recovery_runs]
    recovery_action_count = 0
    if recovery_ids:
        recovery_action_count = int(
            db.scalar(
                select(func.count(CanonicalParserShadowWorkerRecoveryAction.id)).where(
                    CanonicalParserShadowWorkerRecoveryAction.recovery_run_db_id.in_(recovery_ids)
                )
            )
            or 0
        )
    completed = sum(int(item.completed_iterations or 0) for item in loops)
    passed = sum(int(item.passed_iterations or 0) for item in loops)
    partial = sum(int(item.partial_iterations or 0) for item in loops)
    idle = sum(int(item.idle_iterations or 0) for item in loops)
    failed = sum(int(item.failed_iterations or 0) for item in loops)
    skipped = sum(int(item.skipped_iterations or 0) for item in loops)
    circuit_open = sum(1 for item in loops if item.circuit_breaker_open or item.status == "CIRCUIT_OPEN")
    pass_rate = round((passed / completed) * 100, 4) if completed else 0.0
    observation_started = min((_aware(item.started_at) for item in loops), default=None)
    observation_completed = max((_aware(item.completed_at) for item in loops if item.completed_at), default=None)
    observation_minutes = (
        (observation_completed - observation_started).total_seconds() / 60
        if observation_started and observation_completed
        else 0.0
    )
    loop_evidence = [
        {"loop_db_id": item.id, "payload": _loop_payload(item), "hash": calculate_payload_hash(_loop_payload(item))}
        for item in loops
    ]
    metrics = {
        "loop_count": len(loops),
        "completed_iteration_count": completed,
        "passed_iteration_count": passed,
        "partial_iteration_count": partial,
        "idle_iteration_count": idle,
        "failed_iteration_count": failed,
        "skipped_iteration_count": skipped,
        "circuit_open_count": circuit_open,
        "recovery_run_count": len(recovery_runs),
        "recovery_action_count": recovery_action_count,
        "pass_rate": pass_rate,
        "observation_minutes": round(observation_minutes, 4),
    }
    reasons: set[str] = set()
    audit_reasons = list(state.get("audit_reason_codes") or [])
    if audit_reasons:
        reasons.update(audit_reasons)
    if state.get("status") == "ACTIVE" and not state.get("worker_ready"):
        reasons.add("SHADOW_RELIABILITY_WORKER_NOT_HEALTHY")
    if failed > policy["maximum_failed_iterations"]:
        reasons.add("SHADOW_RELIABILITY_FAILED_ITERATIONS_EXCEEDED")
    if circuit_open > policy["maximum_circuit_open_runs"]:
        reasons.add("SHADOW_RELIABILITY_CIRCUIT_OPEN_EXCEEDED")
    if recovery_action_count > policy["maximum_recovery_actions"]:
        reasons.add("SHADOW_RELIABILITY_RECOVERY_ACTIONS_EXCEEDED")
    if len(loops) < policy["minimum_loop_runs"]:
        reasons.add("SHADOW_RELIABILITY_LOOP_EVIDENCE_INSUFFICIENT")
    if completed < policy["minimum_completed_iterations"]:
        reasons.add("SHADOW_RELIABILITY_ITERATION_EVIDENCE_INSUFFICIENT")
    if observation_minutes < policy["minimum_observation_minutes"]:
        reasons.add("SHADOW_RELIABILITY_OBSERVATION_WINDOW_INSUFFICIENT")
    if completed and pass_rate < policy["minimum_pass_rate"]:
        reasons.add("SHADOW_RELIABILITY_PASS_RATE_BELOW_THRESHOLD")

    blocked_codes = {
        "SHADOW_RELIABILITY_WORKER_NOT_HEALTHY",
        "SHADOW_RELIABILITY_FAILED_ITERATIONS_EXCEEDED",
        "SHADOW_RELIABILITY_CIRCUIT_OPEN_EXCEEDED",
        "SHADOW_RELIABILITY_RECOVERY_ACTIONS_EXCEEDED",
    }
    insufficient_codes = {
        "SHADOW_RELIABILITY_LOOP_EVIDENCE_INSUFFICIENT",
        "SHADOW_RELIABILITY_ITERATION_EVIDENCE_INSUFFICIENT",
        "SHADOW_RELIABILITY_OBSERVATION_WINDOW_INSUFFICIENT",
    }
    if reasons & blocked_codes or audit_reasons:
        status = "BLOCKED"
    elif reasons & insufficient_codes:
        status = "INSUFFICIENT_DATA"
    elif "SHADOW_RELIABILITY_PASS_RATE_BELOW_THRESHOLD" in reasons:
        status = "REVIEW"
    else:
        status = "READY"

    evidence_snapshot = {
        "worker": {
            "exists": state.get("exists", False),
            "status": state.get("status"),
            "generation": state.get("generation", 0),
            "lease_epoch": state.get("lease_epoch", 0),
            "latest_event_hash": state.get("latest_event_hash"),
            "audit_reason_codes": audit_reasons,
        },
        "loop_hashes": [item["hash"] for item in loop_evidence],
        "recovery_ids": [item.recovery_id for item in recovery_runs],
    }
    evidence_hash = calculate_payload_hash(evidence_snapshot)
    policy_hash = calculate_payload_hash(policy)
    manifest = {
        "worker_state_db_id": state_model.id if state_model else None,
        "worker_generation": state.get("generation", 0),
        "lease_epoch": state.get("lease_epoch", 0),
        "worker_event_hash": state.get("latest_event_hash"),
        "status": status,
        "metrics": metrics,
        "reason_codes": sorted(reasons),
        "policy_hash": policy_hash,
        "evidence_hash": evidence_hash,
    }
    assessment_key = calculate_payload_hash(manifest)
    return {
        "status": status,
        "reason_codes": sorted(reasons),
        "assessment_key": assessment_key,
        "confirmation": f"{SHADOW_RELIABILITY_PREFIX}:{assessment_key[:16]}",
        "worker_state_db_id": state_model.id if state_model else None,
        "worker_state": sanitize_technical_metadata(state),
        "metrics": metrics,
        "policy": policy,
        "policy_hash": policy_hash,
        "evidence_hash": evidence_hash,
        "evidence_snapshot": sanitize_technical_metadata(evidence_snapshot),
        "loop_evidence": loop_evidence,
        "observation_started_at": observation_started,
        "observation_completed_at": observation_completed,
        "paper_authorized": False,
        "live_authorized": False,
    }


def execute_shadow_reliability_assessment(
    db: Session,
    *,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(
        getattr(settings_object, "CANONICAL_PARSER_SHADOW_RELIABILITY_ENABLED", False)
    ):
        raise CanonicalParserShadowReliabilityError(
            "Shadow reliability assessment disabilitato.",
            code="CANONICAL_PARSER_SHADOW_RELIABILITY_DISABLED",
            status_code=409,
        )
    now = _aware(evaluated_at)
    parts = str(confirmation or "").split(":")
    if len(parts) == 2 and parts[0] == SHADOW_RELIABILITY_PREFIX:
        existing_retry = db.scalar(
            select(CanonicalParserShadowReliabilityAssessment).where(
                CanonicalParserShadowReliabilityAssessment.assessment_key.like(f"{parts[1]}%")
            )
        )
        if existing_retry is not None:
            return _serialize_assessment(db, existing_retry)
    preview = preview_shadow_reliability_assessment(
        db,
        settings_object=settings_object,
        evaluated_at=now,
    )
    if confirmation != preview["confirmation"]:
        raise CanonicalParserShadowReliabilityError(
            "Conferma reliability assessment non valida.",
            code="SHADOW_RELIABILITY_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    existing = db.scalar(
        select(CanonicalParserShadowReliabilityAssessment).where(
            CanonicalParserShadowReliabilityAssessment.assessment_key == preview["assessment_key"]
        )
    )
    if existing is not None:
        return _serialize_assessment(db, existing)
    metrics = preview["metrics"]
    assessment = CanonicalParserShadowReliabilityAssessment(
        assessment_id=str(uuid4()),
        assessment_key=preview["assessment_key"],
        worker_state_db_id=preview["worker_state_db_id"],
        worker_generation=int(preview["worker_state"].get("generation", 0)),
        lease_epoch=int(preview["worker_state"].get("lease_epoch", 0)),
        worker_event_hash=preview["worker_state"].get("latest_event_hash"),
        status=preview["status"],
        loop_count=metrics["loop_count"],
        completed_iteration_count=metrics["completed_iteration_count"],
        passed_iteration_count=metrics["passed_iteration_count"],
        partial_iteration_count=metrics["partial_iteration_count"],
        idle_iteration_count=metrics["idle_iteration_count"],
        failed_iteration_count=metrics["failed_iteration_count"],
        skipped_iteration_count=metrics["skipped_iteration_count"],
        circuit_open_count=metrics["circuit_open_count"],
        recovery_run_count=metrics["recovery_run_count"],
        recovery_action_count=metrics["recovery_action_count"],
        pass_rate=Decimal(str(metrics["pass_rate"])),
        observation_started_at=preview["observation_started_at"],
        observation_completed_at=preview["observation_completed_at"],
        reason_codes=preview["reason_codes"],
        policy_version=SHADOW_RELIABILITY_POLICY_VERSION,
        policy_hash=preview["policy_hash"],
        policy_snapshot=preview["policy"],
        evidence_hash=preview["evidence_hash"],
        evidence_snapshot=preview["evidence_snapshot"],
        metrics_snapshot=metrics,
        actor_label=_actor(actor_label),
        note=_note(note),
        evaluated_at=now,
        valid_until=now + timedelta(minutes=preview["policy"]["validity_minutes"]),
    )
    db.add(assessment)
    try:
        db.flush()
        for sequence, item in enumerate(preview["loop_evidence"], start=1):
            payload = item["payload"]
            db.add(
                CanonicalParserShadowReliabilityEvidenceLoop(
                    assessment_db_id=assessment.id,
                    sequence=sequence,
                    loop_run_db_id=item["loop_db_id"],
                    loop_id=payload["loop_id"],
                    status=payload["status"],
                    completed_iterations=payload["completed_iterations"],
                    passed_iterations=payload["passed_iterations"],
                    partial_iterations=payload["partial_iterations"],
                    idle_iterations=payload["idle_iterations"],
                    failed_iterations=payload["failed_iterations"],
                    skipped_iterations=payload["skipped_iterations"],
                    circuit_breaker_open=payload["circuit_breaker_open"],
                    loop_evidence_hash=item["hash"],
                    started_at=_aware(datetime.fromisoformat(payload["started_at"])),
                    completed_at=(
                        _aware(datetime.fromisoformat(payload["completed_at"]))
                        if payload["completed_at"]
                        else None
                    ),
                )
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(
            select(CanonicalParserShadowReliabilityAssessment).where(
                CanonicalParserShadowReliabilityAssessment.assessment_key == preview["assessment_key"]
            )
        )
        if existing is not None:
            return _serialize_assessment(db, existing)
        raise CanonicalParserShadowReliabilityError(
            "Conflitto durante il reliability assessment.",
            code="SHADOW_RELIABILITY_CONFLICT",
            status_code=409,
        ) from exc
    db.refresh(assessment)
    return _serialize_assessment(db, assessment)


def get_shadow_reliability_assessment(db: Session, assessment_id: str) -> dict[str, Any]:
    assessment = db.scalar(
        select(CanonicalParserShadowReliabilityAssessment).where(
            CanonicalParserShadowReliabilityAssessment.assessment_id == assessment_id
        )
    )
    if assessment is None:
        raise CanonicalParserShadowReliabilityError(
            "Reliability assessment non trovato.",
            code="SHADOW_RELIABILITY_NOT_FOUND",
            status_code=404,
        )
    return _serialize_assessment(db, assessment)


def resolve_shadow_reliability(
    db: Session,
    *,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    assessment = db.scalar(
        select(CanonicalParserShadowReliabilityAssessment)
        .order_by(CanonicalParserShadowReliabilityAssessment.evaluated_at.desc())
        .limit(1)
    )
    if assessment is None:
        return {
            "status": "UNASSESSED",
            "assessment_id": None,
            "paper_authorized": False,
            "live_authorized": False,
        }
    result = _serialize_assessment(db, assessment)
    if assessment.status != "READY":
        result["resolved_status"] = assessment.status
        return result
    if _aware(assessment.valid_until) <= now:
        result["resolved_status"] = "EXPIRED"
        return result
    preview = preview_shadow_reliability_assessment(
        db,
        settings_object=settings_object,
        evaluated_at=now,
    )
    if (
        preview["evidence_hash"] != assessment.evidence_hash
        or preview["policy_hash"] != assessment.policy_hash
        or preview["worker_state"].get("generation", 0) != assessment.worker_generation
        or preview["worker_state"].get("lease_epoch", 0) != assessment.lease_epoch
        or preview["worker_state"].get("latest_event_hash") != assessment.worker_event_hash
    ):
        result["resolved_status"] = "DRIFTED"
        return result
    result["resolved_status"] = "READY"
    return result


def get_shadow_reliability_status(
    db: Session,
    *,
    settings_object: Any = settings,
) -> dict[str, Any]:
    return {
        "enabled": bool(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_RELIABILITY_ENABLED", False)
        ),
        "policy": _policy_snapshot(settings_object),
        "assessment_count": int(
            db.scalar(select(func.count(CanonicalParserShadowReliabilityAssessment.id))) or 0
        ),
        "evidence_loop_count": int(
            db.scalar(select(func.count(CanonicalParserShadowReliabilityEvidenceLoop.id))) or 0
        ),
        "operational_guards": {
            "manual_assessment_only": True,
            "paper_admission_connected": False,
            "live_admission_connected": False,
            "network_allowed": False,
            "writes_trades": False,
        },
    }
