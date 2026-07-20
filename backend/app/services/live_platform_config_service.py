from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.live_platform_config import LivePlatformConfig
from backend.app.services.live_trading_errors import LiveTradingError
from backend.app.services.live_trading_policy_service import record_live_event


CONFIG_NAME = "default"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_mints(values: list | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()

    for value in values or []:
        mint = str(value or "").strip()
        if not mint:
            continue
        if not 32 <= len(mint) <= 44:
            raise LiveTradingError(
                f"Token mint non valido: {mint}",
                code="INVALID_TOKEN_MINT",
                status_code=422,
            )
        if mint not in seen:
            normalized.append(mint)
            seen.add(mint)

    return normalized


def get_or_create_platform_config(db: Session) -> LivePlatformConfig:
    config = (
        db.query(LivePlatformConfig)
        .filter(LivePlatformConfig.name == CONFIG_NAME)
        .first()
    )

    if config is not None:
        config.token_allowlist = config.token_allowlist or []
        config.token_blocklist = config.token_blocklist or []
        return config

    config = LivePlatformConfig(name=CONFIG_NAME)
    db.add(config)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        config = (
            db.query(LivePlatformConfig)
            .filter(LivePlatformConfig.name == CONFIG_NAME)
            .one()
        )
    else:
        db.refresh(config)

    return config


def update_platform_config(
    db: Session,
    config: LivePlatformConfig,
    changes: dict,
) -> LivePlatformConfig:
    changes = dict(changes)

    if "token_allowlist" in changes:
        changes["token_allowlist"] = normalize_mints(changes["token_allowlist"])

    if "token_blocklist" in changes:
        changes["token_blocklist"] = normalize_mints(changes["token_blocklist"])

    overlap = set(
        changes.get("token_allowlist", config.token_allowlist or [])
    ).intersection(
        changes.get("token_blocklist", config.token_blocklist or [])
    )

    if overlap:
        raise LiveTradingError(
            "Uno stesso token non può essere contemporaneamente in allowlist e blocklist.",
            code="TOKEN_LIST_CONFLICT",
            status_code=422,
            payload={"token_mints": sorted(overlap)},
        )

    for field, value in changes.items():
        if value is not None and hasattr(config, field):
            setattr(config, field, value)

    record_live_event(
        db,
        event_type="PLATFORM_CONFIG_UPDATED",
        message="Configurazione analytics, ranking e sicurezza token aggiornata.",
        payload={
            "auto_wallet_selection_enabled": config.auto_wallet_selection_enabled,
            "max_source_wallets": config.max_source_wallets,
            "token_safety_enabled": config.token_safety_enabled,
            "token_allowlist_count": len(config.token_allowlist or []),
            "token_blocklist_count": len(config.token_blocklist or []),
        },
    )

    db.commit()
    db.refresh(config)
    return config


def is_live_armed(config: LivePlatformConfig, *, now: datetime | None = None) -> bool:
    current = now or utc_now()
    armed_until = config.live_armed_until

    if armed_until is None:
        return False

    if armed_until.tzinfo is None:
        armed_until = armed_until.replace(tzinfo=timezone.utc)

    return armed_until > current


def disarm_live_platform(
    db: Session,
    *,
    reason: str,
    commit: bool = True,
) -> LivePlatformConfig:
    config = get_or_create_platform_config(db)
    was_armed = config.live_armed_until is not None
    config.live_armed_until = None

    if was_armed:
        record_live_event(
            db,
            event_type="LIVE_DISARMED",
            severity="WARNING",
            message=reason,
        )

    if commit:
        db.commit()
        db.refresh(config)

    return config
