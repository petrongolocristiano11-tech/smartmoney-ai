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
    CanonicalParserRuntimeBinding,
    CanonicalParserRuntimeBindingEvent,
)
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    sanitize_error_message,
    sanitize_technical_metadata,
)
from backend.app.services.blockchain_parser_promotion_service import (
    CanonicalParserPromotionError,
    get_parser_promotion,
)
from backend.app.services.blockchain_parser_registry_service import (
    DEFAULT_PARSER_REGISTRY,
    ParserRegistry,
    ParserRegistryError,
)


RUNTIME_BINDING_POLICY_VERSION = "canonical-parser-runtime-binding/1"
RUNTIME_SCOPE = "SHADOW_ONLY"
RUNTIME_CHANNEL = "CANONICAL_SHADOW"
BIND_CONFIRMATION_PREFIX = "BIND_CANONICAL_PARSER"
UNBIND_CONFIRMATION_PREFIX = "UNBIND_CANONICAL_PARSER"
_MAX_REASON_LENGTH = 500
_MAX_ACTOR_LABEL_LENGTH = 80


class CanonicalParserRuntimeBindingError(ValueError):
    def __init__(self, message: str, *, code: str, status_code: int = 422):
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
    return aware.isoformat() if aware else None


def _normalize_scope(value: str | None) -> str:
    normalized = str(value or RUNTIME_SCOPE).strip().upper()
    if normalized != RUNTIME_SCOPE:
        raise CanonicalParserRuntimeBindingError(
            "Scope runtime parser non supportato.",
            code="PARSER_RUNTIME_SCOPE_UNSUPPORTED",
        )
    return normalized


def _normalize_channel(value: str | None) -> str:
    normalized = str(value or RUNTIME_CHANNEL).strip().upper()
    if normalized != RUNTIME_CHANNEL:
        raise CanonicalParserRuntimeBindingError(
            "Canale runtime parser non supportato.",
            code="PARSER_RUNTIME_CHANNEL_UNSUPPORTED",
        )
    return normalized


def _normalize_actor(value: str | None) -> str:
    return sanitize_error_message(
        value or "LOCAL_OPERATOR", max_length=_MAX_ACTOR_LABEL_LENGTH
    ) or "LOCAL_OPERATOR"


def _normalize_reason(value: str | None) -> str | None:
    if not str(value or "").strip():
        return None
    return sanitize_error_message(value, max_length=_MAX_REASON_LENGTH)


def _policy_snapshot(*, scope: str, channel: str) -> dict[str, Any]:
    return {
        "policy_version": RUNTIME_BINDING_POLICY_VERSION,
        "scope": scope,
        "channel": channel,
        "required_promotion_status": "APPROVED",
        "require_valid_promotion_audit_chain": True,
        "require_current_registry_identity": True,
        "require_deterministic_parser": True,
        "metadata_resolution_only": True,
        "runtime_consumer_enabled": False,
        "external_requests_allowed": False,
        "trade_writes_allowed": False,
        "automatic_execution": False,
    }


def _get_promotion(db: Session, promotion_id: str | None) -> CanonicalParserPromotion:
    query = select(CanonicalParserPromotion)
    normalized = str(promotion_id or "").strip()
    if normalized:
        query = query.where(CanonicalParserPromotion.promotion_id == normalized)
    else:
        query = (
            query.where(CanonicalParserPromotion.status == "APPROVED")
            .order_by(CanonicalParserPromotion.id.desc())
            .limit(1)
        )
    promotion = db.scalar(query)
    if promotion is None:
        raise CanonicalParserRuntimeBindingError(
            "Promozione parser APPROVED non trovata.",
            code="PARSER_RUNTIME_PROMOTION_NOT_FOUND",
            status_code=404,
        )
    return promotion


def _get_binding(
    db: Session, binding_id: str, *, for_update: bool = False
) -> CanonicalParserRuntimeBinding:
    query = select(CanonicalParserRuntimeBinding).where(
        CanonicalParserRuntimeBinding.binding_id == str(binding_id or "").strip()
    )
    if for_update:
        query = query.with_for_update()
    binding = db.scalar(query)
    if binding is None:
        raise CanonicalParserRuntimeBindingError(
            "Binding runtime parser non trovato.",
            code="PARSER_RUNTIME_BINDING_NOT_FOUND",
            status_code=404,
        )
    return binding


def _event_payload(
    *, event_id: str, binding_id: str, sequence: int, event_type: str,
    previous_status: str | None, new_status: str, actor_label: str,
    reason: str | None, previous_event_hash: str | None, occurred_at: datetime,
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "binding_id": binding_id,
        "sequence": int(sequence),
        "event_type": event_type,
        "previous_status": previous_status,
        "new_status": new_status,
        "actor_label": actor_label,
        "reason": reason,
        "previous_event_hash": previous_event_hash,
        "occurred_at": _iso(occurred_at),
    }


def _binding_chain(db: Session, binding: CanonicalParserRuntimeBinding) -> dict[str, Any]:
    events = list(db.scalars(
        select(CanonicalParserRuntimeBindingEvent)
        .where(CanonicalParserRuntimeBindingEvent.binding_db_id == binding.id)
        .order_by(CanonicalParserRuntimeBindingEvent.sequence.asc())
    ))
    reasons: list[str] = []
    previous_hash = None
    previous_status = None
    for expected, event in enumerate(events, start=1):
        expected_payload = _event_payload(
            event_id=event.event_id,
            binding_id=binding.binding_id,
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
        if event.sequence != expected:
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
        if binding.latest_event_sequence != events[-1].sequence:
            reasons.append("LATEST_EVENT_SEQUENCE_MISMATCH")
        if binding.latest_event_hash != events[-1].event_hash:
            reasons.append("LATEST_EVENT_HASH_MISMATCH")
        if binding.status != events[-1].new_status:
            reasons.append("BINDING_STATUS_MISMATCH")
    return {
        "valid": not reasons,
        "reason_codes": sorted(set(reasons)),
        "event_count": len(events),
        "latest_event_hash": previous_hash,
    }


def _promotion_health(
    db: Session,
    promotion: CanonicalParserPromotion,
    *, registry: ParserRegistry,
) -> tuple[list[str], Any | None, dict[str, Any]]:
    reasons: set[str] = set()
    detail: dict[str, Any] = {}
    try:
        detail = get_parser_promotion(db, promotion.promotion_id)
    except CanonicalParserPromotionError:
        reasons.add("PROMOTION_UNREADABLE")
    if promotion.status != "APPROVED":
        reasons.add("PROMOTION_NOT_APPROVED")
    if promotion.scope != RUNTIME_SCOPE:
        reasons.add("PROMOTION_SCOPE_MISMATCH")
    if detail and not detail.get("audit_chain", {}).get("valid", False):
        reasons.add("PROMOTION_AUDIT_CHAIN_INVALID")
    if calculate_payload_hash(promotion.release_manifest) != promotion.release_manifest_hash:
        reasons.add("PROMOTION_RELEASE_MANIFEST_HASH_MISMATCH")
    definition = None
    try:
        definition = registry.get(promotion.parser_name, promotion.parser_version)
    except ParserRegistryError:
        reasons.add("PARSER_NOT_IN_REGISTRY")
    if definition is not None:
        if not definition.deterministic:
            reasons.add("PARSER_NOT_DETERMINISTIC")
        if definition.performs_external_requests:
            reasons.add("PARSER_NETWORK_FORBIDDEN")
        if definition.writes_trades:
            reasons.add("PARSER_TRADE_WRITES_FORBIDDEN")
        if definition.implementation_hash != promotion.parser_implementation_hash:
            reasons.add("PARSER_IMPLEMENTATION_HASH_DRIFT")
        if definition.output_schema_version != promotion.output_schema_version:
            reasons.add("PARSER_SCHEMA_VERSION_DRIFT")
    return sorted(reasons), definition, detail


def _serialize_event(event: CanonicalParserRuntimeBindingEvent) -> dict[str, Any]:
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


def _resolve_health(
    db: Session,
    binding: CanonicalParserRuntimeBinding,
    *, registry: ParserRegistry,
) -> dict[str, Any]:
    reasons: set[str] = set()
    chain = _binding_chain(db, binding)
    if not chain["valid"]:
        reasons.add("BINDING_AUDIT_CHAIN_INVALID")
    promotion = db.get(CanonicalParserPromotion, binding.promotion_db_id)
    definition = None
    if promotion is None:
        reasons.add("PROMOTION_MISSING")
    else:
        promotion_reasons, definition, _ = _promotion_health(
            db, promotion, registry=registry
        )
        reasons.update(promotion_reasons)
        if promotion.promotion_id != binding.promotion_id:
            reasons.add("PROMOTION_ID_MISMATCH")
        if promotion.release_manifest_hash != binding.release_manifest_hash:
            reasons.add("RELEASE_MANIFEST_HASH_DRIFT")
    if binding.status != "ACTIVE":
        reasons.add("BINDING_NOT_ACTIVE")
    if binding.scope != RUNTIME_SCOPE or binding.channel != RUNTIME_CHANNEL:
        reasons.add("BINDING_SCOPE_CHANNEL_MISMATCH")
    if definition is not None:
        if definition.name != binding.parser_name:
            reasons.add("BINDING_PARSER_NAME_DRIFT")
        if definition.version != binding.parser_version:
            reasons.add("BINDING_PARSER_VERSION_DRIFT")
        if definition.implementation_hash != binding.parser_implementation_hash:
            reasons.add("BINDING_IMPLEMENTATION_HASH_DRIFT")
        if definition.output_schema_version != binding.output_schema_version:
            reasons.add("BINDING_SCHEMA_VERSION_DRIFT")
    return {
        "status": "HEALTHY" if not reasons else "DRIFTED",
        "reason_codes": sorted(reasons),
        "audit_chain": chain,
        "parser": definition.as_dict() if definition is not None else None,
    }


def _serialize_binding(
    db: Session,
    binding: CanonicalParserRuntimeBinding,
    *, registry: ParserRegistry,
    created: bool | None = None,
    include_events: bool = False,
) -> dict[str, Any]:
    health = _resolve_health(db, binding, registry=registry)
    payload: dict[str, Any] = {
        "binding_id": binding.binding_id,
        "binding_key": binding.binding_key,
        "promotion_id": binding.promotion_id,
        "scope": binding.scope,
        "channel": binding.channel,
        "status": binding.status,
        "parser_name": binding.parser_name,
        "parser_version": binding.parser_version,
        "parser_implementation_hash": binding.parser_implementation_hash,
        "output_schema_version": binding.output_schema_version,
        "release_manifest_hash": binding.release_manifest_hash,
        "binding_policy_version": binding.binding_policy_version,
        "binding_policy_hash": binding.binding_policy_hash,
        "bound_at": binding.bound_at,
        "unbound_at": binding.unbound_at,
        "unbind_reason": binding.unbind_reason,
        "latest_event_sequence": binding.latest_event_sequence,
        "latest_event_hash": binding.latest_event_hash,
        "resolution_health": health,
        "technical_metadata": binding.technical_metadata,
    }
    if include_events:
        events = list(db.scalars(
            select(CanonicalParserRuntimeBindingEvent)
            .where(CanonicalParserRuntimeBindingEvent.binding_db_id == binding.id)
            .order_by(CanonicalParserRuntimeBindingEvent.sequence.asc())
        ))
        payload["events"] = [_serialize_event(event) for event in events]
    if created is not None:
        payload["created"] = created
    return payload


def preview_parser_runtime_binding(
    db: Session,
    *, promotion_id: str | None = None, scope: str = RUNTIME_SCOPE,
    channel: str = RUNTIME_CHANNEL, registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    settings_object: Any = settings,
) -> dict[str, Any]:
    normalized_scope = _normalize_scope(scope)
    normalized_channel = _normalize_channel(channel)
    promotion = _get_promotion(db, promotion_id)
    blockers, definition, _ = _promotion_health(db, promotion, registry=registry)
    active = db.scalar(select(CanonicalParserRuntimeBinding).where(
        CanonicalParserRuntimeBinding.scope == normalized_scope,
        CanonicalParserRuntimeBinding.channel == normalized_channel,
        CanonicalParserRuntimeBinding.status == "ACTIVE",
    ))
    idempotent = active is not None and active.promotion_id == promotion.promotion_id
    if active is not None and not idempotent:
        blockers.append("ACTIVE_BINDING_EXISTS")
    policy = _policy_snapshot(scope=normalized_scope, channel=normalized_channel)
    policy_hash = calculate_payload_hash(policy)
    manifest = {
        "promotion_id": promotion.promotion_id,
        "promotion_key": promotion.promotion_key,
        "scope": normalized_scope,
        "channel": normalized_channel,
        "parser_name": promotion.parser_name,
        "parser_version": promotion.parser_version,
        "parser_implementation_hash": promotion.parser_implementation_hash,
        "output_schema_version": promotion.output_schema_version,
        "release_manifest_hash": promotion.release_manifest_hash,
        "binding_policy_hash": policy_hash,
    }
    binding_key = calculate_payload_hash(manifest)
    confirmation = (
        f"{BIND_CONFIRMATION_PREFIX}:{promotion.promotion_id}:"
        f"{normalized_channel}:{binding_key[:12]}"
    )
    blockers = sorted(set(blockers))
    return {
        "dry_run": True,
        "binding_enabled": bool(getattr(
            settings_object, "CANONICAL_PARSER_RUNTIME_BINDING_ENABLED", False
        )),
        "eligible": not blockers,
        "idempotent_existing": idempotent,
        "blocker_codes": blockers,
        "promotion_id": promotion.promotion_id,
        "scope": normalized_scope,
        "channel": normalized_channel,
        "parser_name": promotion.parser_name,
        "parser_version": promotion.parser_version,
        "parser_implementation_hash": promotion.parser_implementation_hash,
        "output_schema_version": promotion.output_schema_version,
        "release_manifest_hash": promotion.release_manifest_hash,
        "binding_policy": policy,
        "binding_policy_hash": policy_hash,
        "binding_manifest": manifest,
        "binding_key": binding_key,
        "confirmation": confirmation,
        "active_binding_id": active.binding_id if active else None,
        "registry_parser": definition.as_dict() if definition else None,
        "writes_database": False,
        "writes_trades": False,
        "external_requests": 0,
        "runtime_consumer_enabled": False,
    }


def bind_parser_runtime(
    db: Session, *, promotion_id: str, confirmation: str,
    scope: str = RUNTIME_SCOPE, channel: str = RUNTIME_CHANNEL,
    actor_label: str | None = None, note: str | None = None,
    settings_object: Any = settings, registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    bound_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(
        settings_object, "CANONICAL_PARSER_RUNTIME_BINDING_ENABLED", False
    )):
        raise CanonicalParserRuntimeBindingError(
            "Canonical parser runtime binding disabilitato.",
            code="CANONICAL_PARSER_RUNTIME_BINDING_DISABLED",
            status_code=409,
        )
    preview = preview_parser_runtime_binding(
        db, promotion_id=promotion_id, scope=scope, channel=channel,
        registry=registry, settings_object=settings_object,
    )
    if str(confirmation or "").strip() != preview["confirmation"]:
        raise CanonicalParserRuntimeBindingError(
            "Conferma binding runtime parser non valida o non aggiornata.",
            code="PARSER_RUNTIME_BINDING_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if preview["idempotent_existing"]:
        existing = db.scalar(select(CanonicalParserRuntimeBinding).where(
            CanonicalParserRuntimeBinding.binding_id == preview["active_binding_id"]
        ))
        return _serialize_binding(db, existing, registry=registry, created=False)
    if not preview["eligible"]:
        raise CanonicalParserRuntimeBindingError(
            "Promozione non idonea al binding runtime.",
            code="PARSER_RUNTIME_BINDING_NOT_ELIGIBLE",
            status_code=409,
        )
    existing = db.scalar(select(CanonicalParserRuntimeBinding).where(
        CanonicalParserRuntimeBinding.binding_key == preview["binding_key"]
    ))
    decision_time = _aware(bound_at) or _utc_now()
    if existing is not None and existing.status == "UNBOUND":
        chain = _binding_chain(db, existing)
        if not chain["valid"]:
            raise CanonicalParserRuntimeBindingError(
                "Catena audit del binding non valida.",
                code="PARSER_RUNTIME_BINDING_AUDIT_CHAIN_INVALID", status_code=409,
            )
        actor = _normalize_actor(actor_label)
        normalized_note = _normalize_reason(note)
        event_id = str(uuid4())
        sequence = existing.latest_event_sequence + 1
        event_payload = _event_payload(
            event_id=event_id, binding_id=existing.binding_id, sequence=sequence,
            event_type="BOUND", previous_status="UNBOUND", new_status="ACTIVE",
            actor_label=actor, reason=normalized_note,
            previous_event_hash=existing.latest_event_hash, occurred_at=decision_time,
        )
        event_hash = calculate_payload_hash(event_payload)
        existing.status = "ACTIVE"
        existing.bound_at = decision_time
        existing.unbound_at = None
        existing.unbind_reason = None
        existing.latest_event_sequence = sequence
        existing.latest_event_hash = event_hash
        existing.technical_metadata = sanitize_technical_metadata({
            **(existing.technical_metadata or {}),
            "rebound_by": actor,
            "runtime_consumer_enabled": False,
        })
        db.add(CanonicalParserRuntimeBindingEvent(
            event_id=event_id, binding_db_id=existing.id, sequence=sequence,
            event_type="BOUND", previous_status="UNBOUND", new_status="ACTIVE",
            actor_label=actor, reason=normalized_note, event_payload=event_payload,
            previous_event_hash=event_payload["previous_event_hash"],
            event_hash=event_hash, occurred_at=decision_time,
        ))
        db.commit()
        db.refresh(existing)
        return _serialize_binding(db, existing, registry=registry, created=True)
    if existing is not None:
        return _serialize_binding(db, existing, registry=registry, created=False)
    promotion = _get_promotion(db, promotion_id)
    public_id = str(uuid4())
    event_id = str(uuid4())
    actor = _normalize_actor(actor_label)
    normalized_note = _normalize_reason(note)
    event_payload = _event_payload(
        event_id=event_id, binding_id=public_id, sequence=1,
        event_type="BOUND", previous_status=None, new_status="ACTIVE",
        actor_label=actor, reason=normalized_note,
        previous_event_hash=None, occurred_at=decision_time,
    )
    event_hash = calculate_payload_hash(event_payload)
    binding = CanonicalParserRuntimeBinding(
        binding_id=public_id,
        binding_key=preview["binding_key"],
        promotion_db_id=promotion.id,
        promotion_id=promotion.promotion_id,
        scope=preview["scope"], channel=preview["channel"], status="ACTIVE",
        parser_name=promotion.parser_name, parser_version=promotion.parser_version,
        parser_implementation_hash=promotion.parser_implementation_hash,
        output_schema_version=promotion.output_schema_version,
        release_manifest_hash=promotion.release_manifest_hash,
        binding_policy_version=RUNTIME_BINDING_POLICY_VERSION,
        binding_policy_hash=preview["binding_policy_hash"],
        bound_at=decision_time, latest_event_sequence=1,
        latest_event_hash=event_hash,
        technical_metadata=sanitize_technical_metadata({
            "actor_label": actor,
            "note_present": normalized_note is not None,
            "metadata_resolution_only": True,
            "runtime_consumer_enabled": False,
        }),
    )
    try:
        with db.begin_nested():
            db.add(binding)
            db.flush()
            db.add(CanonicalParserRuntimeBindingEvent(
                event_id=event_id, binding_db_id=binding.id, sequence=1,
                event_type="BOUND", previous_status=None, new_status="ACTIVE",
                actor_label=actor, reason=normalized_note,
                event_payload=event_payload, previous_event_hash=None,
                event_hash=event_hash, occurred_at=decision_time,
            ))
            db.flush()
    except IntegrityError as exception:
        existing = db.scalar(select(CanonicalParserRuntimeBinding).where(
            CanonicalParserRuntimeBinding.binding_key == preview["binding_key"]
        ))
        if existing is not None:
            db.commit()
            return _serialize_binding(db, existing, registry=registry, created=False)
        raise CanonicalParserRuntimeBindingError(
            "Conflitto concorrente durante il binding runtime parser.",
            code="PARSER_RUNTIME_BINDING_CONFLICT", status_code=409,
        ) from exception
    db.commit()
    db.refresh(binding)
    return _serialize_binding(db, binding, registry=registry, created=True)


def unbind_parser_runtime(
    db: Session, *, binding_id: str, confirmation: str, reason: str,
    actor_label: str | None = None, settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
    unbound_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(
        settings_object, "CANONICAL_PARSER_RUNTIME_BINDING_ENABLED", False
    )):
        raise CanonicalParserRuntimeBindingError(
            "Canonical parser runtime binding disabilitato.",
            code="CANONICAL_PARSER_RUNTIME_BINDING_DISABLED", status_code=409,
        )
    normalized_id = str(binding_id or "").strip()
    expected = f"{UNBIND_CONFIRMATION_PREFIX}:{normalized_id}"
    if str(confirmation or "").strip() != expected:
        raise CanonicalParserRuntimeBindingError(
            "Conferma unbind runtime parser non valida.",
            code="PARSER_RUNTIME_UNBIND_CONFIRMATION_REQUIRED", status_code=409,
        )
    normalized_reason = _normalize_reason(reason)
    if normalized_reason is None or len(normalized_reason) < 3:
        raise CanonicalParserRuntimeBindingError(
            "L'unbind richiede una motivazione.",
            code="PARSER_RUNTIME_UNBIND_REASON_REQUIRED",
        )
    binding = _get_binding(db, normalized_id, for_update=True)
    if binding.status == "UNBOUND":
        return _serialize_binding(db, binding, registry=registry, created=False)
    chain = _binding_chain(db, binding)
    if not chain["valid"]:
        raise CanonicalParserRuntimeBindingError(
            "Catena audit del binding non valida.",
            code="PARSER_RUNTIME_BINDING_AUDIT_CHAIN_INVALID", status_code=409,
        )
    decision_time = _aware(unbound_at) or _utc_now()
    actor = _normalize_actor(actor_label)
    event_id = str(uuid4())
    sequence = binding.latest_event_sequence + 1
    event_payload = _event_payload(
        event_id=event_id, binding_id=binding.binding_id, sequence=sequence,
        event_type="UNBOUND", previous_status="ACTIVE", new_status="UNBOUND",
        actor_label=actor, reason=normalized_reason,
        previous_event_hash=binding.latest_event_hash, occurred_at=decision_time,
    )
    event_hash = calculate_payload_hash(event_payload)
    binding.status = "UNBOUND"
    binding.unbound_at = decision_time
    binding.unbind_reason = normalized_reason
    binding.latest_event_sequence = sequence
    binding.latest_event_hash = event_hash
    binding.technical_metadata = sanitize_technical_metadata({
        **(binding.technical_metadata or {}),
        "unbound_by": actor,
        "runtime_consumer_enabled": False,
    })
    db.add(CanonicalParserRuntimeBindingEvent(
        event_id=event_id, binding_db_id=binding.id, sequence=sequence,
        event_type="UNBOUND", previous_status="ACTIVE", new_status="UNBOUND",
        actor_label=actor, reason=normalized_reason,
        event_payload=event_payload,
        previous_event_hash=event_payload["previous_event_hash"],
        event_hash=event_hash, occurred_at=decision_time,
    ))
    db.commit()
    db.refresh(binding)
    return _serialize_binding(db, binding, registry=registry, created=True)


def resolve_shadow_parser_runtime(
    db: Session, *, scope: str = RUNTIME_SCOPE, channel: str = RUNTIME_CHANNEL,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
) -> dict[str, Any]:
    normalized_scope = _normalize_scope(scope)
    normalized_channel = _normalize_channel(channel)
    binding = db.scalar(select(CanonicalParserRuntimeBinding).where(
        CanonicalParserRuntimeBinding.scope == normalized_scope,
        CanonicalParserRuntimeBinding.channel == normalized_channel,
        CanonicalParserRuntimeBinding.status == "ACTIVE",
    ))
    if binding is None:
        return {
            "resolved": False, "status": "UNBOUND", "reason_codes": ["NO_ACTIVE_BINDING"],
            "scope": normalized_scope, "channel": normalized_channel,
            "parser": None, "metadata_resolution_only": True,
            "runtime_consumer_enabled": False, "external_requests": 0,
            "writes_trades": False,
        }
    serialized = _serialize_binding(db, binding, registry=registry)
    health = serialized["resolution_health"]
    return {
        "resolved": health["status"] == "HEALTHY",
        "status": health["status"],
        "reason_codes": health["reason_codes"],
        "scope": binding.scope, "channel": binding.channel,
        "binding_id": binding.binding_id, "promotion_id": binding.promotion_id,
        "parser": health["parser"] if health["status"] == "HEALTHY" else None,
        "metadata_resolution_only": True,
        "runtime_consumer_enabled": False,
        "external_requests": 0, "writes_trades": False,
    }


def get_parser_runtime_binding(
    db: Session, binding_id: str, *, registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
) -> dict[str, Any]:
    return _serialize_binding(
        db, _get_binding(db, binding_id), registry=registry, include_events=True
    )


def get_parser_runtime_status(
    db: Session, *, settings_object: Any = settings,
    registry: ParserRegistry = DEFAULT_PARSER_REGISTRY,
) -> dict[str, Any]:
    counts = dict(db.execute(select(
        CanonicalParserRuntimeBinding.status,
        func.count(CanonicalParserRuntimeBinding.id),
    ).group_by(CanonicalParserRuntimeBinding.status)).all())
    resolution = resolve_shadow_parser_runtime(db, registry=registry)
    return {
        "binding_enabled": bool(getattr(
            settings_object, "CANONICAL_PARSER_RUNTIME_BINDING_ENABLED", False
        )),
        "policy_version": RUNTIME_BINDING_POLICY_VERSION,
        "supported_scope": RUNTIME_SCOPE,
        "supported_channel": RUNTIME_CHANNEL,
        "binding_count": int(sum(counts.values())),
        "status_counts": {
            "ACTIVE": int(counts.get("ACTIVE", 0)),
            "UNBOUND": int(counts.get("UNBOUND", 0)),
        },
        "resolution": resolution,
        "operational_guards": {
            "metadata_resolution_only": True,
            "runtime_consumer_enabled": False,
            "external_requests": 0,
            "writes_trades": False,
            "starts_workers": False,
            "changes_runtime_flags": False,
            "automatic_execution": False,
        },
    }
