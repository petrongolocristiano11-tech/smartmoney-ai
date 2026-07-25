from __future__ import annotations

import hashlib
import logging
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.database.session import SessionLocal
from backend.app.models.blockchain_integrity import RawBlockchainEvent
from backend.app.services.blockchain_integrity_service import (
    canonicalize_payload,
    register_raw_event,
    sanitize_error_message,
    sanitize_technical_metadata,
)


logger = logging.getLogger("smartmoney.raw_capture")

CAPTURE_MODE = "PASSIVE_SHADOW"
CAPTURE_STATUS_CREATED = "CREATED"
CAPTURE_STATUS_DEDUPLICATED = "DEDUPLICATED"
CAPTURE_STATUS_DISABLED = "DISABLED"
CAPTURE_STATUS_PROVIDER_DISABLED = "PROVIDER_DISABLED"
CAPTURE_STATUS_EVENT_TYPE_DISABLED = "EVENT_TYPE_DISABLED"
CAPTURE_STATUS_OVERSIZE = "OVERSIZE"
CAPTURE_STATUS_FAILED = "FAILED"

MAX_CAPTURE_DEPTH = 64
MAX_CAPTURE_ITEMS = 100_000

_SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)(?:api[_-]?key|authorization|bearer|password|passwd|"
    r"private[_-]?key|secret|seed|mnemonic|access[_-]?token|refresh[_-]?token)"
)
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_URL_SECRET_PATTERN = re.compile(
    r"(?i)([?&])(?:api[-_]?key|key|token|secret|password)=[^&#\s]+"
)
_URL_CREDENTIAL_PATTERN = re.compile(
    r"(?i)([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^@\s/]+)@"
)
_ASSIGNMENT_SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_ -]?key|authorization|password|private[_ -]?key|"
    r"secret|seed phrase|mnemonic|access[_ -]?token|refresh[_ -]?token)"
    r"\s*[:=]\s*([^\s,;]+)"
)


@dataclass(frozen=True, slots=True)
class RawCaptureContext:
    provider: str
    event_type: str
    chain: str = "solana"
    network: str = "mainnet-beta"
    transaction_signature: str | None = None
    slot: int | None = None
    block_time: datetime | int | float | None = None
    observed_wallet: str | None = None
    commitment: str | None = None
    technical_metadata: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class RawCaptureResult:
    status: str
    event_id: int | None = None
    created: bool = False
    payload_size_bytes: int = 0
    redaction_count: int = 0
    error_message: str | None = None


class _RawCaptureMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counts: Counter[str] = Counter()

    def record(self, status: str) -> None:
        with self._lock:
            self._counts[str(status)] += 1

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return dict(sorted(self._counts.items()))

    def reset(self) -> None:
        with self._lock:
            self._counts.clear()


_metrics = _RawCaptureMetrics()


def reset_raw_capture_runtime_metrics() -> None:
    _metrics.reset()


def _record_result(result: RawCaptureResult) -> RawCaptureResult:
    _metrics.record(result.status)
    return result


def _redacted_key(raw_key: str) -> str:
    digest = hashlib.sha256(raw_key.lower().encode("utf-8")).hexdigest()[:16]
    return f"redacted_field_{digest}"


def _sanitize_capture_string(value: str) -> tuple[str, int]:
    sanitized = value
    sanitized = _BEARER_PATTERN.sub("Bearer [REDACTED]", sanitized)
    sanitized = _URL_CREDENTIAL_PATTERN.sub(r"\1[REDACTED]@", sanitized)
    sanitized = _URL_SECRET_PATTERN.sub(r"\1redacted=[REDACTED]", sanitized)
    sanitized = _ASSIGNMENT_SECRET_PATTERN.sub("credential=[REDACTED]", sanitized)
    return sanitized, int(sanitized != value)


def sanitize_provider_payload(
    payload: object,
    *,
    depth: int = 0,
    item_counter: list[int] | None = None,
) -> tuple[dict | list, int]:
    """Create a JSON-safe copy while removing credential-shaped content."""

    if not isinstance(payload, (dict, list)):
        raise TypeError("Il payload provider deve essere un oggetto o array JSON.")

    counter = item_counter if item_counter is not None else [0]

    def visit(value: Any, current_depth: int) -> tuple[Any, int]:
        if current_depth > MAX_CAPTURE_DEPTH:
            raise ValueError("Il payload provider supera la profondità consentita.")

        counter[0] += 1
        if counter[0] > MAX_CAPTURE_ITEMS:
            raise ValueError("Il payload provider contiene troppi elementi.")

        if value is None or isinstance(value, (bool, int, float)):
            return value, 0

        if isinstance(value, str):
            return _sanitize_capture_string(value)

        if isinstance(value, list):
            sanitized_items: list[Any] = []
            redactions = 0
            for item in value:
                sanitized_item, item_redactions = visit(item, current_depth + 1)
                sanitized_items.append(sanitized_item)
                redactions += item_redactions
            return sanitized_items, redactions

        if isinstance(value, dict):
            sanitized_dict: dict[str, Any] = {}
            redactions = 0
            for raw_key, raw_value in value.items():
                key = str(raw_key)
                if _SENSITIVE_KEY_PATTERN.search(key):
                    sanitized_dict[_redacted_key(key)] = "[REDACTED]"
                    redactions += 1
                    continue

                sanitized_value, value_redactions = visit(
                    raw_value,
                    current_depth + 1,
                )
                sanitized_dict[key] = sanitized_value
                redactions += value_redactions
            return sanitized_dict, redactions

        raise TypeError("Il payload provider contiene un valore non JSON.")

    sanitized, redaction_count = visit(payload, depth)
    if not isinstance(sanitized, (dict, list)):
        raise AssertionError("Payload provider sanificato in formato inatteso.")
    return sanitized, redaction_count


def _normalize_block_time(value: datetime | int | float | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    timestamp = float(value)
    if timestamp <= 0:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def _configured_providers(settings_object: Any) -> frozenset[str]:
    configured = getattr(
        settings_object,
        "raw_blockchain_capture_providers",
        None,
    )
    if configured is not None:
        return frozenset(str(item).strip().lower() for item in configured if str(item).strip())

    raw_value = str(
        getattr(settings_object, "RAW_BLOCKCHAIN_CAPTURE_PROVIDERS", "") or ""
    )
    return frozenset(
        item.strip().lower()
        for item in raw_value.split(",")
        if item.strip()
    )


def _configured_event_types(settings_object: Any) -> frozenset[str]:
    configured = getattr(
        settings_object,
        "raw_blockchain_capture_event_types",
        None,
    )
    if configured is not None:
        return frozenset(
            str(item).strip().upper()
            for item in configured
            if str(item).strip()
        )

    raw_value = str(
        getattr(
            settings_object,
            "RAW_BLOCKCHAIN_CAPTURE_EVENT_TYPES",
            "",
        )
        or ""
    )
    return frozenset(
        item.strip().upper()
        for item in raw_value.split(",")
        if item.strip()
    )


def capture_raw_blockchain_payload_safely(
    payload: object,
    *,
    context: RawCaptureContext,
    session_factory: Callable[[], Session] | None = None,
    settings_object: Any = settings,
) -> RawCaptureResult:
    """Persist an already-received provider payload without affecting callers.

    This is deliberately fail-open for Milestone 2. It never performs provider
    requests and never raises capture failures into the existing data pipeline.
    """

    provider = str(context.provider or "").strip().lower()
    event_type = str(context.event_type or "").strip().upper()

    if not bool(getattr(settings_object, "RAW_BLOCKCHAIN_CAPTURE_ENABLED", False)):
        return _record_result(RawCaptureResult(status=CAPTURE_STATUS_DISABLED))

    if provider not in _configured_providers(settings_object):
        return _record_result(
            RawCaptureResult(status=CAPTURE_STATUS_PROVIDER_DISABLED)
        )

    if event_type not in _configured_event_types(settings_object):
        return _record_result(
            RawCaptureResult(status=CAPTURE_STATUS_EVENT_TYPE_DISABLED)
        )

    try:
        sanitized_payload, redaction_count = sanitize_provider_payload(payload)
        canonical = canonicalize_payload(sanitized_payload)
        payload_size_bytes = len(canonical.encode("utf-8"))
        max_payload_bytes = int(
            getattr(
                settings_object,
                "RAW_BLOCKCHAIN_CAPTURE_MAX_PAYLOAD_BYTES",
                4_000_000,
            )
        )

        if payload_size_bytes > max_payload_bytes:
            logger.warning(
                "raw_capture_skipped provider=%s event_type=%s reason=oversize "
                "payload_size_bytes=%s max_payload_bytes=%s",
                provider,
                event_type,
                payload_size_bytes,
                max_payload_bytes,
            )
            return _record_result(
                RawCaptureResult(
                    status=CAPTURE_STATUS_OVERSIZE,
                    payload_size_bytes=payload_size_bytes,
                    redaction_count=redaction_count,
                )
            )

        metadata = sanitize_technical_metadata(
            {
                **(context.technical_metadata or {}),
                "capture_mode": CAPTURE_MODE,
                "capture_source": "provider_response",
                "payload_size_bytes": payload_size_bytes,
                "redaction_count": redaction_count,
            }
        )

        factory = session_factory or SessionLocal
        db = factory()
        try:
            event, created = register_raw_event(
                db,
                provider=provider,
                chain=context.chain,
                network=context.network,
                event_type=event_type,
                transaction_signature=context.transaction_signature,
                slot=context.slot,
                block_time=_normalize_block_time(context.block_time),
                observed_wallet=context.observed_wallet,
                commitment=context.commitment,
                payload=sanitized_payload,
                event_metadata=metadata,
            )
            db.commit()
            status = (
                CAPTURE_STATUS_CREATED
                if created
                else CAPTURE_STATUS_DEDUPLICATED
            )
            return _record_result(
                RawCaptureResult(
                    status=status,
                    event_id=event.id,
                    created=created,
                    payload_size_bytes=payload_size_bytes,
                    redaction_count=redaction_count,
                )
            )
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    except Exception as exception:
        safe_error = sanitize_error_message(exception, max_length=500)
        logger.warning(
            "raw_capture_failed provider=%s event_type=%s error=%s",
            provider or "unknown",
            event_type or "UNKNOWN",
            safe_error,
        )
        return _record_result(
            RawCaptureResult(
                status=CAPTURE_STATUS_FAILED,
                error_message=safe_error,
            )
        )


def get_raw_capture_status(
    db: Session,
    *,
    settings_object: Any = settings,
) -> dict[str, Any]:
    total_events = int(
        db.scalar(select(func.count()).select_from(RawBlockchainEvent)) or 0
    )
    provider_rows = db.execute(
        select(
            RawBlockchainEvent.provider,
            func.count(RawBlockchainEvent.id),
            func.sum(RawBlockchainEvent.observation_count),
        )
        .group_by(RawBlockchainEvent.provider)
        .order_by(RawBlockchainEvent.provider)
    ).all()
    latest_event = db.execute(
        select(RawBlockchainEvent)
        .order_by(RawBlockchainEvent.last_seen_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    return {
        "enabled": bool(
            getattr(settings_object, "RAW_BLOCKCHAIN_CAPTURE_ENABLED", False)
        ),
        "mode": CAPTURE_MODE,
        "providers": sorted(_configured_providers(settings_object)),
        "event_types": sorted(_configured_event_types(settings_object)),
        "max_payload_bytes": int(
            getattr(
                settings_object,
                "RAW_BLOCKCHAIN_CAPTURE_MAX_PAYLOAD_BYTES",
                4_000_000,
            )
        ),
        "persisted": {
            "raw_events": total_events,
            "by_provider": [
                {
                    "provider": str(provider),
                    "raw_events": int(event_count or 0),
                    "observations": int(observation_count or 0),
                }
                for provider, event_count, observation_count in provider_rows
            ],
            "latest_event": (
                {
                    "id": latest_event.id,
                    "provider": latest_event.provider,
                    "event_type": latest_event.event_type,
                    "last_seen_at": latest_event.last_seen_at,
                }
                if latest_event is not None
                else None
            ),
        },
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
        },
        "runtime_metrics": _metrics.snapshot(),
        "operational_guards": {
            "fail_open": True,
            "performs_external_requests": False,
            "starts_normalization": False,
            "changes_pipeline_return_values": False,
        },
    }
