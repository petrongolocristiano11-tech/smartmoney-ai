from datetime import (
    datetime,
    timezone,
)

from sqlalchemy.orm import Session

from backend.app.models.live_copy_order import (
    LiveCopyOrder,
)
from backend.app.models.live_position import (
    LivePosition,
)
from backend.app.models.live_trading_policy import (
    LiveTradingPolicy,
)
from backend.app.services.live_trading_errors import (
    LiveTradingError,
)
from backend.app.services.live_trading_policy_service import (
    POLICY_NAME,
    get_or_create_live_policy,
    record_live_event,
)


ACTIVE_EXECUTION_STATUSES = {
    "RECEIVED",
    "QUOTED",
    "SUBMITTED",
}


def utc_now() -> datetime:
    return datetime.now(
        timezone.utc
    )


def reset_dry_run_generation(
    db: Session,
    *,
    source_wallets: list[str],
    start_stream: bool,
    buy_enabled: bool,
    sell_enabled: bool,
) -> dict:
    get_or_create_live_policy(
        db
    )

    policy = (
        db.query(LiveTradingPolicy)
        .filter(
            LiveTradingPolicy.name
            == POLICY_NAME
        )
        .with_for_update()
        .one()
    )

    if policy.mode != "DRY_RUN":
        raise LiveTradingError(
            "Il reset controllato è "
            "disponibile solo in DRY_RUN.",
            code="DRY_RUN_MODE_REQUIRED",
            status_code=409,
        )

    if policy.stream_execution_enabled:
        raise LiveTradingError(
            "Disattiva prima lo stream "
            "automatico.",
            code=(
                "DRY_RUN_STREAM_MUST_BE_DISABLED"
            ),
            status_code=409,
        )

    previous_generation = max(
        1,
        int(
            policy.dry_run_generation
            or 1
        ),
    )

    active_orders = (
        db.query(LiveCopyOrder)
        .filter(
            LiveCopyOrder.mode
            == "DRY_RUN",
            LiveCopyOrder.generation
            == previous_generation,
            LiveCopyOrder.status.in_(
                ACTIVE_EXECUTION_STATUSES
            ),
        )
        .count()
    )

    if active_orders > 0:
        raise LiveTradingError(
            "Esistono ordini DRY_RUN "
            "ancora in elaborazione.",
            code="DRY_RUN_ORDERS_ACTIVE",
            status_code=409,
            payload={
                "active_orders":
                    active_orders,
            },
        )

    now = utc_now()

    open_positions = (
        db.query(LivePosition)
        .filter(
            LivePosition.mode
            == "DRY_RUN",
            LivePosition.generation
            == previous_generation,
            LivePosition.status
            == "OPEN",
        )
        .with_for_update()
        .all()
    )

    archived_exposure_sol = sum(
        float(
            position.cost_basis_sol
            or 0.0
        )
        for position in open_positions
    )

    for position in open_positions:
        position.status = "CLOSED"
        position.closed_at = now

    active_generation = (
        previous_generation + 1
    )

    policy.dry_run_generation = (
        active_generation
    )

    policy.dry_run_started_at = now

    policy.source_wallets = list(
        source_wallets
    )

    policy.buy_enabled = bool(
        buy_enabled
    )

    policy.sell_enabled = bool(
        sell_enabled
    )

    policy.stream_execution_enabled = (
        bool(start_stream)
    )

    policy.consecutive_failures = 0

    record_live_event(
        db,
        event_type=(
            "DRY_RUN_GENERATION_RESET"
        ),
        severity="WARNING",
        generation=active_generation,
        message=(
            "Generazione DRY_RUN archiviata "
            "e nuovo test inizializzato."
        ),
        payload={
            "previous_generation":
                previous_generation,
            "active_generation":
                active_generation,
            "archived_positions":
                len(open_positions),
            "archived_exposure_sol":
                archived_exposure_sol,
            "source_wallets":
                list(source_wallets),
            "stream_execution_enabled":
                bool(start_stream),
            "buy_enabled":
                bool(buy_enabled),
            "sell_enabled":
                bool(sell_enabled),
        },
    )

    db.commit()
    db.refresh(policy)

    return {
        "policy": policy,
        "previous_generation":
            previous_generation,
        "active_generation":
            active_generation,
        "archived_positions":
            len(open_positions),
        "archived_exposure_sol":
            archived_exposure_sol,
        "reset_at": now,
    }
