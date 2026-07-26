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
    CanonicalParserShadowWorkerLoopRun,
    CanonicalParserShadowWorkerRecoveryAction,
    CanonicalParserShadowWorkerRecoveryRun,
)
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    sanitize_error_message,
    sanitize_technical_metadata,
)
from backend.app.services.blockchain_parser_shadow_worker_service import (
    SHADOW_WORKER_NAME,
    _append_event,
    _verify_event_chain,
)

SHADOW_WORKER_RECOVERY_POLICY_VERSION = "canonical-parser-shadow-worker-recovery/1"
SHADOW_WORKER_RECOVERY_PREFIX = "RECOVER_STALE_SHADOW_WORKER"
_MAX_ACTOR_LENGTH = 80
_MAX_NOTE_LENGTH = 500


class CanonicalParserShadowWorkerRecoveryError(ValueError):
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
    return sanitize_error_message(value or "LOCAL_RECOVERY", max_length=_MAX_ACTOR_LENGTH) or "LOCAL_RECOVERY"


def _note(value: str | None) -> str | None:
    if not str(value or "").strip():
        return None
    return sanitize_error_message(value, max_length=_MAX_NOTE_LENGTH)


def _policy_snapshot(settings_object: Any) -> dict[str, Any]:
    return {
        "policy_version": SHADOW_WORKER_RECOVERY_POLICY_VERSION,
        "stale_after_seconds": int(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_WORKER_RECOVERY_STALE_AFTER_SECONDS", 300)
        ),
        "max_targets_per_run": int(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_WORKER_RECOVERY_MAX_TARGETS", 100)
        ),
        "manual_only": True,
        "automatic_recovery_connected": False,
        "background_daemon": False,
        "network_allowed": False,
        "writes_trades": False,
        "paper_execution": False,
        "live_execution": False,
    }


def _worker_snapshot(state: CanonicalParserShadowSchedulerWorkerState | None) -> dict[str, Any]:
    if state is None:
        return {"exists": False, "worker_name": SHADOW_WORKER_NAME}
    return {
        "exists": True,
        "id": state.id,
        "worker_name": state.worker_name,
        "status": state.status,
        "generation": state.generation,
        "lease_epoch": state.lease_epoch,
        "owner_id": state.owner_id,
        "lease_expires_at": state.lease_expires_at,
        "heartbeat_at": state.heartbeat_at,
        "latest_event_hash": state.latest_event_hash,
        "latest_event_sequence": state.latest_event_sequence,
    }


def _iteration_snapshot(item: CanonicalParserShadowSchedulerWorkerIteration) -> dict[str, Any]:
    return {
        "id": item.id,
        "iteration_id": item.iteration_id,
        "status": item.status,
        "worker_generation": item.worker_generation,
        "lease_epoch": item.lease_epoch,
        "owner_id": item.owner_id,
        "started_at": item.started_at,
        "completed_at": item.completed_at,
        "reason_codes": list(item.reason_codes or []),
    }


def _loop_snapshot(item: CanonicalParserShadowWorkerLoopRun) -> dict[str, Any]:
    return {
        "id": item.id,
        "loop_id": item.loop_id,
        "status": item.status,
        "worker_generation": item.worker_generation,
        "lease_epoch": item.lease_epoch,
        "owner_id": item.owner_id,
        "started_at": item.started_at,
        "completed_at": item.completed_at,
        "stop_reason": item.stop_reason,
    }


def _state_is_stale(
    state: CanonicalParserShadowSchedulerWorkerState | None,
    *,
    now: datetime,
    stale_after_seconds: int,
) -> bool:
    if state is None or state.status != "ACTIVE":
        return False
    lease_expired = bool(state.lease_expires_at and _aware(state.lease_expires_at) <= now)
    heartbeat_stale = bool(
        state.heartbeat_at
        and (now - _aware(state.heartbeat_at)).total_seconds() >= stale_after_seconds
    )
    missing_heartbeat = state.heartbeat_at is None
    return lease_expired or heartbeat_stale or missing_heartbeat


def _select_targets(
    db: Session,
    *,
    evaluated_at: datetime,
    settings_object: Any,
    for_update: bool = False,
) -> dict[str, Any]:
    policy = _policy_snapshot(settings_object)
    cutoff = evaluated_at - timedelta(seconds=policy["stale_after_seconds"])
    state_query = select(CanonicalParserShadowSchedulerWorkerState).where(
        CanonicalParserShadowSchedulerWorkerState.worker_name == SHADOW_WORKER_NAME
    )
    if for_update:
        state_query = state_query.with_for_update()
    state = db.scalar(state_query)

    iteration_query = (
        select(CanonicalParserShadowSchedulerWorkerIteration)
        .where(
            CanonicalParserShadowSchedulerWorkerIteration.status == "RUNNING",
            CanonicalParserShadowSchedulerWorkerIteration.started_at <= cutoff,
        )
        .order_by(CanonicalParserShadowSchedulerWorkerIteration.started_at.asc())
        .limit(policy["max_targets_per_run"])
    )
    loop_query = (
        select(CanonicalParserShadowWorkerLoopRun)
        .where(
            CanonicalParserShadowWorkerLoopRun.status == "RUNNING",
            CanonicalParserShadowWorkerLoopRun.started_at <= cutoff,
        )
        .order_by(CanonicalParserShadowWorkerLoopRun.started_at.asc())
        .limit(policy["max_targets_per_run"])
    )
    if for_update:
        iteration_query = iteration_query.with_for_update()
        loop_query = loop_query.with_for_update()
    iterations = list(db.scalars(iteration_query))
    loops = list(db.scalars(loop_query))
    state_stale = _state_is_stale(
        state,
        now=evaluated_at,
        stale_after_seconds=policy["stale_after_seconds"],
    )
    audit_reasons = _verify_event_chain(db, state) if state is not None else []
    return {
        "policy": policy,
        "state": state,
        "state_stale": state_stale,
        "audit_reasons": audit_reasons,
        "iterations": iterations,
        "loops": loops,
    }


def preview_shadow_worker_recovery(
    db: Session,
    *,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    selected = _select_targets(
        db,
        evaluated_at=now,
        settings_object=settings_object,
    )
    state = selected["state"]
    worker_targets = 1 if selected["state_stale"] else 0
    reason_codes = set(selected["audit_reasons"])
    if not worker_targets and not selected["iterations"] and not selected["loops"]:
        reason_codes.add("SHADOW_WORKER_RECOVERY_NO_STALE_TARGETS")
    target_snapshot = {
        "worker": _worker_snapshot(state),
        "worker_stale": selected["state_stale"],
        "iterations": [_iteration_snapshot(item) for item in selected["iterations"]],
        "loops": [_loop_snapshot(item) for item in selected["loops"]],
    }
    manifest = {
        "worker_generation": int(state.generation if state else 0),
        "lease_epoch": int(state.lease_epoch if state else 0),
        "latest_event_hash": state.latest_event_hash if state else None,
        "worker_stale": selected["state_stale"],
        "iteration_ids": [item.iteration_id for item in selected["iterations"]],
        "loop_ids": [item.loop_id for item in selected["loops"]],
        "policy_hash": calculate_payload_hash(selected["policy"]),
    }
    recovery_key = calculate_payload_hash(manifest)
    blockers = [code for code in reason_codes if code != "SHADOW_WORKER_RECOVERY_NO_STALE_TARGETS"]
    return {
        "recoverable": bool(worker_targets or selected["iterations"] or selected["loops"]) and not blockers,
        "reason_codes": sorted(reason_codes),
        "recovery_key": recovery_key,
        "confirmation": f"{SHADOW_WORKER_RECOVERY_PREFIX}:{recovery_key[:16]}",
        "detected_worker_count": worker_targets,
        "detected_iteration_count": len(selected["iterations"]),
        "detected_loop_count": len(selected["loops"]),
        "target_snapshot": sanitize_technical_metadata(target_snapshot),
        "policy": selected["policy"],
        "manual_only": True,
        "automatic_recovery_connected": False,
    }


def _serialize_action(action: CanonicalParserShadowWorkerRecoveryAction) -> dict[str, Any]:
    return {
        "sequence": action.sequence,
        "target_type": action.target_type,
        "target_id": action.target_id,
        "action_type": action.action_type,
        "previous_status": action.previous_status,
        "new_status": action.new_status,
        "reason_codes": action.reason_codes,
        "snapshot_before": action.snapshot_before,
        "snapshot_after": action.snapshot_after,
        "occurred_at": action.occurred_at,
    }


def _serialize_run(db: Session, run: CanonicalParserShadowWorkerRecoveryRun) -> dict[str, Any]:
    actions = list(
        db.scalars(
            select(CanonicalParserShadowWorkerRecoveryAction)
            .where(CanonicalParserShadowWorkerRecoveryAction.recovery_run_db_id == run.id)
            .order_by(CanonicalParserShadowWorkerRecoveryAction.sequence.asc())
        )
    )
    return {
        "recovery_id": run.recovery_id,
        "recovery_key": run.recovery_key,
        "status": run.status,
        "worker_generation": run.worker_generation,
        "lease_epoch": run.lease_epoch,
        "owner_id": run.owner_id,
        "detected_worker_count": run.detected_worker_count,
        "detected_iteration_count": run.detected_iteration_count,
        "detected_loop_count": run.detected_loop_count,
        "recovered_worker_count": run.recovered_worker_count,
        "recovered_iteration_count": run.recovered_iteration_count,
        "recovered_loop_count": run.recovered_loop_count,
        "reason_codes": run.reason_codes,
        "target_snapshot": run.target_snapshot,
        "policy_snapshot": run.policy_snapshot,
        "summary": run.summary,
        "actor_label": run.actor_label,
        "note": run.note,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "actions": [_serialize_action(action) for action in actions],
    }


def run_shadow_worker_recovery(
    db: Session,
    *,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    started_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(
        getattr(settings_object, "CANONICAL_PARSER_SHADOW_WORKER_RECOVERY_ENABLED", False)
    ):
        raise CanonicalParserShadowWorkerRecoveryError(
            "Shadow worker recovery disabilitato.",
            code="CANONICAL_PARSER_SHADOW_WORKER_RECOVERY_DISABLED",
            status_code=409,
        )
    now = _aware(started_at)
    parts = str(confirmation or "").split(":")
    if len(parts) == 2 and parts[0] == SHADOW_WORKER_RECOVERY_PREFIX:
        existing = db.scalar(
            select(CanonicalParserShadowWorkerRecoveryRun).where(
                CanonicalParserShadowWorkerRecoveryRun.recovery_key.like(f"{parts[1]}%")
            )
        )
        if existing is not None:
            return _serialize_run(db, existing)
    preview = preview_shadow_worker_recovery(
        db,
        settings_object=settings_object,
        evaluated_at=now,
    )
    if confirmation != preview["confirmation"]:
        raise CanonicalParserShadowWorkerRecoveryError(
            "Conferma recovery non valida.",
            code="SHADOW_WORKER_RECOVERY_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if not preview["recoverable"]:
        raise CanonicalParserShadowWorkerRecoveryError(
            "Recovery non eseguibile: " + ", ".join(preview["reason_codes"]),
            code="SHADOW_WORKER_RECOVERY_NOT_ALLOWED",
            status_code=409,
        )
    selected = _select_targets(
        db,
        evaluated_at=now,
        settings_object=settings_object,
        for_update=True,
    )
    state = selected["state"]
    run = CanonicalParserShadowWorkerRecoveryRun(
        recovery_id=str(uuid4()),
        recovery_key=preview["recovery_key"],
        worker_state_db_id=state.id if state else None,
        worker_generation=int(state.generation if state else 0),
        lease_epoch=int(state.lease_epoch if state else 0),
        owner_id=state.owner_id if state else None,
        status="RUNNING",
        detected_worker_count=preview["detected_worker_count"],
        detected_iteration_count=preview["detected_iteration_count"],
        detected_loop_count=preview["detected_loop_count"],
        recovered_worker_count=0,
        recovered_iteration_count=0,
        recovered_loop_count=0,
        actor_label=_actor(actor_label),
        note=_note(note),
        reason_codes=[],
        target_snapshot=preview["target_snapshot"],
        policy_version=SHADOW_WORKER_RECOVERY_POLICY_VERSION,
        policy_hash=calculate_payload_hash(selected["policy"]),
        policy_snapshot=selected["policy"],
        summary={},
        started_at=now,
        completed_at=None,
    )
    db.add(run)
    db.flush()
    sequence = 0
    try:
        if selected["state_stale"] and state is not None:
            sequence += 1
            before = _worker_snapshot(state)
            _append_event(
                db,
                state=state,
                event_type="STOPPED",
                new_status="STOPPED",
                actor_label=run.actor_label,
                reason="M21 stale worker recovery",
                occurred_at=now,
            )
            state.owner_id = None
            state.lease_token_hash = None
            state.lease_acquired_at = None
            state.lease_expires_at = None
            state.heartbeat_at = None
            db.add(
                CanonicalParserShadowWorkerRecoveryAction(
                    recovery_run_db_id=run.id,
                    sequence=sequence,
                    target_type="WORKER_STATE",
                    target_id=state.worker_name,
                    action_type="STOP_STALE_WORKER",
                    previous_status=before["status"],
                    new_status="STOPPED",
                    reason_codes=["SHADOW_WORKER_LEASE_OR_HEARTBEAT_STALE"],
                    snapshot_before=sanitize_technical_metadata(before),
                    snapshot_after=sanitize_technical_metadata(_worker_snapshot(state)),
                    occurred_at=now,
                )
            )
            run.recovered_worker_count += 1

        for item in selected["iterations"]:
            sequence += 1
            before = _iteration_snapshot(item)
            reasons = sorted(set(list(item.reason_codes or []) + ["RECOVERED_STALE_ITERATION"]))
            item.status = "FAILED"
            item.reason_codes = reasons
            item.completed_at = now
            after = _iteration_snapshot(item)
            db.add(
                CanonicalParserShadowWorkerRecoveryAction(
                    recovery_run_db_id=run.id,
                    sequence=sequence,
                    target_type="WORKER_ITERATION",
                    target_id=item.iteration_id,
                    action_type="FAIL_STALE_ITERATION",
                    previous_status=before["status"],
                    new_status="FAILED",
                    reason_codes=["RECOVERED_STALE_ITERATION"],
                    snapshot_before=sanitize_technical_metadata(before),
                    snapshot_after=sanitize_technical_metadata(after),
                    occurred_at=now,
                )
            )
            run.recovered_iteration_count += 1

        for item in selected["loops"]:
            sequence += 1
            before = _loop_snapshot(item)
            item.status = "STOPPED"
            item.stop_reason = "RECOVERED_STALE_LOOP"
            item.completed_at = now
            after = _loop_snapshot(item)
            db.add(
                CanonicalParserShadowWorkerRecoveryAction(
                    recovery_run_db_id=run.id,
                    sequence=sequence,
                    target_type="WORKER_LOOP",
                    target_id=item.loop_id,
                    action_type="STOP_STALE_LOOP",
                    previous_status=before["status"],
                    new_status="STOPPED",
                    reason_codes=["RECOVERED_STALE_LOOP"],
                    snapshot_before=sanitize_technical_metadata(before),
                    snapshot_after=sanitize_technical_metadata(after),
                    occurred_at=now,
                )
            )
            run.recovered_loop_count += 1

        recovered_total = (
            run.recovered_worker_count
            + run.recovered_iteration_count
            + run.recovered_loop_count
        )
        detected_total = (
            run.detected_worker_count
            + run.detected_iteration_count
            + run.detected_loop_count
        )
        run.status = "COMPLETED" if recovered_total == detected_total else "PARTIAL"
        run.completed_at = now
        run.summary = {
            "detected_total": detected_total,
            "recovered_total": recovered_total,
            "manual_only": True,
            "automatic_recovery_connected": False,
        }
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(
            select(CanonicalParserShadowWorkerRecoveryRun).where(
                CanonicalParserShadowWorkerRecoveryRun.recovery_key == preview["recovery_key"]
            )
        )
        if existing is not None:
            return _serialize_run(db, existing)
        raise CanonicalParserShadowWorkerRecoveryError(
            "Conflitto durante il recovery.",
            code="SHADOW_WORKER_RECOVERY_CONFLICT",
            status_code=409,
        ) from exc
    except Exception:
        db.rollback()
        raise
    db.refresh(run)
    return _serialize_run(db, run)


def get_shadow_worker_recovery_run(db: Session, recovery_id: str) -> dict[str, Any]:
    run = db.scalar(
        select(CanonicalParserShadowWorkerRecoveryRun).where(
            CanonicalParserShadowWorkerRecoveryRun.recovery_id == recovery_id
        )
    )
    if run is None:
        raise CanonicalParserShadowWorkerRecoveryError(
            "Recovery run non trovato.",
            code="SHADOW_WORKER_RECOVERY_NOT_FOUND",
            status_code=404,
        )
    return _serialize_run(db, run)


def get_shadow_worker_recovery_status(
    db: Session,
    *,
    settings_object: Any = settings,
) -> dict[str, Any]:
    return {
        "enabled": bool(
            getattr(settings_object, "CANONICAL_PARSER_SHADOW_WORKER_RECOVERY_ENABLED", False)
        ),
        "policy": _policy_snapshot(settings_object),
        "run_count": int(db.scalar(select(func.count(CanonicalParserShadowWorkerRecoveryRun.id))) or 0),
        "action_count": int(db.scalar(select(func.count(CanonicalParserShadowWorkerRecoveryAction.id))) or 0),
        "operational_guards": {
            "manual_only": True,
            "automatic_recovery_connected": False,
            "background_daemon": False,
            "network_allowed": False,
            "writes_trades": False,
            "paper_execution": False,
            "live_execution": False,
        },
    }
