from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserPromotion,
    CanonicalParserPromotionEvent,
    CanonicalQualityAssessment,
)
from backend.app.services.blockchain_canonical_quality_gate_service import (
    CanonicalQualityGateError,
    preview_canonical_quality_gate,
)
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    sanitize_error_message,
    sanitize_technical_metadata,
)
from backend.app.services.blockchain_parser_registry_service import (
    DEFAULT_PARSER_REGISTRY,
    ParserRegistry,
    ParserRegistryError,
)


PROMOTION_POLICY_VERSION = "canonical-parser-promotion/1"
PROMOTION_SCOPE = "SHADOW_ONLY"
APPROVAL_CONFIRMATION_PREFIX = "APPROVE_CANONICAL_PARSER"
REVOCATION_CONFIRMATION_PREFIX = "REVOKE_CANONICAL_PARSER"
_MAX_REASON_LENGTH = 500
_MAX_ACTOR_LABEL_LENGTH = 80


class CanonicalParserPromotionError(ValueError):
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


def _normalize_scope(scope: str | None) -> str:
    normalized = str(scope or PROMOTION_SCOPE).strip().upper()
    if normalized != PROMOTION_SCOPE:
        raise CanonicalParserPromotionError(
            "Scope promozione parser non supportato.",
            code="PARSER_PROMOTION_SCOPE_UNSUPPORTED",
            status_code=422,
        )
    return normalized


def _normalize_actor_label(value: str | None) -> str:
    normalized = sanitize_error_message(
        value or "LOCAL_OPERATOR",
        max_length=_MAX_ACTOR_LABEL_LENGTH,
    )
    return normalized or "LOCAL_OPERATOR"


def _normalize_optional_reason(value: str | None) -> str | None:
    if not str(value or "").strip():
        return None
    return sanitize_error_message(value, max_length=_MAX_REASON_LENGTH)


def _promotion_policy_snapshot(
    *,
    settings_object: Any,
    scope: str,
) -> dict[str, Any]:
    return {
        "policy_version": PROMOTION_POLICY_VERSION,
        "scope": scope,
        "required_assessment_status": "READY",
        "maximum_assessment_age_hours": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_PROMOTION_MAX_ASSESSMENT_AGE_HOURS",
                168,
            )
        ),
        "require_current_quality_policy": True,
        "require_current_registry_identity": True,
        "require_deterministic_parser": True,
        "external_requests_allowed": False,
        "trade_writes_allowed": False,
        "runtime_activation": False,
    }


def _get_assessment(
    db: Session,
    assessment_id: str | None,
) -> CanonicalQualityAssessment:
    query = select(CanonicalQualityAssessment)
    normalized = str(assessment_id or "").strip()
    if normalized:
        query = query.where(
            CanonicalQualityAssessment.assessment_id == normalized
        )
    else:
        query = (
            query.where(CanonicalQualityAssessment.status == "READY")
            .order_by(CanonicalQualityAssessment.id.desc())
            .limit(1)
        )
    assessment = db.scalar(query)
    if assessment is None:
        raise CanonicalParserPromotionError(
            "Canonical quality assessment READY non trovato.",
            code="PARSER_PROMOTION_ASSESSMENT_NOT_FOUND",
            status_code=404,
        )
    return assessment


def _get_promotion(
    db: Session,
    promotion_id: str,
    *,
    for_update: bool = False,
) -> CanonicalParserPromotion:
    query = select(CanonicalParserPromotion).where(
        CanonicalParserPromotion.promotion_id
        == str(promotion_id or "").strip()
    )
    if for_update:
        query = query.with_for_update()
    promotion = db.scalar(query)
    if promotion is None:
        raise CanonicalParserPromotionError(
            "Promozione parser non trovata.",
            code="PARSER_PROMOTION_NOT_FOUND",
            status_code=404,
        )
    return promotion


def _event_payload(
    *,
    event_id: str,
    promotion_id: str,
    sequence: int,
    event_type: str,
    previous_status: str | None,
    new_status: str,
    actor_label: str,
    reason: str | None,
    previous_event_hash: str | None,
    occurred_at: datetime,
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "promotion_id": promotion_id,
        "sequence": int(sequence),
        "event_type": event_type,
        "previous_status": previous_status,
        "new_status": new_status,
        "actor_label": actor_label,
        "reason": reason,
        "previous_event_hash": previous_event_hash,
        "occurred_at": _iso(occurred_at),
    }


def _audit_chain(
    db: Session,
    promotion: CanonicalParserPromotion,
) -> dict[str, Any]:
    events = list(
        db.scalars(
            select(CanonicalParserPromotionEvent)
            .where(
                CanonicalParserPromotionEvent.promotion_db_id == promotion.id
            )
            .order_by(CanonicalParserPromotionEvent.sequence.asc())
        )
    )
    reasons: list[str] = []
    previous_hash: str | None = None
    previous_status: str | None = None

    for expected_sequence, event in enumerate(events, start=1):
        expected_payload = _event_payload(
            event_id=event.event_id,
            promotion_id=promotion.promotion_id,
            sequence=event.sequence,
            event_type=event.event_type,
            previous_status=event.previous_status,
            new_status=event.new_status,
            actor_label=event.actor_label,
            reason=event.reason,
            previous_event_hash=event.previous_event_hash,
            occurred_at=event.occurred_at,
        )
        expected_hash = calculate_payload_hash(expected_payload)
        if event.sequence != expected_sequence:
            reasons.append("EVENT_SEQUENCE_GAP")
        if event.previous_event_hash != previous_hash:
            reasons.append("EVENT_PREVIOUS_HASH_MISMATCH")
        if event.previous_status != previous_status:
            reasons.append("EVENT_PREVIOUS_STATUS_MISMATCH")
        if calculate_payload_hash(event.event_payload) != expected_hash:
            reasons.append("EVENT_PAYLOAD_MISMATCH")
        if event.event_hash != expected_hash:
            reasons.append("EVENT_HASH_MISMATCH")
        previous_hash = event.event_hash
        previous_status = event.new_status

    if not events:
        reasons.append("EVENT_CHAIN_EMPTY")
    else:
        if promotion.latest_event_sequence != events[-1].sequence:
            reasons.append("LATEST_EVENT_SEQUENCE_MISMATCH")
        if promotion.latest_event_hash != events[-1].event_hash:
            reasons.append("LATEST_EVENT_HASH_MISMATCH")
        if promotion.status != events[-1].new_status:
            reasons.append("PROMOTION_STATUS_MISMATCH")

    return {
        "valid": not reasons,
        "reason_codes": sorted(set(reasons)),
        "event_count": len(events),
        "latest_event_hash": previous_hash,
    }


def _serialize_event(event: CanonicalParserPromotionEvent) -> dict[str, Any]:
    return {
        "event_id": event.event_id,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "previous_status": event.previous_status,
        "new_status": event.new_status,
        "actor_label": event.actor_label,
        "reason": event.reason,
        "previous_event_hash": event.previous_event_hash,
        "event_hash": event.event_hash,
        "occurred_at": event.occurred_at,
    }


def _serialize_promotion(
    db: Session,
    promotion: CanonicalParserPromotion,
    *,
    created: bool | None = None,
    include_events: bool = False,
) -> dict[str, Any]:
    chain = _audit_chain(db, promotion)
    payload: dict[str, Any] = {
        "promotion_id": promotion.promotion_id,
        "promotion_key": promotion.promotion_key,
        "assessment_id": promotion.assessment_id,
        "scope": promotion.scope,
        "status": promotion.status,
        "parser_name": promotion.parser_name,
        "parser_version": promotion.parser_version,
        "parser_implementation_hash": promotion.parser_implementation_hash,
        "output_schema_version": promotion.output_schema_version,
        "assessment_policy_hash": promotion.assessment_policy_hash,
        "assessment_evidence_hash": promotion.assessment_evidence_hash,
        "promotion_policy_version": promotion.promotion_policy_version,
        "promotion_policy_hash": promotion.promotion_policy_hash,
        "release_manifest": promotion.release_manifest,
        "release_manifest_hash": promotion.release_manifest_hash,
        "approved_at": promotion.approved_at,
        "revoked_at": promotion.revoked_at,
        "revocation_reason": promotion.revocation_reason,
        "latest_event_sequence": promotion.latest_event_sequence,
        "latest_event_hash": promotion.latest_event_hash,
        "audit_chain": chain,
        "technical_metadata": promotion.technical_metadata,
    }
    if include_events:
        events = list(
            db.scalars(
                select(CanonicalParserPromotionEvent)
                .where(
                    CanonicalParserPromotionEvent.promotion_db_id
                    == promotion.id
                )
                .order_by(CanonicalParserPromotionEvent.sequence.asc())
            )
        )
        payload["events"] = [_serialize_event(event) for event in events]
    if created is not None:
        payload["created"] = created
    return payload


def preview_parser_promotion(
    db: Session,
    *,
    assessment_id: str | None = None,
    scope: str = PROMOTION_SCOPE,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    evaluation_time = _aware(evaluated_at) or _utc_now()
    normalized_scope = _normalize_scope(scope)
    assessment = _get_assessment(db, assessment_id)
    policy = _promotion_policy_snapshot(
        settings_object=settings_object,
        scope=normalized_scope,
    )
    policy_hash = calculate_payload_hash(policy)
    blockers: set[str] = set()
    warnings: set[str] = set()

    if assessment.status != "READY":
        blockers.add("ASSESSMENT_NOT_READY")

    try:
        current_evaluation = preview_canonical_quality_gate(
            db,
            validation_id=assessment.validation_id,
            settings_object=settings_object,
            evaluated_at=assessment.evaluated_at,
        )
    except CanonicalQualityGateError:
        current_evaluation = None
        blockers.add("ASSESSMENT_EVIDENCE_UNVERIFIABLE")

    if current_evaluation is not None:
        expected_pairs = {
            "assessment_key": assessment.assessment_key,
            "policy_hash": assessment.policy_hash,
            "evidence_hash": assessment.evidence_hash,
            "decision": assessment.status,
            "parser_name": assessment.parser_name,
            "parser_version": assessment.parser_version,
            "parser_implementation_hash": assessment.parser_implementation_hash,
        }
        for field, stored_value in expected_pairs.items():
            if current_evaluation.get(field) != stored_value:
                blockers.add(f"ASSESSMENT_{field.upper()}_MISMATCH")

    evidence_completed_at = _aware(assessment.evidence_completed_at)
    if evidence_completed_at is None:
        blockers.add("ASSESSMENT_EVIDENCE_COMPLETION_MISSING")
        age_hours = None
    else:
        age_hours = max(
            0.0,
            (evaluation_time - evidence_completed_at).total_seconds() / 3600,
        )
        if age_hours > policy["maximum_assessment_age_hours"]:
            blockers.add("ASSESSMENT_EVIDENCE_STALE")

    try:
        definition = registry.get(
            assessment.parser_name,
            assessment.parser_version,
        )
    except ParserRegistryError:
        definition = None
        blockers.add("PARSER_NOT_REGISTERED")

    if definition is not None:
        if definition.implementation_hash != assessment.parser_implementation_hash:
            blockers.add("PARSER_IMPLEMENTATION_HASH_MISMATCH")
        if not definition.deterministic:
            blockers.add("PARSER_NOT_DETERMINISTIC")
        if definition.performs_external_requests:
            blockers.add("PARSER_NETWORK_ACCESS_FORBIDDEN")
        if definition.writes_trades:
            blockers.add("PARSER_TRADE_WRITES_FORBIDDEN")
        if not definition.enabled:
            blockers.add("PARSER_DISABLED")
        parser_manifest = definition.as_dict()
    else:
        parser_manifest = {
            "name": assessment.parser_name,
            "version": assessment.parser_version,
            "implementation_hash": assessment.parser_implementation_hash,
            "output_schema_version": None,
        }

    release_manifest = {
        "scope": normalized_scope,
        "assessment_id": assessment.assessment_id,
        "assessment_key": assessment.assessment_key,
        "assessment_policy_hash": assessment.policy_hash,
        "assessment_evidence_hash": assessment.evidence_hash,
        "parser": parser_manifest,
        "promotion_policy_version": PROMOTION_POLICY_VERSION,
        "promotion_policy_hash": policy_hash,
        "runtime_activation": False,
    }
    release_manifest_hash = calculate_payload_hash(release_manifest)
    promotion_key = calculate_payload_hash(
        {
            "assessment_id": assessment.assessment_id,
            "parser_name": assessment.parser_name,
            "parser_version": assessment.parser_version,
            "parser_implementation_hash": assessment.parser_implementation_hash,
            "scope": normalized_scope,
            "promotion_policy_hash": policy_hash,
            "release_manifest_hash": release_manifest_hash,
        }
    )

    existing = db.scalar(
        select(CanonicalParserPromotion).where(
            CanonicalParserPromotion.promotion_key == promotion_key
        )
    )
    active = db.scalar(
        select(CanonicalParserPromotion).where(
            CanonicalParserPromotion.parser_name == assessment.parser_name,
            CanonicalParserPromotion.scope == normalized_scope,
            CanonicalParserPromotion.status == "APPROVED",
        )
    )
    if existing is not None and existing.status == "REVOKED":
        blockers.add("PROMOTION_PREVIOUSLY_REVOKED")
    if active is not None and active.promotion_key != promotion_key:
        blockers.add("ACTIVE_PROMOTION_ALREADY_EXISTS")

    if assessment.reason_codes:
        warnings.add("ASSESSMENT_CONTAINS_REASON_CODES")

    return {
        "dry_run": True,
        "promotion_enabled": bool(
            getattr(
                settings_object,
                "CANONICAL_PARSER_PROMOTION_ENABLED",
                False,
            )
        ),
        "eligible": not blockers,
        "blocker_codes": sorted(blockers),
        "warning_codes": sorted(warnings),
        "scope": normalized_scope,
        "assessment_id": assessment.assessment_id,
        "assessment_status": assessment.status,
        "assessment_evidence_age_hours": age_hours,
        "parser_name": assessment.parser_name,
        "parser_version": assessment.parser_version,
        "parser_implementation_hash": assessment.parser_implementation_hash,
        "output_schema_version": parser_manifest.get("output_schema_version"),
        "promotion_policy": policy,
        "promotion_policy_hash": policy_hash,
        "release_manifest": release_manifest,
        "release_manifest_hash": release_manifest_hash,
        "promotion_key": promotion_key,
        "confirmation": (
            f"{APPROVAL_CONFIRMATION_PREFIX}:{promotion_key[:16]}"
        ),
        "existing_promotion": (
            _serialize_promotion(db, existing)
            if existing is not None
            else None
        ),
        "active_promotion_id": (
            active.promotion_id if active is not None else None
        ),
        "operational_guards": {
            "external_requests": 0,
            "writes_trades": False,
            "starts_workers": False,
            "changes_runtime_flags": False,
            "activates_runtime_parser": False,
            "scope": "AUDIT_LEDGER_ONLY",
        },
    }


def approve_parser_promotion(
    db: Session,
    *,
    confirmation: str,
    assessment_id: str | None = None,
    scope: str = PROMOTION_SCOPE,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    approved_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(
        getattr(settings_object, "CANONICAL_PARSER_PROMOTION_ENABLED", False)
    ):
        raise CanonicalParserPromotionError(
            "Canonical parser promotion ledger disabilitato.",
            code="CANONICAL_PARSER_PROMOTION_DISABLED",
            status_code=409,
        )

    decision_time = _aware(approved_at) or _utc_now()
    preview = preview_parser_promotion(
        db,
        assessment_id=assessment_id,
        scope=scope,
        settings_object=settings_object,
        registry=registry,
        evaluated_at=decision_time,
    )
    if str(confirmation or "").strip() != preview["confirmation"]:
        raise CanonicalParserPromotionError(
            "Conferma promozione parser non valida o non aggiornata.",
            code="PARSER_PROMOTION_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if not preview["eligible"]:
        raise CanonicalParserPromotionError(
            "Assessment non idoneo alla promozione parser.",
            code="PARSER_PROMOTION_NOT_ELIGIBLE",
            status_code=409,
        )

    existing = db.scalar(
        select(CanonicalParserPromotion).where(
            CanonicalParserPromotion.promotion_key == preview["promotion_key"]
        )
    )
    if existing is not None:
        return _serialize_promotion(db, existing, created=False)

    assessment = _get_assessment(db, preview["assessment_id"])
    public_id = str(uuid4())
    event_id = str(uuid4())
    actor = _normalize_actor_label(actor_label)
    normalized_note = _normalize_optional_reason(note)
    event_payload = _event_payload(
        event_id=event_id,
        promotion_id=public_id,
        sequence=1,
        event_type="APPROVED",
        previous_status=None,
        new_status="APPROVED",
        actor_label=actor,
        reason=normalized_note,
        previous_event_hash=None,
        occurred_at=decision_time,
    )
    event_hash = calculate_payload_hash(event_payload)

    promotion = CanonicalParserPromotion(
        promotion_id=public_id,
        promotion_key=preview["promotion_key"],
        assessment_db_id=assessment.id,
        assessment_id=assessment.assessment_id,
        scope=preview["scope"],
        status="APPROVED",
        parser_name=preview["parser_name"],
        parser_version=preview["parser_version"],
        parser_implementation_hash=preview["parser_implementation_hash"],
        output_schema_version=preview["output_schema_version"],
        assessment_policy_hash=assessment.policy_hash,
        assessment_evidence_hash=assessment.evidence_hash,
        promotion_policy_version=PROMOTION_POLICY_VERSION,
        promotion_policy_hash=preview["promotion_policy_hash"],
        release_manifest=preview["release_manifest"],
        release_manifest_hash=preview["release_manifest_hash"],
        approved_at=decision_time,
        latest_event_sequence=1,
        latest_event_hash=event_hash,
        technical_metadata=sanitize_technical_metadata(
            {
                **preview["operational_guards"],
                "actor_label": actor,
                "approval_note_present": normalized_note is not None,
            }
        ),
    )

    try:
        with db.begin_nested():
            db.add(promotion)
            db.flush()
            db.add(
                CanonicalParserPromotionEvent(
                    event_id=event_id,
                    promotion_db_id=promotion.id,
                    sequence=1,
                    event_type="APPROVED",
                    previous_status=None,
                    new_status="APPROVED",
                    actor_label=actor,
                    reason=normalized_note,
                    event_payload=event_payload,
                    previous_event_hash=None,
                    event_hash=event_hash,
                    occurred_at=decision_time,
                )
            )
            db.flush()
    except IntegrityError as exception:
        existing = db.scalar(
            select(CanonicalParserPromotion).where(
                CanonicalParserPromotion.promotion_key
                == preview["promotion_key"]
            )
        )
        if existing is not None:
            db.commit()
            return _serialize_promotion(db, existing, created=False)
        raise CanonicalParserPromotionError(
            "Conflitto concorrente durante la promozione parser.",
            code="PARSER_PROMOTION_CONFLICT",
            status_code=409,
        ) from exception

    db.commit()
    db.refresh(promotion)
    return _serialize_promotion(db, promotion, created=True)


def revoke_parser_promotion(
    db: Session,
    *,
    promotion_id: str,
    confirmation: str,
    reason: str,
    actor_label: str | None = None,
    settings_object: Any = settings,
    revoked_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(
        getattr(settings_object, "CANONICAL_PARSER_PROMOTION_ENABLED", False)
    ):
        raise CanonicalParserPromotionError(
            "Canonical parser promotion ledger disabilitato.",
            code="CANONICAL_PARSER_PROMOTION_DISABLED",
            status_code=409,
        )
    normalized_id = str(promotion_id or "").strip()
    expected_confirmation = f"{REVOCATION_CONFIRMATION_PREFIX}:{normalized_id}"
    if str(confirmation or "").strip() != expected_confirmation:
        raise CanonicalParserPromotionError(
            "Conferma revoca parser non valida.",
            code="PARSER_PROMOTION_REVOCATION_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    normalized_reason = _normalize_optional_reason(reason)
    if normalized_reason is None or len(normalized_reason) < 3:
        raise CanonicalParserPromotionError(
            "La revoca richiede una motivazione.",
            code="PARSER_PROMOTION_REVOCATION_REASON_REQUIRED",
            status_code=422,
        )

    promotion = _get_promotion(db, normalized_id, for_update=True)
    if promotion.status == "REVOKED":
        return _serialize_promotion(db, promotion, created=False)
    chain = _audit_chain(db, promotion)
    if not chain["valid"]:
        raise CanonicalParserPromotionError(
            "Catena audit della promozione non valida.",
            code="PARSER_PROMOTION_AUDIT_CHAIN_INVALID",
            status_code=409,
        )

    decision_time = _aware(revoked_at) or _utc_now()
    actor = _normalize_actor_label(actor_label)
    event_id = str(uuid4())
    sequence = promotion.latest_event_sequence + 1
    event_payload = _event_payload(
        event_id=event_id,
        promotion_id=promotion.promotion_id,
        sequence=sequence,
        event_type="REVOKED",
        previous_status=promotion.status,
        new_status="REVOKED",
        actor_label=actor,
        reason=normalized_reason,
        previous_event_hash=promotion.latest_event_hash,
        occurred_at=decision_time,
    )
    event_hash = calculate_payload_hash(event_payload)

    promotion.status = "REVOKED"
    promotion.revoked_at = decision_time
    promotion.revocation_reason = normalized_reason
    promotion.latest_event_sequence = sequence
    promotion.latest_event_hash = event_hash
    promotion.technical_metadata = sanitize_technical_metadata(
        {
            **(promotion.technical_metadata or {}),
            "revoked_by": actor,
            "runtime_activation": False,
        }
    )
    db.add(
        CanonicalParserPromotionEvent(
            event_id=event_id,
            promotion_db_id=promotion.id,
            sequence=sequence,
            event_type="REVOKED",
            previous_status="APPROVED",
            new_status="REVOKED",
            actor_label=actor,
            reason=normalized_reason,
            event_payload=event_payload,
            previous_event_hash=event_payload["previous_event_hash"],
            event_hash=event_hash,
            occurred_at=decision_time,
        )
    )
    db.commit()
    db.refresh(promotion)
    return _serialize_promotion(db, promotion, created=True)


def get_parser_promotion(
    db: Session,
    promotion_id: str,
) -> dict[str, Any]:
    promotion = _get_promotion(db, promotion_id)
    return _serialize_promotion(db, promotion, include_events=True)


def get_parser_promotion_status(
    db: Session,
    *,
    settings_object: Any = settings,
) -> dict[str, Any]:
    latest = db.scalar(
        select(CanonicalParserPromotion)
        .order_by(CanonicalParserPromotion.id.desc())
        .limit(1)
    )
    active = list(
        db.scalars(
            select(CanonicalParserPromotion)
            .where(CanonicalParserPromotion.status == "APPROVED")
            .order_by(CanonicalParserPromotion.parser_name.asc())
        )
    )
    counts = dict(
        db.execute(
            select(
                CanonicalParserPromotion.status,
                func.count(CanonicalParserPromotion.id),
            ).group_by(CanonicalParserPromotion.status)
        ).all()
    )
    return {
        "promotion_enabled": bool(
            getattr(
                settings_object,
                "CANONICAL_PARSER_PROMOTION_ENABLED",
                False,
            )
        ),
        "policy_version": PROMOTION_POLICY_VERSION,
        "supported_scope": PROMOTION_SCOPE,
        "promotion_count": int(sum(counts.values())),
        "status_counts": {
            "APPROVED": int(counts.get("APPROVED", 0)),
            "REVOKED": int(counts.get("REVOKED", 0)),
        },
        "active_promotions": [
            _serialize_promotion(db, promotion) for promotion in active
        ],
        "latest_promotion": (
            _serialize_promotion(db, latest) if latest is not None else None
        ),
        "operational_guards": {
            "external_requests": 0,
            "writes_trades": False,
            "starts_workers": False,
            "changes_runtime_flags": False,
            "activates_runtime_parser": False,
            "runtime_selection_enabled": False,
        },
    }
