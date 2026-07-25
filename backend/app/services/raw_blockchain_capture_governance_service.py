from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, exists, func, select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    NormalizationRun,
    RawBlockchainEvent,
)
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    canonicalize_payload,
    register_raw_event,
)
from backend.app.services.raw_blockchain_capture_service import (
    CAPTURE_MODE,
    _configured_event_types,
    _configured_providers,
    sanitize_provider_payload,
)


RETENTION_CONFIRMATION = "PRUNE_UNNORMALIZED_RAW_EVENTS"
CANARY_PROVIDER = "internal_canary"
CANARY_EVENT_TYPE = "RAW_CAPTURE_CANARY"


class RawCaptureGovernanceError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: int = 409,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True, slots=True)
class _RetentionPolicy:
    retention_days: int
    batch_size: int
    cutoff: datetime
    provider: str | None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_provider(provider: str | None) -> str | None:
    normalized = str(provider or "").strip().lower()
    if not normalized:
        return None
    if len(normalized) > 64:
        raise RawCaptureGovernanceError(
            "Il filtro provider supera la lunghezza consentita.",
            code="RAW_CAPTURE_PROVIDER_INVALID",
            status_code=422,
        )
    if not all(
        character.isalnum() or character in {"_", "-"}
        for character in normalized
    ):
        raise RawCaptureGovernanceError(
            "Il filtro provider contiene caratteri non validi.",
            code="RAW_CAPTURE_PROVIDER_INVALID",
            status_code=422,
        )
    return normalized


def _retention_policy(
    *,
    settings_object: Any,
    provider: str | None,
    batch_size: int | None,
    as_of: datetime | None,
) -> _RetentionPolicy:
    retention_days = int(
        getattr(
            settings_object,
            "RAW_BLOCKCHAIN_CAPTURE_RETENTION_DAYS",
            30,
        )
    )
    configured_batch_size = int(
        getattr(
            settings_object,
            "RAW_BLOCKCHAIN_CAPTURE_RETENTION_BATCH_SIZE",
            1000,
        )
    )
    effective_batch_size = min(
        int(batch_size or configured_batch_size),
        configured_batch_size,
    )
    current_time = as_of or _utc_now()
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)
    else:
        current_time = current_time.astimezone(timezone.utc)

    return _RetentionPolicy(
        retention_days=retention_days,
        batch_size=effective_batch_size,
        cutoff=current_time - timedelta(days=retention_days),
        provider=_normalize_provider(provider),
    )


def _retention_filters(policy: _RetentionPolicy):
    filters = [
        RawBlockchainEvent.last_seen_at < policy.cutoff,
    ]
    if policy.provider is not None:
        filters.append(
            RawBlockchainEvent.provider == policy.provider
        )
    return filters


def _normalization_exists_clause():
    return exists(
        select(NormalizationRun.id).where(
            NormalizationRun.raw_event_id
            == RawBlockchainEvent.id
        )
    )


def get_raw_capture_readiness(
    db: Session,
    *,
    settings_object: Any = settings,
) -> dict[str, Any]:
    configured_providers = sorted(
        _configured_providers(settings_object)
    )
    configured_event_types = sorted(
        _configured_event_types(settings_object)
    )

    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if not configured_providers:
        blockers.append(
            {
                "code": "NO_CAPTURE_PROVIDERS",
                "message": "Nessun provider raw capture configurato.",
            }
        )

    if not configured_event_types:
        blockers.append(
            {
                "code": "NO_CAPTURE_EVENT_TYPES",
                "message": "Nessun event type raw capture configurato.",
            }
        )

    if not str(
        getattr(settings_object, "AUTOMATION_API_KEY", "") or ""
    ).strip():
        blockers.append(
            {
                "code": "AUTOMATION_KEY_MISSING",
                "message": "AUTOMATION_API_KEY non configurata.",
            }
        )

    table_count = int(
        db.scalar(
            select(func.count()).select_from(RawBlockchainEvent)
        )
        or 0
    )

    if bool(
        getattr(
            settings_object,
            "RAW_BLOCKCHAIN_CAPTURE_PRUNE_ENABLED",
            False,
        )
    ):
        warnings.append(
            {
                "code": "RETENTION_PRUNE_ENABLED",
                "message": (
                    "La cancellazione retention è abilitata; "
                    "resta comunque esplicita e confermata."
                ),
            }
        )

    capture_enabled = bool(
        getattr(
            settings_object,
            "RAW_BLOCKCHAIN_CAPTURE_ENABLED",
            False,
        )
    )

    return {
        "ready": not blockers,
        "state": (
            "ACTIVE_PASSIVE_SHADOW"
            if capture_enabled and not blockers
            else "READY_DISABLED"
            if not capture_enabled and not blockers
            else "BLOCKED"
        ),
        "capture_enabled": capture_enabled,
        "mode": CAPTURE_MODE,
        "configured_providers": configured_providers,
        "configured_event_types": configured_event_types,
        "max_payload_bytes": int(
            getattr(
                settings_object,
                "RAW_BLOCKCHAIN_CAPTURE_MAX_PAYLOAD_BYTES",
                4_000_000,
            )
        ),
        "retention": {
            "days": int(
                getattr(
                    settings_object,
                    "RAW_BLOCKCHAIN_CAPTURE_RETENTION_DAYS",
                    30,
                )
            ),
            "batch_size": int(
                getattr(
                    settings_object,
                    "RAW_BLOCKCHAIN_CAPTURE_RETENTION_BATCH_SIZE",
                    1000,
                )
            ),
            "prune_enabled": bool(
                getattr(
                    settings_object,
                    "RAW_BLOCKCHAIN_CAPTURE_PRUNE_ENABLED",
                    False,
                )
            ),
            "deletes_normalized_events": False,
        },
        "database": {
            "raw_event_table_accessible": True,
            "raw_event_count": table_count,
        },
        "blockers": blockers,
        "warnings": warnings,
        "operational_guards": {
            "performs_external_requests": False,
            "changes_live_state": False,
            "starts_workers": False,
            "starts_normalization": False,
        },
    }


def run_raw_capture_canary(
    db: Session,
) -> dict[str, Any]:
    before_count = int(
        db.scalar(
            select(func.count())
            .select_from(RawBlockchainEvent)
            .where(RawBlockchainEvent.provider == CANARY_PROVIDER)
        )
        or 0
    )

    canary_id = str(uuid4())
    original_payload = {
        "canary_id": canary_id,
        "provider_response": {
            "result": "synthetic-local-only",
            "authorization": "Bearer synthetic-canary-secret",
            "debug_url": (
                "https://canary.invalid/path?api-key="
                "synthetic-canary-secret"
            ),
        },
    }
    sanitized_payload, redaction_count = sanitize_provider_payload(
        original_payload
    )
    payload_hash = calculate_payload_hash(sanitized_payload)

    savepoint = db.begin_nested()
    try:
        event, created = register_raw_event(
            db,
            provider=CANARY_PROVIDER,
            chain="solana",
            network="local-canary",
            event_type=CANARY_EVENT_TYPE,
            transaction_signature=f"canary-{canary_id}",
            observed_wallet="CANARY_LOCAL_ONLY",
            payload=sanitized_payload,
            event_metadata={
                "canary": True,
                "persistent": False,
                "external_requests": False,
            },
        )
        db.flush()
        temporary_event_id = event.id
        if not created:
            raise RawCaptureGovernanceError(
                "Il canary locale non ha creato un evento temporaneo univoco.",
                code="RAW_CAPTURE_CANARY_COLLISION",
                status_code=500,
            )
    finally:
        savepoint.rollback()
        db.expire_all()

    after_count = int(
        db.scalar(
            select(func.count())
            .select_from(RawBlockchainEvent)
            .where(RawBlockchainEvent.provider == CANARY_PROVIDER)
        )
        or 0
    )

    if after_count != before_count:
        raise RawCaptureGovernanceError(
            "Il canary locale ha lasciato dati persistenti inattesi.",
            code="RAW_CAPTURE_CANARY_ROLLBACK_FAILED",
            status_code=500,
        )

    return {
        "status": "PASSED",
        "canary_id": canary_id,
        "temporary_event_id": temporary_event_id,
        "payload_hash": payload_hash,
        "payload_size_bytes": len(
            canonicalize_payload(sanitized_payload).encode("utf-8")
        ),
        "redaction_count": redaction_count,
        "persisted": False,
        "database_write_rolled_back": True,
        "external_requests": 0,
        "live_state_changed": False,
    }


def preview_raw_capture_retention(
    db: Session,
    *,
    provider: str | None = None,
    batch_size: int | None = None,
    as_of: datetime | None = None,
    settings_object: Any = settings,
) -> dict[str, Any]:
    policy = _retention_policy(
        settings_object=settings_object,
        provider=provider,
        batch_size=batch_size,
        as_of=as_of,
    )
    base_filters = _retention_filters(policy)
    normalization_exists = _normalization_exists_clause()

    expired_count = int(
        db.scalar(
            select(func.count())
            .select_from(RawBlockchainEvent)
            .where(*base_filters)
        )
        or 0
    )
    protected_count = int(
        db.scalar(
            select(func.count())
            .select_from(RawBlockchainEvent)
            .where(*base_filters, normalization_exists)
        )
        or 0
    )
    eligible_count = int(
        db.scalar(
            select(func.count())
            .select_from(RawBlockchainEvent)
            .where(*base_filters, ~normalization_exists)
        )
        or 0
    )

    candidates = db.execute(
        select(
            RawBlockchainEvent.id,
            RawBlockchainEvent.provider,
            RawBlockchainEvent.event_type,
            RawBlockchainEvent.last_seen_at,
        )
        .where(*base_filters, ~normalization_exists)
        .order_by(
            RawBlockchainEvent.last_seen_at.asc(),
            RawBlockchainEvent.id.asc(),
        )
        .limit(policy.batch_size)
    ).all()

    return {
        "dry_run": True,
        "provider": policy.provider,
        "retention_days": policy.retention_days,
        "cutoff": policy.cutoff,
        "configured_batch_size": int(
            getattr(
                settings_object,
                "RAW_BLOCKCHAIN_CAPTURE_RETENTION_BATCH_SIZE",
                1000,
            )
        ),
        "effective_batch_size": policy.batch_size,
        "expired_events": expired_count,
        "normalization_protected_events": protected_count,
        "eligible_events": eligible_count,
        "would_delete_this_batch": len(candidates),
        "candidate_ids": [int(row.id) for row in candidates],
        "candidates": [
            {
                "id": int(row.id),
                "provider": str(row.provider),
                "event_type": str(row.event_type),
                "last_seen_at": row.last_seen_at,
            }
            for row in candidates
        ],
        "safety": {
            "deletes_events_with_normalization_runs": False,
            "performs_external_requests": False,
            "requires_explicit_prune_enable": True,
            "requires_confirmation": RETENTION_CONFIRMATION,
        },
    }


def prune_raw_capture_retention(
    db: Session,
    *,
    dry_run: bool,
    confirmation: str,
    provider: str | None = None,
    batch_size: int | None = None,
    settings_object: Any = settings,
) -> dict[str, Any]:
    preview = preview_raw_capture_retention(
        db,
        provider=provider,
        batch_size=batch_size,
        settings_object=settings_object,
    )

    if dry_run:
        return {
            **preview,
            "execution": {
                "performed": False,
                "deleted_events": 0,
                "reason": "DRY_RUN",
            },
        }

    if not bool(
        getattr(
            settings_object,
            "RAW_BLOCKCHAIN_CAPTURE_PRUNE_ENABLED",
            False,
        )
    ):
        raise RawCaptureGovernanceError(
            "La cancellazione retention raw capture è disabilitata.",
            code="RAW_CAPTURE_PRUNE_DISABLED",
        )

    if str(confirmation or "").strip() != RETENTION_CONFIRMATION:
        raise RawCaptureGovernanceError(
            "Conferma retention non valida.",
            code="RAW_CAPTURE_PRUNE_CONFIRMATION_REQUIRED",
            status_code=422,
        )

    policy = _retention_policy(
        settings_object=settings_object,
        provider=provider,
        batch_size=batch_size,
        as_of=None,
    )
    candidate_ids = [
        int(event_id)
        for event_id in preview["candidate_ids"]
    ]
    if not candidate_ids:
        return {
            **preview,
            "dry_run": False,
            "execution": {
                "performed": True,
                "deleted_events": 0,
                "reason": "NO_ELIGIBLE_EVENTS",
            },
        }

    try:
        result = db.execute(
            delete(RawBlockchainEvent).where(
                RawBlockchainEvent.id.in_(candidate_ids),
                *_retention_filters(policy),
                ~_normalization_exists_clause(),
            )
        )
        deleted_events = int(result.rowcount or 0)
        db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        **preview,
        "dry_run": False,
        "execution": {
            "performed": True,
            "deleted_events": deleted_events,
            "reason": "PRUNED",
        },
    }
