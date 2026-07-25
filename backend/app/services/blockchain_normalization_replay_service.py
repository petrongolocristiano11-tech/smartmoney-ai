from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    NormalizationArtifact,
    NormalizationReplayBatch,
    NormalizationRun,
    RawBlockchainEvent,
)
from backend.app.services.blockchain_integrity_service import (
    PROCESSED_NORMALIZATION_STATUSES,
    complete_normalization_run,
    create_normalization_run,
    fail_normalization_run,
    get_events_for_reprocessing,
    get_events_with_outdated_parser,
    get_unnormalized_events,
    sanitize_error_message,
    sanitize_technical_metadata,
    skip_normalization_run,
)
from backend.app.services.blockchain_parser_registry_service import (
    DEFAULT_PARSER_REGISTRY,
    ParserDefinition,
    ParserRegistry,
    ParserRegistryError,
    validate_parser_artifacts,
)


REPLAY_CONFIRMATION = "EXECUTE_CONTROLLED_REPLAY"
REPLAY_SELECTION_MODES = frozenset(
    {"UNNORMALIZED", "OUTDATED", "REPROCESS"}
)


class NormalizationReplayError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        status_code: int = 422,
    ):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_selection_mode(value: str) -> str:
    normalized = str(value or "").strip().upper()
    if normalized not in REPLAY_SELECTION_MODES:
        raise NormalizationReplayError(
            "Selection mode replay non valida.",
            code="REPLAY_SELECTION_MODE_INVALID",
        )
    return normalized


def _allowed_parser_names(settings_object: Any) -> frozenset[str]:
    configured = getattr(
        settings_object,
        "raw_blockchain_replay_allowed_parsers",
        None,
    )
    if configured is None:
        configured = str(
            getattr(
                settings_object,
                "RAW_BLOCKCHAIN_REPLAY_ALLOWED_PARSERS",
                "",
            )
            or ""
        ).split(",")
    return frozenset(
        str(parser).strip().lower()
        for parser in configured
        if str(parser).strip()
    )


def _resolve_parser(
    parser_name: str,
    parser_version: str,
    *,
    registry: ParserRegistry,
    settings_object: Any,
) -> ParserDefinition:
    try:
        definition = registry.get(parser_name, parser_version)
    except ParserRegistryError as exception:
        raise NormalizationReplayError(
            str(exception),
            code=exception.code,
            status_code=exception.status_code,
        ) from exception

    if definition.name not in _allowed_parser_names(settings_object):
        raise NormalizationReplayError(
            "Parser non incluso nell'allowlist replay.",
            code="REPLAY_PARSER_NOT_ALLOWED",
            status_code=403,
        )
    if definition.performs_external_requests or definition.writes_trades:
        raise NormalizationReplayError(
            "Parser incompatibile con le guardie M4.",
            code="REPLAY_PARSER_UNSAFE",
            status_code=409,
        )
    return definition


def _effective_limit(limit: int, settings_object: Any) -> int:
    configured = int(
        getattr(settings_object, "RAW_BLOCKCHAIN_REPLAY_MAX_BATCH_SIZE", 100)
    )
    requested = int(limit)
    if requested < 1:
        raise NormalizationReplayError(
            "Il limite replay deve essere positivo.",
            code="REPLAY_LIMIT_INVALID",
        )
    return min(requested, configured)


def _select_events(
    db: Session,
    *,
    definition: ParserDefinition,
    selection_mode: str,
    provider: str | None,
    event_type: str | None,
    transaction_signature: str | None,
    observed_wallet: str | None,
    observed_from: datetime | None,
    observed_to: datetime | None,
    limit: int,
) -> list[RawBlockchainEvent]:
    common = {
        "provider": provider,
        "event_type": event_type,
        "transaction_signature": transaction_signature,
        "observed_wallet": observed_wallet,
        "observed_from": observed_from,
        "observed_to": observed_to,
        "limit": limit,
    }
    if selection_mode == "UNNORMALIZED":
        candidates = get_unnormalized_events(
            db,
            parser_name=definition.name,
            **common,
        )
    elif selection_mode == "OUTDATED":
        candidates = get_events_with_outdated_parser(
            db,
            parser_name=definition.name,
            current_parser_version=definition.version,
            **common,
        )
    else:
        candidates = get_events_for_reprocessing(
            db,
            parser_name=definition.name,
            current_parser_version=definition.version,
            **common,
        )
    return [event for event in candidates if definition.supports(event)]


def get_parser_registry_status(
    *,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    settings_object: Any = settings,
) -> dict[str, Any]:
    definitions = registry.list()
    allowed = _allowed_parser_names(settings_object)
    return {
        "replay_enabled": bool(
            getattr(settings_object, "RAW_BLOCKCHAIN_REPLAY_ENABLED", False)
        ),
        "max_batch_size": int(
            getattr(settings_object, "RAW_BLOCKCHAIN_REPLAY_MAX_BATCH_SIZE", 100)
        ),
        "allowed_parsers": sorted(allowed),
        "registry_manifest_hash": registry.manifest_hash(),
        "parsers": [
            {
                **definition.as_dict(),
                "allowed_for_replay": definition.name in allowed,
            }
            for definition in definitions
        ],
        "operational_guards": {
            "performs_external_requests": False,
            "writes_trades": False,
            "starts_workers": False,
            "automatic_execution": False,
        },
    }


def preview_normalization_replay(
    db: Session,
    *,
    parser_name: str,
    parser_version: str,
    selection_mode: str = "REPROCESS",
    provider: str | None = None,
    event_type: str | None = None,
    transaction_signature: str | None = None,
    observed_wallet: str | None = None,
    observed_from: datetime | None = None,
    observed_to: datetime | None = None,
    limit: int = 100,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    settings_object: Any = settings,
) -> dict[str, Any]:
    definition = _resolve_parser(
        parser_name,
        parser_version,
        registry=registry,
        settings_object=settings_object,
    )
    mode = _normalize_selection_mode(selection_mode)
    effective_limit = _effective_limit(limit, settings_object)
    candidates = _select_events(
        db,
        definition=definition,
        selection_mode=mode,
        provider=provider,
        event_type=event_type,
        transaction_signature=transaction_signature,
        observed_wallet=observed_wallet,
        observed_from=observed_from,
        observed_to=observed_to,
        limit=effective_limit,
    )
    return {
        "dry_run": True,
        "replay_enabled": bool(
            getattr(settings_object, "RAW_BLOCKCHAIN_REPLAY_ENABLED", False)
        ),
        "parser": definition.as_dict(),
        "selection_mode": mode,
        "requested_limit": int(limit),
        "effective_limit": effective_limit,
        "selected_count": len(candidates),
        "candidate_ids": [event.id for event in candidates],
        "candidates": [
            {
                "raw_event_id": event.id,
                "provider": event.provider,
                "event_type": event.event_type,
                "transaction_signature": event.transaction_signature,
                "observed_wallet": event.observed_wallet,
                "first_seen_at": event.first_seen_at,
            }
            for event in candidates
        ],
        "writes_database": False,
        "external_requests": 0,
        "writes_trades": False,
    }


def _has_current_success(
    db: Session,
    *,
    raw_event_id: int,
    definition: ParserDefinition,
) -> bool:
    return bool(
        db.scalar(
            select(NormalizationRun.id)
            .where(
                NormalizationRun.raw_event_id == raw_event_id,
                NormalizationRun.parser_name == definition.name,
                NormalizationRun.parser_version == definition.version,
                NormalizationRun.status.in_(PROCESSED_NORMALIZATION_STATUSES),
            )
            .limit(1)
        )
    )


def _create_artifacts(
    db: Session,
    *,
    run: NormalizationRun,
    event: RawBlockchainEvent,
    definition: ParserDefinition,
    artifacts: list[dict[str, Any]],
) -> None:
    for artifact in artifacts:
        db.add(
            NormalizationArtifact(
                normalization_run_id=run.id,
                raw_event_id=event.id,
                parser_name=definition.name,
                parser_version=definition.version,
                parser_implementation_hash=definition.implementation_hash,
                artifact_type=artifact["artifact_type"],
                artifact_index=artifact["artifact_index"],
                schema_version=artifact["schema_version"],
                payload=artifact["payload"],
                payload_hash=artifact["payload_hash"],
                artifact_metadata=artifact["artifact_metadata"],
            )
        )
    db.flush()


def execute_normalization_replay(
    db: Session,
    *,
    parser_name: str,
    parser_version: str,
    selection_mode: str,
    confirmation: str,
    provider: str | None = None,
    event_type: str | None = None,
    transaction_signature: str | None = None,
    observed_wallet: str | None = None,
    observed_from: datetime | None = None,
    observed_to: datetime | None = None,
    limit: int = 100,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    settings_object: Any = settings,
) -> dict[str, Any]:
    if not bool(
        getattr(settings_object, "RAW_BLOCKCHAIN_REPLAY_ENABLED", False)
    ):
        raise NormalizationReplayError(
            "Replay normalizzazione disabilitato.",
            code="REPLAY_DISABLED",
            status_code=409,
        )
    if str(confirmation or "").strip() != REPLAY_CONFIRMATION:
        raise NormalizationReplayError(
            "Conferma replay non valida.",
            code="REPLAY_CONFIRMATION_REQUIRED",
            status_code=409,
        )

    definition = _resolve_parser(
        parser_name,
        parser_version,
        registry=registry,
        settings_object=settings_object,
    )
    mode = _normalize_selection_mode(selection_mode)
    effective_limit = _effective_limit(limit, settings_object)
    candidates = _select_events(
        db,
        definition=definition,
        selection_mode=mode,
        provider=provider,
        event_type=event_type,
        transaction_signature=transaction_signature,
        observed_wallet=observed_wallet,
        observed_from=observed_from,
        observed_to=observed_to,
        limit=effective_limit,
    )
    now = _utc_now()
    batch = NormalizationReplayBatch(
        replay_id=str(uuid4()),
        parser_name=definition.name,
        parser_version=definition.version,
        parser_implementation_hash=definition.implementation_hash,
        selection_mode=mode,
        status="RUNNING",
        request_filters=sanitize_technical_metadata(
            {
                "provider": provider,
                "event_type": event_type,
                "transaction_signature": transaction_signature,
                "observed_wallet": observed_wallet,
                "observed_from": observed_from.isoformat()
                if observed_from
                else None,
                "observed_to": observed_to.isoformat() if observed_to else None,
            }
        ),
        requested_limit=effective_limit,
        selected_count=len(candidates),
        processed_count=0,
        completed_count=0,
        failed_count=0,
        skipped_count=0,
        started_at=now,
        completed_at=None,
        error_message=None,
        technical_metadata={
            "registry_manifest_hash": registry.manifest_hash(),
            "external_requests": 0,
            "writes_trades": False,
        },
        updated_at=now,
    )
    db.add(batch)
    db.flush()

    for event in candidates:
        if _has_current_success(
            db,
            raw_event_id=event.id,
            definition=definition,
        ):
            run = create_normalization_run(
                db,
                raw_event_id=event.id,
                parser_name=definition.name,
                parser_version=definition.version,
                technical_metadata={
                    "replay_id": batch.replay_id,
                    "implementation_hash": definition.implementation_hash,
                },
            )
            skip_normalization_run(
                db,
                run,
                reason="Current parser version already completed.",
            )
            batch.processed_count += 1
            batch.skipped_count += 1
            continue

        run = create_normalization_run(
            db,
            raw_event_id=event.id,
            parser_name=definition.name,
            parser_version=definition.version,
            technical_metadata={
                "replay_id": batch.replay_id,
                "selection_mode": mode,
                "implementation_hash": definition.implementation_hash,
                "external_requests": 0,
                "writes_trades": False,
            },
        )
        batch.processed_count += 1
        try:
            parser_outputs = definition.parse(event)
            artifacts = validate_parser_artifacts(definition, parser_outputs)
            try:
                with db.begin_nested():
                    _create_artifacts(
                        db,
                        run=run,
                        event=event,
                        definition=definition,
                        artifacts=artifacts,
                    )
            except IntegrityError:
                skip_normalization_run(
                    db,
                    run,
                    reason="Artifact current parser version already persisted.",
                )
                batch.skipped_count += 1
                continue

            complete_normalization_run(
                db,
                run,
                produced_event_count=len(artifacts),
                produced_trade_count=0,
                technical_metadata={
                    "replay_id": batch.replay_id,
                    "implementation_hash": definition.implementation_hash,
                    "artifact_hashes": [
                        artifact["payload_hash"] for artifact in artifacts
                    ],
                    "external_requests": 0,
                    "writes_trades": False,
                },
            )
            batch.completed_count += 1
        except Exception as exception:
            fail_normalization_run(
                db,
                run,
                exception,
                technical_metadata={
                    "replay_id": batch.replay_id,
                    "implementation_hash": definition.implementation_hash,
                    "external_requests": 0,
                    "writes_trades": False,
                },
            )
            batch.failed_count += 1

    completed_at = _utc_now()
    batch.completed_at = completed_at
    batch.updated_at = completed_at
    if batch.failed_count == 0:
        batch.status = "COMPLETED"
    elif batch.completed_count or batch.skipped_count:
        batch.status = "PARTIAL"
    else:
        batch.status = "FAILED"
        batch.error_message = sanitize_error_message(
            "Tutti gli eventi selezionati hanno fallito la normalizzazione."
        )
    db.commit()
    db.refresh(batch)
    return serialize_replay_batch(batch)


def serialize_replay_batch(batch: NormalizationReplayBatch) -> dict[str, Any]:
    return {
        "replay_id": batch.replay_id,
        "parser_name": batch.parser_name,
        "parser_version": batch.parser_version,
        "parser_implementation_hash": batch.parser_implementation_hash,
        "selection_mode": batch.selection_mode,
        "status": batch.status,
        "request_filters": batch.request_filters,
        "requested_limit": batch.requested_limit,
        "selected_count": batch.selected_count,
        "processed_count": batch.processed_count,
        "completed_count": batch.completed_count,
        "failed_count": batch.failed_count,
        "skipped_count": batch.skipped_count,
        "started_at": batch.started_at,
        "completed_at": batch.completed_at,
        "error_message": batch.error_message,
        "technical_metadata": batch.technical_metadata,
    }


def get_normalization_replay_batch(
    db: Session,
    replay_id: str,
) -> dict[str, Any]:
    normalized = str(replay_id or "").strip()
    batch = db.execute(
        select(NormalizationReplayBatch).where(
            NormalizationReplayBatch.replay_id == normalized
        )
    ).scalar_one_or_none()
    if batch is None:
        raise NormalizationReplayError(
            "Replay batch non trovato.",
            code="REPLAY_BATCH_NOT_FOUND",
            status_code=404,
        )
    return serialize_replay_batch(batch)
