from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserShadowAutomationCycle,
    CanonicalParserShadowSchedulerEvent,
    CanonicalParserShadowSchedulerState,
    CanonicalParserShadowSchedulerTick,
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
from backend.app.services.blockchain_parser_shadow_automation_cycle_service import (
    CanonicalParserShadowAutomationCycleError,
    preview_shadow_automation_cycle,
    run_shadow_automation_cycle,
)

SHADOW_SCHEDULER_POLICY_VERSION = "canonical-parser-shadow-scheduler/1"
SHADOW_SCHEDULER_NAME = "CANONICAL_SHADOW_AUTOMATION"
SHADOW_SCHEDULER_START_PREFIX = "START_CERTIFIED_SHADOW_SCHEDULER"
SHADOW_SCHEDULER_STOP_PREFIX = "STOP_CERTIFIED_SHADOW_SCHEDULER"
SHADOW_SCHEDULER_KILL_PREFIX = "KILL_CERTIFIED_SHADOW_SCHEDULER"
SHADOW_SCHEDULER_RESET_PREFIX = "RESET_CERTIFIED_SHADOW_SCHEDULER"
SHADOW_SCHEDULER_HEARTBEAT_PREFIX = "HEARTBEAT_CERTIFIED_SHADOW_SCHEDULER"
SHADOW_SCHEDULER_TICK_PREFIX = "TICK_CERTIFIED_SHADOW_SCHEDULER"
_MAX_ACTOR_LENGTH = 80
_MAX_NOTE_LENGTH = 500
_MAX_ERROR_LENGTH = 1000


class CanonicalParserShadowSchedulerError(ValueError):
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
            raise CanonicalParserShadowSchedulerError(
                "Gli ID raw event devono essere positivi.",
                code="SHADOW_SCHEDULER_RAW_EVENT_ID_INVALID",
            )
        values.add(value)
    return sorted(values)


def _policy_snapshot(settings_object: Any) -> dict[str, Any]:
    return {
        "policy_version": SHADOW_SCHEDULER_POLICY_VERSION,
        "scheduler_name": SHADOW_SCHEDULER_NAME,
        "minimum_interval_seconds": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_SCHEDULER_MIN_INTERVAL_SECONDS",
                300,
            )
        ),
        "maximum_interval_seconds": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_SCHEDULER_MAX_INTERVAL_SECONDS",
                3600,
            )
        ),
        "lock_ttl_seconds": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_SCHEDULER_LOCK_TTL_SECONDS",
                180,
            )
        ),
        "heartbeat_timeout_seconds": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_SCHEDULER_HEARTBEAT_TIMEOUT_SECONDS",
                300,
            )
        ),
        "maximum_event_reservation": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_SCHEDULER_MAX_EVENT_RESERVATION",
                25,
            )
        ),
        "maximum_execution_limit": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_SHADOW_SCHEDULER_MAX_EXECUTION_LIMIT",
                25,
            )
        ),
        "persistent_singleton_state": True,
        "database_lock": True,
        "lock_expiry": True,
        "heartbeat": True,
        "kill_switch": True,
        "manual_tick_only": True,
        "automatic_loop_connected": False,
        "worker_connected": False,
        "external_requests_allowed": False,
        "writes_trades": False,
        "paper_execution": False,
        "live_execution": False,
    }


def _event_payload(
    *,
    event_id: str,
    scheduler_name: str,
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
        "scheduler_name": scheduler_name,
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
    state: CanonicalParserShadowSchedulerState,
    event_type: str,
    new_status: str,
    actor_label: str,
    reason: str | None,
    occurred_at: datetime,
) -> None:
    sequence = int(state.latest_event_sequence or 0) + 1
    event_id = str(uuid4())
    payload = _event_payload(
        event_id=event_id,
        scheduler_name=state.scheduler_name,
        sequence=sequence,
        event_type=event_type,
        previous_status=state.status,
        new_status=new_status,
        actor_label=actor_label,
        reason=reason,
        previous_event_hash=state.latest_event_hash,
        occurred_at=occurred_at,
    )
    event_hash = calculate_payload_hash(payload)
    db.add(
        CanonicalParserShadowSchedulerEvent(
            event_id=event_id,
            scheduler_state_db_id=state.id,
            sequence=sequence,
            event_type=event_type,
            previous_status=state.status,
            new_status=new_status,
            actor_label=actor_label,
            reason=reason,
            event_payload=payload,
            previous_event_hash=state.latest_event_hash,
            event_hash=event_hash,
            occurred_at=occurred_at,
        )
    )
    state.status = new_status
    state.latest_event_sequence = sequence
    state.latest_event_hash = event_hash


def _verify_event_chain(
    db: Session, state: CanonicalParserShadowSchedulerState
) -> list[str]:
    reasons: list[str] = []
    events = list(
        db.scalars(
            select(CanonicalParserShadowSchedulerEvent)
            .where(CanonicalParserShadowSchedulerEvent.scheduler_state_db_id == state.id)
            .order_by(CanonicalParserShadowSchedulerEvent.sequence.asc())
        )
    )
    previous_hash: str | None = None
    for expected_sequence, event in enumerate(events, start=1):
        if event.sequence != expected_sequence:
            reasons.append("SHADOW_SCHEDULER_EVENT_SEQUENCE_INVALID")
        if event.previous_event_hash != previous_hash:
            reasons.append("SHADOW_SCHEDULER_EVENT_CHAIN_BROKEN")
        expected = _event_payload(
            event_id=event.event_id,
            scheduler_name=state.scheduler_name,
            sequence=event.sequence,
            event_type=event.event_type,
            previous_status=event.previous_status,
            new_status=event.new_status,
            actor_label=event.actor_label,
            reason=event.reason,
            previous_event_hash=event.previous_event_hash,
            occurred_at=_aware(event.occurred_at),
        )
        if event.event_hash != calculate_payload_hash(expected):
            reasons.append("SHADOW_SCHEDULER_EVENT_HASH_INVALID")
        previous_hash = event.event_hash
    if state.latest_event_sequence != len(events):
        reasons.append("SHADOW_SCHEDULER_LATEST_SEQUENCE_INVALID")
    if state.latest_event_hash != previous_hash:
        reasons.append("SHADOW_SCHEDULER_LATEST_HASH_INVALID")
    return sorted(set(reasons))


def _get_state(
    db: Session, *, for_update: bool = False
) -> CanonicalParserShadowSchedulerState | None:
    statement = select(CanonicalParserShadowSchedulerState).where(
        CanonicalParserShadowSchedulerState.scheduler_name == SHADOW_SCHEDULER_NAME
    )
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def _serialize_state(
    db: Session,
    state: CanonicalParserShadowSchedulerState | None,
    *,
    evaluated_at: datetime | None = None,
    settings_object: Any = settings,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _policy_snapshot(settings_object)
    if state is None:
        return {
            "exists": False,
            "scheduler_name": SHADOW_SCHEDULER_NAME,
            "status": "STOPPED",
            "generation": 0,
            "kill_switch_engaged": False,
            "lock_active": False,
            "heartbeat_stale": False,
            "scheduler_ready": False,
            "scheduler_enabled": bool(
                getattr(settings_object, "CANONICAL_PARSER_SHADOW_SCHEDULER_ENABLED", False)
            ),
            "policy": policy,
            "automatic_loop_connected": False,
            "worker_connected": False,
        }
    lock_expires = _aware(state.lock_expires_at) if state.lock_expires_at else None
    lock_active = bool(state.lock_token_hash and lock_expires and lock_expires > now)
    heartbeat = _aware(state.heartbeat_at) if state.heartbeat_at else None
    heartbeat_stale = bool(
        heartbeat
        and (now - heartbeat).total_seconds() > policy["heartbeat_timeout_seconds"]
    )
    audit_reasons = _verify_event_chain(db, state)
    return {
        "exists": True,
        "scheduler_name": state.scheduler_name,
        "status": state.status,
        "generation": state.generation,
        "kill_switch_engaged": state.kill_switch_engaged,
        "kill_reason": state.kill_reason,
        "interval_seconds": state.interval_seconds,
        "event_reservation": state.event_reservation,
        "execution_limit": state.execution_limit,
        "permit_id": state.permit_id,
        "lock_owner": state.lock_owner,
        "lock_token_hash": state.lock_token_hash,
        "lock_acquired_at": state.lock_acquired_at,
        "lock_expires_at": state.lock_expires_at,
        "lock_active": lock_active,
        "heartbeat_at": state.heartbeat_at,
        "heartbeat_stale": heartbeat_stale,
        "next_run_not_before": state.next_run_not_before,
        "latest_tick_id": state.latest_tick_id,
        "latest_cycle_id": state.latest_cycle_id,
        "scheduler_policy_version": state.scheduler_policy_version,
        "scheduler_policy_hash": state.scheduler_policy_hash,
        "scheduler_policy_snapshot": state.scheduler_policy_snapshot,
        "latest_event_sequence": state.latest_event_sequence,
        "latest_event_hash": state.latest_event_hash,
        "audit_chain_valid": not audit_reasons,
        "audit_reason_codes": audit_reasons,
        "scheduler_enabled": bool(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_SCHEDULER_ENABLED", False)
        ),
        "scheduler_ready": (
            state.status == "RUNNING"
            and not state.kill_switch_engaged
            and not heartbeat_stale
            and not audit_reasons
        ),
        "automatic_loop_connected": False,
        "worker_connected": False,
        "external_requests": 0,
        "writes_trades": False,
        "paper_execution": False,
        "live_execution": False,
    }


def _serialize_tick(tick: CanonicalParserShadowSchedulerTick) -> dict[str, Any]:
    return {
        "tick_id": tick.tick_id,
        "tick_key": tick.tick_key,
        "scheduler_generation": tick.scheduler_generation,
        "cycle_id": tick.cycle_id,
        "permit_id": tick.permit_id,
        "status": tick.status,
        "lock_token_hash": tick.lock_token_hash,
        "requested_event_reservation": tick.requested_event_reservation,
        "requested_limit": tick.requested_limit,
        "raw_event_ids": list(tick.raw_event_ids or []),
        "actor_label": tick.actor_label,
        "note": tick.note,
        "reason_codes": list(tick.reason_codes or []),
        "cycle_snapshot": tick.cycle_snapshot,
        "technical_metadata": tick.technical_metadata,
        "started_at": tick.started_at,
        "completed_at": tick.completed_at,
    }


def preview_shadow_scheduler_start(
    *,
    permit_id: str,
    interval_seconds: int = 300,
    event_reservation: int = 10,
    limit: int = 10,
    settings_object: Any = settings,
) -> dict[str, Any]:
    policy = _policy_snapshot(settings_object)
    blockers: set[str] = set()
    if not str(permit_id or "").strip():
        blockers.add("SHADOW_SCHEDULER_PERMIT_REQUIRED")
    if interval_seconds < policy["minimum_interval_seconds"]:
        blockers.add("SHADOW_SCHEDULER_INTERVAL_BELOW_MINIMUM")
    if interval_seconds > policy["maximum_interval_seconds"]:
        blockers.add("SHADOW_SCHEDULER_INTERVAL_ABOVE_MAXIMUM")
    if event_reservation < 1 or event_reservation > policy["maximum_event_reservation"]:
        blockers.add("SHADOW_SCHEDULER_EVENT_RESERVATION_INVALID")
    if limit < 1 or limit > policy["maximum_execution_limit"]:
        blockers.add("SHADOW_SCHEDULER_LIMIT_INVALID")
    if limit > event_reservation:
        blockers.add("SHADOW_SCHEDULER_LIMIT_EXCEEDS_RESERVATION")
    manifest = {
        "permit_id": permit_id,
        "interval_seconds": int(interval_seconds),
        "event_reservation": int(event_reservation),
        "limit": int(limit),
        "scheduler_policy_hash": calculate_payload_hash(policy),
    }
    key = calculate_payload_hash(manifest)
    return {
        "startable": not blockers,
        "reason_codes": sorted(blockers),
        "manifest": manifest,
        "scheduler_key": key,
        "confirmation": f"{SHADOW_SCHEDULER_START_PREFIX}:{permit_id}:{key[:16]}",
        "policy": policy,
        "scheduler_enabled": bool(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_SCHEDULER_ENABLED", False)
        ),
        "manual_tick_only": True,
        "automatic_loop_connected": False,
        "worker_connected": False,
    }


def start_shadow_scheduler(
    db: Session,
    *,
    confirmation: str,
    permit_id: str,
    interval_seconds: int = 300,
    event_reservation: int = 10,
    limit: int = 10,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    started_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_SHADOW_SCHEDULER_ENABLED", False)):
        raise CanonicalParserShadowSchedulerError(
            "Shadow scheduler disabilitato.",
            code="CANONICAL_PARSER_SHADOW_SCHEDULER_DISABLED",
            status_code=409,
        )
    preview = preview_shadow_scheduler_start(
        permit_id=permit_id,
        interval_seconds=interval_seconds,
        event_reservation=event_reservation,
        limit=limit,
        settings_object=settings_object,
    )
    if confirmation != preview["confirmation"]:
        raise CanonicalParserShadowSchedulerError(
            "Conferma avvio scheduler non valida.",
            code="SHADOW_SCHEDULER_START_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if not preview["startable"]:
        raise CanonicalParserShadowSchedulerError(
            "Scheduler non avviabile.",
            code="SHADOW_SCHEDULER_NOT_STARTABLE",
            status_code=409,
        )
    now = _aware(started_at)
    actor = _actor(actor_label)
    state = _get_state(db, for_update=True)
    if state is None:
        state = CanonicalParserShadowSchedulerState(
            scheduler_name=SHADOW_SCHEDULER_NAME,
            status="STOPPED",
            generation=0,
            kill_switch_engaged=False,
            kill_reason=None,
            interval_seconds=int(interval_seconds),
            event_reservation=int(event_reservation),
            execution_limit=int(limit),
            permit_id=permit_id,
            scheduler_policy_version=SHADOW_SCHEDULER_POLICY_VERSION,
            scheduler_policy_hash=calculate_payload_hash(preview["policy"]),
            scheduler_policy_snapshot=preview["policy"],
            lock_owner=None,
            lock_token_hash=None,
            lock_acquired_at=None,
            lock_expires_at=None,
            heartbeat_at=now,
            next_run_not_before=now,
            latest_tick_id=None,
            latest_cycle_id=None,
            actor_label=actor,
            note=_note(note),
            latest_event_sequence=0,
            latest_event_hash=None,
        )
        db.add(state)
        db.flush()
    elif state.status == "RUNNING" and not state.kill_switch_engaged:
        return _serialize_state(db, state, evaluated_at=now, settings_object=settings_object)
    state.generation = int(state.generation) + 1
    state.kill_switch_engaged = False
    state.kill_reason = None
    state.interval_seconds = int(interval_seconds)
    state.event_reservation = int(event_reservation)
    state.execution_limit = int(limit)
    state.permit_id = permit_id
    state.scheduler_policy_version = SHADOW_SCHEDULER_POLICY_VERSION
    state.scheduler_policy_hash = calculate_payload_hash(preview["policy"])
    state.scheduler_policy_snapshot = preview["policy"]
    state.lock_owner = None
    state.lock_token_hash = None
    state.lock_acquired_at = None
    state.lock_expires_at = None
    state.heartbeat_at = now
    state.next_run_not_before = now
    state.actor_label = actor
    state.note = _note(note)
    _append_event(
        db,
        state=state,
        event_type="STARTED",
        new_status="RUNNING",
        actor_label=actor,
        reason=_note(note),
        occurred_at=now,
    )
    db.commit()
    db.refresh(state)
    return _serialize_state(db, state, evaluated_at=now, settings_object=settings_object)


def _control_confirmation(prefix: str, state: CanonicalParserShadowSchedulerState) -> str:
    return f"{prefix}:{state.generation}:{(state.latest_event_hash or '0' * 64)[:16]}"


def stop_shadow_scheduler(
    db: Session,
    *,
    confirmation: str,
    reason: str,
    actor_label: str | None = None,
    stopped_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(stopped_at)
    state = _get_state(db, for_update=True)
    if state is None:
        raise CanonicalParserShadowSchedulerError(
            "Scheduler state non trovato.", code="SHADOW_SCHEDULER_STATE_NOT_FOUND", status_code=404
        )
    if confirmation != _control_confirmation(SHADOW_SCHEDULER_STOP_PREFIX, state):
        raise CanonicalParserShadowSchedulerError(
            "Conferma stop scheduler non valida.",
            code="SHADOW_SCHEDULER_STOP_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if state.status == "STOPPED":
        return _serialize_state(db, state, evaluated_at=now)
    state.lock_owner = None
    state.lock_token_hash = None
    state.lock_acquired_at = None
    state.lock_expires_at = None
    _append_event(
        db,
        state=state,
        event_type="STOPPED",
        new_status="STOPPED",
        actor_label=_actor(actor_label),
        reason=_note(reason),
        occurred_at=now,
    )
    db.commit()
    db.refresh(state)
    return _serialize_state(db, state, evaluated_at=now)


def engage_shadow_scheduler_kill_switch(
    db: Session,
    *,
    confirmation: str,
    reason: str,
    actor_label: str | None = None,
    killed_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(killed_at)
    state = _get_state(db, for_update=True)
    if state is None:
        raise CanonicalParserShadowSchedulerError(
            "Scheduler state non trovato.", code="SHADOW_SCHEDULER_STATE_NOT_FOUND", status_code=404
        )
    if confirmation != _control_confirmation(SHADOW_SCHEDULER_KILL_PREFIX, state):
        raise CanonicalParserShadowSchedulerError(
            "Conferma kill switch non valida.",
            code="SHADOW_SCHEDULER_KILL_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    state.kill_switch_engaged = True
    state.kill_reason = _note(reason) or "MANUAL_KILL_SWITCH"
    state.lock_owner = None
    state.lock_token_hash = None
    state.lock_acquired_at = None
    state.lock_expires_at = None
    _append_event(
        db,
        state=state,
        event_type="KILLED",
        new_status="KILLED",
        actor_label=_actor(actor_label),
        reason=state.kill_reason,
        occurred_at=now,
    )
    db.commit()
    db.refresh(state)
    return _serialize_state(db, state, evaluated_at=now)


def reset_shadow_scheduler_kill_switch(
    db: Session,
    *,
    confirmation: str,
    reason: str,
    actor_label: str | None = None,
    reset_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(reset_at)
    state = _get_state(db, for_update=True)
    if state is None:
        raise CanonicalParserShadowSchedulerError(
            "Scheduler state non trovato.", code="SHADOW_SCHEDULER_STATE_NOT_FOUND", status_code=404
        )
    if confirmation != _control_confirmation(SHADOW_SCHEDULER_RESET_PREFIX, state):
        raise CanonicalParserShadowSchedulerError(
            "Conferma reset kill switch non valida.",
            code="SHADOW_SCHEDULER_RESET_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    state.kill_switch_engaged = False
    state.kill_reason = None
    state.generation = int(state.generation) + 1
    state.heartbeat_at = now
    state.next_run_not_before = now
    _append_event(
        db,
        state=state,
        event_type="RESET",
        new_status="STOPPED",
        actor_label=_actor(actor_label),
        reason=_note(reason),
        occurred_at=now,
    )
    db.commit()
    db.refresh(state)
    return _serialize_state(db, state, evaluated_at=now)


def heartbeat_shadow_scheduler(
    db: Session,
    *,
    confirmation: str,
    actor_label: str | None = None,
    heartbeat_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(heartbeat_at)
    state = _get_state(db, for_update=True)
    if state is None:
        raise CanonicalParserShadowSchedulerError(
            "Scheduler state non trovato.", code="SHADOW_SCHEDULER_STATE_NOT_FOUND", status_code=404
        )
    expected = _control_confirmation(SHADOW_SCHEDULER_HEARTBEAT_PREFIX, state)
    if confirmation != expected:
        raise CanonicalParserShadowSchedulerError(
            "Conferma heartbeat non valida.",
            code="SHADOW_SCHEDULER_HEARTBEAT_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if state.status != "RUNNING" or state.kill_switch_engaged:
        raise CanonicalParserShadowSchedulerError(
            "Heartbeat consentito solo con scheduler RUNNING e kill switch disinserito.",
            code="SHADOW_SCHEDULER_HEARTBEAT_NOT_ALLOWED",
            status_code=409,
        )
    state.heartbeat_at = now
    _append_event(
        db,
        state=state,
        event_type="HEARTBEAT",
        new_status="RUNNING",
        actor_label=_actor(actor_label),
        reason="MANUAL_CONTROL_PLANE_HEARTBEAT",
        occurred_at=now,
    )
    db.commit()
    db.refresh(state)
    return _serialize_state(db, state, evaluated_at=now)


def preview_shadow_scheduler_tick(
    db: Session,
    *,
    raw_event_ids: list[int] | None = None,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    state = _get_state(db)
    state_payload = _serialize_state(db, state, evaluated_at=now, settings_object=settings_object)
    ids = _normalize_event_ids(raw_event_ids)
    blockers: set[str] = set()
    if state is None:
        blockers.add("SHADOW_SCHEDULER_STATE_MISSING")
    else:
        if state.status != "RUNNING":
            blockers.add("SHADOW_SCHEDULER_NOT_RUNNING")
        if state.kill_switch_engaged:
            blockers.add("SHADOW_SCHEDULER_KILL_SWITCH_ENGAGED")
        if state_payload["heartbeat_stale"]:
            blockers.add("SHADOW_SCHEDULER_HEARTBEAT_STALE")
        if not state_payload["audit_chain_valid"]:
            blockers.add("SHADOW_SCHEDULER_AUDIT_CHAIN_INVALID")
        if state_payload["lock_active"]:
            blockers.add("SHADOW_SCHEDULER_LOCK_HELD")
        if state.next_run_not_before and _aware(state.next_run_not_before) > now:
            blockers.add("SHADOW_SCHEDULER_INTERVAL_NOT_ELAPSED")
    cycle_preview: dict[str, Any] = {}
    if state is not None:
        cycle_preview = preview_shadow_automation_cycle(
            db,
            permit_id=state.permit_id,
            raw_event_ids=ids,
            event_reservation=state.event_reservation,
            limit=state.execution_limit,
            settings_object=settings_object,
            registry=registry,
            evaluated_at=now,
        )
        if not cycle_preview.get("eligible"):
            blockers.update(cycle_preview.get("blocker_codes") or [])
            blockers.add("SHADOW_SCHEDULER_CYCLE_NOT_ELIGIBLE")
    manifest = {
        "scheduler_name": SHADOW_SCHEDULER_NAME,
        "generation": state.generation if state else 0,
        "latest_event_hash": state.latest_event_hash if state else None,
        "permit_id": state.permit_id if state else None,
        "raw_event_ids": ids,
        "cycle_key": cycle_preview.get("cycle_key"),
    }
    tick_key = calculate_payload_hash(manifest)
    return {
        "tickable": not blockers,
        "reason_codes": sorted(blockers),
        "state": state_payload,
        "cycle_preview": sanitize_technical_metadata(cycle_preview),
        "tick_manifest": manifest,
        "tick_key": tick_key,
        "confirmation": f"{SHADOW_SCHEDULER_TICK_PREFIX}:{state.generation if state else 0}:{tick_key[:16]}",
        "manual_tick_only": True,
        "automatic_loop_connected": False,
        "worker_connected": False,
    }


def run_shadow_scheduler_tick(
    db: Session,
    *,
    confirmation: str,
    raw_event_ids: list[int] | None = None,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_SHADOW_SCHEDULER_ENABLED", False)):
        raise CanonicalParserShadowSchedulerError(
            "Shadow scheduler disabilitato.",
            code="CANONICAL_PARSER_SHADOW_SCHEDULER_DISABLED",
            status_code=409,
        )
    now = _aware(started_at)
    preview = preview_shadow_scheduler_tick(
        db,
        raw_event_ids=raw_event_ids,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=now,
    )
    if confirmation != preview["confirmation"]:
        raise CanonicalParserShadowSchedulerError(
            "Conferma tick scheduler non valida o non aggiornata.",
            code="SHADOW_SCHEDULER_TICK_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if not preview["tickable"]:
        raise CanonicalParserShadowSchedulerError(
            "Scheduler tick non eseguibile: " + ", ".join(preview["reason_codes"]),
            code="SHADOW_SCHEDULER_TICK_NOT_ALLOWED",
            status_code=409,
        )
    state = _get_state(db, for_update=True)
    if state is None:
        raise CanonicalParserShadowSchedulerError(
            "Scheduler state non trovato.", code="SHADOW_SCHEDULER_STATE_NOT_FOUND", status_code=404
        )
    current = _serialize_state(db, state, evaluated_at=now, settings_object=settings_object)
    if not current["scheduler_ready"] or current["lock_active"]:
        raise CanonicalParserShadowSchedulerError(
            "Scheduler state cambiato dopo la preview.",
            code="SHADOW_SCHEDULER_STATE_DRIFT",
            status_code=409,
        )
    lock_token = str(uuid4())
    lock_hash = calculate_payload_hash({"scheduler": state.scheduler_name, "token": lock_token})
    tick = CanonicalParserShadowSchedulerTick(
        tick_id=str(uuid4()),
        tick_key=preview["tick_key"],
        scheduler_state_db_id=state.id,
        scheduler_generation=state.generation,
        cycle_db_id=None,
        cycle_id=None,
        permit_id=state.permit_id,
        status="RUNNING",
        lock_token_hash=lock_hash,
        requested_event_reservation=state.event_reservation,
        requested_limit=state.execution_limit,
        raw_event_ids=_normalize_event_ids(raw_event_ids),
        actor_label=_actor(actor_label),
        note=_note(note),
        reason_codes=[],
        cycle_snapshot={},
        technical_metadata={
            "manual_tick_only": True,
            "database_lock": True,
            "heartbeat": True,
            "kill_switch": True,
            "automatic_loop_connected": False,
            "worker_connected": False,
            "external_requests": 0,
            "writes_trades": False,
            "paper_execution": False,
            "live_execution": False,
        },
        started_at=now,
        completed_at=None,
    )
    db.add(tick)
    try:
        db.flush()
        state.lock_owner = tick.tick_id
        state.lock_token_hash = lock_hash
        state.lock_acquired_at = now
        state.lock_expires_at = now + timedelta(
            seconds=_policy_snapshot(settings_object)["lock_ttl_seconds"]
        )
        state.heartbeat_at = now
        state.latest_tick_id = tick.tick_id
        _append_event(
            db,
            state=state,
            event_type="TICK_ACQUIRED",
            new_status="RUNNING",
            actor_label=tick.actor_label,
            reason=tick.tick_id,
            occurred_at=now,
        )
        db.commit()
    except IntegrityError as exception:
        db.rollback()
        existing = db.scalar(
            select(CanonicalParserShadowSchedulerTick).where(
                CanonicalParserShadowSchedulerTick.tick_key == preview["tick_key"]
            )
        )
        if existing is not None:
            return _serialize_tick(existing)
        raise CanonicalParserShadowSchedulerError(
            "Conflitto durante l'acquisizione del tick.",
            code="SHADOW_SCHEDULER_TICK_CONFLICT",
            status_code=409,
        ) from exception
    try:
        cycle_preview = preview_shadow_automation_cycle(
            db,
            permit_id=state.permit_id,
            raw_event_ids=tick.raw_event_ids,
            event_reservation=state.event_reservation,
            limit=state.execution_limit,
            settings_object=settings_object,
            registry=registry,
            evaluated_at=now,
        )
        cycle_payload = run_shadow_automation_cycle(
            db,
            confirmation=cycle_preview["confirmation"],
            permit_id=state.permit_id,
            raw_event_ids=tick.raw_event_ids,
            event_reservation=state.event_reservation,
            limit=state.execution_limit,
            actor_label=tick.actor_label,
            note=f"M18 scheduler tick {tick.tick_id}",
            settings_object=settings_object,
            registry=registry,
            started_at=now,
            completed_at=_aware(completed_at),
        )
        final_time = _aware(completed_at)
        state = _get_state(db, for_update=True)
        tick = db.scalar(
            select(CanonicalParserShadowSchedulerTick)
            .where(CanonicalParserShadowSchedulerTick.tick_id == tick.tick_id)
            .with_for_update()
        )
        assert state is not None and tick is not None
        cycle = db.scalar(
            select(CanonicalParserShadowAutomationCycle).where(
                CanonicalParserShadowAutomationCycle.cycle_id == cycle_payload["cycle_id"]
            )
        )
        interlock_reasons: list[str] = []
        if state.kill_switch_engaged or state.status == "KILLED":
            interlock_reasons.append("SHADOW_SCHEDULER_KILL_SWITCH_TRIPPED")
        if state.lock_token_hash != lock_hash:
            interlock_reasons.append("SHADOW_SCHEDULER_LOCK_TOKEN_DRIFT")
        terminal_status = cycle_payload["status"]
        if interlock_reasons:
            terminal_status = "KILLED"
        elif terminal_status not in {"PASSED", "PARTIAL"}:
            terminal_status = "FAILED"
        tick.cycle_db_id = cycle.id if cycle is not None else None
        tick.cycle_id = cycle_payload["cycle_id"]
        tick.status = terminal_status
        tick.reason_codes = sorted(
            set(interlock_reasons + list(cycle_payload.get("reason_codes") or []))
        )
        tick.cycle_snapshot = sanitize_technical_metadata(cycle_payload)
        tick.completed_at = final_time
        state.latest_cycle_id = tick.cycle_id
        state.heartbeat_at = final_time
        state.next_run_not_before = final_time + timedelta(seconds=state.interval_seconds)
        state.lock_owner = None
        state.lock_token_hash = None
        state.lock_acquired_at = None
        state.lock_expires_at = None
        event_type = "TICK_COMPLETED" if terminal_status in {"PASSED", "PARTIAL"} else "TICK_FAILED"
        _append_event(
            db,
            state=state,
            event_type=event_type,
            new_status=state.status,
            actor_label=tick.actor_label,
            reason=f"{tick.tick_id}:{terminal_status}",
            occurred_at=final_time,
        )
        db.commit()
        db.refresh(tick)
        return _serialize_tick(tick)
    except CanonicalParserShadowAutomationCycleError as exception:
        db.rollback()
        final_time = _aware(completed_at)
        state = _get_state(db, for_update=True)
        tick = db.scalar(
            select(CanonicalParserShadowSchedulerTick)
            .where(CanonicalParserShadowSchedulerTick.tick_key == preview["tick_key"])
            .with_for_update()
        )
        if state is not None:
            if state.lock_token_hash == lock_hash:
                state.lock_owner = None
                state.lock_token_hash = None
                state.lock_acquired_at = None
                state.lock_expires_at = None
            state.heartbeat_at = final_time
        if tick is not None:
            tick.status = "FAILED"
            tick.reason_codes = [getattr(exception, "code", "SHADOW_SCHEDULER_CYCLE_FAILED")]
            tick.technical_metadata = {
                **(tick.technical_metadata or {}),
                "error": sanitize_error_message(exception, max_length=_MAX_ERROR_LENGTH),
            }
            tick.completed_at = final_time
        if state is not None:
            _append_event(
                db,
                state=state,
                event_type="TICK_FAILED",
                new_status=state.status,
                actor_label=_actor(actor_label),
                reason=sanitize_error_message(exception, max_length=_MAX_ERROR_LENGTH),
                occurred_at=final_time,
            )
        db.commit()
        raise CanonicalParserShadowSchedulerError(
            "Scheduler tick fallito: " + str(exception),
            code="SHADOW_SCHEDULER_TICK_CYCLE_FAILED",
            status_code=getattr(exception, "status_code", 409),
        ) from exception


def get_shadow_scheduler_state(
    db: Session,
    *,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    return _serialize_state(
        db,
        _get_state(db),
        evaluated_at=evaluated_at,
        settings_object=settings_object,
    )


def get_shadow_scheduler_tick(db: Session, tick_id: str) -> dict[str, Any]:
    tick = db.scalar(
        select(CanonicalParserShadowSchedulerTick).where(
            CanonicalParserShadowSchedulerTick.tick_id == str(tick_id or "").strip()
        )
    )
    if tick is None:
        raise CanonicalParserShadowSchedulerError(
            "Scheduler tick non trovato.",
            code="SHADOW_SCHEDULER_TICK_NOT_FOUND",
            status_code=404,
        )
    return _serialize_tick(tick)


def get_shadow_scheduler_status(
    db: Session,
    *,
    settings_object: Any = settings,
) -> dict[str, Any]:
    counts = dict(
        db.execute(
            select(
                CanonicalParserShadowSchedulerTick.status,
                func.count(CanonicalParserShadowSchedulerTick.id),
            ).group_by(CanonicalParserShadowSchedulerTick.status)
        ).all()
    )
    return {
        "scheduler_enabled": bool(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_SCHEDULER_ENABLED", False)
        ),
        "policy_version": SHADOW_SCHEDULER_POLICY_VERSION,
        "scheduler_name": SHADOW_SCHEDULER_NAME,
        "state": get_shadow_scheduler_state(db, settings_object=settings_object),
        "tick_count": int(sum(counts.values())),
        "tick_status_counts": {
            status: int(counts.get(status, 0))
            for status in ("RUNNING", "PASSED", "PARTIAL", "FAILED", "SKIPPED", "KILLED")
        },
        "policy": _policy_snapshot(settings_object),
        "operational_guards": {
            "manual_tick_only": True,
            "automatic_loop_connected": False,
            "worker_connected": False,
            "external_requests": 0,
            "writes_trades": False,
            "paper_execution": False,
            "live_execution": False,
        },
    }
