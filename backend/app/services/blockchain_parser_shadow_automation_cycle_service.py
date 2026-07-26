from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserShadowAutomationCycle,
    CanonicalParserShadowAutomationCycleEvent,
    CanonicalParserShadowAutomationPermit,
    CanonicalParserShadowExecutionTicket,
    CanonicalParserShadowTicketExecutionRun,
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
from backend.app.services.blockchain_parser_shadow_execution_ticket_service import (
    CanonicalParserShadowExecutionTicketError,
    EXECUTION_TICKET_RELEASE_PREFIX,
    preview_shadow_execution_ticket,
    release_shadow_execution_ticket,
    reserve_shadow_execution_ticket,
)
from backend.app.services.blockchain_parser_shadow_ticket_execution_service import (
    CanonicalParserShadowTicketExecutionError,
    preview_shadow_ticket_execution,
    run_shadow_ticket_execution,
)

AUTOMATION_CYCLE_POLICY_VERSION = "canonical-parser-shadow-automation-cycle/1"
AUTOMATION_CYCLE_CONFIRMATION_PREFIX = "RUN_CERTIFIED_SHADOW_AUTOMATION_CYCLE"
AUTOMATION_CYCLE_EXECUTOR = "CERTIFIED_SHADOW_AUTOMATION_COORDINATOR"
_MAX_ACTOR_LENGTH = 80
_MAX_NOTE_LENGTH = 500
_MAX_ERROR_LENGTH = 1000


class CanonicalParserShadowAutomationCycleError(ValueError):
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


def _normalize_event_ids(raw_event_ids: list[int] | None) -> list[int]:
    values: set[int] = set()
    for raw_value in raw_event_ids or []:
        value = int(raw_value)
        if value <= 0:
            raise CanonicalParserShadowAutomationCycleError(
                "Gli ID raw event devono essere positivi.",
                code="SHADOW_AUTOMATION_CYCLE_RAW_EVENT_ID_INVALID",
            )
        values.add(value)
    return sorted(values)


def _policy_snapshot(settings_object: Any) -> dict[str, Any]:
    return {
        "policy_version": AUTOMATION_CYCLE_POLICY_VERSION,
        "executor": AUTOMATION_CYCLE_EXECUTOR,
        "maximum_event_reservation": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_AUTOMATION_CYCLE_MAX_EVENT_RESERVATION",
                25,
            )
        ),
        "maximum_execution_limit": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_AUTOMATION_CYCLE_MAX_EXECUTION_LIMIT",
                25,
            )
        ),
        "ticket_validity_seconds": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_AUTOMATION_CYCLE_TICKET_VALIDITY_SECONDS",
                120,
            )
        ),
        "manual_only": True,
        "reserve_ticket": True,
        "execute_ticket": True,
        "compensating_release_on_failure": True,
        "idempotent_cycle_key": True,
        "external_requests_allowed": False,
        "writes_shadow_tables_only": True,
        "writes_trades": False,
        "paper_execution": False,
        "live_execution": False,
        "scheduler_connected": False,
        "worker_connected": False,
        "automatic_loop_connected": False,
    }


def _event_payload(
    *,
    event_id: str,
    cycle_id: str,
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
        "cycle_id": cycle_id,
        "sequence": sequence,
        "event_type": event_type,
        "previous_status": previous_status,
        "new_status": new_status,
        "actor_label": actor_label,
        "reason": reason,
        "previous_event_hash": previous_event_hash,
        "occurred_at": occurred_at.isoformat(),
    }


def _append_event(
    db: Session,
    *,
    cycle: CanonicalParserShadowAutomationCycle,
    event_type: str,
    new_status: str,
    actor_label: str,
    reason: str | None,
    occurred_at: datetime,
) -> None:
    sequence = int(cycle.latest_event_sequence or 0) + 1
    event_id = str(uuid4())
    payload = _event_payload(
        event_id=event_id,
        cycle_id=cycle.cycle_id,
        sequence=sequence,
        event_type=event_type,
        previous_status=cycle.status,
        new_status=new_status,
        actor_label=actor_label,
        reason=reason,
        previous_event_hash=cycle.latest_event_hash,
        occurred_at=occurred_at,
    )
    event_hash = calculate_payload_hash(payload)
    db.add(
        CanonicalParserShadowAutomationCycleEvent(
            event_id=event_id,
            cycle_db_id=cycle.id,
            sequence=sequence,
            event_type=event_type,
            previous_status=cycle.status,
            new_status=new_status,
            actor_label=actor_label,
            reason=reason,
            event_payload=payload,
            previous_event_hash=cycle.latest_event_hash,
            event_hash=event_hash,
            occurred_at=occurred_at,
        )
    )
    cycle.status = new_status
    cycle.latest_event_sequence = sequence
    cycle.latest_event_hash = event_hash


def _verify_event_chain(
    db: Session, cycle: CanonicalParserShadowAutomationCycle
) -> list[str]:
    reasons: list[str] = []
    events = list(
        db.scalars(
            select(CanonicalParserShadowAutomationCycleEvent)
            .where(CanonicalParserShadowAutomationCycleEvent.cycle_db_id == cycle.id)
            .order_by(CanonicalParserShadowAutomationCycleEvent.sequence.asc())
        )
    )
    previous_hash: str | None = None
    for expected_sequence, event in enumerate(events, start=1):
        if event.sequence != expected_sequence:
            reasons.append("SHADOW_AUTOMATION_CYCLE_EVENT_SEQUENCE_INVALID")
        if event.previous_event_hash != previous_hash:
            reasons.append("SHADOW_AUTOMATION_CYCLE_EVENT_CHAIN_BROKEN")
        expected_payload = _event_payload(
            event_id=event.event_id,
            cycle_id=cycle.cycle_id,
            sequence=event.sequence,
            event_type=event.event_type,
            previous_status=event.previous_status,
            new_status=event.new_status,
            actor_label=event.actor_label,
            reason=event.reason,
            previous_event_hash=event.previous_event_hash,
            occurred_at=_aware(event.occurred_at),
        )
        if event.event_hash != calculate_payload_hash(expected_payload):
            reasons.append("SHADOW_AUTOMATION_CYCLE_EVENT_HASH_INVALID")
        previous_hash = event.event_hash
    if cycle.latest_event_sequence != len(events):
        reasons.append("SHADOW_AUTOMATION_CYCLE_LATEST_SEQUENCE_INVALID")
    if cycle.latest_event_hash != previous_hash:
        reasons.append("SHADOW_AUTOMATION_CYCLE_LATEST_HASH_INVALID")
    return sorted(set(reasons))


def _serialize_cycle(
    db: Session,
    cycle: CanonicalParserShadowAutomationCycle,
    *,
    created: bool | None = None,
) -> dict[str, Any]:
    events = list(
        db.scalars(
            select(CanonicalParserShadowAutomationCycleEvent)
            .where(CanonicalParserShadowAutomationCycleEvent.cycle_db_id == cycle.id)
            .order_by(CanonicalParserShadowAutomationCycleEvent.sequence.asc())
        )
    )
    payload = {
        "cycle_id": cycle.cycle_id,
        "cycle_key": cycle.cycle_key,
        "permit_id": cycle.permit_id,
        "ticket_id": cycle.ticket_id,
        "execution_run_id": cycle.execution_run_id,
        "status": cycle.status,
        "cycle_policy_version": cycle.cycle_policy_version,
        "cycle_policy_hash": cycle.cycle_policy_hash,
        "cycle_policy_snapshot": cycle.cycle_policy_snapshot,
        "requested_event_reservation": cycle.requested_event_reservation,
        "requested_limit": cycle.requested_limit,
        "raw_event_ids": list(cycle.raw_event_ids or []),
        "processed_count": cycle.processed_count,
        "passed_count": cycle.passed_count,
        "failed_count": cycle.failed_count,
        "skipped_count": cycle.skipped_count,
        "artifact_count": cycle.artifact_count,
        "budget_settled": cycle.budget_settled,
        "actor_label": cycle.actor_label,
        "note": cycle.note,
        "reason_codes": list(cycle.reason_codes or []),
        "preview_snapshot": cycle.preview_snapshot,
        "execution_snapshot": cycle.execution_snapshot,
        "technical_metadata": cycle.technical_metadata,
        "latest_event_sequence": cycle.latest_event_sequence,
        "latest_event_hash": cycle.latest_event_hash,
        "started_at": cycle.started_at,
        "completed_at": cycle.completed_at,
        "audit_chain_valid": not _verify_event_chain(db, cycle),
        "events": [
            {
                "event_id": item.event_id,
                "sequence": item.sequence,
                "event_type": item.event_type,
                "previous_status": item.previous_status,
                "new_status": item.new_status,
                "actor_label": item.actor_label,
                "reason": item.reason,
                "event_hash": item.event_hash,
                "previous_event_hash": item.previous_event_hash,
                "occurred_at": item.occurred_at,
            }
            for item in events
        ],
    }
    if created is not None:
        payload["created"] = created
    return payload


def preview_shadow_automation_cycle(
    db: Session,
    *,
    permit_id: str | None = None,
    raw_event_ids: list[int] | None = None,
    event_reservation: int = 10,
    limit: int = 10,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    ids = _normalize_event_ids(raw_event_ids)
    policy = _policy_snapshot(settings_object)
    policy_hash = calculate_payload_hash(policy)
    blockers: set[str] = set()
    reservation = int(event_reservation)
    requested_limit = int(limit)
    if reservation < 1 or reservation > policy["maximum_event_reservation"]:
        blockers.add("SHADOW_AUTOMATION_CYCLE_EVENT_RESERVATION_INVALID")
    if requested_limit < 1 or requested_limit > policy["maximum_execution_limit"]:
        blockers.add("SHADOW_AUTOMATION_CYCLE_LIMIT_INVALID")
    if requested_limit > reservation:
        blockers.add("SHADOW_AUTOMATION_CYCLE_LIMIT_EXCEEDS_RESERVATION")
    if ids and len(ids) > reservation:
        blockers.add("SHADOW_AUTOMATION_CYCLE_SELECTION_EXCEEDS_RESERVATION")
    ticket_preview = preview_shadow_execution_ticket(
        db,
        permit_id=permit_id,
        validity_seconds=policy["ticket_validity_seconds"],
        event_reservation=reservation,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=now,
    )
    if not ticket_preview.get("reservable"):
        blockers.update(ticket_preview.get("reason_codes") or [])
        blockers.add("SHADOW_AUTOMATION_CYCLE_TICKET_NOT_RESERVABLE")
    resolved_permit_id = ticket_preview.get("permit_id") or permit_id
    manifest = {
        "permit_id": resolved_permit_id,
        "ticket_key": ticket_preview.get("ticket_key"),
        "event_reservation": reservation,
        "limit": requested_limit,
        "raw_event_ids": ids,
        "cycle_policy_hash": policy_hash,
    }
    cycle_key = calculate_payload_hash(manifest)
    confirmation = (
        f"{AUTOMATION_CYCLE_CONFIRMATION_PREFIX}:"
        f"{resolved_permit_id or 'UNRESOLVED'}:{cycle_key[:16]}"
    )
    return {
        "eligible": not blockers,
        "blocker_codes": sorted(blockers),
        "permit_id": resolved_permit_id,
        "event_reservation": reservation,
        "limit": requested_limit,
        "raw_event_ids": ids,
        "ticket_preview": sanitize_technical_metadata(ticket_preview),
        "cycle_manifest": manifest,
        "cycle_key": cycle_key,
        "cycle_policy": policy,
        "cycle_policy_hash": policy_hash,
        "confirmation": confirmation,
        "cycle_enabled": bool(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_AUTOMATION_CYCLE_ENABLED",
                False,
            )
        ),
        "writes_database": False,
        "manual_only": True,
        "scheduler_connected": False,
        "worker_connected": False,
        "automatic_loop_connected": False,
        "external_requests": 0,
        "writes_trades": False,
        "paper_execution": False,
        "live_execution": False,
    }


def run_shadow_automation_cycle(
    db: Session,
    *,
    confirmation: str,
    permit_id: str | None = None,
    raw_event_ids: list[int] | None = None,
    event_reservation: int = 10,
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
            "CANONICAL_PARSER_SHADOW_AUTOMATION_CYCLE_ENABLED",
            False,
        )
    ):
        raise CanonicalParserShadowAutomationCycleError(
            "Shadow automation cycle disabilitato.",
            code="CANONICAL_PARSER_SHADOW_AUTOMATION_CYCLE_DISABLED",
            status_code=409,
        )
    now = _aware(started_at)
    preview = preview_shadow_automation_cycle(
        db,
        permit_id=permit_id,
        raw_event_ids=raw_event_ids,
        event_reservation=event_reservation,
        limit=limit,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=now,
    )
    if confirmation != preview["confirmation"]:
        prefix = f"{AUTOMATION_CYCLE_CONFIRMATION_PREFIX}:{permit_id or preview.get('permit_id')}:"
        supplied_prefix = confirmation[len(prefix):] if confirmation.startswith(prefix) else ""
        if supplied_prefix:
            existing_retry = db.scalar(
                select(CanonicalParserShadowAutomationCycle).where(
                    CanonicalParserShadowAutomationCycle.permit_id == (permit_id or preview.get("permit_id")),
                    CanonicalParserShadowAutomationCycle.requested_event_reservation == int(event_reservation),
                    CanonicalParserShadowAutomationCycle.requested_limit == int(limit),
                    CanonicalParserShadowAutomationCycle.raw_event_ids == preview["raw_event_ids"],
                    CanonicalParserShadowAutomationCycle.cycle_key.like(f"{supplied_prefix}%"),
                )
            )
            if existing_retry is not None:
                return _serialize_cycle(db, existing_retry, created=False)
        raise CanonicalParserShadowAutomationCycleError(
            "Conferma shadow automation cycle non valida o non aggiornata.",
            code="SHADOW_AUTOMATION_CYCLE_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    existing = db.scalar(
        select(CanonicalParserShadowAutomationCycle).where(
            CanonicalParserShadowAutomationCycle.cycle_key == preview["cycle_key"]
        )
    )
    if existing is not None:
        return _serialize_cycle(db, existing, created=False)
    if not preview["eligible"]:
        raise CanonicalParserShadowAutomationCycleError(
            "Shadow automation cycle non idoneo.",
            code="SHADOW_AUTOMATION_CYCLE_NOT_ELIGIBLE",
            status_code=409,
        )
    permit_payload = preview["ticket_preview"].get("permit") or {}
    permit = db.scalar(
        select(CanonicalParserShadowAutomationPermit).where(
            CanonicalParserShadowAutomationPermit.permit_id == preview["permit_id"]
        )
    )
    if permit is None:
        raise CanonicalParserShadowAutomationCycleError(
            "Automation permit non trovato.",
            code="SHADOW_AUTOMATION_CYCLE_PERMIT_NOT_FOUND",
            status_code=404,
        )
    cycle = CanonicalParserShadowAutomationCycle(
        cycle_id=str(uuid4()),
        cycle_key=preview["cycle_key"],
        permit_db_id=permit.id,
        permit_id=permit.permit_id,
        ticket_db_id=None,
        ticket_id=None,
        execution_run_db_id=None,
        execution_run_id=None,
        status="RUNNING",
        cycle_policy_version=AUTOMATION_CYCLE_POLICY_VERSION,
        cycle_policy_hash=preview["cycle_policy_hash"],
        cycle_policy_snapshot=preview["cycle_policy"],
        requested_event_reservation=int(event_reservation),
        requested_limit=int(limit),
        raw_event_ids=preview["raw_event_ids"],
        processed_count=0,
        passed_count=0,
        failed_count=0,
        skipped_count=0,
        artifact_count=0,
        budget_settled=False,
        actor_label=_actor(actor_label),
        note=_note(note),
        reason_codes=[],
        preview_snapshot=sanitize_technical_metadata(preview),
        execution_snapshot={},
        technical_metadata={
            "manual_only": True,
            "coordinator": True,
            "ticket_reservation_connected": True,
            "ticket_execution_connected": True,
            "compensating_release_on_failure": True,
            "scheduler_connected": False,
            "worker_connected": False,
            "automatic_loop_connected": False,
            "external_requests": 0,
            "writes_trades": False,
            "paper_execution": False,
            "live_execution": False,
        },
        latest_event_sequence=0,
        latest_event_hash=None,
        started_at=now,
        completed_at=None,
    )
    db.add(cycle)
    try:
        db.flush()
        _append_event(
            db,
            cycle=cycle,
            event_type="STARTED",
            new_status="RUNNING",
            actor_label=cycle.actor_label,
            reason=cycle.note,
            occurred_at=now,
        )
        db.commit()
    except IntegrityError as exception:
        db.rollback()
        existing = db.scalar(
            select(CanonicalParserShadowAutomationCycle).where(
                CanonicalParserShadowAutomationCycle.cycle_key == preview["cycle_key"]
            )
        )
        if existing is not None:
            return _serialize_cycle(db, existing, created=False)
        raise CanonicalParserShadowAutomationCycleError(
            "Conflitto durante la creazione del ciclo.",
            code="SHADOW_AUTOMATION_CYCLE_CONFLICT",
            status_code=409,
        ) from exception

    ticket_id: str | None = None
    try:
        ticket_payload = reserve_shadow_execution_ticket(
            db,
            confirmation=preview["ticket_preview"]["confirmation"],
            permit_id=permit.permit_id,
            validity_seconds=preview["cycle_policy"]["ticket_validity_seconds"],
            event_reservation=int(event_reservation),
            actor_label=cycle.actor_label,
            note=f"M17 cycle {cycle.cycle_id}",
            settings_object=settings_object,
            registry=registry,
            issued_at=now,
        )
        ticket_id = ticket_payload["ticket_id"]
        execution_preview = preview_shadow_ticket_execution(
            db,
            ticket_id=ticket_id,
            raw_event_ids=preview["raw_event_ids"],
            limit=int(limit),
            settings_object=settings_object,
            registry=registry,
            evaluated_at=now,
        )
        execution_payload = run_shadow_ticket_execution(
            db,
            confirmation=execution_preview["confirmation"],
            ticket_id=ticket_id,
            raw_event_ids=preview["raw_event_ids"],
            limit=int(limit),
            actor_label=cycle.actor_label,
            note=f"M17 cycle {cycle.cycle_id}",
            settings_object=settings_object,
            registry=registry,
            started_at=now,
            completed_at=_aware(completed_at),
        )
        cycle = db.scalar(
            select(CanonicalParserShadowAutomationCycle)
            .where(CanonicalParserShadowAutomationCycle.id == cycle.id)
            .with_for_update()
        )
        assert cycle is not None
        ticket = db.scalar(
            select(CanonicalParserShadowExecutionTicket).where(
                CanonicalParserShadowExecutionTicket.ticket_id == ticket_id
            )
        )
        execution_run = db.scalar(
            select(CanonicalParserShadowTicketExecutionRun).where(
                CanonicalParserShadowTicketExecutionRun.run_id
                == execution_payload["run_id"]
            )
        )
        cycle.ticket_db_id = ticket.id if ticket is not None else None
        cycle.ticket_id = ticket_id
        cycle.execution_run_db_id = execution_run.id if execution_run is not None else None
        cycle.execution_run_id = execution_payload["run_id"]
        cycle.processed_count = int(execution_payload["processed_count"])
        cycle.passed_count = int(execution_payload["passed_count"])
        cycle.failed_count = int(execution_payload["failed_count"])
        cycle.skipped_count = int(execution_payload["skipped_count"])
        cycle.artifact_count = int(execution_payload["artifact_count"])
        cycle.budget_settled = bool(execution_payload["budget_settled"])
        cycle.reason_codes = list(execution_payload.get("reason_codes") or [])
        cycle.execution_snapshot = sanitize_technical_metadata(execution_payload)
        terminal_status = execution_payload["status"]
        if terminal_status not in {"PASSED", "PARTIAL"}:
            terminal_status = "FAILED"
        cycle.completed_at = _aware(completed_at)
        _append_event(
            db,
            cycle=cycle,
            event_type="COMPLETED" if terminal_status != "FAILED" else "FAILED",
            new_status=terminal_status,
            actor_label=cycle.actor_label,
            reason=f"TICKET_EXECUTION:{execution_payload['run_id']}:{execution_payload['status']}",
            occurred_at=cycle.completed_at,
        )
        db.commit()
        db.refresh(cycle)
        return _serialize_cycle(db, cycle, created=True)
    except (
        CanonicalParserShadowExecutionTicketError,
        CanonicalParserShadowTicketExecutionError,
    ) as exception:
        db.rollback()
        if ticket_id:
            try:
                release_shadow_execution_ticket(
                    db,
                    ticket_id=ticket_id,
                    confirmation=f"{EXECUTION_TICKET_RELEASE_PREFIX}:{ticket_id}",
                    reason=f"M17_COMPENSATING_RELEASE:{getattr(exception, 'code', 'ERROR')}",
                    actor_label="M17_COORDINATOR",
                    released_at=_aware(completed_at),
                )
            except Exception:
                db.rollback()
        cycle = db.scalar(
            select(CanonicalParserShadowAutomationCycle)
            .where(CanonicalParserShadowAutomationCycle.cycle_key == preview["cycle_key"])
            .with_for_update()
        )
        if cycle is not None:
            if ticket_id:
                ticket = db.scalar(
                    select(CanonicalParserShadowExecutionTicket).where(
                        CanonicalParserShadowExecutionTicket.ticket_id == ticket_id
                    )
                )
                cycle.ticket_db_id = ticket.id if ticket is not None else None
                cycle.ticket_id = ticket_id
            cycle.reason_codes = [
                getattr(exception, "code", "SHADOW_AUTOMATION_CYCLE_FAILED")
            ]
            cycle.execution_snapshot = {
                "error": sanitize_error_message(exception, max_length=_MAX_ERROR_LENGTH),
                "error_code": getattr(exception, "code", None),
            }
            cycle.completed_at = _aware(completed_at)
            _append_event(
                db,
                cycle=cycle,
                event_type="FAILED",
                new_status="FAILED",
                actor_label=cycle.actor_label,
                reason=sanitize_error_message(exception, max_length=_MAX_ERROR_LENGTH),
                occurred_at=cycle.completed_at,
            )
            db.commit()
        raise CanonicalParserShadowAutomationCycleError(
            "Shadow automation cycle fallito: " + str(exception),
            code="SHADOW_AUTOMATION_CYCLE_EXECUTION_FAILED",
            status_code=getattr(exception, "status_code", 409),
        ) from exception


def get_shadow_automation_cycle(db: Session, cycle_id: str) -> dict[str, Any]:
    cycle = db.scalar(
        select(CanonicalParserShadowAutomationCycle).where(
            CanonicalParserShadowAutomationCycle.cycle_id
            == str(cycle_id or "").strip()
        )
    )
    if cycle is None:
        raise CanonicalParserShadowAutomationCycleError(
            "Shadow automation cycle non trovato.",
            code="SHADOW_AUTOMATION_CYCLE_NOT_FOUND",
            status_code=404,
        )
    return _serialize_cycle(db, cycle)


def get_shadow_automation_cycle_status(
    db: Session,
    *,
    settings_object: Any = settings,
) -> dict[str, Any]:
    counts = dict(
        db.execute(
            select(
                CanonicalParserShadowAutomationCycle.status,
                func.count(CanonicalParserShadowAutomationCycle.id),
            ).group_by(CanonicalParserShadowAutomationCycle.status)
        ).all()
    )
    return {
        "cycle_enabled": bool(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_AUTOMATION_CYCLE_ENABLED",
                False,
            )
        ),
        "policy_version": AUTOMATION_CYCLE_POLICY_VERSION,
        "executor": AUTOMATION_CYCLE_EXECUTOR,
        "cycle_count": int(sum(counts.values())),
        "status_counts": {
            status: int(counts.get(status, 0))
            for status in ("RUNNING", "PASSED", "PARTIAL", "FAILED")
        },
        "policy": _policy_snapshot(settings_object),
        "operational_guards": {
            "manual_only": True,
            "scheduler_connected": False,
            "worker_connected": False,
            "automatic_loop_connected": False,
            "external_requests": 0,
            "writes_trades": False,
            "paper_execution": False,
            "live_execution": False,
        },
    }
