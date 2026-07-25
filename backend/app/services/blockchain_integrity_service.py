from __future__ import annotations

import copy
import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import and_, exists, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models.blockchain_integrity import (
    NormalizationRun,
    RawBlockchainEvent,
)


NORMALIZATION_STATUSES = frozenset(
    {
        "PENDING",
        "RUNNING",
        "COMPLETED",
        "PARTIAL",
        "FAILED",
        "SKIPPED",
    }
)
PROCESSED_NORMALIZATION_STATUSES = frozenset(
    {"COMPLETED", "PARTIAL", "SKIPPED"}
)
TERMINAL_NORMALIZATION_STATUSES = frozenset(
    {"COMPLETED", "PARTIAL", "FAILED", "SKIPPED"}
)
MAX_ERROR_MESSAGE_LENGTH = 2000
MAX_WARNING_LENGTH = 500
MAX_METADATA_STRING_LENGTH = 2000
MAX_METADATA_DEPTH = 8

_SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)(?:api[_-]?key|authorization|bearer|password|passwd|"
    r"private[_-]?key|secret|seed|mnemonic|access[_-]?token|refresh[_-]?token)"
)
_ASSIGNMENT_SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_ -]?key|authorization|password|private[_ -]?key|"
    r"secret|seed phrase|mnemonic|access[_ -]?token|refresh[_ -]?token)"
    r"\s*[:=]\s*([^\s,;]+)"
)
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_URL_SECRET_PATTERN = re.compile(
    r"(?i)([?&](?:api[-_]?key|key|token|secret|password)=)[^&#\s]+"
)
_URL_CREDENTIAL_PATTERN = re.compile(
    r"(?i)([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^@\s/]+)@"
)
_CONTROL_CHARACTER_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_COMMITMENT_RANK = {
    "processed": 1,
    "confirmed": 2,
    "finalized": 3,
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime | None) -> datetime:
    resolved = value or utc_now()
    if resolved.tzinfo is None:
        return resolved.replace(tzinfo=timezone.utc)
    return resolved.astimezone(timezone.utc)


def _required_text(value: object, field_name: str, *, uppercase: bool = False) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field_name} non può essere vuoto.")
    return normalized.upper() if uppercase else normalized.lower()


def _optional_text(value: object | None, *, lowercase: bool = False) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return normalized.lower() if lowercase else normalized


def _assert_payload_contains_no_secrets(value: Any, *, depth: int = 0) -> None:
    if depth >= MAX_METADATA_DEPTH + 8:
        raise ValueError("Il payload blockchain supera la profondità JSON consentita.")
    if isinstance(value, dict):
        for raw_key, item in value.items():
            key = str(raw_key)
            if _SENSITIVE_KEY_PATTERN.search(key):
                raise ValueError(
                    "Il payload blockchain contiene un campo sensibile non consentito."
                )
            _assert_payload_contains_no_secrets(item, depth=depth + 1)
        return
    if isinstance(value, list):
        for item in value:
            _assert_payload_contains_no_secrets(item, depth=depth + 1)
        return
    if isinstance(value, str) and (
        _BEARER_PATTERN.search(value)
        or _URL_SECRET_PATTERN.search(value)
        or _URL_CREDENTIAL_PATTERN.search(value)
    ):
        raise ValueError(
            "Il payload blockchain contiene un valore sensibile non consentito."
        )


def canonicalize_payload(payload: object) -> str:
    """Return strict, deterministic UTF-8 JSON text for hashing and audit."""

    if not isinstance(payload, (dict, list)):
        raise TypeError("Il payload blockchain deve essere un oggetto o array JSON.")

    _assert_payload_contains_no_secrets(payload)

    try:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exception:
        raise ValueError("Il payload blockchain non è JSON canonizzabile.") from exception


def calculate_payload_hash(payload: object) -> str:
    canonical = canonicalize_payload(payload)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def calculate_deduplication_key(
    *,
    provider: str,
    chain: str,
    network: str,
    event_type: str,
    transaction_signature: str | None,
    observed_wallet: str | None,
    payload_hash: str,
) -> str:
    identity = {
        "provider": provider,
        "chain": chain,
        "network": network,
        "event_type": event_type,
        "transaction_signature": transaction_signature,
        "observed_wallet": observed_wallet,
        "payload_hash": payload_hash,
    }
    canonical_identity = json.dumps(
        identity,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical_identity.encode("utf-8")).hexdigest()


def sanitize_error_message(error: object, *, max_length: int = MAX_ERROR_MESSAGE_LENGTH) -> str:
    message = str(error or "Errore non specificato.")
    message = _CONTROL_CHARACTER_PATTERN.sub(" ", message)
    message = _BEARER_PATTERN.sub("Bearer [REDACTED]", message)
    message = _URL_CREDENTIAL_PATTERN.sub(r"\1[REDACTED]@", message)
    message = _URL_SECRET_PATTERN.sub(r"\1[REDACTED]", message)
    message = _ASSIGNMENT_SECRET_PATTERN.sub(r"\1=[REDACTED]", message)
    message = " ".join(message.split())
    if not message:
        message = "Errore non specificato."
    return message[: max(1, int(max_length))]


def _sanitize_metadata_value(value: Any, *, depth: int = 0) -> Any:
    if depth >= MAX_METADATA_DEPTH:
        return "[MAX_DEPTH_REACHED]"
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else "[NON_FINITE_NUMBER]"
    if isinstance(value, str):
        return sanitize_error_message(value, max_length=MAX_METADATA_STRING_LENGTH)
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)[:200]
            if _SENSITIVE_KEY_PATTERN.search(key):
                sanitized[key] = "[REDACTED]"
            else:
                sanitized[key] = _sanitize_metadata_value(
                    raw_value,
                    depth=depth + 1,
                )
        return sanitized
    if isinstance(value, (list, tuple)):
        return [
            _sanitize_metadata_value(item, depth=depth + 1)
            for item in value[:500]
        ]
    return sanitize_error_message(repr(value), max_length=MAX_METADATA_STRING_LENGTH)


def sanitize_technical_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    if not isinstance(metadata, dict):
        raise TypeError("I metadati tecnici devono essere un oggetto JSON.")
    return _sanitize_metadata_value(metadata)


def _prefer_commitment(current: str | None, candidate: str | None) -> str | None:
    current_value = _optional_text(current, lowercase=True)
    candidate_value = _optional_text(candidate, lowercase=True)
    if candidate_value is None:
        return current_value
    if current_value is None:
        return candidate_value
    current_rank = _COMMITMENT_RANK.get(current_value, 0)
    candidate_rank = _COMMITMENT_RANK.get(candidate_value, 0)
    return candidate_value if candidate_rank > current_rank else current_value


def _apply_repeat_observation(
    event: RawBlockchainEvent,
    *,
    observed_at: datetime,
    slot: int | None,
    block_time: datetime | None,
    commitment: str | None,
) -> RawBlockchainEvent:
    event.observation_count = int(event.observation_count or 0) + 1
    existing_last_seen = _ensure_utc(event.last_seen_at)
    event.last_seen_at = max(existing_last_seen, observed_at)
    if event.slot is None and slot is not None:
        event.slot = slot
    if event.block_time is None and block_time is not None:
        event.block_time = block_time
    event.commitment = _prefer_commitment(event.commitment, commitment)
    existing_updated_at = _ensure_utc(event.updated_at)
    event.updated_at = max(existing_updated_at, observed_at)
    return event


def register_raw_event(
    db: Session,
    *,
    provider: str,
    chain: str,
    network: str,
    event_type: str,
    payload: dict | list,
    transaction_signature: str | None = None,
    slot: int | None = None,
    block_time: datetime | None = None,
    observed_wallet: str | None = None,
    commitment: str | None = None,
    event_metadata: dict[str, Any] | None = None,
    observed_at: datetime | None = None,
) -> tuple[RawBlockchainEvent, bool]:
    normalized_provider = _required_text(provider, "provider")
    normalized_chain = _required_text(chain, "chain")
    normalized_network = _required_text(network, "network")
    normalized_event_type = _required_text(event_type, "event_type", uppercase=True)
    normalized_signature = _optional_text(transaction_signature)
    normalized_wallet = _optional_text(observed_wallet)
    normalized_commitment = _optional_text(commitment, lowercase=True)
    normalized_observed_at = _ensure_utc(observed_at)
    normalized_block_time = (
        _ensure_utc(block_time) if block_time is not None else None
    )

    normalized_slot: int | None = None
    if slot is not None:
        normalized_slot = int(slot)
        if normalized_slot < 0:
            raise ValueError("slot non può essere negativo.")

    payload_hash = calculate_payload_hash(payload)
    deduplication_key = calculate_deduplication_key(
        provider=normalized_provider,
        chain=normalized_chain,
        network=normalized_network,
        event_type=normalized_event_type,
        transaction_signature=normalized_signature,
        observed_wallet=normalized_wallet,
        payload_hash=payload_hash,
    )

    existing = db.execute(
        select(RawBlockchainEvent).where(
            RawBlockchainEvent.deduplication_key == deduplication_key
        )
    ).scalar_one_or_none()
    if existing is not None:
        return (
            _apply_repeat_observation(
                existing,
                observed_at=normalized_observed_at,
                slot=normalized_slot,
                block_time=normalized_block_time,
                commitment=normalized_commitment,
            ),
            False,
        )

    event = RawBlockchainEvent(
        provider=normalized_provider,
        chain=normalized_chain,
        network=normalized_network,
        event_type=normalized_event_type,
        transaction_signature=normalized_signature,
        slot=normalized_slot,
        block_time=normalized_block_time,
        observed_wallet=normalized_wallet,
        commitment=normalized_commitment,
        raw_payload=copy.deepcopy(payload),
        payload_hash=payload_hash,
        deduplication_key=deduplication_key,
        event_metadata=sanitize_technical_metadata(event_metadata),
        first_seen_at=normalized_observed_at,
        last_seen_at=normalized_observed_at,
        observation_count=1,
        updated_at=normalized_observed_at,
    )

    try:
        with db.begin_nested():
            db.add(event)
            db.flush()
        return event, True
    except IntegrityError:
        existing = db.execute(
            select(RawBlockchainEvent)
            .where(RawBlockchainEvent.deduplication_key == deduplication_key)
            .with_for_update()
        ).scalar_one()
        return (
            _apply_repeat_observation(
                existing,
                observed_at=normalized_observed_at,
                slot=normalized_slot,
                block_time=normalized_block_time,
                commitment=normalized_commitment,
            ),
            False,
        )


def create_normalization_run(
    db: Session,
    *,
    raw_event_id: int,
    parser_name: str,
    parser_version: str,
    technical_metadata: dict[str, Any] | None = None,
    start_immediately: bool = True,
    started_at: datetime | None = None,
) -> NormalizationRun:
    if db.get(RawBlockchainEvent, raw_event_id) is None:
        raise ValueError("Raw blockchain event non trovato.")

    normalized_parser_name = _required_text(parser_name, "parser_name")
    normalized_parser_version = str(parser_version or "").strip()
    if not normalized_parser_version:
        raise ValueError("parser_version non può essere vuoto.")

    now = _ensure_utc(started_at)
    run = NormalizationRun(
        run_id=str(uuid4()),
        raw_event_id=raw_event_id,
        parser_name=normalized_parser_name,
        parser_version=normalized_parser_version,
        status="RUNNING" if start_immediately else "PENDING",
        started_at=now if start_immediately else None,
        produced_event_count=0,
        produced_trade_count=0,
        warnings=[],
        error_message=None,
        technical_metadata=sanitize_technical_metadata(technical_metadata),
        updated_at=now,
    )
    db.add(run)
    db.flush()
    return run


def start_normalization_run(
    db: Session,
    run: NormalizationRun,
    *,
    started_at: datetime | None = None,
) -> NormalizationRun:
    if run.status != "PENDING":
        raise ValueError("Solo una normalization run PENDING può essere avviata.")
    now = _ensure_utc(started_at)
    run.status = "RUNNING"
    run.started_at = now
    run.updated_at = now
    db.flush()
    return run


def _sanitize_warnings(warnings: list[object] | None) -> list[str]:
    return [
        sanitize_error_message(item, max_length=MAX_WARNING_LENGTH)
        for item in (warnings or [])[:200]
    ]


def complete_normalization_run(
    db: Session,
    run: NormalizationRun,
    *,
    produced_event_count: int = 0,
    produced_trade_count: int = 0,
    warnings: list[object] | None = None,
    technical_metadata: dict[str, Any] | None = None,
    partial: bool = False,
    completed_at: datetime | None = None,
) -> NormalizationRun:
    if run.status in TERMINAL_NORMALIZATION_STATUSES:
        raise ValueError("La normalization run è già in uno stato terminale.")
    event_count = int(produced_event_count)
    trade_count = int(produced_trade_count)
    if event_count < 0 or trade_count < 0:
        raise ValueError("I contatori prodotti non possono essere negativi.")

    now = _ensure_utc(completed_at)
    run.status = "PARTIAL" if partial else "COMPLETED"
    run.started_at = run.started_at or now
    run.completed_at = now
    run.produced_event_count = event_count
    run.produced_trade_count = trade_count
    run.warnings = _sanitize_warnings(warnings)
    run.error_message = None
    if technical_metadata is not None:
        run.technical_metadata = sanitize_technical_metadata(technical_metadata)
    run.updated_at = now
    db.flush()
    return run


def fail_normalization_run(
    db: Session,
    run: NormalizationRun,
    error: object,
    *,
    warnings: list[object] | None = None,
    technical_metadata: dict[str, Any] | None = None,
    completed_at: datetime | None = None,
) -> NormalizationRun:
    if run.status in TERMINAL_NORMALIZATION_STATUSES:
        raise ValueError("La normalization run è già in uno stato terminale.")

    now = _ensure_utc(completed_at)
    run.status = "FAILED"
    run.started_at = run.started_at or now
    run.completed_at = now
    run.warnings = _sanitize_warnings(warnings)
    run.error_message = sanitize_error_message(error)
    if technical_metadata is not None:
        run.technical_metadata = sanitize_technical_metadata(technical_metadata)
    run.updated_at = now
    db.flush()
    return run


def skip_normalization_run(
    db: Session,
    run: NormalizationRun,
    *,
    reason: object,
    completed_at: datetime | None = None,
) -> NormalizationRun:
    if run.status in TERMINAL_NORMALIZATION_STATUSES:
        raise ValueError("La normalization run è già in uno stato terminale.")
    now = _ensure_utc(completed_at)
    run.status = "SKIPPED"
    run.started_at = run.started_at or now
    run.completed_at = now
    run.warnings = [sanitize_error_message(reason, max_length=MAX_WARNING_LENGTH)]
    run.error_message = None
    run.updated_at = now
    db.flush()
    return run


def _apply_raw_event_filters(
    statement,
    *,
    provider: str | None = None,
    event_type: str | None = None,
    transaction_signature: str | None = None,
    observed_wallet: str | None = None,
    observed_from: datetime | None = None,
    observed_to: datetime | None = None,
):
    if provider:
        statement = statement.where(
            RawBlockchainEvent.provider == str(provider).strip().lower()
        )
    if event_type:
        statement = statement.where(
            RawBlockchainEvent.event_type == str(event_type).strip().upper()
        )
    if transaction_signature:
        statement = statement.where(
            RawBlockchainEvent.transaction_signature
            == str(transaction_signature).strip()
        )
    if observed_wallet:
        statement = statement.where(
            RawBlockchainEvent.observed_wallet == str(observed_wallet).strip()
        )
    if observed_from is not None:
        statement = statement.where(
            RawBlockchainEvent.first_seen_at >= _ensure_utc(observed_from)
        )
    if observed_to is not None:
        statement = statement.where(
            RawBlockchainEvent.first_seen_at < _ensure_utc(observed_to)
        )
    return statement


def get_unnormalized_events(
    db: Session,
    *,
    parser_name: str | None = None,
    provider: str | None = None,
    event_type: str | None = None,
    transaction_signature: str | None = None,
    observed_wallet: str | None = None,
    observed_from: datetime | None = None,
    observed_to: datetime | None = None,
    limit: int = 100,
) -> list[RawBlockchainEvent]:
    processed_conditions = [
        NormalizationRun.raw_event_id == RawBlockchainEvent.id,
        NormalizationRun.status.in_(PROCESSED_NORMALIZATION_STATUSES),
    ]
    if parser_name:
        processed_conditions.append(
            NormalizationRun.parser_name == str(parser_name).strip().lower()
        )

    statement = select(RawBlockchainEvent).where(
        ~exists(select(1).where(and_(*processed_conditions)))
    )
    statement = _apply_raw_event_filters(
        statement,
        provider=provider,
        event_type=event_type,
        transaction_signature=transaction_signature,
        observed_wallet=observed_wallet,
        observed_from=observed_from,
        observed_to=observed_to,
    )
    statement = statement.order_by(
        RawBlockchainEvent.first_seen_at.asc(),
        RawBlockchainEvent.id.asc(),
    ).limit(max(1, min(int(limit), 1000)))
    return list(db.execute(statement).scalars())


def get_events_with_outdated_parser(
    db: Session,
    *,
    parser_name: str,
    current_parser_version: str,
    provider: str | None = None,
    event_type: str | None = None,
    transaction_signature: str | None = None,
    observed_wallet: str | None = None,
    observed_from: datetime | None = None,
    observed_to: datetime | None = None,
    limit: int = 100,
) -> list[RawBlockchainEvent]:
    normalized_parser_name = _required_text(parser_name, "parser_name")
    normalized_version = str(current_parser_version or "").strip()
    if not normalized_version:
        raise ValueError("current_parser_version non può essere vuoto.")

    has_older_success = exists(
        select(1).where(
            NormalizationRun.raw_event_id == RawBlockchainEvent.id,
            NormalizationRun.parser_name == normalized_parser_name,
            NormalizationRun.parser_version != normalized_version,
            NormalizationRun.status.in_(PROCESSED_NORMALIZATION_STATUSES),
        )
    )
    has_current_success = exists(
        select(1).where(
            NormalizationRun.raw_event_id == RawBlockchainEvent.id,
            NormalizationRun.parser_name == normalized_parser_name,
            NormalizationRun.parser_version == normalized_version,
            NormalizationRun.status.in_(PROCESSED_NORMALIZATION_STATUSES),
        )
    )

    statement = select(RawBlockchainEvent).where(
        has_older_success,
        ~has_current_success,
    )
    statement = _apply_raw_event_filters(
        statement,
        provider=provider,
        event_type=event_type,
        transaction_signature=transaction_signature,
        observed_wallet=observed_wallet,
        observed_from=observed_from,
        observed_to=observed_to,
    )
    statement = statement.order_by(
        RawBlockchainEvent.first_seen_at.asc(),
        RawBlockchainEvent.id.asc(),
    ).limit(max(1, min(int(limit), 1000)))
    return list(db.execute(statement).scalars())


def get_events_for_reprocessing(
    db: Session,
    *,
    parser_name: str,
    current_parser_version: str,
    provider: str | None = None,
    event_type: str | None = None,
    transaction_signature: str | None = None,
    observed_wallet: str | None = None,
    observed_from: datetime | None = None,
    observed_to: datetime | None = None,
    limit: int = 100,
) -> list[RawBlockchainEvent]:
    normalized_parser_name = _required_text(parser_name, "parser_name")
    normalized_version = str(current_parser_version or "").strip()
    if not normalized_version:
        raise ValueError("current_parser_version non può essere vuoto.")

    has_current_success = exists(
        select(1).where(
            NormalizationRun.raw_event_id == RawBlockchainEvent.id,
            NormalizationRun.parser_name == normalized_parser_name,
            NormalizationRun.parser_version == normalized_version,
            NormalizationRun.status.in_(PROCESSED_NORMALIZATION_STATUSES),
        )
    )
    has_any_attempt = exists(
        select(1).where(
            NormalizationRun.raw_event_id == RawBlockchainEvent.id,
            NormalizationRun.parser_name == normalized_parser_name,
        )
    )
    has_failed_or_old = exists(
        select(1).where(
            NormalizationRun.raw_event_id == RawBlockchainEvent.id,
            NormalizationRun.parser_name == normalized_parser_name,
            or_(
                NormalizationRun.status == "FAILED",
                and_(
                    NormalizationRun.status.in_(PROCESSED_NORMALIZATION_STATUSES),
                    NormalizationRun.parser_version != normalized_version,
                ),
            ),
        )
    )

    statement = select(RawBlockchainEvent).where(
        ~has_current_success,
        or_(~has_any_attempt, has_failed_or_old),
    )
    statement = _apply_raw_event_filters(
        statement,
        provider=provider,
        event_type=event_type,
        transaction_signature=transaction_signature,
        observed_wallet=observed_wallet,
        observed_from=observed_from,
        observed_to=observed_to,
    )
    statement = statement.order_by(
        RawBlockchainEvent.first_seen_at.asc(),
        RawBlockchainEvent.id.asc(),
    ).limit(max(1, min(int(limit), 1000)))
    return list(db.execute(statement).scalars())
