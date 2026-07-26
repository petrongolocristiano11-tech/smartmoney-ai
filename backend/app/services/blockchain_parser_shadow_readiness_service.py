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
    CanonicalParserShadowConsumerResult,
    CanonicalParserShadowConsumerRun,
    CanonicalParserShadowReadinessAssessment,
    CanonicalParserShadowReadinessEvidenceRun,
    CanonicalParserShadowRuntimeLease,
    RawBlockchainEvent,
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
from backend.app.services.blockchain_parser_shadow_consumer_service import (
    SHADOW_CONSUMER_POLICY_VERSION,
)
from backend.app.services.blockchain_parser_shadow_runtime_lease_service import (
    LEASE_CONSUMER,
    resolve_shadow_runtime_lease,
)

READINESS_POLICY_VERSION = "canonical-parser-shadow-readiness/1"
READINESS_CONFIRMATION_PREFIX = "ASSESS_CERTIFIED_SHADOW_READINESS"
_MAX_ACTOR_LENGTH = 80
_MAX_NOTE_LENGTH = 500


class CanonicalParserShadowReadinessError(ValueError):
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


def _iso(value: datetime | None) -> str | None:
    return _aware(value).isoformat() if value is not None else None


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
        "policy_version": READINESS_POLICY_VERSION,
        "scope": RUNTIME_SCOPE,
        "channel": RUNTIME_CHANNEL,
        "consumer": LEASE_CONSUMER,
        "minimum_runs": int(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_READINESS_MIN_RUNS", 3)
        ),
        "maximum_runs": int(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_READINESS_MAX_RUNS", 20)
        ),
        "minimum_total_events": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_READINESS_MIN_TOTAL_EVENTS",
                15,
            )
        ),
        "minimum_unique_events": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_READINESS_MIN_UNIQUE_EVENTS",
                10,
            )
        ),
        "minimum_pass_rate": float(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_READINESS_MIN_PASS_RATE",
                100.0,
            )
        ),
        "maximum_failed_events": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_READINESS_MAX_FAILED_EVENTS",
                0,
            )
        ),
        "maximum_skipped_events": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_READINESS_MAX_SKIPPED_EVENTS",
                0,
            )
        ),
        "minimum_observation_span_minutes": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_READINESS_MIN_OBSERVATION_SPAN_MINUTES",
                5,
            )
        ),
        "maximum_evidence_age_minutes": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_READINESS_MAX_EVIDENCE_AGE_MINUTES",
                30,
            )
        ),
        "validity_minutes": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_READINESS_VALIDITY_MINUTES",
                15,
            )
        ),
        "requires_current_certified_lease": True,
        "requires_passed_consumer_runs": True,
        "requires_result_count_reconciliation": True,
        "requires_current_raw_payload_hashes": True,
        "requires_deterministic_outputs": True,
        "requires_non_empty_shadow_artifacts": True,
        "immutable_evidence_links": True,
        "external_requests_allowed": False,
        "writes_trades": False,
        "writes_canonical_materialization": False,
        "starts_workers": False,
        "automatic_execution": False,
        "live_execution": False,
    }


def _stored_run_evidence_hash(snapshot: dict[str, Any]) -> str:
    payload = dict(snapshot)
    payload.pop("run_evidence_hash", None)
    return calculate_payload_hash(payload)


def _expected_run_key(run: CanonicalParserShadowConsumerRun) -> str:
    manifest = {
        "lease_id": run.lease_id,
        "certification_id": run.certification_id,
        "binding_id": run.binding_id,
        "promotion_id": run.promotion_id,
        "lease_event_hash": run.lease_event_hash,
        "certification_event_hash": run.certification_event_hash,
        "release_manifest_hash": run.release_manifest_hash,
        "parser_name": run.parser_name,
        "parser_version": run.parser_version,
        "parser_implementation_hash": run.parser_implementation_hash,
        "output_schema_version": run.output_schema_version,
        "consumer_policy_hash": run.consumer_policy_hash,
        "selection": run.selection_snapshot,
    }
    return calculate_payload_hash(manifest)


def _run_evidence(
    db: Session,
    *,
    run: CanonicalParserShadowConsumerRun,
    lease: CanonicalParserShadowRuntimeLease,
) -> tuple[dict[str, Any], list[str]]:
    reasons: set[str] = set()
    results = list(
        db.scalars(
            select(CanonicalParserShadowConsumerResult)
            .where(
                CanonicalParserShadowConsumerResult.consumer_run_db_id == run.id
            )
            .order_by(CanonicalParserShadowConsumerResult.id.asc())
        )
    )
    counts = {
        "PASS": sum(result.status == "PASS" for result in results),
        "FAIL": sum(result.status == "FAIL" for result in results),
        "SKIPPED": sum(result.status == "SKIPPED" for result in results),
    }
    artifact_count = sum(int(result.artifact_count) for result in results)

    if run.status != "PASSED":
        reasons.add("SHADOW_RUN_NOT_PASSED")
    if run.completed_at is None:
        reasons.add("SHADOW_RUN_INCOMPLETE")
    if run.consumer_policy_version != SHADOW_CONSUMER_POLICY_VERSION:
        reasons.add("SHADOW_RUN_POLICY_VERSION_DRIFT")
    if run.run_key != _expected_run_key(run):
        reasons.add("SHADOW_RUN_KEY_INVALID")
    if run.lease_db_id != lease.id or run.lease_id != lease.lease_id:
        reasons.add("SHADOW_RUN_LEASE_MISMATCH")
    comparisons = {
        "SHADOW_RUN_CERTIFICATION_DRIFT": (
            run.certification_id,
            lease.certification_id,
        ),
        "SHADOW_RUN_BINDING_DRIFT": (run.binding_id, lease.binding_id),
        "SHADOW_RUN_PROMOTION_DRIFT": (run.promotion_id, lease.promotion_id),
        "SHADOW_RUN_SCOPE_DRIFT": (run.scope, lease.scope),
        "SHADOW_RUN_CHANNEL_DRIFT": (run.channel, lease.channel),
        "SHADOW_RUN_CONSUMER_DRIFT": (run.consumer, lease.consumer),
        "SHADOW_RUN_PARSER_NAME_DRIFT": (run.parser_name, lease.parser_name),
        "SHADOW_RUN_PARSER_VERSION_DRIFT": (
            run.parser_version,
            lease.parser_version,
        ),
        "SHADOW_RUN_PARSER_HASH_DRIFT": (
            run.parser_implementation_hash,
            lease.parser_implementation_hash,
        ),
        "SHADOW_RUN_SCHEMA_DRIFT": (
            run.output_schema_version,
            lease.output_schema_version,
        ),
        "SHADOW_RUN_RELEASE_DRIFT": (
            run.release_manifest_hash,
            lease.release_manifest_hash,
        ),
        "SHADOW_RUN_LEASE_EVENT_DRIFT": (
            run.lease_event_hash,
            lease.latest_event_hash,
        ),
        "SHADOW_RUN_CERTIFICATION_EVENT_DRIFT": (
            run.certification_event_hash,
            lease.certification_event_hash,
        ),
    }
    for reason, (expected, actual) in comparisons.items():
        if expected != actual:
            reasons.add(reason)

    if run.processed_count != len(results):
        reasons.add("SHADOW_RUN_RESULT_COUNT_MISMATCH")
    if run.selected_count < run.processed_count:
        reasons.add("SHADOW_RUN_SELECTION_COUNT_INVALID")
    if run.passed_count != counts["PASS"]:
        reasons.add("SHADOW_RUN_PASS_COUNT_MISMATCH")
    if run.failed_count != counts["FAIL"]:
        reasons.add("SHADOW_RUN_FAIL_COUNT_MISMATCH")
    if run.skipped_count != counts["SKIPPED"]:
        reasons.add("SHADOW_RUN_SKIP_COUNT_MISMATCH")
    if run.artifact_count != artifact_count:
        reasons.add("SHADOW_RUN_ARTIFACT_COUNT_MISMATCH")
    if (
        run.processed_count
        != run.passed_count + run.failed_count + run.skipped_count
    ):
        reasons.add("SHADOW_RUN_PROCESSED_BREAKDOWN_INVALID")

    result_snapshots: list[dict[str, Any]] = []
    for result in results:
        raw_event = db.get(RawBlockchainEvent, result.raw_event_id)
        if raw_event is None:
            reasons.add("SHADOW_RESULT_RAW_EVENT_MISSING")
        else:
            current_payload_hash = calculate_payload_hash(raw_event.raw_payload)
            if current_payload_hash != raw_event.payload_hash:
                reasons.add("SHADOW_RESULT_RAW_PAYLOAD_HASH_INVALID")
            if result.raw_payload_hash != raw_event.payload_hash:
                reasons.add("SHADOW_RESULT_RAW_PAYLOAD_DRIFT")

        artifact_hash = calculate_payload_hash(result.shadow_artifacts)
        if result.status != "PASS":
            reasons.add("SHADOW_RESULT_NOT_PASS")
        if result.compatible is not True:
            reasons.add("SHADOW_RESULT_INCOMPATIBLE")
        if result.deterministic is not True:
            reasons.add("SHADOW_RESULT_NOT_DETERMINISTIC")
        if not result.output_hash:
            reasons.add("SHADOW_RESULT_OUTPUT_HASH_MISSING")
        if result.output_hash != result.verification_output_hash:
            reasons.add("SHADOW_RESULT_OUTPUT_HASH_MISMATCH")
        if result.output_hash != artifact_hash:
            reasons.add("SHADOW_RESULT_ARTIFACT_HASH_MISMATCH")
        if result.artifact_count != len(result.shadow_artifacts or []):
            reasons.add("SHADOW_RESULT_ARTIFACT_COUNT_MISMATCH")
        if result.artifact_count < 1:
            reasons.add("SHADOW_RESULT_EMPTY_ARTIFACTS")
        if result.reason_codes:
            reasons.add("SHADOW_RESULT_REASON_CODES_PRESENT")
        if result.error_message:
            reasons.add("SHADOW_RESULT_ERROR_PRESENT")

        result_snapshots.append(
            {
                "result_id": result.result_id,
                "raw_event_id": result.raw_event_id,
                "raw_payload_hash": result.raw_payload_hash,
                "status": result.status,
                "compatible": result.compatible,
                "deterministic": result.deterministic,
                "output_hash": result.output_hash,
                "verification_output_hash": result.verification_output_hash,
                "artifact_count": result.artifact_count,
                "shadow_artifacts_hash": artifact_hash,
                "reason_codes": sorted(str(item) for item in (result.reason_codes or [])),
                "error_message": result.error_message,
            }
        )

    snapshot = {
        "run_id": run.run_id,
        "run_key": run.run_key,
        "lease_id": run.lease_id,
        "certification_id": run.certification_id,
        "binding_id": run.binding_id,
        "promotion_id": run.promotion_id,
        "status": run.status,
        "scope": run.scope,
        "channel": run.channel,
        "consumer": run.consumer,
        "parser_name": run.parser_name,
        "parser_version": run.parser_version,
        "parser_implementation_hash": run.parser_implementation_hash,
        "output_schema_version": run.output_schema_version,
        "release_manifest_hash": run.release_manifest_hash,
        "lease_event_hash": run.lease_event_hash,
        "certification_event_hash": run.certification_event_hash,
        "consumer_policy_version": run.consumer_policy_version,
        "consumer_policy_hash": run.consumer_policy_hash,
        "requested_limit": run.requested_limit,
        "selected_count": run.selected_count,
        "processed_count": run.processed_count,
        "passed_count": run.passed_count,
        "failed_count": run.failed_count,
        "skipped_count": run.skipped_count,
        "artifact_count": run.artifact_count,
        "selection_snapshot": run.selection_snapshot,
        "metrics_snapshot": run.metrics_snapshot,
        "reason_codes": run.reason_codes,
        "started_at": _iso(run.started_at),
        "completed_at": _iso(run.completed_at),
        "result_count": len(results),
        "results": result_snapshots,
    }
    snapshot["run_evidence_hash"] = calculate_payload_hash(snapshot)
    return snapshot, sorted(reasons)


def _evaluate(
    db: Session,
    *,
    lease_id: str | None,
    settings_object: Any,
    registry: ParserRegistry,
    evaluated_at: datetime,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _policy_snapshot(settings_object)
    policy_hash = calculate_payload_hash(policy)
    integrity_reasons: set[str] = set()
    blocking_reasons: set[str] = set()
    review_reasons: set[str] = set()
    insufficient_reasons: set[str] = set()

    lease_resolution = resolve_shadow_runtime_lease(
        db,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=now,
    )
    lease_payload = lease_resolution.get("lease") or {}
    resolved_lease_id = lease_payload.get("lease_id")
    if lease_id and str(lease_id).strip() != resolved_lease_id:
        blocking_reasons.add("SHADOW_READINESS_LEASE_ID_MISMATCH")
    if not lease_resolution.get("resolved"):
        blocking_reasons.update(
            lease_resolution.get("reason_codes") or ["SHADOW_LEASE_UNRESOLVED"]
        )
    if not resolved_lease_id:
        blocking_reasons.add("SHADOW_READINESS_LEASE_MISSING")

    lease = None
    if resolved_lease_id:
        lease = db.scalar(
            select(CanonicalParserShadowRuntimeLease).where(
                CanonicalParserShadowRuntimeLease.lease_id == resolved_lease_id
            )
        )
    if lease is None:
        blocking_reasons.add("SHADOW_READINESS_LEASE_ROW_MISSING")

    runs: list[CanonicalParserShadowConsumerRun] = []
    if lease is not None:
        runs = list(
            db.scalars(
                select(CanonicalParserShadowConsumerRun)
                .where(
                    CanonicalParserShadowConsumerRun.lease_db_id == lease.id,
                    CanonicalParserShadowConsumerRun.completed_at.is_not(None),
                )
                .order_by(
                    CanonicalParserShadowConsumerRun.completed_at.desc(),
                    CanonicalParserShadowConsumerRun.id.desc(),
                )
                .limit(policy["maximum_runs"])
            )
        )
    runs = list(reversed(runs))

    run_snapshots: list[dict[str, Any]] = []
    run_rows: list[CanonicalParserShadowConsumerRun] = []
    if lease is not None:
        for run in runs:
            snapshot, run_reasons = _run_evidence(db, run=run, lease=lease)
            run_snapshots.append(snapshot)
            run_rows.append(run)
            integrity_reasons.update(run_reasons)

    run_count = len(run_snapshots)
    total_processed = sum(int(item["processed_count"]) for item in run_snapshots)
    total_passed = sum(int(item["passed_count"]) for item in run_snapshots)
    total_failed = sum(int(item["failed_count"]) for item in run_snapshots)
    total_skipped = sum(int(item["skipped_count"]) for item in run_snapshots)
    total_artifacts = sum(int(item["artifact_count"]) for item in run_snapshots)
    unique_event_ids = sorted(
        {
            int(result["raw_event_id"])
            for item in run_snapshots
            for result in item["results"]
        }
    )
    pass_rate = (
        round((total_passed / total_processed) * 100.0, 4)
        if total_processed
        else 0.0
    )

    completed_times = [
        _aware(run.completed_at) for run in run_rows if run.completed_at is not None
    ]
    started_times = [_aware(run.started_at) for run in run_rows]
    evidence_started_at = min(started_times) if started_times else None
    evidence_completed_at = max(completed_times) if completed_times else None
    observation_span_minutes = (
        round(
            (evidence_completed_at - evidence_started_at).total_seconds() / 60.0,
            4,
        )
        if evidence_started_at is not None and evidence_completed_at is not None
        else 0.0
    )
    evidence_age_minutes: float | None = None
    if evidence_completed_at is not None:
        age_seconds = (now - evidence_completed_at).total_seconds()
        if age_seconds < -1:
            integrity_reasons.add("SHADOW_EVIDENCE_TIMESTAMP_IN_FUTURE")
        else:
            evidence_age_minutes = round(age_seconds / 60.0, 4)
            if evidence_age_minutes > policy["maximum_evidence_age_minutes"]:
                review_reasons.add("SHADOW_EVIDENCE_STALE")

    if run_count < policy["minimum_runs"]:
        insufficient_reasons.add("SHADOW_READINESS_RUNS_BELOW_MINIMUM")
    if total_processed < policy["minimum_total_events"]:
        insufficient_reasons.add("SHADOW_READINESS_EVENTS_BELOW_MINIMUM")
    if len(unique_event_ids) < policy["minimum_unique_events"]:
        insufficient_reasons.add("SHADOW_READINESS_UNIQUE_EVENTS_BELOW_MINIMUM")
    if observation_span_minutes < policy["minimum_observation_span_minutes"]:
        insufficient_reasons.add("SHADOW_READINESS_OBSERVATION_SPAN_BELOW_MINIMUM")
    if pass_rate < policy["minimum_pass_rate"]:
        blocking_reasons.add("SHADOW_READINESS_PASS_RATE_BELOW_MINIMUM")
    if total_failed > policy["maximum_failed_events"]:
        blocking_reasons.add("SHADOW_READINESS_FAILED_EVENTS_EXCEEDED")
    if total_skipped > policy["maximum_skipped_events"]:
        blocking_reasons.add("SHADOW_READINESS_SKIPPED_EVENTS_EXCEEDED")

    if integrity_reasons or blocking_reasons:
        decision = "BLOCKED"
    elif insufficient_reasons:
        decision = "INSUFFICIENT_DATA"
    elif review_reasons:
        decision = "REVIEW"
    else:
        decision = "READY"

    metrics = {
        "run_count": run_count,
        "total_processed_count": total_processed,
        "total_passed_count": total_passed,
        "total_failed_count": total_failed,
        "total_skipped_count": total_skipped,
        "total_artifact_count": total_artifacts,
        "unique_event_count": len(unique_event_ids),
        "pass_rate": pass_rate,
        "observation_span_minutes": observation_span_minutes,
        "evidence_age_minutes": evidence_age_minutes,
    }
    evidence = {
        "lease_id": lease.lease_id if lease else None,
        "certification_id": lease.certification_id if lease else None,
        "binding_id": lease.binding_id if lease else None,
        "promotion_id": lease.promotion_id if lease else None,
        "scope": lease.scope if lease else RUNTIME_SCOPE,
        "channel": lease.channel if lease else RUNTIME_CHANNEL,
        "consumer": lease.consumer if lease else LEASE_CONSUMER,
        "parser_name": lease.parser_name if lease else None,
        "parser_version": lease.parser_version if lease else None,
        "parser_implementation_hash": (
            lease.parser_implementation_hash if lease else None
        ),
        "output_schema_version": lease.output_schema_version if lease else None,
        "release_manifest_hash": lease.release_manifest_hash if lease else None,
        "lease_event_hash": lease.latest_event_hash if lease else None,
        "certification_event_hash": (
            lease.certification_event_hash if lease else None
        ),
        "run_ids": [item["run_id"] for item in run_snapshots],
        "run_evidence_hashes": [
            item["run_evidence_hash"] for item in run_snapshots
        ],
        "runs": run_snapshots,
        "metrics": {
            key: value
            for key, value in metrics.items()
            if key != "evidence_age_minutes"
        },
    }
    evidence_hash = calculate_payload_hash(evidence)
    assessment_key = calculate_payload_hash(
        {
            "lease_id": evidence["lease_id"],
            "readiness_policy_hash": policy_hash,
            "evidence_hash": evidence_hash,
        }
    )
    confirmation = (
        f"{READINESS_CONFIRMATION_PREFIX}:"
        f"{evidence['lease_id'] or 'UNLEASED'}:{evidence_hash[:12]}"
    )
    reason_codes = sorted(
        integrity_reasons
        | blocking_reasons
        | review_reasons
        | insufficient_reasons
    )
    return {
        "dry_run": True,
        "readiness_enabled": bool(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_READINESS_ENABLED",
                False,
            )
        ),
        "assessable": lease is not None,
        "decision": decision,
        "ready": decision == "READY",
        "reason_codes": reason_codes,
        "integrity_reason_codes": sorted(integrity_reasons),
        "blocking_reason_codes": sorted(blocking_reasons),
        "review_reason_codes": sorted(review_reasons),
        "insufficient_reason_codes": sorted(insufficient_reasons),
        "lease_resolution": sanitize_technical_metadata(lease_resolution),
        "lease_id": evidence["lease_id"],
        "certification_id": evidence["certification_id"],
        "binding_id": evidence["binding_id"],
        "promotion_id": evidence["promotion_id"],
        "parser": (
            {
                "name": evidence["parser_name"],
                "version": evidence["parser_version"],
                "implementation_hash": evidence["parser_implementation_hash"],
                "output_schema_version": evidence["output_schema_version"],
            }
            if lease is not None
            else None
        ),
        "readiness_policy": policy,
        "readiness_policy_hash": policy_hash,
        "evidence_snapshot": evidence,
        "evidence_hash": evidence_hash,
        "assessment_key": assessment_key,
        "confirmation": confirmation,
        "metrics": metrics,
        "evidence_started_at": evidence_started_at,
        "evidence_completed_at": evidence_completed_at,
        "evaluated_at": now,
        "writes_database": False,
        "writes_trades": False,
        "writes_canonical_materialization": False,
        "external_requests": 0,
        "starts_workers": False,
        "automatic_execution": False,
        "live_execution": False,
    }


def preview_shadow_consumer_readiness(
    db: Session,
    *,
    lease_id: str | None = None,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    return _evaluate(
        db,
        lease_id=lease_id,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=_aware(evaluated_at),
    )


def _serialize_evidence_link(
    link: CanonicalParserShadowReadinessEvidenceRun,
) -> dict[str, Any]:
    return {
        "evidence_id": link.evidence_id,
        "run_id": link.run_id,
        "run_key": link.run_key,
        "status": link.status,
        "result_count": link.result_count,
        "processed_count": link.processed_count,
        "passed_count": link.passed_count,
        "failed_count": link.failed_count,
        "skipped_count": link.skipped_count,
        "artifact_count": link.artifact_count,
        "run_evidence_hash": link.run_evidence_hash,
        "completed_at": link.completed_at,
        "evidence_snapshot": link.evidence_snapshot,
    }


def _serialize_assessment(
    db: Session,
    assessment: CanonicalParserShadowReadinessAssessment,
    *,
    created: bool | None = None,
    include_evidence: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "assessment_id": assessment.assessment_id,
        "assessment_key": assessment.assessment_key,
        "lease_id": assessment.lease_id,
        "certification_id": assessment.certification_id,
        "binding_id": assessment.binding_id,
        "promotion_id": assessment.promotion_id,
        "scope": assessment.scope,
        "channel": assessment.channel,
        "consumer": assessment.consumer,
        "status": assessment.status,
        "parser_name": assessment.parser_name,
        "parser_version": assessment.parser_version,
        "parser_implementation_hash": assessment.parser_implementation_hash,
        "output_schema_version": assessment.output_schema_version,
        "release_manifest_hash": assessment.release_manifest_hash,
        "lease_event_hash": assessment.lease_event_hash,
        "certification_event_hash": assessment.certification_event_hash,
        "readiness_policy_version": assessment.readiness_policy_version,
        "readiness_policy_hash": assessment.readiness_policy_hash,
        "evidence_hash": assessment.evidence_hash,
        "run_ids": assessment.run_ids,
        "run_count": assessment.run_count,
        "total_processed_count": assessment.total_processed_count,
        "total_passed_count": assessment.total_passed_count,
        "total_failed_count": assessment.total_failed_count,
        "total_skipped_count": assessment.total_skipped_count,
        "total_artifact_count": assessment.total_artifact_count,
        "unique_event_count": assessment.unique_event_count,
        "pass_rate": float(assessment.pass_rate),
        "reason_codes": assessment.reason_codes,
        "policy_snapshot": assessment.policy_snapshot,
        "evidence_snapshot": assessment.evidence_snapshot,
        "metrics_snapshot": assessment.metrics_snapshot,
        "actor_label": assessment.actor_label,
        "note": assessment.note,
        "evidence_started_at": assessment.evidence_started_at,
        "evidence_completed_at": assessment.evidence_completed_at,
        "evaluated_at": assessment.evaluated_at,
        "valid_until": assessment.valid_until,
        "technical_metadata": assessment.technical_metadata,
    }
    if include_evidence:
        links = list(
            db.scalars(
                select(CanonicalParserShadowReadinessEvidenceRun)
                .where(
                    CanonicalParserShadowReadinessEvidenceRun.assessment_db_id
                    == assessment.id
                )
                .order_by(
                    CanonicalParserShadowReadinessEvidenceRun.completed_at.asc(),
                    CanonicalParserShadowReadinessEvidenceRun.id.asc(),
                )
            )
        )
        payload["evidence_runs"] = [
            _serialize_evidence_link(link) for link in links
        ]
    if created is not None:
        payload["created"] = created
    return payload


def execute_shadow_consumer_readiness_assessment(
    db: Session,
    *,
    confirmation: str,
    lease_id: str | None = None,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(
        getattr(
            settings_object,
            "CANONICAL_PARSER_SHADOW_READINESS_ENABLED",
            False,
        )
    ):
        raise CanonicalParserShadowReadinessError(
            "Shadow consumer readiness assessment disabilitato.",
            code="CANONICAL_PARSER_SHADOW_READINESS_DISABLED",
            status_code=409,
        )
    now = _aware(evaluated_at)
    preview = preview_shadow_consumer_readiness(
        db,
        lease_id=lease_id,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=now,
    )
    if str(confirmation or "").strip() != preview["confirmation"]:
        raise CanonicalParserShadowReadinessError(
            "Conferma readiness non valida o non aggiornata.",
            code="SHADOW_READINESS_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if not preview["assessable"]:
        raise CanonicalParserShadowReadinessError(
            "Nessuna lease disponibile per la valutazione readiness.",
            code="SHADOW_READINESS_NOT_ASSESSABLE",
            status_code=409,
        )

    existing = db.scalar(
        select(CanonicalParserShadowReadinessAssessment).where(
            CanonicalParserShadowReadinessAssessment.assessment_key
            == preview["assessment_key"]
        )
    )
    if existing is not None:
        return _serialize_assessment(db, existing, created=False)

    lease = db.scalar(
        select(CanonicalParserShadowRuntimeLease).where(
            CanonicalParserShadowRuntimeLease.lease_id == preview["lease_id"]
        )
    )
    if lease is None:
        raise CanonicalParserShadowReadinessError(
            "Shadow runtime lease non trovata.",
            code="SHADOW_READINESS_LEASE_MISSING",
            status_code=409,
        )
    policy = preview["readiness_policy"]
    candidate_valid_until = now + timedelta(minutes=policy["validity_minutes"])
    valid_until = min(candidate_valid_until, _aware(lease.expires_at))

    metrics = preview["metrics"]
    assessment = CanonicalParserShadowReadinessAssessment(
        assessment_id=str(uuid4()),
        assessment_key=preview["assessment_key"],
        lease_db_id=lease.id,
        lease_id=lease.lease_id,
        certification_id=lease.certification_id,
        binding_id=lease.binding_id,
        promotion_id=lease.promotion_id,
        scope=lease.scope,
        channel=lease.channel,
        consumer=lease.consumer,
        status=preview["decision"],
        parser_name=lease.parser_name,
        parser_version=lease.parser_version,
        parser_implementation_hash=lease.parser_implementation_hash,
        output_schema_version=lease.output_schema_version,
        release_manifest_hash=lease.release_manifest_hash,
        lease_event_hash=lease.latest_event_hash,
        certification_event_hash=lease.certification_event_hash,
        readiness_policy_version=READINESS_POLICY_VERSION,
        readiness_policy_hash=preview["readiness_policy_hash"],
        evidence_hash=preview["evidence_hash"],
        run_ids=preview["evidence_snapshot"]["run_ids"],
        run_count=metrics["run_count"],
        total_processed_count=metrics["total_processed_count"],
        total_passed_count=metrics["total_passed_count"],
        total_failed_count=metrics["total_failed_count"],
        total_skipped_count=metrics["total_skipped_count"],
        total_artifact_count=metrics["total_artifact_count"],
        unique_event_count=metrics["unique_event_count"],
        pass_rate=Decimal(str(metrics["pass_rate"])),
        reason_codes=preview["reason_codes"],
        policy_snapshot=policy,
        evidence_snapshot=preview["evidence_snapshot"],
        metrics_snapshot=metrics,
        actor_label=_actor(actor_label),
        note=_note(note),
        evidence_started_at=preview["evidence_started_at"],
        evidence_completed_at=preview["evidence_completed_at"],
        evaluated_at=now,
        valid_until=valid_until,
        technical_metadata={
            "manual_only": True,
            "immutable_assessment": True,
            "consumer_connected": False,
            "external_requests": 0,
            "writes_trades": False,
            "writes_canonical_materialization": False,
            "starts_workers": False,
            "automatic_execution": False,
            "live_execution": False,
        },
    )
    db.add(assessment)
    try:
        db.flush()
        run_by_id = {
            run.run_id: run
            for run in db.scalars(
                select(CanonicalParserShadowConsumerRun).where(
                    CanonicalParserShadowConsumerRun.run_id.in_(
                        preview["evidence_snapshot"]["run_ids"]
                    )
                )
            )
        }
        for run_snapshot in preview["evidence_snapshot"]["runs"]:
            run = run_by_id.get(run_snapshot["run_id"])
            if run is None:
                raise CanonicalParserShadowReadinessError(
                    "Un run shadow selezionato non esiste più.",
                    code="SHADOW_READINESS_EVIDENCE_RUN_MISSING",
                    status_code=409,
                )
            db.add(
                CanonicalParserShadowReadinessEvidenceRun(
                    evidence_id=str(uuid4()),
                    assessment_db_id=assessment.id,
                    consumer_run_db_id=run.id,
                    run_id=run.run_id,
                    run_key=run.run_key,
                    status=run.status,
                    result_count=int(run_snapshot["result_count"]),
                    processed_count=run.processed_count,
                    passed_count=run.passed_count,
                    failed_count=run.failed_count,
                    skipped_count=run.skipped_count,
                    artifact_count=run.artifact_count,
                    run_evidence_hash=run_snapshot["run_evidence_hash"],
                    completed_at=_aware(run.completed_at),
                    evidence_snapshot=run_snapshot,
                )
            )
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(CanonicalParserShadowReadinessAssessment).where(
                CanonicalParserShadowReadinessAssessment.assessment_key
                == preview["assessment_key"]
            )
        )
        if existing is not None:
            return _serialize_assessment(db, existing, created=False)
        raise
    db.refresh(assessment)
    return _serialize_assessment(db, assessment, created=True)


def get_shadow_consumer_readiness_assessment(
    db: Session,
    assessment_id: str,
) -> dict[str, Any]:
    assessment = db.scalar(
        select(CanonicalParserShadowReadinessAssessment).where(
            CanonicalParserShadowReadinessAssessment.assessment_id
            == str(assessment_id or "").strip()
        )
    )
    if assessment is None:
        raise CanonicalParserShadowReadinessError(
            "Shadow readiness assessment non trovato.",
            code="SHADOW_READINESS_ASSESSMENT_NOT_FOUND",
            status_code=404,
        )
    return _serialize_assessment(db, assessment)


def resolve_shadow_consumer_readiness(
    db: Session,
    *,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    readiness_enabled = bool(
        getattr(
            settings_object,
            "CANONICAL_PARSER_SHADOW_READINESS_ENABLED",
            False,
        )
    )
    lease_resolution = resolve_shadow_runtime_lease(
        db,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=now,
    )
    lease_payload = lease_resolution.get("lease") or {}
    lease_id = lease_payload.get("lease_id")
    if not lease_id:
        return {
            "resolved": False,
            "status": "UNASSESSED",
            "reason_codes": sorted(
                set(
                    lease_resolution.get("reason_codes")
                    or ["ACTIVE_SHADOW_LEASE_MISSING"]
                )
            ),
            "readiness_enabled": readiness_enabled,
            "consumer_authorized": False,
            "consumer_connected": False,
            "lease_resolution": sanitize_technical_metadata(lease_resolution),
            "automatic_execution": False,
            "live_execution": False,
        }

    assessment = db.scalar(
        select(CanonicalParserShadowReadinessAssessment)
        .where(CanonicalParserShadowReadinessAssessment.lease_id == lease_id)
        .order_by(
            CanonicalParserShadowReadinessAssessment.evaluated_at.desc(),
            CanonicalParserShadowReadinessAssessment.id.desc(),
        )
    )
    if assessment is None:
        return {
            "resolved": False,
            "status": "UNASSESSED",
            "reason_codes": ["SHADOW_READINESS_ASSESSMENT_MISSING"],
            "readiness_enabled": readiness_enabled,
            "consumer_authorized": False,
            "consumer_connected": False,
            "lease_resolution": sanitize_technical_metadata(lease_resolution),
            "automatic_execution": False,
            "live_execution": False,
        }

    reasons: set[str] = set()
    if assessment.status != "READY":
        reasons.add(f"SHADOW_READINESS_DECISION_{assessment.status}")
    if _aware(assessment.valid_until) <= now:
        reasons.add("SHADOW_READINESS_EXPIRED")
    if not lease_resolution.get("resolved"):
        reasons.update(
            lease_resolution.get("reason_codes") or ["SHADOW_LEASE_UNRESOLVED"]
        )

    lease = db.scalar(
        select(CanonicalParserShadowRuntimeLease).where(
            CanonicalParserShadowRuntimeLease.lease_id == lease_id
        )
    )
    if lease is None:
        reasons.add("SHADOW_READINESS_LEASE_ROW_MISSING")
    else:
        comparisons = {
            "SHADOW_READINESS_CERTIFICATION_DRIFT": (
                assessment.certification_id,
                lease.certification_id,
            ),
            "SHADOW_READINESS_BINDING_DRIFT": (
                assessment.binding_id,
                lease.binding_id,
            ),
            "SHADOW_READINESS_PROMOTION_DRIFT": (
                assessment.promotion_id,
                lease.promotion_id,
            ),
            "SHADOW_READINESS_PARSER_HASH_DRIFT": (
                assessment.parser_implementation_hash,
                lease.parser_implementation_hash,
            ),
            "SHADOW_READINESS_SCHEMA_DRIFT": (
                assessment.output_schema_version,
                lease.output_schema_version,
            ),
            "SHADOW_READINESS_RELEASE_DRIFT": (
                assessment.release_manifest_hash,
                lease.release_manifest_hash,
            ),
            "SHADOW_READINESS_LEASE_EVENT_DRIFT": (
                assessment.lease_event_hash,
                lease.latest_event_hash,
            ),
            "SHADOW_READINESS_CERTIFICATION_EVENT_DRIFT": (
                assessment.certification_event_hash,
                lease.certification_event_hash,
            ),
        }
        for reason, (expected, actual) in comparisons.items():
            if expected != actual:
                reasons.add(reason)

    current_policy_hash = calculate_payload_hash(_policy_snapshot(settings_object))
    if current_policy_hash != assessment.readiness_policy_hash:
        reasons.add("SHADOW_READINESS_POLICY_DRIFT")
    if calculate_payload_hash(assessment.policy_snapshot) != assessment.readiness_policy_hash:
        reasons.add("SHADOW_READINESS_POLICY_HASH_INVALID")
    if calculate_payload_hash(assessment.evidence_snapshot) != assessment.evidence_hash:
        reasons.add("SHADOW_READINESS_EVIDENCE_HASH_INVALID")

    links = list(
        db.scalars(
            select(CanonicalParserShadowReadinessEvidenceRun)
            .where(
                CanonicalParserShadowReadinessEvidenceRun.assessment_db_id
                == assessment.id
            )
            .order_by(
                CanonicalParserShadowReadinessEvidenceRun.completed_at.asc(),
                CanonicalParserShadowReadinessEvidenceRun.id.asc(),
            )
        )
    )
    if len(links) != assessment.run_count:
        reasons.add("SHADOW_READINESS_EVIDENCE_LINK_COUNT_MISMATCH")
    if [link.run_id for link in links] != list(assessment.run_ids or []):
        reasons.add("SHADOW_READINESS_EVIDENCE_RUN_IDS_MISMATCH")
    if lease is not None:
        for link in links:
            if _stored_run_evidence_hash(link.evidence_snapshot) != link.run_evidence_hash:
                reasons.add("SHADOW_READINESS_LINK_HASH_INVALID")
            run = db.get(CanonicalParserShadowConsumerRun, link.consumer_run_db_id)
            if run is None:
                reasons.add("SHADOW_READINESS_CURRENT_RUN_MISSING")
                continue
            current_snapshot, run_reasons = _run_evidence(db, run=run, lease=lease)
            if run_reasons:
                reasons.update(run_reasons)
            if current_snapshot["run_evidence_hash"] != link.run_evidence_hash:
                reasons.add("SHADOW_READINESS_CURRENT_RUN_DRIFT")

    if assessment.status != "READY":
        status = "NOT_READY"
    elif reasons == {"SHADOW_READINESS_EXPIRED"}:
        status = "EXPIRED"
    elif reasons:
        status = "DRIFTED"
    else:
        status = "READY"
    resolved = status == "READY"
    consumer_authorized = bool(
        resolved
        and readiness_enabled
        and lease_resolution.get("consumer_authorized")
    )
    return {
        "resolved": resolved,
        "status": status,
        "reason_codes": sorted(reasons),
        "readiness_enabled": readiness_enabled,
        "consumer_authorized": consumer_authorized,
        "consumer_connected": False,
        "assessment": _serialize_assessment(db, assessment),
        "lease_resolution": sanitize_technical_metadata(lease_resolution),
        "automatic_execution": False,
        "starts_workers": False,
        "live_execution": False,
    }


def get_shadow_consumer_readiness_status(
    db: Session,
    *,
    settings_object: Any = settings,
) -> dict[str, Any]:
    counts = dict(
        db.execute(
            select(
                CanonicalParserShadowReadinessAssessment.status,
                func.count(CanonicalParserShadowReadinessAssessment.id),
            ).group_by(CanonicalParserShadowReadinessAssessment.status)
        ).all()
    )
    return {
        "readiness_enabled": bool(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_READINESS_ENABLED",
                False,
            )
        ),
        "policy_version": READINESS_POLICY_VERSION,
        "assessment_count": int(sum(counts.values())),
        "status_counts": {
            status: int(counts.get(status, 0))
            for status in ("READY", "REVIEW", "BLOCKED", "INSUFFICIENT_DATA")
        },
        "policy": _policy_snapshot(settings_object),
        "operational_guards": {
            "manual_assessment_only": True,
            "immutable_evidence_links": True,
            "consumer_connected": False,
            "automatic_consumer_connected": False,
            "external_requests": 0,
            "writes_trades": False,
            "writes_canonical_materialization": False,
            "starts_workers": False,
            "changes_runtime_flags": False,
            "operational_pipeline_consumer": False,
            "live_execution": False,
        },
    }
