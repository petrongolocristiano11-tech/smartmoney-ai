from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalNormalizedEvent,
    CanonicalQualityAssessment,
    CanonicalShadowValidationBatch,
    CanonicalShadowValidationResult,
)
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
)


QUALITY_GATE_POLICY_VERSION = "canonical-quality-gate/1"
QUALITY_GATE_CONFIRMATION = "ASSESS_CANONICAL_QUALITY"
_RATE_QUANTUM = Decimal("0.0001")


class CanonicalQualityGateError(ValueError):
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


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    aware = _aware(value)
    return aware.isoformat() if aware is not None else None


def _rate(numerator: int, denominator: int) -> Decimal:
    if denominator <= 0:
        return Decimal("0.0000")
    return (
        Decimal(int(numerator))
        * Decimal("100")
        / Decimal(int(denominator))
    ).quantize(_RATE_QUANTUM, rounding=ROUND_HALF_UP)


def _float_rate(value: Decimal) -> float:
    return float(value.quantize(_RATE_QUANTUM, rounding=ROUND_HALF_UP))


def _threshold_snapshot(settings_object: Any) -> dict[str, Any]:
    return {
        "policy_version": QUALITY_GATE_POLICY_VERSION,
        "minimum_comparable_events": int(
            getattr(
                settings_object,
                "CANONICAL_QUALITY_GATE_MIN_COMPARABLE_EVENTS",
                50,
            )
        ),
        "minimum_match_rate": float(
            getattr(
                settings_object,
                "CANONICAL_QUALITY_GATE_MIN_MATCH_RATE",
                98.0,
            )
        ),
        "maximum_mismatch_rate": float(
            getattr(
                settings_object,
                "CANONICAL_QUALITY_GATE_MAX_MISMATCH_RATE",
                2.0,
            )
        ),
        "maximum_missing_trade_rate": float(
            getattr(
                settings_object,
                "CANONICAL_QUALITY_GATE_MAX_MISSING_TRADE_RATE",
                10.0,
            )
        ),
        "maximum_not_comparable_rate": float(
            getattr(
                settings_object,
                "CANONICAL_QUALITY_GATE_MAX_NOT_COMPARABLE_RATE",
                5.0,
            )
        ),
        "maximum_failed_rate": float(
            getattr(
                settings_object,
                "CANONICAL_QUALITY_GATE_MAX_FAILED_RATE",
                0.5,
            )
        ),
        "minimum_pass_quality_rate": float(
            getattr(
                settings_object,
                "CANONICAL_QUALITY_GATE_MIN_PASS_QUALITY_RATE",
                95.0,
            )
        ),
        "maximum_evidence_age_hours": int(
            getattr(
                settings_object,
                "CANONICAL_QUALITY_GATE_MAX_EVIDENCE_AGE_HOURS",
                168,
            )
        ),
    }


def _get_validation_batch(
    db: Session,
    validation_id: str | None,
) -> CanonicalShadowValidationBatch:
    query = select(CanonicalShadowValidationBatch)
    if validation_id:
        query = query.where(
            CanonicalShadowValidationBatch.validation_id
            == str(validation_id).strip()
        )
    else:
        query = query.order_by(CanonicalShadowValidationBatch.id.desc()).limit(1)
    batch = db.scalar(query)
    if batch is None:
        raise CanonicalQualityGateError(
            "Batch shadow validation non trovato.",
            code="QUALITY_GATE_VALIDATION_BATCH_NOT_FOUND",
            status_code=404,
        )
    return batch


def _load_evidence_rows(
    db: Session,
    batch: CanonicalShadowValidationBatch,
) -> list[tuple[CanonicalShadowValidationResult, CanonicalNormalizedEvent]]:
    return list(
        db.execute(
            select(
                CanonicalShadowValidationResult,
                CanonicalNormalizedEvent,
            )
            .join(
                CanonicalNormalizedEvent,
                CanonicalNormalizedEvent.id
                == CanonicalShadowValidationResult.canonical_event_id,
            )
            .where(
                CanonicalShadowValidationResult.validation_batch_id == batch.id
            )
            .order_by(CanonicalShadowValidationResult.id.asc())
        ).all()
    )


def _evidence_snapshot(
    batch: CanonicalShadowValidationBatch,
    rows: list[tuple[CanonicalShadowValidationResult, CanonicalNormalizedEvent]],
) -> dict[str, Any]:
    return {
        "validation_batch": {
            "id": batch.id,
            "validation_id": batch.validation_id,
            "comparator_version": batch.comparator_version,
            "status": batch.status,
            "selected_count": batch.selected_count,
            "processed_count": batch.processed_count,
            "match_count": batch.match_count,
            "mismatch_count": batch.mismatch_count,
            "missing_trade_count": batch.missing_trade_count,
            "not_comparable_count": batch.not_comparable_count,
            "failed_count": batch.failed_count,
            "started_at": _iso(batch.started_at),
            "completed_at": _iso(batch.completed_at),
        },
        "results": [
            {
                "result_id": result.id,
                "canonical_event_id": event.id,
                "transaction_signature": result.transaction_signature,
                "status": result.status,
                "mismatch_fields": sorted(
                    str(field) for field in (result.mismatch_fields or [])
                ),
                "canonical_snapshot_hash": result.canonical_snapshot_hash,
                "trade_snapshot_hash": result.trade_snapshot_hash,
                "comparator_version": result.comparator_version,
                "parser_name": event.parser_name,
                "parser_version": event.parser_version,
                "parser_implementation_hash": event.parser_implementation_hash,
                "canonical_payload_hash": event.canonical_payload_hash,
                "quality_status": event.quality_status,
            }
            for result, event in rows
        ],
    }


def _evaluate(
    db: Session,
    *,
    validation_id: str | None,
    settings_object: Any,
    evaluated_at: datetime,
) -> dict[str, Any]:
    batch = _get_validation_batch(db, validation_id)
    rows = _load_evidence_rows(db, batch)
    thresholds = _threshold_snapshot(settings_object)
    policy_hash = calculate_payload_hash(thresholds)

    integrity_reasons: set[str] = set()
    review_reasons: set[str] = set()
    blocking_reasons: set[str] = set()

    status_counts = Counter(result.status for result, _ in rows)
    quality_counts = Counter(event.quality_status for _, event in rows)
    mismatch_fields: Counter[str] = Counter()
    parser_identities: set[tuple[str, str, str]] = set()

    for result, event in rows:
        parser_identities.add(
            (
                event.parser_name,
                event.parser_version,
                event.parser_implementation_hash,
            )
        )
        mismatch_fields.update(
            str(field) for field in (result.mismatch_fields or [])
        )

        if calculate_payload_hash(result.canonical_snapshot) != (
            result.canonical_snapshot_hash
        ):
            integrity_reasons.add("CANONICAL_SNAPSHOT_HASH_MISMATCH")

        if result.trade_snapshot is None:
            if result.trade_snapshot_hash is not None:
                integrity_reasons.add("TRADE_SNAPSHOT_HASH_UNEXPECTED")
        elif calculate_payload_hash(result.trade_snapshot) != (
            result.trade_snapshot_hash
        ):
            integrity_reasons.add("TRADE_SNAPSHOT_HASH_MISMATCH")

        if calculate_payload_hash(event.canonical_payload) != (
            event.canonical_payload_hash
        ):
            integrity_reasons.add("CANONICAL_PAYLOAD_HASH_MISMATCH")

        if result.comparator_version != batch.comparator_version:
            integrity_reasons.add("COMPARATOR_VERSION_MISMATCH")

        if result.transaction_signature != event.transaction_signature:
            integrity_reasons.add("TRANSACTION_SIGNATURE_MISMATCH")

    if len(parser_identities) > 1:
        integrity_reasons.add("MIXED_PARSER_IDENTITY")

    result_count = len(rows)
    computed_match = int(status_counts.get("MATCH", 0))
    computed_mismatch = int(status_counts.get("MISMATCH", 0))
    computed_missing = int(status_counts.get("MISSING_TRADE", 0))
    computed_not_comparable = int(status_counts.get("NOT_COMPARABLE", 0))

    if result_count + int(batch.failed_count) != int(batch.processed_count):
        integrity_reasons.add("PROCESSED_COUNT_RECONCILIATION_FAILED")

    expected_counts = {
        "MATCH": int(batch.match_count),
        "MISMATCH": int(batch.mismatch_count),
        "MISSING_TRADE": int(batch.missing_trade_count),
        "NOT_COMPARABLE": int(batch.not_comparable_count),
    }
    computed_counts = {
        "MATCH": computed_match,
        "MISMATCH": computed_mismatch,
        "MISSING_TRADE": computed_missing,
        "NOT_COMPARABLE": computed_not_comparable,
    }
    if expected_counts != computed_counts:
        integrity_reasons.add("STATUS_COUNT_RECONCILIATION_FAILED")

    if int(batch.selected_count) < int(batch.processed_count):
        integrity_reasons.add("SELECTED_COUNT_RECONCILIATION_FAILED")

    if batch.status == "FAILED":
        blocking_reasons.add("VALIDATION_BATCH_FAILED")
    elif batch.status == "RUNNING":
        blocking_reasons.add("VALIDATION_BATCH_RUNNING")
    elif batch.status == "PARTIAL":
        review_reasons.add("VALIDATION_BATCH_PARTIAL")
    elif batch.status != "COMPLETED":
        integrity_reasons.add("VALIDATION_BATCH_STATUS_INVALID")

    completed_at = _aware(batch.completed_at)
    evaluation_time = _aware(evaluated_at) or _utc_now()
    evidence_age_hours: float | None = None
    if completed_at is not None:
        age_seconds = (evaluation_time - completed_at).total_seconds()
        if age_seconds < -1:
            integrity_reasons.add("EVIDENCE_TIMESTAMP_IN_FUTURE")
        else:
            evidence_age_hours = round(age_seconds / 3600.0, 4)
            if evidence_age_hours > thresholds["maximum_evidence_age_hours"]:
                review_reasons.add("EVIDENCE_STALE")
    else:
        review_reasons.add("EVIDENCE_COMPLETION_TIMESTAMP_MISSING")

    sample_size = result_count
    comparable_count = computed_match + computed_mismatch
    match_rate = _rate(computed_match, comparable_count)
    mismatch_rate = _rate(computed_mismatch, comparable_count)
    missing_trade_rate = _rate(computed_missing, sample_size)
    not_comparable_rate = _rate(computed_not_comparable, sample_size)
    failed_rate = _rate(int(batch.failed_count), int(batch.processed_count))
    quality_pass_count = int(quality_counts.get("PASS", 0))
    quality_warn_count = int(quality_counts.get("WARN", 0))
    quality_fail_count = int(quality_counts.get("FAIL", 0))
    quality_pass_rate = _rate(quality_pass_count, sample_size)

    insufficient = (
        comparable_count < thresholds["minimum_comparable_events"]
    )
    if insufficient:
        review_reasons.add("COMPARABLE_SAMPLE_BELOW_MINIMUM")
    else:
        if float(match_rate) < thresholds["minimum_match_rate"]:
            blocking_reasons.add("MATCH_RATE_BELOW_MINIMUM")
        if float(mismatch_rate) > thresholds["maximum_mismatch_rate"]:
            blocking_reasons.add("MISMATCH_RATE_ABOVE_MAXIMUM")
        if (
            float(missing_trade_rate)
            > thresholds["maximum_missing_trade_rate"]
        ):
            blocking_reasons.add("MISSING_TRADE_RATE_ABOVE_MAXIMUM")
        if float(failed_rate) > thresholds["maximum_failed_rate"]:
            blocking_reasons.add("FAILED_RATE_ABOVE_MAXIMUM")
        if (
            float(quality_pass_rate)
            < thresholds["minimum_pass_quality_rate"]
        ):
            blocking_reasons.add("QUALITY_PASS_RATE_BELOW_MINIMUM")
        if (
            float(not_comparable_rate)
            > thresholds["maximum_not_comparable_rate"]
        ):
            review_reasons.add("NOT_COMPARABLE_RATE_ABOVE_MAXIMUM")

    if integrity_reasons or blocking_reasons:
        decision = "BLOCKED"
    elif insufficient:
        decision = "INSUFFICIENT_DATA"
    elif review_reasons:
        decision = "REVIEW"
    else:
        decision = "READY"

    parser_name = "unknown"
    parser_version = "unknown"
    parser_implementation_hash = "0" * 64
    if len(parser_identities) == 1:
        (
            parser_name,
            parser_version,
            parser_implementation_hash,
        ) = next(iter(parser_identities))

    evidence_snapshot = _evidence_snapshot(batch, rows)
    evidence_hash = calculate_payload_hash(evidence_snapshot)
    assessment_key = calculate_payload_hash(
        {
            "validation_id": batch.validation_id,
            "policy_hash": policy_hash,
            "evidence_hash": evidence_hash,
        }
    )

    metrics = {
        "sample_size": sample_size,
        "comparable_count": comparable_count,
        "match_count": computed_match,
        "mismatch_count": computed_mismatch,
        "missing_trade_count": computed_missing,
        "not_comparable_count": computed_not_comparable,
        "failed_count": int(batch.failed_count),
        "quality_pass_count": quality_pass_count,
        "quality_warn_count": quality_warn_count,
        "quality_fail_count": quality_fail_count,
        "match_rate": _float_rate(match_rate),
        "mismatch_rate": _float_rate(mismatch_rate),
        "missing_trade_rate": _float_rate(missing_trade_rate),
        "not_comparable_rate": _float_rate(not_comparable_rate),
        "failed_rate": _float_rate(failed_rate),
        "quality_pass_rate": _float_rate(quality_pass_rate),
        "evidence_age_hours": evidence_age_hours,
        "mismatch_field_counts": dict(sorted(mismatch_fields.items())),
    }

    reasons = sorted(
        integrity_reasons | blocking_reasons | review_reasons
    )
    return {
        "dry_run": True,
        "quality_gate_enabled": bool(
            getattr(settings_object, "CANONICAL_QUALITY_GATE_ENABLED", False)
        ),
        "decision": decision,
        "reason_codes": reasons,
        "validation_id": batch.validation_id,
        "validation_batch_id": batch.id,
        "validation_status": batch.status,
        "parser_name": parser_name,
        "parser_version": parser_version,
        "parser_implementation_hash": parser_implementation_hash,
        "comparator_version": batch.comparator_version,
        "policy_version": QUALITY_GATE_POLICY_VERSION,
        "policy_hash": policy_hash,
        "evidence_hash": evidence_hash,
        "assessment_key": assessment_key,
        "thresholds": thresholds,
        "metrics": metrics,
        "evidence_completed_at": completed_at,
        "evaluated_at": evaluation_time,
        "operational_guards": {
            "external_requests": 0,
            "writes_trades": False,
            "starts_workers": False,
            "changes_runtime_flags": False,
            "promotes_pipeline": False,
        },
    }


def preview_canonical_quality_gate(
    db: Session,
    *,
    validation_id: str | None = None,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    return _evaluate(
        db,
        validation_id=validation_id,
        settings_object=settings_object,
        evaluated_at=evaluated_at or _utc_now(),
    )


def _serialize_assessment(
    assessment: CanonicalQualityAssessment,
    *,
    created: bool | None = None,
) -> dict[str, Any]:
    payload = {
        "assessment_id": assessment.assessment_id,
        "assessment_key": assessment.assessment_key,
        "validation_id": assessment.validation_id,
        "status": assessment.status,
        "reason_codes": assessment.reason_codes,
        "policy_version": assessment.policy_version,
        "policy_hash": assessment.policy_hash,
        "evidence_hash": assessment.evidence_hash,
        "parser_name": assessment.parser_name,
        "parser_version": assessment.parser_version,
        "parser_implementation_hash": assessment.parser_implementation_hash,
        "comparator_version": assessment.comparator_version,
        "thresholds": assessment.threshold_snapshot,
        "metrics": assessment.metrics_snapshot,
        "mismatch_field_counts": assessment.mismatch_field_counts,
        "evidence_completed_at": assessment.evidence_completed_at,
        "evaluated_at": assessment.evaluated_at,
        "technical_metadata": assessment.technical_metadata,
    }
    if created is not None:
        payload["created"] = created
    return payload


def execute_canonical_quality_assessment(
    db: Session,
    *,
    confirmation: str,
    validation_id: str | None = None,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(
        getattr(settings_object, "CANONICAL_QUALITY_GATE_ENABLED", False)
    ):
        raise CanonicalQualityGateError(
            "Canonical quality gate disabilitato.",
            code="CANONICAL_QUALITY_GATE_DISABLED",
            status_code=409,
        )
    if str(confirmation or "").strip() != QUALITY_GATE_CONFIRMATION:
        raise CanonicalQualityGateError(
            "Conferma quality assessment non valida.",
            code="CANONICAL_QUALITY_GATE_CONFIRMATION_REQUIRED",
            status_code=409,
        )

    evaluation = _evaluate(
        db,
        validation_id=validation_id,
        settings_object=settings_object,
        evaluated_at=evaluated_at or _utc_now(),
    )
    existing = db.scalar(
        select(CanonicalQualityAssessment).where(
            CanonicalQualityAssessment.assessment_key
            == evaluation["assessment_key"]
        )
    )
    if existing is not None:
        return _serialize_assessment(existing, created=False)

    metrics = evaluation["metrics"]
    assessment = CanonicalQualityAssessment(
        assessment_id=str(uuid4()),
        assessment_key=evaluation["assessment_key"],
        validation_batch_id=evaluation["validation_batch_id"],
        validation_id=evaluation["validation_id"],
        policy_version=evaluation["policy_version"],
        policy_hash=evaluation["policy_hash"],
        evidence_hash=evaluation["evidence_hash"],
        status=evaluation["decision"],
        parser_name=evaluation["parser_name"],
        parser_version=evaluation["parser_version"],
        parser_implementation_hash=evaluation[
            "parser_implementation_hash"
        ],
        comparator_version=evaluation["comparator_version"],
        sample_size=metrics["sample_size"],
        comparable_count=metrics["comparable_count"],
        match_count=metrics["match_count"],
        mismatch_count=metrics["mismatch_count"],
        missing_trade_count=metrics["missing_trade_count"],
        not_comparable_count=metrics["not_comparable_count"],
        failed_count=metrics["failed_count"],
        quality_pass_count=metrics["quality_pass_count"],
        quality_warn_count=metrics["quality_warn_count"],
        quality_fail_count=metrics["quality_fail_count"],
        match_rate=Decimal(str(metrics["match_rate"])),
        mismatch_rate=Decimal(str(metrics["mismatch_rate"])),
        missing_trade_rate=Decimal(str(metrics["missing_trade_rate"])),
        not_comparable_rate=Decimal(
            str(metrics["not_comparable_rate"])
        ),
        failed_rate=Decimal(str(metrics["failed_rate"])),
        quality_pass_rate=Decimal(str(metrics["quality_pass_rate"])),
        reason_codes=evaluation["reason_codes"],
        mismatch_field_counts=metrics["mismatch_field_counts"],
        threshold_snapshot=evaluation["thresholds"],
        metrics_snapshot=metrics,
        technical_metadata={
            **evaluation["operational_guards"],
            "source_validation_status": evaluation["validation_status"],
        },
        evidence_completed_at=evaluation["evidence_completed_at"],
        evaluated_at=evaluation["evaluated_at"],
    )

    try:
        with db.begin_nested():
            db.add(assessment)
            db.flush()
    except IntegrityError:
        existing = db.scalar(
            select(CanonicalQualityAssessment).where(
                CanonicalQualityAssessment.assessment_key
                == evaluation["assessment_key"]
            )
        )
        if existing is None:
            raise
        db.commit()
        return _serialize_assessment(existing, created=False)

    db.commit()
    db.refresh(assessment)
    return _serialize_assessment(assessment, created=True)


def get_canonical_quality_assessment(
    db: Session,
    assessment_id: str,
) -> dict[str, Any]:
    assessment = db.scalar(
        select(CanonicalQualityAssessment).where(
            CanonicalQualityAssessment.assessment_id
            == str(assessment_id or "").strip()
        )
    )
    if assessment is None:
        raise CanonicalQualityGateError(
            "Canonical quality assessment non trovato.",
            code="CANONICAL_QUALITY_ASSESSMENT_NOT_FOUND",
            status_code=404,
        )
    return _serialize_assessment(assessment)


def get_canonical_quality_gate_status(
    db: Session,
    *,
    settings_object: Any = settings,
) -> dict[str, Any]:
    latest = db.scalar(
        select(CanonicalQualityAssessment)
        .order_by(CanonicalQualityAssessment.id.desc())
        .limit(1)
    )
    thresholds = _threshold_snapshot(settings_object)
    return {
        "quality_gate_enabled": bool(
            getattr(settings_object, "CANONICAL_QUALITY_GATE_ENABLED", False)
        ),
        "policy_version": QUALITY_GATE_POLICY_VERSION,
        "policy_hash": calculate_payload_hash(thresholds),
        "thresholds": thresholds,
        "assessment_count": int(db.query(CanonicalQualityAssessment).count()),
        "latest_assessment": (
            _serialize_assessment(latest) if latest is not None else None
        ),
        "operational_guards": {
            "external_requests": 0,
            "writes_trades": False,
            "starts_workers": False,
            "changes_runtime_flags": False,
            "promotes_pipeline": False,
        },
    }
