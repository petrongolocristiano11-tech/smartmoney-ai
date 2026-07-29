from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserAssistedMicroLivePilot,
    CanonicalParserAssistedMicroLivePilotChecklist,
    CanonicalParserAssistedMicroLivePilotCheckpoint,
    CanonicalParserAssistedMicroLivePilotEvent,
    CanonicalParserControlledLiveSubmission,
    CanonicalParserGovernedLiveExitIntent,
    CanonicalParserGovernedLivePosition,
    CanonicalParserLiveIncident,
    CanonicalParserLiveObservabilitySnapshot,
    CanonicalParserLiveOnchainSettlement,
    CanonicalParserLiveOperationalAlert,
    CanonicalParserPreproductionCertification,
)
from backend.app.services.blockchain_integrity_service import calculate_payload_hash

ASSISTED_MICRO_LIVE_PILOT_POLICY_VERSION = "canonical-parser-assisted-micro-live-pilot/1"
ISSUE_PREFIX = "ISSUE_M45_ASSISTED_MICRO_LIVE_PILOT"
ATTEST_PREFIX = "ATTEST_M45_ASSISTED_MICRO_LIVE_CHECK"
ARM_PREFIX = "ARM_M45_ASSISTED_MICRO_LIVE_PILOT"
CHECKPOINT_PREFIX = "CHECKPOINT_M45_ASSISTED_MICRO_LIVE_PILOT"
COMPLETE_PREFIX = "COMPLETE_M45_ASSISTED_MICRO_LIVE_PILOT"
ABORT_PREFIX = "ABORT_M45_ASSISTED_MICRO_LIVE_PILOT"
_MONEY_QUANTUM = Decimal("0.000000001")
_LAMPORTS_PER_SOL = Decimal("1000000000")
_TERMINAL_STATUSES = {"COMPLETED", "ABORTED", "EXPIRED"}
_ACTIVE_STATUSES = {
    "PLANNED",
    "ARMED",
    "ENTRY_SUBMITTED",
    "ENTRY_RECONCILED",
    "ENTRY_SETTLED",
    "EXIT_READY",
    "EXIT_SUBMITTED",
    "EXIT_RECONCILED",
    "EXIT_SETTLED",
}
REQUIRED_CHECKLIST_ITEMS: tuple[str, ...] = (
    "OPERATOR_PRESENT",
    "WALLET_PUBLIC_KEY_VERIFIED",
    "WALLET_BALANCE_LIMITED",
    "TOKEN_MINT_VERIFIED",
    "ENTRY_BUDGET_VERIFIED",
    "EXIT_ROUTE_VERIFIED",
    "RPC_HEALTH_VERIFIED",
    "KILL_SWITCH_VERIFIED",
    "INCIDENT_RUNBOOK_REVIEWED",
    "NO_AUTOMATION_CONFIRMED",
)


class CanonicalParserAssistedMicroLivePilotError(ValueError):
    def __init__(self, message: str, *, code: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _now(value: datetime | None = None) -> datetime:
    resolved = value or datetime.now(timezone.utc)
    if resolved.tzinfo is None:
        return resolved.replace(tzinfo=timezone.utc)
    return resolved.astimezone(timezone.utc)


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return _now(value)


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CanonicalParserAssistedMicroLivePilotError(
            "Valore monetario M45 non valido.", code="M45_INVALID_MONEY_VALUE"
        ) from exc
    if not result.is_finite():
        raise CanonicalParserAssistedMicroLivePilotError(
            "Valore monetario M45 non finito.", code="M45_INVALID_MONEY_VALUE"
        )
    return result.quantize(_MONEY_QUANTUM)


def _money(value: Any) -> str:
    return format(_decimal(value), "f")


def _actor(value: str | None) -> str:
    return str(value or "MANUAL_OPERATOR").strip()[:80] or "MANUAL_OPERATOR"


def _note(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized[:500] if normalized else None


def _policy(settings_object: Any = settings) -> dict[str, Any]:
    return {
        "version": ASSISTED_MICRO_LIVE_PILOT_POLICY_VERSION,
        "enabled": bool(
            getattr(
                settings_object,
                "CANONICAL_PARSER_ASSISTED_MICRO_LIVE_PILOT_ENABLED",
                False,
            )
        ),
        "pilot_guard_enabled": bool(
            getattr(
                settings_object,
                "CANONICAL_PARSER_ASSISTED_MICRO_LIVE_PILOT_GUARD_ENABLED",
                False,
            )
        ),
        "max_validity_minutes": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_ASSISTED_MICRO_LIVE_MAX_VALIDITY_MINUTES",
                60,
            )
        ),
        "max_entry_budget_sol": _money(
            getattr(
                settings_object,
                "CANONICAL_PARSER_ASSISTED_MICRO_LIVE_MAX_ENTRY_BUDGET_SOL",
                0.005,
            )
        ),
        "max_total_fee_sol": _money(
            getattr(
                settings_object,
                "CANONICAL_PARSER_ASSISTED_MICRO_LIVE_MAX_TOTAL_FEE_SOL",
                0.001,
            )
        ),
        "max_position_duration_minutes": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_ASSISTED_MICRO_LIVE_MAX_POSITION_DURATION_MINUTES",
                30,
            )
        ),
        "require_healthy_observability": bool(
            getattr(
                settings_object,
                "CANONICAL_PARSER_ASSISTED_MICRO_LIVE_REQUIRE_HEALTHY_OBSERVABILITY",
                True,
            )
        ),
        "require_active_certification": bool(
            getattr(
                settings_object,
                "CANONICAL_PARSER_ASSISTED_MICRO_LIVE_REQUIRE_ACTIVE_CERTIFICATION",
                True,
            )
        ),
        "required_checklist_items": list(REQUIRED_CHECKLIST_ITEMS),
        "manual_only": True,
        "automatic_submission": False,
        "automatic_exit": False,
        "external_dispatch": False,
    }


def _resolved_certification_status(
    row: CanonicalParserPreproductionCertification, now: datetime
) -> str:
    if row.status == "ACTIVE" and _now(row.expires_at) <= now:
        return "EXPIRED"
    return row.status


def _resolved_pilot_status(
    row: CanonicalParserAssistedMicroLivePilot, now: datetime
) -> str:
    if row.status in _ACTIVE_STATUSES and _now(row.expires_at) <= now:
        return "EXPIRED"
    return row.status


def _operational_health(db: Session, *, now: datetime) -> dict[str, Any]:
    snapshot = db.scalar(
        select(CanonicalParserLiveObservabilitySnapshot)
        .order_by(CanonicalParserLiveObservabilitySnapshot.observed_at.desc())
        .limit(1)
    )
    open_critical_alert_count = int(
        db.scalar(
            select(func.count(CanonicalParserLiveOperationalAlert.id)).where(
                CanonicalParserLiveOperationalAlert.status != "RESOLVED",
                CanonicalParserLiveOperationalAlert.severity == "CRITICAL",
            )
        )
        or 0
    )
    active_incident_count = int(
        db.scalar(
            select(func.count(CanonicalParserLiveIncident.id)).where(
                CanonicalParserLiveIncident.status != "RESOLVED"
            )
        )
        or 0
    )
    freeze_incident_count = int(
        db.scalar(
            select(func.count(CanonicalParserLiveIncident.id)).where(
                CanonicalParserLiveIncident.status != "RESOLVED",
                CanonicalParserLiveIncident.freeze_new_submissions.is_(True),
            )
        )
        or 0
    )
    snapshot_status = None if snapshot is None else snapshot.status
    snapshot_expired = (
        True
        if snapshot is None
        else _now(snapshot.expires_at) <= now
    )
    healthy = (
        snapshot is not None
        and snapshot.status == "HEALTHY"
        and not snapshot_expired
        and open_critical_alert_count == 0
        and active_incident_count == 0
        and freeze_incident_count == 0
    )
    return {
        "healthy": healthy,
        "snapshot_id": None if snapshot is None else snapshot.snapshot_id,
        "snapshot_status": snapshot_status,
        "snapshot_expired": snapshot_expired,
        "open_critical_alert_count": open_critical_alert_count,
        "active_incident_count": active_incident_count,
        "freeze_incident_count": freeze_incident_count,
    }


def _checklist_rows(
    db: Session, pilot_db_id: int
) -> list[CanonicalParserAssistedMicroLivePilotChecklist]:
    return list(
        db.scalars(
            select(CanonicalParserAssistedMicroLivePilotChecklist)
            .where(
                CanonicalParserAssistedMicroLivePilotChecklist.pilot_db_id
                == pilot_db_id
            )
            .order_by(CanonicalParserAssistedMicroLivePilotChecklist.attested_at.asc())
        )
    )


def _runbook(row: CanonicalParserAssistedMicroLivePilot, now: datetime) -> dict[str, Any]:
    status = _resolved_pilot_status(row, now)
    mapping = {
        "PLANNED": ("ATTEST_CHECKLIST", "Attestare tutte le voci obbligatorie e poi armare il pilot."),
        "ARMED": ("SUBMIT_ENTRY", "Eseguire un solo BUY tramite M35-M38 usando questo pilot_id."),
        "ENTRY_SUBMITTED": ("RECONCILE_ENTRY", "Riconciliare M38 fino a FINALIZED e registrare ENTRY_RECONCILED."),
        "ENTRY_RECONCILED": ("SETTLE_ENTRY", "Eseguire M39 e registrare ENTRY_SETTLED."),
        "ENTRY_SETTLED": ("PREPARE_EXIT", "Valutare la posizione M40 ed emettere un exit intent."),
        "EXIT_READY": ("SUBMIT_EXIT", "Eseguire un solo SELL tramite M35-M38 usando questo pilot_id."),
        "EXIT_SUBMITTED": ("RECONCILE_EXIT", "Riconciliare M38 fino a FINALIZED e registrare EXIT_RECONCILED."),
        "EXIT_RECONCILED": ("SETTLE_EXIT", "Eseguire M39 e registrare EXIT_SETTLED."),
        "EXIT_SETTLED": ("POST_PILOT_HEALTH", "Creare uno snapshot M43 HEALTHY, registrarlo e completare il pilot."),
        "COMPLETED": ("NONE", "Pilot completato; conservare evidenze e non riutilizzare."),
        "ABORTED": ("MANUAL_RECOVERY", "Pilot abortito; verificare eventuale posizione residua e usare M41."),
        "EXPIRED": ("MANUAL_REVIEW", "Pilot scaduto; non inviare altre transazioni e verificare eventuali esposizioni."),
    }
    action, instruction = mapping.get(status, ("MANUAL_REVIEW", "Verificare manualmente lo stato del pilot."))
    return {"resolved_status": status, "next_action": action, "instruction": instruction}


def _serialize_pilot(
    db: Session, row: CanonicalParserAssistedMicroLivePilot, *, now: datetime
) -> dict[str, Any]:
    checklist = _checklist_rows(db, row.id)
    checklist_map = {item.item_code: item.status for item in checklist}
    return {
        "pilot_id": row.pilot_id,
        "pilot_key": row.pilot_key,
        "scope": row.scope,
        "status": row.status,
        "resolved_status": _resolved_pilot_status(row, now),
        "certification_id": row.certification_id,
        "wallet_address": row.wallet_address,
        "network": row.network,
        "token_mint": row.token_mint,
        "max_entry_budget_sol": _money(row.max_entry_budget_sol),
        "max_total_fee_sol": _money(row.max_total_fee_sol),
        "max_position_duration_minutes": row.max_position_duration_minutes,
        "required_checklist_count": row.required_checklist_count,
        "passed_checklist_count": row.passed_checklist_count,
        "checklist": [
            {
                "item_code": code,
                "status": checklist_map.get(code, "PENDING"),
            }
            for code in REQUIRED_CHECKLIST_ITEMS
        ],
        "entry_submission_id": row.entry_submission_id,
        "entry_settlement_id": row.entry_settlement_id,
        "position_id": row.position_id,
        "exit_intent_id": row.exit_intent_id,
        "exit_submission_id": row.exit_submission_id,
        "exit_settlement_id": row.exit_settlement_id,
        "post_observability_snapshot_id": row.post_observability_snapshot_id,
        "pilot_snapshot": row.pilot_snapshot,
        "completion_snapshot": row.completion_snapshot,
        "evidence_hash": row.evidence_hash,
        "actor_label": row.actor_label,
        "note": row.note,
        "issued_at": row.issued_at,
        "expires_at": row.expires_at,
        "armed_at": row.armed_at,
        "completed_at": row.completed_at,
        "aborted_at": row.aborted_at,
        "latest_event_sequence": row.latest_event_sequence,
        "latest_event_hash": row.latest_event_hash,
        "runbook": _runbook(row, now),
        "safety": {
            "manual_only": True,
            "automatic_submission": False,
            "automatic_exit": False,
            "private_key_loaded": False,
            "transaction_built": False,
            "transaction_signed": False,
            "transaction_sent_by_m45": False,
        },
    }


def _append_event(
    db: Session,
    row: CanonicalParserAssistedMicroLivePilot,
    *,
    event_type: str,
    payload: dict[str, Any],
    at: datetime,
) -> None:
    sequence = int(row.latest_event_sequence) + 1
    body = {
        "pilot_id": row.pilot_id,
        "sequence": sequence,
        "event_type": event_type,
        "occurred_at": at.isoformat(),
        "payload": payload,
        "previous_event_hash": row.latest_event_hash,
    }
    event_hash = calculate_payload_hash(body)
    db.add(
        CanonicalParserAssistedMicroLivePilotEvent(
            event_id=str(uuid4()),
            pilot_db_id=row.id,
            sequence=sequence,
            event_type=event_type,
            event_payload=body,
            previous_event_hash=row.latest_event_hash,
            event_hash=event_hash,
            occurred_at=at,
        )
    )
    row.latest_event_sequence = sequence
    row.latest_event_hash = event_hash


def get_assisted_micro_live_pilot_status(
    db: Session, *, settings_object: Any = settings, evaluated_at: datetime | None = None
) -> dict[str, Any]:
    now = _now(evaluated_at)
    rows = list(db.scalars(select(CanonicalParserAssistedMicroLivePilot)))
    resolved_counts: dict[str, int] = {}
    for row in rows:
        status = _resolved_pilot_status(row, now)
        resolved_counts[status] = resolved_counts.get(status, 0) + 1
    return {
        "policy": _policy(settings_object),
        "pilot_count": len(rows),
        "resolved_status_counts": resolved_counts,
        "operational_health": _operational_health(db, now=now),
        "required_checklist_items": list(REQUIRED_CHECKLIST_ITEMS),
        "safety": {
            "manual_only": True,
            "automatic_submission": False,
            "automatic_exit": False,
            "external_dispatch": False,
        },
    }


def preview_assisted_micro_live_pilot(
    db: Session,
    *,
    certification_id: str,
    wallet_address: str,
    token_mint: str,
    max_entry_budget_sol: Any,
    max_total_fee_sol: Any,
    max_position_duration_minutes: int,
    validity_minutes: int,
    idempotency_token: str,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _now(evaluated_at)
    policy = _policy(settings_object)
    certification = db.scalar(
        select(CanonicalParserPreproductionCertification).where(
            CanonicalParserPreproductionCertification.certification_id
            == certification_id
        )
    )
    reasons: list[str] = []
    cert_status = None
    if certification is None:
        reasons.append("M45_CERTIFICATION_NOT_FOUND")
    else:
        cert_status = _resolved_certification_status(certification, now)
        if policy["require_active_certification"] and cert_status != "ACTIVE":
            reasons.append("M45_CERTIFICATION_NOT_ACTIVE")
    budget = _decimal(max_entry_budget_sol)
    fees = _decimal(max_total_fee_sol)
    duration = int(max_position_duration_minutes)
    validity = int(validity_minutes)
    if budget <= Decimal("0"):
        reasons.append("M45_ENTRY_BUDGET_NOT_POSITIVE")
    if fees < Decimal("0"):
        reasons.append("M45_TOTAL_FEE_LIMIT_NEGATIVE")
    if duration < 1:
        reasons.append("M45_POSITION_DURATION_TOO_SHORT")
    if validity < 5:
        reasons.append("M45_VALIDITY_TOO_SHORT")
    if budget > _decimal(policy["max_entry_budget_sol"]):
        reasons.append("M45_ENTRY_BUDGET_EXCEEDED")
    if fees > _decimal(policy["max_total_fee_sol"]):
        reasons.append("M45_TOTAL_FEE_LIMIT_EXCEEDED")
    if duration > policy["max_position_duration_minutes"]:
        reasons.append("M45_POSITION_DURATION_EXCEEDED")
    if validity > policy["max_validity_minutes"]:
        reasons.append("M45_VALIDITY_EXCEEDED")
    if certification is not None and now + timedelta(minutes=int(validity_minutes)) > _now(certification.expires_at):
        reasons.append("M45_VALIDITY_EXCEEDS_CERTIFICATION")
    active = db.scalar(
        select(CanonicalParserAssistedMicroLivePilot).where(
            CanonicalParserAssistedMicroLivePilot.wallet_address == str(wallet_address),
            CanonicalParserAssistedMicroLivePilot.token_mint == str(token_mint),
            CanonicalParserAssistedMicroLivePilot.status.in_(tuple(_ACTIVE_STATUSES)),
        )
    )
    if active is not None and _resolved_pilot_status(active, now) in _ACTIVE_STATUSES:
        reasons.append("M45_ACTIVE_PILOT_ALREADY_EXISTS")
    pilot_key = calculate_payload_hash(
        {
            "certification_id": certification_id,
            "wallet_address": str(wallet_address),
            "network": "mainnet-beta",
            "token_mint": str(token_mint),
            "max_entry_budget_sol": _money(budget),
            "max_total_fee_sol": _money(fees),
            "max_position_duration_minutes": int(max_position_duration_minutes),
            "validity_minutes": int(validity_minutes),
            "idempotency_token": str(idempotency_token).strip(),
            "policy": policy,
        }
    )
    existing = db.scalar(
        select(CanonicalParserAssistedMicroLivePilot).where(
            CanonicalParserAssistedMicroLivePilot.pilot_key == pilot_key
        )
    )
    evidence = {
        "certification_id": certification_id,
        "certification_status": cert_status,
        "wallet_address": str(wallet_address),
        "network": "mainnet-beta",
        "token_mint": str(token_mint),
        "max_entry_budget_sol": _money(budget),
        "max_total_fee_sol": _money(fees),
        "max_position_duration_minutes": int(max_position_duration_minutes),
        "validity_minutes": int(validity_minutes),
        "required_checklist_items": list(REQUIRED_CHECKLIST_ITEMS),
        "reason_codes": sorted(set(reasons)),
        "policy": policy,
        "evaluated_at": now.isoformat(),
    }
    return {
        "status": "READY" if not reasons else "BLOCKED",
        "ready": not reasons,
        "pilot_key": pilot_key,
        "existing_pilot": None if existing is None else _serialize_pilot(db, existing, now=now),
        "reason_codes": sorted(set(reasons)),
        "evidence": evidence,
        "evidence_hash": calculate_payload_hash(evidence),
        "confirmation": f"{ISSUE_PREFIX}:{pilot_key}",
        "policy": policy,
        "safety": {
            "manual_only": True,
            "automatic_submission": False,
            "automatic_exit": False,
        },
    }


def issue_assisted_micro_live_pilot(
    db: Session,
    *,
    certification_id: str,
    wallet_address: str,
    token_mint: str,
    max_entry_budget_sol: Any,
    max_total_fee_sol: Any,
    max_position_duration_minutes: int,
    validity_minutes: int,
    idempotency_token: str,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    issued_at: datetime | None = None,
) -> dict[str, Any]:
    if not _policy(settings_object)["enabled"]:
        raise CanonicalParserAssistedMicroLivePilotError(
            "M45 pilot assistito disabilitato.", code="M45_DISABLED", status_code=409
        )
    now = _now(issued_at)
    preview = preview_assisted_micro_live_pilot(
        db,
        certification_id=certification_id,
        wallet_address=wallet_address,
        token_mint=token_mint,
        max_entry_budget_sol=max_entry_budget_sol,
        max_total_fee_sol=max_total_fee_sol,
        max_position_duration_minutes=max_position_duration_minutes,
        validity_minutes=validity_minutes,
        idempotency_token=idempotency_token,
        settings_object=settings_object,
        evaluated_at=now,
    )
    if preview["existing_pilot"] is not None:
        return preview["existing_pilot"]
    if preview["status"] != "READY":
        raise CanonicalParserAssistedMicroLivePilotError(
            "Creazione pilot M45 bloccata.", code="M45_PILOT_BLOCKED", status_code=409
        )
    if confirmation != preview["confirmation"]:
        raise CanonicalParserAssistedMicroLivePilotError(
            "Conferma pilot M45 non valida.", code="M45_ISSUE_CONFIRMATION_REQUIRED", status_code=409
        )
    certification = db.scalar(
        select(CanonicalParserPreproductionCertification).where(
            CanonicalParserPreproductionCertification.certification_id == certification_id
        )
    )
    assert certification is not None
    pilot_id = str(uuid4())
    initial_body = {
        "pilot_id": pilot_id,
        "sequence": 1,
        "event_type": "ISSUED",
        "occurred_at": now.isoformat(),
        "payload": {"evidence_hash": preview["evidence_hash"]},
        "previous_event_hash": None,
    }
    initial_hash = calculate_payload_hash(initial_body)
    row = CanonicalParserAssistedMicroLivePilot(
        pilot_id=pilot_id,
        pilot_key=preview["pilot_key"],
        scope="M45_ASSISTED_MICRO_LIVE_PILOT",
        status="PLANNED",
        certification_db_id=certification.id,
        certification_id=certification.certification_id,
        wallet_address=str(wallet_address),
        network="mainnet-beta",
        token_mint=str(token_mint),
        max_entry_budget_sol=_decimal(max_entry_budget_sol),
        max_total_fee_sol=_decimal(max_total_fee_sol),
        max_position_duration_minutes=int(max_position_duration_minutes),
        required_checklist_count=len(REQUIRED_CHECKLIST_ITEMS),
        passed_checklist_count=0,
        entry_submission_id=None,
        entry_settlement_id=None,
        position_id=None,
        exit_intent_id=None,
        exit_submission_id=None,
        exit_settlement_id=None,
        post_observability_snapshot_id=None,
        pilot_snapshot=preview["evidence"],
        completion_snapshot=None,
        evidence_hash=preview["evidence_hash"],
        actor_label=_actor(actor_label),
        note=_note(note),
        issued_at=now,
        expires_at=now + timedelta(minutes=int(validity_minutes)),
        armed_at=None,
        completed_at=None,
        aborted_at=None,
        latest_event_sequence=1,
        latest_event_hash=initial_hash,
    )
    db.add(row)
    db.flush()
    db.add(
        CanonicalParserAssistedMicroLivePilotEvent(
            event_id=str(uuid4()),
            pilot_db_id=row.id,
            sequence=1,
            event_type="ISSUED",
            event_payload=initial_body,
            previous_event_hash=None,
            event_hash=initial_hash,
            occurred_at=now,
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.scalar(
            select(CanonicalParserAssistedMicroLivePilot).where(
                CanonicalParserAssistedMicroLivePilot.pilot_key == preview["pilot_key"]
            )
        )
        if duplicate is not None:
            return _serialize_pilot(db, duplicate, now=now)
        raise CanonicalParserAssistedMicroLivePilotError(
            "Conflitto creazione pilot M45.", code="M45_PILOT_CONFLICT", status_code=409
        ) from exc
    db.refresh(row)
    return _serialize_pilot(db, row, now=now)


def preview_assisted_micro_live_checklist_attestation(
    db: Session,
    *,
    pilot_id: str,
    item_code: str,
    status: str,
    evidence: str,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _now(evaluated_at)
    row = db.scalar(
        select(CanonicalParserAssistedMicroLivePilot).where(
            CanonicalParserAssistedMicroLivePilot.pilot_id == pilot_id
        )
    )
    if row is None:
        raise CanonicalParserAssistedMicroLivePilotError(
            "Pilot M45 non trovato.", code="M45_PILOT_NOT_FOUND", status_code=404
        )
    code = str(item_code).strip().upper()
    normalized_status = str(status).strip().upper()
    reasons: list[str] = []
    if _resolved_pilot_status(row, now) != "PLANNED":
        reasons.append("M45_PILOT_NOT_PLANNED")
    if code not in REQUIRED_CHECKLIST_ITEMS:
        reasons.append("M45_UNKNOWN_CHECKLIST_ITEM")
    if normalized_status not in {"PASS", "FAIL"}:
        reasons.append("M45_INVALID_CHECKLIST_STATUS")
    if len(str(evidence).strip()) < 8:
        reasons.append("M45_CHECKLIST_EVIDENCE_TOO_SHORT")
    existing = db.scalar(
        select(CanonicalParserAssistedMicroLivePilotChecklist).where(
            CanonicalParserAssistedMicroLivePilotChecklist.pilot_db_id == row.id,
            CanonicalParserAssistedMicroLivePilotChecklist.item_code == code,
        )
    )
    if existing is not None:
        reasons.append("M45_CHECKLIST_ITEM_ALREADY_ATTESTED")
    evidence_body = {
        "pilot_id": pilot_id,
        "item_code": code,
        "status": normalized_status,
        "evidence": str(evidence).strip()[:500],
        "pilot_evidence_hash": row.evidence_hash,
        "evaluated_at": now.isoformat(),
    }
    evidence_hash = calculate_payload_hash(evidence_body)
    return {
        "status": "READY" if not reasons else "BLOCKED",
        "ready": not reasons,
        "reason_codes": reasons,
        "evidence": evidence_body,
        "evidence_hash": evidence_hash,
        "confirmation": f"{ATTEST_PREFIX}:{pilot_id}:{code}:{normalized_status}:{evidence_hash}",
    }


def attest_assisted_micro_live_checklist(
    db: Session,
    *,
    pilot_id: str,
    item_code: str,
    status: str,
    evidence: str,
    confirmation: str,
    actor_label: str | None = None,
    settings_object: Any = settings,
    attested_at: datetime | None = None,
) -> dict[str, Any]:
    if not _policy(settings_object)["enabled"]:
        raise CanonicalParserAssistedMicroLivePilotError(
            "M45 pilot assistito disabilitato.", code="M45_DISABLED", status_code=409
        )
    now = _now(attested_at)
    preview = preview_assisted_micro_live_checklist_attestation(
        db,
        pilot_id=pilot_id,
        item_code=item_code,
        status=status,
        evidence=evidence,
        evaluated_at=now,
    )
    if preview["status"] != "READY":
        raise CanonicalParserAssistedMicroLivePilotError(
            "Attestazione checklist M45 bloccata.", code="M45_CHECKLIST_BLOCKED", status_code=409
        )
    if confirmation != preview["confirmation"]:
        raise CanonicalParserAssistedMicroLivePilotError(
            "Conferma checklist M45 non valida.", code="M45_CHECKLIST_CONFIRMATION_REQUIRED", status_code=409
        )
    row = db.scalar(
        select(CanonicalParserAssistedMicroLivePilot)
        .where(CanonicalParserAssistedMicroLivePilot.pilot_id == pilot_id)
        .with_for_update()
    )
    assert row is not None
    item = CanonicalParserAssistedMicroLivePilotChecklist(
        item_id=str(uuid4()),
        pilot_db_id=row.id,
        pilot_id=row.pilot_id,
        item_code=preview["evidence"]["item_code"],
        status=preview["evidence"]["status"],
        attestation_detail=preview["evidence"],
        evidence_hash=preview["evidence_hash"],
        actor_label=_actor(actor_label),
        attested_at=now,
    )
    db.add(item)
    if item.status == "PASS":
        row.passed_checklist_count += 1
    _append_event(
        db,
        row,
        event_type="CHECK_ATTESTED",
        payload={
            "item_code": item.item_code,
            "status": item.status,
            "evidence_hash": item.evidence_hash,
        },
        at=now,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise CanonicalParserAssistedMicroLivePilotError(
            "Voce checklist M45 già attestata.", code="M45_CHECKLIST_CONFLICT", status_code=409
        ) from exc
    db.refresh(row)
    return _serialize_pilot(db, row, now=now)


def preview_arm_assisted_micro_live_pilot(
    db: Session,
    *,
    pilot_id: str,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _now(evaluated_at)
    policy = _policy(settings_object)
    row = db.scalar(
        select(CanonicalParserAssistedMicroLivePilot).where(
            CanonicalParserAssistedMicroLivePilot.pilot_id == pilot_id
        )
    )
    if row is None:
        raise CanonicalParserAssistedMicroLivePilotError(
            "Pilot M45 non trovato.", code="M45_PILOT_NOT_FOUND", status_code=404
        )
    reasons: list[str] = []
    if _resolved_pilot_status(row, now) != "PLANNED":
        reasons.append("M45_PILOT_NOT_PLANNED")
    checklist = _checklist_rows(db, row.id)
    statuses = {item.item_code: item.status for item in checklist}
    missing = [code for code in REQUIRED_CHECKLIST_ITEMS if code not in statuses]
    failed = [code for code, value in statuses.items() if value != "PASS"]
    if missing:
        reasons.append("M45_CHECKLIST_INCOMPLETE")
    if failed:
        reasons.append("M45_CHECKLIST_FAILED")
    certification = db.scalar(
        select(CanonicalParserPreproductionCertification).where(
            CanonicalParserPreproductionCertification.id == row.certification_db_id
        )
    )
    cert_status = None if certification is None else _resolved_certification_status(certification, now)
    if policy["require_active_certification"] and cert_status != "ACTIVE":
        reasons.append("M45_CERTIFICATION_NOT_ACTIVE")
    health = _operational_health(db, now=now)
    if policy["require_healthy_observability"] and not health["healthy"]:
        reasons.append("M45_OPERATIONAL_HEALTH_NOT_READY")
    snapshot = {
        "pilot_id": row.pilot_id,
        "checklist": statuses,
        "missing_items": missing,
        "failed_items": failed,
        "certification_status": cert_status,
        "operational_health": health,
        "policy": policy,
        "evaluated_at": now.isoformat(),
    }
    evidence_hash = calculate_payload_hash(snapshot)
    return {
        "status": "READY" if not reasons else "BLOCKED",
        "ready": not reasons,
        "reason_codes": sorted(set(reasons)),
        "snapshot": snapshot,
        "evidence_hash": evidence_hash,
        "confirmation": f"{ARM_PREFIX}:{row.pilot_id}:{evidence_hash}",
    }


def arm_assisted_micro_live_pilot(
    db: Session,
    *,
    pilot_id: str,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    armed_at: datetime | None = None,
) -> dict[str, Any]:
    if not _policy(settings_object)["enabled"]:
        raise CanonicalParserAssistedMicroLivePilotError(
            "M45 pilot assistito disabilitato.", code="M45_DISABLED", status_code=409
        )
    now = _now(armed_at)
    preview = preview_arm_assisted_micro_live_pilot(
        db, pilot_id=pilot_id, settings_object=settings_object, evaluated_at=now
    )
    if preview["status"] != "READY":
        raise CanonicalParserAssistedMicroLivePilotError(
            "Arming pilot M45 bloccato.", code="M45_ARM_BLOCKED", status_code=409
        )
    if confirmation != preview["confirmation"]:
        raise CanonicalParserAssistedMicroLivePilotError(
            "Conferma arming M45 non valida.", code="M45_ARM_CONFIRMATION_REQUIRED", status_code=409
        )
    row = db.scalar(
        select(CanonicalParserAssistedMicroLivePilot)
        .where(CanonicalParserAssistedMicroLivePilot.pilot_id == pilot_id)
        .with_for_update()
    )
    assert row is not None
    row.status = "ARMED"
    row.armed_at = now
    row.actor_label = _actor(actor_label)
    if note is not None:
        row.note = _note(note)
    _append_event(
        db,
        row,
        event_type="ARMED",
        payload={"arming_evidence_hash": preview["evidence_hash"]},
        at=now,
    )
    db.commit()
    db.refresh(row)
    return _serialize_pilot(db, row, now=now)


def validate_assisted_micro_live_pilot_for_submission(
    db: Session,
    *,
    pilot_id: str | None,
    wallet_address: str | None,
    side: str,
    token_mint: str,
    requested_budget_sol: Any,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _now(evaluated_at)
    policy = _policy(settings_object)
    if not policy["pilot_guard_enabled"]:
        return {
            "required": False,
            "ready": True,
            "reason_codes": [],
            "pilot": None,
            "snapshot": {"pilot_guard_enabled": False, "manual_only": True},
        }
    reasons: list[str] = []
    row = None
    certification = None
    normalized_side = str(side).upper()
    if not pilot_id:
        reasons.append("M45_ASSISTED_PILOT_REQUIRED")
    else:
        row = db.scalar(
            select(CanonicalParserAssistedMicroLivePilot).where(
                CanonicalParserAssistedMicroLivePilot.pilot_id == pilot_id
            )
        )
        if row is None:
            reasons.append("M45_ASSISTED_PILOT_NOT_FOUND")
        else:
            certification = db.scalar(
                select(CanonicalParserPreproductionCertification).where(
                    CanonicalParserPreproductionCertification.id == row.certification_db_id
                )
            )
            resolved = _resolved_pilot_status(row, now)
            expected_status = "ARMED" if normalized_side == "BUY" else "EXIT_READY"
            if resolved != expected_status:
                reasons.append("M45_ASSISTED_PILOT_STAGE_MISMATCH")
            if wallet_address is None or row.wallet_address != wallet_address:
                reasons.append("M45_ASSISTED_PILOT_WALLET_MISMATCH")
            if row.token_mint != str(token_mint):
                reasons.append("M45_ASSISTED_PILOT_TOKEN_MISMATCH")
            if normalized_side == "BUY":
                if _decimal(requested_budget_sol) > _decimal(row.max_entry_budget_sol):
                    reasons.append("M45_ASSISTED_PILOT_ENTRY_BUDGET_EXCEEDED")
                if row.entry_submission_id is not None:
                    reasons.append("M45_ASSISTED_PILOT_ENTRY_ALREADY_USED")
            elif normalized_side == "SELL":
                if row.exit_submission_id is not None:
                    reasons.append("M45_ASSISTED_PILOT_EXIT_ALREADY_USED")
            else:
                reasons.append("M45_ASSISTED_PILOT_SIDE_UNSUPPORTED")
            if policy["require_active_certification"] and (
                certification is None
                or _resolved_certification_status(certification, now) != "ACTIVE"
            ):
                reasons.append("M45_ASSISTED_PILOT_CERTIFICATION_NOT_ACTIVE")
    snapshot = {
        "pilot_guard_enabled": True,
        "pilot_id": pilot_id,
        "wallet_address": wallet_address,
        "side": normalized_side,
        "token_mint": str(token_mint),
        "requested_budget_sol": _money(requested_budget_sol),
        "resolved_pilot_status": None if row is None else _resolved_pilot_status(row, now),
        "certification_status": None
        if certification is None
        else _resolved_certification_status(certification, now),
        "single_entry": True,
        "single_exit": True,
        "manual_only": True,
    }
    return {
        "required": True,
        "ready": not reasons,
        "reason_codes": sorted(set(reasons)),
        "pilot": row,
        "snapshot": snapshot,
    }


def consume_assisted_micro_live_pilot_submission_slot(
    db: Session,
    *,
    pilot_id: str,
    submission_id: str,
    wallet_address: str | None,
    side: str,
    token_mint: str,
    requested_budget_sol: Any,
    settings_object: Any = settings,
    consumed_at: datetime | None = None,
) -> dict[str, Any]:
    now = _now(consumed_at)
    validation = validate_assisted_micro_live_pilot_for_submission(
        db,
        pilot_id=pilot_id,
        wallet_address=wallet_address,
        side=side,
        token_mint=token_mint,
        requested_budget_sol=requested_budget_sol,
        settings_object=settings_object,
        evaluated_at=now,
    )
    if not validation["required"]:
        return {"consumed": False, "reason": "M45_PILOT_GUARD_DISABLED"}
    if not validation["ready"]:
        raise CanonicalParserAssistedMicroLivePilotError(
            "Pilot M45 non consumabile.", code="M45_PILOT_CONSUME_BLOCKED", status_code=409
        )
    row = db.scalar(
        select(CanonicalParserAssistedMicroLivePilot)
        .where(CanonicalParserAssistedMicroLivePilot.pilot_id == pilot_id)
        .with_for_update()
    )
    assert row is not None
    normalized_side = str(side).upper()
    if normalized_side == "BUY":
        if row.status != "ARMED" or row.entry_submission_id is not None:
            raise CanonicalParserAssistedMicroLivePilotError(
                "Slot entry M45 già utilizzato.", code="M45_ENTRY_SLOT_ALREADY_USED", status_code=409
            )
        row.entry_submission_id = submission_id
        row.status = "ENTRY_SUBMITTED"
        event_type = "ENTRY_SUBMITTED"
    else:
        if row.status != "EXIT_READY" or row.exit_submission_id is not None:
            raise CanonicalParserAssistedMicroLivePilotError(
                "Slot exit M45 già utilizzato.", code="M45_EXIT_SLOT_ALREADY_USED", status_code=409
            )
        row.exit_submission_id = submission_id
        row.status = "EXIT_SUBMITTED"
        event_type = "EXIT_SUBMITTED"
    _append_event(
        db,
        row,
        event_type=event_type,
        payload={"submission_id": submission_id, "side": normalized_side},
        at=now,
    )
    return {"consumed": True, "pilot": _serialize_pilot(db, row, now=now)}


def _checkpoint_source(
    db: Session,
    *,
    row: CanonicalParserAssistedMicroLivePilot,
    checkpoint_type: str,
    source_id: str,
    now: datetime,
) -> tuple[str, dict[str, Any], list[str], dict[str, Any]]:
    reasons: list[str] = []
    updates: dict[str, Any] = {}
    source_type = "UNKNOWN"
    snapshot: dict[str, Any] = {
        "pilot_id": row.pilot_id,
        "checkpoint_type": checkpoint_type,
        "source_id": source_id,
        "checked_at": now.isoformat(),
    }
    if checkpoint_type == "ENTRY_RECONCILED":
        source_type = "M38_SUBMISSION"
        source = db.scalar(
            select(CanonicalParserControlledLiveSubmission).where(
                CanonicalParserControlledLiveSubmission.submission_id == source_id
            )
        )
        if row.status != "ENTRY_SUBMITTED":
            reasons.append("M45_ENTRY_RECONCILE_STAGE_MISMATCH")
        if source is None:
            reasons.append("M45_ENTRY_SUBMISSION_NOT_FOUND")
        else:
            snapshot["source_status"] = source.status
            snapshot["source_side"] = source.side
            if source.submission_id != row.entry_submission_id:
                reasons.append("M45_ENTRY_SUBMISSION_ID_MISMATCH")
            if source.side != "BUY" or source.token_mint != row.token_mint:
                reasons.append("M45_ENTRY_SUBMISSION_SCOPE_MISMATCH")
            if source.status != "FINALIZED":
                reasons.append("M45_ENTRY_SUBMISSION_NOT_FINALIZED")
        updates["status"] = "ENTRY_RECONCILED"
    elif checkpoint_type == "ENTRY_SETTLED":
        source_type = "M39_SETTLEMENT"
        source = db.scalar(
            select(CanonicalParserLiveOnchainSettlement).where(
                CanonicalParserLiveOnchainSettlement.settlement_id == source_id
            )
        )
        if row.status != "ENTRY_RECONCILED":
            reasons.append("M45_ENTRY_SETTLEMENT_STAGE_MISMATCH")
        position = None
        if source is None:
            reasons.append("M45_ENTRY_SETTLEMENT_NOT_FOUND")
        else:
            snapshot.update({"source_status": source.status, "source_side": source.side, "position_id": source.position_id})
            if source.submission_id != row.entry_submission_id:
                reasons.append("M45_ENTRY_SETTLEMENT_SUBMISSION_MISMATCH")
            if source.side != "BUY" or source.status != "SETTLED":
                reasons.append("M45_ENTRY_SETTLEMENT_NOT_AUTHORITATIVE")
            if source.wallet_address != row.wallet_address or source.token_mint != row.token_mint:
                reasons.append("M45_ENTRY_SETTLEMENT_SCOPE_MISMATCH")
            if source.position_id is None:
                reasons.append("M45_ENTRY_POSITION_MISSING")
            else:
                position = db.scalar(
                    select(CanonicalParserGovernedLivePosition).where(
                        CanonicalParserGovernedLivePosition.position_id == source.position_id
                    )
                )
                if position is None or position.status not in {"OPEN", "REVIEW"}:
                    reasons.append("M45_ENTRY_POSITION_NOT_OPEN")
        updates.update({"status": "ENTRY_SETTLED", "entry_settlement_id": source_id, "position_id": None if source is None else source.position_id})
    elif checkpoint_type == "EXIT_INTENT_VERIFIED":
        source_type = "M40_EXIT_INTENT"
        source = db.scalar(
            select(CanonicalParserGovernedLiveExitIntent).where(
                CanonicalParserGovernedLiveExitIntent.intent_id == source_id
            )
        )
        if row.status != "ENTRY_SETTLED":
            reasons.append("M45_EXIT_INTENT_STAGE_MISMATCH")
        if source is None:
            reasons.append("M45_EXIT_INTENT_NOT_FOUND")
        else:
            snapshot["source_status"] = source.status
            snapshot["position_id"] = source.position_id
            if source.position_id != row.position_id:
                reasons.append("M45_EXIT_INTENT_POSITION_MISMATCH")
            if source.status not in {"ACTIVE", "CONSUMED"}:
                reasons.append("M45_EXIT_INTENT_NOT_USABLE")
        updates.update({"status": "EXIT_READY", "exit_intent_id": source_id})
    elif checkpoint_type == "EXIT_RECONCILED":
        source_type = "M38_SUBMISSION"
        source = db.scalar(
            select(CanonicalParserControlledLiveSubmission).where(
                CanonicalParserControlledLiveSubmission.submission_id == source_id
            )
        )
        if row.status != "EXIT_SUBMITTED":
            reasons.append("M45_EXIT_RECONCILE_STAGE_MISMATCH")
        if source is None:
            reasons.append("M45_EXIT_SUBMISSION_NOT_FOUND")
        else:
            snapshot["source_status"] = source.status
            snapshot["source_side"] = source.side
            if source.submission_id != row.exit_submission_id:
                reasons.append("M45_EXIT_SUBMISSION_ID_MISMATCH")
            if source.side != "SELL" or source.token_mint != row.token_mint:
                reasons.append("M45_EXIT_SUBMISSION_SCOPE_MISMATCH")
            if source.status != "FINALIZED":
                reasons.append("M45_EXIT_SUBMISSION_NOT_FINALIZED")
        updates["status"] = "EXIT_RECONCILED"
    elif checkpoint_type == "EXIT_SETTLED":
        source_type = "M39_SETTLEMENT"
        source = db.scalar(
            select(CanonicalParserLiveOnchainSettlement).where(
                CanonicalParserLiveOnchainSettlement.settlement_id == source_id
            )
        )
        if row.status != "EXIT_RECONCILED":
            reasons.append("M45_EXIT_SETTLEMENT_STAGE_MISMATCH")
        position = None
        if source is None:
            reasons.append("M45_EXIT_SETTLEMENT_NOT_FOUND")
        else:
            snapshot.update({"source_status": source.status, "source_side": source.side, "position_id": source.position_id})
            if source.submission_id != row.exit_submission_id:
                reasons.append("M45_EXIT_SETTLEMENT_SUBMISSION_MISMATCH")
            if source.side != "SELL" or source.status != "SETTLED":
                reasons.append("M45_EXIT_SETTLEMENT_NOT_AUTHORITATIVE")
            if source.wallet_address != row.wallet_address or source.token_mint != row.token_mint:
                reasons.append("M45_EXIT_SETTLEMENT_SCOPE_MISMATCH")
            position = db.scalar(
                select(CanonicalParserGovernedLivePosition).where(
                    CanonicalParserGovernedLivePosition.position_id == row.position_id
                )
            )
            if position is None or position.status != "CLOSED" or Decimal(position.quantity_raw) != 0:
                reasons.append("M45_POSITION_NOT_CLOSED")
        updates.update({"status": "EXIT_SETTLED", "exit_settlement_id": source_id})
    elif checkpoint_type == "POST_PILOT_HEALTH":
        source_type = "M43_OBSERVABILITY_SNAPSHOT"
        source = db.scalar(
            select(CanonicalParserLiveObservabilitySnapshot).where(
                CanonicalParserLiveObservabilitySnapshot.snapshot_id == source_id
            )
        )
        if row.status != "EXIT_SETTLED":
            reasons.append("M45_POST_HEALTH_STAGE_MISMATCH")
        if source is None:
            reasons.append("M45_POST_HEALTH_SNAPSHOT_NOT_FOUND")
        else:
            snapshot.update({"source_status": source.status, "observed_at": source.observed_at.isoformat()})
            if source.status != "HEALTHY" or _now(source.expires_at) <= now:
                reasons.append("M45_POST_HEALTH_NOT_HEALTHY")
            exit_settlement = db.scalar(
                select(CanonicalParserLiveOnchainSettlement).where(
                    CanonicalParserLiveOnchainSettlement.settlement_id == row.exit_settlement_id
                )
            )
            if exit_settlement is None or _now(source.observed_at) < _now(exit_settlement.settled_at):
                reasons.append("M45_POST_HEALTH_PRECEDES_EXIT")
        updates["post_observability_snapshot_id"] = source_id
    else:
        reasons.append("M45_CHECKPOINT_TYPE_UNSUPPORTED")
    return source_type, snapshot, reasons, updates


def preview_assisted_micro_live_pilot_checkpoint(
    db: Session,
    *,
    pilot_id: str,
    checkpoint_type: str,
    source_id: str,
    idempotency_token: str,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _now(evaluated_at)
    row = db.scalar(
        select(CanonicalParserAssistedMicroLivePilot).where(
            CanonicalParserAssistedMicroLivePilot.pilot_id == pilot_id
        )
    )
    if row is None:
        raise CanonicalParserAssistedMicroLivePilotError(
            "Pilot M45 non trovato.", code="M45_PILOT_NOT_FOUND", status_code=404
        )
    normalized = str(checkpoint_type).upper()
    source_type, snapshot, reasons, updates = _checkpoint_source(
        db, row=row, checkpoint_type=normalized, source_id=source_id, now=now
    )
    if _resolved_pilot_status(row, now) in _TERMINAL_STATUSES:
        reasons.append("M45_PILOT_TERMINAL")
    checkpoint_key = calculate_payload_hash(
        {
            "pilot_id": row.pilot_id,
            "checkpoint_type": normalized,
            "source_id": str(source_id),
            "idempotency_token": str(idempotency_token).strip(),
        }
    )
    existing = db.scalar(
        select(CanonicalParserAssistedMicroLivePilotCheckpoint).where(
            CanonicalParserAssistedMicroLivePilotCheckpoint.checkpoint_key
            == checkpoint_key
        )
    )
    evidence = {
        **snapshot,
        "source_type": source_type,
        "reason_codes": sorted(set(reasons)),
        "updates": updates,
    }
    evidence_hash = calculate_payload_hash(evidence)
    return {
        "status": "VERIFIED" if not reasons else "BLOCKED",
        "ready": not reasons,
        "checkpoint_key": checkpoint_key,
        "existing_checkpoint": None
        if existing is None
        else {
            "checkpoint_id": existing.checkpoint_id,
            "status": existing.status,
            "checkpoint_type": existing.checkpoint_type,
        },
        "source_type": source_type,
        "reason_codes": sorted(set(reasons)),
        "snapshot": snapshot,
        "updates": updates,
        "evidence_hash": evidence_hash,
        "confirmation": f"{CHECKPOINT_PREFIX}:{row.pilot_id}:{normalized}:{checkpoint_key}",
    }


def record_assisted_micro_live_pilot_checkpoint(
    db: Session,
    *,
    pilot_id: str,
    checkpoint_type: str,
    source_id: str,
    idempotency_token: str,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    if not _policy(settings_object)["enabled"]:
        raise CanonicalParserAssistedMicroLivePilotError(
            "M45 pilot assistito disabilitato.", code="M45_DISABLED", status_code=409
        )
    now = _now(checked_at)
    preview = preview_assisted_micro_live_pilot_checkpoint(
        db,
        pilot_id=pilot_id,
        checkpoint_type=checkpoint_type,
        source_id=source_id,
        idempotency_token=idempotency_token,
        evaluated_at=now,
    )
    if preview["existing_checkpoint"] is not None:
        return get_assisted_micro_live_pilot(db, pilot_id, evaluated_at=now)
    if preview["status"] != "VERIFIED":
        raise CanonicalParserAssistedMicroLivePilotError(
            "Checkpoint M45 bloccato.", code="M45_CHECKPOINT_BLOCKED", status_code=409
        )
    if confirmation != preview["confirmation"]:
        raise CanonicalParserAssistedMicroLivePilotError(
            "Conferma checkpoint M45 non valida.", code="M45_CHECKPOINT_CONFIRMATION_REQUIRED", status_code=409
        )
    row = db.scalar(
        select(CanonicalParserAssistedMicroLivePilot)
        .where(CanonicalParserAssistedMicroLivePilot.pilot_id == pilot_id)
        .with_for_update()
    )
    assert row is not None
    for key, value in preview["updates"].items():
        setattr(row, key, value)
    checkpoint = CanonicalParserAssistedMicroLivePilotCheckpoint(
        checkpoint_id=str(uuid4()),
        checkpoint_key=preview["checkpoint_key"],
        pilot_db_id=row.id,
        pilot_id=row.pilot_id,
        checkpoint_type=str(checkpoint_type).upper(),
        source_type=preview["source_type"],
        source_id=str(source_id),
        status="VERIFIED",
        reason_codes=[],
        checkpoint_snapshot=preview["snapshot"],
        evidence_hash=preview["evidence_hash"],
        actor_label=_actor(actor_label),
        note=_note(note),
        checked_at=now,
    )
    db.add(checkpoint)
    _append_event(
        db,
        row,
        event_type="CHECKPOINT_VERIFIED",
        payload={
            "checkpoint_type": checkpoint.checkpoint_type,
            "source_id": checkpoint.source_id,
            "checkpoint_id": checkpoint.checkpoint_id,
        },
        at=now,
    )
    db.commit()
    db.refresh(row)
    return _serialize_pilot(db, row, now=now)


def preview_complete_assisted_micro_live_pilot(
    db: Session,
    *,
    pilot_id: str,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _now(evaluated_at)
    row = db.scalar(
        select(CanonicalParserAssistedMicroLivePilot).where(
            CanonicalParserAssistedMicroLivePilot.pilot_id == pilot_id
        )
    )
    if row is None:
        raise CanonicalParserAssistedMicroLivePilotError(
            "Pilot M45 non trovato.", code="M45_PILOT_NOT_FOUND", status_code=404
        )
    reasons: list[str] = []
    resolved_status = _resolved_pilot_status(row, now)
    if resolved_status == "EXPIRED":
        reasons.append("M45_PILOT_EXPIRED")
    if row.status != "EXIT_SETTLED":
        reasons.append("M45_PILOT_NOT_EXIT_SETTLED")
    if row.post_observability_snapshot_id is None:
        reasons.append("M45_POST_HEALTH_MISSING")
    entry = None
    exit_row = None
    position = None
    snapshot = None
    if row.entry_settlement_id:
        entry = db.scalar(
            select(CanonicalParserLiveOnchainSettlement).where(
                CanonicalParserLiveOnchainSettlement.settlement_id == row.entry_settlement_id
            )
        )
    if row.exit_settlement_id:
        exit_row = db.scalar(
            select(CanonicalParserLiveOnchainSettlement).where(
                CanonicalParserLiveOnchainSettlement.settlement_id == row.exit_settlement_id
            )
        )
    if row.position_id:
        position = db.scalar(
            select(CanonicalParserGovernedLivePosition).where(
                CanonicalParserGovernedLivePosition.position_id == row.position_id
            )
        )
    if row.post_observability_snapshot_id:
        snapshot = db.scalar(
            select(CanonicalParserLiveObservabilitySnapshot).where(
                CanonicalParserLiveObservabilitySnapshot.snapshot_id
                == row.post_observability_snapshot_id
            )
        )
    if entry is None or exit_row is None:
        reasons.append("M45_SETTLEMENT_EVIDENCE_MISSING")
    if position is None or position.status != "CLOSED" or Decimal(position.quantity_raw) != 0:
        reasons.append("M45_POSITION_NOT_CLOSED")
    if snapshot is None or snapshot.status != "HEALTHY" or _now(snapshot.expires_at) <= now:
        reasons.append("M45_POST_HEALTH_NOT_HEALTHY")
    total_fee_sol = Decimal("0")
    duration_minutes = None
    if entry is not None and exit_row is not None:
        total_fee_sol = (
            Decimal(entry.fee_lamports) + Decimal(exit_row.fee_lamports)
        ) / _LAMPORTS_PER_SOL
        duration_minutes = (
            _now(exit_row.settled_at) - _now(entry.settled_at)
        ).total_seconds() / 60
        if total_fee_sol > Decimal(row.max_total_fee_sol):
            reasons.append("M45_TOTAL_FEE_EXCEEDED")
        if duration_minutes > row.max_position_duration_minutes:
            reasons.append("M45_POSITION_DURATION_EXCEEDED")
    health = _operational_health(db, now=now)
    if not health["healthy"]:
        reasons.append("M45_OPERATIONAL_HEALTH_NOT_READY")
    completion = {
        "pilot_id": row.pilot_id,
        "entry_submission_id": row.entry_submission_id,
        "entry_settlement_id": row.entry_settlement_id,
        "position_id": row.position_id,
        "exit_intent_id": row.exit_intent_id,
        "exit_submission_id": row.exit_submission_id,
        "exit_settlement_id": row.exit_settlement_id,
        "post_observability_snapshot_id": row.post_observability_snapshot_id,
        "total_fee_sol": _money(total_fee_sol),
        "position_duration_minutes": duration_minutes,
        "realized_pnl_sol": None if position is None else _money(position.realized_pnl_sol),
        "position_status": None if position is None else position.status,
        "operational_health": health,
        "reason_codes": sorted(set(reasons)),
        "evaluated_at": now.isoformat(),
    }
    evidence_hash = calculate_payload_hash(completion)
    return {
        "status": "READY" if not reasons else "BLOCKED",
        "ready": not reasons,
        "reason_codes": sorted(set(reasons)),
        "completion_snapshot": completion,
        "evidence_hash": evidence_hash,
        "confirmation": f"{COMPLETE_PREFIX}:{row.pilot_id}:{evidence_hash}",
    }


def complete_assisted_micro_live_pilot(
    db: Session,
    *,
    pilot_id: str,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    completed_at: datetime | None = None,
) -> dict[str, Any]:
    if not _policy(settings_object)["enabled"]:
        raise CanonicalParserAssistedMicroLivePilotError(
            "M45 pilot assistito disabilitato.", code="M45_DISABLED", status_code=409
        )
    now = _now(completed_at)
    preview = preview_complete_assisted_micro_live_pilot(
        db, pilot_id=pilot_id, evaluated_at=now
    )
    if preview["status"] != "READY":
        raise CanonicalParserAssistedMicroLivePilotError(
            "Completamento pilot M45 bloccato.", code="M45_COMPLETION_BLOCKED", status_code=409
        )
    if confirmation != preview["confirmation"]:
        raise CanonicalParserAssistedMicroLivePilotError(
            "Conferma completamento M45 non valida.", code="M45_COMPLETE_CONFIRMATION_REQUIRED", status_code=409
        )
    row = db.scalar(
        select(CanonicalParserAssistedMicroLivePilot)
        .where(CanonicalParserAssistedMicroLivePilot.pilot_id == pilot_id)
        .with_for_update()
    )
    assert row is not None
    row.status = "COMPLETED"
    row.completed_at = now
    row.completion_snapshot = preview["completion_snapshot"]
    row.actor_label = _actor(actor_label)
    if note is not None:
        row.note = _note(note)
    _append_event(
        db,
        row,
        event_type="COMPLETED",
        payload={"completion_evidence_hash": preview["evidence_hash"]},
        at=now,
    )
    db.commit()
    db.refresh(row)
    return _serialize_pilot(db, row, now=now)


def abort_assisted_micro_live_pilot(
    db: Session,
    *,
    pilot_id: str,
    reason: str,
    confirmation: str,
    actor_label: str | None = None,
    settings_object: Any = settings,
    aborted_at: datetime | None = None,
) -> dict[str, Any]:
    if not _policy(settings_object)["enabled"]:
        raise CanonicalParserAssistedMicroLivePilotError(
            "M45 pilot assistito disabilitato.", code="M45_DISABLED", status_code=409
        )
    now = _now(aborted_at)
    row = db.scalar(
        select(CanonicalParserAssistedMicroLivePilot)
        .where(CanonicalParserAssistedMicroLivePilot.pilot_id == pilot_id)
        .with_for_update()
    )
    if row is None:
        raise CanonicalParserAssistedMicroLivePilotError(
            "Pilot M45 non trovato.", code="M45_PILOT_NOT_FOUND", status_code=404
        )
    if row.status in _TERMINAL_STATUSES:
        return _serialize_pilot(db, row, now=now)
    expected = f"{ABORT_PREFIX}:{row.pilot_id}:{row.evidence_hash}"
    if confirmation != expected:
        raise CanonicalParserAssistedMicroLivePilotError(
            "Conferma abort M45 non valida.", code="M45_ABORT_CONFIRMATION_REQUIRED", status_code=409
        )
    prior_status = row.status
    row.status = "ABORTED"
    row.aborted_at = now
    row.actor_label = _actor(actor_label)
    row.completion_snapshot = {
        "aborted": True,
        "reason": str(reason).strip()[:500],
        "prior_status": prior_status,
        "manual_position_recovery_required": row.position_id is not None
        and row.exit_settlement_id is None,
    }
    _append_event(
        db,
        row,
        event_type="ABORTED",
        payload=row.completion_snapshot,
        at=now,
    )
    db.commit()
    db.refresh(row)
    return _serialize_pilot(db, row, now=now)


def get_assisted_micro_live_pilot(
    db: Session, pilot_id: str, *, evaluated_at: datetime | None = None
) -> dict[str, Any]:
    now = _now(evaluated_at)
    row = db.scalar(
        select(CanonicalParserAssistedMicroLivePilot).where(
            CanonicalParserAssistedMicroLivePilot.pilot_id == pilot_id
        )
    )
    if row is None:
        raise CanonicalParserAssistedMicroLivePilotError(
            "Pilot M45 non trovato.", code="M45_PILOT_NOT_FOUND", status_code=404
        )
    checkpoints = list(
        db.scalars(
            select(CanonicalParserAssistedMicroLivePilotCheckpoint)
            .where(CanonicalParserAssistedMicroLivePilotCheckpoint.pilot_db_id == row.id)
            .order_by(CanonicalParserAssistedMicroLivePilotCheckpoint.checked_at.asc())
        )
    )
    payload = _serialize_pilot(db, row, now=now)
    payload["checkpoints"] = [
        {
            "checkpoint_id": item.checkpoint_id,
            "checkpoint_type": item.checkpoint_type,
            "source_type": item.source_type,
            "source_id": item.source_id,
            "status": item.status,
            "evidence_hash": item.evidence_hash,
            "checked_at": item.checked_at,
        }
        for item in checkpoints
    ]
    return payload


def resolve_assisted_micro_live_pilots(
    db: Session,
    *,
    wallet_address: str | None = None,
    token_mint: str | None = None,
    limit: int = 50,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _now(evaluated_at)
    query = select(CanonicalParserAssistedMicroLivePilot)
    if wallet_address:
        query = query.where(
            CanonicalParserAssistedMicroLivePilot.wallet_address == wallet_address
        )
    if token_mint:
        query = query.where(CanonicalParserAssistedMicroLivePilot.token_mint == token_mint)
    rows = list(
        db.scalars(
            query.order_by(CanonicalParserAssistedMicroLivePilot.issued_at.desc()).limit(
                max(1, min(int(limit), 200))
            )
        )
    )
    return {
        "items": [_serialize_pilot(db, row, now=now) for row in rows],
        "count": len(rows),
        "evaluated_at": now,
    }
