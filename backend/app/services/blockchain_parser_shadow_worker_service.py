from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserShadowSchedulerTick,
    CanonicalParserShadowSchedulerWorkerEvent,
    CanonicalParserShadowSchedulerWorkerIteration,
    CanonicalParserShadowSchedulerWorkerState,
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
from backend.app.services.blockchain_parser_shadow_scheduler_service import (
    CanonicalParserShadowSchedulerError,
    get_shadow_scheduler_state,
    preview_shadow_scheduler_tick,
    run_shadow_scheduler_tick,
)

SHADOW_WORKER_POLICY_VERSION = "canonical-parser-shadow-worker/1"
SHADOW_WORKER_NAME = "CANONICAL_SHADOW_SCHEDULER_WORKER"
SHADOW_WORKER_START_PREFIX = "START_CERTIFIED_SHADOW_WORKER"
SHADOW_WORKER_STOP_PREFIX = "STOP_CERTIFIED_SHADOW_WORKER"
SHADOW_WORKER_KILL_PREFIX = "KILL_CERTIFIED_SHADOW_WORKER"
SHADOW_WORKER_RESET_PREFIX = "RESET_CERTIFIED_SHADOW_WORKER"
SHADOW_WORKER_HEARTBEAT_PREFIX = "HEARTBEAT_CERTIFIED_SHADOW_WORKER"
SHADOW_WORKER_ITERATION_PREFIX = "ITERATE_CERTIFIED_SHADOW_WORKER"
_MAX_ACTOR_LENGTH = 80
_MAX_NOTE_LENGTH = 500
_MAX_ERROR_LENGTH = 1000


class CanonicalParserShadowWorkerError(ValueError):
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
    return sanitize_error_message(value or "LOCAL_WORKER", max_length=_MAX_ACTOR_LENGTH) or "LOCAL_WORKER"


def _note(value: str | None) -> str | None:
    if not str(value or "").strip():
        return None
    return sanitize_error_message(value, max_length=_MAX_NOTE_LENGTH)


def _owner(value: str | None) -> str:
    normalized = sanitize_error_message(value or "LOCAL_WORKER_INSTANCE", max_length=80)
    if not normalized:
        raise CanonicalParserShadowWorkerError(
            "Owner worker non valido.", code="SHADOW_WORKER_OWNER_INVALID"
        )
    return normalized


def _policy_snapshot(settings_object: Any) -> dict[str, Any]:
    return {
        "policy_version": SHADOW_WORKER_POLICY_VERSION,
        "worker_name": SHADOW_WORKER_NAME,
        "lease_ttl_seconds": int(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_WORKER_LEASE_TTL_SECONDS", 120)
        ),
        "heartbeat_timeout_seconds": int(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_WORKER_HEARTBEAT_TIMEOUT_SECONDS", 180)
        ),
        "maximum_consecutive_failures": int(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_WORKER_MAX_CONSECUTIVE_FAILURES", 3)
        ),
        "single_iteration_only": True,
        "background_loop_connected": False,
        "thread_created": False,
        "network_allowed": False,
        "writes_trades": False,
        "paper_execution": False,
        "live_execution": False,
    }


def _event_payload(*, event_id: str, state: CanonicalParserShadowSchedulerWorkerState,
                   sequence: int, event_type: str, previous_status: str | None,
                   new_status: str, actor_label: str, reason: str | None,
                   previous_event_hash: str | None, occurred_at: datetime) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "worker_name": state.worker_name,
        "sequence": sequence,
        "event_type": event_type,
        "previous_status": previous_status,
        "new_status": new_status,
        "actor_label": actor_label,
        "reason": reason,
        "previous_event_hash": previous_event_hash,
        "occurred_at": occurred_at.isoformat(),
    }


def _append_event(db: Session, *, state: CanonicalParserShadowSchedulerWorkerState,
                  event_type: str, new_status: str, actor_label: str,
                  reason: str | None, occurred_at: datetime) -> None:
    sequence = int(state.latest_event_sequence or 0) + 1
    event_id = str(uuid4())
    payload = _event_payload(
        event_id=event_id, state=state, sequence=sequence, event_type=event_type,
        previous_status=state.status, new_status=new_status, actor_label=actor_label,
        reason=reason, previous_event_hash=state.latest_event_hash, occurred_at=occurred_at,
    )
    event_hash = calculate_payload_hash(payload)
    db.add(CanonicalParserShadowSchedulerWorkerEvent(
        event_id=event_id,
        worker_state_db_id=state.id,
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
    ))
    state.status = new_status
    state.latest_event_sequence = sequence
    state.latest_event_hash = event_hash


def _verify_event_chain(db: Session, state: CanonicalParserShadowSchedulerWorkerState) -> list[str]:
    reasons: list[str] = []
    events = list(db.scalars(
        select(CanonicalParserShadowSchedulerWorkerEvent)
        .where(CanonicalParserShadowSchedulerWorkerEvent.worker_state_db_id == state.id)
        .order_by(CanonicalParserShadowSchedulerWorkerEvent.sequence.asc())
    ))
    previous_hash: str | None = None
    for expected_sequence, event in enumerate(events, start=1):
        if event.sequence != expected_sequence:
            reasons.append("SHADOW_WORKER_EVENT_SEQUENCE_INVALID")
        if event.previous_event_hash != previous_hash:
            reasons.append("SHADOW_WORKER_EVENT_CHAIN_BROKEN")
        expected = _event_payload(
            event_id=event.event_id, state=state, sequence=event.sequence,
            event_type=event.event_type, previous_status=event.previous_status,
            new_status=event.new_status, actor_label=event.actor_label,
            reason=event.reason, previous_event_hash=event.previous_event_hash,
            occurred_at=_aware(event.occurred_at),
        )
        if event.event_hash != calculate_payload_hash(expected):
            reasons.append("SHADOW_WORKER_EVENT_HASH_INVALID")
        previous_hash = event.event_hash
    if state.latest_event_sequence != len(events):
        reasons.append("SHADOW_WORKER_LATEST_SEQUENCE_INVALID")
    if state.latest_event_hash != previous_hash:
        reasons.append("SHADOW_WORKER_LATEST_HASH_INVALID")
    return sorted(set(reasons))


def _get_state(db: Session, *, for_update: bool = False) -> CanonicalParserShadowSchedulerWorkerState | None:
    statement = select(CanonicalParserShadowSchedulerWorkerState).where(
        CanonicalParserShadowSchedulerWorkerState.worker_name == SHADOW_WORKER_NAME
    )
    if for_update:
        statement = statement.with_for_update()
    return db.scalar(statement)


def _serialize_state(db: Session, state: CanonicalParserShadowSchedulerWorkerState | None,
                     *, evaluated_at: datetime | None = None,
                     settings_object: Any = settings) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _policy_snapshot(settings_object)
    if state is None:
        return {
            "exists": False,
            "worker_name": SHADOW_WORKER_NAME,
            "status": "STOPPED",
            "generation": 0,
            "lease_epoch": 0,
            "worker_ready": False,
            "worker_enabled": bool(getattr(settings_object, "CANONICAL_PARSER_SHADOW_WORKER_ENABLED", False)),
            "background_loop_connected": False,
            "policy": policy,
        }
    lease_expires = _aware(state.lease_expires_at) if state.lease_expires_at else None
    lease_active = bool(state.lease_token_hash and lease_expires and lease_expires > now)
    heartbeat = _aware(state.heartbeat_at) if state.heartbeat_at else None
    heartbeat_stale = bool(
        heartbeat and (now - heartbeat).total_seconds() > policy["heartbeat_timeout_seconds"]
    )
    audit_reasons = _verify_event_chain(db, state)
    worker_ready = (
        state.status == "ACTIVE" and lease_active and not heartbeat_stale and not audit_reasons
    )
    return {
        "exists": True,
        "worker_name": state.worker_name,
        "status": state.status,
        "generation": state.generation,
        "owner_id": state.owner_id,
        "lease_epoch": state.lease_epoch,
        "lease_token_hash": state.lease_token_hash,
        "lease_acquired_at": state.lease_acquired_at,
        "lease_expires_at": state.lease_expires_at,
        "lease_active": lease_active,
        "heartbeat_at": state.heartbeat_at,
        "heartbeat_stale": heartbeat_stale,
        "consecutive_failures": state.consecutive_failures,
        "latest_iteration_id": state.latest_iteration_id,
        "latest_tick_id": state.latest_tick_id,
        "kill_reason": state.kill_reason,
        "worker_policy_version": state.worker_policy_version,
        "worker_policy_hash": state.worker_policy_hash,
        "worker_policy_snapshot": state.worker_policy_snapshot,
        "latest_event_sequence": state.latest_event_sequence,
        "latest_event_hash": state.latest_event_hash,
        "audit_chain_valid": not audit_reasons,
        "audit_reason_codes": audit_reasons,
        "worker_ready": worker_ready,
        "worker_enabled": bool(getattr(settings_object, "CANONICAL_PARSER_SHADOW_WORKER_ENABLED", False)),
        "background_loop_connected": False,
        "thread_created": False,
        "external_requests": 0,
        "writes_trades": False,
        "paper_execution": False,
        "live_execution": False,
        "policy": policy,
    }


def _serialize_iteration(iteration: CanonicalParserShadowSchedulerWorkerIteration) -> dict[str, Any]:
    return {
        "iteration_id": iteration.iteration_id,
        "iteration_key": iteration.iteration_key,
        "worker_generation": iteration.worker_generation,
        "lease_epoch": iteration.lease_epoch,
        "owner_id": iteration.owner_id,
        "scheduler_generation": iteration.scheduler_generation,
        "tick_id": iteration.tick_id,
        "cycle_id": iteration.cycle_id,
        "status": iteration.status,
        "raw_event_ids": list(iteration.raw_event_ids or []),
        "actor_label": iteration.actor_label,
        "note": iteration.note,
        "reason_codes": list(iteration.reason_codes or []),
        "scheduler_preview": iteration.scheduler_preview,
        "tick_snapshot": iteration.tick_snapshot,
        "technical_metadata": iteration.technical_metadata,
        "started_at": iteration.started_at,
        "completed_at": iteration.completed_at,
    }


def preview_shadow_worker_start(*, owner_id: str, settings_object: Any = settings) -> dict[str, Any]:
    owner = _owner(owner_id)
    policy = _policy_snapshot(settings_object)
    manifest = {"worker_name": SHADOW_WORKER_NAME, "owner_id": owner, "policy_hash": calculate_payload_hash(policy)}
    worker_key = calculate_payload_hash(manifest)
    return {
        "startable": True,
        "reason_codes": [],
        "worker_key": worker_key,
        "manifest": manifest,
        "confirmation": f"{SHADOW_WORKER_START_PREFIX}:{owner}:{worker_key[:16]}",
        "worker_enabled": bool(getattr(settings_object, "CANONICAL_PARSER_SHADOW_WORKER_ENABLED", False)),
        "policy": policy,
    }


def start_shadow_worker(db: Session, *, confirmation: str, owner_id: str,
                        actor_label: str | None = None, note: str | None = None,
                        settings_object: Any = settings,
                        started_at: datetime | None = None) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_SHADOW_WORKER_ENABLED", False)):
        raise CanonicalParserShadowWorkerError(
            "Shadow worker disabilitato.", code="CANONICAL_PARSER_SHADOW_WORKER_DISABLED", status_code=409
        )
    preview = preview_shadow_worker_start(owner_id=owner_id, settings_object=settings_object)
    if confirmation != preview["confirmation"]:
        raise CanonicalParserShadowWorkerError(
            "Conferma avvio worker non valida.", code="SHADOW_WORKER_START_CONFIRMATION_REQUIRED", status_code=409
        )
    now = _aware(started_at)
    owner = _owner(owner_id)
    policy = _policy_snapshot(settings_object)
    state = _get_state(db, for_update=True)
    if state is not None:
        current = _serialize_state(db, state, evaluated_at=now, settings_object=settings_object)
        if current.get("worker_ready") and state.owner_id == owner:
            return current
        if current.get("lease_active") and state.owner_id != owner:
            raise CanonicalParserShadowWorkerError(
                "Worker lease già posseduta da un'altra istanza.", code="SHADOW_WORKER_LEASE_HELD", status_code=409
            )
        state.generation += 1
        state.lease_epoch += 1
        state.owner_id = owner
        state.lease_token_hash = calculate_payload_hash({"owner": owner, "epoch": state.lease_epoch, "nonce": str(uuid4())})
        state.lease_acquired_at = now
        state.lease_expires_at = now + timedelta(seconds=policy["lease_ttl_seconds"])
        state.heartbeat_at = now
        state.consecutive_failures = 0
        state.kill_reason = None
        state.worker_policy_version = SHADOW_WORKER_POLICY_VERSION
        state.worker_policy_hash = calculate_payload_hash(policy)
        state.worker_policy_snapshot = policy
        state.actor_label = _actor(actor_label)
        state.note = _note(note)
    else:
        state = CanonicalParserShadowSchedulerWorkerState(
            worker_name=SHADOW_WORKER_NAME,
            status="STOPPED",
            generation=1,
            owner_id=owner,
            lease_token_hash=calculate_payload_hash({"owner": owner, "epoch": 1, "nonce": str(uuid4())}),
            lease_epoch=1,
            lease_acquired_at=now,
            lease_expires_at=now + timedelta(seconds=policy["lease_ttl_seconds"]),
            heartbeat_at=now,
            consecutive_failures=0,
            latest_iteration_id=None,
            latest_tick_id=None,
            worker_policy_version=SHADOW_WORKER_POLICY_VERSION,
            worker_policy_hash=calculate_payload_hash(policy),
            worker_policy_snapshot=policy,
            actor_label=_actor(actor_label),
            note=_note(note),
            kill_reason=None,
            latest_event_sequence=0,
            latest_event_hash=None,
        )
        db.add(state)
        db.flush()
    _append_event(db, state=state, event_type="STARTED", new_status="ACTIVE",
                  actor_label=_actor(actor_label), reason=owner, occurred_at=now)
    db.commit()
    db.refresh(state)
    return _serialize_state(db, state, evaluated_at=now, settings_object=settings_object)


def _control_confirmation(prefix: str, state: CanonicalParserShadowSchedulerWorkerState, owner_id: str) -> str:
    return f"{prefix}:{state.generation}:{state.lease_epoch}:{_owner(owner_id)}:{(state.latest_event_hash or '0'*64)[:16]}"


def control_shadow_worker(db: Session, *, action: str, confirmation: str, owner_id: str,
                          reason: str, actor_label: str | None = None,
                          settings_object: Any = settings,
                          occurred_at: datetime | None = None) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_SHADOW_WORKER_ENABLED", False)):
        raise CanonicalParserShadowWorkerError("Shadow worker disabilitato.", code="CANONICAL_PARSER_SHADOW_WORKER_DISABLED", status_code=409)
    now = _aware(occurred_at)
    state = _get_state(db, for_update=True)
    if state is None:
        raise CanonicalParserShadowWorkerError("Worker state non trovato.", code="SHADOW_WORKER_STATE_NOT_FOUND", status_code=404)
    prefixes = {"STOP": SHADOW_WORKER_STOP_PREFIX, "KILL": SHADOW_WORKER_KILL_PREFIX, "RESET": SHADOW_WORKER_RESET_PREFIX}
    if action not in prefixes or confirmation != _control_confirmation(prefixes[action], state, owner_id):
        raise CanonicalParserShadowWorkerError("Conferma controllo worker non valida.", code="SHADOW_WORKER_CONTROL_CONFIRMATION_REQUIRED", status_code=409)
    if state.owner_id != _owner(owner_id) and action != "RESET":
        raise CanonicalParserShadowWorkerError("Owner worker non corrispondente.", code="SHADOW_WORKER_OWNER_MISMATCH", status_code=409)
    if action == "KILL":
        state.kill_reason = sanitize_error_message(reason, max_length=500)
        new_status, event_type = "KILLED", "KILLED"
    elif action == "RESET":
        state.generation += 1
        state.owner_id = None
        state.kill_reason = None
        new_status, event_type = "STOPPED", "RESET"
    else:
        new_status, event_type = "STOPPED", "STOPPED"
    state.lease_token_hash = None
    state.lease_acquired_at = None
    state.lease_expires_at = None
    state.heartbeat_at = now
    _append_event(db, state=state, event_type=event_type, new_status=new_status,
                  actor_label=_actor(actor_label), reason=sanitize_error_message(reason, max_length=500), occurred_at=now)
    db.commit()
    db.refresh(state)
    return _serialize_state(db, state, evaluated_at=now, settings_object=settings_object)


def heartbeat_shadow_worker(db: Session, *, confirmation: str, owner_id: str,
                            actor_label: str | None = None,
                            settings_object: Any = settings,
                            heartbeat_at: datetime | None = None) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_SHADOW_WORKER_ENABLED", False)):
        raise CanonicalParserShadowWorkerError("Shadow worker disabilitato.", code="CANONICAL_PARSER_SHADOW_WORKER_DISABLED", status_code=409)
    now = _aware(heartbeat_at)
    state = _get_state(db, for_update=True)
    if state is None:
        raise CanonicalParserShadowWorkerError("Worker state non trovato.", code="SHADOW_WORKER_STATE_NOT_FOUND", status_code=404)
    expected = _control_confirmation(SHADOW_WORKER_HEARTBEAT_PREFIX, state, owner_id)
    if confirmation != expected or state.owner_id != _owner(owner_id):
        raise CanonicalParserShadowWorkerError("Conferma heartbeat non valida.", code="SHADOW_WORKER_HEARTBEAT_CONFIRMATION_REQUIRED", status_code=409)
    if state.status != "ACTIVE":
        raise CanonicalParserShadowWorkerError("Worker non attivo.", code="SHADOW_WORKER_NOT_ACTIVE", status_code=409)
    state.heartbeat_at = now
    state.lease_expires_at = now + timedelta(seconds=_policy_snapshot(settings_object)["lease_ttl_seconds"])
    _append_event(db, state=state, event_type="HEARTBEAT", new_status="ACTIVE",
                  actor_label=_actor(actor_label), reason=state.owner_id, occurred_at=now)
    db.commit()
    db.refresh(state)
    return _serialize_state(db, state, evaluated_at=now, settings_object=settings_object)


def preview_shadow_worker_iteration(db: Session, *, owner_id: str,
                                    raw_event_ids: list[int] | None = None,
                                    settings_object: Any = settings,
                                    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
                                    evaluated_at: datetime | None = None) -> dict[str, Any]:
    now = _aware(evaluated_at)
    state = _get_state(db)
    state_payload = _serialize_state(db, state, evaluated_at=now, settings_object=settings_object)
    blockers: set[str] = set()
    owner = _owner(owner_id)
    if state is None:
        blockers.add("SHADOW_WORKER_STATE_MISSING")
    else:
        if state.owner_id != owner:
            blockers.add("SHADOW_WORKER_OWNER_MISMATCH")
        if not state_payload.get("worker_ready"):
            blockers.add("SHADOW_WORKER_NOT_READY")
        if state.consecutive_failures >= _policy_snapshot(settings_object)["maximum_consecutive_failures"]:
            blockers.add("SHADOW_WORKER_FAILURE_BUDGET_EXHAUSTED")
    scheduler_preview: dict[str, Any] = {}
    try:
        scheduler_preview = preview_shadow_scheduler_tick(
            db, raw_event_ids=raw_event_ids, settings_object=settings_object,
            registry=registry, evaluated_at=now,
        )
    except CanonicalParserShadowSchedulerError as exc:
        blockers.add(getattr(exc, "code", "SHADOW_WORKER_SCHEDULER_PREVIEW_FAILED"))
    manifest = {
        "worker_name": SHADOW_WORKER_NAME,
        "generation": state.generation if state else 0,
        "lease_epoch": state.lease_epoch if state else 0,
        "owner_id": owner,
        "latest_event_hash": state.latest_event_hash if state else None,
        "scheduler_tick_key": scheduler_preview.get("tick_key"),
        "evaluated_at": now.replace(microsecond=0).isoformat(),
    }
    iteration_key = calculate_payload_hash(manifest)
    return {
        "iterable": not blockers,
        "reason_codes": sorted(blockers),
        "worker_state": state_payload,
        "scheduler_preview": sanitize_technical_metadata(scheduler_preview),
        "iteration_key": iteration_key,
        "manifest": manifest,
        "confirmation": f"{SHADOW_WORKER_ITERATION_PREFIX}:{state.lease_epoch if state else 0}:{iteration_key[:16]}",
        "scheduler_tickable": bool(scheduler_preview.get("tickable")),
        "single_iteration_only": True,
        "background_loop_connected": False,
    }


def run_shadow_worker_iteration(db: Session, *, confirmation: str, owner_id: str,
                                raw_event_ids: list[int] | None = None,
                                actor_label: str | None = None, note: str | None = None,
                                settings_object: Any = settings,
                                registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
                                started_at: datetime | None = None,
                                completed_at: datetime | None = None) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_SHADOW_WORKER_ENABLED", False)):
        raise CanonicalParserShadowWorkerError("Shadow worker disabilitato.", code="CANONICAL_PARSER_SHADOW_WORKER_DISABLED", status_code=409)
    now = _aware(started_at)
    preview = preview_shadow_worker_iteration(
        db, owner_id=owner_id, raw_event_ids=raw_event_ids,
        settings_object=settings_object, registry=registry, evaluated_at=now,
    )
    if confirmation != preview["confirmation"]:
        raise CanonicalParserShadowWorkerError("Conferma iterazione non valida.", code="SHADOW_WORKER_ITERATION_CONFIRMATION_REQUIRED", status_code=409)
    if not preview["iterable"]:
        raise CanonicalParserShadowWorkerError(
            "Iterazione worker non consentita: " + ", ".join(preview["reason_codes"]),
            code="SHADOW_WORKER_ITERATION_NOT_ALLOWED", status_code=409,
        )
    existing = db.scalar(select(CanonicalParserShadowSchedulerWorkerIteration).where(
        CanonicalParserShadowSchedulerWorkerIteration.iteration_key == preview["iteration_key"]
    ))
    if existing is not None:
        return _serialize_iteration(existing)
    state = _get_state(db, for_update=True)
    assert state is not None
    current = _serialize_state(db, state, evaluated_at=now, settings_object=settings_object)
    if not current["worker_ready"] or state.owner_id != _owner(owner_id) or state.lease_epoch != preview["manifest"]["lease_epoch"]:
        raise CanonicalParserShadowWorkerError("Worker lease cambiata dopo la preview.", code="SHADOW_WORKER_FENCING_DRIFT", status_code=409)
    scheduler_generation = int((preview.get("scheduler_preview") or {}).get("state", {}).get("generation") or 0)
    iteration = CanonicalParserShadowSchedulerWorkerIteration(
        iteration_id=str(uuid4()), iteration_key=preview["iteration_key"],
        worker_state_db_id=state.id, worker_generation=state.generation,
        lease_epoch=state.lease_epoch, owner_id=state.owner_id or _owner(owner_id),
        scheduler_generation=scheduler_generation, tick_db_id=None, tick_id=None, cycle_id=None,
        status="RUNNING", raw_event_ids=list(raw_event_ids or []),
        actor_label=_actor(actor_label), note=_note(note), reason_codes=[],
        scheduler_preview=preview["scheduler_preview"], tick_snapshot={},
        technical_metadata={"single_iteration_only": True, "background_loop_connected": False,
                            "external_requests": 0, "writes_trades": False,
                            "paper_execution": False, "live_execution": False},
        started_at=now, completed_at=None,
    )
    db.add(iteration)
    try:
        db.flush()
        state.latest_iteration_id = iteration.iteration_id
        state.heartbeat_at = now
        state.lease_expires_at = now + timedelta(seconds=_policy_snapshot(settings_object)["lease_ttl_seconds"])
        _append_event(db, state=state, event_type="ITERATION_STARTED", new_status="ACTIVE",
                      actor_label=iteration.actor_label, reason=iteration.iteration_id, occurred_at=now)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(select(CanonicalParserShadowSchedulerWorkerIteration).where(
            CanonicalParserShadowSchedulerWorkerIteration.iteration_key == preview["iteration_key"]
        ))
        if existing is not None:
            return _serialize_iteration(existing)
        raise CanonicalParserShadowWorkerError("Conflitto iterazione worker.", code="SHADOW_WORKER_ITERATION_CONFLICT", status_code=409) from exc

    final_time = _aware(completed_at)
    if not preview["scheduler_tickable"]:
        state = _get_state(db, for_update=True)
        iteration = db.scalar(select(CanonicalParserShadowSchedulerWorkerIteration).where(
            CanonicalParserShadowSchedulerWorkerIteration.iteration_key == preview["iteration_key"]
        ).with_for_update())
        assert state is not None and iteration is not None
        reasons = list((preview.get("scheduler_preview") or {}).get("reason_codes") or [])
        iteration.status = "IDLE"
        iteration.reason_codes = reasons
        iteration.completed_at = final_time
        state.consecutive_failures = 0
        state.heartbeat_at = final_time
        _append_event(db, state=state, event_type="ITERATION_IDLE", new_status="ACTIVE",
                      actor_label=iteration.actor_label, reason=iteration.iteration_id, occurred_at=final_time)
        db.commit()
        db.refresh(iteration)
        return _serialize_iteration(iteration)

    try:
        tick_preview = preview["scheduler_preview"]
        tick_payload = run_shadow_scheduler_tick(
            db, confirmation=tick_preview["confirmation"], raw_event_ids=raw_event_ids,
            actor_label=_actor(actor_label), note=f"M19 worker iteration {iteration.iteration_id}",
            settings_object=settings_object, registry=registry,
            started_at=now, completed_at=final_time,
        )
        state = _get_state(db, for_update=True)
        iteration = db.scalar(select(CanonicalParserShadowSchedulerWorkerIteration).where(
            CanonicalParserShadowSchedulerWorkerIteration.iteration_key == preview["iteration_key"]
        ).with_for_update())
        assert state is not None and iteration is not None
        tick = db.scalar(select(CanonicalParserShadowSchedulerTick).where(
            CanonicalParserShadowSchedulerTick.tick_id == tick_payload.get("tick_id")
        ))
        status = str(tick_payload.get("status") or "FAILED")
        iteration.status = status if status in {"PASSED", "PARTIAL", "FAILED", "SKIPPED", "KILLED"} else "FAILED"
        iteration.tick_db_id = tick.id if tick else None
        iteration.tick_id = tick_payload.get("tick_id")
        iteration.cycle_id = tick_payload.get("cycle_id")
        iteration.reason_codes = list(tick_payload.get("reason_codes") or [])
        iteration.tick_snapshot = sanitize_technical_metadata(tick_payload)
        iteration.completed_at = final_time
        state.latest_tick_id = iteration.tick_id
        state.heartbeat_at = final_time
        if iteration.status in {"FAILED", "KILLED"}:
            state.consecutive_failures += 1
            event_type = "ITERATION_FAILED"
        else:
            state.consecutive_failures = 0
            event_type = "ITERATION_COMPLETED"
        _append_event(db, state=state, event_type=event_type, new_status=state.status,
                      actor_label=iteration.actor_label, reason=f"{iteration.iteration_id}:{iteration.status}", occurred_at=final_time)
        db.commit()
        db.refresh(iteration)
        return _serialize_iteration(iteration)
    except CanonicalParserShadowSchedulerError as exc:
        db.rollback()
        state = _get_state(db, for_update=True)
        iteration = db.scalar(select(CanonicalParserShadowSchedulerWorkerIteration).where(
            CanonicalParserShadowSchedulerWorkerIteration.iteration_key == preview["iteration_key"]
        ).with_for_update())
        if state is not None:
            state.consecutive_failures += 1
            state.heartbeat_at = final_time
        if iteration is not None:
            iteration.status = "FAILED"
            iteration.reason_codes = [getattr(exc, "code", "SHADOW_WORKER_SCHEDULER_FAILED")]
            iteration.technical_metadata = {**(iteration.technical_metadata or {}), "error": sanitize_error_message(exc, max_length=_MAX_ERROR_LENGTH)}
            iteration.completed_at = final_time
        if state is not None:
            _append_event(db, state=state, event_type="ITERATION_FAILED", new_status=state.status,
                          actor_label=_actor(actor_label), reason=sanitize_error_message(exc, max_length=_MAX_ERROR_LENGTH), occurred_at=final_time)
        db.commit()
        raise CanonicalParserShadowWorkerError(
            "Iterazione worker fallita: " + str(exc), code="SHADOW_WORKER_SCHEDULER_TICK_FAILED",
            status_code=getattr(exc, "status_code", 409),
        ) from exc


def get_shadow_worker_state(db: Session, *, settings_object: Any = settings,
                            evaluated_at: datetime | None = None) -> dict[str, Any]:
    return _serialize_state(db, _get_state(db), evaluated_at=evaluated_at, settings_object=settings_object)


def get_shadow_worker_iteration(db: Session, iteration_id: str) -> dict[str, Any]:
    iteration = db.scalar(select(CanonicalParserShadowSchedulerWorkerIteration).where(
        CanonicalParserShadowSchedulerWorkerIteration.iteration_id == str(iteration_id or "").strip()
    ))
    if iteration is None:
        raise CanonicalParserShadowWorkerError("Iterazione worker non trovata.", code="SHADOW_WORKER_ITERATION_NOT_FOUND", status_code=404)
    return _serialize_iteration(iteration)


def get_shadow_worker_status(db: Session, *, settings_object: Any = settings) -> dict[str, Any]:
    counts = dict(db.execute(select(
        CanonicalParserShadowSchedulerWorkerIteration.status,
        func.count(CanonicalParserShadowSchedulerWorkerIteration.id),
    ).group_by(CanonicalParserShadowSchedulerWorkerIteration.status)).all())
    return {
        "worker_enabled": bool(getattr(settings_object, "CANONICAL_PARSER_SHADOW_WORKER_ENABLED", False)),
        "policy_version": SHADOW_WORKER_POLICY_VERSION,
        "worker_name": SHADOW_WORKER_NAME,
        "state": get_shadow_worker_state(db, settings_object=settings_object),
        "iteration_count": int(sum(counts.values())),
        "iteration_status_counts": {status: int(counts.get(status, 0)) for status in (
            "RUNNING", "IDLE", "PASSED", "PARTIAL", "FAILED", "SKIPPED", "KILLED"
        )},
        "operational_guards": {
            "single_iteration_only": True,
            "background_loop_connected": False,
            "thread_created": False,
            "external_requests": 0,
            "writes_trades": False,
            "paper_execution": False,
            "live_execution": False,
        },
    }
