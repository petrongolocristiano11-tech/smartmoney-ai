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
    CanonicalParserAdmissionResult,
    CanonicalParserAdmissionRun,
    CanonicalParserRuntimeBinding,
    CanonicalParserRuntimeCertification,
    CanonicalParserRuntimeCertificationEvent,
)
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    sanitize_error_message,
    sanitize_technical_metadata,
)
from backend.app.services.blockchain_parser_registry_service import (
    DEFAULT_PARSER_REGISTRY,
    ParserRegistry,
    ParserRegistryError,
)
from backend.app.services.blockchain_parser_runtime_binding_service import (
    RUNTIME_CHANNEL,
    RUNTIME_SCOPE,
    resolve_shadow_parser_runtime,
)

CERTIFICATION_POLICY_VERSION = "canonical-parser-runtime-certification/1"
CERTIFICATION_CONFIRMATION_PREFIX = "CERTIFY_PARSER_RUNTIME"
CERTIFICATION_REVOKE_PREFIX = "REVOKE_PARSER_RUNTIME_CERTIFICATION"
_MAX_ACTOR_LENGTH = 80
_MAX_NOTE_LENGTH = 500


class CanonicalParserRuntimeCertificationError(ValueError):
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
        "policy_version": CERTIFICATION_POLICY_VERSION,
        "scope": RUNTIME_SCOPE,
        "channel": RUNTIME_CHANNEL,
        "minimum_admission_runs": int(
            getattr(settings_object, "CANONICAL_PARSER_RUNTIME_CERTIFICATION_MIN_RUNS", 2)
        ),
        "minimum_total_events": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_RUNTIME_CERTIFICATION_MIN_TOTAL_EVENTS",
                10,
            )
        ),
        "minimum_pass_rate": float(
            getattr(
                settings_object,
                "CANONICAL_PARSER_RUNTIME_CERTIFICATION_MIN_PASS_RATE",
                100.0,
            )
        ),
        "maximum_failed_events": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_RUNTIME_CERTIFICATION_MAX_FAILED_EVENTS",
                0,
            )
        ),
        "maximum_evidence_age_hours": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_RUNTIME_CERTIFICATION_MAX_EVIDENCE_AGE_HOURS",
                24,
            )
        ),
        "validity_hours": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_RUNTIME_CERTIFICATION_VALIDITY_HOURS",
                24,
            )
        ),
        "requires_healthy_binding": True,
        "requires_passed_admission_runs": True,
        "requires_result_count_reconciliation": True,
        "requires_deterministic_outputs": True,
        "external_requests_allowed": False,
        "trade_writes_allowed": False,
        "runtime_activation": False,
        "operational_pipeline_consumer": False,
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


def _verify_event_chain(
    db: Session, certification: CanonicalParserRuntimeCertification
) -> list[str]:
    events = list(
        db.scalars(
            select(CanonicalParserRuntimeCertificationEvent)
            .where(
                CanonicalParserRuntimeCertificationEvent.certification_db_id
                == certification.id
            )
            .order_by(CanonicalParserRuntimeCertificationEvent.sequence.asc())
        )
    )
    reasons: list[str] = []
    previous_hash: str | None = None
    for expected_sequence, event in enumerate(events, start=1):
        if event.sequence != expected_sequence:
            reasons.append("CERTIFICATION_EVENT_SEQUENCE_INVALID")
        if event.previous_event_hash != previous_hash:
            reasons.append("CERTIFICATION_EVENT_PREVIOUS_HASH_INVALID")
        if calculate_payload_hash(event.event_payload) != event.event_hash:
            reasons.append("CERTIFICATION_EVENT_HASH_INVALID")
        previous_hash = event.event_hash
    if not events:
        reasons.append("CERTIFICATION_EVENT_CHAIN_EMPTY")
    elif certification.latest_event_sequence != events[-1].sequence:
        reasons.append("CERTIFICATION_LATEST_SEQUENCE_INVALID")
    elif certification.latest_event_hash != events[-1].event_hash:
        reasons.append("CERTIFICATION_LATEST_HASH_INVALID")
    return sorted(set(reasons))


def _serialize(certification: CanonicalParserRuntimeCertification) -> dict[str, Any]:
    return {
        "certification_id": certification.certification_id,
        "certification_key": certification.certification_key,
        "binding_id": certification.binding_id,
        "promotion_id": certification.promotion_id,
        "scope": certification.scope,
        "channel": certification.channel,
        "status": certification.status,
        "parser_name": certification.parser_name,
        "parser_version": certification.parser_version,
        "parser_implementation_hash": certification.parser_implementation_hash,
        "output_schema_version": certification.output_schema_version,
        "release_manifest_hash": certification.release_manifest_hash,
        "certification_policy_version": certification.certification_policy_version,
        "certification_policy_hash": certification.certification_policy_hash,
        "evidence_hash": certification.evidence_hash,
        "evidence_snapshot": certification.evidence_snapshot,
        "admission_run_ids": certification.admission_run_ids,
        "admission_run_count": certification.admission_run_count,
        "total_processed_count": certification.total_processed_count,
        "total_passed_count": certification.total_passed_count,
        "total_failed_count": certification.total_failed_count,
        "total_skipped_count": certification.total_skipped_count,
        "pass_rate": float(certification.pass_rate),
        "actor_label": certification.actor_label,
        "note": certification.note,
        "certified_at": certification.certified_at,
        "expires_at": certification.expires_at,
        "revoked_at": certification.revoked_at,
        "revocation_reason": certification.revocation_reason,
        "latest_event_sequence": certification.latest_event_sequence,
        "latest_event_hash": certification.latest_event_hash,
        "technical_metadata": certification.technical_metadata,
    }


def _run_evidence(
    db: Session,
    run: CanonicalParserAdmissionRun,
) -> tuple[dict[str, Any], list[str]]:
    blockers: set[str] = set()
    results = list(
        db.scalars(
            select(CanonicalParserAdmissionResult)
            .where(CanonicalParserAdmissionResult.admission_run_db_id == run.id)
            .order_by(CanonicalParserAdmissionResult.id.asc())
        )
    )
    counts = {
        "PASS": sum(result.status == "PASS" for result in results),
        "FAIL": sum(result.status == "FAIL" for result in results),
        "SKIPPED": sum(result.status == "SKIPPED" for result in results),
    }
    if run.status != "PASSED":
        blockers.add("ADMISSION_RUN_NOT_PASSED")
    if run.completed_at is None:
        blockers.add("ADMISSION_RUN_INCOMPLETE")
    if run.processed_count != len(results):
        blockers.add("ADMISSION_RESULT_COUNT_MISMATCH")
    if run.passed_count != counts["PASS"]:
        blockers.add("ADMISSION_PASS_COUNT_MISMATCH")
    if run.failed_count != counts["FAIL"]:
        blockers.add("ADMISSION_FAIL_COUNT_MISMATCH")
    if run.skipped_count != counts["SKIPPED"]:
        blockers.add("ADMISSION_SKIP_COUNT_MISMATCH")
    for result in results:
        if result.status == "PASS":
            if result.deterministic is not True:
                blockers.add("ADMISSION_RESULT_NOT_DETERMINISTIC")
            if not result.first_output_hash or result.first_output_hash != result.second_output_hash:
                blockers.add("ADMISSION_RESULT_HASH_MISMATCH")
            if result.artifact_count < 1:
                blockers.add("ADMISSION_RESULT_EMPTY")
    snapshot = {
        "admission_id": run.admission_id,
        "admission_key": run.admission_key,
        "status": run.status,
        "binding_id": run.binding_id,
        "binding_event_hash": run.binding_event_hash,
        "release_manifest_hash": run.release_manifest_hash,
        "parser_name": run.parser_name,
        "parser_version": run.parser_version,
        "parser_implementation_hash": run.parser_implementation_hash,
        "output_schema_version": run.output_schema_version,
        "admission_policy_hash": run.admission_policy_hash,
        "selected_count": run.selected_count,
        "processed_count": run.processed_count,
        "passed_count": run.passed_count,
        "failed_count": run.failed_count,
        "skipped_count": run.skipped_count,
        "result_count": len(results),
        "result_hashes": [
            {
                "raw_event_id": result.raw_event_id,
                "status": result.status,
                "first_output_hash": result.first_output_hash,
                "second_output_hash": result.second_output_hash,
                "artifact_count": result.artifact_count,
            }
            for result in results
        ],
        "started_at": _aware(run.started_at).isoformat(),
        "completed_at": _aware(run.completed_at).isoformat() if run.completed_at else None,
    }
    snapshot["run_evidence_hash"] = calculate_payload_hash(snapshot)
    return snapshot, sorted(blockers)


def preview_parser_runtime_certification(
    db: Session,
    *,
    binding_id: str | None = None,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _policy_snapshot(settings_object)
    policy_hash = calculate_payload_hash(policy)
    blockers: set[str] = set()
    resolution = resolve_shadow_parser_runtime(db, registry=registry)
    if not resolution.get("resolved"):
        blockers.update(resolution.get("reason_codes") or ["RUNTIME_BINDING_UNRESOLVED"])
    resolved_binding_id = resolution.get("binding_id")
    if binding_id and binding_id != resolved_binding_id:
        blockers.add("RUNTIME_BINDING_ID_MISMATCH")
    binding = None
    if resolved_binding_id:
        binding = db.scalar(
            select(CanonicalParserRuntimeBinding).where(
                CanonicalParserRuntimeBinding.binding_id == resolved_binding_id
            )
        )
    if binding is None:
        blockers.add("RUNTIME_BINDING_MISSING")

    max_age = timedelta(hours=policy["maximum_evidence_age_hours"])
    runs: list[CanonicalParserAdmissionRun] = []
    if binding is not None:
        runs = list(
            db.scalars(
                select(CanonicalParserAdmissionRun)
                .where(
                    CanonicalParserAdmissionRun.binding_db_id == binding.id,
                    CanonicalParserAdmissionRun.completed_at.is_not(None),
                )
                .order_by(CanonicalParserAdmissionRun.completed_at.desc(), CanonicalParserAdmissionRun.id.desc())
                .limit(policy["minimum_admission_runs"])
            )
        )
    if len(runs) < policy["minimum_admission_runs"]:
        blockers.add("INSUFFICIENT_ADMISSION_RUNS")

    run_snapshots: list[dict[str, Any]] = []
    for run in reversed(runs):
        snapshot, run_blockers = _run_evidence(db, run)
        run_snapshots.append(snapshot)
        blockers.update(run_blockers)
        if run.completed_at is None or now - _aware(run.completed_at) > max_age:
            blockers.add("ADMISSION_EVIDENCE_STALE")
        if binding is not None:
            if run.binding_id != binding.binding_id:
                blockers.add("ADMISSION_BINDING_MISMATCH")
            if run.binding_event_hash != binding.latest_event_hash:
                blockers.add("ADMISSION_BINDING_EVENT_DRIFT")
            if run.release_manifest_hash != binding.release_manifest_hash:
                blockers.add("ADMISSION_RELEASE_DRIFT")
            if run.parser_implementation_hash != binding.parser_implementation_hash:
                blockers.add("ADMISSION_PARSER_HASH_DRIFT")
            if run.output_schema_version != binding.output_schema_version:
                blockers.add("ADMISSION_SCHEMA_DRIFT")

    total_processed = sum(item["processed_count"] for item in run_snapshots)
    total_passed = sum(item["passed_count"] for item in run_snapshots)
    total_failed = sum(item["failed_count"] for item in run_snapshots)
    total_skipped = sum(item["skipped_count"] for item in run_snapshots)
    pass_rate = round((total_passed / total_processed) * 100, 4) if total_processed else 0.0
    if total_processed < policy["minimum_total_events"]:
        blockers.add("INSUFFICIENT_ADMISSION_EVENTS")
    if pass_rate < policy["minimum_pass_rate"]:
        blockers.add("ADMISSION_PASS_RATE_TOO_LOW")
    if total_failed > policy["maximum_failed_events"]:
        blockers.add("ADMISSION_FAILED_EVENTS_EXCEEDED")
    if total_skipped > 0:
        blockers.add("ADMISSION_SKIPPED_EVENTS_PRESENT")

    evidence = {
        "binding_resolution": sanitize_technical_metadata(resolution),
        "binding_id": binding.binding_id if binding else None,
        "promotion_id": binding.promotion_id if binding else None,
        "binding_event_hash": binding.latest_event_hash if binding else None,
        "release_manifest_hash": binding.release_manifest_hash if binding else None,
        "parser_name": binding.parser_name if binding else None,
        "parser_version": binding.parser_version if binding else None,
        "parser_implementation_hash": binding.parser_implementation_hash if binding else None,
        "output_schema_version": binding.output_schema_version if binding else None,
        "admission_runs": run_snapshots,
        "metrics": {
            "admission_run_count": len(run_snapshots),
            "total_processed_count": total_processed,
            "total_passed_count": total_passed,
            "total_failed_count": total_failed,
            "total_skipped_count": total_skipped,
            "pass_rate": pass_rate,
        },
        "evidence_completed_at": (
            max(
                (item["completed_at"] for item in run_snapshots if item["completed_at"]),
                default=None,
            )
        ),
    }
    evidence_hash = calculate_payload_hash(evidence)
    certification_key = calculate_payload_hash(
        {
            "binding_id": evidence["binding_id"],
            "certification_policy_hash": policy_hash,
            "evidence_hash": evidence_hash,
        }
    )
    confirmation = (
        f"{CERTIFICATION_CONFIRMATION_PREFIX}:"
        f"{evidence['binding_id'] or 'UNBOUND'}:{evidence_hash[:12]}"
    )
    return {
        "dry_run": True,
        "certification_enabled": bool(
            getattr(settings_object, "CANONICAL_PARSER_RUNTIME_CERTIFICATION_ENABLED", False)
        ),
        "eligible": not blockers,
        "blocker_codes": sorted(blockers),
        "binding_resolution": resolution,
        "binding_id": evidence["binding_id"],
        "promotion_id": evidence["promotion_id"],
        "parser": {
            "name": evidence["parser_name"],
            "version": evidence["parser_version"],
            "implementation_hash": evidence["parser_implementation_hash"],
            "output_schema_version": evidence["output_schema_version"],
        } if binding else None,
        "certification_policy": policy,
        "certification_policy_hash": policy_hash,
        "evidence_snapshot": evidence,
        "evidence_evaluated_at": now,
        "evidence_hash": evidence_hash,
        "certification_key": certification_key,
        "confirmation": confirmation,
        "writes_database": False,
        "writes_trades": False,
        "external_requests": 0,
        "runtime_activation": False,
    }


def certify_parser_runtime(
    db: Session,
    *,
    confirmation: str,
    binding_id: str | None = None,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    certified_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(
        getattr(settings_object, "CANONICAL_PARSER_RUNTIME_CERTIFICATION_ENABLED", False)
    ):
        raise CanonicalParserRuntimeCertificationError(
            "Runtime certification disabilitata.",
            code="CANONICAL_PARSER_RUNTIME_CERTIFICATION_DISABLED",
            status_code=409,
        )
    decision_time = _aware(certified_at)
    preview = preview_parser_runtime_certification(
        db,
        binding_id=binding_id,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=decision_time,
    )
    if str(confirmation or "").strip() != preview["confirmation"]:
        raise CanonicalParserRuntimeCertificationError(
            "Conferma runtime certification non valida o non aggiornata.",
            code="PARSER_RUNTIME_CERTIFICATION_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if not preview["eligible"]:
        raise CanonicalParserRuntimeCertificationError(
            "Runtime certification non idonea.",
            code="PARSER_RUNTIME_CERTIFICATION_NOT_ELIGIBLE",
            status_code=409,
        )
    existing = db.scalar(
        select(CanonicalParserRuntimeCertification).where(
            CanonicalParserRuntimeCertification.certification_key
            == preview["certification_key"]
        )
    )
    if existing is not None:
        result = _serialize(existing)
        result["created"] = False
        return result
    binding = db.scalar(
        select(CanonicalParserRuntimeBinding).where(
            CanonicalParserRuntimeBinding.binding_id == preview["binding_id"]
        )
    )
    if binding is None:
        raise CanonicalParserRuntimeCertificationError(
            "Binding runtime non trovato.",
            code="PARSER_RUNTIME_CERTIFICATION_BINDING_MISSING",
            status_code=409,
        )
    active = db.scalar(
        select(CanonicalParserRuntimeCertification).where(
            CanonicalParserRuntimeCertification.binding_db_id == binding.id,
            CanonicalParserRuntimeCertification.status == "CERTIFIED",
        )
    )
    if active is not None:
        raise CanonicalParserRuntimeCertificationError(
            "Esiste già una certificazione attiva per il binding.",
            code="PARSER_RUNTIME_CERTIFICATION_ACTIVE_EXISTS",
            status_code=409,
        )
    certification_id = str(uuid4())
    event_id = str(uuid4())
    actor = _actor(actor_label)
    event_payload = _event_payload(
        event_id=event_id,
        certification_id=certification_id,
        sequence=1,
        event_type="CERTIFIED",
        previous_status=None,
        new_status="CERTIFIED",
        actor_label=actor,
        reason=None,
        previous_event_hash=None,
        occurred_at=decision_time,
    )
    event_hash = calculate_payload_hash(event_payload)
    metrics = preview["evidence_snapshot"]["metrics"]
    validity_hours = preview["certification_policy"]["validity_hours"]
    certification = CanonicalParserRuntimeCertification(
        certification_id=certification_id,
        certification_key=preview["certification_key"],
        binding_db_id=binding.id,
        binding_id=binding.binding_id,
        promotion_id=binding.promotion_id,
        scope=binding.scope,
        channel=binding.channel,
        status="CERTIFIED",
        parser_name=binding.parser_name,
        parser_version=binding.parser_version,
        parser_implementation_hash=binding.parser_implementation_hash,
        output_schema_version=binding.output_schema_version,
        release_manifest_hash=binding.release_manifest_hash,
        certification_policy_version=CERTIFICATION_POLICY_VERSION,
        certification_policy_hash=preview["certification_policy_hash"],
        evidence_hash=preview["evidence_hash"],
        evidence_snapshot=sanitize_technical_metadata(preview["evidence_snapshot"]),
        admission_run_ids=[
            item["admission_id"]
            for item in preview["evidence_snapshot"]["admission_runs"]
        ],
        admission_run_count=metrics["admission_run_count"],
        total_processed_count=metrics["total_processed_count"],
        total_passed_count=metrics["total_passed_count"],
        total_failed_count=metrics["total_failed_count"],
        total_skipped_count=metrics["total_skipped_count"],
        pass_rate=Decimal(str(metrics["pass_rate"])),
        actor_label=actor,
        note=_note(note),
        certified_at=decision_time,
        expires_at=decision_time + timedelta(hours=validity_hours),
        revoked_at=None,
        revocation_reason=None,
        latest_event_sequence=1,
        latest_event_hash=event_hash,
        technical_metadata={
            "metadata_only": True,
            "runtime_activation": False,
            "external_requests": 0,
            "writes_trades": False,
        },
    )
    db.add(certification)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(CanonicalParserRuntimeCertification).where(
                CanonicalParserRuntimeCertification.certification_key
                == preview["certification_key"]
            )
        )
        if existing is not None:
            result = _serialize(existing)
            result["created"] = False
            return result
        raise
    db.add(
        CanonicalParserRuntimeCertificationEvent(
            event_id=event_id,
            certification_db_id=certification.id,
            sequence=1,
            event_type="CERTIFIED",
            previous_status=None,
            new_status="CERTIFIED",
            actor_label=actor,
            reason=None,
            event_payload=event_payload,
            previous_event_hash=None,
            event_hash=event_hash,
            occurred_at=decision_time,
        )
    )
    db.commit()
    db.refresh(certification)
    result = _serialize(certification)
    result["created"] = True
    return result


def revoke_parser_runtime_certification(
    db: Session,
    *,
    certification_id: str,
    confirmation: str,
    reason: str,
    actor_label: str | None = None,
    settings_object: Any = settings,
    revoked_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(
        getattr(settings_object, "CANONICAL_PARSER_RUNTIME_CERTIFICATION_ENABLED", False)
    ):
        raise CanonicalParserRuntimeCertificationError(
            "Runtime certification disabilitata.",
            code="CANONICAL_PARSER_RUNTIME_CERTIFICATION_DISABLED",
            status_code=409,
        )
    certification = db.scalar(
        select(CanonicalParserRuntimeCertification).where(
            CanonicalParserRuntimeCertification.certification_id
            == str(certification_id or "").strip()
        )
    )
    if certification is None:
        raise CanonicalParserRuntimeCertificationError(
            "Runtime certification non trovata.",
            code="PARSER_RUNTIME_CERTIFICATION_NOT_FOUND",
            status_code=404,
        )
    expected = f"{CERTIFICATION_REVOKE_PREFIX}:{certification.certification_id}"
    if str(confirmation or "").strip() != expected:
        raise CanonicalParserRuntimeCertificationError(
            "Conferma revoca non valida.",
            code="PARSER_RUNTIME_CERTIFICATION_REVOKE_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    sanitized_reason = _note(reason)
    if not sanitized_reason:
        raise CanonicalParserRuntimeCertificationError(
            "Motivazione revoca obbligatoria.",
            code="PARSER_RUNTIME_CERTIFICATION_REVOKE_REASON_REQUIRED",
        )
    chain_errors = _verify_event_chain(db, certification)
    if chain_errors:
        raise CanonicalParserRuntimeCertificationError(
            "Audit chain certificazione non integra.",
            code="PARSER_RUNTIME_CERTIFICATION_AUDIT_CHAIN_INVALID",
            status_code=409,
        )
    if certification.status == "REVOKED":
        result = _serialize(certification)
        result["updated"] = False
        return result
    decision_time = _aware(revoked_at)
    actor = _actor(actor_label)
    sequence = certification.latest_event_sequence + 1
    event_id = str(uuid4())
    payload = _event_payload(
        event_id=event_id,
        certification_id=certification.certification_id,
        sequence=sequence,
        event_type="REVOKED",
        previous_status=certification.status,
        new_status="REVOKED",
        actor_label=actor,
        reason=sanitized_reason,
        previous_event_hash=certification.latest_event_hash,
        occurred_at=decision_time,
    )
    event_hash = calculate_payload_hash(payload)
    db.add(
        CanonicalParserRuntimeCertificationEvent(
            event_id=event_id,
            certification_db_id=certification.id,
            sequence=sequence,
            event_type="REVOKED",
            previous_status=certification.status,
            new_status="REVOKED",
            actor_label=actor,
            reason=sanitized_reason,
            event_payload=payload,
            previous_event_hash=certification.latest_event_hash,
            event_hash=event_hash,
            occurred_at=decision_time,
        )
    )
    certification.status = "REVOKED"
    certification.revoked_at = decision_time
    certification.revocation_reason = sanitized_reason
    certification.latest_event_sequence = sequence
    certification.latest_event_hash = event_hash
    db.commit()
    db.refresh(certification)
    result = _serialize(certification)
    result["updated"] = True
    return result


def get_parser_runtime_certification(
    db: Session, certification_id: str
) -> dict[str, Any]:
    certification = db.scalar(
        select(CanonicalParserRuntimeCertification).where(
            CanonicalParserRuntimeCertification.certification_id
            == str(certification_id or "").strip()
        )
    )
    if certification is None:
        raise CanonicalParserRuntimeCertificationError(
            "Runtime certification non trovata.",
            code="PARSER_RUNTIME_CERTIFICATION_NOT_FOUND",
            status_code=404,
        )
    payload = _serialize(certification)
    payload["audit_chain_valid"] = not _verify_event_chain(db, certification)
    payload["revoke_confirmation"] = (
        f"{CERTIFICATION_REVOKE_PREFIX}:{certification.certification_id}"
    )
    return payload


def resolve_parser_runtime_certification(
    db: Session,
    *,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    resolution = resolve_shadow_parser_runtime(db, registry=registry)
    binding_id = resolution.get("binding_id")
    if not binding_id:
        return {
            "resolved": False,
            "status": "UNCERTIFIED",
            "reason_codes": sorted(
                set(resolution.get("reason_codes") or ["RUNTIME_BINDING_UNRESOLVED"])
            ),
            "binding_resolution": resolution,
            "runtime_activation": False,
        }
    certification = db.scalar(
        select(CanonicalParserRuntimeCertification)
        .where(
            CanonicalParserRuntimeCertification.binding_id == binding_id,
            CanonicalParserRuntimeCertification.status == "CERTIFIED",
        )
        .order_by(CanonicalParserRuntimeCertification.certified_at.desc())
    )
    if certification is None:
        return {
            "resolved": False,
            "status": "UNCERTIFIED",
            "reason_codes": ["ACTIVE_CERTIFICATION_MISSING"],
            "binding_resolution": resolution,
            "runtime_activation": False,
        }
    reasons = set(_verify_event_chain(db, certification))
    if _aware(certification.expires_at) <= now:
        reasons.add("CERTIFICATION_EXPIRED")
    if not resolution.get("resolved"):
        reasons.add("RUNTIME_BINDING_UNRESOLVED")
    parser = resolution.get("parser") or {}
    if certification.parser_implementation_hash != parser.get("implementation_hash"):
        reasons.add("CERTIFICATION_PARSER_HASH_DRIFT")
    if certification.output_schema_version != parser.get("output_schema_version"):
        reasons.add("CERTIFICATION_SCHEMA_DRIFT")
    binding = db.scalar(
        select(CanonicalParserRuntimeBinding).where(
            CanonicalParserRuntimeBinding.binding_id == binding_id
        )
    )
    if binding is None:
        reasons.add("CERTIFICATION_BINDING_MISSING")
    elif certification.release_manifest_hash != binding.release_manifest_hash:
        reasons.add("CERTIFICATION_RELEASE_DRIFT")
    status = "CERTIFIED" if not reasons else (
        "EXPIRED" if reasons == {"CERTIFICATION_EXPIRED"} else "DRIFTED"
    )
    return {
        "resolved": status == "CERTIFIED",
        "status": status,
        "reason_codes": sorted(reasons),
        "certification": _serialize(certification),
        "binding_resolution": resolution,
        "runtime_activation": False,
    }


def get_parser_runtime_certification_status(
    db: Session,
    *,
    settings_object: Any = settings,
) -> dict[str, Any]:
    counts = dict(
        db.execute(
            select(
                CanonicalParserRuntimeCertification.status,
                func.count(CanonicalParserRuntimeCertification.id),
            ).group_by(CanonicalParserRuntimeCertification.status)
        ).all()
    )
    return {
        "certification_enabled": bool(
            getattr(settings_object, "CANONICAL_PARSER_RUNTIME_CERTIFICATION_ENABLED", False)
        ),
        "policy_version": CERTIFICATION_POLICY_VERSION,
        "certification_count": int(sum(counts.values())),
        "status_counts": {
            status: int(counts.get(status, 0)) for status in ("CERTIFIED", "REVOKED")
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
            "operational_pipeline_consumer": False,
        },
    }
