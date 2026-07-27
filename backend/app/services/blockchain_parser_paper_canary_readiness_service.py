from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserPaperAdmissionCanaryResult,
    CanonicalParserPaperAdmissionCanaryRun,
    CanonicalParserPaperCanaryReadinessAssessment,
    CanonicalParserPaperCanaryReadinessEvidenceRun,
    CanonicalParserPaperProjectionResult,
    CanonicalParserPaperRuntimeBinding,
)
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    sanitize_error_message,
    sanitize_technical_metadata,
)
from backend.app.services.blockchain_parser_paper_runtime_binding_service import (
    resolve_paper_runtime_binding,
)

PAPER_CANARY_READINESS_POLICY_VERSION = "canonical-parser-paper-canary-readiness/1"
PAPER_CANARY_READINESS_PREFIX = "ASSESS_PAPER_CANARY_READINESS"
_MAX_ACTOR_LENGTH = 80
_MAX_NOTE_LENGTH = 500


class CanonicalParserPaperCanaryReadinessError(ValueError):
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
    return sanitize_error_message(value or "LOCAL_PAPER_CANARY_READINESS", max_length=_MAX_ACTOR_LENGTH) or "LOCAL_PAPER_CANARY_READINESS"


def _note(value: str | None) -> str | None:
    if not str(value or "").strip():
        return None
    return sanitize_error_message(value, max_length=_MAX_NOTE_LENGTH)


def _policy_snapshot(settings_object: Any) -> dict[str, Any]:
    return {
        "policy_version": PAPER_CANARY_READINESS_POLICY_VERSION,
        "lookback_minutes": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_CANARY_READINESS_LOOKBACK_MINUTES", 1440)),
        "maximum_source_runs": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_CANARY_READINESS_MAX_SOURCE_RUNS", 20)),
        "minimum_runs": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_CANARY_READINESS_MIN_RUNS", 3)),
        "minimum_results": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_CANARY_READINESS_MIN_RESULTS", 3)),
        "minimum_admissible_results": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_CANARY_READINESS_MIN_ADMISSIBLE_RESULTS", 3)),
        "maximum_review_runs": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_CANARY_READINESS_MAX_REVIEW_RUNS", 0)),
        "maximum_blocked_runs": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_CANARY_READINESS_MAX_BLOCKED_RUNS", 0)),
        "maximum_insufficient_runs": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_CANARY_READINESS_MAX_INSUFFICIENT_RUNS", 0)),
        "minimum_observation_minutes": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_CANARY_READINESS_MIN_OBSERVATION_MINUTES", 5)),
        "maximum_source_age_minutes": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_CANARY_READINESS_MAX_SOURCE_AGE_MINUTES", 30)),
        "validity_minutes": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_CANARY_READINESS_VALIDITY_MINUTES", 30)),
        "manual_assessment_only": True,
        "requires_current_read_only_paper_binding": True,
        "requires_multiple_m28_runs": True,
        "source_run_audit_required": True,
        "freshness_required": True,
        "fail_closed_on_drift": True,
        "writes_readiness_tables_only": True,
        "paper_account_reads": False,
        "paper_account_writes": False,
        "paper_order_reads": False,
        "paper_order_writes": False,
        "paper_position_reads": False,
        "paper_position_writes": False,
        "trade_writes": False,
        "external_requests_allowed": False,
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
    }


def _expected_run_status(run: CanonicalParserPaperAdmissionCanaryRun) -> str:
    if int(run.blocked_count) > 0:
        return "BLOCKED"
    if int(run.review_count) > 0:
        return "REVIEW"
    minimum = int((run.policy_snapshot or {}).get("min_admissible_results", 1))
    if int(run.admissible_count) < minimum:
        return "INSUFFICIENT_DATA"
    return "PASSED"


def _run_payload(db: Session, run: CanonicalParserPaperAdmissionCanaryRun, *, evaluated_at: datetime) -> tuple[dict[str, Any], list[str]]:
    results = list(
        db.scalars(
            select(CanonicalParserPaperAdmissionCanaryResult)
            .where(CanonicalParserPaperAdmissionCanaryResult.canary_run_db_id == run.id)
            .order_by(CanonicalParserPaperAdmissionCanaryResult.sequence.asc())
        )
    )
    source_ids = [item.source_projection_result_db_id for item in results]
    source_map: dict[int, CanonicalParserPaperProjectionResult] = {}
    if source_ids:
        source_map = {
            item.id: item
            for item in db.scalars(
                select(CanonicalParserPaperProjectionResult).where(
                    CanonicalParserPaperProjectionResult.id.in_(source_ids)
                )
            )
        }

    reasons: set[str] = set()
    admissible = sum(item.status == "ADMISSIBLE" for item in results)
    review = sum(item.status == "REVIEW" for item in results)
    blocked = sum(item.status == "BLOCKED" for item in results)
    if len(results) != int(run.source_result_count):
        reasons.add("PAPER_CANARY_READINESS_RESULT_COUNT_MISMATCH")
    if admissible != int(run.admissible_count):
        reasons.add("PAPER_CANARY_READINESS_ADMISSIBLE_COUNT_MISMATCH")
    if review != int(run.review_count):
        reasons.add("PAPER_CANARY_READINESS_REVIEW_COUNT_MISMATCH")
    if blocked != int(run.blocked_count):
        reasons.add("PAPER_CANARY_READINESS_BLOCKED_COUNT_MISMATCH")
    if run.status != _expected_run_status(run):
        reasons.add("PAPER_CANARY_READINESS_RUN_STATUS_MISMATCH")

    result_manifest: list[dict[str, Any]] = []
    for expected_sequence, item in enumerate(results, start=1):
        if item.sequence != expected_sequence:
            reasons.add("PAPER_CANARY_READINESS_RESULT_SEQUENCE_INVALID")
        if calculate_payload_hash(item.canary_payload) != item.canary_hash:
            reasons.add("PAPER_CANARY_READINESS_RESULT_HASH_INVALID")
        source = source_map.get(item.source_projection_result_db_id)
        if source is None:
            reasons.add("PAPER_CANARY_READINESS_SOURCE_PROJECTION_MISSING")
        elif source.projection_hash != item.source_projection_hash:
            reasons.add("PAPER_CANARY_READINESS_SOURCE_PROJECTION_DRIFTED")
        result_manifest.append(
            {
                "result_id": item.result_id,
                "sequence": item.sequence,
                "status": item.status,
                "source_projection_result_id": item.source_projection_result_id,
                "source_projection_hash": item.source_projection_hash,
                "canary_hash": item.canary_hash,
            }
        )

    canary_manifest = {
        "binding_id": run.binding_id,
        "binding_event_hash": run.binding_event_hash,
        "certification_id": run.certification_id,
        "assessment_id": run.assessment_id,
        "paper_account_id": run.paper_account_id,
        "source_evidence_hash": run.source_evidence_hash,
        "account_state_hash": run.account_state_hash,
        "policy_hash": run.policy_hash,
    }
    if calculate_payload_hash(canary_manifest) != run.canary_key:
        reasons.add("PAPER_CANARY_READINESS_CANARY_KEY_INVALID")

    payload = {
        "canary_run_db_id": run.id,
        "canary_id": run.canary_id,
        "canary_key": run.canary_key,
        "resource_link": f"/integrity/parser-paper-admission-canary/runs/{run.canary_id}",
        "binding_id": run.binding_id,
        "binding_event_hash": run.binding_event_hash,
        "certification_id": run.certification_id,
        "paper_account_id": run.paper_account_id,
        "status": run.status,
        "source_result_count": int(run.source_result_count),
        "admissible_count": int(run.admissible_count),
        "review_count": int(run.review_count),
        "blocked_count": int(run.blocked_count),
        "source_evidence_hash": run.source_evidence_hash,
        "account_state_hash": run.account_state_hash,
        "policy_hash": run.policy_hash,
        "result_manifest": result_manifest,
        "completed_at": _aware(run.completed_at).isoformat(),
        "valid_until": _aware(run.valid_until).isoformat(),
        "source_valid_at_evaluation": _aware(run.valid_until) > evaluated_at,
    }
    payload["run_evidence_hash"] = calculate_payload_hash(payload)
    return payload, sorted(reasons)


def _collect_evidence(
    db: Session,
    *,
    binding: CanonicalParserPaperRuntimeBinding | None,
    policy: dict[str, Any],
    evaluated_at: datetime,
) -> tuple[list[dict[str, Any]], list[str]]:
    if binding is None:
        return [], []
    cutoff = evaluated_at - timedelta(minutes=int(policy["lookback_minutes"]))
    runs = list(
        db.scalars(
            select(CanonicalParserPaperAdmissionCanaryRun)
            .where(
                CanonicalParserPaperAdmissionCanaryRun.binding_db_id == binding.id,
                CanonicalParserPaperAdmissionCanaryRun.binding_id == binding.binding_id,
                CanonicalParserPaperAdmissionCanaryRun.binding_event_hash == binding.latest_event_hash,
                CanonicalParserPaperAdmissionCanaryRun.certification_id == binding.certification_id,
                CanonicalParserPaperAdmissionCanaryRun.paper_account_id == binding.paper_account_id,
                CanonicalParserPaperAdmissionCanaryRun.completed_at >= cutoff,
            )
            .order_by(CanonicalParserPaperAdmissionCanaryRun.completed_at.desc(), CanonicalParserPaperAdmissionCanaryRun.id.desc())
            .limit(int(policy["maximum_source_runs"]))
        )
    )
    evidence: list[dict[str, Any]] = []
    reasons: set[str] = set()
    for run in reversed(runs):
        payload, run_reasons = _run_payload(db, run, evaluated_at=evaluated_at)
        evidence.append(payload)
        reasons.update(run_reasons)
    return evidence, sorted(reasons)


def preview_paper_canary_readiness(
    db: Session,
    *,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _policy_snapshot(settings_object)
    policy_hash = calculate_payload_hash(policy)
    binding_resolution = resolve_paper_runtime_binding(db, settings_object=settings_object, evaluated_at=now)
    blockers: set[str] = set()
    review_reasons: set[str] = set()
    insufficient_reasons: set[str] = set()

    if binding_resolution.get("resolved_status") != "BOUND":
        blockers.add("PAPER_CANARY_READINESS_BINDING_NOT_BOUND")
    binding = None
    binding_id = binding_resolution.get("binding_id")
    if binding_id:
        binding = db.scalar(
            select(CanonicalParserPaperRuntimeBinding).where(
                CanonicalParserPaperRuntimeBinding.binding_id == binding_id
            )
        )
    if binding is None:
        blockers.add("PAPER_CANARY_READINESS_BINDING_MISSING")

    evidence, audit_reasons = _collect_evidence(
        db,
        binding=binding,
        policy=policy,
        evaluated_at=now,
    )
    blockers.update(audit_reasons)

    run_count = len(evidence)
    passed_runs = sum(item["status"] == "PASSED" for item in evidence)
    review_runs = sum(item["status"] == "REVIEW" for item in evidence)
    blocked_runs = sum(item["status"] == "BLOCKED" for item in evidence)
    insufficient_runs = sum(item["status"] == "INSUFFICIENT_DATA" for item in evidence)
    result_count = sum(int(item["source_result_count"]) for item in evidence)
    admissible_count = sum(int(item["admissible_count"]) for item in evidence)
    review_result_count = sum(int(item["review_count"]) for item in evidence)
    blocked_result_count = sum(int(item["blocked_count"]) for item in evidence)

    observation_started_at = min(
        (_aware(datetime.fromisoformat(item["completed_at"])) for item in evidence), default=None
    )
    observation_completed_at = max(
        (_aware(datetime.fromisoformat(item["completed_at"])) for item in evidence), default=None
    )
    observation_minutes = 0.0
    if observation_started_at and observation_completed_at:
        observation_minutes = max(0.0, (observation_completed_at - observation_started_at).total_seconds() / 60.0)
    latest_source_valid_until = max(
        (_aware(datetime.fromisoformat(item["valid_until"])) for item in evidence), default=None
    )
    freshness_cutoff_at = now - timedelta(minutes=int(policy["maximum_source_age_minutes"]))
    latest_source_at = observation_completed_at

    if run_count < int(policy["minimum_runs"]):
        insufficient_reasons.add("PAPER_CANARY_READINESS_MIN_RUNS_NOT_MET")
    if result_count < int(policy["minimum_results"]):
        insufficient_reasons.add("PAPER_CANARY_READINESS_MIN_RESULTS_NOT_MET")
    if admissible_count < int(policy["minimum_admissible_results"]):
        insufficient_reasons.add("PAPER_CANARY_READINESS_MIN_ADMISSIBLE_NOT_MET")
    if observation_minutes < float(policy["minimum_observation_minutes"]):
        insufficient_reasons.add("PAPER_CANARY_READINESS_OBSERVATION_WINDOW_TOO_SHORT")
    if latest_source_at is None or latest_source_at < freshness_cutoff_at:
        blockers.add("PAPER_CANARY_READINESS_EVIDENCE_STALE")
    if latest_source_valid_until is None or latest_source_valid_until <= now:
        blockers.add("PAPER_CANARY_READINESS_SOURCE_CANARY_EXPIRED")
    if blocked_runs > int(policy["maximum_blocked_runs"]):
        blockers.add("PAPER_CANARY_READINESS_BLOCKED_RUN_LIMIT_EXCEEDED")
    elif blocked_runs:
        review_reasons.add("PAPER_CANARY_READINESS_BLOCKED_RUNS_PRESENT")
    if review_runs > int(policy["maximum_review_runs"]):
        review_reasons.add("PAPER_CANARY_READINESS_REVIEW_RUN_LIMIT_EXCEEDED")
    if insufficient_runs > int(policy["maximum_insufficient_runs"]):
        insufficient_reasons.add("PAPER_CANARY_READINESS_INSUFFICIENT_RUN_LIMIT_EXCEEDED")

    account_hashes = sorted({item["account_state_hash"] for item in evidence})
    canary_policy_hashes = sorted({item["policy_hash"] for item in evidence})
    if len(account_hashes) > 1:
        review_reasons.add("PAPER_CANARY_READINESS_ACCOUNT_STATE_DRIFT_OBSERVED")
    if len(canary_policy_hashes) > 1:
        review_reasons.add("PAPER_CANARY_READINESS_CANARY_POLICY_DRIFT_OBSERVED")

    if blockers:
        status = "BLOCKED"
    elif insufficient_reasons:
        status = "INSUFFICIENT_DATA"
    elif review_reasons:
        status = "REVIEW"
    else:
        status = "READY"

    evidence_snapshot = {
        "binding_id": binding.binding_id if binding else None,
        "binding_event_hash": binding.latest_event_hash if binding else None,
        "certification_id": binding.certification_id if binding else None,
        "paper_account_id": binding.paper_account_id if binding else None,
        "canary_runs": evidence,
    }
    evidence_hash = calculate_payload_hash(evidence_snapshot)
    manifest = {
        "binding_id": evidence_snapshot["binding_id"],
        "binding_event_hash": evidence_snapshot["binding_event_hash"],
        "certification_id": evidence_snapshot["certification_id"],
        "paper_account_id": evidence_snapshot["paper_account_id"],
        "evidence_hash": evidence_hash,
        "policy_hash": policy_hash,
    }
    assessment_key = calculate_payload_hash(manifest)
    metrics = {
        "run_count": run_count,
        "passed_run_count": passed_runs,
        "review_run_count": review_runs,
        "blocked_run_count": blocked_runs,
        "insufficient_run_count": insufficient_runs,
        "result_count": result_count,
        "admissible_count": admissible_count,
        "review_result_count": review_result_count,
        "blocked_result_count": blocked_result_count,
        "observation_minutes": round(observation_minutes, 6),
        "account_state_hash_count": len(account_hashes),
        "canary_policy_hash_count": len(canary_policy_hashes),
    }
    reason_codes = sorted(blockers | review_reasons | insufficient_reasons)
    return {
        "eligible": binding is not None,
        "status": status,
        "reason_codes": reason_codes,
        "assessment_key": assessment_key,
        "confirmation": f"{PAPER_CANARY_READINESS_PREFIX}:{assessment_key[:16]}",
        "binding_db_id": binding.id if binding else None,
        "binding": sanitize_technical_metadata(binding_resolution),
        "certification_id": binding.certification_id if binding else None,
        "paper_account_id": binding.paper_account_id if binding else None,
        "policy": policy,
        "policy_hash": policy_hash,
        "evidence_hash": evidence_hash,
        "evidence_snapshot": sanitize_technical_metadata(evidence_snapshot),
        "metrics": metrics,
        "observation_started_at": observation_started_at,
        "observation_completed_at": observation_completed_at,
        "latest_source_valid_until": latest_source_valid_until,
        "freshness_cutoff_at": freshness_cutoff_at,
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
    }


def _serialize_assessment(db: Session, assessment: CanonicalParserPaperCanaryReadinessAssessment) -> dict[str, Any]:
    evidence = list(
        db.scalars(
            select(CanonicalParserPaperCanaryReadinessEvidenceRun)
            .where(CanonicalParserPaperCanaryReadinessEvidenceRun.assessment_db_id == assessment.id)
            .order_by(CanonicalParserPaperCanaryReadinessEvidenceRun.sequence.asc())
        )
    )
    return {
        "assessment_id": assessment.assessment_id,
        "assessment_key": assessment.assessment_key,
        "binding_id": assessment.binding_id,
        "binding_event_hash": assessment.binding_event_hash,
        "certification_id": assessment.certification_id,
        "paper_account_id": assessment.paper_account_id,
        "status": assessment.status,
        "run_count": assessment.run_count,
        "passed_run_count": assessment.passed_run_count,
        "review_run_count": assessment.review_run_count,
        "blocked_run_count": assessment.blocked_run_count,
        "insufficient_run_count": assessment.insufficient_run_count,
        "result_count": assessment.result_count,
        "admissible_count": assessment.admissible_count,
        "review_result_count": assessment.review_result_count,
        "blocked_result_count": assessment.blocked_result_count,
        "observation_started_at": assessment.observation_started_at,
        "observation_completed_at": assessment.observation_completed_at,
        "latest_source_valid_until": assessment.latest_source_valid_until,
        "freshness_cutoff_at": assessment.freshness_cutoff_at,
        "policy_version": assessment.policy_version,
        "policy_hash": assessment.policy_hash,
        "policy_snapshot": assessment.policy_snapshot,
        "evidence_hash": assessment.evidence_hash,
        "evidence_snapshot": assessment.evidence_snapshot,
        "metrics_snapshot": assessment.metrics_snapshot,
        "reason_codes": assessment.reason_codes,
        "actor_label": assessment.actor_label,
        "note": assessment.note,
        "evaluated_at": assessment.evaluated_at,
        "valid_until": assessment.valid_until,
        "evidence_runs": [
            {
                "sequence": item.sequence,
                "canary_id": item.canary_id,
                "resource_link": f"/integrity/parser-paper-admission-canary/runs/{item.canary_id}",
                "status": item.status,
                "source_result_count": item.source_result_count,
                "admissible_count": item.admissible_count,
                "review_count": item.review_count,
                "blocked_count": item.blocked_count,
                "canary_key": item.canary_key,
                "binding_event_hash": item.binding_event_hash,
                "source_evidence_hash": item.source_evidence_hash,
                "account_state_hash": item.account_state_hash,
                "policy_hash": item.policy_hash,
                "run_evidence_hash": item.run_evidence_hash,
                "completed_at": item.completed_at,
                "valid_until": item.valid_until,
            }
            for item in evidence
        ],
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
    }


def execute_paper_canary_readiness_assessment(
    db: Session,
    *,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_PAPER_CANARY_READINESS_ENABLED", False)):
        raise CanonicalParserPaperCanaryReadinessError(
            "PAPER canary readiness evidence gate disabilitato.",
            code="CANONICAL_PARSER_PAPER_CANARY_READINESS_DISABLED",
            status_code=409,
        )
    now = _aware(evaluated_at)
    preview = preview_paper_canary_readiness(db, settings_object=settings_object, evaluated_at=now)
    existing = db.scalar(
        select(CanonicalParserPaperCanaryReadinessAssessment).where(
            CanonicalParserPaperCanaryReadinessAssessment.assessment_key == preview["assessment_key"]
        )
    )
    if existing is not None:
        return _serialize_assessment(db, existing)
    if confirmation != preview["confirmation"]:
        raise CanonicalParserPaperCanaryReadinessError(
            "Conferma PAPER canary readiness non valida.",
            code="PAPER_CANARY_READINESS_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if not preview["eligible"] or preview["binding_db_id"] is None:
        raise CanonicalParserPaperCanaryReadinessError(
            "Binding PAPER non disponibile per la readiness.",
            code="PAPER_CANARY_READINESS_BINDING_REQUIRED",
            status_code=409,
        )

    assessment = CanonicalParserPaperCanaryReadinessAssessment(
        assessment_id=str(uuid4()),
        assessment_key=preview["assessment_key"],
        binding_db_id=preview["binding_db_id"],
        binding_id=preview["binding"]["binding_id"],
        binding_event_hash=preview["binding"]["latest_event_hash"],
        certification_id=preview["certification_id"],
        paper_account_id=preview["paper_account_id"],
        status=preview["status"],
        run_count=preview["metrics"]["run_count"],
        passed_run_count=preview["metrics"]["passed_run_count"],
        review_run_count=preview["metrics"]["review_run_count"],
        blocked_run_count=preview["metrics"]["blocked_run_count"],
        insufficient_run_count=preview["metrics"]["insufficient_run_count"],
        result_count=preview["metrics"]["result_count"],
        admissible_count=preview["metrics"]["admissible_count"],
        review_result_count=preview["metrics"]["review_result_count"],
        blocked_result_count=preview["metrics"]["blocked_result_count"],
        observation_started_at=preview["observation_started_at"],
        observation_completed_at=preview["observation_completed_at"],
        latest_source_valid_until=preview["latest_source_valid_until"],
        freshness_cutoff_at=preview["freshness_cutoff_at"],
        policy_version=PAPER_CANARY_READINESS_POLICY_VERSION,
        policy_hash=preview["policy_hash"],
        policy_snapshot=preview["policy"],
        evidence_hash=preview["evidence_hash"],
        evidence_snapshot=preview["evidence_snapshot"],
        metrics_snapshot=preview["metrics"],
        reason_codes=preview["reason_codes"],
        actor_label=_actor(actor_label),
        note=_note(note),
        evaluated_at=now,
        valid_until=now + timedelta(minutes=int(preview["policy"]["validity_minutes"])),
    )
    db.add(assessment)
    try:
        db.flush()
        for sequence, item in enumerate(preview["evidence_snapshot"]["canary_runs"], start=1):
            db.add(
                CanonicalParserPaperCanaryReadinessEvidenceRun(
                    assessment_db_id=assessment.id,
                    sequence=sequence,
                    canary_run_db_id=item["canary_run_db_id"],
                    canary_id=item["canary_id"],
                    status=item["status"],
                    source_result_count=item["source_result_count"],
                    admissible_count=item["admissible_count"],
                    review_count=item["review_count"],
                    blocked_count=item["blocked_count"],
                    canary_key=item["canary_key"],
                    binding_event_hash=item["binding_event_hash"],
                    source_evidence_hash=item["source_evidence_hash"],
                    account_state_hash=item["account_state_hash"],
                    policy_hash=item["policy_hash"],
                    run_evidence_hash=item["run_evidence_hash"],
                    completed_at=_aware(datetime.fromisoformat(item["completed_at"])),
                    valid_until=_aware(datetime.fromisoformat(item["valid_until"])),
                )
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(
            select(CanonicalParserPaperCanaryReadinessAssessment).where(
                CanonicalParserPaperCanaryReadinessAssessment.assessment_key == preview["assessment_key"]
            )
        )
        if existing is not None:
            return _serialize_assessment(db, existing)
        raise CanonicalParserPaperCanaryReadinessError(
            "Conflitto durante la PAPER canary readiness.",
            code="PAPER_CANARY_READINESS_CONFLICT",
            status_code=409,
        ) from exc
    db.refresh(assessment)
    return _serialize_assessment(db, assessment)


def get_paper_canary_readiness_assessment(db: Session, assessment_id: str) -> dict[str, Any]:
    assessment = db.scalar(
        select(CanonicalParserPaperCanaryReadinessAssessment).where(
            CanonicalParserPaperCanaryReadinessAssessment.assessment_id == assessment_id
        )
    )
    if assessment is None:
        raise CanonicalParserPaperCanaryReadinessError(
            "PAPER canary readiness assessment non trovata.",
            code="PAPER_CANARY_READINESS_NOT_FOUND",
            status_code=404,
        )
    return _serialize_assessment(db, assessment)


def _stored_evidence_audit(db: Session, assessment: CanonicalParserPaperCanaryReadinessAssessment) -> list[str]:
    evidence = list(
        db.scalars(
            select(CanonicalParserPaperCanaryReadinessEvidenceRun)
            .where(CanonicalParserPaperCanaryReadinessEvidenceRun.assessment_db_id == assessment.id)
            .order_by(CanonicalParserPaperCanaryReadinessEvidenceRun.sequence.asc())
        )
    )
    reasons: set[str] = set()
    if len(evidence) != assessment.run_count:
        reasons.add("PAPER_CANARY_READINESS_STORED_EVIDENCE_COUNT_MISMATCH")
    for expected_sequence, item in enumerate(evidence, start=1):
        if item.sequence != expected_sequence:
            reasons.add("PAPER_CANARY_READINESS_STORED_EVIDENCE_SEQUENCE_INVALID")
        source = db.get(CanonicalParserPaperAdmissionCanaryRun, item.canary_run_db_id)
        if source is None:
            reasons.add("PAPER_CANARY_READINESS_STORED_SOURCE_MISSING")
            continue
        payload, run_reasons = _run_payload(db, source, evaluated_at=_aware(assessment.evaluated_at))
        reasons.update(run_reasons)
        if payload["run_evidence_hash"] != item.run_evidence_hash:
            reasons.add("PAPER_CANARY_READINESS_STORED_EVIDENCE_HASH_INVALID")
    return sorted(reasons)


def resolve_paper_canary_readiness(
    db: Session,
    *,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    assessment = db.scalar(
        select(CanonicalParserPaperCanaryReadinessAssessment)
        .order_by(CanonicalParserPaperCanaryReadinessAssessment.evaluated_at.desc(), CanonicalParserPaperCanaryReadinessAssessment.id.desc())
        .limit(1)
    )
    if assessment is None:
        return {
            "resolved_status": "UNASSESSED",
            "assessment_id": None,
            "paper_execution_authorized": False,
            "live_execution_authorized": False,
        }
    payload = _serialize_assessment(db, assessment)
    audit_reasons = _stored_evidence_audit(db, assessment)
    if audit_reasons:
        payload.update(resolved_status="AUDIT_INVALID", resolution_reason_codes=audit_reasons)
        return payload
    if _aware(assessment.valid_until) <= now:
        payload["resolved_status"] = "EXPIRED"
        return payload
    preview = preview_paper_canary_readiness(db, settings_object=settings_object, evaluated_at=now)
    if (
        preview["evidence_hash"] != assessment.evidence_hash
        or preview["policy_hash"] != assessment.policy_hash
        or preview.get("binding", {}).get("binding_id") != assessment.binding_id
        or preview.get("binding", {}).get("latest_event_hash") != assessment.binding_event_hash
    ):
        payload["resolved_status"] = "DRIFTED"
        return payload
    payload["resolved_status"] = assessment.status
    return payload


def get_paper_canary_readiness_status(db: Session, *, settings_object: Any = settings) -> dict[str, Any]:
    return {
        "enabled": bool(getattr(settings_object, "CANONICAL_PARSER_PAPER_CANARY_READINESS_ENABLED", False)),
        "policy": _policy_snapshot(settings_object),
        "assessment_count": int(db.scalar(select(func.count(CanonicalParserPaperCanaryReadinessAssessment.id))) or 0),
        "evidence_run_count": int(db.scalar(select(func.count(CanonicalParserPaperCanaryReadinessEvidenceRun.id))) or 0),
        "operational_guards": {
            "manual_assessment_only": True,
            "source_run_audit_required": True,
            "writes_readiness_tables_only": True,
            "paper_account_writes": False,
            "paper_order_writes": False,
            "paper_position_writes": False,
            "trade_writes": False,
            "worker_connected": False,
            "scheduler_connected": False,
            "stream_connected": False,
            "position_monitor_connected": False,
            "paper_execution_authorized": False,
            "live_execution_authorized": False,
        },
    }
