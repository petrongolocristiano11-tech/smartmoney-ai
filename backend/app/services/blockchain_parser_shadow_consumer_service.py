from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserShadowConsumerResult,
    CanonicalParserShadowConsumerRun,
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
    ParserDefinition,
    ParserRegistry,
    ParserRegistryError,
    validate_parser_artifacts,
)
from backend.app.services.blockchain_parser_runtime_binding_service import (
    RUNTIME_CHANNEL,
    RUNTIME_SCOPE,
)
from backend.app.services.blockchain_parser_shadow_runtime_lease_service import (
    LEASE_CONSUMER,
    resolve_shadow_runtime_lease,
)

SHADOW_CONSUMER_POLICY_VERSION = "canonical-parser-shadow-consumer/1"
SHADOW_CONSUMER_CONFIRMATION_PREFIX = "RUN_CERTIFIED_SHADOW_DRY_RUN"
_MAX_ACTOR_LENGTH = 80
_MAX_NOTE_LENGTH = 500
_MAX_ERROR_LENGTH = 1000


class CanonicalParserShadowConsumerError(ValueError):
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
        "policy_version": SHADOW_CONSUMER_POLICY_VERSION,
        "scope": RUNTIME_SCOPE,
        "channel": RUNTIME_CHANNEL,
        "consumer": LEASE_CONSUMER,
        "max_sample_size": int(max_sample_size),
        "requires_active_certified_lease": True,
        "requires_consumer_permission": True,
        "requires_deterministic_parser": True,
        "double_execution_comparison": True,
        "requires_non_empty_output": True,
        "fail_closed_before_and_after_execution": True,
        "writes_shadow_tables_only": True,
        "writes_canonical_materialization": False,
        "writes_trades": False,
        "external_requests_allowed": False,
        "automatic_execution": False,
        "starts_workers": False,
        "live_execution": False,
    }


def _normalize_event_ids(raw_event_ids: list[int] | None) -> list[int]:
    values: set[int] = set()
    for raw_value in raw_event_ids or []:
        value = int(raw_value)
        if value <= 0:
            raise CanonicalParserShadowConsumerError(
                "Gli ID raw event devono essere positivi.",
                code="SHADOW_CONSUMER_RAW_EVENT_ID_INVALID",
            )
        values.add(value)
    return sorted(values)


def _resolve_definition(
    db: Session,
    *,
    lease_id: str | None,
    settings_object: Any,
    registry: ParserRegistry,
    evaluated_at: datetime,
) -> tuple[
    dict[str, Any],
    CanonicalParserShadowRuntimeLease | None,
    ParserDefinition | None,
    list[str],
]:
    resolution = resolve_shadow_runtime_lease(
        db,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=evaluated_at,
    )
    blockers: set[str] = set()
    if not resolution.get("resolved"):
        blockers.update(
            resolution.get("reason_codes") or ["SHADOW_LEASE_UNRESOLVED"]
        )
    if not resolution.get("consumer_authorized"):
        blockers.add("SHADOW_LEASE_CONSUMER_NOT_AUTHORIZED")
    lease_payload = resolution.get("lease") or {}
    resolved_lease_id = lease_payload.get("lease_id")
    if lease_id and str(lease_id).strip() != resolved_lease_id:
        blockers.add("SHADOW_LEASE_ID_MISMATCH")
    if not resolved_lease_id:
        return resolution, None, None, sorted(blockers)

    lease = db.scalar(
        select(CanonicalParserShadowRuntimeLease).where(
            CanonicalParserShadowRuntimeLease.lease_id == resolved_lease_id
        )
    )
    if lease is None:
        blockers.add("SHADOW_LEASE_MISSING")
        return resolution, None, None, sorted(blockers)

    try:
        definition = registry.get(lease.parser_name, lease.parser_version)
    except ParserRegistryError:
        blockers.add("PARSER_NOT_IN_REGISTRY")
        return resolution, lease, None, sorted(blockers)

    if not definition.deterministic:
        blockers.add("PARSER_NOT_DETERMINISTIC")
    if definition.performs_external_requests:
        blockers.add("PARSER_NETWORK_FORBIDDEN")
    if definition.writes_trades:
        blockers.add("PARSER_TRADE_WRITES_FORBIDDEN")
    if definition.implementation_hash != lease.parser_implementation_hash:
        blockers.add("PARSER_IMPLEMENTATION_HASH_DRIFT")
    if definition.output_schema_version != lease.output_schema_version:
        blockers.add("PARSER_SCHEMA_VERSION_DRIFT")
    if lease.scope != RUNTIME_SCOPE:
        blockers.add("SHADOW_LEASE_SCOPE_INVALID")
    if lease.channel != RUNTIME_CHANNEL:
        blockers.add("SHADOW_LEASE_CHANNEL_INVALID")
    if lease.consumer != LEASE_CONSUMER:
        blockers.add("SHADOW_LEASE_CONSUMER_INVALID")
    return resolution, lease, definition, sorted(blockers)


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
        incompatible = [
            int(event.id) for event in events if not definition.supports(event)
        ]
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
            .order_by(
                RawBlockchainEvent.first_seen_at.desc(),
                RawBlockchainEvent.id.desc(),
            )
            .limit(limit)
        )
    )
    return events, [], []


def preview_shadow_consumer_run(
    db: Session,
    *,
    lease_id: str | None = None,
    raw_event_ids: list[int] | None = None,
    limit: int = 10,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    decision_time = _aware(evaluated_at)
    max_sample = int(
        getattr(settings_object, "CANONICAL_PARSER_SHADOW_CONSUMER_MAX_SAMPLE_SIZE", 25)
    )
    requested_limit = int(limit)
    if requested_limit < 1 or requested_limit > max_sample:
        raise CanonicalParserShadowConsumerError(
            f"Il limite deve essere compreso tra 1 e {max_sample}.",
            code="SHADOW_CONSUMER_LIMIT_INVALID",
        )
    event_ids = _normalize_event_ids(raw_event_ids)
    if len(event_ids) > max_sample:
        raise CanonicalParserShadowConsumerError(
            "Troppi raw event richiesti per il consumer shadow.",
            code="SHADOW_CONSUMER_SAMPLE_TOO_LARGE",
        )

    resolution, lease, definition, blockers = _resolve_definition(
        db,
        lease_id=lease_id,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=decision_time,
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
        "lease_id": lease.lease_id if lease else None,
        "certification_id": lease.certification_id if lease else None,
        "binding_id": lease.binding_id if lease else None,
        "promotion_id": lease.promotion_id if lease else None,
        "lease_event_hash": lease.latest_event_hash if lease else None,
        "certification_event_hash": (
            lease.certification_event_hash if lease else None
        ),
        "release_manifest_hash": lease.release_manifest_hash if lease else None,
        "parser_name": definition.name if definition else None,
        "parser_version": definition.version if definition else None,
        "parser_implementation_hash": (
            definition.implementation_hash if definition else None
        ),
        "output_schema_version": (
            definition.output_schema_version if definition else None
        ),
        "consumer_policy_hash": policy_hash,
        "selection": selection,
    }
    run_key = calculate_payload_hash(manifest)
    confirmation = (
        f"{SHADOW_CONSUMER_CONFIRMATION_PREFIX}:"
        f"{manifest['lease_id'] or 'UNLEASED'}:{run_key[:12]}"
    )
    return {
        "dry_run": True,
        "consumer_enabled": bool(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_CONSUMER_ENABLED",
                False,
            )
        ),
        "eligible": not blockers,
        "blocker_codes": blockers,
        "lease_resolution": sanitize_technical_metadata(resolution),
        "lease_id": manifest["lease_id"],
        "certification_id": manifest["certification_id"],
        "binding_id": manifest["binding_id"],
        "promotion_id": manifest["promotion_id"],
        "parser": definition.as_dict() if definition else None,
        "requested_limit": requested_limit,
        "selected_count": len(events),
        "selected_raw_event_ids": selection["raw_event_ids"],
        "incompatible_raw_event_ids": incompatible,
        "missing_raw_event_ids": missing,
        "consumer_policy": policy,
        "consumer_policy_hash": policy_hash,
        "run_manifest": manifest,
        "run_key": run_key,
        "confirmation": confirmation,
        "writes_database": True,
        "writes_shadow_tables_only": True,
        "writes_canonical_materialization": False,
        "writes_trades": False,
        "external_requests": 0,
        "automatic_execution": False,
        "live_execution": False,
    }


def _serialize_result(result: CanonicalParserShadowConsumerResult) -> dict[str, Any]:
    return {
        "result_id": result.result_id,
        "raw_event_id": result.raw_event_id,
        "raw_payload_hash": result.raw_payload_hash,
        "status": result.status,
        "compatible": result.compatible,
        "deterministic": result.deterministic,
        "output_hash": result.output_hash,
        "verification_output_hash": result.verification_output_hash,
        "artifact_count": result.artifact_count,
        "shadow_artifacts": result.shadow_artifacts,
        "reason_codes": result.reason_codes,
        "error_message": result.error_message,
        "started_at": result.started_at,
        "completed_at": result.completed_at,
    }


def _serialize_run(
    db: Session,
    run: CanonicalParserShadowConsumerRun,
    *,
    created: bool | None = None,
    include_results: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "run_id": run.run_id,
        "run_key": run.run_key,
        "lease_id": run.lease_id,
        "certification_id": run.certification_id,
        "binding_id": run.binding_id,
        "promotion_id": run.promotion_id,
        "scope": run.scope,
        "channel": run.channel,
        "consumer": run.consumer,
        "status": run.status,
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
                select(CanonicalParserShadowConsumerResult)
                .where(
                    CanonicalParserShadowConsumerResult.consumer_run_db_id
                    == run.id
                )
                .order_by(CanonicalParserShadowConsumerResult.id.asc())
            )
        )
        payload["results"] = [_serialize_result(result) for result in results]
    if created is not None:
        payload["created"] = created
    return payload


def run_shadow_consumer_dry_run(
    db: Session,
    *,
    confirmation: str,
    lease_id: str | None = None,
    raw_event_ids: list[int] | None = None,
    limit: int = 10,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(
        getattr(
            settings_object,
            "CANONICAL_PARSER_SHADOW_CONSUMER_ENABLED",
            False,
        )
    ):
        raise CanonicalParserShadowConsumerError(
            "Certified shadow consumer disabilitato.",
            code="CANONICAL_PARSER_SHADOW_CONSUMER_DISABLED",
            status_code=409,
        )
    decision_time = _aware(started_at)
    preview = preview_shadow_consumer_run(
        db,
        lease_id=lease_id,
        raw_event_ids=raw_event_ids,
        limit=limit,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=decision_time,
    )
    if str(confirmation or "").strip() != preview["confirmation"]:
        raise CanonicalParserShadowConsumerError(
            "Conferma shadow consumer non valida o non aggiornata.",
            code="SHADOW_CONSUMER_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if not preview["eligible"]:
        raise CanonicalParserShadowConsumerError(
            "Certified shadow consumer non idoneo.",
            code="SHADOW_CONSUMER_NOT_ELIGIBLE",
            status_code=409,
        )

    existing = db.scalar(
        select(CanonicalParserShadowConsumerRun).where(
            CanonicalParserShadowConsumerRun.run_key == preview["run_key"]
        )
    )
    if existing is not None:
        return _serialize_run(db, existing, created=False)

    lease = db.scalar(
        select(CanonicalParserShadowRuntimeLease).where(
            CanonicalParserShadowRuntimeLease.lease_id == preview["lease_id"]
        )
    )
    if lease is None:
        raise CanonicalParserShadowConsumerError(
            "Shadow runtime lease non trovata.",
            code="SHADOW_CONSUMER_LEASE_MISSING",
            status_code=409,
        )
    definition = registry.get(lease.parser_name, lease.parser_version)
    events = list(
        db.scalars(
            select(RawBlockchainEvent)
            .where(RawBlockchainEvent.id.in_(preview["selected_raw_event_ids"]))
            .order_by(RawBlockchainEvent.id.asc())
        )
    )
    current_selection = {
        "raw_event_ids": [int(event.id) for event in events],
        "payload_hashes": [event.payload_hash for event in events],
        "explicit_selection": bool(raw_event_ids),
        "requested_limit": int(limit),
    }
    if current_selection != preview["run_manifest"]["selection"]:
        raise CanonicalParserShadowConsumerError(
            "La selezione raw event è cambiata dopo la preview.",
            code="SHADOW_CONSUMER_SELECTION_DRIFT",
            status_code=409,
        )

    run = CanonicalParserShadowConsumerRun(
        run_id=str(uuid4()),
        run_key=preview["run_key"],
        lease_db_id=lease.id,
        lease_id=lease.lease_id,
        certification_id=lease.certification_id,
        binding_id=lease.binding_id,
        promotion_id=lease.promotion_id,
        scope=lease.scope,
        channel=lease.channel,
        consumer=lease.consumer,
        status="RUNNING",
        parser_name=definition.name,
        parser_version=definition.version,
        parser_implementation_hash=definition.implementation_hash,
        output_schema_version=definition.output_schema_version,
        release_manifest_hash=lease.release_manifest_hash,
        lease_event_hash=lease.latest_event_hash,
        certification_event_hash=lease.certification_event_hash,
        consumer_policy_version=SHADOW_CONSUMER_POLICY_VERSION,
        consumer_policy_hash=preview["consumer_policy_hash"],
        requested_limit=preview["requested_limit"],
        selected_count=len(events),
        processed_count=0,
        passed_count=0,
        failed_count=0,
        skipped_count=0,
        artifact_count=0,
        actor_label=_actor(actor_label),
        note=_note(note),
        reason_codes=[],
        selection_snapshot=sanitize_technical_metadata(current_selection),
        metrics_snapshot={},
        technical_metadata={
            "manual_only": True,
            "shadow_only": True,
            "certified_lease_required": True,
            "external_requests": 0,
            "writes_shadow_tables_only": True,
            "writes_canonical_materialization": False,
            "writes_trades": False,
            "automatic_execution": False,
            "starts_workers": False,
            "live_execution": False,
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
            select(CanonicalParserShadowConsumerRun).where(
                CanonicalParserShadowConsumerRun.run_key == preview["run_key"]
            )
        )
        if existing is not None:
            return _serialize_run(db, existing, created=False)
        raise

    passed = failed = skipped = artifact_total = 0
    for event in events:
        item_started = _utc_now()
        status = "PASS"
        compatible = definition.supports(event)
        deterministic: bool | None = None
        output_hash: str | None = None
        verification_hash: str | None = None
        artifacts: list[dict[str, Any]] = []
        reasons: list[str] = []
        error_message: str | None = None
        try:
            if not compatible:
                status = "SKIPPED"
                reasons.append("EVENT_INCOMPATIBLE")
            elif event.payload_hash != calculate_payload_hash(event.raw_payload):
                status = "FAIL"
                reasons.append("RAW_PAYLOAD_HASH_MISMATCH")
            else:
                first = validate_parser_artifacts(definition, definition.parse(event))
                second = validate_parser_artifacts(definition, definition.parse(event))
                output_hash = calculate_payload_hash(first)
                verification_hash = calculate_payload_hash(second)
                deterministic = output_hash == verification_hash
                if not first:
                    status = "FAIL"
                    reasons.append("EMPTY_PARSER_OUTPUT")
                elif not deterministic:
                    status = "FAIL"
                    reasons.append("NON_DETERMINISTIC_OUTPUT")
                else:
                    artifacts = first
        except Exception as exception:  # parser boundary: persist sanitized failure
            status = "FAIL"
            reasons.append("PARSER_EXECUTION_FAILED")
            error_message = sanitize_error_message(
                exception, max_length=_MAX_ERROR_LENGTH
            )

        if status == "PASS":
            passed += 1
            artifact_total += len(artifacts)
        elif status == "SKIPPED":
            skipped += 1
        else:
            failed += 1
        item_completed = _utc_now()
        db.add(
            CanonicalParserShadowConsumerResult(
                result_id=str(uuid4()),
                consumer_run_db_id=run.id,
                raw_event_id=event.id,
                raw_payload_hash=event.payload_hash,
                status=status,
                compatible=compatible,
                deterministic=deterministic,
                output_hash=output_hash,
                verification_output_hash=verification_hash,
                artifact_count=len(artifacts),
                shadow_artifacts=artifacts,
                reason_codes=sorted(set(reasons)),
                error_message=error_message,
                started_at=item_started,
                completed_at=item_completed,
            )
        )

    final_time = _aware(completed_at)
    final_resolution = resolve_shadow_runtime_lease(
        db,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=final_time,
    )
    run_reasons: set[str] = set()
    final_lease = final_resolution.get("lease") or {}
    if not final_resolution.get("resolved") or not final_resolution.get(
        "consumer_authorized"
    ):
        run_reasons.add("SHADOW_LEASE_INTERLOCK_TRIPPED")
        run_reasons.update(final_resolution.get("reason_codes") or [])
    if final_lease.get("lease_id") != run.lease_id:
        run_reasons.add("SHADOW_LEASE_ID_DRIFT")
    if final_lease.get("latest_event_hash") != run.lease_event_hash:
        run_reasons.add("SHADOW_LEASE_EVENT_HASH_DRIFT")
    if final_lease.get("parser_implementation_hash") != run.parser_implementation_hash:
        run_reasons.add("SHADOW_LEASE_PARSER_HASH_DRIFT")
    if final_lease.get("release_manifest_hash") != run.release_manifest_hash:
        run_reasons.add("SHADOW_LEASE_RELEASE_HASH_DRIFT")

    processed = len(events)
    if run_reasons:
        status = "FAILED"
    elif failed == 0 and skipped == 0 and passed == processed and processed > 0:
        status = "PASSED"
    elif passed > 0:
        status = "PARTIAL"
    else:
        status = "FAILED"

    run.status = status
    run.processed_count = processed
    run.passed_count = passed
    run.failed_count = failed
    run.skipped_count = skipped
    run.artifact_count = artifact_total
    run.reason_codes = sorted(run_reasons)
    run.metrics_snapshot = {
        "selected_count": len(events),
        "processed_count": processed,
        "passed_count": passed,
        "failed_count": failed,
        "skipped_count": skipped,
        "artifact_count": artifact_total,
        "pass_rate": round(passed / processed, 6) if processed else 0.0,
        "lease_interlock_healthy": not run_reasons,
    }
    run.technical_metadata = {
        **(run.technical_metadata or {}),
        "final_lease_resolution": sanitize_technical_metadata(final_resolution),
    }
    run.completed_at = final_time
    db.commit()
    db.refresh(run)
    return _serialize_run(db, run, created=True)


def get_shadow_consumer_run(db: Session, run_id: str) -> dict[str, Any]:
    run = db.scalar(
        select(CanonicalParserShadowConsumerRun).where(
            CanonicalParserShadowConsumerRun.run_id == str(run_id or "").strip()
        )
    )
    if run is None:
        raise CanonicalParserShadowConsumerError(
            "Shadow consumer run non trovato.",
            code="SHADOW_CONSUMER_RUN_NOT_FOUND",
            status_code=404,
        )
    return _serialize_run(db, run)


def get_shadow_consumer_status(
    db: Session,
    *,
    settings_object: Any = settings,
) -> dict[str, Any]:
    counts = dict(
        db.execute(
            select(
                CanonicalParserShadowConsumerRun.status,
                func.count(CanonicalParserShadowConsumerRun.id),
            ).group_by(CanonicalParserShadowConsumerRun.status)
        ).all()
    )
    max_sample = int(
        getattr(settings_object, "CANONICAL_PARSER_SHADOW_CONSUMER_MAX_SAMPLE_SIZE", 25)
    )
    return {
        "consumer_enabled": bool(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_CONSUMER_ENABLED",
                False,
            )
        ),
        "policy_version": SHADOW_CONSUMER_POLICY_VERSION,
        "consumer": LEASE_CONSUMER,
        "run_count": int(sum(counts.values())),
        "status_counts": {
            status: int(counts.get(status, 0))
            for status in ("RUNNING", "PASSED", "PARTIAL", "FAILED")
        },
        "policy": _policy_snapshot(max_sample_size=max_sample),
        "operational_guards": {
            "manual_consumer_connected": True,
            "automatic_consumer_connected": False,
            "certified_lease_required": True,
            "external_requests": 0,
            "writes_shadow_tables_only": True,
            "writes_canonical_materialization": False,
            "writes_trades": False,
            "starts_workers": False,
            "changes_runtime_flags": False,
            "live_execution": False,
            "operational_pipeline_consumer": False,
        },
    }
