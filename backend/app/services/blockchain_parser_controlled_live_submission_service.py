from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserControlledLiveSubmission,
    CanonicalParserControlledLiveSubmissionEvent,
    CanonicalParserExternalSigningApproval,
    CanonicalParserIsolatedSignerProfile,
    CanonicalParserLiveTransactionDryRun,
    CanonicalParserMicroLiveCanaryPermit,
)
from backend.app.models.live_platform_config import LivePlatformConfig
from backend.app.models.live_trading_policy import LiveTradingPolicy
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    sanitize_error_message,
)
from backend.app.services.blockchain_parser_external_signing_approval_service import (
    inspect_and_verify_signed_transaction,
)
from backend.app.services.solana_rpc import SolanaRpcClient

CONTROLLED_LIVE_SUBMISSION_POLICY_VERSION = (
    "canonical-parser-controlled-live-submission/1"
)
SUBMISSION_PREFIX = "SUBMIT_M38_CONTROLLED_LIVE"
RECONCILE_PREFIX = "RECONCILE_M38_CONTROLLED_LIVE"
_MONEY_QUANTUM = Decimal("0.000000001")
_ACTIVE_BUDGET_STATUSES = {
    "RESERVED",
    "SUBMITTED",
    "PROCESSED",
    "CONFIRMED",
    "FINALIZED",
    "FAILED",
    "RECONCILIATION_REQUIRED",
}


class CanonicalParserControlledLiveSubmissionError(ValueError):
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


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CanonicalParserControlledLiveSubmissionError(
            "Valore budget M38 non valido.", code="M38_INVALID_BUDGET"
        ) from exc
    if not result.is_finite():
        raise CanonicalParserControlledLiveSubmissionError(
            "Valore budget M38 non finito.", code="M38_INVALID_BUDGET"
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
        "version": CONTROLLED_LIVE_SUBMISSION_POLICY_VERSION,
        "send_rpc_enabled": bool(
            getattr(
                settings_object,
                "CANONICAL_PARSER_CONTROLLED_LIVE_SEND_RPC_ENABLED",
                False,
            )
        ),
        "reconciliation_enabled": bool(
            getattr(
                settings_object,
                "CANONICAL_PARSER_CONTROLLED_LIVE_RECONCILIATION_ENABLED",
                False,
            )
        ),
        "maximum_pending_seconds": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_CONTROLLED_LIVE_MAX_PENDING_SECONDS",
                180,
            )
        ),
        "manual_only": True,
        "autonomous_worker_permitted": False,
        "raw_signed_transaction_persisted": False,
    }


def _live_control_snapshot(
    db: Session, *, now: datetime, settings_object: Any
) -> dict[str, Any]:
    live_policy = db.scalar(
        select(LiveTradingPolicy).order_by(LiveTradingPolicy.id.asc()).limit(1)
    )
    platform = db.scalar(
        select(LivePlatformConfig).order_by(LivePlatformConfig.id.asc()).limit(1)
    )
    reasons: list[str] = []
    if live_policy is None:
        reasons.append("LIVE_POLICY_MISSING")
    else:
        # The legacy/autonomous LIVE path must remain hard-stopped. M38 is the
        # only one-shot manual submission path.
        if live_policy.mode != "DISABLED":
            reasons.append("LEGACY_LIVE_MODE_NOT_DISABLED")
        if not live_policy.kill_switch:
            reasons.append("LEGACY_KILL_SWITCH_NOT_ENGAGED")
        if live_policy.stream_execution_enabled:
            reasons.append("LEGACY_STREAM_EXECUTION_ENABLED")
    if platform is None:
        reasons.append("LIVE_PLATFORM_CONFIG_MISSING")
    else:
        if platform.live_armed_until is not None and _aware(platform.live_armed_until) > now:
            reasons.append("LEGACY_LIVE_PLATFORM_ARMED")
        if not platform.token_safety_enabled:
            reasons.append("TOKEN_SAFETY_DISABLED")
        if not platform.token_safety_fail_closed:
            reasons.append("TOKEN_SAFETY_NOT_FAIL_CLOSED")
    if bool(getattr(settings_object, "RUN_LIVE_STREAM_WORKER", False)):
        reasons.append("LIVE_STREAM_WORKER_ENABLED")
    if bool(getattr(settings_object, "RUN_LIVE_POSITION_MONITOR", False)):
        reasons.append("LIVE_POSITION_MONITOR_ENABLED")
    snapshot = {
        "live_policy": None
        if live_policy is None
        else {
            "id": live_policy.id,
            "mode": live_policy.mode,
            "kill_switch": bool(live_policy.kill_switch),
            "stream_execution_enabled": bool(live_policy.stream_execution_enabled),
            "max_order_size_sol": str(live_policy.max_order_size_sol),
            "max_daily_buy_sol": str(live_policy.max_daily_buy_sol),
            "max_total_exposure_sol": str(live_policy.max_total_exposure_sol),
        },
        "platform": None
        if platform is None
        else {
            "id": platform.id,
            "live_armed_until": None
            if platform.live_armed_until is None
            else _aware(platform.live_armed_until).isoformat(),
            "token_safety_enabled": bool(platform.token_safety_enabled),
            "token_safety_fail_closed": bool(platform.token_safety_fail_closed),
        },
        "reasons": reasons,
    }
    if reasons:
        raise CanonicalParserControlledLiveSubmissionError(
            "Stato LIVE non sicuro per il percorso M38.",
            code="M38_LIVE_CONTROL_STATE_UNSAFE",
            status_code=409,
        )
    return snapshot


def _serialize(row: CanonicalParserControlledLiveSubmission) -> dict[str, Any]:
    return {
        "submission_id": row.submission_id,
        "submission_key": row.submission_key,
        "scope": row.scope,
        "approval_id": row.approval_id,
        "dry_run_id": row.dry_run_id,
        "micro_live_permit_id": row.micro_live_permit_id,
        "status": row.status,
        "side": row.side,
        "token_mint": row.token_mint,
        "reserved_budget_sol": _money(row.reserved_budget_sol),
        "signed_transaction_hash": row.signed_transaction_hash,
        "expected_signature": row.expected_signature,
        "rpc_signature": row.rpc_signature,
        "send_attempted": row.send_attempted,
        "confirmation_status": row.confirmation_status,
        "confirmation_slot": row.confirmation_slot,
        "chain_error": row.chain_error,
        "reason_codes": row.reason_codes,
        "reservation_snapshot": row.reservation_snapshot,
        "submission_snapshot": row.submission_snapshot,
        "evidence_hash": row.evidence_hash,
        "actor_label": row.actor_label,
        "note": row.note,
        "reserved_at": row.reserved_at,
        "submitted_at": row.submitted_at,
        "reconciled_at": row.reconciled_at,
        "confirmed_at": row.confirmed_at,
        "finalized_at": row.finalized_at,
        "raw_signed_transaction_persisted": False,
    }


def _add_event(
    db: Session,
    row: CanonicalParserControlledLiveSubmission,
    *,
    event_type: str,
    payload: dict[str, Any],
    occurred_at: datetime,
) -> None:
    previous = db.scalar(
        select(CanonicalParserControlledLiveSubmissionEvent)
        .where(CanonicalParserControlledLiveSubmissionEvent.submission_db_id == row.id)
        .order_by(CanonicalParserControlledLiveSubmissionEvent.sequence.desc())
        .limit(1)
    )
    sequence = 1 if previous is None else previous.sequence + 1
    previous_hash = None if previous is None else previous.event_hash
    event_payload = {
        "submission_id": row.submission_id,
        "sequence": sequence,
        "event_type": event_type,
        "occurred_at": occurred_at.isoformat(),
        "payload": payload,
        "previous_event_hash": previous_hash,
    }
    db.add(
        CanonicalParserControlledLiveSubmissionEvent(
            event_id=str(uuid4()),
            submission_db_id=row.id,
            sequence=sequence,
            event_type=event_type,
            event_payload=event_payload,
            previous_event_hash=previous_hash,
            event_hash=calculate_payload_hash(event_payload),
            occurred_at=occurred_at,
        )
    )


def _permit_usage(
    db: Session, permit_id: str
) -> tuple[Decimal, int]:
    rows = list(
        db.scalars(
            select(CanonicalParserControlledLiveSubmission).where(
                CanonicalParserControlledLiveSubmission.micro_live_permit_id
                == permit_id,
                CanonicalParserControlledLiveSubmission.status.in_(
                    sorted(_ACTIVE_BUDGET_STATUSES)
                ),
            )
        )
    )
    return (
        sum((_decimal(row.reserved_budget_sol) for row in rows), Decimal("0")),
        len(rows),
    )


def _preview(
    db: Session,
    *,
    approval_id: str,
    signed_transaction_base64: str,
    idempotency_token: str,
    portfolio_risk_permit_id: str | None,
    preproduction_release_approval_id: str | None,
    settings_object: Any,
    evaluated_at: datetime,
) -> dict[str, Any]:
    if len(str(idempotency_token or "").strip()) < 8:
        raise CanonicalParserControlledLiveSubmissionError(
            "Idempotency token M38 non valido.", code="M38_IDEMPOTENCY_INVALID"
        )
    approval = db.scalar(
        select(CanonicalParserExternalSigningApproval).where(
            CanonicalParserExternalSigningApproval.approval_id == approval_id
        )
    )
    if approval is None:
        raise CanonicalParserControlledLiveSubmissionError(
            "Approval M37 non trovata.", code="M38_APPROVAL_NOT_FOUND", status_code=404
        )
    dry_run = db.scalar(
        select(CanonicalParserLiveTransactionDryRun).where(
            CanonicalParserLiveTransactionDryRun.id == approval.dry_run_db_id
        )
    )
    signer_profile = None
    if dry_run is not None:
        signer_profile = db.scalar(
            select(CanonicalParserIsolatedSignerProfile).where(
                CanonicalParserIsolatedSignerProfile.id == dry_run.signer_profile_db_id
            )
        )
    permit = db.scalar(
        select(CanonicalParserMicroLiveCanaryPermit)
        .where(
            CanonicalParserMicroLiveCanaryPermit.permit_id
            == approval.micro_live_permit_id
        )
        .with_for_update()
    )
    reasons: list[str] = []
    if approval.status != "READY":
        reasons.append("M37_APPROVAL_NOT_READY")
    if approval.revoked_at is not None:
        reasons.append("M37_APPROVAL_REVOKED")
    if _aware(approval.expires_at) <= evaluated_at:
        reasons.append("M37_APPROVAL_EXPIRED")
    if dry_run is None:
        reasons.append("M36_DRY_RUN_MISSING")
    if permit is None:
        reasons.append("M35_PERMIT_MISSING")
    else:
        if permit.status != "ACTIVE":
            reasons.append("M35_PERMIT_NOT_ACTIVE")
        if _aware(permit.expires_at) <= evaluated_at:
            reasons.append("M35_PERMIT_EXPIRED")
    signed = inspect_and_verify_signed_transaction(signed_transaction_base64)
    if not signed["all_signatures_valid"]:
        reasons.append("SIGNED_TRANSACTION_INVALID")
    if signed["signed_transaction_hash"] != approval.signed_transaction_hash:
        reasons.append("SIGNED_TRANSACTION_HASH_DRIFT")
    if signed["message_hash"] != approval.message_hash:
        reasons.append("SIGNED_MESSAGE_HASH_DRIFT")
    if signed["expected_signature"] != approval.expected_signature:
        reasons.append("SIGNED_SIGNATURE_DRIFT")
    live_snapshot = _live_control_snapshot(
        db, now=evaluated_at, settings_object=settings_object
    )
    budget = Decimal("0") if dry_run is None else _decimal(dry_run.requested_budget_sol)
    if dry_run is not None and dry_run.side == "BUY" and budget <= 0:
        reasons.append("BUY_BUDGET_MISSING")
    incident_guard = {"blocked": False, "reason_codes": [], "active_incident_ids": []}
    portfolio_risk = {"required": False, "ready": True, "reason_codes": [], "permit": None, "snapshot": {"enforcement_enabled": False}}
    preproduction_release = {"required": False, "ready": True, "reason_codes": [], "release": None, "snapshot": {"release_guard_enabled": False}}
    if dry_run is not None:
        from backend.app.services.blockchain_parser_live_incident_response_service import get_live_submission_incident_guard
        from backend.app.services.blockchain_parser_live_portfolio_risk_service import validate_portfolio_risk_permit_for_submission
        from backend.app.services.blockchain_parser_preproduction_certification_service import validate_preproduction_release_for_submission
        incident_guard = get_live_submission_incident_guard(
            db, side=dry_run.side, settings_object=settings_object, evaluated_at=evaluated_at
        )
        reasons.extend(incident_guard["reason_codes"])
        portfolio_risk = validate_portfolio_risk_permit_for_submission(
            db,
            permit_id=portfolio_risk_permit_id,
            side=dry_run.side,
            token_mint=dry_run.token_mint,
            requested_budget_sol=budget,
            wallet_address=None if signer_profile is None else signer_profile.wallet_address,
            settings_object=settings_object,
            evaluated_at=evaluated_at,
        )
        reasons.extend(portfolio_risk["reason_codes"])
        preproduction_release = validate_preproduction_release_for_submission(
            db,
            release_id=preproduction_release_approval_id,
            side=dry_run.side,
            token_mint=dry_run.token_mint,
            requested_budget_sol=budget,
            wallet_address=None if signer_profile is None else signer_profile.wallet_address,
            settings_object=settings_object,
            evaluated_at=evaluated_at,
        )
        reasons.extend(preproduction_release["reason_codes"])
    used_budget = Decimal("0")
    used_count = 0
    if permit is not None:
        used_budget, used_count = _permit_usage(db, permit.permit_id)
        if budget > _decimal(permit.max_order_budget_sol):
            reasons.append("M35_ORDER_BUDGET_EXCEEDED")
        if used_budget + budget > _decimal(permit.total_budget_sol):
            reasons.append("M35_TOTAL_BUDGET_EXCEEDED")
        if used_count + 1 > int(permit.max_order_count):
            reasons.append("M35_ORDER_COUNT_EXCEEDED")
    policy = _policy(settings_object)
    submission_key = calculate_payload_hash(
        {
            "approval_id": approval.approval_id,
            "approval_envelope_hash": approval.approval_envelope_hash,
            "signed_transaction_hash": signed["signed_transaction_hash"],
            "idempotency_token": str(idempotency_token).strip(),
            "portfolio_risk_permit_id": portfolio_risk_permit_id,
            "preproduction_release_approval_id": preproduction_release_approval_id,
            "policy": policy,
        }
    )
    existing = db.scalar(
        select(CanonicalParserControlledLiveSubmission).where(
            CanonicalParserControlledLiveSubmission.submission_key == submission_key
        )
    )
    approval_use = db.scalar(
        select(CanonicalParserControlledLiveSubmission).where(
            CanonicalParserControlledLiveSubmission.approval_db_id == approval.id
        )
    )
    if approval_use is not None and approval_use.submission_key != submission_key:
        reasons.append("M37_APPROVAL_ALREADY_USED")
    reservation = {
        "permit_id": None if permit is None else permit.permit_id,
        "budget_sol": _money(budget),
        "used_budget_before_sol": _money(used_budget),
        "used_order_count_before": used_count,
        "remaining_budget_after_sol": None
        if permit is None
        else _money(_decimal(permit.total_budget_sol) - used_budget - budget),
        "remaining_order_count_after": None
        if permit is None
        else int(permit.max_order_count) - used_count - 1,
        "portfolio_risk": portfolio_risk["snapshot"],
        "preproduction_release": preproduction_release["snapshot"],
        "incident_guard": incident_guard,
    }
    evidence = {
        "approval_id": approval.approval_id,
        "approval_evidence_hash": approval.evidence_hash,
        "signed_transaction_hash": signed["signed_transaction_hash"],
        "expected_signature": signed["expected_signature"],
        "reservation": reservation,
        "live_control_snapshot": live_snapshot,
        "incident_guard": incident_guard,
        "portfolio_risk": portfolio_risk["snapshot"],
        "preproduction_release": preproduction_release["snapshot"],
        "reason_codes": sorted(set(reasons)),
        "policy": policy,
    }
    return {
        "approval": approval,
        "dry_run": dry_run,
        "signer_profile": signer_profile,
        "permit": permit,
        "portfolio_risk_permit": portfolio_risk["permit"],
        "preproduction_release_approval": preproduction_release["release"],
        "incident_guard": incident_guard,
        "portfolio_risk": portfolio_risk,
        "preproduction_release": preproduction_release,
        "signed": signed,
        "submission_key": submission_key,
        "existing_submission": None if existing is None else _serialize(existing),
        "status": "READY" if not reasons else "BLOCKED",
        "reason_codes": sorted(set(reasons)),
        "reservation": reservation,
        "live_control_snapshot": live_snapshot,
        "policy": policy,
        "evidence": evidence,
        "evidence_hash": calculate_payload_hash(evidence),
        "confirmation": f"{SUBMISSION_PREFIX}:{approval.approval_id}:{submission_key}",
    }


def preview_controlled_live_submission(
    db: Session,
    *,
    approval_id: str,
    signed_transaction_base64: str,
    idempotency_token: str,
    portfolio_risk_permit_id: str | None = None,
    preproduction_release_approval_id: str | None = None,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    preview = _preview(
        db,
        approval_id=approval_id,
        signed_transaction_base64=signed_transaction_base64,
        idempotency_token=idempotency_token,
        portfolio_risk_permit_id=portfolio_risk_permit_id,
        preproduction_release_approval_id=preproduction_release_approval_id,
        settings_object=settings_object,
        evaluated_at=_aware(evaluated_at),
    )
    return {
        "status": preview["status"],
        "ready": preview["status"] == "READY",
        "submission_key": preview["submission_key"],
        "existing_submission": preview["existing_submission"],
        "expected_signature": preview["signed"]["expected_signature"],
        "reservation": preview["reservation"],
        "incident_guard": preview["incident_guard"],
        "portfolio_risk": preview["portfolio_risk"]["snapshot"],
        "preproduction_release": preview["preproduction_release"]["snapshot"],
        "reason_codes": preview["reason_codes"],
        "evidence_hash": preview["evidence_hash"],
        "confirmation": preview["confirmation"],
        "policy": preview["policy"],
        "safety": {
            "manual_only": True,
            "legacy_live_engine_disabled": True,
            "legacy_kill_switch_engaged": True,
            "raw_signed_transaction_persisted": False,
            "automatic_retry": False,
        },
    }


def submit_controlled_live_transaction(
    db: Session,
    *,
    approval_id: str,
    signed_transaction_base64: str,
    idempotency_token: str,
    portfolio_risk_permit_id: str | None = None,
    preproduction_release_approval_id: str | None = None,
    confirmation: str = "",
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    submitted_at: datetime | None = None,
    rpc_client: SolanaRpcClient | None = None,
) -> dict[str, Any]:
    if not bool(
        getattr(
            settings_object,
            "CANONICAL_PARSER_CONTROLLED_LIVE_SUBMISSION_ENABLED",
            False,
        )
    ):
        raise CanonicalParserControlledLiveSubmissionError(
            "M38 è disabilitata.", code="M38_DISABLED", status_code=409
        )
    if not bool(
        getattr(
            settings_object,
            "CANONICAL_PARSER_CONTROLLED_LIVE_SEND_RPC_ENABLED",
            False,
        )
    ):
        raise CanonicalParserControlledLiveSubmissionError(
            "Invio RPC M38 disabilitato.", code="M38_SEND_RPC_DISABLED", status_code=409
        )
    now = _aware(submitted_at)
    preview = _preview(
        db,
        approval_id=approval_id,
        signed_transaction_base64=signed_transaction_base64,
        idempotency_token=idempotency_token,
        portfolio_risk_permit_id=portfolio_risk_permit_id,
        preproduction_release_approval_id=preproduction_release_approval_id,
        settings_object=settings_object,
        evaluated_at=now,
    )
    if preview["existing_submission"] is not None:
        return preview["existing_submission"]
    if preview["status"] != "READY":
        raise CanonicalParserControlledLiveSubmissionError(
            "Submission M38 bloccata dai controlli.",
            code="M38_SUBMISSION_BLOCKED",
            status_code=409,
        )
    if confirmation != preview["confirmation"]:
        raise CanonicalParserControlledLiveSubmissionError(
            "Conferma M38 non valida.", code="M38_CONFIRMATION_REQUIRED", status_code=409
        )
    assert preview["dry_run"] is not None
    row = CanonicalParserControlledLiveSubmission(
        submission_id=str(uuid4()),
        submission_key=preview["submission_key"],
        scope="M38_MANUAL_CONTROLLED_LIVE_SUBMISSION",
        approval_db_id=preview["approval"].id,
        approval_id=preview["approval"].approval_id,
        dry_run_id=preview["approval"].dry_run_id,
        micro_live_permit_id=preview["approval"].micro_live_permit_id,
        status="RESERVED",
        side=preview["dry_run"].side,
        token_mint=preview["dry_run"].token_mint,
        reserved_budget_sol=_decimal(preview["dry_run"].requested_budget_sol),
        signed_transaction_hash=preview["signed"]["signed_transaction_hash"],
        expected_signature=preview["signed"]["expected_signature"],
        rpc_signature=None,
        send_attempted=False,
        confirmation_status=None,
        confirmation_slot=None,
        chain_error=None,
        reason_codes=[],
        reservation_snapshot=preview["reservation"],
        submission_snapshot={
            "rpc_send_enabled": True,
            "automatic_retry": False,
            "raw_signed_transaction_persisted": False,
            "portfolio_risk_permit_id": portfolio_risk_permit_id,
            "preproduction_release_approval_id": preproduction_release_approval_id,
            "incident_guard": preview["incident_guard"],
            "preproduction_release": preview["preproduction_release"]["snapshot"],
        },
        evidence_hash=preview["evidence_hash"],
        actor_label=_actor(actor_label),
        note=_note(note),
        reserved_at=now,
        submitted_at=None,
        reconciled_at=None,
        confirmed_at=None,
        finalized_at=None,
    )
    db.add(row)
    db.flush()
    _add_event(
        db,
        row,
        event_type="RESERVED",
        payload={"reservation": preview["reservation"]},
        occurred_at=now,
    )
    if preview["portfolio_risk"]["required"]:
        from backend.app.services.blockchain_parser_live_portfolio_risk_service import consume_portfolio_risk_permit
        consume_portfolio_risk_permit(
            db,
            permit_id=str(portfolio_risk_permit_id),
            submission_id=row.submission_id,
            side=row.side,
            token_mint=row.token_mint,
            requested_budget_sol=row.reserved_budget_sol,
            wallet_address=None if preview["signer_profile"] is None else preview["signer_profile"].wallet_address,
            settings_object=settings_object,
            consumed_at=now,
        )
    if preview["preproduction_release"]["required"]:
        from backend.app.services.blockchain_parser_preproduction_certification_service import consume_preproduction_release_approval
        consume_preproduction_release_approval(
            db,
            release_id=str(preproduction_release_approval_id),
            submission_id=row.submission_id,
            side=row.side,
            token_mint=row.token_mint,
            requested_budget_sol=row.reserved_budget_sol,
            wallet_address=None if preview["signer_profile"] is None else preview["signer_profile"].wallet_address,
            settings_object=settings_object,
            consumed_at=now,
        )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.scalar(
            select(CanonicalParserControlledLiveSubmission).where(
                CanonicalParserControlledLiveSubmission.submission_key
                == preview["submission_key"]
            )
        )
        if duplicate is not None:
            return _serialize(duplicate)
        raise CanonicalParserControlledLiveSubmissionError(
            "Conflitto reservation M38.",
            code="M38_RESERVATION_CONFLICT",
            status_code=409,
        ) from exc
    db.refresh(row)
    row.send_attempted = True
    try:
        rpc_signature = (rpc_client or SolanaRpcClient()).send_signed_transaction_base64(
            signed_transaction_base64
        )
        row.rpc_signature = str(rpc_signature)
        row.submitted_at = now
        if row.rpc_signature != row.expected_signature:
            row.status = "RECONCILIATION_REQUIRED"
            row.reason_codes = ["RPC_SIGNATURE_MISMATCH"]
            _add_event(
                db,
                row,
                event_type="UNCERTAIN",
                payload={
                    "expected_signature": row.expected_signature,
                    "rpc_signature": row.rpc_signature,
                },
                occurred_at=now,
            )
        else:
            row.status = "SUBMITTED"
            _add_event(
                db,
                row,
                event_type="SUBMITTED",
                payload={"rpc_signature": row.rpc_signature},
                occurred_at=now,
            )
    except Exception as exc:
        # The network outcome may be unknown after an RPC transport failure.
        # Reservation is intentionally retained until explicit reconciliation.
        row.status = "RECONCILIATION_REQUIRED"
        row.rpc_signature = row.expected_signature
        row.reason_codes = ["RPC_SUBMISSION_OUTCOME_UNCERTAIN"]
        row.chain_error = {
            "message": sanitize_error_message(exc, max_length=500)
        }
        _add_event(
            db,
            row,
            event_type="UNCERTAIN",
            payload={"reason": "RPC_SUBMISSION_OUTCOME_UNCERTAIN"},
            occurred_at=now,
        )
    db.commit()
    db.refresh(row)
    return _serialize(row)


def reconcile_controlled_live_submission(
    db: Session,
    *,
    submission_id: str,
    confirmation: str,
    actor_label: str | None = None,
    settings_object: Any = settings,
    reconciled_at: datetime | None = None,
    rpc_client: SolanaRpcClient | None = None,
) -> dict[str, Any]:
    if not bool(
        getattr(
            settings_object,
            "CANONICAL_PARSER_CONTROLLED_LIVE_RECONCILIATION_ENABLED",
            False,
        )
    ):
        raise CanonicalParserControlledLiveSubmissionError(
            "Riconciliazione M38 disabilitata.",
            code="M38_RECONCILIATION_DISABLED",
            status_code=409,
        )
    now = _aware(reconciled_at)
    row = db.scalar(
        select(CanonicalParserControlledLiveSubmission)
        .where(CanonicalParserControlledLiveSubmission.submission_id == submission_id)
        .with_for_update()
    )
    if row is None:
        raise CanonicalParserControlledLiveSubmissionError(
            "Submission M38 non trovata.",
            code="M38_SUBMISSION_NOT_FOUND",
            status_code=404,
        )
    expected = f"{RECONCILE_PREFIX}:{row.submission_id}:{row.expected_signature}"
    if confirmation != expected:
        raise CanonicalParserControlledLiveSubmissionError(
            "Conferma reconcile M38 non valida.",
            code="M38_RECONCILE_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    signature = row.rpc_signature or row.expected_signature
    try:
        status = (rpc_client or SolanaRpcClient()).get_signature_status(signature)
    except Exception as exc:
        row.status = "RECONCILIATION_REQUIRED"
        row.reason_codes = sorted(
            set(list(row.reason_codes or []) + ["RPC_RECONCILIATION_UNAVAILABLE"])
        )
        row.chain_error = {"message": sanitize_error_message(exc, max_length=500)}
        row.reconciled_at = now
        _add_event(
            db,
            row,
            event_type="UNCERTAIN",
            payload={"reason": "RPC_RECONCILIATION_UNAVAILABLE"},
            occurred_at=now,
        )
        db.commit()
        db.refresh(row)
        return _serialize(row)
    row.reconciled_at = now
    row.confirmation_status = status.get("confirmation_status")
    row.confirmation_slot = status.get("slot")
    row.chain_error = status.get("error")
    if not status.get("found"):
        row.status = "RECONCILIATION_REQUIRED"
        row.reason_codes = sorted(
            set(list(row.reason_codes or []) + ["SIGNATURE_NOT_FOUND"])
        )
        event_type = "UNCERTAIN"
    elif status.get("error") is not None:
        row.status = "FAILED"
        row.reason_codes = sorted(
            set(list(row.reason_codes or []) + ["ON_CHAIN_TRANSACTION_FAILED"])
        )
        event_type = "FAILED"
    elif status.get("confirmation_status") == "finalized":
        row.status = "FINALIZED"
        row.confirmed_at = row.confirmed_at or now
        row.finalized_at = now
        event_type = "FINALIZED"
    elif status.get("confirmation_status") == "confirmed":
        row.status = "CONFIRMED"
        row.confirmed_at = now
        event_type = "CONFIRMED"
    else:
        row.status = "PROCESSED"
        event_type = "RECONCILED"
    _add_event(
        db,
        row,
        event_type=event_type,
        payload={
            "rpc_signature": signature,
            "confirmation_status": row.confirmation_status,
            "slot": row.confirmation_slot,
            "chain_error": row.chain_error,
            "actor_label": _actor(actor_label),
        },
        occurred_at=now,
    )
    db.commit()
    db.refresh(row)
    return _serialize(row)


def get_controlled_live_submission(db: Session, submission_id: str) -> dict[str, Any]:
    row = db.scalar(
        select(CanonicalParserControlledLiveSubmission).where(
            CanonicalParserControlledLiveSubmission.submission_id == submission_id
        )
    )
    if row is None:
        raise CanonicalParserControlledLiveSubmissionError(
            "Submission M38 non trovata.",
            code="M38_SUBMISSION_NOT_FOUND",
            status_code=404,
        )
    result = _serialize(row)
    result["events"] = [
        {
            "sequence": event.sequence,
            "event_type": event.event_type,
            "event_hash": event.event_hash,
            "previous_event_hash": event.previous_event_hash,
            "event_payload": event.event_payload,
            "occurred_at": event.occurred_at,
        }
        for event in db.scalars(
            select(CanonicalParserControlledLiveSubmissionEvent)
            .where(CanonicalParserControlledLiveSubmissionEvent.submission_db_id == row.id)
            .order_by(CanonicalParserControlledLiveSubmissionEvent.sequence.asc())
        )
    ]
    return result


def resolve_controlled_live_submission(db: Session) -> dict[str, Any]:
    row = db.scalar(
        select(CanonicalParserControlledLiveSubmission)
        .order_by(CanonicalParserControlledLiveSubmission.created_at.desc())
        .limit(1)
    )
    return {
        "latest_submission": None if row is None else _serialize(row),
        "resolved_status": "EMPTY" if row is None else row.status,
    }


def get_controlled_live_submission_status(
    db: Session, *, settings_object: Any = settings
) -> dict[str, Any]:
    return {
        "enabled": bool(
            getattr(
                settings_object,
                "CANONICAL_PARSER_CONTROLLED_LIVE_SUBMISSION_ENABLED",
                False,
            )
        ),
        "submission_count": int(
            db.scalar(select(func.count(CanonicalParserControlledLiveSubmission.id)))
            or 0
        ),
        "reconciliation_required_count": int(
            db.scalar(
                select(func.count(CanonicalParserControlledLiveSubmission.id)).where(
                    CanonicalParserControlledLiveSubmission.status
                    == "RECONCILIATION_REQUIRED"
                )
            )
            or 0
        ),
        "policy": _policy(settings_object),
        "safety": {
            "manual_only": True,
            "legacy_live_engine_disabled": True,
            "legacy_kill_switch_engaged": True,
            "automatic_retry": False,
            "raw_signed_transaction_persisted": False,
            "worker_connected": False,
            "scheduler_connected": False,
            "stream_connected": False,
        },
    }
