from datetime import (
    datetime,
    timezone,
)

from sqlalchemy.exc import (
    IntegrityError,
)
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.live_trading_event import (
    LiveTradingEvent,
)
from backend.app.models.live_platform_config import (
    LivePlatformConfig,
)
from backend.app.models.live_trading_policy import (
    LiveTradingPolicy,
)
from backend.app.services.live_trading_errors import (
    LiveTradingError,
)


POLICY_NAME = "default"


def record_live_event(
    db: Session,
    *,
    event_type: str,
    message: str,
    severity: str = "INFO",
    order_id: int | None = None,
    generation: int | None = None,
    payload: dict | None = None,
    commit: bool = False,
) -> LiveTradingEvent:
    event = LiveTradingEvent(
        order_id=order_id,
        event_type=event_type,
        generation=generation,
        severity=severity,
        message=message,
        payload=payload,
    )

    db.add(event)

    if commit:
        db.commit()
        db.refresh(event)

    return event


def get_or_create_live_policy(
    db: Session,
) -> LiveTradingPolicy:
    policy = (
        db.query(LiveTradingPolicy)
        .filter(
            LiveTradingPolicy.name
            == POLICY_NAME
        )
        .first()
    )

    if policy is not None:
        if policy.source_wallets is None:
            policy.source_wallets = []

        return policy

    policy = LiveTradingPolicy(
        name=POLICY_NAME
    )

    db.add(policy)

    try:
        db.commit()

    except IntegrityError:
        db.rollback()

        policy = (
            db.query(
                LiveTradingPolicy
            )
            .filter(
                LiveTradingPolicy.name
                == POLICY_NAME
            )
            .one()
        )

    else:
        db.refresh(policy)

    if policy.source_wallets is None:
        policy.source_wallets = []

    return policy


def _disarm_existing_platform_config(
    db: Session,
) -> None:
    config = (
        db.query(LivePlatformConfig)
        .filter(
            LivePlatformConfig.name
            == "default"
        )
        .first()
    )

    if config is not None:
        config.live_armed_until = None


def _validate_merged_limits(
    values: dict,
) -> None:
    if (
        values["fixed_buy_size_sol"]
        > values["max_order_size_sol"]
    ):
        raise LiveTradingError(
            "fixed_buy_size_sol non può "
            "superare max_order_size_sol.",
            code="INVALID_LIVE_TRADING_LIMITS",
            status_code=422,
        )

    if (
        values["max_order_size_sol"]
        > values["max_daily_buy_sol"]
    ):
        raise LiveTradingError(
            "max_order_size_sol non può "
            "superare max_daily_buy_sol.",
            code="INVALID_LIVE_TRADING_LIMITS",
            status_code=422,
        )

    if (
        values["max_order_size_sol"]
        > values["max_total_exposure_sol"]
    ):
        raise LiveTradingError(
            "max_order_size_sol non può "
            "superare max_total_exposure_sol.",
            code="INVALID_LIVE_TRADING_LIMITS",
            status_code=422,
        )


def update_live_policy(
    db: Session,
    policy: LiveTradingPolicy,
    changes: dict,
) -> LiveTradingPolicy:
    changes = dict(changes)

    confirmation = changes.pop(
        "confirmation",
        None,
    )

    if changes.get("mode") == "LIVE":
        if (
            confirmation
            != "ENABLE LIVE TRADING"
        ):
            raise LiveTradingError(
                "Conferma LIVE non valida.",
                code="LIVE_CONFIRMATION_REQUIRED",
                status_code=422,
            )

        if not settings.is_live_trading_configured:
            raise LiveTradingError(
                "Wallet, chiave privata, API key "
                "interna e Jupiter devono essere "
                "configurati prima della modalità "
                "LIVE.",
                code="LIVE_EXECUTION_NOT_CONFIGURED",
                status_code=503,
            )

    if (
        policy.kill_switch
        and changes.get(
            "kill_switch"
        ) is False
    ):
        raise LiveTradingError(
            "Usa l'endpoint dedicato per "
            "rilasciare il kill switch.",
            code="KILL_SWITCH_RELEASE_REQUIRED",
            status_code=409,
        )

    merged = {
        "fixed_buy_size_sol":
            policy.fixed_buy_size_sol,
        "max_order_size_sol":
            policy.max_order_size_sol,
        "max_daily_buy_sol":
            policy.max_daily_buy_sol,
        "max_total_exposure_sol":
            policy.max_total_exposure_sol,
    }

    merged.update(
        {
            key: value
            for key, value
            in changes.items()
            if key in merged
        }
    )

    _validate_merged_limits(
        merged
    )

    source_wallets = changes.get(
        "source_wallets",
        policy.source_wallets or [],
    )

    stream_enabled = changes.get(
        "stream_execution_enabled",
        policy.stream_execution_enabled,
    )

    if (
        stream_enabled
        and not source_wallets
    ):
        raise LiveTradingError(
            "Per attivare lo stream devi "
            "configurare almeno un wallet "
            "sorgente.",
            code="SOURCE_WALLETS_REQUIRED",
            status_code=422,
        )

    for field, value in changes.items():
        if (
            value is not None
            and hasattr(
                policy,
                field,
            )
        ):
            setattr(
                policy,
                field,
                value,
            )

    if policy.mode == "DISABLED":
        policy.stream_execution_enabled = (
            False
        )

    if (
        policy.mode == "DRY_RUN"
        and policy.dry_run_started_at
        is None
    ):
        policy.dry_run_started_at = (
            datetime.now(timezone.utc)
        )

    if (
        policy.mode != "LIVE"
        or policy.kill_switch
    ):
        _disarm_existing_platform_config(
            db
        )

    record_live_event(
        db,
        event_type="POLICY_UPDATED",
        generation=(
            policy.dry_run_generation
            if policy.mode == "DRY_RUN"
            else None
        ),
        message=(
            "Policy Live Trading "
            "aggiornata."
        ),
        payload={
            "mode":
                policy.mode,
            "kill_switch":
                policy.kill_switch,
            "stream_execution_enabled":
                policy.stream_execution_enabled,
            "source_wallets_count":
                len(
                    policy.source_wallets
                    or []
                ),
        },
    )

    db.commit()
    db.refresh(policy)

    return policy


def engage_kill_switch(
    db: Session,
    policy: LiveTradingPolicy,
    *,
    reason: str,
    automatic: bool = False,
    commit: bool = True,
) -> LiveTradingPolicy:
    policy.kill_switch = True

    policy.stream_execution_enabled = (
        False
    )

    _disarm_existing_platform_config(
        db
    )

    record_live_event(
        db,
        event_type="KILL_SWITCH_ENGAGED",
        generation=(
            policy.dry_run_generation
            if policy.mode == "DRY_RUN"
            else None
        ),
        severity=(
            "CRITICAL"
            if automatic
            else "WARNING"
        ),
        message=reason,
        payload={
            "automatic": automatic,
        },
    )

    if commit:
        db.commit()
        db.refresh(policy)

    return policy


def release_kill_switch(
    db: Session,
    policy: LiveTradingPolicy,
) -> LiveTradingPolicy:
    policy.kill_switch = False
    policy.consecutive_failures = 0

    record_live_event(
        db,
        event_type="KILL_SWITCH_RELEASED",
        generation=(
            policy.dry_run_generation
            if policy.mode == "DRY_RUN"
            else None
        ),
        message=(
            "Kill switch Live Trading "
            "rilasciato manualmente."
        ),
    )

    db.commit()
    db.refresh(policy)

    return policy 