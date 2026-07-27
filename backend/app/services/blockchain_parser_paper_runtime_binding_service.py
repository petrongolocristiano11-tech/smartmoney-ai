from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserPaperAdmissionCertification,
    CanonicalParserPaperRuntimeBinding,
    CanonicalParserPaperRuntimeBindingEvent,
)
from backend.app.models.paper_account import PaperAccount
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    sanitize_error_message,
    sanitize_technical_metadata,
)
from backend.app.services.blockchain_parser_paper_admission_certification_service import (
    resolve_paper_admission_certification,
)

PAPER_RUNTIME_BINDING_POLICY_VERSION = "canonical-parser-paper-runtime-binding/1"
PAPER_RUNTIME_BINDING_PREFIX = "BIND_PAPER_RUNTIME"
PAPER_RUNTIME_UNBIND_PREFIX = "UNBIND_PAPER_RUNTIME"
_MAX_ACTOR_LENGTH = 80
_MAX_NOTE_LENGTH = 500


class CanonicalParserPaperRuntimeBindingError(ValueError):
    def __init__(self, message: str, *, code: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime:
    resolved = value or _utc_now()
    if resolved.tzinfo is None:
        return resolved.replace(tzinfo=timezone.utc)
    return resolved.astimezone(timezone.utc)


def _actor(value: str | None) -> str:
    return sanitize_error_message(value or "LOCAL_PAPER_BINDING", max_length=_MAX_ACTOR_LENGTH) or "LOCAL_PAPER_BINDING"


def _note(value: str | None) -> str | None:
    if not str(value or "").strip():
        return None
    return sanitize_error_message(value, max_length=_MAX_NOTE_LENGTH)


def _policy_snapshot(settings_object: Any) -> dict[str, Any]:
    return {
        "policy_version": PAPER_RUNTIME_BINDING_POLICY_VERSION,
        "validity_minutes": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_RUNTIME_BINDING_VALIDITY_MINUTES", 60)),
        "required_account_status": "ACTIVE",
        "mode": "READ_ONLY_CANARY",
        "manual_binding_only": True,
        "single_active_binding_per_account": True,
        "paper_account_reads": True,
        "paper_account_writes": False,
        "paper_order_reads": False,
        "paper_order_writes": False,
        "paper_position_reads": False,
        "paper_position_writes": False,
        "trade_writes": False,
        "external_requests_allowed": False,
        "paper_runtime_connected": False,
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
    }


def _account_snapshot(account: PaperAccount) -> dict[str, Any]:
    return {
        "paper_account_id": int(account.id),
        "paper_account_name": account.name,
        "status": account.status,
        "starting_balance_sol": str(account.starting_balance_sol),
        "max_position_size_sol": str(account.max_position_size_sol),
        "max_open_positions": int(account.max_open_positions),
        "daily_loss_limit_sol": str(account.daily_loss_limit_sol),
    }


def _event_payload(
    *, event_id: str, binding_id: str, sequence: int, event_type: str,
    previous_status: str | None, new_status: str, actor_label: str,
    reason: str | None, previous_event_hash: str | None, occurred_at: datetime,
) -> dict[str, Any]:
    return {
        "event_id": event_id,
        "binding_id": binding_id,
        "sequence": sequence,
        "event_type": event_type,
        "previous_status": previous_status,
        "new_status": new_status,
        "actor_label": actor_label,
        "reason": reason,
        "previous_event_hash": previous_event_hash,
        "occurred_at": _aware(occurred_at).isoformat(),
    }


def _audit_reasons(db: Session, binding: CanonicalParserPaperRuntimeBinding) -> list[str]:
    events = list(
        db.scalars(
            select(CanonicalParserPaperRuntimeBindingEvent)
            .where(CanonicalParserPaperRuntimeBindingEvent.binding_db_id == binding.id)
            .order_by(CanonicalParserPaperRuntimeBindingEvent.sequence.asc())
        )
    )
    reasons: set[str] = set()
    previous_hash: str | None = None
    for expected_sequence, event in enumerate(events, start=1):
        if event.sequence != expected_sequence:
            reasons.add("PAPER_RUNTIME_BINDING_EVENT_SEQUENCE_INVALID")
        if event.previous_event_hash != previous_hash:
            reasons.add("PAPER_RUNTIME_BINDING_EVENT_CHAIN_INVALID")
        expected = _event_payload(
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
        if calculate_payload_hash(expected) != event.event_hash:
            reasons.add("PAPER_RUNTIME_BINDING_EVENT_HASH_INVALID")
        previous_hash = event.event_hash
    if not events:
        reasons.add("PAPER_RUNTIME_BINDING_EVENTS_MISSING")
    elif binding.latest_event_sequence != events[-1].sequence:
        reasons.add("PAPER_RUNTIME_BINDING_LATEST_SEQUENCE_INVALID")
    elif binding.latest_event_hash != events[-1].event_hash:
        reasons.add("PAPER_RUNTIME_BINDING_LATEST_HASH_INVALID")
    return sorted(reasons)


def _serialize(binding: CanonicalParserPaperRuntimeBinding) -> dict[str, Any]:
    return {
        "binding_id": binding.binding_id,
        "binding_key": binding.binding_key,
        "certification_id": binding.certification_id,
        "certification_event_hash": binding.certification_event_hash,
        "paper_account_id": binding.paper_account_id,
        "paper_account_name": binding.paper_account_name,
        "mode": binding.mode,
        "status": binding.status,
        "account_snapshot_hash": binding.account_snapshot_hash,
        "account_snapshot": binding.account_snapshot,
        "policy_version": binding.policy_version,
        "policy_hash": binding.policy_hash,
        "policy_snapshot": binding.policy_snapshot,
        "actor_label": binding.actor_label,
        "note": binding.note,
        "bound_at": binding.bound_at,
        "expires_at": binding.expires_at,
        "unbound_at": binding.unbound_at,
        "unbind_reason": binding.unbind_reason,
        "latest_event_sequence": binding.latest_event_sequence,
        "latest_event_hash": binding.latest_event_hash,
        "technical_metadata": binding.technical_metadata,
        "paper_runtime_bound": binding.status == "ACTIVE",
        "paper_runtime_connected": False,
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
    }


def preview_paper_runtime_binding(
    db: Session, *, paper_account_id: int, settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _policy_snapshot(settings_object)
    policy_hash = calculate_payload_hash(policy)
    certification = resolve_paper_admission_certification(db, settings_object=settings_object, evaluated_at=now)
    blockers: set[str] = set()
    if certification.get("resolved_status") != "CERTIFIED":
        blockers.add("PAPER_ADMISSION_CERTIFICATION_NOT_CERTIFIED")
    account = db.get(PaperAccount, int(paper_account_id))
    if account is None:
        blockers.add("PAPER_ACCOUNT_NOT_FOUND")
        account_snapshot = None
        account_snapshot_hash = None
    else:
        account_snapshot = _account_snapshot(account)
        account_snapshot_hash = calculate_payload_hash(account_snapshot)
        if account.status != "ACTIVE":
            blockers.add("PAPER_ACCOUNT_NOT_ACTIVE")
    existing_active = db.scalar(
        select(CanonicalParserPaperRuntimeBinding)
        .where(
            CanonicalParserPaperRuntimeBinding.paper_account_id == int(paper_account_id),
            CanonicalParserPaperRuntimeBinding.status == "ACTIVE",
        )
        .order_by(CanonicalParserPaperRuntimeBinding.bound_at.desc())
        .limit(1)
    )
    manifest = {
        "certification_id": certification.get("certification_id"),
        "certification_event_hash": certification.get("latest_event_hash"),
        "paper_account_id": int(paper_account_id),
        "account_snapshot_hash": account_snapshot_hash,
        "policy_hash": policy_hash,
        "mode": "READ_ONLY_CANARY",
    }
    binding_key = calculate_payload_hash(manifest)
    if existing_active is not None and existing_active.binding_key != binding_key:
        blockers.add("PAPER_ACCOUNT_ALREADY_BOUND")
    return {
        "eligible": not blockers,
        "reason_codes": sorted(blockers),
        "binding_key": binding_key,
        "confirmation": f"{PAPER_RUNTIME_BINDING_PREFIX}:{binding_key[:16]}",
        "certification": sanitize_technical_metadata(certification),
        "paper_account": sanitize_technical_metadata(account_snapshot),
        "account_snapshot_hash": account_snapshot_hash,
        "policy": policy,
        "policy_hash": policy_hash,
        "existing_binding_id": existing_active.binding_id if existing_active else None,
        "paper_runtime_bound": False,
        "paper_runtime_connected": False,
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
    }


def bind_paper_runtime(
    db: Session, *, paper_account_id: int, confirmation: str,
    actor_label: str | None = None, note: str | None = None,
    settings_object: Any = settings, bound_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_PAPER_RUNTIME_BINDING_ENABLED", False)):
        raise CanonicalParserPaperRuntimeBindingError(
            "PAPER runtime binding disabilitato.",
            code="CANONICAL_PARSER_PAPER_RUNTIME_BINDING_DISABLED",
            status_code=409,
        )
    now = _aware(bound_at)
    preview = preview_paper_runtime_binding(
        db, paper_account_id=paper_account_id, settings_object=settings_object, evaluated_at=now
    )
    existing = db.scalar(
        select(CanonicalParserPaperRuntimeBinding).where(
            CanonicalParserPaperRuntimeBinding.binding_key == preview["binding_key"]
        )
    )
    if existing is not None:
        return _serialize(existing)
    if confirmation != preview["confirmation"]:
        raise CanonicalParserPaperRuntimeBindingError(
            "Conferma PAPER runtime binding non valida.",
            code="PAPER_RUNTIME_BINDING_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if not preview["eligible"]:
        raise CanonicalParserPaperRuntimeBindingError(
            "PAPER runtime binding non idoneo.",
            code=preview["reason_codes"][0],
            status_code=409,
        )
    certification_id = preview["certification"]["certification_id"]
    certification = db.scalar(
        select(CanonicalParserPaperAdmissionCertification).where(
            CanonicalParserPaperAdmissionCertification.certification_id == certification_id
        )
    )
    account = db.get(PaperAccount, int(paper_account_id))
    if certification is None or account is None:
        raise CanonicalParserPaperRuntimeBindingError(
            "Evidenza PAPER runtime non disponibile.",
            code="PAPER_RUNTIME_BINDING_SOURCE_MISSING",
            status_code=409,
        )
    policy = preview["policy"]
    binding = CanonicalParserPaperRuntimeBinding(
        binding_id=str(uuid4()),
        binding_key=preview["binding_key"],
        certification_db_id=certification.id,
        certification_id=certification.certification_id,
        certification_event_hash=certification.latest_event_hash,
        paper_account_id=account.id,
        paper_account_name=account.name,
        mode="READ_ONLY_CANARY",
        status="ACTIVE",
        account_snapshot_hash=preview["account_snapshot_hash"],
        account_snapshot=preview["paper_account"],
        policy_version=PAPER_RUNTIME_BINDING_POLICY_VERSION,
        policy_hash=preview["policy_hash"],
        policy_snapshot=policy,
        actor_label=_actor(actor_label),
        note=_note(note),
        bound_at=now,
        expires_at=now + timedelta(minutes=int(policy["validity_minutes"])),
        unbound_at=None,
        unbind_reason=None,
        latest_event_sequence=1,
        latest_event_hash="0" * 64,
        technical_metadata={
            "paper_account_reads": True,
            "paper_account_writes": False,
            "paper_runtime_connected": False,
            "paper_execution_authorized": False,
            "live_execution_authorized": False,
        },
    )
    event_id = str(uuid4())
    payload = _event_payload(
        event_id=event_id,
        binding_id=binding.binding_id,
        sequence=1,
        event_type="BOUND",
        previous_status=None,
        new_status="ACTIVE",
        actor_label=binding.actor_label,
        reason=binding.note,
        previous_event_hash=None,
        occurred_at=now,
    )
    binding.latest_event_hash = calculate_payload_hash(payload)
    db.add(binding)
    try:
        db.flush()
        db.add(CanonicalParserPaperRuntimeBindingEvent(
            event_id=event_id,
            binding_db_id=binding.id,
            sequence=1,
            event_type="BOUND",
            previous_status=None,
            new_status="ACTIVE",
            actor_label=binding.actor_label,
            reason=binding.note,
            event_payload=payload,
            previous_event_hash=None,
            event_hash=binding.latest_event_hash,
            occurred_at=now,
        ))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(
            select(CanonicalParserPaperRuntimeBinding).where(
                CanonicalParserPaperRuntimeBinding.binding_key == preview["binding_key"]
            )
        )
        if existing is not None:
            return _serialize(existing)
        raise CanonicalParserPaperRuntimeBindingError(
            "Conflitto durante il PAPER runtime binding.",
            code="PAPER_RUNTIME_BINDING_CONFLICT",
            status_code=409,
        ) from exc
    db.refresh(binding)
    return _serialize(binding)


def unbind_paper_runtime(
    db: Session, *, binding_id: str, confirmation: str, reason: str,
    actor_label: str | None = None, unbound_at: datetime | None = None,
) -> dict[str, Any]:
    binding = db.scalar(
        select(CanonicalParserPaperRuntimeBinding).where(
            CanonicalParserPaperRuntimeBinding.binding_id == binding_id
        )
    )
    if binding is None:
        raise CanonicalParserPaperRuntimeBindingError(
            "PAPER runtime binding non trovato.",
            code="PAPER_RUNTIME_BINDING_NOT_FOUND",
            status_code=404,
        )
    expected = f"{PAPER_RUNTIME_UNBIND_PREFIX}:{binding.binding_id}"
    if confirmation != expected:
        raise CanonicalParserPaperRuntimeBindingError(
            "Conferma unbind PAPER runtime non valida.",
            code="PAPER_RUNTIME_UNBIND_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if binding.status == "UNBOUND":
        return _serialize(binding)
    now = _aware(unbound_at)
    previous_status = binding.status
    binding.status = "UNBOUND"
    binding.unbound_at = now
    binding.unbind_reason = sanitize_error_message(reason, max_length=_MAX_NOTE_LENGTH)
    binding.latest_event_sequence += 1
    event_id = str(uuid4())
    payload = _event_payload(
        event_id=event_id,
        binding_id=binding.binding_id,
        sequence=binding.latest_event_sequence,
        event_type="UNBOUND",
        previous_status=previous_status,
        new_status="UNBOUND",
        actor_label=_actor(actor_label),
        reason=binding.unbind_reason,
        previous_event_hash=binding.latest_event_hash,
        occurred_at=now,
    )
    event_hash = calculate_payload_hash(payload)
    db.add(CanonicalParserPaperRuntimeBindingEvent(
        event_id=event_id,
        binding_db_id=binding.id,
        sequence=binding.latest_event_sequence,
        event_type="UNBOUND",
        previous_status=previous_status,
        new_status="UNBOUND",
        actor_label=payload["actor_label"],
        reason=binding.unbind_reason,
        event_payload=payload,
        previous_event_hash=binding.latest_event_hash,
        event_hash=event_hash,
        occurred_at=now,
    ))
    binding.latest_event_hash = event_hash
    db.commit()
    db.refresh(binding)
    return _serialize(binding)


def get_paper_runtime_binding(db: Session, binding_id: str) -> dict[str, Any]:
    binding = db.scalar(
        select(CanonicalParserPaperRuntimeBinding).where(
            CanonicalParserPaperRuntimeBinding.binding_id == binding_id
        )
    )
    if binding is None:
        raise CanonicalParserPaperRuntimeBindingError(
            "PAPER runtime binding non trovato.",
            code="PAPER_RUNTIME_BINDING_NOT_FOUND",
            status_code=404,
        )
    return _serialize(binding)


def resolve_paper_runtime_binding(
    db: Session, *, settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    binding = db.scalar(
        select(CanonicalParserPaperRuntimeBinding)
        .order_by(CanonicalParserPaperRuntimeBinding.bound_at.desc())
        .limit(1)
    )
    if binding is None:
        return {
            "resolved_status": "UNBOUND",
            "binding_id": None,
            "paper_runtime_bound": False,
            "paper_runtime_connected": False,
            "paper_execution_authorized": False,
            "live_execution_authorized": False,
        }
    payload = _serialize(binding)
    audit_reasons = _audit_reasons(db, binding)
    if audit_reasons:
        payload.update(resolved_status="AUDIT_INVALID", reason_codes=audit_reasons, paper_runtime_bound=False)
        return payload
    if binding.status == "UNBOUND":
        payload.update(resolved_status="UNBOUND", paper_runtime_bound=False)
        return payload
    if _aware(binding.expires_at) <= now:
        payload.update(resolved_status="EXPIRED", paper_runtime_bound=False)
        return payload
    certification = resolve_paper_admission_certification(db, settings_object=settings_object, evaluated_at=now)
    account = db.get(PaperAccount, binding.paper_account_id)
    policy_hash = calculate_payload_hash(_policy_snapshot(settings_object))
    drifted = (
        certification.get("resolved_status") != "CERTIFIED"
        or certification.get("certification_id") != binding.certification_id
        or certification.get("latest_event_hash") != binding.certification_event_hash
        or account is None
        or (account is not None and calculate_payload_hash(_account_snapshot(account)) != binding.account_snapshot_hash)
        or policy_hash != binding.policy_hash
    )
    if drifted:
        payload.update(resolved_status="DRIFTED", paper_runtime_bound=False)
        return payload
    payload.update(resolved_status="BOUND", paper_runtime_bound=True)
    return payload


def get_paper_runtime_binding_status(db: Session, *, settings_object: Any = settings) -> dict[str, Any]:
    return {
        "enabled": bool(getattr(settings_object, "CANONICAL_PARSER_PAPER_RUNTIME_BINDING_ENABLED", False)),
        "policy": _policy_snapshot(settings_object),
        "binding_count": int(db.scalar(select(func.count(CanonicalParserPaperRuntimeBinding.id))) or 0),
        "event_count": int(db.scalar(select(func.count(CanonicalParserPaperRuntimeBindingEvent.id))) or 0),
        "operational_guards": {
            "manual_binding_only": True,
            "paper_account_reads": True,
            "paper_account_writes": False,
            "paper_order_reads": False,
            "paper_order_writes": False,
            "paper_position_reads": False,
            "paper_position_writes": False,
            "trade_writes": False,
            "external_requests_allowed": False,
            "paper_runtime_connected": False,
            "paper_execution_authorized": False,
            "live_execution_authorized": False,
        },
    }
