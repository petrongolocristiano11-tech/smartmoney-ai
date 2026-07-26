from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserShadowSchedulerWorkerIteration,
    CanonicalParserShadowSchedulerWorkerState,
    CanonicalParserShadowWorkerLoopIteration,
    CanonicalParserShadowWorkerLoopRun,
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
    SHADOW_SCHEDULER_KILL_PREFIX,
    CanonicalParserShadowSchedulerError,
    engage_shadow_scheduler_kill_switch,
    get_shadow_scheduler_state,
)
from backend.app.services.blockchain_parser_shadow_worker_service import (
    CanonicalParserShadowWorkerError,
    get_shadow_worker_state,
    preview_shadow_worker_iteration,
    run_shadow_worker_iteration,
)

SHADOW_WORKER_LOOP_POLICY_VERSION = "canonical-parser-shadow-worker-loop/1"
SHADOW_WORKER_LOOP_PREFIX = "RUN_BOUNDED_SHADOW_WORKER_LOOP"
_MAX_NOTE_LENGTH = 500


class CanonicalParserShadowWorkerLoopError(ValueError):
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


def _policy_snapshot(settings_object: Any) -> dict[str, Any]:
    return {
        "policy_version": SHADOW_WORKER_LOOP_POLICY_VERSION,
        "maximum_iterations": int(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_WORKER_LOOP_MAX_ITERATIONS", 5)
        ),
        "maximum_consecutive_failures": int(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_WORKER_LOOP_MAX_CONSECUTIVE_FAILURES", 2)
        ),
        "enforce_scheduler_kill_switch": bool(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_WORKER_LOOP_ENFORCE_KILL_SWITCH", False)
        ),
        "bounded_session": True,
        "background_daemon": False,
        "sleep_calls": False,
        "network_allowed": False,
        "writes_trades": False,
        "paper_execution": False,
        "live_execution": False,
    }


def _serialize_loop(loop: CanonicalParserShadowWorkerLoopRun) -> dict[str, Any]:
    return {
        "loop_id": loop.loop_id,
        "loop_key": loop.loop_key,
        "worker_generation": loop.worker_generation,
        "lease_epoch": loop.lease_epoch,
        "owner_id": loop.owner_id,
        "status": loop.status,
        "requested_iterations": loop.requested_iterations,
        "completed_iterations": loop.completed_iterations,
        "passed_iterations": loop.passed_iterations,
        "partial_iterations": loop.partial_iterations,
        "idle_iterations": loop.idle_iterations,
        "failed_iterations": loop.failed_iterations,
        "skipped_iterations": loop.skipped_iterations,
        "max_consecutive_failures": loop.max_consecutive_failures,
        "observed_consecutive_failures": loop.observed_consecutive_failures,
        "circuit_breaker_open": loop.circuit_breaker_open,
        "kill_switch_enforced": loop.kill_switch_enforced,
        "actor_label": loop.actor_label,
        "note": loop.note,
        "stop_reason": loop.stop_reason,
        "policy_snapshot": loop.policy_snapshot,
        "summary": loop.summary,
        "started_at": loop.started_at,
        "completed_at": loop.completed_at,
    }


def preview_shadow_worker_loop(
    db: Session,
    *,
    owner_id: str,
    iterations: int = 3,
    raw_event_ids: list[int] | None = None,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _policy_snapshot(settings_object)
    blockers: set[str] = set()
    if iterations < 1 or iterations > policy["maximum_iterations"]:
        blockers.add("SHADOW_WORKER_LOOP_ITERATION_COUNT_INVALID")
    state = get_shadow_worker_state(db, settings_object=settings_object, evaluated_at=now)
    if not state.get("worker_ready"):
        blockers.add("SHADOW_WORKER_LOOP_WORKER_NOT_READY")
    if state.get("owner_id") != str(owner_id or "").strip():
        blockers.add("SHADOW_WORKER_LOOP_OWNER_MISMATCH")
    iteration_preview: dict[str, Any] = {}
    if not blockers:
        try:
            iteration_preview = preview_shadow_worker_iteration(
                db,
                owner_id=owner_id,
                raw_event_ids=raw_event_ids,
                settings_object=settings_object,
                registry=registry,
                evaluated_at=now,
            )
        except CanonicalParserShadowWorkerError as exc:
            blockers.add(getattr(exc, "code", "SHADOW_WORKER_LOOP_PREVIEW_FAILED"))
    manifest = {
        "owner_id": str(owner_id or "").strip(),
        "worker_generation": state.get("generation", 0),
        "lease_epoch": state.get("lease_epoch", 0),
        "latest_event_hash": state.get("latest_event_hash"),
        "iterations": int(iterations),
        "raw_event_ids": sorted(set(int(value) for value in (raw_event_ids or []))),
        "policy_hash": calculate_payload_hash(policy),
        "evaluated_at": now.replace(microsecond=0).isoformat(),
    }
    loop_key = calculate_payload_hash(manifest)
    return {
        "runnable": not blockers,
        "reason_codes": sorted(blockers),
        "worker_state": state,
        "first_iteration_preview": sanitize_technical_metadata(iteration_preview),
        "loop_key": loop_key,
        "manifest": manifest,
        "confirmation": f"{SHADOW_WORKER_LOOP_PREFIX}:{state.get('lease_epoch', 0)}:{loop_key[:16]}",
        "policy": policy,
        "bounded_session": True,
        "background_daemon": False,
    }


def _attempt_kill_switch(
    db: Session,
    *,
    actor_label: str,
    reason: str,
    settings_object: Any,
    occurred_at: datetime,
) -> bool:
    if not bool(
        getattr(settings_object, "CANONICAL_PARSER_SHADOW_WORKER_LOOP_ENFORCE_KILL_SWITCH", False)
    ):
        return False
    try:
        state = get_shadow_scheduler_state(db, settings_object=settings_object, evaluated_at=occurred_at)
        if not state.get("exists") or state.get("kill_switch_engaged"):
            return bool(state.get("kill_switch_engaged"))
        confirmation = (
            f"{SHADOW_SCHEDULER_KILL_PREFIX}:{state['generation']}:"
            f"{(state.get('latest_event_hash') or '0' * 64)[:16]}"
        )
        engage_shadow_scheduler_kill_switch(
            db,
            confirmation=confirmation,
            reason=reason,
            actor_label=actor_label,
            settings_object=settings_object,
            killed_at=occurred_at,
        )
        return True
    except (CanonicalParserShadowSchedulerError, KeyError, TypeError):
        db.rollback()
        return False


def run_shadow_worker_loop(
    db: Session,
    *,
    confirmation: str,
    owner_id: str,
    iterations: int = 3,
    raw_event_ids: list[int] | None = None,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    started_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_SHADOW_WORKER_LOOP_ENABLED", False)):
        raise CanonicalParserShadowWorkerLoopError(
            "Shadow worker loop disabilitato.",
            code="CANONICAL_PARSER_SHADOW_WORKER_LOOP_DISABLED",
            status_code=409,
        )
    now = _aware(started_at)
    confirmation_parts = str(confirmation or "").split(":")
    if len(confirmation_parts) == 3 and confirmation_parts[0] == SHADOW_WORKER_LOOP_PREFIX:
        key_prefix = confirmation_parts[2]
        existing_retry = db.scalar(
            select(CanonicalParserShadowWorkerLoopRun).where(
                CanonicalParserShadowWorkerLoopRun.loop_key.like(f"{key_prefix}%")
            )
        )
        if existing_retry is not None:
            return _serialize_loop(existing_retry)
    preview = preview_shadow_worker_loop(
        db,
        owner_id=owner_id,
        iterations=iterations,
        raw_event_ids=raw_event_ids,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=now,
    )
    if confirmation != preview["confirmation"]:
        raise CanonicalParserShadowWorkerLoopError(
            "Conferma loop non valida.",
            code="SHADOW_WORKER_LOOP_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if not preview["runnable"]:
        raise CanonicalParserShadowWorkerLoopError(
            "Loop non eseguibile: " + ", ".join(preview["reason_codes"]),
            code="SHADOW_WORKER_LOOP_NOT_ALLOWED",
            status_code=409,
        )
    existing = db.scalar(
        select(CanonicalParserShadowWorkerLoopRun).where(
            CanonicalParserShadowWorkerLoopRun.loop_key == preview["loop_key"]
        )
    )
    if existing is not None:
        return _serialize_loop(existing)
    state = db.scalar(
        select(CanonicalParserShadowSchedulerWorkerState)
        .where(CanonicalParserShadowSchedulerWorkerState.worker_name == "CANONICAL_SHADOW_SCHEDULER_WORKER")
        .with_for_update()
    )
    if state is None or state.generation != preview["manifest"]["worker_generation"] or state.lease_epoch != preview["manifest"]["lease_epoch"]:
        raise CanonicalParserShadowWorkerLoopError(
            "Worker fencing cambiato dopo la preview.",
            code="SHADOW_WORKER_LOOP_FENCING_DRIFT",
            status_code=409,
        )
    policy = _policy_snapshot(settings_object)
    actor = sanitize_error_message(actor_label or "LOCAL_LOOP_OPERATOR", max_length=80) or "LOCAL_LOOP_OPERATOR"
    loop = CanonicalParserShadowWorkerLoopRun(
        loop_id=str(uuid4()),
        loop_key=preview["loop_key"],
        worker_state_db_id=state.id,
        worker_generation=state.generation,
        lease_epoch=state.lease_epoch,
        owner_id=state.owner_id or str(owner_id),
        status="RUNNING",
        requested_iterations=int(iterations),
        completed_iterations=0,
        passed_iterations=0,
        partial_iterations=0,
        idle_iterations=0,
        failed_iterations=0,
        skipped_iterations=0,
        max_consecutive_failures=policy["maximum_consecutive_failures"],
        observed_consecutive_failures=0,
        circuit_breaker_open=False,
        kill_switch_enforced=False,
        actor_label=actor,
        note=sanitize_error_message(note, max_length=_MAX_NOTE_LENGTH) if note else None,
        stop_reason=None,
        policy_snapshot=policy,
        summary={},
        started_at=now,
        completed_at=None,
    )
    db.add(loop)
    try:
        db.commit()
        db.refresh(loop)
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(select(CanonicalParserShadowWorkerLoopRun).where(
            CanonicalParserShadowWorkerLoopRun.loop_key == preview["loop_key"]
        ))
        if existing is not None:
            return _serialize_loop(existing)
        raise CanonicalParserShadowWorkerLoopError(
            "Conflitto creazione loop.", code="SHADOW_WORKER_LOOP_CONFLICT", status_code=409
        ) from exc

    consecutive_failures = 0
    terminal_status = "COMPLETED"
    stop_reason: str | None = None
    for sequence in range(1, int(iterations) + 1):
        iteration_time = now + timedelta(seconds=sequence - 1)
        try:
            iteration_preview = preview_shadow_worker_iteration(
                db,
                owner_id=owner_id,
                raw_event_ids=raw_event_ids,
                settings_object=settings_object,
                registry=registry,
                evaluated_at=iteration_time,
            )
            if not iteration_preview.get("iterable"):
                terminal_status = "STOPPED"
                stop_reason = "WORKER_NOT_ITERABLE:" + ",".join(iteration_preview.get("reason_codes") or [])
                break
            payload = run_shadow_worker_iteration(
                db,
                confirmation=iteration_preview["confirmation"],
                owner_id=owner_id,
                raw_event_ids=raw_event_ids,
                actor_label=actor,
                note=f"M20 bounded loop {loop.loop_id} iteration {sequence}",
                settings_object=settings_object,
                registry=registry,
                started_at=iteration_time,
                completed_at=iteration_time,
            )
            iteration = db.scalar(select(CanonicalParserShadowSchedulerWorkerIteration).where(
                CanonicalParserShadowSchedulerWorkerIteration.iteration_id == payload["iteration_id"]
            ))
            if iteration is None:
                raise CanonicalParserShadowWorkerLoopError(
                    "Iterazione worker non persistita.", code="SHADOW_WORKER_LOOP_ITERATION_MISSING", status_code=500
                )
            link = CanonicalParserShadowWorkerLoopIteration(
                loop_run_db_id=loop.id,
                sequence=sequence,
                worker_iteration_db_id=iteration.id,
                iteration_id=iteration.iteration_id,
                status=iteration.status,
                reason_codes=list(iteration.reason_codes or []),
                started_at=iteration.started_at,
                completed_at=iteration.completed_at,
            )
            db.add(link)
            loop = db.scalar(select(CanonicalParserShadowWorkerLoopRun).where(
                CanonicalParserShadowWorkerLoopRun.id == loop.id
            ).with_for_update())
            assert loop is not None
            loop.completed_iterations += 1
            status = iteration.status
            if status == "PASSED":
                loop.passed_iterations += 1
                consecutive_failures = 0
            elif status == "PARTIAL":
                loop.partial_iterations += 1
                consecutive_failures = 0
            elif status == "IDLE":
                loop.idle_iterations += 1
                consecutive_failures = 0
            elif status == "SKIPPED":
                loop.skipped_iterations += 1
                consecutive_failures = 0
            else:
                loop.failed_iterations += 1
                consecutive_failures += 1
            loop.observed_consecutive_failures = max(loop.observed_consecutive_failures, consecutive_failures)
            db.commit()
            if consecutive_failures >= loop.max_consecutive_failures:
                loop = db.scalar(select(CanonicalParserShadowWorkerLoopRun).where(
                    CanonicalParserShadowWorkerLoopRun.id == loop.id
                ).with_for_update())
                assert loop is not None
                loop.circuit_breaker_open = True
                terminal_status = "CIRCUIT_OPEN"
                stop_reason = "MAX_CONSECUTIVE_FAILURES_REACHED"
                db.commit()
                break
        except CanonicalParserShadowWorkerError as exc:
            db.rollback()
            loop = db.scalar(select(CanonicalParserShadowWorkerLoopRun).where(
                CanonicalParserShadowWorkerLoopRun.id == loop.id
            ).with_for_update())
            assert loop is not None
            loop.failed_iterations += 1
            loop.completed_iterations += 1
            consecutive_failures += 1
            loop.observed_consecutive_failures = max(loop.observed_consecutive_failures, consecutive_failures)
            db.commit()
            if consecutive_failures >= loop.max_consecutive_failures:
                loop = db.scalar(select(CanonicalParserShadowWorkerLoopRun).where(
                    CanonicalParserShadowWorkerLoopRun.id == loop.id
                ).with_for_update())
                assert loop is not None
                loop.circuit_breaker_open = True
                terminal_status = "CIRCUIT_OPEN"
                stop_reason = getattr(exc, "code", "SHADOW_WORKER_LOOP_ITERATION_FAILED")
                db.commit()
                break

    final_time = now + timedelta(seconds=max(loop.completed_iterations, 1))
    loop = db.scalar(select(CanonicalParserShadowWorkerLoopRun).where(
        CanonicalParserShadowWorkerLoopRun.id == loop.id
    ).with_for_update())
    assert loop is not None
    if loop.circuit_breaker_open:
        loop.kill_switch_enforced = _attempt_kill_switch(
            db,
            actor_label=actor,
            reason=stop_reason or "M20 circuit breaker",
            settings_object=settings_object,
            occurred_at=final_time,
        )
        loop = db.scalar(select(CanonicalParserShadowWorkerLoopRun).where(
            CanonicalParserShadowWorkerLoopRun.id == loop.id
        ).with_for_update())
        assert loop is not None
    loop.status = terminal_status
    loop.stop_reason = stop_reason
    loop.completed_at = final_time
    loop.summary = sanitize_technical_metadata({
        "completed_iterations": loop.completed_iterations,
        "passed_iterations": loop.passed_iterations,
        "partial_iterations": loop.partial_iterations,
        "idle_iterations": loop.idle_iterations,
        "failed_iterations": loop.failed_iterations,
        "skipped_iterations": loop.skipped_iterations,
        "circuit_breaker_open": loop.circuit_breaker_open,
        "kill_switch_enforced": loop.kill_switch_enforced,
        "bounded_session": True,
        "background_daemon": False,
    })
    db.commit()
    db.refresh(loop)
    return _serialize_loop(loop)


def get_shadow_worker_loop(db: Session, loop_id: str) -> dict[str, Any]:
    loop = db.scalar(select(CanonicalParserShadowWorkerLoopRun).where(
        CanonicalParserShadowWorkerLoopRun.loop_id == str(loop_id or "").strip()
    ))
    if loop is None:
        raise CanonicalParserShadowWorkerLoopError(
            "Worker loop non trovato.", code="SHADOW_WORKER_LOOP_NOT_FOUND", status_code=404
        )
    return _serialize_loop(loop)


def get_shadow_worker_loop_status(db: Session, *, settings_object: Any = settings) -> dict[str, Any]:
    counts = dict(db.execute(select(
        CanonicalParserShadowWorkerLoopRun.status,
        func.count(CanonicalParserShadowWorkerLoopRun.id),
    ).group_by(CanonicalParserShadowWorkerLoopRun.status)).all())
    return {
        "loop_enabled": bool(getattr(settings_object, "CANONICAL_PARSER_SHADOW_WORKER_LOOP_ENABLED", False)),
        "policy_version": SHADOW_WORKER_LOOP_POLICY_VERSION,
        "loop_count": int(sum(counts.values())),
        "loop_status_counts": {status: int(counts.get(status, 0)) for status in (
            "RUNNING", "COMPLETED", "STOPPED", "CIRCUIT_OPEN", "FAILED", "KILLED"
        )},
        "worker_state": get_shadow_worker_state(db, settings_object=settings_object),
        "policy": _policy_snapshot(settings_object),
        "operational_guards": {
            "bounded_session": True,
            "background_daemon": False,
            "sleep_calls": False,
            "external_requests": 0,
            "writes_trades": False,
            "paper_execution": False,
            "live_execution": False,
        },
    }
