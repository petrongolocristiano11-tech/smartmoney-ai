from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserShadowAutomationPermit,
    CanonicalParserShadowExecutionTicket,
    CanonicalParserShadowExecutionTicketEvent,
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
from backend.app.services.blockchain_parser_shadow_automation_permit_service import (
    AUTOMATION_PERMIT_CONSUMER,
    resolve_shadow_automation_permit,
)

EXECUTION_TICKET_POLICY_VERSION = "canonical-parser-shadow-execution-ticket/1"
EXECUTION_TICKET_CONFIRMATION_PREFIX = (
    "RESERVE_CERTIFIED_SHADOW_EXECUTION_TICKET"
)
EXECUTION_TICKET_RELEASE_PREFIX = (
    "RELEASE_CERTIFIED_SHADOW_EXECUTION_TICKET"
)
EXECUTION_TICKET_EXECUTOR = "CERTIFIED_SHADOW_EXECUTION_TICKET"
_MAX_ACTOR_LENGTH = 80
_MAX_NOTE_LENGTH = 500


class CanonicalParserShadowExecutionTicketError(ValueError):
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
    sanitized = sanitize_error_message(
        value or "LOCAL_OPERATOR", max_length=_MAX_ACTOR_LENGTH
    ) or "LOCAL_OPERATOR"
    return sanitized.replace("<", "").replace(">", "")


def _note(value: str | None) -> str | None:
    if not str(value or "").strip():
        return None
    return sanitize_error_message(value, max_length=_MAX_NOTE_LENGTH)


def _policy_snapshot(settings_object: Any) -> dict[str, Any]:
    return {
        "policy_version": EXECUTION_TICKET_POLICY_VERSION,
        "executor": EXECUTION_TICKET_EXECUTOR,
        "maximum_validity_seconds": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_MAX_VALIDITY_SECONDS",
                180,
            )
        ),
        "minimum_permit_remaining_seconds": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_MIN_PERMIT_REMAINING_SECONDS",
                30,
            )
        ),
        "maximum_event_reservation": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_MAX_EVENT_RESERVATION",
                25,
            )
        ),
        "run_reservation_per_ticket": 1,
        "requires_ready_automation_permit": True,
        "atomic_budget_reservation": True,
        "manual_reserve_only": True,
        "manual_release_only": True,
        "budget_consumption_connected": False,
        "execution_connected": False,
        "scheduler_connected": False,
        "worker_connected": False,
        "automatic_execution": False,
        "external_requests_allowed": False,
        "writes_trades": False,
        "writes_canonical_materialization": False,
        "live_execution": False,
    }


def _event_payload(
    *,
    event_id: str,
    ticket_id: str,
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
        "ticket_id": ticket_id,
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
    db: Session, ticket: CanonicalParserShadowExecutionTicket
) -> list[str]:
    events = list(
        db.scalars(
            select(CanonicalParserShadowExecutionTicketEvent)
            .where(
                CanonicalParserShadowExecutionTicketEvent.ticket_db_id
                == ticket.id
            )
            .order_by(
                CanonicalParserShadowExecutionTicketEvent.sequence.asc()
            )
        )
    )
    reasons: set[str] = set()
    previous_hash: str | None = None
    for expected_sequence, event in enumerate(events, start=1):
        if event.sequence != expected_sequence:
            reasons.add("SHADOW_EXECUTION_TICKET_EVENT_SEQUENCE_INVALID")
        if event.previous_event_hash != previous_hash:
            reasons.add("SHADOW_EXECUTION_TICKET_EVENT_PREVIOUS_HASH_INVALID")
        if calculate_payload_hash(event.event_payload) != event.event_hash:
            reasons.add("SHADOW_EXECUTION_TICKET_EVENT_HASH_INVALID")
        previous_hash = event.event_hash
    if not events:
        reasons.add("SHADOW_EXECUTION_TICKET_EVENT_CHAIN_EMPTY")
    elif ticket.latest_event_sequence != events[-1].sequence:
        reasons.add("SHADOW_EXECUTION_TICKET_LATEST_SEQUENCE_INVALID")
    elif ticket.latest_event_hash != events[-1].event_hash:
        reasons.add("SHADOW_EXECUTION_TICKET_LATEST_HASH_INVALID")
    return sorted(reasons)


def _serialize(ticket: CanonicalParserShadowExecutionTicket) -> dict[str, Any]:
    return {
        "ticket_id": ticket.ticket_id,
        "ticket_key": ticket.ticket_key,
        "ticket_generation": ticket.ticket_generation,
        "permit_id": ticket.permit_id,
        "permit_key": ticket.permit_key,
        "assessment_id": ticket.assessment_id,
        "lease_id": ticket.lease_id,
        "certification_id": ticket.certification_id,
        "binding_id": ticket.binding_id,
        "promotion_id": ticket.promotion_id,
        "scope": ticket.scope,
        "channel": ticket.channel,
        "consumer": ticket.consumer,
        "executor": ticket.executor,
        "status": ticket.status,
        "parser_name": ticket.parser_name,
        "parser_version": ticket.parser_version,
        "parser_implementation_hash": ticket.parser_implementation_hash,
        "output_schema_version": ticket.output_schema_version,
        "release_manifest_hash": ticket.release_manifest_hash,
        "readiness_evidence_hash": ticket.readiness_evidence_hash,
        "permit_policy_hash": ticket.permit_policy_hash,
        "permit_event_hash": ticket.permit_event_hash,
        "ticket_policy_version": ticket.ticket_policy_version,
        "ticket_policy_hash": ticket.ticket_policy_hash,
        "ticket_policy_snapshot": ticket.ticket_policy_snapshot,
        "requested_validity_seconds": ticket.requested_validity_seconds,
        "run_reservation": ticket.run_reservation,
        "event_reservation": ticket.event_reservation,
        "actor_label": ticket.actor_label,
        "note": ticket.note,
        "issued_at": ticket.issued_at,
        "expires_at": ticket.expires_at,
        "released_at": ticket.released_at,
        "release_reason": ticket.release_reason,
        "latest_event_sequence": ticket.latest_event_sequence,
        "latest_event_hash": ticket.latest_event_hash,
        "technical_metadata": ticket.technical_metadata,
    }


def _active_reservations(
    db: Session,
    *,
    permit_db_id: int,
    evaluated_at: datetime,
    exclude_ticket_id: str | None = None,
) -> dict[str, int]:
    query = select(
        func.count(CanonicalParserShadowExecutionTicket.id),
        func.coalesce(
            func.sum(CanonicalParserShadowExecutionTicket.event_reservation),
            0,
        ),
    ).where(
        CanonicalParserShadowExecutionTicket.permit_db_id == permit_db_id,
        CanonicalParserShadowExecutionTicket.status == "RESERVED",
        CanonicalParserShadowExecutionTicket.expires_at > evaluated_at,
    )
    if exclude_ticket_id:
        query = query.where(
            CanonicalParserShadowExecutionTicket.ticket_id
            != exclude_ticket_id
        )
    run_count, event_count = db.execute(query).one()
    return {
        "reserved_run_count": int(run_count or 0),
        "reserved_event_count": int(event_count or 0),
    }


def _append_terminal_event(
    db: Session,
    *,
    ticket: CanonicalParserShadowExecutionTicket,
    event_type: str,
    new_status: str,
    actor_label: str,
    reason: str,
    occurred_at: datetime,
) -> None:
    if _verify_event_chain(db, ticket):
        raise CanonicalParserShadowExecutionTicketError(
            "Audit chain execution ticket non integra.",
            code="PARSER_SHADOW_EXECUTION_TICKET_AUDIT_CHAIN_INVALID",
            status_code=409,
        )
    sequence = ticket.latest_event_sequence + 1
    event_id = str(uuid4())
    payload = _event_payload(
        event_id=event_id,
        ticket_id=ticket.ticket_id,
        sequence=sequence,
        event_type=event_type,
        previous_status=ticket.status,
        new_status=new_status,
        actor_label=actor_label,
        reason=reason,
        previous_event_hash=ticket.latest_event_hash,
        occurred_at=occurred_at,
    )
    event_hash = calculate_payload_hash(payload)
    db.add(
        CanonicalParserShadowExecutionTicketEvent(
            event_id=event_id,
            ticket_db_id=ticket.id,
            sequence=sequence,
            event_type=event_type,
            previous_status=ticket.status,
            new_status=new_status,
            actor_label=actor_label,
            reason=reason,
            event_payload=payload,
            previous_event_hash=ticket.latest_event_hash,
            event_hash=event_hash,
            occurred_at=occurred_at,
        )
    )
    ticket.status = new_status
    ticket.latest_event_sequence = sequence
    ticket.latest_event_hash = event_hash
    if new_status == "RELEASED":
        ticket.released_at = occurred_at
        ticket.release_reason = reason


def _expire_stale_tickets(
    db: Session, *, permit_db_id: int | None, evaluated_at: datetime
) -> list[str]:
    query = select(CanonicalParserShadowExecutionTicket).where(
        CanonicalParserShadowExecutionTicket.status == "RESERVED",
        CanonicalParserShadowExecutionTicket.expires_at <= evaluated_at,
    )
    if permit_db_id is not None:
        query = query.where(
            CanonicalParserShadowExecutionTicket.permit_db_id
            == permit_db_id
        )
    tickets = list(db.scalars(query))
    expired_ids: list[str] = []
    for ticket in tickets:
        _append_terminal_event(
            db,
            ticket=ticket,
            event_type="EXPIRED",
            new_status="EXPIRED",
            actor_label="SYSTEM_EXPIRY",
            reason="SHADOW_EXECUTION_TICKET_VALIDITY_WINDOW_ELAPSED",
            occurred_at=evaluated_at,
        )
        expired_ids.append(ticket.ticket_id)
    return expired_ids


def _permit_from_resolution(
    db: Session, resolution: dict[str, Any], permit_id: str | None
) -> CanonicalParserShadowAutomationPermit | None:
    payload = resolution.get("permit") or {}
    resolved_id = payload.get("permit_id")
    target_id = permit_id or resolved_id
    if not target_id:
        return None
    if permit_id and resolved_id and permit_id != resolved_id:
        return None
    return db.scalar(
        select(CanonicalParserShadowAutomationPermit).where(
            CanonicalParserShadowAutomationPermit.permit_id == target_id
        )
    )


def preview_shadow_execution_ticket(
    db: Session,
    *,
    permit_id: str | None = None,
    validity_seconds: int = 120,
    event_reservation: int = 10,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _policy_snapshot(settings_object)
    policy_hash = calculate_payload_hash(policy)
    blockers: set[str] = set()
    requested_validity = int(validity_seconds)
    requested_events = int(event_reservation)

    if requested_validity < 1:
        blockers.add("SHADOW_EXECUTION_TICKET_VALIDITY_BELOW_MINIMUM")
    if requested_validity > policy["maximum_validity_seconds"]:
        blockers.add("SHADOW_EXECUTION_TICKET_VALIDITY_ABOVE_MAXIMUM")
    if requested_events < 1:
        blockers.add("SHADOW_EXECUTION_TICKET_EVENT_RESERVATION_BELOW_MINIMUM")
    if requested_events > policy["maximum_event_reservation"]:
        blockers.add("SHADOW_EXECUTION_TICKET_EVENT_RESERVATION_ABOVE_MAXIMUM")

    permit_resolution = resolve_shadow_automation_permit(
        db,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=now,
    )
    permit = _permit_from_resolution(db, permit_resolution, permit_id)
    if permit is None:
        blockers.add("SHADOW_EXECUTION_TICKET_PERMIT_MISSING_OR_MISMATCHED")
    if not permit_resolution.get("resolved"):
        blockers.update(
            permit_resolution.get("reason_codes")
            or ["SHADOW_AUTOMATION_PERMIT_UNRESOLVED"]
        )
    if not permit_resolution.get("automation_authorized"):
        blockers.add("SHADOW_AUTOMATION_PERMIT_NOT_AUTHORIZED")
    if permit_resolution.get("status") != "READY":
        blockers.add("SHADOW_AUTOMATION_PERMIT_NOT_READY")

    reservations = {"reserved_run_count": 0, "reserved_event_count": 0}
    remaining_run_budget = 0
    remaining_event_budget = 0
    permit_remaining_seconds: float | None = None
    expires_at: datetime | None = None
    reservation_state_hash = calculate_payload_hash(reservations)
    if permit is not None:
        reservations = _active_reservations(
            db, permit_db_id=permit.id, evaluated_at=now
        )
        remaining_run_budget = max(
            0,
            int(permit.run_budget)
            - int(permit.consumed_run_count)
            - reservations["reserved_run_count"],
        )
        remaining_event_budget = max(
            0,
            int(permit.event_budget)
            - int(permit.consumed_event_count)
            - reservations["reserved_event_count"],
        )
        if remaining_run_budget < 1:
            blockers.add("SHADOW_EXECUTION_TICKET_RUN_BUDGET_UNAVAILABLE")
        if requested_events > remaining_event_budget:
            blockers.add("SHADOW_EXECUTION_TICKET_EVENT_BUDGET_UNAVAILABLE")
        permit_remaining_seconds = round(
            (_aware(permit.expires_at) - now).total_seconds(), 4
        )
        if permit_remaining_seconds < policy[
            "minimum_permit_remaining_seconds"
        ]:
            blockers.add("SHADOW_EXECUTION_TICKET_PERMIT_WINDOW_TOO_SHORT")
        expires_at = min(
            now + timedelta(seconds=requested_validity),
            _aware(permit.expires_at),
        )
        reservation_state_hash = calculate_payload_hash(
            {
                "permit_id": permit.permit_id,
                **reservations,
                "consumed_run_count": permit.consumed_run_count,
                "consumed_event_count": permit.consumed_event_count,
                "permit_event_hash": permit.latest_event_hash,
            }
        )

    permit_payload = permit_resolution.get("permit") or {}
    ticket_manifest = {
        "permit_id": permit_payload.get("permit_id"),
        "permit_key": permit_payload.get("permit_key"),
        "assessment_id": permit_payload.get("assessment_id"),
        "lease_id": permit_payload.get("lease_id"),
        "certification_id": permit_payload.get("certification_id"),
        "binding_id": permit_payload.get("binding_id"),
        "promotion_id": permit_payload.get("promotion_id"),
        "scope": permit_payload.get("scope"),
        "channel": permit_payload.get("channel"),
        "consumer": permit_payload.get("consumer"),
        "parser_name": permit_payload.get("parser_name"),
        "parser_version": permit_payload.get("parser_version"),
        "parser_implementation_hash": permit_payload.get(
            "parser_implementation_hash"
        ),
        "output_schema_version": permit_payload.get("output_schema_version"),
        "release_manifest_hash": permit_payload.get("release_manifest_hash"),
        "readiness_evidence_hash": permit_payload.get(
            "readiness_evidence_hash"
        ),
        "permit_policy_hash": permit_payload.get("permit_policy_hash"),
        "permit_event_hash": permit_payload.get("latest_event_hash"),
        "ticket_policy_hash": policy_hash,
        "requested_validity_seconds": requested_validity,
        "run_reservation": 1,
        "event_reservation": requested_events,
        "reservation_state_hash": reservation_state_hash,
    }
    ticket_key = calculate_payload_hash(ticket_manifest)
    resolved_permit_id = permit_payload.get("permit_id") or "UNRESOLVED"
    confirmation = (
        f"{EXECUTION_TICKET_CONFIRMATION_PREFIX}:"
        f"{resolved_permit_id}:{ticket_key[:16]}"
    )
    return {
        "reservable": not blockers,
        "reason_codes": sorted(blockers),
        "permit_id": permit_payload.get("permit_id"),
        "permit": sanitize_technical_metadata(permit_payload),
        "permit_resolution": sanitize_technical_metadata(permit_resolution),
        "requested_validity_seconds": requested_validity,
        "run_reservation": 1,
        "event_reservation": requested_events,
        "active_reservations": reservations,
        "remaining_run_budget": remaining_run_budget,
        "remaining_event_budget": remaining_event_budget,
        "permit_remaining_seconds": permit_remaining_seconds,
        "expires_at": expires_at,
        "ticket_policy": policy,
        "ticket_policy_hash": policy_hash,
        "ticket_manifest": ticket_manifest,
        "ticket_key": ticket_key,
        "confirmation": confirmation,
        "ticket_enabled": bool(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_ENABLED",
                False,
            )
        ),
        "writes_database": False,
        "budget_reservation_connected": False,
        "budget_consumption_connected": False,
        "execution_connected": False,
        "scheduler_connected": False,
        "worker_connected": False,
        "automatic_execution": False,
        "external_requests": 0,
        "writes_trades": False,
        "writes_canonical_materialization": False,
        "live_execution": False,
    }


def reserve_shadow_execution_ticket(
    db: Session,
    *,
    confirmation: str,
    permit_id: str | None = None,
    validity_seconds: int = 120,
    event_reservation: int = 10,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    issued_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(
        getattr(
            settings_object,
            "CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_ENABLED",
            False,
        )
    ):
        raise CanonicalParserShadowExecutionTicketError(
            "Shadow execution ticket disabilitato.",
            code="CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_DISABLED",
            status_code=409,
        )

    now = _aware(issued_at)
    permit_resolution = resolve_shadow_automation_permit(
        db,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=now,
    )
    permit = _permit_from_resolution(db, permit_resolution, permit_id)
    if permit is None:
        raise CanonicalParserShadowExecutionTicketError(
            "Automation permit non trovato o non corrispondente.",
            code="SHADOW_EXECUTION_TICKET_PERMIT_NOT_FOUND",
            status_code=404,
        )
    permit = db.scalar(
        select(CanonicalParserShadowAutomationPermit)
        .where(CanonicalParserShadowAutomationPermit.id == permit.id)
        .with_for_update()
    )
    assert permit is not None
    expired_ids = _expire_stale_tickets(
        db, permit_db_id=permit.id, evaluated_at=now
    )

    preview = preview_shadow_execution_ticket(
        db,
        permit_id=permit.permit_id,
        validity_seconds=validity_seconds,
        event_reservation=event_reservation,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=now,
    )
    if confirmation != preview["confirmation"]:
        prefix = f"{EXECUTION_TICKET_CONFIRMATION_PREFIX}:{permit.permit_id}:"
        supplied_prefix = confirmation[len(prefix):] if confirmation.startswith(prefix) else ""
        if supplied_prefix:
            existing = db.scalar(
                select(CanonicalParserShadowExecutionTicket).where(
                    CanonicalParserShadowExecutionTicket.permit_db_id
                    == permit.id,
                    CanonicalParserShadowExecutionTicket.status == "RESERVED",
                    CanonicalParserShadowExecutionTicket.expires_at > now,
                    CanonicalParserShadowExecutionTicket.event_reservation
                    == int(event_reservation),
                    CanonicalParserShadowExecutionTicket.ticket_key.like(
                        f"{supplied_prefix}%"
                    ),
                )
            )
            if existing is not None:
                payload = _serialize(existing)
                payload["idempotent"] = True
                payload["expired_ticket_ids"] = expired_ids
                payload["audit_chain_valid"] = not _verify_event_chain(
                    db, existing
                )
                return payload
        raise CanonicalParserShadowExecutionTicketError(
            "Conferma execution ticket non valida.",
            code="SHADOW_EXECUTION_TICKET_CONFIRMATION_MISMATCH",
            status_code=409,
        )
    if not preview["reservable"]:
        raise CanonicalParserShadowExecutionTicketError(
            "Execution ticket non prenotabile: "
            + ", ".join(preview["reason_codes"]),
            code="SHADOW_EXECUTION_TICKET_NOT_RESERVABLE",
            status_code=409,
        )

    existing = db.scalar(
        select(CanonicalParserShadowExecutionTicket).where(
            CanonicalParserShadowExecutionTicket.ticket_key
            == preview["ticket_key"]
        )
    )
    if existing is not None:
        payload = _serialize(existing)
        payload["idempotent"] = True
        payload["expired_ticket_ids"] = expired_ids
        payload["audit_chain_valid"] = not _verify_event_chain(db, existing)
        return payload

    generation = int(
        db.scalar(
            select(
                func.coalesce(
                    func.max(
                        CanonicalParserShadowExecutionTicket.ticket_generation
                    ),
                    0,
                )
            ).where(
                CanonicalParserShadowExecutionTicket.permit_db_id == permit.id
            )
        )
        or 0
    ) + 1
    ticket_id = str(uuid4())
    event_id = str(uuid4())
    actor = _actor(actor_label)
    payload = _event_payload(
        event_id=event_id,
        ticket_id=ticket_id,
        sequence=1,
        event_type="RESERVED",
        previous_status=None,
        new_status="RESERVED",
        actor_label=actor,
        reason=_note(note),
        previous_event_hash=None,
        occurred_at=now,
    )
    event_hash = calculate_payload_hash(payload)
    permit_payload = preview["permit"]
    ticket = CanonicalParserShadowExecutionTicket(
        ticket_id=ticket_id,
        ticket_key=preview["ticket_key"],
        ticket_generation=generation,
        permit_db_id=permit.id,
        permit_id=permit.permit_id,
        permit_key=permit.permit_key,
        assessment_id=permit.assessment_id,
        lease_id=permit.lease_id,
        certification_id=permit.certification_id,
        binding_id=permit.binding_id,
        promotion_id=permit.promotion_id,
        scope=permit.scope,
        channel=permit.channel,
        consumer=permit.consumer,
        executor=EXECUTION_TICKET_EXECUTOR,
        status="RESERVED",
        parser_name=permit.parser_name,
        parser_version=permit.parser_version,
        parser_implementation_hash=permit.parser_implementation_hash,
        output_schema_version=permit.output_schema_version,
        release_manifest_hash=permit.release_manifest_hash,
        readiness_evidence_hash=permit.readiness_evidence_hash,
        permit_policy_hash=permit.permit_policy_hash,
        permit_event_hash=permit.latest_event_hash,
        ticket_policy_version=EXECUTION_TICKET_POLICY_VERSION,
        ticket_policy_hash=preview["ticket_policy_hash"],
        ticket_policy_snapshot=preview["ticket_policy"],
        requested_validity_seconds=int(validity_seconds),
        run_reservation=1,
        event_reservation=int(event_reservation),
        actor_label=actor,
        note=_note(note),
        issued_at=now,
        expires_at=_aware(preview["expires_at"]),
        released_at=None,
        release_reason=None,
        latest_event_sequence=1,
        latest_event_hash=event_hash,
        technical_metadata={
            "manual_reservation": True,
            "atomic_budget_reservation": True,
            "budget_consumption_connected": False,
            "execution_connected": False,
            "scheduler_connected": False,
            "worker_connected": False,
            "external_requests": 0,
            "writes_trades": False,
            "writes_canonical_materialization": False,
            "live_execution": False,
        },
    )
    db.add(ticket)
    try:
        db.flush()
        db.add(
            CanonicalParserShadowExecutionTicketEvent(
                event_id=event_id,
                ticket_db_id=ticket.id,
                sequence=1,
                event_type="RESERVED",
                previous_status=None,
                new_status="RESERVED",
                actor_label=actor,
                reason=_note(note),
                event_payload=payload,
                previous_event_hash=None,
                event_hash=event_hash,
                occurred_at=now,
            )
        )
        db.commit()
    except IntegrityError as exception:
        db.rollback()
        raise CanonicalParserShadowExecutionTicketError(
            "Conflitto durante la prenotazione execution ticket.",
            code="SHADOW_EXECUTION_TICKET_RESERVATION_CONFLICT",
            status_code=409,
        ) from exception
    db.refresh(ticket)
    result = _serialize(ticket)
    result["idempotent"] = False
    result["expired_ticket_ids"] = expired_ids
    result["audit_chain_valid"] = True
    result["remaining_run_budget_after_reservation"] = max(
        0, int(preview["remaining_run_budget"]) - 1
    )
    result["remaining_event_budget_after_reservation"] = max(
        0,
        int(preview["remaining_event_budget"])
        - int(event_reservation),
    )
    return result


def release_shadow_execution_ticket(
    db: Session,
    *,
    ticket_id: str,
    confirmation: str,
    reason: str,
    actor_label: str | None = None,
    released_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(released_at)
    ticket = db.scalar(
        select(CanonicalParserShadowExecutionTicket)
        .where(CanonicalParserShadowExecutionTicket.ticket_id == ticket_id)
        .with_for_update()
    )
    if ticket is None:
        raise CanonicalParserShadowExecutionTicketError(
            "Shadow execution ticket non trovato.",
            code="SHADOW_EXECUTION_TICKET_NOT_FOUND",
            status_code=404,
        )
    expected = f"{EXECUTION_TICKET_RELEASE_PREFIX}:{ticket.ticket_id}"
    if confirmation != expected:
        raise CanonicalParserShadowExecutionTicketError(
            "Conferma rilascio execution ticket non valida.",
            code="SHADOW_EXECUTION_TICKET_RELEASE_CONFIRMATION_MISMATCH",
            status_code=409,
        )
    if ticket.status == "RELEASED":
        payload = _serialize(ticket)
        payload["idempotent"] = True
        payload["audit_chain_valid"] = not _verify_event_chain(db, ticket)
        return payload
    if ticket.status == "EXPIRED":
        payload = _serialize(ticket)
        payload["idempotent"] = True
        payload["audit_chain_valid"] = not _verify_event_chain(db, ticket)
        return payload
    _append_terminal_event(
        db,
        ticket=ticket,
        event_type="RELEASED",
        new_status="RELEASED",
        actor_label=_actor(actor_label),
        reason=_note(reason) or "MANUAL_RELEASE",
        occurred_at=now,
    )
    db.commit()
    db.refresh(ticket)
    payload = _serialize(ticket)
    payload["idempotent"] = False
    payload["audit_chain_valid"] = True
    return payload


def get_shadow_execution_ticket(
    db: Session, ticket_id: str
) -> dict[str, Any]:
    ticket = db.scalar(
        select(CanonicalParserShadowExecutionTicket).where(
            CanonicalParserShadowExecutionTicket.ticket_id == ticket_id
        )
    )
    if ticket is None:
        raise CanonicalParserShadowExecutionTicketError(
            "Shadow execution ticket non trovato.",
            code="SHADOW_EXECUTION_TICKET_NOT_FOUND",
            status_code=404,
        )
    payload = _serialize(ticket)
    payload["audit_chain_valid"] = not _verify_event_chain(db, ticket)
    payload["release_confirmation"] = (
        f"{EXECUTION_TICKET_RELEASE_PREFIX}:{ticket.ticket_id}"
    )
    return payload


def resolve_shadow_execution_ticket(
    db: Session,
    *,
    ticket_id: str | None = None,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    ticket_enabled = bool(
        getattr(
            settings_object,
            "CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_ENABLED",
            False,
        )
    )
    query = select(CanonicalParserShadowExecutionTicket)
    if ticket_id:
        query = query.where(
            CanonicalParserShadowExecutionTicket.ticket_id == ticket_id
        )
    else:
        query = query.where(
            CanonicalParserShadowExecutionTicket.status == "RESERVED"
        ).order_by(
            CanonicalParserShadowExecutionTicket.issued_at.desc(),
            CanonicalParserShadowExecutionTicket.id.desc(),
        )
    ticket = db.scalar(query)
    if ticket is None:
        return {
            "resolved": False,
            "status": "UNTICKETED",
            "reason_codes": ["ACTIVE_SHADOW_EXECUTION_TICKET_MISSING"],
            "ticket_enabled": ticket_enabled,
            "ticket_authorized": False,
            "budget_reservation_connected": True,
            "budget_consumption_connected": False,
            "execution_connected": False,
            "scheduler_connected": False,
            "worker_connected": False,
            "automatic_execution": False,
            "live_execution": False,
        }

    reasons: set[str] = set(_verify_event_chain(db, ticket))
    if ticket.status == "RELEASED":
        reasons.add("SHADOW_EXECUTION_TICKET_RELEASED")
    if ticket.status == "EXPIRED" or _aware(ticket.expires_at) <= now:
        reasons.add("SHADOW_EXECUTION_TICKET_EXPIRED")
    if calculate_payload_hash(ticket.ticket_policy_snapshot) != ticket.ticket_policy_hash:
        reasons.add("SHADOW_EXECUTION_TICKET_POLICY_HASH_INVALID")
    current_policy_hash = calculate_payload_hash(_policy_snapshot(settings_object))
    if current_policy_hash != ticket.ticket_policy_hash:
        reasons.add("SHADOW_EXECUTION_TICKET_POLICY_DRIFT")
    if ticket.run_reservation != 1:
        reasons.add("SHADOW_EXECUTION_TICKET_RUN_RESERVATION_INVALID")
    if ticket.event_reservation < 1:
        reasons.add("SHADOW_EXECUTION_TICKET_EVENT_RESERVATION_INVALID")
    if ticket.executor != EXECUTION_TICKET_EXECUTOR:
        reasons.add("SHADOW_EXECUTION_TICKET_EXECUTOR_INVALID")

    permit_resolution = resolve_shadow_automation_permit(
        db,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=now,
    )
    if not permit_resolution.get("resolved"):
        reasons.update(
            permit_resolution.get("reason_codes")
            or ["SHADOW_AUTOMATION_PERMIT_UNRESOLVED"]
        )
    permit_payload = permit_resolution.get("permit") or {}
    comparisons = {
        "SHADOW_EXECUTION_TICKET_PERMIT_DRIFT": (
            ticket.permit_id,
            permit_payload.get("permit_id"),
        ),
        "SHADOW_EXECUTION_TICKET_PERMIT_KEY_DRIFT": (
            ticket.permit_key,
            permit_payload.get("permit_key"),
        ),
        "SHADOW_EXECUTION_TICKET_ASSESSMENT_DRIFT": (
            ticket.assessment_id,
            permit_payload.get("assessment_id"),
        ),
        "SHADOW_EXECUTION_TICKET_LEASE_DRIFT": (
            ticket.lease_id,
            permit_payload.get("lease_id"),
        ),
        "SHADOW_EXECUTION_TICKET_CERTIFICATION_DRIFT": (
            ticket.certification_id,
            permit_payload.get("certification_id"),
        ),
        "SHADOW_EXECUTION_TICKET_BINDING_DRIFT": (
            ticket.binding_id,
            permit_payload.get("binding_id"),
        ),
        "SHADOW_EXECUTION_TICKET_PROMOTION_DRIFT": (
            ticket.promotion_id,
            permit_payload.get("promotion_id"),
        ),
        "SHADOW_EXECUTION_TICKET_PARSER_HASH_DRIFT": (
            ticket.parser_implementation_hash,
            permit_payload.get("parser_implementation_hash"),
        ),
        "SHADOW_EXECUTION_TICKET_SCHEMA_DRIFT": (
            ticket.output_schema_version,
            permit_payload.get("output_schema_version"),
        ),
        "SHADOW_EXECUTION_TICKET_RELEASE_DRIFT": (
            ticket.release_manifest_hash,
            permit_payload.get("release_manifest_hash"),
        ),
        "SHADOW_EXECUTION_TICKET_READINESS_EVIDENCE_DRIFT": (
            ticket.readiness_evidence_hash,
            permit_payload.get("readiness_evidence_hash"),
        ),
        "SHADOW_EXECUTION_TICKET_PERMIT_POLICY_DRIFT": (
            ticket.permit_policy_hash,
            permit_payload.get("permit_policy_hash"),
        ),
        "SHADOW_EXECUTION_TICKET_PERMIT_EVENT_DRIFT": (
            ticket.permit_event_hash,
            permit_payload.get("latest_event_hash"),
        ),
    }
    for reason, (expected, actual) in comparisons.items():
        if expected != actual:
            reasons.add(reason)

    permit = db.get(CanonicalParserShadowAutomationPermit, ticket.permit_db_id)
    if permit is None:
        reasons.add("SHADOW_EXECUTION_TICKET_PERMIT_ROW_MISSING")
        reservations = {"reserved_run_count": 0, "reserved_event_count": 0}
    else:
        reservations = _active_reservations(
            db, permit_db_id=permit.id, evaluated_at=now
        )
        total_run_commitment = (
            int(permit.consumed_run_count)
            + reservations["reserved_run_count"]
        )
        total_event_commitment = (
            int(permit.consumed_event_count)
            + reservations["reserved_event_count"]
        )
        if total_run_commitment > int(permit.run_budget):
            reasons.add("SHADOW_EXECUTION_TICKET_RUN_BUDGET_OVERBOOKED")
        if total_event_commitment > int(permit.event_budget):
            reasons.add("SHADOW_EXECUTION_TICKET_EVENT_BUDGET_OVERBOOKED")
        if permit.status != "ACTIVE":
            reasons.add("SHADOW_EXECUTION_TICKET_PERMIT_NOT_ACTIVE")
        if _aware(permit.expires_at) <= now:
            reasons.add("SHADOW_EXECUTION_TICKET_PERMIT_EXPIRED")

    terminal_only = {
        "SHADOW_EXECUTION_TICKET_RELEASED",
        "SHADOW_EXECUTION_TICKET_EXPIRED",
    }
    if not reasons:
        status = "READY"
    elif reasons == {"SHADOW_EXECUTION_TICKET_RELEASED"}:
        status = "RELEASED"
    elif reasons == {"SHADOW_EXECUTION_TICKET_EXPIRED"}:
        status = "EXPIRED"
    elif reasons and reasons.issubset(terminal_only):
        status = "EXPIRED"
    else:
        status = "DRIFTED"
    resolved = status == "READY"
    return {
        "resolved": resolved,
        "status": status,
        "reason_codes": sorted(reasons),
        "ticket_enabled": ticket_enabled,
        "ticket_authorized": bool(
            resolved
            and ticket_enabled
            and permit_resolution.get("automation_authorized")
        ),
        "budget_reservation_connected": True,
        "budget_consumption_connected": False,
        "execution_connected": False,
        "scheduler_connected": False,
        "worker_connected": False,
        "automatic_execution": False,
        "live_execution": False,
        "ticket": _serialize(ticket),
        "active_reservations": reservations,
        "permit_resolution": sanitize_technical_metadata(
            permit_resolution
        ),
    }


def get_shadow_execution_ticket_status(
    db: Session,
    *,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    counts = dict(
        db.execute(
            select(
                CanonicalParserShadowExecutionTicket.status,
                func.count(CanonicalParserShadowExecutionTicket.id),
            ).group_by(CanonicalParserShadowExecutionTicket.status)
        ).all()
    )
    active_run_reservations, active_event_reservations = db.execute(
        select(
            func.count(CanonicalParserShadowExecutionTicket.id),
            func.coalesce(
                func.sum(
                    CanonicalParserShadowExecutionTicket.event_reservation
                ),
                0,
            ),
        ).where(
            CanonicalParserShadowExecutionTicket.status == "RESERVED",
            CanonicalParserShadowExecutionTicket.expires_at > now,
        )
    ).one()
    return {
        "ticket_enabled": bool(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_EXECUTION_TICKET_ENABLED",
                False,
            )
        ),
        "policy_version": EXECUTION_TICKET_POLICY_VERSION,
        "executor": EXECUTION_TICKET_EXECUTOR,
        "ticket_count": int(sum(counts.values())),
        "status_counts": {
            status: int(counts.get(status, 0))
            for status in ("RESERVED", "RELEASED", "EXPIRED")
        },
        "active_run_reservations": int(active_run_reservations or 0),
        "active_event_reservations": int(active_event_reservations or 0),
        "policy": _policy_snapshot(settings_object),
        "operational_guards": {
            "manual_reserve_only": True,
            "manual_release_only": True,
            "atomic_budget_reservation": True,
            "budget_reservation_connected": True,
            "budget_consumption_connected": False,
            "execution_connected": False,
            "scheduler_connected": False,
            "worker_connected": False,
            "automatic_execution": False,
            "external_requests": 0,
            "writes_trades": False,
            "writes_canonical_materialization": False,
            "changes_runtime_flags": False,
            "operational_pipeline_consumer": False,
            "live_execution": False,
        },
    }
