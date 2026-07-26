from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserShadowAutomationPermit,
    CanonicalParserShadowExecutionTicket,
    CanonicalParserShadowTicketExecutionResult,
    CanonicalParserShadowTicketExecutionRun,
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
from backend.app.services.blockchain_parser_shadow_automation_permit_service import (
    _append_terminal_event as _append_permit_terminal_event,
)
from backend.app.services.blockchain_parser_shadow_execution_ticket_service import (
    _append_terminal_event as _append_ticket_terminal_event,
    resolve_shadow_execution_ticket,
)

TICKET_EXECUTION_POLICY_VERSION = "canonical-parser-shadow-ticket-execution/1"
TICKET_EXECUTION_CONFIRMATION_PREFIX = "RUN_RESERVED_SHADOW_EXECUTION_TICKET"
TICKET_EXECUTION_EXECUTOR = "CERTIFIED_SHADOW_TICKET_EXECUTION"
TICKET_EXECUTION_SCOPE = "SHADOW_ONLY"
TICKET_EXECUTION_CHANNEL = "CANONICAL_SHADOW"
TICKET_EXECUTION_CONSUMER = "CERTIFIED_SHADOW_AUTOMATION"
_MAX_ACTOR_LENGTH = 80
_MAX_NOTE_LENGTH = 500
_MAX_ERROR_LENGTH = 1000


class CanonicalParserShadowTicketExecutionError(ValueError):
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
        "policy_version": TICKET_EXECUTION_POLICY_VERSION,
        "executor": TICKET_EXECUTION_EXECUTOR,
        "scope": TICKET_EXECUTION_SCOPE,
        "channel": TICKET_EXECUTION_CHANNEL,
        "consumer": TICKET_EXECUTION_CONSUMER,
        "maximum_sample_size": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_TICKET_EXECUTION_MAX_SAMPLE_SIZE",
                25,
            )
        ),
        "requires_ready_authorized_ticket": True,
        "selection_bounded_by_ticket_reservation": True,
        "requires_deterministic_parser": True,
        "double_execution_comparison": True,
        "requires_non_empty_output": True,
        "raw_payload_hash_verification": True,
        "fail_closed_before_and_after_execution": True,
        "atomic_budget_settlement": True,
        "consume_one_run_per_execution": True,
        "consume_processed_events": True,
        "release_unused_event_reservation": True,
        "writes_shadow_tables_only": True,
        "writes_canonical_materialization": False,
        "writes_trades": False,
        "external_requests_allowed": False,
        "manual_execution_only": True,
        "scheduler_connected": False,
        "worker_connected": False,
        "automatic_execution": False,
        "paper_execution": False,
        "live_execution": False,
    }


def _normalize_event_ids(raw_event_ids: list[int] | None) -> list[int]:
    values: set[int] = set()
    for raw_value in raw_event_ids or []:
        value = int(raw_value)
        if value <= 0:
            raise CanonicalParserShadowTicketExecutionError(
                "Gli ID raw event devono essere positivi.",
                code="SHADOW_TICKET_EXECUTION_RAW_EVENT_ID_INVALID",
            )
        values.add(value)
    return sorted(values)


def _ticket_from_resolution(
    db: Session,
    resolution: dict[str, Any],
    ticket_id: str | None,
) -> CanonicalParserShadowExecutionTicket | None:
    payload = resolution.get("ticket") or {}
    resolved_id = payload.get("ticket_id")
    target_id = ticket_id or resolved_id
    if not target_id:
        return None
    if ticket_id and resolved_id and ticket_id != resolved_id:
        return None
    return db.scalar(
        select(CanonicalParserShadowExecutionTicket).where(
            CanonicalParserShadowExecutionTicket.ticket_id == target_id
        )
    )


def _resolve_definition(
    db: Session,
    *,
    ticket_id: str | None,
    settings_object: Any,
    registry: ParserRegistry,
    evaluated_at: datetime,
) -> tuple[
    dict[str, Any],
    CanonicalParserShadowExecutionTicket | None,
    ParserDefinition | None,
    list[str],
]:
    resolution = resolve_shadow_execution_ticket(
        db,
        ticket_id=ticket_id,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=evaluated_at,
    )
    blockers: set[str] = set()
    if not resolution.get("resolved"):
        blockers.update(
            resolution.get("reason_codes") or ["SHADOW_EXECUTION_TICKET_UNRESOLVED"]
        )
    if not resolution.get("ticket_authorized"):
        blockers.add("SHADOW_EXECUTION_TICKET_NOT_AUTHORIZED")
    if resolution.get("status") != "READY":
        blockers.add("SHADOW_EXECUTION_TICKET_NOT_READY")

    ticket = _ticket_from_resolution(db, resolution, ticket_id)
    if ticket is None:
        blockers.add("SHADOW_EXECUTION_TICKET_MISSING_OR_MISMATCHED")
        return resolution, None, None, sorted(blockers)

    try:
        definition = registry.get(ticket.parser_name, ticket.parser_version)
    except ParserRegistryError:
        blockers.add("PARSER_NOT_IN_REGISTRY")
        return resolution, ticket, None, sorted(blockers)

    if not definition.deterministic:
        blockers.add("PARSER_NOT_DETERMINISTIC")
    if definition.performs_external_requests:
        blockers.add("PARSER_NETWORK_FORBIDDEN")
    if definition.writes_trades:
        blockers.add("PARSER_TRADE_WRITES_FORBIDDEN")
    if definition.implementation_hash != ticket.parser_implementation_hash:
        blockers.add("PARSER_IMPLEMENTATION_HASH_DRIFT")
    if definition.output_schema_version != ticket.output_schema_version:
        blockers.add("PARSER_SCHEMA_VERSION_DRIFT")
    if ticket.scope != TICKET_EXECUTION_SCOPE:
        blockers.add("SHADOW_EXECUTION_TICKET_SCOPE_INVALID")
    if ticket.channel != TICKET_EXECUTION_CHANNEL:
        blockers.add("SHADOW_EXECUTION_TICKET_CHANNEL_INVALID")
    if ticket.consumer != TICKET_EXECUTION_CONSUMER:
        blockers.add("SHADOW_EXECUTION_TICKET_CONSUMER_INVALID")
    return resolution, ticket, definition, sorted(blockers)


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


def preview_shadow_ticket_execution(
    db: Session,
    *,
    ticket_id: str | None = None,
    raw_event_ids: list[int] | None = None,
    limit: int = 10,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    decision_time = _aware(evaluated_at)
    max_sample = int(
        getattr(
            settings_object,
            "CANONICAL_PARSER_SHADOW_TICKET_EXECUTION_MAX_SAMPLE_SIZE",
            25,
        )
    )
    requested_limit = int(limit)
    if requested_limit < 1 or requested_limit > max_sample:
        raise CanonicalParserShadowTicketExecutionError(
            f"Il limite deve essere compreso tra 1 e {max_sample}.",
            code="SHADOW_TICKET_EXECUTION_LIMIT_INVALID",
        )
    event_ids = _normalize_event_ids(raw_event_ids)
    if len(event_ids) > max_sample:
        raise CanonicalParserShadowTicketExecutionError(
            "Troppi raw event richiesti per l'esecuzione ticket-bound.",
            code="SHADOW_TICKET_EXECUTION_SAMPLE_TOO_LARGE",
        )

    resolution, ticket, definition, blockers = _resolve_definition(
        db,
        ticket_id=ticket_id,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=decision_time,
    )
    reservation = int(ticket.event_reservation) if ticket is not None else 0
    if requested_limit > reservation and ticket is not None:
        blockers.append("SHADOW_TICKET_EXECUTION_LIMIT_EXCEEDS_RESERVATION")
    if len(event_ids) > reservation and ticket is not None:
        blockers.append("SHADOW_TICKET_EXECUTION_SELECTION_EXCEEDS_RESERVATION")

    bounded_limit = min(requested_limit, reservation) if reservation else requested_limit
    events, incompatible, missing = _select_events(
        db,
        definition=definition,
        raw_event_ids=event_ids,
        limit=bounded_limit,
    )
    if missing:
        blockers.append("RAW_EVENTS_NOT_FOUND")
    if incompatible:
        blockers.append("RAW_EVENTS_INCOMPATIBLE")
    if not events:
        blockers.append("NO_COMPATIBLE_RAW_EVENTS")
    if ticket is not None and len(events) > reservation:
        blockers.append("SHADOW_TICKET_EXECUTION_SELECTED_COUNT_EXCEEDS_RESERVATION")
    blockers = sorted(set(blockers))

    policy = _policy_snapshot(settings_object)
    policy_hash = calculate_payload_hash(policy)
    selection = {
        "raw_event_ids": [int(event.id) for event in events],
        "payload_hashes": [event.payload_hash for event in events],
        "explicit_selection": bool(event_ids),
        "requested_limit": requested_limit,
    }
    ticket_payload = resolution.get("ticket") or {}
    manifest = {
        "ticket_id": ticket_payload.get("ticket_id"),
        "ticket_key": ticket_payload.get("ticket_key"),
        "ticket_event_hash": ticket_payload.get("latest_event_hash"),
        "permit_id": ticket_payload.get("permit_id"),
        "permit_key": ticket_payload.get("permit_key"),
        "assessment_id": ticket_payload.get("assessment_id"),
        "lease_id": ticket_payload.get("lease_id"),
        "certification_id": ticket_payload.get("certification_id"),
        "binding_id": ticket_payload.get("binding_id"),
        "promotion_id": ticket_payload.get("promotion_id"),
        "parser_name": ticket_payload.get("parser_name"),
        "parser_version": ticket_payload.get("parser_version"),
        "parser_implementation_hash": ticket_payload.get(
            "parser_implementation_hash"
        ),
        "output_schema_version": ticket_payload.get("output_schema_version"),
        "release_manifest_hash": ticket_payload.get("release_manifest_hash"),
        "readiness_evidence_hash": ticket_payload.get("readiness_evidence_hash"),
        "permit_policy_hash": ticket_payload.get("permit_policy_hash"),
        "permit_event_hash": ticket_payload.get("permit_event_hash"),
        "ticket_policy_hash": ticket_payload.get("ticket_policy_hash"),
        "event_reservation": reservation,
        "selection": selection,
        "execution_policy_hash": policy_hash,
    }
    run_key = calculate_payload_hash(manifest)
    resolved_ticket_id = ticket_payload.get("ticket_id") or "UNRESOLVED"
    confirmation = (
        f"{TICKET_EXECUTION_CONFIRMATION_PREFIX}:"
        f"{resolved_ticket_id}:{run_key[:16]}"
    )
    return {
        "eligible": not blockers,
        "blocker_codes": blockers,
        "ticket_id": ticket_payload.get("ticket_id"),
        "ticket": sanitize_technical_metadata(ticket_payload),
        "ticket_resolution": sanitize_technical_metadata(resolution),
        "requested_limit": requested_limit,
        "event_reservation": reservation,
        "selected_count": len(events),
        "selected_raw_event_ids": selection["raw_event_ids"],
        "missing_raw_event_ids": missing,
        "incompatible_raw_event_ids": incompatible,
        "execution_policy": policy,
        "execution_policy_hash": policy_hash,
        "run_manifest": manifest,
        "run_key": run_key,
        "confirmation": confirmation,
        "execution_enabled": bool(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_TICKET_EXECUTION_ENABLED",
                False,
            )
        ),
        "writes_database": False,
        "budget_settlement_connected": True,
        "manual_execution_connected": True,
        "scheduler_connected": False,
        "worker_connected": False,
        "automatic_execution": False,
        "external_requests": 0,
        "writes_shadow_tables_only": True,
        "writes_canonical_materialization": False,
        "writes_trades": False,
        "paper_execution": False,
        "live_execution": False,
    }


def _serialize_result(
    result: CanonicalParserShadowTicketExecutionResult,
) -> dict[str, Any]:
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
    run: CanonicalParserShadowTicketExecutionRun,
    *,
    created: bool | None = None,
) -> dict[str, Any]:
    results = list(
        db.scalars(
            select(CanonicalParserShadowTicketExecutionResult)
            .where(
                CanonicalParserShadowTicketExecutionResult.execution_run_db_id
                == run.id
            )
            .order_by(CanonicalParserShadowTicketExecutionResult.raw_event_id.asc())
        )
    )
    payload = {
        "run_id": run.run_id,
        "run_key": run.run_key,
        "ticket_id": run.ticket_id,
        "ticket_key": run.ticket_key,
        "permit_id": run.permit_id,
        "assessment_id": run.assessment_id,
        "lease_id": run.lease_id,
        "certification_id": run.certification_id,
        "binding_id": run.binding_id,
        "promotion_id": run.promotion_id,
        "scope": run.scope,
        "channel": run.channel,
        "consumer": run.consumer,
        "executor": run.executor,
        "status": run.status,
        "parser_name": run.parser_name,
        "parser_version": run.parser_version,
        "parser_implementation_hash": run.parser_implementation_hash,
        "output_schema_version": run.output_schema_version,
        "release_manifest_hash": run.release_manifest_hash,
        "readiness_evidence_hash": run.readiness_evidence_hash,
        "permit_policy_hash": run.permit_policy_hash,
        "permit_event_hash": run.permit_event_hash,
        "ticket_policy_hash": run.ticket_policy_hash,
        "ticket_event_hash": run.ticket_event_hash,
        "execution_policy_version": run.execution_policy_version,
        "execution_policy_hash": run.execution_policy_hash,
        "execution_policy_snapshot": run.execution_policy_snapshot,
        "requested_limit": run.requested_limit,
        "reserved_run_count": run.reserved_run_count,
        "reserved_event_count": run.reserved_event_count,
        "selected_count": run.selected_count,
        "processed_count": run.processed_count,
        "passed_count": run.passed_count,
        "failed_count": run.failed_count,
        "skipped_count": run.skipped_count,
        "artifact_count": run.artifact_count,
        "consumed_run_count": run.consumed_run_count,
        "consumed_event_count": run.consumed_event_count,
        "released_event_count": run.released_event_count,
        "budget_settled": run.budget_settled,
        "settlement_hash": run.settlement_hash,
        "actor_label": run.actor_label,
        "note": run.note,
        "reason_codes": run.reason_codes,
        "selection_snapshot": run.selection_snapshot,
        "metrics_snapshot": run.metrics_snapshot,
        "technical_metadata": run.technical_metadata,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "results": [_serialize_result(item) for item in results],
    }
    if created is not None:
        payload["created"] = created
    return payload


def _existing_for_ticket(
    db: Session, ticket_id: str | None
) -> CanonicalParserShadowTicketExecutionRun | None:
    if not ticket_id:
        return None
    return db.scalar(
        select(CanonicalParserShadowTicketExecutionRun).where(
            CanonicalParserShadowTicketExecutionRun.ticket_id == ticket_id
        )
    )


def run_shadow_ticket_execution(
    db: Session,
    *,
    confirmation: str,
    ticket_id: str,
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
            "CANONICAL_PARSER_SHADOW_TICKET_EXECUTION_ENABLED",
            False,
        )
    ):
        raise CanonicalParserShadowTicketExecutionError(
            "Shadow ticket execution disabilitata.",
            code="CANONICAL_PARSER_SHADOW_TICKET_EXECUTION_DISABLED",
            status_code=409,
        )

    existing = _existing_for_ticket(db, ticket_id)
    if existing is not None:
        return _serialize_run(db, existing, created=False)

    decision_time = _aware(started_at)
    preview = preview_shadow_ticket_execution(
        db,
        ticket_id=ticket_id,
        raw_event_ids=raw_event_ids,
        limit=limit,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=decision_time,
    )
    if confirmation != preview["confirmation"]:
        raise CanonicalParserShadowTicketExecutionError(
            "Conferma shadow ticket execution non valida o non aggiornata.",
            code="SHADOW_TICKET_EXECUTION_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if not preview["eligible"]:
        raise CanonicalParserShadowTicketExecutionError(
            "Shadow execution ticket non idoneo all'esecuzione.",
            code="SHADOW_TICKET_EXECUTION_NOT_ELIGIBLE",
            status_code=409,
        )

    ticket = db.scalar(
        select(CanonicalParserShadowExecutionTicket)
        .where(CanonicalParserShadowExecutionTicket.ticket_id == ticket_id)
        .with_for_update()
    )
    if ticket is None:
        raise CanonicalParserShadowTicketExecutionError(
            "Shadow execution ticket non trovato.",
            code="SHADOW_TICKET_EXECUTION_TICKET_NOT_FOUND",
            status_code=404,
        )
    existing = db.scalar(
        select(CanonicalParserShadowTicketExecutionRun).where(
            CanonicalParserShadowTicketExecutionRun.ticket_db_id == ticket.id
        )
    )
    if existing is not None:
        return _serialize_run(db, existing, created=False)
    if ticket.status != "RESERVED":
        raise CanonicalParserShadowTicketExecutionError(
            "Il ticket non è più riservato.",
            code="SHADOW_TICKET_EXECUTION_TICKET_NOT_RESERVED",
            status_code=409,
        )
    if ticket.ticket_key != preview["run_manifest"]["ticket_key"]:
        raise CanonicalParserShadowTicketExecutionError(
            "Il ticket è cambiato dopo la preview.",
            code="SHADOW_TICKET_EXECUTION_TICKET_DRIFT",
            status_code=409,
        )
    if ticket.latest_event_hash != preview["run_manifest"]["ticket_event_hash"]:
        raise CanonicalParserShadowTicketExecutionError(
            "La audit chain del ticket è cambiata dopo la preview.",
            code="SHADOW_TICKET_EXECUTION_TICKET_EVENT_DRIFT",
            status_code=409,
        )

    try:
        definition = registry.get(ticket.parser_name, ticket.parser_version)
    except ParserRegistryError as exception:
        raise CanonicalParserShadowTicketExecutionError(
            "Parser del ticket non disponibile nel registry.",
            code="SHADOW_TICKET_EXECUTION_PARSER_NOT_FOUND",
            status_code=409,
        ) from exception

    events = list(
        db.scalars(
            select(RawBlockchainEvent)
            .where(
                RawBlockchainEvent.id.in_(preview["selected_raw_event_ids"])
            )
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
        raise CanonicalParserShadowTicketExecutionError(
            "La selezione raw event è cambiata dopo la preview.",
            code="SHADOW_TICKET_EXECUTION_SELECTION_DRIFT",
            status_code=409,
        )

    run = CanonicalParserShadowTicketExecutionRun(
        run_id=str(uuid4()),
        run_key=preview["run_key"],
        ticket_db_id=ticket.id,
        ticket_id=ticket.ticket_id,
        ticket_key=ticket.ticket_key,
        permit_db_id=ticket.permit_db_id,
        permit_id=ticket.permit_id,
        assessment_id=ticket.assessment_id,
        lease_id=ticket.lease_id,
        certification_id=ticket.certification_id,
        binding_id=ticket.binding_id,
        promotion_id=ticket.promotion_id,
        scope=ticket.scope,
        channel=ticket.channel,
        consumer=ticket.consumer,
        executor=TICKET_EXECUTION_EXECUTOR,
        status="RUNNING",
        parser_name=definition.name,
        parser_version=definition.version,
        parser_implementation_hash=definition.implementation_hash,
        output_schema_version=definition.output_schema_version,
        release_manifest_hash=ticket.release_manifest_hash,
        readiness_evidence_hash=ticket.readiness_evidence_hash,
        permit_policy_hash=ticket.permit_policy_hash,
        permit_event_hash=ticket.permit_event_hash,
        ticket_policy_hash=ticket.ticket_policy_hash,
        ticket_event_hash=ticket.latest_event_hash,
        execution_policy_version=TICKET_EXECUTION_POLICY_VERSION,
        execution_policy_hash=preview["execution_policy_hash"],
        execution_policy_snapshot=preview["execution_policy"],
        requested_limit=preview["requested_limit"],
        reserved_run_count=ticket.run_reservation,
        reserved_event_count=ticket.event_reservation,
        selected_count=len(events),
        processed_count=0,
        passed_count=0,
        failed_count=0,
        skipped_count=0,
        artifact_count=0,
        consumed_run_count=0,
        consumed_event_count=0,
        released_event_count=0,
        budget_settled=False,
        settlement_hash=None,
        actor_label=_actor(actor_label),
        note=_note(note),
        reason_codes=[],
        selection_snapshot=sanitize_technical_metadata(current_selection),
        metrics_snapshot={},
        technical_metadata={
            "manual_only": True,
            "ticket_bound": True,
            "atomic_budget_settlement": True,
            "external_requests": 0,
            "writes_shadow_tables_only": True,
            "writes_canonical_materialization": False,
            "writes_trades": False,
            "scheduler_connected": False,
            "worker_connected": False,
            "automatic_execution": False,
            "paper_execution": False,
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
        existing = _existing_for_ticket(db, ticket_id)
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
                first = validate_parser_artifacts(
                    definition, definition.parse(event)
                )
                second = validate_parser_artifacts(
                    definition, definition.parse(event)
                )
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
        except Exception as exception:
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
            CanonicalParserShadowTicketExecutionResult(
                result_id=str(uuid4()),
                execution_run_db_id=run.id,
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
    final_resolution = resolve_shadow_execution_ticket(
        db,
        ticket_id=ticket.ticket_id,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=final_time,
    )
    run_reasons: set[str] = set()
    final_ticket = final_resolution.get("ticket") or {}
    if not final_resolution.get("resolved") or not final_resolution.get(
        "ticket_authorized"
    ):
        run_reasons.add("SHADOW_EXECUTION_TICKET_INTERLOCK_TRIPPED")
        run_reasons.update(final_resolution.get("reason_codes") or [])
    comparisons = {
        "SHADOW_TICKET_EXECUTION_TICKET_ID_DRIFT": (
            run.ticket_id,
            final_ticket.get("ticket_id"),
        ),
        "SHADOW_TICKET_EXECUTION_TICKET_KEY_DRIFT": (
            run.ticket_key,
            final_ticket.get("ticket_key"),
        ),
        "SHADOW_TICKET_EXECUTION_PARSER_HASH_DRIFT": (
            run.parser_implementation_hash,
            final_ticket.get("parser_implementation_hash"),
        ),
        "SHADOW_TICKET_EXECUTION_RELEASE_HASH_DRIFT": (
            run.release_manifest_hash,
            final_ticket.get("release_manifest_hash"),
        ),
        "SHADOW_TICKET_EXECUTION_PERMIT_EVENT_DRIFT": (
            run.permit_event_hash,
            final_ticket.get("permit_event_hash"),
        ),
        "SHADOW_TICKET_EXECUTION_TICKET_EVENT_DRIFT": (
            run.ticket_event_hash,
            final_ticket.get("latest_event_hash"),
        ),
    }
    for reason, (expected, actual) in comparisons.items():
        if expected != actual:
            run_reasons.add(reason)

    processed = len(events)
    if run_reasons:
        run_status = "FAILED"
    elif failed == 0 and skipped == 0 and passed == processed and processed > 0:
        run_status = "PASSED"
    elif passed > 0:
        run_status = "PARTIAL"
    else:
        run_status = "FAILED"

    locked_permit = db.scalar(
        select(CanonicalParserShadowAutomationPermit)
        .where(CanonicalParserShadowAutomationPermit.id == ticket.permit_db_id)
        .with_for_update()
    )
    if locked_permit is None:
        db.rollback()
        raise CanonicalParserShadowTicketExecutionError(
            "Automation permit del ticket non trovato durante il settlement.",
            code="SHADOW_TICKET_EXECUTION_PERMIT_MISSING",
            status_code=409,
        )
    before_runs = int(locked_permit.consumed_run_count)
    before_events = int(locked_permit.consumed_event_count)
    after_runs = before_runs + 1
    after_events = before_events + processed
    if after_runs > int(locked_permit.run_budget):
        db.rollback()
        raise CanonicalParserShadowTicketExecutionError(
            "Budget run insufficiente durante il settlement atomico.",
            code="SHADOW_TICKET_EXECUTION_RUN_BUDGET_SETTLEMENT_FAILED",
            status_code=409,
        )
    if after_events > int(locked_permit.event_budget):
        db.rollback()
        raise CanonicalParserShadowTicketExecutionError(
            "Budget eventi insufficiente durante il settlement atomico.",
            code="SHADOW_TICKET_EXECUTION_EVENT_BUDGET_SETTLEMENT_FAILED",
            status_code=409,
        )

    locked_permit.consumed_run_count = after_runs
    locked_permit.consumed_event_count = after_events
    permit_exhausted = (
        after_runs >= int(locked_permit.run_budget)
        or after_events >= int(locked_permit.event_budget)
    )
    if permit_exhausted and locked_permit.status == "ACTIVE":
        _append_permit_terminal_event(
            db,
            permit=locked_permit,
            event_type="EXHAUSTED",
            new_status="EXHAUSTED",
            actor_label="TICKET_EXECUTION_SETTLEMENT",
            reason=f"SHADOW_TICKET_EXECUTION_BUDGET_EXHAUSTED:{run.run_id}",
            occurred_at=final_time,
        )

    ticket_expired = _aware(ticket.expires_at) <= final_time
    ticket_terminal_status = "EXPIRED" if ticket_expired else "RELEASED"
    ticket_terminal_event = "EXPIRED" if ticket_expired else "RELEASED"
    ticket_reason = (
        f"SHADOW_TICKET_EXECUTION_SETTLED:{run.run_id}:"
        f"{run_status}"
    )
    _append_ticket_terminal_event(
        db,
        ticket=ticket,
        event_type=ticket_terminal_event,
        new_status=ticket_terminal_status,
        actor_label="TICKET_EXECUTION_SETTLEMENT",
        reason=ticket_reason,
        occurred_at=final_time,
    )

    released_events = max(0, int(ticket.event_reservation) - processed)
    settlement_payload = {
        "run_id": run.run_id,
        "run_key": run.run_key,
        "ticket_id": ticket.ticket_id,
        "ticket_key": ticket.ticket_key,
        "ticket_terminal_status": ticket.status,
        "ticket_latest_event_hash": ticket.latest_event_hash,
        "permit_id": locked_permit.permit_id,
        "permit_status": locked_permit.status,
        "permit_latest_event_hash": locked_permit.latest_event_hash,
        "before_consumed_run_count": before_runs,
        "after_consumed_run_count": after_runs,
        "before_consumed_event_count": before_events,
        "after_consumed_event_count": after_events,
        "reserved_run_count": int(ticket.run_reservation),
        "reserved_event_count": int(ticket.event_reservation),
        "consumed_run_count": 1,
        "consumed_event_count": processed,
        "released_event_count": released_events,
        "run_status": run_status,
        "completed_at": final_time.isoformat(),
    }
    settlement_hash = calculate_payload_hash(settlement_payload)

    run.status = run_status
    run.processed_count = processed
    run.passed_count = passed
    run.failed_count = failed
    run.skipped_count = skipped
    run.artifact_count = artifact_total
    run.consumed_run_count = 1
    run.consumed_event_count = processed
    run.released_event_count = released_events
    run.budget_settled = True
    run.settlement_hash = settlement_hash
    run.reason_codes = sorted(run_reasons)
    run.metrics_snapshot = {
        "selected_count": len(events),
        "processed_count": processed,
        "passed_count": passed,
        "failed_count": failed,
        "skipped_count": skipped,
        "artifact_count": artifact_total,
        "pass_rate": round(passed / processed, 6) if processed else 0.0,
        "ticket_interlock_healthy": not run_reasons,
        "budget_settled": True,
        "consumed_run_count": 1,
        "consumed_event_count": processed,
        "released_event_count": released_events,
    }
    run.technical_metadata = {
        **(run.technical_metadata or {}),
        "final_ticket_resolution": sanitize_technical_metadata(final_resolution),
        "settlement_payload": sanitize_technical_metadata(settlement_payload),
    }
    run.completed_at = final_time
    db.commit()
    db.refresh(run)
    return _serialize_run(db, run, created=True)


def get_shadow_ticket_execution_run(
    db: Session, run_id: str
) -> dict[str, Any]:
    run = db.scalar(
        select(CanonicalParserShadowTicketExecutionRun).where(
            CanonicalParserShadowTicketExecutionRun.run_id
            == str(run_id or "").strip()
        )
    )
    if run is None:
        raise CanonicalParserShadowTicketExecutionError(
            "Shadow ticket execution run non trovato.",
            code="SHADOW_TICKET_EXECUTION_RUN_NOT_FOUND",
            status_code=404,
        )
    return _serialize_run(db, run)


def get_shadow_ticket_execution_status(
    db: Session,
    *,
    settings_object: Any = settings,
) -> dict[str, Any]:
    counts = dict(
        db.execute(
            select(
                CanonicalParserShadowTicketExecutionRun.status,
                func.count(CanonicalParserShadowTicketExecutionRun.id),
            ).group_by(CanonicalParserShadowTicketExecutionRun.status)
        ).all()
    )
    settled_runs, settled_events, released_events = db.execute(
        select(
            func.coalesce(
                func.sum(CanonicalParserShadowTicketExecutionRun.consumed_run_count),
                0,
            ),
            func.coalesce(
                func.sum(CanonicalParserShadowTicketExecutionRun.consumed_event_count),
                0,
            ),
            func.coalesce(
                func.sum(CanonicalParserShadowTicketExecutionRun.released_event_count),
                0,
            ),
        )
    ).one()
    return {
        "execution_enabled": bool(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_TICKET_EXECUTION_ENABLED",
                False,
            )
        ),
        "policy_version": TICKET_EXECUTION_POLICY_VERSION,
        "executor": TICKET_EXECUTION_EXECUTOR,
        "run_count": int(sum(counts.values())),
        "status_counts": {
            status: int(counts.get(status, 0))
            for status in ("RUNNING", "PASSED", "PARTIAL", "FAILED")
        },
        "settled_run_count": int(settled_runs or 0),
        "settled_event_count": int(settled_events or 0),
        "released_event_count": int(released_events or 0),
        "policy": _policy_snapshot(settings_object),
        "operational_guards": {
            "manual_execution_connected": True,
            "ticket_required": True,
            "atomic_budget_settlement": True,
            "unused_reservation_released": True,
            "scheduler_connected": False,
            "worker_connected": False,
            "automatic_execution": False,
            "external_requests": 0,
            "writes_shadow_tables_only": True,
            "writes_canonical_materialization": False,
            "writes_trades": False,
            "paper_execution": False,
            "live_execution": False,
        },
    }
