from __future__ import annotations

import base64
import binascii
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserExternalSigningApproval,
    CanonicalParserExternalSigningApprovalEvent,
    CanonicalParserIsolatedSignerProfile,
    CanonicalParserLiveTransactionDryRun,
)
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    sanitize_error_message,
)
from backend.app.services.blockchain_parser_live_transaction_dry_run_service import (
    _base58_decode,
    _base58_encode,
    _read_shortvec,
    inspect_unsigned_solana_transaction,
)
from backend.app.services.solana_rpc import SolanaRpcClient

EXTERNAL_SIGNING_APPROVAL_POLICY_VERSION = (
    "canonical-parser-external-signing-approval/1"
)
APPROVAL_PREFIX = "APPROVE_M37_EXTERNAL_SIGNATURE"
REVOKE_PREFIX = "REVOKE_M37_EXTERNAL_SIGNATURE"


class CanonicalParserExternalSigningApprovalError(ValueError):
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
    return str(value or "MANUAL_OPERATOR").strip()[:80] or "MANUAL_OPERATOR"


def _note(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized[:500] if normalized else None


def _policy(settings_object: Any = settings) -> dict[str, Any]:
    return {
        "version": EXTERNAL_SIGNING_APPROVAL_POLICY_VERSION,
        "approval_ttl_seconds": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_EXTERNAL_SIGNING_APPROVAL_TTL_SECONDS",
                60,
            )
        ),
        "signed_rpc_simulation_enabled": bool(
            getattr(
                settings_object,
                "CANONICAL_PARSER_EXTERNAL_SIGNING_RPC_ENABLED",
                False,
            )
        ),
        "raw_signed_transaction_persisted": False,
        "credential_material_permitted": False,
        "submission_permitted": False,
    }


def _decode_signed_transaction(transaction_base64: str) -> dict[str, Any]:
    try:
        raw = base64.b64decode(transaction_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise CanonicalParserExternalSigningApprovalError(
            "Transazione firmata M37 non valida in base64.",
            code="M37_TRANSACTION_BASE64_INVALID",
        ) from exc
    if not raw:
        raise CanonicalParserExternalSigningApprovalError(
            "Transazione firmata M37 vuota.", code="M37_TRANSACTION_EMPTY"
        )
    try:
        signature_count, cursor = _read_shortvec(raw, 0)
        signatures: list[bytes] = []
        for _ in range(signature_count):
            if cursor + 64 > len(raw):
                raise ValueError("signature truncated")
            signatures.append(raw[cursor : cursor + 64])
            cursor += 64
        message_bytes = raw[cursor:]
        if not message_bytes:
            raise ValueError("message missing")
        inspection = inspect_unsigned_solana_transaction(transaction_base64)
    except CanonicalParserExternalSigningApprovalError:
        raise
    except Exception as exc:
        raise CanonicalParserExternalSigningApprovalError(
            "Transazione firmata M37 non interpretabile.",
            code="M37_TRANSACTION_INVALID",
        ) from exc
    if signature_count != inspection["required_signer_count"]:
        raise CanonicalParserExternalSigningApprovalError(
            "Numero firme M37 non coerente con il messaggio.",
            code="M37_SIGNATURE_COUNT_MISMATCH",
        )
    if any(signature == b"\x00" * 64 for signature in signatures):
        raise CanonicalParserExternalSigningApprovalError(
            "La transazione M37 non è completamente firmata.",
            code="M37_SIGNATURE_MISSING",
        )
    return {
        "raw": raw,
        "message_bytes": message_bytes,
        "signatures": signatures,
        "signature_strings": [_base58_encode(item) for item in signatures],
        "inspection": inspection,
        "signed_transaction_hash": hashlib.sha256(raw).hexdigest(),
        "message_hash": hashlib.sha256(message_bytes).hexdigest(),
        "expected_signature": _base58_encode(signatures[0]),
    }


def _verify_signature(public_key: str, signature: bytes, message: bytes) -> bool:
    try:
        from solders.pubkey import Pubkey
        from solders.signature import Signature

        return bool(
            Signature.from_bytes(signature).verify(
                Pubkey.from_bytes(_base58_decode(public_key)), message
            )
        )
    except Exception:
        return False


def inspect_and_verify_signed_transaction(transaction_base64: str) -> dict[str, Any]:
    decoded = _decode_signed_transaction(transaction_base64)
    signers = list(decoded["inspection"]["required_signers"])
    verified: list[str] = []
    failed: list[str] = []
    for public_key, signature in zip(signers, decoded["signatures"], strict=True):
        if _verify_signature(public_key, signature, decoded["message_bytes"]):
            verified.append(public_key)
        else:
            failed.append(public_key)
    return {
        "inspection": decoded["inspection"],
        "signed_transaction_hash": decoded["signed_transaction_hash"],
        "message_hash": decoded["message_hash"],
        "expected_signature": decoded["expected_signature"],
        "signature_strings": decoded["signature_strings"],
        "verified_signers": verified,
        "failed_signers": failed,
        "all_signatures_valid": not failed and len(verified) == len(signers),
    }


def _serialize(row: CanonicalParserExternalSigningApproval, *, now: datetime | None = None) -> dict[str, Any]:
    current = _aware(now)
    resolved = row.status
    if row.status in {"READY", "REVIEW"} and _aware(row.expires_at) <= current:
        resolved = "EXPIRED"
    return {
        "approval_id": row.approval_id,
        "approval_key": row.approval_key,
        "scope": row.scope,
        "status": row.status,
        "resolved_status": resolved,
        "dry_run_id": row.dry_run_id,
        "signer_profile_id": row.signer_profile_id,
        "micro_live_permit_id": row.micro_live_permit_id,
        "signed_transaction_hash": row.signed_transaction_hash,
        "message_hash": row.message_hash,
        "expected_signature": row.expected_signature,
        "verified_signers": row.verified_signers,
        "signature_count": row.signature_count,
        "signature_verification_status": row.signature_verification_status,
        "rpc_simulation_status": row.rpc_simulation_status,
        "units_consumed": row.units_consumed,
        "reason_codes": row.reason_codes,
        "verification_snapshot": row.verification_snapshot,
        "rpc_simulation_snapshot": row.rpc_simulation_snapshot,
        "approval_envelope": row.approval_envelope,
        "approval_envelope_hash": row.approval_envelope_hash,
        "evidence_hash": row.evidence_hash,
        "actor_label": row.actor_label,
        "note": row.note,
        "verified_at": row.verified_at,
        "expires_at": row.expires_at,
        "revoked_at": row.revoked_at,
        "revocation_reason": row.revocation_reason,
        "raw_signed_transaction_persisted": False,
    }


def _preview(
    db: Session,
    *,
    dry_run_id: str,
    signed_transaction_base64: str,
    idempotency_token: str,
    settings_object: Any,
    evaluated_at: datetime,
) -> dict[str, Any]:
    if len(str(idempotency_token or "").strip()) < 8:
        raise CanonicalParserExternalSigningApprovalError(
            "Idempotency token M37 non valido.", code="M37_IDEMPOTENCY_INVALID"
        )
    dry_run = db.scalar(
        select(CanonicalParserLiveTransactionDryRun).where(
            CanonicalParserLiveTransactionDryRun.dry_run_id == dry_run_id
        )
    )
    if dry_run is None:
        raise CanonicalParserExternalSigningApprovalError(
            "Dry-run M36 non trovato.", code="M37_DRY_RUN_NOT_FOUND", status_code=404
        )
    profile = db.scalar(
        select(CanonicalParserIsolatedSignerProfile).where(
            CanonicalParserIsolatedSignerProfile.id == dry_run.signer_profile_db_id
        )
    )
    reasons: list[str] = []
    if dry_run.status != "READY":
        reasons.append("M36_DRY_RUN_NOT_READY")
    if _aware(dry_run.envelope_expires_at) <= evaluated_at:
        reasons.append("M36_SIGNING_ENVELOPE_EXPIRED")
    if profile is None:
        reasons.append("M36_SIGNER_PROFILE_MISSING")
    else:
        if profile.status != "ACTIVE":
            reasons.append("M36_SIGNER_PROFILE_NOT_ACTIVE")
        if _aware(profile.expires_at) <= evaluated_at:
            reasons.append("M36_SIGNER_PROFILE_EXPIRED")
    signed = inspect_and_verify_signed_transaction(signed_transaction_base64)
    inspection = signed["inspection"]
    if signed["message_hash"] != dry_run.message_hash:
        reasons.append("SIGNED_MESSAGE_HASH_DRIFT")
    if inspection["account_keys_hash"] != dry_run.account_keys_hash:
        reasons.append("SIGNED_ACCOUNT_KEYS_DRIFT")
    if sorted(inspection["program_ids"]) != sorted(dry_run.program_ids or []):
        reasons.append("SIGNED_PROGRAM_IDS_DRIFT")
    if inspection["required_signers"] != list(dry_run.required_signers or []):
        reasons.append("SIGNED_REQUIRED_SIGNERS_DRIFT")
    if not signed["all_signatures_valid"]:
        reasons.append("SIGNATURE_VERIFICATION_FAILED")
    if profile is not None and profile.wallet_address not in signed["verified_signers"]:
        reasons.append("EXPECTED_SIGNER_NOT_VERIFIED")
    policy = _policy(settings_object)
    approval_key = calculate_payload_hash(
        {
            "dry_run_id": dry_run.dry_run_id,
            "signing_envelope_hash": dry_run.signing_envelope_hash,
            "signed_transaction_hash": signed["signed_transaction_hash"],
            "idempotency_token": str(idempotency_token).strip(),
            "policy": policy,
        }
    )
    existing = db.scalar(
        select(CanonicalParserExternalSigningApproval).where(
            CanonicalParserExternalSigningApproval.approval_key == approval_key
        )
    )
    structural_status = "READY" if not reasons else "BLOCKED"
    evidence = {
        "dry_run_id": dry_run.dry_run_id,
        "dry_run_evidence_hash": dry_run.evidence_hash,
        "signing_envelope_hash": dry_run.signing_envelope_hash,
        "signed_transaction_hash": signed["signed_transaction_hash"],
        "message_hash": signed["message_hash"],
        "expected_signature": signed["expected_signature"],
        "verified_signers": signed["verified_signers"],
        "failed_signers": signed["failed_signers"],
        "inspection": inspection,
        "reason_codes": sorted(set(reasons)),
        "policy": policy,
    }
    return {
        "dry_run": dry_run,
        "profile": profile,
        "signed": signed,
        "approval_key": approval_key,
        "existing_approval": None if existing is None else _serialize(existing, now=evaluated_at),
        "status": structural_status,
        "reason_codes": sorted(set(reasons)),
        "policy": policy,
        "evidence": evidence,
        "evidence_hash": calculate_payload_hash(evidence),
        "confirmation": f"{APPROVAL_PREFIX}:{dry_run.dry_run_id}:{approval_key}",
    }


def preview_external_signing_approval(
    db: Session,
    *,
    dry_run_id: str,
    signed_transaction_base64: str,
    idempotency_token: str,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    preview = _preview(
        db,
        dry_run_id=dry_run_id,
        signed_transaction_base64=signed_transaction_base64,
        idempotency_token=idempotency_token,
        settings_object=settings_object,
        evaluated_at=_aware(evaluated_at),
    )
    return {
        "status": preview["status"],
        "ready": preview["status"] == "READY",
        "approval_key": preview["approval_key"],
        "existing_approval": preview["existing_approval"],
        "signed_transaction_hash": preview["signed"]["signed_transaction_hash"],
        "expected_signature": preview["signed"]["expected_signature"],
        "verified_signers": preview["signed"]["verified_signers"],
        "reason_codes": preview["reason_codes"],
        "evidence_hash": preview["evidence_hash"],
        "confirmation": preview["confirmation"],
        "policy": preview["policy"],
        "safety": {
            "private_key_loaded": False,
            "signature_created_by_backend": False,
            "raw_signed_transaction_persisted": False,
            "submission_authorized": False,
        },
    }


def _add_event(
    db: Session,
    approval: CanonicalParserExternalSigningApproval,
    *,
    event_type: str,
    payload: dict[str, Any],
    occurred_at: datetime,
) -> None:
    previous = db.scalar(
        select(CanonicalParserExternalSigningApprovalEvent)
        .where(CanonicalParserExternalSigningApprovalEvent.approval_db_id == approval.id)
        .order_by(CanonicalParserExternalSigningApprovalEvent.sequence.desc())
        .limit(1)
    )
    sequence = 1 if previous is None else previous.sequence + 1
    previous_hash = None if previous is None else previous.event_hash
    event_payload = {
        "approval_id": approval.approval_id,
        "sequence": sequence,
        "event_type": event_type,
        "occurred_at": occurred_at.isoformat(),
        "payload": payload,
        "previous_event_hash": previous_hash,
    }
    db.add(
        CanonicalParserExternalSigningApprovalEvent(
            event_id=str(uuid4()),
            approval_db_id=approval.id,
            sequence=sequence,
            event_type=event_type,
            event_payload=event_payload,
            previous_event_hash=previous_hash,
            event_hash=calculate_payload_hash(event_payload),
            occurred_at=occurred_at,
        )
    )


def approve_external_signed_transaction(
    db: Session,
    *,
    dry_run_id: str,
    signed_transaction_base64: str,
    idempotency_token: str,
    run_rpc_simulation: bool,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    verified_at: datetime | None = None,
    rpc_client: SolanaRpcClient | None = None,
) -> dict[str, Any]:
    if not bool(
        getattr(settings_object, "CANONICAL_PARSER_EXTERNAL_SIGNING_APPROVAL_ENABLED", False)
    ):
        raise CanonicalParserExternalSigningApprovalError(
            "M37 è disabilitata.", code="M37_DISABLED", status_code=409
        )
    now = _aware(verified_at)
    preview = _preview(
        db,
        dry_run_id=dry_run_id,
        signed_transaction_base64=signed_transaction_base64,
        idempotency_token=idempotency_token,
        settings_object=settings_object,
        evaluated_at=now,
    )
    if preview["existing_approval"] is not None:
        return preview["existing_approval"]
    if confirmation != preview["confirmation"]:
        raise CanonicalParserExternalSigningApprovalError(
            "Conferma M37 non valida.", code="M37_CONFIRMATION_REQUIRED", status_code=409
        )
    reasons = list(preview["reason_codes"])
    status = preview["status"]
    rpc_status = "SKIPPED"
    rpc_snapshot: dict[str, Any] = {
        "requested": bool(run_rpc_simulation),
        "enabled": preview["policy"]["signed_rpc_simulation_enabled"],
        "success": False,
        "error": None,
        "units_consumed": None,
        "logs": [],
    }
    if status == "READY":
        if not run_rpc_simulation:
            status = "REVIEW"
            reasons.append("SIGNED_RPC_SIMULATION_SKIPPED")
        elif not preview["policy"]["signed_rpc_simulation_enabled"]:
            status = "REVIEW"
            rpc_status = "UNAVAILABLE"
            reasons.append("SIGNED_RPC_SIMULATION_DISABLED")
        else:
            try:
                result = (rpc_client or SolanaRpcClient()).simulate_transaction_base64(
                    signed_transaction_base64
                )
                rpc_status = "PASSED"
                rpc_snapshot = {
                    "requested": True,
                    "enabled": True,
                    "success": True,
                    "error": None,
                    "units_consumed": result.get("units_consumed"),
                    "logs": list(result.get("logs") or [])[-20:],
                }
            except Exception as exc:
                status = "BLOCKED"
                rpc_status = "FAILED"
                reasons.append("SIGNED_RPC_SIMULATION_FAILED")
                rpc_snapshot = {
                    "requested": True,
                    "enabled": True,
                    "success": False,
                    "error": sanitize_error_message(exc, max_length=500),
                    "units_consumed": None,
                    "logs": [],
                }
    approval_id = str(uuid4())
    expires_at = min(
        _aware(preview["dry_run"].envelope_expires_at),
        now + timedelta(seconds=preview["policy"]["approval_ttl_seconds"]),
    )
    envelope = {
        "scope": "M37_VERIFIED_SIGNATURE_APPROVAL",
        "approval_id": approval_id,
        "dry_run_id": preview["dry_run"].dry_run_id,
        "micro_live_permit_id": preview["dry_run"].micro_live_permit_id,
        "signed_transaction_hash": preview["signed"]["signed_transaction_hash"],
        "message_hash": preview["signed"]["message_hash"],
        "expected_signature": preview["signed"]["expected_signature"],
        "status": status,
        "eligible_for_m38_submission": status == "READY",
        "submission_authorized_by_backend": False,
        "issued_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
    }
    envelope_hash = calculate_payload_hash(envelope)
    evidence = dict(preview["evidence"])
    evidence["rpc_simulation"] = rpc_snapshot
    evidence["approval_envelope_hash"] = envelope_hash
    evidence["final_status"] = status
    row = CanonicalParserExternalSigningApproval(
        approval_id=approval_id,
        approval_key=preview["approval_key"],
        scope="M37_EXTERNAL_SIGNING_APPROVAL_ONLY",
        status=status,
        dry_run_db_id=preview["dry_run"].id,
        dry_run_id=preview["dry_run"].dry_run_id,
        signer_profile_id=preview["dry_run"].signer_profile_id,
        micro_live_permit_id=preview["dry_run"].micro_live_permit_id,
        signed_transaction_hash=preview["signed"]["signed_transaction_hash"],
        message_hash=preview["signed"]["message_hash"],
        expected_signature=preview["signed"]["expected_signature"],
        verified_signers=preview["signed"]["verified_signers"],
        signature_count=len(preview["signed"]["signature_strings"]),
        signature_verification_status=(
            "PASSED" if preview["signed"]["all_signatures_valid"] else "FAILED"
        ),
        rpc_simulation_status=rpc_status,
        units_consumed=rpc_snapshot.get("units_consumed"),
        reason_codes=sorted(set(reasons)),
        verification_snapshot=preview["evidence"],
        rpc_simulation_snapshot=rpc_snapshot,
        approval_envelope=envelope,
        approval_envelope_hash=envelope_hash,
        evidence_hash=calculate_payload_hash(evidence),
        actor_label=_actor(actor_label),
        note=_note(note),
        verified_at=now,
        expires_at=expires_at,
        revoked_at=None,
        revocation_reason=None,
    )
    db.add(row)
    db.flush()
    _add_event(
        db,
        row,
        event_type="APPROVED",
        payload={"status": status, "evidence_hash": row.evidence_hash},
        occurred_at=now,
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.scalar(
            select(CanonicalParserExternalSigningApproval).where(
                CanonicalParserExternalSigningApproval.approval_key
                == preview["approval_key"]
            )
        )
        if duplicate is not None:
            return _serialize(duplicate)
        raise CanonicalParserExternalSigningApprovalError(
            "Conflitto approval M37.", code="M37_APPROVAL_CONFLICT", status_code=409
        ) from exc
    db.refresh(row)
    return _serialize(row)


def revoke_external_signing_approval(
    db: Session,
    *,
    approval_id: str,
    confirmation: str,
    reason: str,
    actor_label: str | None = None,
    revoked_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(revoked_at)
    row = db.scalar(
        select(CanonicalParserExternalSigningApproval)
        .where(CanonicalParserExternalSigningApproval.approval_id == approval_id)
        .with_for_update()
    )
    if row is None:
        raise CanonicalParserExternalSigningApprovalError(
            "Approval M37 non trovata.", code="M37_APPROVAL_NOT_FOUND", status_code=404
        )
    expected = f"{REVOKE_PREFIX}:{row.approval_id}:{row.approval_envelope_hash}"
    if confirmation != expected:
        raise CanonicalParserExternalSigningApprovalError(
            "Conferma revoca M37 non valida.",
            code="M37_REVOKE_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if row.status == "REVOKED":
        return _serialize(row, now=now)
    row.status = "REVOKED"
    row.revoked_at = now
    row.revocation_reason = str(reason).strip()[:500]
    _add_event(
        db,
        row,
        event_type="REVOKED",
        payload={"reason": row.revocation_reason, "actor_label": _actor(actor_label)},
        occurred_at=now,
    )
    db.commit()
    db.refresh(row)
    return _serialize(row, now=now)


def get_external_signing_approval(db: Session, approval_id: str) -> dict[str, Any]:
    row = db.scalar(
        select(CanonicalParserExternalSigningApproval).where(
            CanonicalParserExternalSigningApproval.approval_id == approval_id
        )
    )
    if row is None:
        raise CanonicalParserExternalSigningApprovalError(
            "Approval M37 non trovata.", code="M37_APPROVAL_NOT_FOUND", status_code=404
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
            select(CanonicalParserExternalSigningApprovalEvent)
            .where(CanonicalParserExternalSigningApprovalEvent.approval_db_id == row.id)
            .order_by(CanonicalParserExternalSigningApprovalEvent.sequence.asc())
        )
    ]
    return result


def resolve_external_signing_approval(db: Session) -> dict[str, Any]:
    row = db.scalar(
        select(CanonicalParserExternalSigningApproval)
        .order_by(CanonicalParserExternalSigningApproval.created_at.desc())
        .limit(1)
    )
    return {
        "latest_approval": None if row is None else _serialize(row),
        "resolved_status": "EMPTY" if row is None else _serialize(row)["resolved_status"],
    }


def get_external_signing_approval_status(
    db: Session, *, settings_object: Any = settings
) -> dict[str, Any]:
    return {
        "enabled": bool(
            getattr(settings_object, "CANONICAL_PARSER_EXTERNAL_SIGNING_APPROVAL_ENABLED", False)
        ),
        "approval_count": int(
            db.scalar(select(func.count(CanonicalParserExternalSigningApproval.id))) or 0
        ),
        "policy": _policy(settings_object),
        "safety": {
            "external_signing_only": True,
            "private_key_loaded": False,
            "raw_signed_transaction_persisted": False,
            "transaction_submission_available": False,
            "worker_connected": False,
            "scheduler_connected": False,
            "stream_connected": False,
        },
    }
