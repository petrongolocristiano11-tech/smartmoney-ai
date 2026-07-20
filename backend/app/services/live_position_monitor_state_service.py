from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.live_position_monitor import LivePositionMonitorState


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def get_or_create_monitor_state(db: Session) -> LivePositionMonitorState:
    state = db.query(LivePositionMonitorState).filter(LivePositionMonitorState.id == 1).first()
    if state is not None:
        return state
    state = LivePositionMonitorState(id=1, status="STOPPED")
    db.add(state)
    try:
        db.commit()
        db.refresh(state)
        return state
    except IntegrityError:
        db.rollback()
        return db.query(LivePositionMonitorState).filter(LivePositionMonitorState.id == 1).one()


def acquire_monitor_lease(
    db: Session,
    *,
    worker_id: str,
    lease_seconds: int,
) -> bool:
    now = utc_now()
    state = get_or_create_monitor_state(db)
    state = (
        db.query(LivePositionMonitorState)
        .filter(LivePositionMonitorState.id == 1)
        .with_for_update()
        .one()
    )
    expires = _as_utc(state.lease_expires_at)
    if state.lease_owner and state.lease_owner != worker_id and expires and expires > now:
        db.rollback()
        return False
    state.worker_id = worker_id
    state.lease_owner = worker_id
    state.lease_expires_at = now + timedelta(seconds=max(10, int(lease_seconds)))
    state.heartbeat_at = now
    if state.status == "STOPPED":
        state.status = "IDLE"
    db.commit()
    return True


def heartbeat_monitor(
    db: Session,
    *,
    worker_id: str,
    lease_seconds: int,
    status: str | None = None,
) -> bool:
    now = utc_now()
    state = (
        db.query(LivePositionMonitorState)
        .filter(LivePositionMonitorState.id == 1)
        .with_for_update()
        .first()
    )
    if state is None or state.lease_owner != worker_id:
        db.rollback()
        return False
    state.heartbeat_at = now
    state.lease_expires_at = now + timedelta(seconds=max(10, int(lease_seconds)))
    if status:
        state.status = status
    db.commit()
    return True


def release_monitor_lease(db: Session, *, worker_id: str) -> None:
    state = db.query(LivePositionMonitorState).filter(LivePositionMonitorState.id == 1).first()
    if state is None or state.lease_owner != worker_id:
        return
    state.status = "STOPPED"
    state.lease_owner = None
    state.lease_expires_at = None
    state.heartbeat_at = utc_now()
    db.commit()


def update_monitor_run(
    db: Session,
    *,
    summary: dict,
    started_at: datetime,
    completed_at: datetime,
    error: Exception | None = None,
) -> LivePositionMonitorState:
    state = get_or_create_monitor_state(db)
    state.total_runs = int(state.total_runs or 0) + 1
    state.last_run_started_at = started_at
    state.last_run_completed_at = completed_at
    state.positions_scanned = int(state.positions_scanned or 0) + int(summary.get("positions_scanned", 0))
    state.quotes_succeeded = int(state.quotes_succeeded or 0) + int(summary.get("quotes_succeeded", 0))
    state.quotes_failed = int(state.quotes_failed or 0) + int(summary.get("quotes_failed", 0))
    state.exits_triggered = int(state.exits_triggered or 0) + int(summary.get("exits_triggered", 0))
    state.exits_completed = int(state.exits_completed or 0) + int(summary.get("exits_completed", 0))
    state.exits_failed = int(state.exits_failed or 0) + int(summary.get("exits_failed", 0))
    reconciliation = summary.get("reconciliation") or {}
    state.orders_reconciled = int(state.orders_reconciled or 0) + int(reconciliation.get("confirmed", 0))
    state.reconciliation_failed = int(state.reconciliation_failed or 0) + int(reconciliation.get("failed", 0))
    if error is not None:
        state.status = "ERROR"
        state.last_error_code = type(error).__name__
        state.last_error_message = str(error)[:1000]
    elif summary.get("quotes_failed") or summary.get("exits_failed") or reconciliation.get("failed"):
        state.status = "DEGRADED"
        state.last_error_code = None
        state.last_error_message = None
    else:
        state.status = "IDLE"
        state.last_error_code = None
        state.last_error_message = None
    db.commit()
    db.refresh(state)
    return state


def serialize_monitor_state(state: LivePositionMonitorState, *, now: datetime | None = None) -> dict:
    now = now or utc_now()
    heartbeat = _as_utc(state.heartbeat_at)
    expires = _as_utc(state.lease_expires_at)
    return {
        "status": state.status,
        "online": bool(heartbeat and (now - heartbeat).total_seconds() <= 180),
        "lease_active": bool(state.lease_owner and expires and expires > now),
        "worker_id": state.worker_id,
        "lease_owner": state.lease_owner,
        "lease_expires_at": state.lease_expires_at,
        "heartbeat_at": state.heartbeat_at,
        "last_run_started_at": state.last_run_started_at,
        "last_run_completed_at": state.last_run_completed_at,
        "total_runs": state.total_runs,
        "positions_scanned": state.positions_scanned,
        "quotes_succeeded": state.quotes_succeeded,
        "quotes_failed": state.quotes_failed,
        "exits_triggered": state.exits_triggered,
        "exits_completed": state.exits_completed,
        "exits_failed": state.exits_failed,
        "orders_reconciled": state.orders_reconciled,
        "reconciliation_failed": state.reconciliation_failed,
        "last_error_code": state.last_error_code,
        "last_error_message": state.last_error_message,
        "updated_at": state.updated_at,
    }
