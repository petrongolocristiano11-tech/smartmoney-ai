from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from importlib.metadata import PackageNotFoundError, version as package_version
from typing import Any
from uuid import uuid4

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserControlledLiveSubmission,
    CanonicalParserLiveIncident,
    CanonicalParserLiveObservabilitySnapshot,
    CanonicalParserLiveOperationalAlert,
    CanonicalParserPreproductionCertification,
    CanonicalParserPreproductionCertificationCheck,
    CanonicalParserPreproductionCertificationEvent,
    CanonicalParserPreproductionReleaseApproval,
    CanonicalParserPreproductionReleaseApprovalEvent,
)
from backend.app.services.blockchain_integrity_service import calculate_payload_hash

POLICY_VERSION = "canonical-parser-preproduction-certification/1"
CERTIFY_PREFIX = "CERTIFY_M44_PREPRODUCTION"
REVOKE_CERT_PREFIX = "REVOKE_M44_PREPRODUCTION_CERTIFICATION"
RELEASE_PREFIX = "ISSUE_M44_PREPRODUCTION_RELEASE"
REVOKE_RELEASE_PREFIX = "REVOKE_M44_PREPRODUCTION_RELEASE"
EXPECTED_ALEMBIC_HEAD = "a9d1e4f7b853"
_MONEY_QUANTUM = Decimal("0.000000001")
_ACTIVE_INCIDENT_STATUSES = {"OPEN", "ACKNOWLEDGED", "RECOVERY_AUTHORIZED"}
_ACTIVE_ALERT_STATUSES = {"OPEN", "ACKNOWLEDGED"}


class CanonicalParserPreproductionCertificationError(ValueError):
    def __init__(self, message: str, *, code: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _now(value: datetime | None = None) -> datetime:
    resolved = value or datetime.now(timezone.utc)
    if resolved.tzinfo is None:
        return resolved.replace(tzinfo=timezone.utc)
    return resolved.astimezone(timezone.utc)


def _actor(value: str | None) -> str:
    return str(value or "MANUAL_OPERATOR").strip()[:80] or "MANUAL_OPERATOR"


def _note(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    return normalized[:500] if normalized else None


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CanonicalParserPreproductionCertificationError(
            "Budget M44 non valido.", code="M44_INVALID_BUDGET"
        ) from exc
    if not result.is_finite() or result < 0:
        raise CanonicalParserPreproductionCertificationError(
            "Budget M44 non valido.", code="M44_INVALID_BUDGET"
        )
    return result.quantize(_MONEY_QUANTUM)


def _money(value: Any) -> str:
    return format(_decimal(value), "f")


def _policy(settings_object: Any = settings) -> dict[str, Any]:
    return {
        "version": POLICY_VERSION,
        "enabled": bool(getattr(settings_object, "CANONICAL_PARSER_PREPRODUCTION_CERTIFICATION_ENABLED", False)),
        "release_guard_enabled": bool(getattr(settings_object, "CANONICAL_PARSER_PREPRODUCTION_RELEASE_GUARD_ENABLED", False)),
        "certification_ttl_minutes": int(getattr(settings_object, "CANONICAL_PARSER_PREPRODUCTION_CERTIFICATION_TTL_MINUTES", 30)),
        "max_release_validity_minutes": int(getattr(settings_object, "CANONICAL_PARSER_PREPRODUCTION_MAX_RELEASE_VALIDITY_MINUTES", 10)),
        "minimum_full_test_count": int(getattr(settings_object, "CANONICAL_PARSER_PREPRODUCTION_MIN_FULL_TEST_COUNT", 1137)),
        "required_fastapi_version": str(getattr(settings_object, "CANONICAL_PARSER_PREPRODUCTION_REQUIRED_FASTAPI_VERSION", "0.138.2")),
        "expected_alembic_head": EXPECTED_ALEMBIC_HEAD,
        "require_healthy_observability": bool(getattr(settings_object, "CANONICAL_PARSER_PREPRODUCTION_REQUIRE_HEALTHY_OBSERVABILITY", True)),
        "require_zero_open_critical_alerts": bool(getattr(settings_object, "CANONICAL_PARSER_PREPRODUCTION_REQUIRE_ZERO_OPEN_CRITICAL_ALERTS", True)),
        "manual_only": True,
        "single_use_release": True,
        "automatic_deploy": False,
        "automatic_live_enablement": False,
    }


def _runtime_fastapi_version() -> str:
    try:
        return package_version("fastapi")
    except PackageNotFoundError:
        return "NOT_INSTALLED"


def _script_head() -> str | None:
    try:
        config = Config("alembic.ini")
        config.set_main_option("script_location", "alembic")
        heads = ScriptDirectory.from_config(config).get_heads()
        return heads[0] if len(heads) == 1 else None
    except Exception:
        return None


def _database_head(db: Session) -> str | None:
    try:
        bind = db.get_bind()
        if not inspect(bind).has_table("alembic_version"):
            return None
        return db.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).scalar_one_or_none()
    except Exception:
        return None


def _resolved_certification_status(row: CanonicalParserPreproductionCertification, now: datetime) -> str:
    if row.status == "ACTIVE" and _now(row.expires_at) <= now:
        return "EXPIRED"
    return row.status


def _resolved_release_status(row: CanonicalParserPreproductionReleaseApproval, now: datetime) -> str:
    if row.status == "ACTIVE" and _now(row.expires_at) <= now:
        return "EXPIRED"
    return row.status


def _serialize_certification(row: CanonicalParserPreproductionCertification, *, now: datetime | None = None) -> dict[str, Any]:
    return {
        "certification_id": row.certification_id,
        "certification_key": row.certification_key,
        "scope": row.scope,
        "environment": row.environment,
        "status": row.status,
        "resolved_status": _resolved_certification_status(row, _now(now)),
        "observability_snapshot_id": row.observability_snapshot_id,
        "git_commit_sha": row.git_commit_sha,
        "alembic_head": row.alembic_head,
        "fastapi_version": row.fastapi_version,
        "clean_worktree_attested": row.clean_worktree_attested,
        "full_test_count": row.full_test_count,
        "full_test_failures": row.full_test_failures,
        "test_evidence_hash": row.test_evidence_hash,
        "check_summary": row.check_summary,
        "evidence_snapshot": row.evidence_snapshot,
        "evidence_hash": row.evidence_hash,
        "actor_label": row.actor_label,
        "note": row.note,
        "certified_at": row.certified_at,
        "expires_at": row.expires_at,
        "revoked_at": row.revoked_at,
        "latest_event_sequence": row.latest_event_sequence,
        "latest_event_hash": row.latest_event_hash,
    }


def _serialize_release(row: CanonicalParserPreproductionReleaseApproval, *, now: datetime | None = None) -> dict[str, Any]:
    return {
        "release_id": row.release_id,
        "release_key": row.release_key,
        "scope": row.scope,
        "certification_id": row.certification_id,
        "wallet_address": row.wallet_address,
        "network": row.network,
        "side": row.side,
        "token_mint": row.token_mint,
        "max_budget_sol": _money(row.max_budget_sol),
        "status": row.status,
        "resolved_status": _resolved_release_status(row, _now(now)),
        "approval_snapshot": row.approval_snapshot,
        "evidence_hash": row.evidence_hash,
        "actor_label": row.actor_label,
        "note": row.note,
        "issued_at": row.issued_at,
        "expires_at": row.expires_at,
        "revoked_at": row.revoked_at,
        "consumed_at": row.consumed_at,
        "consumed_submission_id": row.consumed_submission_id,
        "latest_event_sequence": row.latest_event_sequence,
        "latest_event_hash": row.latest_event_hash,
    }


def _append_certification_event(
    db: Session,
    row: CanonicalParserPreproductionCertification,
    *,
    event_type: str,
    payload: dict[str, Any],
    at: datetime,
) -> None:
    sequence = int(row.latest_event_sequence or 0) + 1
    previous_hash = row.latest_event_hash if row.latest_event_sequence else None
    body = {
        "certification_id": row.certification_id,
        "sequence": sequence,
        "event_type": event_type,
        "occurred_at": at.isoformat(),
        "payload": payload,
        "previous_event_hash": previous_hash,
    }
    event_hash = calculate_payload_hash(body)
    db.add(
        CanonicalParserPreproductionCertificationEvent(
            event_id=str(uuid4()),
            certification_db_id=row.id,
            sequence=sequence,
            event_type=event_type,
            event_payload=body,
            previous_event_hash=previous_hash,
            event_hash=event_hash,
            occurred_at=at,
        )
    )
    row.latest_event_sequence = sequence
    row.latest_event_hash = event_hash


def _append_release_event(
    db: Session,
    row: CanonicalParserPreproductionReleaseApproval,
    *,
    event_type: str,
    payload: dict[str, Any],
    at: datetime,
) -> None:
    sequence = int(row.latest_event_sequence or 0) + 1
    previous_hash = row.latest_event_hash if row.latest_event_sequence else None
    body = {
        "release_id": row.release_id,
        "sequence": sequence,
        "event_type": event_type,
        "occurred_at": at.isoformat(),
        "payload": payload,
        "previous_event_hash": previous_hash,
    }
    event_hash = calculate_payload_hash(body)
    db.add(
        CanonicalParserPreproductionReleaseApprovalEvent(
            event_id=str(uuid4()),
            release_db_id=row.id,
            sequence=sequence,
            event_type=event_type,
            event_payload=body,
            previous_event_hash=previous_hash,
            event_hash=event_hash,
            occurred_at=at,
        )
    )
    row.latest_event_sequence = sequence
    row.latest_event_hash = event_hash


def _check(name: str, passed: bool, detail: dict[str, Any]) -> dict[str, Any]:
    return {"name": name, "status": "PASS" if passed else "FAIL", "detail": detail}


def preview_preproduction_certification(
    db: Session,
    *,
    observability_snapshot_id: str,
    git_commit_sha: str,
    clean_worktree_attested: bool,
    full_test_count: int,
    full_test_failures: int,
    test_evidence_hash: str,
    idempotency_token: str,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _now(evaluated_at)
    token = str(idempotency_token or "").strip()
    if len(token) < 8:
        raise CanonicalParserPreproductionCertificationError(
            "Idempotency token M44 non valido.", code="M44_IDEMPOTENCY_INVALID"
        )
    commit_sha = str(git_commit_sha or "").strip().lower()
    evidence_hash = str(test_evidence_hash or "").strip().lower()
    snapshot = db.scalar(
        select(CanonicalParserLiveObservabilitySnapshot).where(
            CanonicalParserLiveObservabilitySnapshot.snapshot_id == observability_snapshot_id
        )
    )
    if snapshot is None:
        raise CanonicalParserPreproductionCertificationError(
            "Snapshot osservabilità M43 non trovato.", code="M44_OBSERVABILITY_SNAPSHOT_NOT_FOUND", status_code=404
        )
    policy = _policy(settings_object)
    runtime_fastapi = _runtime_fastapi_version()
    script_head = _script_head()
    database_head = _database_head(db)
    open_critical_alert_count = len(
        list(
            db.scalars(
                select(CanonicalParserLiveOperationalAlert).where(
                    CanonicalParserLiveOperationalAlert.status.in_(sorted(_ACTIVE_ALERT_STATUSES)),
                    CanonicalParserLiveOperationalAlert.severity == "CRITICAL",
                )
            )
        )
    )
    active_freeze_incident_count = len(
        list(
            db.scalars(
                select(CanonicalParserLiveIncident).where(
                    CanonicalParserLiveIncident.status.in_(sorted(_ACTIVE_INCIDENT_STATUSES)),
                    CanonicalParserLiveIncident.freeze_new_submissions.is_(True),
                )
            )
        )
    )
    uncertain_submission_count = len(
        list(
            db.scalars(
                select(CanonicalParserControlledLiveSubmission).where(
                    CanonicalParserControlledLiveSubmission.status == "RECONCILIATION_REQUIRED"
                )
            )
        )
    )
    checks = [
        _check("GIT_COMMIT_SHA", bool(re.fullmatch(r"[0-9a-f]{40}", commit_sha)), {"git_commit_sha": commit_sha}),
        _check("CLEAN_WORKTREE_ATTESTATION", bool(clean_worktree_attested), {"clean_worktree_attested": bool(clean_worktree_attested)}),
        _check("FULL_TEST_SUITE", int(full_test_failures) == 0 and int(full_test_count) >= policy["minimum_full_test_count"], {"full_test_count": int(full_test_count), "full_test_failures": int(full_test_failures), "minimum": policy["minimum_full_test_count"]}),
        _check("TEST_EVIDENCE_HASH", bool(re.fullmatch(r"[0-9a-f]{64}", evidence_hash)), {"test_evidence_hash": evidence_hash}),
        _check("FASTAPI_RUNTIME", runtime_fastapi == policy["required_fastapi_version"], {"runtime": runtime_fastapi, "required": policy["required_fastapi_version"]}),
        _check("ALEMBIC_SCRIPT_HEAD", script_head == policy["expected_alembic_head"], {"script_head": script_head, "expected": policy["expected_alembic_head"]}),
        _check("ALEMBIC_DATABASE_HEAD", database_head == policy["expected_alembic_head"], {"database_head": database_head, "expected": policy["expected_alembic_head"]}),
        _check("M43_OBSERVABILITY_FRESH", _now(snapshot.expires_at) > now, {"snapshot_id": snapshot.snapshot_id, "expires_at": _now(snapshot.expires_at).isoformat()}),
        _check("M43_OBSERVABILITY_HEALTHY", (not policy["require_healthy_observability"]) or snapshot.status == "HEALTHY", {"status": snapshot.status, "required": policy["require_healthy_observability"]}),
        _check("M43_ZERO_CRITICAL_ALERTS", (not policy["require_zero_open_critical_alerts"]) or open_critical_alert_count == 0, {"open_critical_alert_count": open_critical_alert_count, "required": policy["require_zero_open_critical_alerts"]}),
        _check("M41_NO_ACTIVE_FREEZE", active_freeze_incident_count == 0, {"active_freeze_incident_count": active_freeze_incident_count}),
        _check("M38_NO_UNCERTAIN_SUBMISSIONS", uncertain_submission_count == 0, {"uncertain_submission_count": uncertain_submission_count}),
    ]
    failed = [item for item in checks if item["status"] == "FAIL"]
    certification_key = calculate_payload_hash(
        {
            "observability_snapshot_id": snapshot.snapshot_id,
            "git_commit_sha": commit_sha,
            "test_evidence_hash": evidence_hash,
            "idempotency_token": token,
            "policy": policy,
        }
    )
    existing = db.scalar(
        select(CanonicalParserPreproductionCertification).where(
            CanonicalParserPreproductionCertification.certification_key == certification_key
        )
    )
    evidence = {
        "certification_key": certification_key,
        "environment": "PREPRODUCTION",
        "observability_snapshot_id": snapshot.snapshot_id,
        "observability_evidence_hash": snapshot.evidence_hash,
        "git_commit_sha": commit_sha,
        "clean_worktree_attested": bool(clean_worktree_attested),
        "full_test_count": int(full_test_count),
        "full_test_failures": int(full_test_failures),
        "test_evidence_hash": evidence_hash,
        "runtime_fastapi": runtime_fastapi,
        "script_head": script_head,
        "database_head": database_head,
        "checks": checks,
        "policy": policy,
        "evaluated_at": now.isoformat(),
    }
    return {
        "status": "READY" if not failed else "BLOCKED",
        "ready": not failed,
        "certification_key": certification_key,
        "existing_certification": None if existing is None else _serialize_certification(existing, now=now),
        "checks": checks,
        "failed_checks": [item["name"] for item in failed],
        "reason_codes": [f"M44_{item['name']}_FAILED" for item in failed],
        "runtime": {"fastapi": runtime_fastapi, "script_head": script_head, "database_head": database_head},
        "policy": policy,
        "evidence": evidence,
        "evidence_hash": calculate_payload_hash(evidence),
        "confirmation": f"{CERTIFY_PREFIX}:{certification_key}",
        "safety": {
            "manual_only": True,
            "automatic_deploy": False,
            "automatic_live_enablement": False,
            "transaction_built": False,
            "transaction_signed": False,
            "transaction_sent": False,
        },
    }


def certify_preproduction_readiness(
    db: Session,
    *,
    observability_snapshot_id: str,
    git_commit_sha: str,
    clean_worktree_attested: bool,
    full_test_count: int,
    full_test_failures: int,
    test_evidence_hash: str,
    idempotency_token: str,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    certified_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_PREPRODUCTION_CERTIFICATION_ENABLED", False)):
        raise CanonicalParserPreproductionCertificationError(
            "M44 certificazione disabilitata.", code="M44_DISABLED", status_code=409
        )
    now = _now(certified_at)
    preview = preview_preproduction_certification(
        db,
        observability_snapshot_id=observability_snapshot_id,
        git_commit_sha=git_commit_sha,
        clean_worktree_attested=clean_worktree_attested,
        full_test_count=full_test_count,
        full_test_failures=full_test_failures,
        test_evidence_hash=test_evidence_hash,
        idempotency_token=idempotency_token,
        settings_object=settings_object,
        evaluated_at=now,
    )
    if preview["existing_certification"] is not None:
        return preview["existing_certification"]
    if preview["status"] != "READY":
        raise CanonicalParserPreproductionCertificationError(
            "Certificazione M44 bloccata.", code="M44_CERTIFICATION_BLOCKED", status_code=409
        )
    if confirmation != preview["confirmation"]:
        raise CanonicalParserPreproductionCertificationError(
            "Conferma certificazione M44 non valida.", code="M44_CERTIFICATION_CONFIRMATION_REQUIRED", status_code=409
        )
    snapshot = db.scalar(
        select(CanonicalParserLiveObservabilitySnapshot).where(
            CanonicalParserLiveObservabilitySnapshot.snapshot_id == observability_snapshot_id
        )
    )
    assert snapshot is not None
    certification_id = str(uuid4())
    initial_event_body = {
        "certification_id": certification_id,
        "sequence": 1,
        "event_type": "CERTIFIED",
        "occurred_at": now.isoformat(),
        "payload": {"evidence_hash": preview["evidence_hash"]},
        "previous_event_hash": None,
    }
    initial_event_hash = calculate_payload_hash(initial_event_body)
    row = CanonicalParserPreproductionCertification(
        certification_id=certification_id,
        certification_key=preview["certification_key"],
        scope="M44_PREPRODUCTION_CERTIFICATION",
        environment="PREPRODUCTION",
        status="ACTIVE",
        observability_snapshot_db_id=snapshot.id,
        observability_snapshot_id=snapshot.snapshot_id,
        git_commit_sha=str(git_commit_sha).strip().lower(),
        alembic_head=preview["runtime"]["database_head"],
        fastapi_version=preview["runtime"]["fastapi"],
        clean_worktree_attested=bool(clean_worktree_attested),
        full_test_count=int(full_test_count),
        full_test_failures=int(full_test_failures),
        test_evidence_hash=str(test_evidence_hash).strip().lower(),
        check_summary={"pass_count": len(preview["checks"]), "fail_count": 0},
        evidence_snapshot=preview["evidence"],
        evidence_hash=preview["evidence_hash"],
        actor_label=_actor(actor_label),
        note=_note(note),
        certified_at=now,
        expires_at=now + timedelta(minutes=preview["policy"]["certification_ttl_minutes"]),
        revoked_at=None,
        latest_event_sequence=1,
        latest_event_hash=initial_event_hash,
    )
    db.add(row)
    db.flush()
    db.add(
        CanonicalParserPreproductionCertificationEvent(
            event_id=str(uuid4()),
            certification_db_id=row.id,
            sequence=1,
            event_type="CERTIFIED",
            event_payload=initial_event_body,
            previous_event_hash=None,
            event_hash=initial_event_hash,
            occurred_at=now,
        )
    )
    for item in preview["checks"]:
        detail = {"name": item["name"], "status": item["status"], "detail": item["detail"], "checked_at": now.isoformat()}
        db.add(
            CanonicalParserPreproductionCertificationCheck(
                check_id=str(uuid4()),
                certification_db_id=row.id,
                check_name=item["name"],
                status=item["status"],
                check_detail=item["detail"],
                evidence_hash=calculate_payload_hash(detail),
                checked_at=now,
            )
        )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.scalar(
            select(CanonicalParserPreproductionCertification).where(
                CanonicalParserPreproductionCertification.certification_key == preview["certification_key"]
            )
        )
        if duplicate is not None:
            return _serialize_certification(duplicate, now=now)
        raise CanonicalParserPreproductionCertificationError(
            "Conflitto certificazione M44.", code="M44_CERTIFICATION_CONFLICT", status_code=409
        ) from exc
    db.refresh(row)
    return _serialize_certification(row, now=now)


def revoke_preproduction_certification(
    db: Session,
    *,
    certification_id: str,
    confirmation: str,
    reason: str,
    actor_label: str | None = None,
    settings_object: Any = settings,
    revoked_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_PREPRODUCTION_CERTIFICATION_ENABLED", False)):
        raise CanonicalParserPreproductionCertificationError(
            "M44 certificazione disabilitata.", code="M44_DISABLED", status_code=409
        )
    now = _now(revoked_at)
    row = db.scalar(
        select(CanonicalParserPreproductionCertification)
        .where(CanonicalParserPreproductionCertification.certification_id == certification_id)
        .with_for_update()
    )
    if row is None:
        raise CanonicalParserPreproductionCertificationError(
            "Certificazione M44 non trovata.", code="M44_CERTIFICATION_NOT_FOUND", status_code=404
        )
    if row.status == "REVOKED":
        return _serialize_certification(row, now=now)
    expected = f"{REVOKE_CERT_PREFIX}:{row.certification_id}:{row.evidence_hash}"
    if confirmation != expected:
        raise CanonicalParserPreproductionCertificationError(
            "Conferma revoca certificazione M44 non valida.", code="M44_CERTIFICATION_REVOKE_CONFIRMATION_REQUIRED", status_code=409
        )
    row.status = "REVOKED"
    row.revoked_at = now
    row.actor_label = _actor(actor_label)
    _append_certification_event(db, row, event_type="REVOKED", payload={"reason": str(reason)[:500]}, at=now)
    db.commit()
    db.refresh(row)
    return _serialize_certification(row, now=now)


def preview_preproduction_release_approval(
    db: Session,
    *,
    certification_id: str,
    wallet_address: str,
    side: str,
    token_mint: str,
    max_budget_sol: Any,
    validity_minutes: int,
    idempotency_token: str,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _now(evaluated_at)
    token = str(idempotency_token or "").strip()
    if len(token) < 8:
        raise CanonicalParserPreproductionCertificationError(
            "Idempotency token release M44 non valido.", code="M44_RELEASE_IDEMPOTENCY_INVALID"
        )
    policy = _policy(settings_object)
    certification = db.scalar(
        select(CanonicalParserPreproductionCertification).where(
            CanonicalParserPreproductionCertification.certification_id == certification_id
        )
    )
    if certification is None:
        raise CanonicalParserPreproductionCertificationError(
            "Certificazione M44 non trovata.", code="M44_CERTIFICATION_NOT_FOUND", status_code=404
        )
    resolved_side = str(side or "").strip().upper()
    budget = _decimal(max_budget_sol)
    reasons: list[str] = []
    if _resolved_certification_status(certification, now) != "ACTIVE":
        reasons.append("M44_CERTIFICATION_NOT_ACTIVE")
    if resolved_side not in {"BUY", "SELL"}:
        reasons.append("M44_RELEASE_SIDE_INVALID")
    if not (1 <= int(validity_minutes) <= policy["max_release_validity_minutes"]):
        reasons.append("M44_RELEASE_VALIDITY_INVALID")
    if len(str(wallet_address).strip()) < 32:
        reasons.append("M44_RELEASE_WALLET_INVALID")
    if len(str(token_mint).strip()) < 32:
        reasons.append("M44_RELEASE_TOKEN_INVALID")
    release_key = calculate_payload_hash(
        {
            "certification_id": certification.certification_id,
            "wallet_address": str(wallet_address).strip(),
            "network": "mainnet-beta",
            "side": resolved_side,
            "token_mint": str(token_mint).strip(),
            "max_budget_sol": _money(budget),
            "validity_minutes": int(validity_minutes),
            "idempotency_token": token,
        }
    )
    existing = db.scalar(
        select(CanonicalParserPreproductionReleaseApproval).where(
            CanonicalParserPreproductionReleaseApproval.release_key == release_key
        )
    )
    evidence = {
        "release_key": release_key,
        "certification_id": certification.certification_id,
        "certification_evidence_hash": certification.evidence_hash,
        "wallet_address": str(wallet_address).strip(),
        "network": "mainnet-beta",
        "side": resolved_side,
        "token_mint": str(token_mint).strip(),
        "max_budget_sol": _money(budget),
        "validity_minutes": int(validity_minutes),
        "policy": policy,
        "evaluated_at": now.isoformat(),
    }
    return {
        "status": "READY" if not reasons else "BLOCKED",
        "ready": not reasons,
        "release_key": release_key,
        "existing_release": None if existing is None else _serialize_release(existing, now=now),
        "certification": _serialize_certification(certification, now=now),
        "reason_codes": reasons,
        "evidence": evidence,
        "evidence_hash": calculate_payload_hash(evidence),
        "confirmation": f"{RELEASE_PREFIX}:{certification.certification_id}:{release_key}",
        "policy": policy,
    }


def issue_preproduction_release_approval(
    db: Session,
    *,
    certification_id: str,
    wallet_address: str,
    side: str,
    token_mint: str,
    max_budget_sol: Any,
    validity_minutes: int,
    idempotency_token: str,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    issued_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_PREPRODUCTION_CERTIFICATION_ENABLED", False)):
        raise CanonicalParserPreproductionCertificationError(
            "M44 certificazione disabilitata.", code="M44_DISABLED", status_code=409
        )
    now = _now(issued_at)
    preview = preview_preproduction_release_approval(
        db,
        certification_id=certification_id,
        wallet_address=wallet_address,
        side=side,
        token_mint=token_mint,
        max_budget_sol=max_budget_sol,
        validity_minutes=validity_minutes,
        idempotency_token=idempotency_token,
        settings_object=settings_object,
        evaluated_at=now,
    )
    if preview["existing_release"] is not None:
        return preview["existing_release"]
    if preview["status"] != "READY":
        raise CanonicalParserPreproductionCertificationError(
            "Release approval M44 bloccata.", code="M44_RELEASE_BLOCKED", status_code=409
        )
    if confirmation != preview["confirmation"]:
        raise CanonicalParserPreproductionCertificationError(
            "Conferma release M44 non valida.", code="M44_RELEASE_CONFIRMATION_REQUIRED", status_code=409
        )
    certification = db.scalar(
        select(CanonicalParserPreproductionCertification).where(
            CanonicalParserPreproductionCertification.certification_id == certification_id
        )
    )
    assert certification is not None
    release_id = str(uuid4())
    initial_event_body = {
        "release_id": release_id,
        "sequence": 1,
        "event_type": "ISSUED",
        "occurred_at": now.isoformat(),
        "payload": {"certification_id": certification.certification_id},
        "previous_event_hash": None,
    }
    initial_event_hash = calculate_payload_hash(initial_event_body)
    row = CanonicalParserPreproductionReleaseApproval(
        release_id=release_id,
        release_key=preview["release_key"],
        scope="M44_SINGLE_USE_PREPRODUCTION_RELEASE_APPROVAL",
        certification_db_id=certification.id,
        certification_id=certification.certification_id,
        wallet_address=str(wallet_address).strip(),
        network="mainnet-beta",
        side=str(side).strip().upper(),
        token_mint=str(token_mint).strip(),
        max_budget_sol=_decimal(max_budget_sol),
        status="ACTIVE",
        approval_snapshot=preview["evidence"],
        evidence_hash=preview["evidence_hash"],
        actor_label=_actor(actor_label),
        note=_note(note),
        issued_at=now,
        expires_at=now + timedelta(minutes=int(validity_minutes)),
        revoked_at=None,
        consumed_at=None,
        consumed_submission_id=None,
        latest_event_sequence=1,
        latest_event_hash=initial_event_hash,
    )
    db.add(row)
    db.flush()
    db.add(
        CanonicalParserPreproductionReleaseApprovalEvent(
            event_id=str(uuid4()),
            release_db_id=row.id,
            sequence=1,
            event_type="ISSUED",
            event_payload=initial_event_body,
            previous_event_hash=None,
            event_hash=initial_event_hash,
            occurred_at=now,
        )
    )
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.scalar(
            select(CanonicalParserPreproductionReleaseApproval).where(
                CanonicalParserPreproductionReleaseApproval.release_key == preview["release_key"]
            )
        )
        if duplicate is not None:
            return _serialize_release(duplicate, now=now)
        raise CanonicalParserPreproductionCertificationError(
            "Conflitto release M44.", code="M44_RELEASE_CONFLICT", status_code=409
        ) from exc
    db.refresh(row)
    return _serialize_release(row, now=now)


def revoke_preproduction_release_approval(
    db: Session,
    *,
    release_id: str,
    confirmation: str,
    reason: str,
    actor_label: str | None = None,
    settings_object: Any = settings,
    revoked_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_PREPRODUCTION_CERTIFICATION_ENABLED", False)):
        raise CanonicalParserPreproductionCertificationError(
            "M44 certificazione disabilitata.", code="M44_DISABLED", status_code=409
        )
    now = _now(revoked_at)
    row = db.scalar(
        select(CanonicalParserPreproductionReleaseApproval)
        .where(CanonicalParserPreproductionReleaseApproval.release_id == release_id)
        .with_for_update()
    )
    if row is None:
        raise CanonicalParserPreproductionCertificationError(
            "Release M44 non trovata.", code="M44_RELEASE_NOT_FOUND", status_code=404
        )
    if row.status == "REVOKED":
        return _serialize_release(row, now=now)
    if row.status != "ACTIVE":
        raise CanonicalParserPreproductionCertificationError(
            "Release M44 non attiva.", code="M44_RELEASE_NOT_ACTIVE", status_code=409
        )
    expected = f"{REVOKE_RELEASE_PREFIX}:{row.release_id}:{row.evidence_hash}"
    if confirmation != expected:
        raise CanonicalParserPreproductionCertificationError(
            "Conferma revoca release M44 non valida.", code="M44_RELEASE_REVOKE_CONFIRMATION_REQUIRED", status_code=409
        )
    row.status = "REVOKED"
    row.revoked_at = now
    row.actor_label = _actor(actor_label)
    _append_release_event(db, row, event_type="REVOKED", payload={"reason": str(reason)[:500]}, at=now)
    db.commit()
    db.refresh(row)
    return _serialize_release(row, now=now)


def validate_preproduction_release_for_submission(
    db: Session,
    *,
    release_id: str | None,
    wallet_address: str | None,
    side: str,
    token_mint: str,
    requested_budget_sol: Any,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _now(evaluated_at)
    policy = _policy(settings_object)
    if not policy["release_guard_enabled"]:
        return {
            "required": False,
            "ready": True,
            "reason_codes": [],
            "release": None,
            "snapshot": {"release_guard_enabled": False, "single_use": True},
        }
    reasons: list[str] = []
    row = None
    certification = None
    if not release_id:
        reasons.append("M44_PREPRODUCTION_RELEASE_REQUIRED")
    else:
        row = db.scalar(
            select(CanonicalParserPreproductionReleaseApproval).where(
                CanonicalParserPreproductionReleaseApproval.release_id == release_id
            )
        )
        if row is None:
            reasons.append("M44_PREPRODUCTION_RELEASE_NOT_FOUND")
        else:
            certification = db.scalar(
                select(CanonicalParserPreproductionCertification).where(
                    CanonicalParserPreproductionCertification.id == row.certification_db_id
                )
            )
            if _resolved_release_status(row, now) != "ACTIVE":
                reasons.append("M44_PREPRODUCTION_RELEASE_NOT_ACTIVE")
            if certification is None or _resolved_certification_status(certification, now) != "ACTIVE":
                reasons.append("M44_PREPRODUCTION_CERTIFICATION_NOT_ACTIVE")
            if wallet_address is None or row.wallet_address != wallet_address:
                reasons.append("M44_PREPRODUCTION_RELEASE_WALLET_MISMATCH")
            if row.side != str(side).upper():
                reasons.append("M44_PREPRODUCTION_RELEASE_SIDE_MISMATCH")
            if row.token_mint != str(token_mint):
                reasons.append("M44_PREPRODUCTION_RELEASE_TOKEN_MISMATCH")
            if _decimal(requested_budget_sol) > _decimal(row.max_budget_sol):
                reasons.append("M44_PREPRODUCTION_RELEASE_BUDGET_EXCEEDED")
    snapshot = {
        "release_guard_enabled": True,
        "release_id": release_id,
        "wallet_address": wallet_address,
        "side": str(side).upper(),
        "token_mint": str(token_mint),
        "requested_budget_sol": _money(requested_budget_sol),
        "resolved_release_status": None if row is None else _resolved_release_status(row, now),
        "resolved_certification_status": None if certification is None else _resolved_certification_status(certification, now),
        "single_use": True,
    }
    return {
        "required": True,
        "ready": not reasons,
        "reason_codes": reasons,
        "release": row,
        "snapshot": snapshot,
    }


def consume_preproduction_release_approval(
    db: Session,
    *,
    release_id: str,
    submission_id: str,
    wallet_address: str | None,
    side: str,
    token_mint: str,
    requested_budget_sol: Any,
    settings_object: Any = settings,
    consumed_at: datetime | None = None,
) -> dict[str, Any]:
    now = _now(consumed_at)
    validation = validate_preproduction_release_for_submission(
        db,
        release_id=release_id,
        wallet_address=wallet_address,
        side=side,
        token_mint=token_mint,
        requested_budget_sol=requested_budget_sol,
        settings_object=settings_object,
        evaluated_at=now,
    )
    if not validation["required"]:
        return {"consumed": False, "reason": "M44_RELEASE_GUARD_DISABLED"}
    if not validation["ready"]:
        raise CanonicalParserPreproductionCertificationError(
            "Release M44 non consumabile.", code="M44_RELEASE_CONSUME_BLOCKED", status_code=409
        )
    row = db.scalar(
        select(CanonicalParserPreproductionReleaseApproval)
        .where(CanonicalParserPreproductionReleaseApproval.release_id == release_id)
        .with_for_update()
    )
    assert row is not None
    if row.status != "ACTIVE":
        raise CanonicalParserPreproductionCertificationError(
            "Release M44 già utilizzata.", code="M44_RELEASE_ALREADY_USED", status_code=409
        )
    row.status = "CONSUMED"
    row.consumed_at = now
    row.consumed_submission_id = submission_id
    _append_release_event(db, row, event_type="CONSUMED", payload={"submission_id": submission_id}, at=now)
    return {"consumed": True, "release": _serialize_release(row, now=now)}


def get_preproduction_certification(db: Session, certification_id: str) -> dict[str, Any]:
    row = db.scalar(
        select(CanonicalParserPreproductionCertification).where(
            CanonicalParserPreproductionCertification.certification_id == certification_id
        )
    )
    if row is None:
        raise CanonicalParserPreproductionCertificationError(
            "Certificazione M44 non trovata.", code="M44_CERTIFICATION_NOT_FOUND", status_code=404
        )
    checks = list(
        db.scalars(
            select(CanonicalParserPreproductionCertificationCheck)
            .where(CanonicalParserPreproductionCertificationCheck.certification_db_id == row.id)
            .order_by(CanonicalParserPreproductionCertificationCheck.check_name.asc())
        )
    )
    result = _serialize_certification(row)
    result["checks"] = [
        {"check_id": item.check_id, "check_name": item.check_name, "status": item.status, "check_detail": item.check_detail, "evidence_hash": item.evidence_hash, "checked_at": item.checked_at}
        for item in checks
    ]
    return result


def get_preproduction_release_approval(db: Session, release_id: str) -> dict[str, Any]:
    row = db.scalar(
        select(CanonicalParserPreproductionReleaseApproval).where(
            CanonicalParserPreproductionReleaseApproval.release_id == release_id
        )
    )
    if row is None:
        raise CanonicalParserPreproductionCertificationError(
            "Release M44 non trovata.", code="M44_RELEASE_NOT_FOUND", status_code=404
        )
    return _serialize_release(row)


def get_preproduction_certification_status(
    db: Session, *, settings_object: Any = settings, evaluated_at: datetime | None = None
) -> dict[str, Any]:
    now = _now(evaluated_at)
    certifications = list(db.scalars(select(CanonicalParserPreproductionCertification)))
    releases = list(db.scalars(select(CanonicalParserPreproductionReleaseApproval)))
    active_certifications = [row for row in certifications if _resolved_certification_status(row, now) == "ACTIVE"]
    active_releases = [row for row in releases if _resolved_release_status(row, now) == "ACTIVE"]
    return {
        "milestone": "M44",
        "policy": _policy(settings_object),
        "runtime": {"fastapi": _runtime_fastapi_version(), "script_head": _script_head(), "database_head": _database_head(db)},
        "certification_count": len(certifications),
        "active_certification_count": len(active_certifications),
        "release_count": len(releases),
        "active_release_count": len(active_releases),
        "safety": {
            "manual_only": True,
            "single_use_release": True,
            "automatic_deploy": False,
            "automatic_live_enablement": False,
            "private_key_loaded": False,
            "transaction_built": False,
            "transaction_signed": False,
            "transaction_sent_by_m44": False,
        },
    }


def resolve_preproduction_certification(
    db: Session, *, settings_object: Any = settings, evaluated_at: datetime | None = None
) -> dict[str, Any]:
    status = get_preproduction_certification_status(db, settings_object=settings_object, evaluated_at=evaluated_at)
    if status["runtime"]["script_head"] != EXPECTED_ALEMBIC_HEAD or status["runtime"]["database_head"] != EXPECTED_ALEMBIC_HEAD:
        status["resolved_status"] = "SCHEMA_DRIFT"
    elif status["active_certification_count"] == 0:
        status["resolved_status"] = "NOT_CERTIFIED"
    else:
        status["resolved_status"] = "CERTIFIED"
    return status
