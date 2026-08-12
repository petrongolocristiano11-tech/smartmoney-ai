from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.database.session import SessionLocal
from backend.app.models.gen4_copyability import (
    CanonicalParserGen4CopyabilityWorkerState,
)


HELIUS_CREDIT_GUARD_POLICY_VERSION = "helius-credit-containment/1"
HELIUS_CREDIT_GUARD_METADATA_KEY = "helius_credit_guard"
HELIUS_CREDIT_GUARD_STATE_ID = "GEN4_COPYABILITY_GLOBAL"

CATEGORY_ENHANCED = "ENHANCED"
CATEGORY_RPC = "RPC"
ALLOWED_CATEGORIES = frozenset({CATEGORY_ENHANCED, CATEGORY_RPC})


@dataclass(slots=True)
class HeliusCreditGuardError(RuntimeError):
    message: str
    code: str
    category: str
    origin: str
    estimated_credits: int

    def __post_init__(self) -> None:
        RuntimeError.__init__(self, self.message)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _guard_enforced(*, force: bool = False) -> bool:
    if force:
        return True
    if not bool(getattr(settings, "HELIUS_CREDIT_GUARD_ENABLED", True)):
        return False
    return bool(
        str(getattr(settings, "ENVIRONMENT", "development")).lower()
        == "production"
        or getattr(
            settings,
            "HELIUS_CREDIT_GUARD_ENFORCE_IN_NON_PRODUCTION",
            False,
        )
    )


def _empty_guard(day: str) -> dict[str, Any]:
    return {
        "policy_version": HELIUS_CREDIT_GUARD_POLICY_VERSION,
        "utc_day": day,
        "daily_total_credits": 0,
        "daily_enhanced_credits": 0,
        "daily_rpc_credits": 0,
        "daily_automatic_enhanced_credits": 0,
        "daily_reservations": 0,
        "daily_blocked_requests": 0,
        "lifetime_reserved_credits": 0,
        "lifetime_blocked_requests": 0,
        "last_category": None,
        "last_origin": None,
        "last_reserved_at": None,
        "last_blocked_at": None,
        "last_blocked_code": None,
    }


def _normalize_guard(value: object, *, day: str) -> dict[str, Any]:
    current = dict(value) if isinstance(value, dict) else {}
    lifetime_reserved = max(
        0,
        int(current.get("lifetime_reserved_credits") or 0),
    )
    lifetime_blocked = max(
        0,
        int(current.get("lifetime_blocked_requests") or 0),
    )
    if str(current.get("utc_day") or "") != day:
        reset = _empty_guard(day)
        reset["lifetime_reserved_credits"] = lifetime_reserved
        reset["lifetime_blocked_requests"] = lifetime_blocked
        return reset

    normalized = _empty_guard(day)
    normalized.update(current)
    normalized["policy_version"] = HELIUS_CREDIT_GUARD_POLICY_VERSION
    for key in (
        "daily_total_credits",
        "daily_enhanced_credits",
        "daily_rpc_credits",
        "daily_automatic_enhanced_credits",
        "daily_reservations",
        "daily_blocked_requests",
        "lifetime_reserved_credits",
        "lifetime_blocked_requests",
    ):
        normalized[key] = max(0, int(normalized.get(key) or 0))
    return normalized


def _ensure_worker_state(db: Session) -> CanonicalParserGen4CopyabilityWorkerState:
    row = db.scalar(
        select(CanonicalParserGen4CopyabilityWorkerState)
        .where(
            CanonicalParserGen4CopyabilityWorkerState.state_id
            == HELIUS_CREDIT_GUARD_STATE_ID
        )
        .with_for_update()
        .limit(1)
    )
    if row is not None:
        return row

    row = CanonicalParserGen4CopyabilityWorkerState(
        state_id=HELIUS_CREDIT_GUARD_STATE_ID,
        enabled=True,
        poll_interval_seconds=max(
            1,
            min(
                int(
                    getattr(
                        settings,
                        "CANONICAL_PARSER_GEN4_COPYABILITY_WORKER_INTERVAL_SECONDS",
                        1,
                    )
                ),
                60,
            ),
        ),
        batch_size=max(
            1,
            min(
                int(
                    getattr(
                        settings,
                        "CANONICAL_PARSER_GEN4_COPYABILITY_WORKER_BATCH_SIZE",
                        20,
                    )
                ),
                100,
            ),
        ),
        technical_metadata={
            "policy_version": "canonical-parser-gen4-realtime-copyability/1",
        },
    )
    db.add(row)
    db.flush()
    return row


def _caps() -> dict[str, int]:
    return {
        "total": max(
            100,
            int(getattr(settings, "HELIUS_APP_DAILY_CREDIT_CAP", 20_000)),
        ),
        "enhanced": max(
            0,
            int(getattr(settings, "HELIUS_ENHANCED_DAILY_CREDIT_CAP", 10_000)),
        ),
        "rpc": max(
            0,
            int(getattr(settings, "HELIUS_RPC_DAILY_CREDIT_CAP", 10_000)),
        ),
    }


def _public_status(
    guard: dict[str, Any],
    *,
    enforced: bool | None = None,
) -> dict[str, Any]:
    caps = _caps()
    return {
        **guard,
        "enforced": _guard_enforced() if enforced is None else enforced,
        "automatic_enhanced_enabled": bool(
            getattr(settings, "HELIUS_AUTOMATIC_ENHANCED_API_ENABLED", False)
        ),
        "daily_total_credit_cap": caps["total"],
        "daily_enhanced_credit_cap": caps["enhanced"],
        "daily_rpc_credit_cap": caps["rpc"],
        "daily_total_credits_remaining": max(
            0,
            caps["total"] - int(guard.get("daily_total_credits") or 0),
        ),
        "daily_enhanced_credits_remaining": max(
            0,
            caps["enhanced"] - int(guard.get("daily_enhanced_credits") or 0),
        ),
        "daily_rpc_credits_remaining": max(
            0,
            caps["rpc"] - int(guard.get("daily_rpc_credits") or 0),
        ),
        "raw_webhook_guarded": False,
        "raw_webhook_reason": "INBOUND_DELIVERY_NOT_AN_OUTBOUND_API_CALL",
    }


def reserve_helius_credits(
    *,
    category: str,
    estimated_credits: int,
    origin: str,
    automatic: bool,
    now: datetime | None = None,
    session_factory: Callable[[], Session] = SessionLocal,
    force: bool = False,
) -> dict[str, Any]:
    normalized_category = str(category or "").strip().upper()
    normalized_origin = str(origin or "UNSPECIFIED")[:120]
    credits = max(1, int(estimated_credits))
    if normalized_category not in ALLOWED_CATEGORIES:
        raise ValueError(f"Categoria Helius non supportata: {normalized_category}")

    if not _guard_enforced(force=force):
        return {
            "enforced": False,
            "category": normalized_category,
            "origin": normalized_origin,
            "estimated_credits": credits,
        }

    observed = now or _utc_now()
    day = observed.astimezone(timezone.utc).date().isoformat()
    db = session_factory()
    try:
        row = _ensure_worker_state(db)
        metadata = dict(row.technical_metadata or {})
        guard = _normalize_guard(
            metadata.get(HELIUS_CREDIT_GUARD_METADATA_KEY),
            day=day,
        )
        caps = _caps()

        blocked_code: str | None = None
        if (
            automatic
            and normalized_category == CATEGORY_ENHANCED
            and not bool(
                getattr(
                    settings,
                    "HELIUS_AUTOMATIC_ENHANCED_API_ENABLED",
                    False,
                )
            )
        ):
            blocked_code = "HELIUS_AUTOMATIC_ENHANCED_DISABLED"
        elif guard["daily_total_credits"] + credits > caps["total"]:
            blocked_code = "HELIUS_DAILY_TOTAL_CREDIT_CAP_REACHED"
        elif (
            normalized_category == CATEGORY_ENHANCED
            and guard["daily_enhanced_credits"] + credits > caps["enhanced"]
        ):
            blocked_code = "HELIUS_DAILY_ENHANCED_CREDIT_CAP_REACHED"
        elif (
            normalized_category == CATEGORY_RPC
            and guard["daily_rpc_credits"] + credits > caps["rpc"]
        ):
            blocked_code = "HELIUS_DAILY_RPC_CREDIT_CAP_REACHED"

        if blocked_code is not None:
            guard["daily_blocked_requests"] += 1
            guard["lifetime_blocked_requests"] += 1
            guard["last_category"] = normalized_category
            guard["last_origin"] = normalized_origin
            guard["last_blocked_at"] = observed.isoformat()
            guard["last_blocked_code"] = blocked_code
            metadata[HELIUS_CREDIT_GUARD_METADATA_KEY] = guard
            row.technical_metadata = metadata
            db.commit()
            raise HeliusCreditGuardError(
                message="Richiesta Helius bloccata dal budget applicativo.",
                code=blocked_code,
                category=normalized_category,
                origin=normalized_origin,
                estimated_credits=credits,
            )

        guard["daily_total_credits"] += credits
        if normalized_category == CATEGORY_ENHANCED:
            guard["daily_enhanced_credits"] += credits
            if automatic:
                guard["daily_automatic_enhanced_credits"] += credits
        else:
            guard["daily_rpc_credits"] += credits
        guard["daily_reservations"] += 1
        guard["lifetime_reserved_credits"] += credits
        guard["last_category"] = normalized_category
        guard["last_origin"] = normalized_origin
        guard["last_reserved_at"] = observed.isoformat()
        guard["last_blocked_code"] = None
        metadata[HELIUS_CREDIT_GUARD_METADATA_KEY] = guard
        row.technical_metadata = metadata
        db.commit()
        return _public_status(guard, enforced=True)
    except HeliusCreditGuardError:
        raise
    except SQLAlchemyError as error:
        db.rollback()
        raise HeliusCreditGuardError(
            message="Guardia crediti Helius non disponibile; richiesta bloccata.",
            code="HELIUS_CREDIT_GUARD_UNAVAILABLE",
            category=normalized_category,
            origin=normalized_origin,
            estimated_credits=credits,
        ) from error
    finally:
        db.close()


def get_helius_credit_guard_status(
    db: Session,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    observed = now or _utc_now()
    day = observed.astimezone(timezone.utc).date().isoformat()
    row = db.scalar(
        select(CanonicalParserGen4CopyabilityWorkerState)
        .where(
            CanonicalParserGen4CopyabilityWorkerState.state_id
            == HELIUS_CREDIT_GUARD_STATE_ID
        )
        .limit(1)
    )
    metadata = dict(row.technical_metadata or {}) if row is not None else {}
    guard = _normalize_guard(
        metadata.get(HELIUS_CREDIT_GUARD_METADATA_KEY),
        day=day,
    )
    return _public_status(guard)
