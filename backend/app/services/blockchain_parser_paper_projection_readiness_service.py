from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserPaperProjectionReadinessAssessment,
    CanonicalParserPaperProjectionReadinessEvidenceRun,
    CanonicalParserPaperProjectionResult,
    CanonicalParserPaperProjectionRun,
    CanonicalParserShadowReliabilityCertification,
)
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    sanitize_error_message,
    sanitize_technical_metadata,
)
from backend.app.services.blockchain_parser_shadow_reliability_certification_service import (
    resolve_shadow_reliability_certification,
)

PAPER_PROJECTION_READINESS_POLICY_VERSION = "canonical-parser-paper-projection-readiness/1"
PAPER_PROJECTION_READINESS_PREFIX = "ASSESS_PAPER_PROJECTION_READINESS"
_MAX_ACTOR_LENGTH = 80
_MAX_NOTE_LENGTH = 500


class CanonicalParserPaperProjectionReadinessError(ValueError):
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
    return sanitize_error_message(value or "LOCAL_PAPER_READINESS", max_length=_MAX_ACTOR_LENGTH) or "LOCAL_PAPER_READINESS"


def _note(value: str | None) -> str | None:
    if not str(value or "").strip():
        return None
    return sanitize_error_message(value, max_length=_MAX_NOTE_LENGTH)


def _policy_snapshot(settings_object: Any) -> dict[str, Any]:
    return {
        "policy_version": PAPER_PROJECTION_READINESS_POLICY_VERSION,
        "lookback_minutes": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_PROJECTION_READINESS_LOOKBACK_MINUTES", 1440)),
        "maximum_source_runs": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_PROJECTION_READINESS_MAX_SOURCE_RUNS", 20)),
        "minimum_projection_runs": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_PROJECTION_READINESS_MIN_RUNS", 3)),
        "minimum_projection_results": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_PROJECTION_READINESS_MIN_RESULTS", 3)),
        "minimum_projectable_rate": float(getattr(settings_object, "CANONICAL_PARSER_PAPER_PROJECTION_READINESS_MIN_PROJECTABLE_RATE", 100.0)),
        "maximum_review_results": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_PROJECTION_READINESS_MAX_REVIEW_RESULTS", 0)),
        "maximum_rejected_results": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_PROJECTION_READINESS_MAX_REJECTED_RESULTS", 0)),
        "minimum_observation_minutes": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_PROJECTION_READINESS_MIN_OBSERVATION_MINUTES", 5)),
        "validity_minutes": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_PROJECTION_READINESS_VALIDITY_MINUTES", 30)),
        "manual_assessment_only": True,
        "requires_active_shadow_reliability_certification": True,
        "requires_projection_runs": True,
        "writes_readiness_tables_only": True,
        "paper_account_reads": False,
        "paper_account_writes": False,
        "paper_order_writes": False,
        "paper_position_writes": False,
        "trade_writes": False,
        "external_requests_allowed": False,
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
    }


def _rate(projectable: int, total: int) -> Decimal:
    if total <= 0:
        return Decimal("0.0000")
    return (Decimal(projectable) * Decimal("100") / Decimal(total)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _run_payload(db: Session, run: CanonicalParserPaperProjectionRun) -> tuple[dict[str, Any], list[str]]:
    results = list(
        db.scalars(
            select(CanonicalParserPaperProjectionResult)
            .where(CanonicalParserPaperProjectionResult.projection_run_db_id == run.id)
            .order_by(CanonicalParserPaperProjectionResult.sequence.asc())
        )
    )
    projectable = sum(item.status == "PROJECTABLE" for item in results)
    review = sum(item.status == "REVIEW" for item in results)
    rejected = sum(item.status == "REJECTED" for item in results)
    reasons: set[str] = set()
    if len(results) != int(run.source_result_count):
        reasons.add("PAPER_PROJECTION_READINESS_RESULT_COUNT_MISMATCH")
    if projectable != int(run.projectable_count):
        reasons.add("PAPER_PROJECTION_READINESS_PROJECTABLE_COUNT_MISMATCH")
    if review != int(run.review_count):
        reasons.add("PAPER_PROJECTION_READINESS_REVIEW_COUNT_MISMATCH")
    if rejected != int(run.rejected_count):
        reasons.add("PAPER_PROJECTION_READINESS_REJECTED_COUNT_MISMATCH")
    manifest = [
        {
            "result_id": item.result_id,
            "sequence": item.sequence,
            "status": item.status,
            "projection_hash": item.projection_hash,
            "artifact_hash": item.artifact_hash,
        }
        for item in results
    ]
    payload = {
        "projection_run_db_id": run.id,
        "projection_id": run.projection_id,
        "projection_key": run.projection_key,
        "certification_id": run.certification_id,
        "certification_event_hash": run.certification_event_hash,
        "status": run.status,
        "source_result_count": int(run.source_result_count),
        "projectable_count": int(run.projectable_count),
        "review_count": int(run.review_count),
        "rejected_count": int(run.rejected_count),
        "policy_hash": run.policy_hash,
        "source_evidence_hash": run.source_evidence_hash,
        "result_manifest": manifest,
        "started_at": _aware(run.started_at).isoformat(),
        "completed_at": _aware(run.completed_at).isoformat(),
    }
    payload["run_evidence_hash"] = calculate_payload_hash(payload)
    return payload, sorted(reasons)


def _collect_evidence(
    db: Session,
    *,
    certification_id: str | None,
    certification_event_hash: str | None,
    settings_object: Any,
    evaluated_at: datetime,
) -> tuple[list[dict[str, Any]], list[str]]:
    policy = _policy_snapshot(settings_object)
    if not certification_id or not certification_event_hash:
        return [], []
    cutoff = evaluated_at - timedelta(minutes=policy["lookback_minutes"])
    runs = list(
        db.scalars(
            select(CanonicalParserPaperProjectionRun)
            .where(
                CanonicalParserPaperProjectionRun.certification_id == certification_id,
                CanonicalParserPaperProjectionRun.certification_event_hash == certification_event_hash,
                CanonicalParserPaperProjectionRun.completed_at >= cutoff,
            )
            .order_by(CanonicalParserPaperProjectionRun.completed_at.desc())
            .limit(policy["maximum_source_runs"])
        )
    )
    evidence: list[dict[str, Any]] = []
    reasons: set[str] = set()
    for run in reversed(runs):
        payload, run_reasons = _run_payload(db, run)
        evidence.append(payload)
        reasons.update(run_reasons)
    return evidence, sorted(reasons)


def preview_paper_projection_readiness(
    db: Session,
    *,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _policy_snapshot(settings_object)
    policy_hash = calculate_payload_hash(policy)
    certification = resolve_shadow_reliability_certification(db, settings_object=settings_object, evaluated_at=now)
    blockers: set[str] = set()
    if certification.get("resolved_status") != "CERTIFIED":
        blockers.add("PAPER_PROJECTION_READINESS_RELIABILITY_NOT_CERTIFIED")
    certification_id = certification.get("certification_id")
    certification_model = None
    if certification_id:
        certification_model = db.scalar(
            select(CanonicalParserShadowReliabilityCertification).where(
                CanonicalParserShadowReliabilityCertification.certification_id == certification_id
            )
        )
    if certification_model is None:
        blockers.add("PAPER_PROJECTION_READINESS_CERTIFICATION_MISSING")
    certification_event_hash = certification.get("latest_event_hash")
    evidence, evidence_reasons = _collect_evidence(
        db,
        certification_id=certification_id,
        certification_event_hash=certification_event_hash,
        settings_object=settings_object,
        evaluated_at=now,
    )
    blockers.update(evidence_reasons)
    run_count = len(evidence)
    result_count = sum(item["source_result_count"] for item in evidence)
    projectable_count = sum(item["projectable_count"] for item in evidence)
    review_count = sum(item["review_count"] for item in evidence)
    rejected_count = sum(item["rejected_count"] for item in evidence)
    projectable_rate = _rate(projectable_count, result_count)
    observation_started_at = min((_aware(datetime.fromisoformat(item["started_at"])) for item in evidence), default=None)
    observation_completed_at = max((_aware(datetime.fromisoformat(item["completed_at"])) for item in evidence), default=None)
    observation_minutes = 0.0
    if observation_started_at and observation_completed_at:
        observation_minutes = max(0.0, (observation_completed_at - observation_started_at).total_seconds() / 60.0)
    reasons: set[str] = set(blockers)
    insufficient = False
    if run_count < policy["minimum_projection_runs"]:
        reasons.add("PAPER_PROJECTION_READINESS_RUNS_INSUFFICIENT")
        insufficient = True
    if result_count < policy["minimum_projection_results"]:
        reasons.add("PAPER_PROJECTION_READINESS_RESULTS_INSUFFICIENT")
        insufficient = True
    if observation_minutes < policy["minimum_observation_minutes"]:
        reasons.add("PAPER_PROJECTION_READINESS_OBSERVATION_INSUFFICIENT")
        insufficient = True
    if any(item["status"] in {"BLOCKED", "INSUFFICIENT_DATA"} for item in evidence):
        reasons.add("PAPER_PROJECTION_READINESS_SOURCE_RUN_BLOCKED")
        blockers.add("PAPER_PROJECTION_READINESS_SOURCE_RUN_BLOCKED")
    if rejected_count > policy["maximum_rejected_results"]:
        reasons.add("PAPER_PROJECTION_READINESS_REJECTED_RESULTS_EXCEEDED")
        blockers.add("PAPER_PROJECTION_READINESS_REJECTED_RESULTS_EXCEEDED")
    review_needed = False
    if review_count > policy["maximum_review_results"]:
        reasons.add("PAPER_PROJECTION_READINESS_REVIEW_RESULTS_EXCEEDED")
        review_needed = True
    if float(projectable_rate) < policy["minimum_projectable_rate"]:
        reasons.add("PAPER_PROJECTION_READINESS_PROJECTABLE_RATE_LOW")
        review_needed = True
    if any(item["status"] == "PARTIAL" for item in evidence):
        reasons.add("PAPER_PROJECTION_READINESS_PARTIAL_SOURCE_RUN")
        review_needed = True
    evidence_snapshot = {
        "certification_id": certification_id,
        "certification_event_hash": certification_event_hash,
        "projection_runs": evidence,
    }
    evidence_hash = calculate_payload_hash(evidence_snapshot)
    if blockers:
        status = "BLOCKED"
    elif insufficient:
        status = "INSUFFICIENT_DATA"
    elif review_needed:
        status = "REVIEW"
    else:
        status = "READY"
    metrics = {
        "run_count": run_count,
        "result_count": result_count,
        "projectable_count": projectable_count,
        "review_count": review_count,
        "rejected_count": rejected_count,
        "projectable_rate": float(projectable_rate),
        "observation_minutes": observation_minutes,
    }
    manifest = {
        "certification_id": certification_id,
        "certification_event_hash": certification_event_hash,
        "policy_hash": policy_hash,
        "evidence_hash": evidence_hash,
        "status": status,
    }
    assessment_key = calculate_payload_hash(manifest)
    return {
        "eligible": status in {"READY", "REVIEW", "INSUFFICIENT_DATA"} and not blockers,
        "status": status,
        "reason_codes": sorted(reasons),
        "assessment_key": assessment_key,
        "confirmation": f"{PAPER_PROJECTION_READINESS_PREFIX}:{assessment_key[:16]}",
        "certification_db_id": certification_model.id if certification_model else None,
        "certification": sanitize_technical_metadata(certification),
        "policy": policy,
        "policy_hash": policy_hash,
        "evidence_hash": evidence_hash,
        "evidence_snapshot": sanitize_technical_metadata(evidence_snapshot),
        "metrics": metrics,
        "observation_started_at": observation_started_at,
        "observation_completed_at": observation_completed_at,
        "paper_admission_certified": False,
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
    }


def _serialize_assessment(db: Session, assessment: CanonicalParserPaperProjectionReadinessAssessment) -> dict[str, Any]:
    evidence = list(
        db.scalars(
            select(CanonicalParserPaperProjectionReadinessEvidenceRun)
            .where(CanonicalParserPaperProjectionReadinessEvidenceRun.assessment_db_id == assessment.id)
            .order_by(CanonicalParserPaperProjectionReadinessEvidenceRun.sequence.asc())
        )
    )
    return {
        "assessment_id": assessment.assessment_id,
        "assessment_key": assessment.assessment_key,
        "status": assessment.status,
        "certification_id": assessment.certification_id,
        "certification_event_hash": assessment.certification_event_hash,
        "run_count": assessment.run_count,
        "result_count": assessment.result_count,
        "projectable_count": assessment.projectable_count,
        "review_count": assessment.review_count,
        "rejected_count": assessment.rejected_count,
        "projectable_rate": float(assessment.projectable_rate),
        "observation_started_at": assessment.observation_started_at,
        "observation_completed_at": assessment.observation_completed_at,
        "reason_codes": assessment.reason_codes,
        "policy_version": assessment.policy_version,
        "policy_hash": assessment.policy_hash,
        "policy_snapshot": assessment.policy_snapshot,
        "evidence_hash": assessment.evidence_hash,
        "evidence_snapshot": assessment.evidence_snapshot,
        "metrics_snapshot": assessment.metrics_snapshot,
        "actor_label": assessment.actor_label,
        "note": assessment.note,
        "evaluated_at": assessment.evaluated_at,
        "valid_until": assessment.valid_until,
        "evidence_runs": [
            {
                "sequence": item.sequence,
                "projection_id": item.projection_id,
                "status": item.status,
                "source_result_count": item.source_result_count,
                "projectable_count": item.projectable_count,
                "review_count": item.review_count,
                "rejected_count": item.rejected_count,
                "projection_key": item.projection_key,
                "policy_hash": item.policy_hash,
                "source_evidence_hash": item.source_evidence_hash,
                "run_evidence_hash": item.run_evidence_hash,
                "completed_at": item.completed_at,
            }
            for item in evidence
        ],
        "paper_admission_certified": False,
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
    }


def execute_paper_projection_readiness_assessment(
    db: Session,
    *,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_PAPER_PROJECTION_READINESS_ENABLED", False)):
        raise CanonicalParserPaperProjectionReadinessError(
            "PAPER projection readiness disabilitata.",
            code="CANONICAL_PARSER_PAPER_PROJECTION_READINESS_DISABLED",
            status_code=409,
        )
    now = _aware(evaluated_at)
    preview = preview_paper_projection_readiness(db, settings_object=settings_object, evaluated_at=now)
    existing = db.scalar(
        select(CanonicalParserPaperProjectionReadinessAssessment).where(
            CanonicalParserPaperProjectionReadinessAssessment.assessment_key == preview["assessment_key"]
        )
    )
    if existing is not None:
        return _serialize_assessment(db, existing)
    if confirmation != preview["confirmation"]:
        raise CanonicalParserPaperProjectionReadinessError(
            "Conferma PAPER projection readiness non valida.",
            code="PAPER_PROJECTION_READINESS_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if preview["certification_db_id"] is None:
        raise CanonicalParserPaperProjectionReadinessError(
            "Certificazione reliability non disponibile.",
            code="PAPER_PROJECTION_READINESS_BLOCKED",
            status_code=409,
        )
    assessment = CanonicalParserPaperProjectionReadinessAssessment(
        assessment_id=str(uuid4()),
        assessment_key=preview["assessment_key"],
        certification_db_id=preview["certification_db_id"],
        certification_id=preview["certification"].get("certification_id"),
        certification_event_hash=preview["certification"].get("latest_event_hash"),
        status=preview["status"],
        run_count=preview["metrics"]["run_count"],
        result_count=preview["metrics"]["result_count"],
        projectable_count=preview["metrics"]["projectable_count"],
        review_count=preview["metrics"]["review_count"],
        rejected_count=preview["metrics"]["rejected_count"],
        projectable_rate=Decimal(str(preview["metrics"]["projectable_rate"])),
        observation_started_at=preview["observation_started_at"],
        observation_completed_at=preview["observation_completed_at"],
        policy_version=PAPER_PROJECTION_READINESS_POLICY_VERSION,
        policy_hash=preview["policy_hash"],
        policy_snapshot=preview["policy"],
        evidence_hash=preview["evidence_hash"],
        evidence_snapshot=preview["evidence_snapshot"],
        metrics_snapshot=preview["metrics"],
        reason_codes=preview["reason_codes"],
        actor_label=_actor(actor_label),
        note=_note(note),
        evaluated_at=now,
        valid_until=now + timedelta(minutes=preview["policy"]["validity_minutes"]),
    )
    db.add(assessment)
    try:
        db.flush()
        for sequence, item in enumerate(preview["evidence_snapshot"]["projection_runs"], start=1):
            db.add(
                CanonicalParserPaperProjectionReadinessEvidenceRun(
                    assessment_db_id=assessment.id,
                    sequence=sequence,
                    projection_run_db_id=item["projection_run_db_id"],
                    projection_id=item["projection_id"],
                    status=item["status"],
                    source_result_count=item["source_result_count"],
                    projectable_count=item["projectable_count"],
                    review_count=item["review_count"],
                    rejected_count=item["rejected_count"],
                    projection_key=item["projection_key"],
                    policy_hash=item["policy_hash"],
                    source_evidence_hash=item["source_evidence_hash"],
                    run_evidence_hash=item["run_evidence_hash"],
                    completed_at=_aware(datetime.fromisoformat(item["completed_at"])),
                )
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(
            select(CanonicalParserPaperProjectionReadinessAssessment).where(
                CanonicalParserPaperProjectionReadinessAssessment.assessment_key == preview["assessment_key"]
            )
        )
        if existing is not None:
            return _serialize_assessment(db, existing)
        raise CanonicalParserPaperProjectionReadinessError(
            "Conflitto durante la PAPER projection readiness.",
            code="PAPER_PROJECTION_READINESS_CONFLICT",
            status_code=409,
        ) from exc
    db.refresh(assessment)
    return _serialize_assessment(db, assessment)


def get_paper_projection_readiness_assessment(db: Session, assessment_id: str) -> dict[str, Any]:
    assessment = db.scalar(
        select(CanonicalParserPaperProjectionReadinessAssessment).where(
            CanonicalParserPaperProjectionReadinessAssessment.assessment_id == assessment_id
        )
    )
    if assessment is None:
        raise CanonicalParserPaperProjectionReadinessError(
            "PAPER projection readiness assessment non trovata.",
            code="PAPER_PROJECTION_READINESS_NOT_FOUND",
            status_code=404,
        )
    return _serialize_assessment(db, assessment)


def resolve_paper_projection_readiness(
    db: Session,
    *,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    assessment = db.scalar(
        select(CanonicalParserPaperProjectionReadinessAssessment)
        .order_by(CanonicalParserPaperProjectionReadinessAssessment.evaluated_at.desc())
        .limit(1)
    )
    if assessment is None:
        return {
            "resolved_status": "UNASSESSED",
            "assessment_id": None,
            "paper_admission_certified": False,
            "paper_execution_authorized": False,
            "live_execution_authorized": False,
        }
    payload = _serialize_assessment(db, assessment)
    if assessment.status != "READY":
        payload["resolved_status"] = assessment.status
        return payload
    if _aware(assessment.valid_until) <= now:
        payload["resolved_status"] = "EXPIRED"
        return payload
    preview = preview_paper_projection_readiness(db, settings_object=settings_object, evaluated_at=now)
    if (
        preview["evidence_hash"] != assessment.evidence_hash
        or preview["policy_hash"] != assessment.policy_hash
        or preview["certification"].get("latest_event_hash") != assessment.certification_event_hash
    ):
        payload["resolved_status"] = "DRIFTED"
        return payload
    payload["resolved_status"] = "READY"
    return payload


def get_paper_projection_readiness_status(
    db: Session,
    *,
    settings_object: Any = settings,
) -> dict[str, Any]:
    return {
        "enabled": bool(getattr(settings_object, "CANONICAL_PARSER_PAPER_PROJECTION_READINESS_ENABLED", False)),
        "policy": _policy_snapshot(settings_object),
        "assessment_count": int(db.scalar(select(func.count(CanonicalParserPaperProjectionReadinessAssessment.id))) or 0),
        "evidence_run_count": int(db.scalar(select(func.count(CanonicalParserPaperProjectionReadinessEvidenceRun.id))) or 0),
        "operational_guards": {
            "manual_assessment_only": True,
            "writes_readiness_tables_only": True,
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
