from datetime import (
    datetime,
    timedelta,
    timezone,
)

from sqlalchemy.exc import (
    IntegrityError,
)
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.live_trading_worker import (
    LiveTradingWorkerState,
)


WORKER_STATE_ID = 1


def utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    )


def as_utc(
    value: datetime | None,
) -> datetime | None:
    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(
            tzinfo=timezone.utc
        )

    return value.astimezone(
        timezone.utc
    )


def get_or_create_worker_state(
    db: Session,
) -> LiveTradingWorkerState:
    state = db.get(
        LiveTradingWorkerState,
        WORKER_STATE_ID,
    )

    if state is not None:
        if state.active_wallets is None:
            state.active_wallets = []

        return state

    state = LiveTradingWorkerState(
        id=WORKER_STATE_ID,
        status="STOPPED",
        active_wallets=[],
    )

    db.add(state)

    try:
        db.commit()

    except IntegrityError:
        db.rollback()

        state = db.get(
            LiveTradingWorkerState,
            WORKER_STATE_ID,
        )

        if state is None:
            raise

    else:
        db.refresh(state)

    if state.active_wallets is None:
        state.active_wallets = []

    return state


def acquire_worker_lease(
    db: Session,
    *,
    worker_id: str,
    lease_seconds: int,
    now: datetime | None = None,
) -> bool:
    current_time = now or utc_now()

    get_or_create_worker_state(
        db
    )

    state = (
        db.query(
            LiveTradingWorkerState
        )
        .filter(
            LiveTradingWorkerState.id
            == WORKER_STATE_ID
        )
        .with_for_update()
        .one()
    )

    lease_expires_at = as_utc(
        state.lease_expires_at
    )

    lease_is_active = bool(
        state.lease_owner
        and lease_expires_at
        and lease_expires_at
        > current_time
    )

    if (
        lease_is_active
        and state.lease_owner
        != worker_id
    ):
        db.rollback()
        return False

    owner_changed = (
        state.lease_owner
        != worker_id
    )

    state.worker_id = worker_id
    state.lease_owner = worker_id
    state.lease_expires_at = (
        current_time
        + timedelta(
            seconds=lease_seconds
        )
    )

    state.heartbeat_at = current_time

    if owner_changed:
        state.status = "STARTING"
        state.started_at = current_time
        state.connected_at = None
        state.last_message_at = None
        state.last_trade_at = None
        state.last_error_at = None
        state.last_error_code = None
        state.last_error_message = None
        state.active_wallets = []
        state.monitored_wallets = 0
        state.active_subscriptions = 0
        state.queue_depth = 0
        state.reconnect_count = 0
        state.signatures_received = 0
        state.signatures_processed = 0
        state.signatures_failed = 0
        state.signatures_dropped = 0
        state.last_signature = None
        state.last_latency_ms = None

    db.commit()

    return True


WORKER_UPDATE_FIELDS = {
    "status",
    "active_wallets",
    "monitored_wallets",
    "active_subscriptions",
    "queue_depth",
    "reconnect_count",
    "signatures_received",
    "signatures_processed",
    "signatures_failed",
    "signatures_dropped",
    "last_latency_ms",
    "config_fingerprint",
    "last_signature",
    "last_error_code",
    "last_error_message",
    "connected_at",
    "last_message_at",
    "last_trade_at",
    "last_error_at",
}


def heartbeat_worker(
    db: Session,
    *,
    worker_id: str,
    lease_seconds: int,
    updates: dict | None = None,
    now: datetime | None = None,
) -> bool:
    current_time = now or utc_now()

    state = (
        db.query(
            LiveTradingWorkerState
        )
        .filter(
            LiveTradingWorkerState.id
            == WORKER_STATE_ID
        )
        .with_for_update()
        .first()
    )

    if (
        state is None
        or state.lease_owner
        != worker_id
    ):
        db.rollback()
        return False

    state.worker_id = worker_id
    state.heartbeat_at = current_time
    state.lease_expires_at = (
        current_time
        + timedelta(
            seconds=lease_seconds
        )
    )

    for field, value in (
        updates or {}
    ).items():
        if field in WORKER_UPDATE_FIELDS:
            setattr(
                state,
                field,
                value,
            )

    db.commit()

    return True


def release_worker_lease(
    db: Session,
    *,
    worker_id: str,
    now: datetime | None = None,
) -> bool:
    current_time = now or utc_now()

    state = (
        db.query(
            LiveTradingWorkerState
        )
        .filter(
            LiveTradingWorkerState.id
            == WORKER_STATE_ID
        )
        .with_for_update()
        .first()
    )

    if (
        state is None
        or state.lease_owner
        != worker_id
    ):
        db.rollback()
        return False

    state.status = "STOPPED"
    state.heartbeat_at = current_time
    state.lease_owner = None
    state.lease_expires_at = None
    state.active_wallets = []
    state.monitored_wallets = 0
    state.active_subscriptions = 0
    state.queue_depth = 0
    state.last_latency_ms = None

    db.commit()

    return True


def get_live_worker_status(
    db: Session,
    *,
    now: datetime | None = None,
    offline_after_seconds: (
        int | None
    ) = None,
) -> dict:
    current_time = now or utc_now()

    state = get_or_create_worker_state(
        db
    )

    heartbeat_at = as_utc(
        state.heartbeat_at
    )

    lease_expires_at = as_utc(
        state.lease_expires_at
    )

    seconds_since_heartbeat: (
        float | None
    ) = None

    if heartbeat_at is not None:
        seconds_since_heartbeat = max(
            0.0,
            (
                current_time
                - heartbeat_at
            ).total_seconds(),
        )

    offline_limit = (
        offline_after_seconds
        if offline_after_seconds
        is not None
        else max(
            60,
            settings
            .LIVE_STREAM_LEASE_SECONDS
            * 2,
        )
    )

    online = bool(
        heartbeat_at
        and seconds_since_heartbeat
        is not None
        and seconds_since_heartbeat
        <= offline_limit
        and state.status
        != "STOPPED"
    )

    lease_active = bool(
        state.lease_owner
        and lease_expires_at
        and lease_expires_at
        > current_time
    )

    return {
        "status": state.status,
        "online": online,
        "lease_active": lease_active,
        "worker_id": state.worker_id,
        "lease_owner":
            state.lease_owner,
        "lease_expires_at":
            state.lease_expires_at,
        "active_wallets":
            list(
                state.active_wallets
                or []
            ),
        "monitored_wallets":
            state.monitored_wallets,
        "active_subscriptions":
            state.active_subscriptions,
        "queue_depth":
            state.queue_depth,
        "reconnect_count":
            state.reconnect_count,
        "signatures_received":
            state.signatures_received,
        "signatures_processed":
            state.signatures_processed,
        "signatures_failed":
            state.signatures_failed,
        "signatures_dropped":
            state.signatures_dropped,
        "last_latency_ms":
            state.last_latency_ms,
        "config_fingerprint":
            state.config_fingerprint,
        "last_signature":
            state.last_signature,
        "last_error_code":
            state.last_error_code,
        "last_error_message":
            state.last_error_message,
        "started_at":
            state.started_at,
        "heartbeat_at":
            state.heartbeat_at,
        "connected_at":
            state.connected_at,
        "last_message_at":
            state.last_message_at,
        "last_trade_at":
            state.last_trade_at,
        "last_error_at":
            state.last_error_at,
        "seconds_since_heartbeat":
            seconds_since_heartbeat,
        "updated_at":
            state.updated_at,
    } 