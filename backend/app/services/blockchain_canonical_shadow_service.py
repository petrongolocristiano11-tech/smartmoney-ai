from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalNormalizedEvent,
    CanonicalShadowValidationBatch,
    CanonicalShadowValidationResult,
    NormalizationArtifact,
    RawBlockchainEvent,
)
from backend.app.models.trade import Trade
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    canonicalize_payload,
    sanitize_error_message,
    sanitize_technical_metadata,
)
from backend.app.services.blockchain_parser_registry_service import (
    DEFAULT_PARSER_REGISTRY,
    ParserRegistry,
    ParserRegistryError,
)


CANONICAL_PARSER_NAME = "swap_canonical_event"
CANONICAL_PARSER_VERSION = "1.0.0"
CANONICAL_ARTIFACT_TYPE = "CANONICAL_SWAP_EVENT"
CANONICAL_MATERIALIZE_CONFIRMATION = "MATERIALIZE_CANONICAL_EVENTS"
SHADOW_VALIDATION_CONFIRMATION = "EXECUTE_SHADOW_VALIDATION"
SHADOW_COMPARATOR_VERSION = "canonical-trade-shadow/1"


class CanonicalShadowError(ValueError):
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


def _aware_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse_datetime(value: object) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _decimal_string(value: object) -> str | None:
    parsed = _decimal(value)
    if parsed is None:
        return None
    normalized = format(parsed.normalize(), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def _effective_limit(requested: int, configured: int) -> int:
    if int(requested) < 1:
        raise CanonicalShadowError(
            "Il limite deve essere positivo.",
            code="CANONICAL_LIMIT_INVALID",
        )
    return min(int(requested), int(configured))


def _canonical_definition(registry: ParserRegistry):
    try:
        return registry.get(CANONICAL_PARSER_NAME, CANONICAL_PARSER_VERSION)
    except ParserRegistryError as exception:
        raise CanonicalShadowError(
            str(exception),
            code=exception.code,
            status_code=exception.status_code,
        ) from exception


def get_canonical_shadow_status(
    db: Session,
    *,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    settings_object: Any = settings,
) -> dict[str, Any]:
    definition = _canonical_definition(registry)
    return {
        "canonical_normalization_enabled": bool(
            getattr(settings_object, "CANONICAL_NORMALIZATION_ENABLED", False)
        ),
        "shadow_validation_enabled": bool(
            getattr(settings_object, "CANONICAL_SHADOW_VALIDATION_ENABLED", False)
        ),
        "parser": definition.as_dict(),
        "canonical_event_count": int(
            db.query(CanonicalNormalizedEvent).count()
        ),
        "shadow_batch_count": int(
            db.query(CanonicalShadowValidationBatch).count()
        ),
        "operational_guards": {
            "external_requests": 0,
            "writes_trades": False,
            "starts_workers": False,
            "automatic_execution": False,
        },
    }


def _artifact_query(
    *,
    provider: str | None,
    observed_wallet: str | None,
    transaction_signature: str | None,
):
    query = (
        select(NormalizationArtifact, RawBlockchainEvent)
        .join(RawBlockchainEvent, RawBlockchainEvent.id == NormalizationArtifact.raw_event_id)
        .outerjoin(
            CanonicalNormalizedEvent,
            CanonicalNormalizedEvent.normalization_artifact_id
            == NormalizationArtifact.id,
        )
        .where(
            NormalizationArtifact.parser_name == CANONICAL_PARSER_NAME,
            NormalizationArtifact.parser_version == CANONICAL_PARSER_VERSION,
            NormalizationArtifact.artifact_type == CANONICAL_ARTIFACT_TYPE,
            CanonicalNormalizedEvent.id.is_(None),
        )
    )
    if provider:
        query = query.where(RawBlockchainEvent.provider == provider.strip().lower())
    if observed_wallet:
        query = query.where(
            RawBlockchainEvent.observed_wallet == observed_wallet.strip()
        )
    if transaction_signature:
        query = query.where(
            RawBlockchainEvent.transaction_signature == transaction_signature.strip()
        )
    return query.order_by(NormalizationArtifact.id.asc())


def preview_canonical_materialization(
    db: Session,
    *,
    provider: str | None = None,
    observed_wallet: str | None = None,
    transaction_signature: str | None = None,
    limit: int = 100,
    settings_object: Any = settings,
) -> dict[str, Any]:
    effective_limit = _effective_limit(
        limit,
        int(getattr(settings_object, "CANONICAL_NORMALIZATION_MAX_BATCH_SIZE", 100)),
    )
    rows = db.execute(
        _artifact_query(
            provider=provider,
            observed_wallet=observed_wallet,
            transaction_signature=transaction_signature,
        ).limit(effective_limit)
    ).all()
    return {
        "dry_run": True,
        "canonical_normalization_enabled": bool(
            getattr(settings_object, "CANONICAL_NORMALIZATION_ENABLED", False)
        ),
        "requested_limit": int(limit),
        "effective_limit": effective_limit,
        "selected_count": len(rows),
        "artifact_ids": [artifact.id for artifact, _ in rows],
        "writes_database": False,
        "writes_trades": False,
        "external_requests": 0,
    }


def _canonical_event_from_artifact(
    artifact: NormalizationArtifact,
) -> CanonicalNormalizedEvent:
    payload = artifact.payload
    if not isinstance(payload, dict):
        raise CanonicalShadowError(
            "Payload artifact canonico non valido.",
            code="CANONICAL_ARTIFACT_PAYLOAD_INVALID",
        )
    canonical_payload_hash = calculate_payload_hash(payload)
    if canonical_payload_hash != artifact.payload_hash:
        raise CanonicalShadowError(
            "Hash artifact canonico non coerente.",
            code="CANONICAL_ARTIFACT_HASH_MISMATCH",
            status_code=409,
        )
    event_key = calculate_payload_hash(
        {
            "normalization_artifact_id": artifact.id,
            "raw_event_id": artifact.raw_event_id,
            "parser_name": artifact.parser_name,
            "parser_version": artifact.parser_version,
            "artifact_index": artifact.artifact_index,
            "payload_hash": artifact.payload_hash,
        }
    )
    side = str(payload.get("side") or "UNKNOWN").strip().upper()
    if side not in {"BUY", "SELL", "UNKNOWN"}:
        side = "UNKNOWN"
    quality_status = str(payload.get("quality_status") or "FAIL").strip().upper()
    if quality_status not in {"PASS", "WARN", "FAIL"}:
        quality_status = "FAIL"
    fee_value = payload.get("fee_lamports")
    try:
        fee_lamports = int(fee_value) if fee_value is not None else None
    except (TypeError, ValueError):
        fee_lamports = None
    return CanonicalNormalizedEvent(
        canonical_event_id=str(uuid4()),
        canonical_event_key=event_key,
        normalization_artifact_id=artifact.id,
        normalization_run_id=artifact.normalization_run_id,
        raw_event_id=artifact.raw_event_id,
        parser_name=artifact.parser_name,
        parser_version=artifact.parser_version,
        parser_implementation_hash=artifact.parser_implementation_hash,
        schema_version=artifact.schema_version,
        canonical_type=str(payload.get("canonical_type") or "SWAP").strip().upper(),
        transaction_signature=(
            str(payload.get("signature") or "").strip() or None
        ),
        observed_wallet=(
            str(payload.get("wallet_address") or "").strip() or None
        ),
        side=side,
        source=str(payload.get("source") or "").strip() or None,
        token_mint=str(payload.get("token_mint") or "").strip() or None,
        token_amount=_decimal(payload.get("token_amount")),
        sol_amount=_decimal(payload.get("sol_amount")),
        fee_lamports=fee_lamports,
        success=bool(payload.get("success", False)),
        block_time=_parse_datetime(payload.get("block_time")),
        quality_status=quality_status,
        quality_flags=list(payload.get("quality_flags") or []),
        canonical_payload=payload,
        canonical_payload_hash=canonical_payload_hash,
        technical_metadata=sanitize_technical_metadata(
            {
                "source_artifact_id": artifact.id,
                "artifact_metadata": artifact.artifact_metadata,
                "external_requests": 0,
                "writes_trades": False,
            }
        ),
    )


def execute_canonical_materialization(
    db: Session,
    *,
    confirmation: str,
    provider: str | None = None,
    observed_wallet: str | None = None,
    transaction_signature: str | None = None,
    limit: int = 100,
    settings_object: Any = settings,
) -> dict[str, Any]:
    if not bool(
        getattr(settings_object, "CANONICAL_NORMALIZATION_ENABLED", False)
    ):
        raise CanonicalShadowError(
            "Materializzazione canonica disabilitata.",
            code="CANONICAL_NORMALIZATION_DISABLED",
            status_code=409,
        )
    if str(confirmation or "").strip() != CANONICAL_MATERIALIZE_CONFIRMATION:
        raise CanonicalShadowError(
            "Conferma materializzazione canonica non valida.",
            code="CANONICAL_MATERIALIZE_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    effective_limit = _effective_limit(
        limit,
        int(getattr(settings_object, "CANONICAL_NORMALIZATION_MAX_BATCH_SIZE", 100)),
    )
    rows = db.execute(
        _artifact_query(
            provider=provider,
            observed_wallet=observed_wallet,
            transaction_signature=transaction_signature,
        ).limit(effective_limit)
    ).all()
    created = 0
    skipped = 0
    failed = 0
    errors: list[str] = []
    for artifact, _ in rows:
        try:
            with db.begin_nested():
                db.add(_canonical_event_from_artifact(artifact))
                db.flush()
            created += 1
        except IntegrityError:
            skipped += 1
        except Exception as exception:
            failed += 1
            errors.append(sanitize_error_message(exception))
    db.commit()
    return {
        "selected_count": len(rows),
        "created_count": created,
        "skipped_count": skipped,
        "failed_count": failed,
        "errors": errors[:20],
        "writes_trades": False,
        "external_requests": 0,
    }


def _canonical_query(
    *,
    transaction_signature: str | None,
    observed_wallet: str | None,
    quality_status: str | None,
):
    query = select(CanonicalNormalizedEvent)
    if transaction_signature:
        query = query.where(
            CanonicalNormalizedEvent.transaction_signature
            == transaction_signature.strip()
        )
    if observed_wallet:
        query = query.where(
            CanonicalNormalizedEvent.observed_wallet == observed_wallet.strip()
        )
    if quality_status:
        normalized_quality = quality_status.strip().upper()
        if normalized_quality not in {"PASS", "WARN", "FAIL"}:
            raise CanonicalShadowError(
                "Quality status non valido.",
                code="CANONICAL_QUALITY_STATUS_INVALID",
            )
        query = query.where(
            CanonicalNormalizedEvent.quality_status == normalized_quality
        )
    return query.order_by(CanonicalNormalizedEvent.id.asc())


def preview_shadow_validation(
    db: Session,
    *,
    transaction_signature: str | None = None,
    observed_wallet: str | None = None,
    quality_status: str | None = None,
    limit: int = 200,
    settings_object: Any = settings,
) -> dict[str, Any]:
    effective_limit = _effective_limit(
        limit,
        int(
            getattr(
                settings_object,
                "CANONICAL_SHADOW_VALIDATION_MAX_BATCH_SIZE",
                200,
            )
        ),
    )
    rows = db.scalars(
        _canonical_query(
            transaction_signature=transaction_signature,
            observed_wallet=observed_wallet,
            quality_status=quality_status,
        ).limit(effective_limit)
    ).all()
    return {
        "dry_run": True,
        "shadow_validation_enabled": bool(
            getattr(settings_object, "CANONICAL_SHADOW_VALIDATION_ENABLED", False)
        ),
        "requested_limit": int(limit),
        "effective_limit": effective_limit,
        "selected_count": len(rows),
        "canonical_event_ids": [row.canonical_event_id for row in rows],
        "writes_database": False,
        "writes_trades": False,
        "external_requests": 0,
    }


def _canonical_snapshot(event: CanonicalNormalizedEvent) -> dict[str, Any]:
    return {
        "signature": event.transaction_signature,
        "wallet_address": event.observed_wallet,
        "side": event.side,
        "source": event.source,
        "token_mint": event.token_mint,
        "token_amount": _decimal_string(event.token_amount),
        "sol_amount": _decimal_string(event.sol_amount),
        "fee_lamports": event.fee_lamports,
        "success": bool(event.success),
        "block_time": _aware_iso(event.block_time),
        "quality_status": event.quality_status,
    }


def _trade_snapshot(trade: Trade) -> dict[str, Any]:
    return {
        "signature": trade.signature,
        "wallet_address": trade.wallet_address,
        "side": str(trade.side or "UNKNOWN").upper(),
        "source": trade.source,
        "token_mint": trade.token_mint,
        "token_amount": _decimal_string(trade.token_amount),
        "sol_amount": _decimal_string(trade.sol_amount),
        "fee_lamports": trade.fee,
        "success": bool(trade.success),
        "block_time": _aware_iso(trade.block_time),
    }


def _amount_equal(left: object, right: object, tolerance: Decimal) -> bool:
    left_value = _decimal(left)
    right_value = _decimal(right)
    if left_value is None or right_value is None:
        return left_value is None and right_value is None
    return abs(left_value - right_value) <= tolerance


def _compare_event_to_trade(
    event: CanonicalNormalizedEvent,
    trade: Trade | None,
    *,
    amount_tolerance: Decimal,
) -> tuple[str, list[str], dict[str, Any], dict[str, Any] | None]:
    canonical = _canonical_snapshot(event)
    if (
        event.quality_status == "FAIL"
        or not event.transaction_signature
        or event.side == "UNKNOWN"
    ):
        return "NOT_COMPARABLE", [], canonical, None
    if trade is None:
        return "MISSING_TRADE", [], canonical, None
    trade_data = _trade_snapshot(trade)
    mismatches: list[str] = []
    for field in (
        "signature",
        "wallet_address",
        "side",
        "source",
        "token_mint",
        "success",
        "block_time",
    ):
        if canonical.get(field) != trade_data.get(field):
            mismatches.append(field)
    if not _amount_equal(
        canonical.get("token_amount"),
        trade_data.get("token_amount"),
        amount_tolerance,
    ):
        mismatches.append("token_amount")
    if not _amount_equal(
        canonical.get("sol_amount"),
        trade_data.get("sol_amount"),
        amount_tolerance,
    ):
        mismatches.append("sol_amount")
    if not _amount_equal(
        canonical.get("fee_lamports"),
        trade_data.get("fee_lamports"),
        amount_tolerance,
    ):
        mismatches.append("fee_lamports")
    return (
        "MISMATCH" if mismatches else "MATCH",
        mismatches,
        canonical,
        trade_data,
    )


def execute_shadow_validation(
    db: Session,
    *,
    confirmation: str,
    transaction_signature: str | None = None,
    observed_wallet: str | None = None,
    quality_status: str | None = None,
    limit: int = 200,
    settings_object: Any = settings,
) -> dict[str, Any]:
    if not bool(
        getattr(settings_object, "CANONICAL_SHADOW_VALIDATION_ENABLED", False)
    ):
        raise CanonicalShadowError(
            "Shadow validation disabilitata.",
            code="CANONICAL_SHADOW_VALIDATION_DISABLED",
            status_code=409,
        )
    if str(confirmation or "").strip() != SHADOW_VALIDATION_CONFIRMATION:
        raise CanonicalShadowError(
            "Conferma shadow validation non valida.",
            code="SHADOW_VALIDATION_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    effective_limit = _effective_limit(
        limit,
        int(
            getattr(
                settings_object,
                "CANONICAL_SHADOW_VALIDATION_MAX_BATCH_SIZE",
                200,
            )
        ),
    )
    events = db.scalars(
        _canonical_query(
            transaction_signature=transaction_signature,
            observed_wallet=observed_wallet,
            quality_status=quality_status,
        ).limit(effective_limit)
    ).all()
    now = _utc_now()
    batch = CanonicalShadowValidationBatch(
        validation_id=str(uuid4()),
        comparator_version=SHADOW_COMPARATOR_VERSION,
        status="RUNNING",
        request_filters=sanitize_technical_metadata(
            {
                "transaction_signature": transaction_signature,
                "observed_wallet": observed_wallet,
                "quality_status": quality_status,
            }
        ),
        requested_limit=effective_limit,
        selected_count=len(events),
        processed_count=0,
        match_count=0,
        mismatch_count=0,
        missing_trade_count=0,
        not_comparable_count=0,
        failed_count=0,
        started_at=now,
        technical_metadata={
            "amount_tolerance": str(
                getattr(settings_object, "CANONICAL_SHADOW_AMOUNT_TOLERANCE", 1e-9)
            ),
            "external_requests": 0,
            "writes_trades": False,
        },
    )
    db.add(batch)
    db.flush()
    tolerance = Decimal(
        str(getattr(settings_object, "CANONICAL_SHADOW_AMOUNT_TOLERANCE", 1e-9))
    )
    for event in events:
        try:
            trade = None
            if event.transaction_signature:
                trade = db.scalar(
                    select(Trade).where(
                        Trade.signature == event.transaction_signature
                    )
                )
            status, mismatches, canonical, trade_data = _compare_event_to_trade(
                event,
                trade,
                amount_tolerance=tolerance,
            )
            db.add(
                CanonicalShadowValidationResult(
                    validation_batch_id=batch.id,
                    canonical_event_id=event.id,
                    trade_id=trade.id if trade is not None else None,
                    transaction_signature=event.transaction_signature,
                    comparator_version=SHADOW_COMPARATOR_VERSION,
                    status=status,
                    mismatch_fields=mismatches,
                    canonical_snapshot=canonical,
                    trade_snapshot=trade_data,
                    canonical_snapshot_hash=calculate_payload_hash(canonical),
                    trade_snapshot_hash=(
                        calculate_payload_hash(trade_data)
                        if trade_data is not None
                        else None
                    ),
                    technical_metadata={
                        "amount_tolerance": str(tolerance),
                        "external_requests": 0,
                        "writes_trades": False,
                    },
                )
            )
            batch.processed_count += 1
            if status == "MATCH":
                batch.match_count += 1
            elif status == "MISMATCH":
                batch.mismatch_count += 1
            elif status == "MISSING_TRADE":
                batch.missing_trade_count += 1
            else:
                batch.not_comparable_count += 1
        except Exception:
            batch.processed_count += 1
            batch.failed_count += 1
    batch.completed_at = _utc_now()
    batch.updated_at = batch.completed_at
    if batch.failed_count == 0:
        batch.status = "COMPLETED"
    elif batch.processed_count > batch.failed_count:
        batch.status = "PARTIAL"
    else:
        batch.status = "FAILED"
        batch.error_message = sanitize_error_message(
            "Tutti i confronti shadow selezionati hanno fallito."
        )
    db.commit()
    db.refresh(batch)
    return serialize_shadow_validation_batch(batch)


def serialize_shadow_validation_batch(
    batch: CanonicalShadowValidationBatch,
) -> dict[str, Any]:
    return {
        "validation_id": batch.validation_id,
        "comparator_version": batch.comparator_version,
        "status": batch.status,
        "request_filters": batch.request_filters,
        "requested_limit": batch.requested_limit,
        "selected_count": batch.selected_count,
        "processed_count": batch.processed_count,
        "match_count": batch.match_count,
        "mismatch_count": batch.mismatch_count,
        "missing_trade_count": batch.missing_trade_count,
        "not_comparable_count": batch.not_comparable_count,
        "failed_count": batch.failed_count,
        "started_at": batch.started_at,
        "completed_at": batch.completed_at,
        "error_message": batch.error_message,
        "technical_metadata": batch.technical_metadata,
    }


def get_shadow_validation_batch(
    db: Session,
    validation_id: str,
) -> dict[str, Any]:
    batch = db.scalar(
        select(CanonicalShadowValidationBatch).where(
            CanonicalShadowValidationBatch.validation_id
            == str(validation_id or "").strip()
        )
    )
    if batch is None:
        raise CanonicalShadowError(
            "Batch shadow validation non trovato.",
            code="SHADOW_VALIDATION_BATCH_NOT_FOUND",
            status_code=404,
        )
    result_counts: dict[str, int] = {
        "MATCH": 0,
        "MISMATCH": 0,
        "MISSING_TRADE": 0,
        "NOT_COMPARABLE": 0,
    }
    results = db.scalars(
        select(CanonicalShadowValidationResult)
        .where(CanonicalShadowValidationResult.validation_batch_id == batch.id)
        .order_by(CanonicalShadowValidationResult.id.asc())
        .limit(100)
    ).all()
    for result in results:
        result_counts[result.status] = result_counts.get(result.status, 0) + 1
    return {
        **serialize_shadow_validation_batch(batch),
        "result_counts": result_counts,
        "results": [
            {
                "status": result.status,
                "transaction_signature": result.transaction_signature,
                "mismatch_fields": result.mismatch_fields,
                "canonical_snapshot_hash": result.canonical_snapshot_hash,
                "trade_snapshot_hash": result.trade_snapshot_hash,
            }
            for result in results
        ],
    }
