from __future__ import annotations

from datetime import datetime, timezone
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
    RawBlockchainEvent,
)
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    sanitize_error_message,
    sanitize_technical_metadata,
)
from backend.app.services.blockchain_parser_registry_service import (
    DEFAULT_PARSER_REGISTRY,
    ParserDefinition,
    ParserRegistry,
    ParserRegistryError,
    validate_parser_artifacts,
)
from backend.app.services.blockchain_parser_runtime_binding_service import (
    RUNTIME_CHANNEL,
    RUNTIME_SCOPE,
    resolve_shadow_parser_runtime,
)


ADMISSION_POLICY_VERSION = "canonical-parser-runtime-admission/1"
ADMISSION_CONFIRMATION_PREFIX = "RUN_PARSER_RUNTIME_ADMISSION"
_MAX_ACTOR_LENGTH = 80
_MAX_NOTE_LENGTH = 500
_MAX_ERROR_LENGTH = 1000


class CanonicalParserRuntimeAdmissionError(ValueError):
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


def _policy_snapshot(*, max_sample_size: int) -> dict[str, Any]:
    return {
        "policy_version": ADMISSION_POLICY_VERSION,
        "scope": RUNTIME_SCOPE,
        "channel": RUNTIME_CHANNEL,
        "max_sample_size": int(max_sample_size),
        "requires_healthy_binding": True,
        "requires_deterministic_parser": True,
        "requires_non_empty_output": True,
        "double_execution_comparison": True,
        "external_requests_allowed": False,
        "trade_writes_allowed": False,
        "automatic_execution": False,
        "operational_pipeline_consumer": False,
    }


def _normalize_event_ids(raw_event_ids: list[int] | None) -> list[int]:
    values: set[int] = set()
    for raw_value in raw_event_ids or []:
        value = int(raw_value)
        if value <= 0:
            raise CanonicalParserRuntimeAdmissionError(
                "Gli ID raw event devono essere positivi.",
                code="PARSER_ADMISSION_RAW_EVENT_ID_INVALID",
            )
        values.add(value)
    return sorted(values)


def _resolve_definition(
    db: Session,
    *,
    binding_id: str | None,
    registry: ParserRegistry,
) -> tuple[dict[str, Any], CanonicalParserRuntimeBinding | None, ParserDefinition | None, list[str]]:
    resolution = resolve_shadow_parser_runtime(db, registry=registry)
    blockers: set[str] = set()
    if not resolution.get("resolved"):
        blockers.update(resolution.get("reason_codes") or ["RUNTIME_BINDING_UNRESOLVED"])
        return resolution, None, None, sorted(blockers)
    if binding_id and str(binding_id).strip() != resolution.get("binding_id"):
        blockers.add("RUNTIME_BINDING_ID_MISMATCH")
    binding = db.scalar(
        select(CanonicalParserRuntimeBinding).where(
            CanonicalParserRuntimeBinding.binding_id == resolution["binding_id"]
        )
    )
    if binding is None:
        blockers.add("RUNTIME_BINDING_MISSING")
        return resolution, None, None, sorted(blockers)
    try:
        definition = registry.get(binding.parser_name, binding.parser_version)
    except ParserRegistryError:
        blockers.add("PARSER_NOT_IN_REGISTRY")
        return resolution, binding, None, sorted(blockers)
    if not definition.deterministic:
        blockers.add("PARSER_NOT_DETERMINISTIC")
    if definition.performs_external_requests:
        blockers.add("PARSER_NETWORK_FORBIDDEN")
    if definition.writes_trades:
        blockers.add("PARSER_TRADE_WRITES_FORBIDDEN")
    if definition.implementation_hash != binding.parser_implementation_hash:
        blockers.add("PARSER_IMPLEMENTATION_HASH_DRIFT")
    if definition.output_schema_version != binding.output_schema_version:
        blockers.add("PARSER_SCHEMA_VERSION_DRIFT")
    return resolution, binding, definition, sorted(blockers)


def _select_events(
    db: Session,
    *,
    definition: ParserDefinition | None,
    raw_event_ids: list[int],
    limit: int,
) -> tuple[list[RawBlockchainEvent], list[int], list[int]]:
    if definition is None:
        return [], [], raw_event_ids
    if raw_event_ids:
        events = list(
            db.scalars(
                select(RawBlockchainEvent)
                .where(RawBlockchainEvent.id.in_(raw_event_ids))
                .order_by(RawBlockchainEvent.id.asc())
            )
        )
        found = {int(event.id) for event in events}
        missing = sorted(set(raw_event_ids) - found)
        incompatible = [int(event.id) for event in events if not definition.supports(event)]
        return events, incompatible, missing
    events = list(
        db.scalars(
            select(RawBlockchainEvent)
            .where(
                func.lower(RawBlockchainEvent.provider).in_(
                    sorted(definition.supported_providers)
                ),
                RawBlockchainEvent.event_type.in_(
                    sorted(definition.supported_event_types)
                ),
            )
            .order_by(RawBlockchainEvent.first_seen_at.desc(), RawBlockchainEvent.id.desc())
            .limit(limit)
        )
    )
    return events, [], []


def preview_parser_runtime_admission(
    db: Session,
    *,
    binding_id: str | None = None,
    raw_event_ids: list[int] | None = None,
    limit: int = 10,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
) -> dict[str, Any]:
    max_sample = int(
        getattr(settings_object, "CANONICAL_PARSER_RUNTIME_ADMISSION_MAX_SAMPLE_SIZE", 25)
    )
    requested_limit = int(limit)
    if requested_limit < 1 or requested_limit > max_sample:
        raise CanonicalParserRuntimeAdmissionError(
            f"Il limite deve essere compreso tra 1 e {max_sample}.",
            code="PARSER_ADMISSION_LIMIT_INVALID",
        )
    event_ids = _normalize_event_ids(raw_event_ids)
    if len(event_ids) > max_sample:
        raise CanonicalParserRuntimeAdmissionError(
            "Troppi raw event richiesti per il canary.",
            code="PARSER_ADMISSION_SAMPLE_TOO_LARGE",
        )
    resolution, binding, definition, blockers = _resolve_definition(
        db, binding_id=binding_id, registry=registry
    )
    events, incompatible, missing = _select_events(
        db,
        definition=definition,
        raw_event_ids=event_ids,
        limit=requested_limit,
    )
    if missing:
        blockers.append("RAW_EVENTS_NOT_FOUND")
    if incompatible:
        blockers.append("RAW_EVENTS_INCOMPATIBLE")
    if not events:
        blockers.append("NO_COMPATIBLE_RAW_EVENTS")
    blockers = sorted(set(blockers))
    policy = _policy_snapshot(max_sample_size=max_sample)
    policy_hash = calculate_payload_hash(policy)
    selection = {
        "raw_event_ids": [int(event.id) for event in events],
        "payload_hashes": [event.payload_hash for event in events],
        "explicit_selection": bool(event_ids),
        "requested_limit": requested_limit,
    }
    manifest = {
        "binding_id": binding.binding_id if binding else None,
        "promotion_id": binding.promotion_id if binding else None,
        "binding_event_hash": binding.latest_event_hash if binding else None,
        "release_manifest_hash": binding.release_manifest_hash if binding else None,
        "parser_name": definition.name if definition else None,
        "parser_version": definition.version if definition else None,
        "parser_implementation_hash": (
            definition.implementation_hash if definition else None
        ),
        "output_schema_version": definition.output_schema_version if definition else None,
        "admission_policy_hash": policy_hash,
        "selection": selection,
    }
    admission_key = calculate_payload_hash(manifest)
    confirmation = (
        f"{ADMISSION_CONFIRMATION_PREFIX}:"
        f"{manifest['binding_id'] or 'UNBOUND'}:{admission_key[:12]}"
    )
    return {
        "dry_run": True,
        "admission_enabled": bool(
            getattr(settings_object, "CANONICAL_PARSER_RUNTIME_ADMISSION_ENABLED", False)
        ),
        "eligible": not blockers,
        "blocker_codes": blockers,
        "binding_resolution": resolution,
        "binding_id": manifest["binding_id"],
        "promotion_id": manifest["promotion_id"],
        "parser": definition.as_dict() if definition else None,
        "requested_limit": requested_limit,
        "selected_count": len(events),
        "selected_raw_event_ids": selection["raw_event_ids"],
        "incompatible_raw_event_ids": incompatible,
        "missing_raw_event_ids": missing,
        "admission_policy": policy,
        "admission_policy_hash": policy_hash,
        "admission_manifest": manifest,
        "admission_key": admission_key,
        "confirmation": confirmation,
        "writes_database": False,
        "writes_trades": False,
        "external_requests": 0,
        "automatic_execution": False,
    }


def _result_summary(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "artifact_type": item["artifact_type"],
            "artifact_index": item["artifact_index"],
            "schema_version": item["schema_version"],
            "payload_hash": item["payload_hash"],
        }
        for item in artifacts
    ]


def _serialize_result(result: CanonicalParserAdmissionResult) -> dict[str, Any]:
    return {
        "result_id": result.result_id,
        "raw_event_id": result.raw_event_id,
        "status": result.status,
        "compatible": result.compatible,
        "deterministic": result.deterministic,
        "first_output_hash": result.first_output_hash,
        "second_output_hash": result.second_output_hash,
        "artifact_count": result.artifact_count,
        "artifact_summary": result.artifact_summary,
        "reason_codes": result.reason_codes,
        "error_message": result.error_message,
        "started_at": result.started_at,
        "completed_at": result.completed_at,
    }


def _serialize_run(
    db: Session,
    run: CanonicalParserAdmissionRun,
    *,
    created: bool | None = None,
    include_results: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "admission_id": run.admission_id,
        "admission_key": run.admission_key,
        "binding_id": run.binding_id,
        "promotion_id": run.promotion_id,
        "scope": run.scope,
        "channel": run.channel,
        "status": run.status,
        "parser_name": run.parser_name,
        "parser_version": run.parser_version,
        "parser_implementation_hash": run.parser_implementation_hash,
        "output_schema_version": run.output_schema_version,
        "binding_event_hash": run.binding_event_hash,
        "release_manifest_hash": run.release_manifest_hash,
        "admission_policy_version": run.admission_policy_version,
        "admission_policy_hash": run.admission_policy_hash,
        "requested_limit": run.requested_limit,
        "selected_count": run.selected_count,
        "processed_count": run.processed_count,
        "passed_count": run.passed_count,
        "failed_count": run.failed_count,
        "skipped_count": run.skipped_count,
        "actor_label": run.actor_label,
        "note": run.note,
        "reason_codes": run.reason_codes,
        "selection_snapshot": run.selection_snapshot,
        "metrics_snapshot": run.metrics_snapshot,
        "technical_metadata": run.technical_metadata,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
    }
    if include_results:
        results = list(
            db.scalars(
                select(CanonicalParserAdmissionResult)
                .where(CanonicalParserAdmissionResult.admission_run_db_id == run.id)
                .order_by(CanonicalParserAdmissionResult.id.asc())
            )
        )
        payload["results"] = [_serialize_result(result) for result in results]
    if created is not None:
        payload["created"] = created
    return payload


def run_parser_runtime_admission(
    db: Session,
    *,
    confirmation: str,
    binding_id: str | None = None,
    raw_event_ids: list[int] | None = None,
    limit: int = 10,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    started_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(
        getattr(settings_object, "CANONICAL_PARSER_RUNTIME_ADMISSION_ENABLED", False)
    ):
        raise CanonicalParserRuntimeAdmissionError(
            "Runtime admission canary disabilitato.",
            code="CANONICAL_PARSER_RUNTIME_ADMISSION_DISABLED",
            status_code=409,
        )
    preview = preview_parser_runtime_admission(
        db,
        binding_id=binding_id,
        raw_event_ids=raw_event_ids,
        limit=limit,
        settings_object=settings_object,
        registry=registry,
    )
    if str(confirmation or "").strip() != preview["confirmation"]:
        raise CanonicalParserRuntimeAdmissionError(
            "Conferma runtime admission non valida o non aggiornata.",
            code="PARSER_ADMISSION_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if not preview["eligible"]:
        raise CanonicalParserRuntimeAdmissionError(
            "Runtime admission non idoneo.",
            code="PARSER_ADMISSION_NOT_ELIGIBLE",
            status_code=409,
        )
    existing = db.scalar(
        select(CanonicalParserAdmissionRun).where(
            CanonicalParserAdmissionRun.admission_key == preview["admission_key"]
        )
    )
    if existing is not None:
        return _serialize_run(db, existing, created=False)

    binding = db.scalar(
        select(CanonicalParserRuntimeBinding).where(
            CanonicalParserRuntimeBinding.binding_id == preview["binding_id"]
        )
    )
    if binding is None:
        raise CanonicalParserRuntimeAdmissionError(
            "Binding runtime non trovato.",
            code="PARSER_ADMISSION_BINDING_MISSING",
            status_code=409,
        )
    definition = registry.get(binding.parser_name, binding.parser_version)
    events = list(
        db.scalars(
            select(RawBlockchainEvent)
            .where(RawBlockchainEvent.id.in_(preview["selected_raw_event_ids"]))
            .order_by(RawBlockchainEvent.id.asc())
        )
    )
    decision_time = _aware(started_at)
    run = CanonicalParserAdmissionRun(
        admission_id=str(uuid4()),
        admission_key=preview["admission_key"],
        binding_db_id=binding.id,
        binding_id=binding.binding_id,
        promotion_id=binding.promotion_id,
        scope=binding.scope,
        channel=binding.channel,
        status="RUNNING",
        parser_name=definition.name,
        parser_version=definition.version,
        parser_implementation_hash=definition.implementation_hash,
        output_schema_version=definition.output_schema_version,
        binding_event_hash=binding.latest_event_hash,
        release_manifest_hash=binding.release_manifest_hash,
        admission_policy_version=ADMISSION_POLICY_VERSION,
        admission_policy_hash=preview["admission_policy_hash"],
        requested_limit=preview["requested_limit"],
        selected_count=len(events),
        processed_count=0,
        passed_count=0,
        failed_count=0,
        skipped_count=0,
        actor_label=_actor(actor_label),
        note=_note(note),
        reason_codes=[],
        selection_snapshot=sanitize_technical_metadata(
            preview["admission_manifest"]["selection"]
        ),
        metrics_snapshot={},
        technical_metadata={
            "manual_only": True,
            "shadow_only": True,
            "external_requests": 0,
            "writes_trades": False,
            "operational_pipeline_consumer": False,
        },
        started_at=decision_time,
        completed_at=None,
    )
    db.add(run)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(CanonicalParserAdmissionRun).where(
                CanonicalParserAdmissionRun.admission_key == preview["admission_key"]
            )
        )
        if existing is not None:
            return _serialize_run(db, existing, created=False)
        raise

    total_artifacts = 0
    for event in events:
        item_started = _utc_now()
        status = "PASS"
        deterministic: bool | None = None
        first_hash = None
        second_hash = None
        summary: list[dict[str, Any]] = []
        reasons: list[str] = []
        error_message = None
        compatible = definition.supports(event)
        try:
            if not compatible:
                status = "SKIPPED"
                reasons.append("EVENT_INCOMPATIBLE")
            else:
                first = validate_parser_artifacts(definition, definition.parse(event))
                second = validate_parser_artifacts(definition, definition.parse(event))
                first_hash = calculate_payload_hash(first)
                second_hash = calculate_payload_hash(second)
                deterministic = first_hash == second_hash
                summary = _result_summary(first)
                if not first:
                    status = "FAIL"
                    reasons.append("EMPTY_PARSER_OUTPUT")
                elif not deterministic:
                    status = "FAIL"
                    reasons.append("NON_DETERMINISTIC_OUTPUT")
                else:
                    total_artifacts += len(first)
        except Exception as exception:  # parser boundary: persist sanitized failure
            status = "FAIL"
            reasons.append("PARSER_EXECUTION_FAILED")
            error_message = sanitize_error_message(
                exception, max_length=_MAX_ERROR_LENGTH
            )
        item_completed = _utc_now()
        db.add(
            CanonicalParserAdmissionResult(
                result_id=str(uuid4()),
                admission_run_db_id=run.id,
                raw_event_id=event.id,
                status=status,
                compatible=compatible,
                deterministic=deterministic,
                first_output_hash=first_hash,
                second_output_hash=second_hash,
                artifact_count=len(summary),
                artifact_summary=summary,
                reason_codes=sorted(set(reasons)),
                error_message=error_message,
                started_at=item_started,
                completed_at=item_completed,
            )
        )
        run.processed_count += 1
        if status == "PASS":
            run.passed_count += 1
        elif status == "FAIL":
            run.failed_count += 1
        else:
            run.skipped_count += 1

    end_resolution = resolve_shadow_parser_runtime(db, registry=registry)
    run_reasons: set[str] = set()
    if (
        not end_resolution.get("resolved")
        or end_resolution.get("binding_id") != run.binding_id
        or (end_resolution.get("parser") or {}).get("implementation_hash")
        != run.parser_implementation_hash
        or binding.latest_event_hash != run.binding_event_hash
    ):
        run_reasons.add("RUNTIME_BINDING_DRIFT_DETECTED")

    if run_reasons:
        final_status = "FAILED"
    elif run.failed_count == 0 and run.skipped_count == 0 and run.passed_count > 0:
        final_status = "PASSED"
    elif run.passed_count > 0:
        final_status = "PARTIAL"
    else:
        final_status = "FAILED"
    run.status = final_status
    run.reason_codes = sorted(run_reasons)
    run.completed_at = _utc_now()
    run.metrics_snapshot = {
        "selected_count": run.selected_count,
        "processed_count": run.processed_count,
        "passed_count": run.passed_count,
        "failed_count": run.failed_count,
        "skipped_count": run.skipped_count,
        "artifact_count": total_artifacts,
        "deterministic_pass_rate": (
            round((run.passed_count / run.processed_count) * 100, 4)
            if run.processed_count else 0.0
        ),
        "binding_healthy_at_start": True,
        "binding_healthy_at_end": not bool(run_reasons),
    }
    db.commit()
    db.refresh(run)
    return _serialize_run(db, run, created=True)


def get_parser_runtime_admission_run(
    db: Session, admission_id: str
) -> dict[str, Any]:
    run = db.scalar(
        select(CanonicalParserAdmissionRun).where(
            CanonicalParserAdmissionRun.admission_id == str(admission_id or "").strip()
        )
    )
    if run is None:
        raise CanonicalParserRuntimeAdmissionError(
            "Runtime admission run non trovato.",
            code="PARSER_ADMISSION_RUN_NOT_FOUND",
            status_code=404,
        )
    return _serialize_run(db, run)


def get_parser_runtime_admission_status(
    db: Session,
    *,
    settings_object: Any = settings,
) -> dict[str, Any]:
    counts = dict(
        db.execute(
            select(
                CanonicalParserAdmissionRun.status,
                func.count(CanonicalParserAdmissionRun.id),
            ).group_by(CanonicalParserAdmissionRun.status)
        ).all()
    )
    return {
        "admission_enabled": bool(
            getattr(settings_object, "CANONICAL_PARSER_RUNTIME_ADMISSION_ENABLED", False)
        ),
        "policy_version": ADMISSION_POLICY_VERSION,
        "max_sample_size": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_RUNTIME_ADMISSION_MAX_SAMPLE_SIZE",
                25,
            )
        ),
        "run_count": int(sum(counts.values())),
        "status_counts": {
            status: int(counts.get(status, 0))
            for status in ("RUNNING", "PASSED", "PARTIAL", "FAILED")
        },
        "operational_guards": {
            "manual_only": True,
            "shadow_only": True,
            "external_requests": 0,
            "writes_trades": False,
            "starts_workers": False,
            "changes_runtime_flags": False,
            "automatic_execution": False,
            "operational_pipeline_consumer": False,
        },
    }
