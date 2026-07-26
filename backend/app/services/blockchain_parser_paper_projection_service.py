from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserPaperProjectionResult,
    CanonicalParserPaperProjectionRun,
    CanonicalParserShadowReliabilityCertification,
    CanonicalParserShadowTicketExecutionResult,
    CanonicalParserShadowTicketExecutionRun,
)
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    sanitize_error_message,
    sanitize_technical_metadata,
)
from backend.app.services.blockchain_parser_shadow_reliability_certification_service import (
    resolve_shadow_reliability_certification,
)

PAPER_PROJECTION_POLICY_VERSION = "canonical-parser-paper-projection/1"
PAPER_PROJECTION_PREFIX = "RUN_PAPER_PROJECTION_DRY_RUN"
_MAX_ACTOR_LENGTH = 80
_MAX_NOTE_LENGTH = 500


class CanonicalParserPaperProjectionError(ValueError):
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
    return sanitize_error_message(value or "LOCAL_OPERATOR", max_length=_MAX_ACTOR_LENGTH) or "LOCAL_OPERATOR"


def _note(value: str | None) -> str | None:
    if not str(value or "").strip():
        return None
    return sanitize_error_message(value, max_length=_MAX_NOTE_LENGTH)


def _policy_snapshot(settings_object: Any) -> dict[str, Any]:
    return {
        "policy_version": PAPER_PROJECTION_POLICY_VERSION,
        "lookback_minutes": int(
            getattr(settings_object, "CANONICAL_PARSER_PAPER_PROJECTION_LOOKBACK_MINUTES", 1440)
        ),
        "maximum_source_runs": int(
            getattr(settings_object, "CANONICAL_PARSER_PAPER_PROJECTION_MAX_SOURCE_RUNS", 10)
        ),
        "maximum_artifacts": int(
            getattr(settings_object, "CANONICAL_PARSER_PAPER_PROJECTION_MAX_ARTIFACTS", 100)
        ),
        "minimum_projectable_results": int(
            getattr(settings_object, "CANONICAL_PARSER_PAPER_PROJECTION_MIN_PROJECTABLE_RESULTS", 1)
        ),
        "requires_certified_shadow_reliability": True,
        "requires_passed_shadow_execution_results": True,
        "canonical_swap_schema_only": True,
        "manual_projection_only": True,
        "writes_projection_tables_only": True,
        "paper_account_reads": False,
        "paper_account_writes": False,
        "paper_order_writes": False,
        "paper_position_writes": False,
        "trade_writes": False,
        "external_requests_allowed": False,
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
    }


def _project_artifact(artifact: Any) -> dict[str, Any]:
    reasons: set[str] = set()
    if not isinstance(artifact, dict):
        payload: dict[str, Any] = {}
        artifact_type = ""
        schema_version = ""
        artifact_hash = calculate_payload_hash({"invalid_artifact": str(type(artifact).__name__)})
        reasons.add("PAPER_PROJECTION_ARTIFACT_INVALID")
    else:
        artifact_type = str(artifact.get("artifact_type") or "").strip().upper()
        schema_version = str(artifact.get("schema_version") or "").strip()
        payload = artifact.get("payload") if isinstance(artifact.get("payload"), dict) else {}
        artifact_hash = str(artifact.get("payload_hash") or "").strip()
        if len(artifact_hash) != 64:
            artifact_hash = calculate_payload_hash(payload or {"artifact": artifact})
    if artifact_type != "CANONICAL_SWAP_EVENT":
        reasons.add("PAPER_PROJECTION_ARTIFACT_TYPE_UNSUPPORTED")
    if schema_version != "canonical-swap/1":
        reasons.add("PAPER_PROJECTION_SCHEMA_UNSUPPORTED")

    action = str(payload.get("side") or "UNKNOWN").strip().upper()
    if action not in {"BUY", "SELL"}:
        action = "UNKNOWN"
        reasons.add("PAPER_PROJECTION_SIDE_UNKNOWN")
    wallet = str(payload.get("wallet_address") or "").strip() or None
    token_mint = str(payload.get("token_mint") or "").strip() or None
    token_amount = str(payload.get("token_amount") or "").strip() or None
    sol_amount = str(payload.get("sol_amount") or "").strip() or None
    quality_status = str(payload.get("quality_status") or "").strip().upper()
    success = payload.get("success")
    if not wallet:
        reasons.add("PAPER_PROJECTION_WALLET_MISSING")
    if not token_mint:
        reasons.add("PAPER_PROJECTION_TOKEN_MINT_MISSING")
    if not token_amount:
        reasons.add("PAPER_PROJECTION_TOKEN_AMOUNT_MISSING")
    if not sol_amount:
        reasons.add("PAPER_PROJECTION_SOL_AMOUNT_MISSING")
    if success is not True:
        reasons.add("PAPER_PROJECTION_SOURCE_TRANSACTION_NOT_SUCCESSFUL")
    if quality_status == "FAIL":
        reasons.add("PAPER_PROJECTION_SOURCE_QUALITY_FAILED")

    hard = {
        "PAPER_PROJECTION_ARTIFACT_INVALID",
        "PAPER_PROJECTION_ARTIFACT_TYPE_UNSUPPORTED",
        "PAPER_PROJECTION_SCHEMA_UNSUPPORTED",
        "PAPER_PROJECTION_WALLET_MISSING",
        "PAPER_PROJECTION_TOKEN_MINT_MISSING",
        "PAPER_PROJECTION_SOURCE_TRANSACTION_NOT_SUCCESSFUL",
        "PAPER_PROJECTION_SOURCE_QUALITY_FAILED",
    }
    if reasons & hard:
        status = "REJECTED"
    elif reasons:
        status = "REVIEW"
    else:
        status = "PROJECTABLE"
    projection_payload = {
        "mode": "PAPER_PROJECTION_DRY_RUN",
        "action": action,
        "wallet_address": wallet,
        "token_mint": token_mint,
        "token_amount": token_amount,
        "sol_amount": sol_amount,
        "source_quality_status": quality_status or None,
        "source_success": success,
        "paper_account_id": None,
        "price_source": None,
        "estimated_fill": None,
        "paper_execution": False,
        "live_execution": False,
    }
    return {
        "status": status,
        "action": action,
        "wallet_address": wallet,
        "token_mint": token_mint,
        "token_amount": token_amount,
        "sol_amount": sol_amount,
        "artifact_hash": artifact_hash,
        "projection_hash": calculate_payload_hash(projection_payload),
        "projection_payload": projection_payload,
        "reason_codes": sorted(reasons),
    }


def _collect_sources(
    db: Session,
    *,
    settings_object: Any,
    evaluated_at: datetime,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    policy = _policy_snapshot(settings_object)
    cutoff = evaluated_at - timedelta(minutes=policy["lookback_minutes"])
    runs = list(
        db.scalars(
            select(CanonicalParserShadowTicketExecutionRun)
            .where(
                CanonicalParserShadowTicketExecutionRun.status.in_(["PASSED", "PARTIAL"]),
                CanonicalParserShadowTicketExecutionRun.completed_at.is_not(None),
                CanonicalParserShadowTicketExecutionRun.completed_at >= cutoff,
            )
            .order_by(CanonicalParserShadowTicketExecutionRun.completed_at.desc())
            .limit(policy["maximum_source_runs"])
        )
    )
    sources: list[dict[str, Any]] = []
    projections: list[dict[str, Any]] = []
    for run in reversed(runs):
        results = list(
            db.scalars(
                select(CanonicalParserShadowTicketExecutionResult)
                .where(
                    CanonicalParserShadowTicketExecutionResult.execution_run_db_id == run.id,
                    CanonicalParserShadowTicketExecutionResult.status == "PASS",
                )
                .order_by(CanonicalParserShadowTicketExecutionResult.raw_event_id.asc())
            )
        )
        source_run = {
            "run_db_id": run.id,
            "run_id": run.run_id,
            "run_key": run.run_key,
            "status": run.status,
            "parser_name": run.parser_name,
            "parser_version": run.parser_version,
            "output_schema_version": run.output_schema_version,
            "settlement_hash": run.settlement_hash,
            "completed_at": _aware(run.completed_at).isoformat() if run.completed_at else None,
            "results": [],
        }
        for result in results:
            result_payload = {
                "result_db_id": result.id,
                "result_id": result.result_id,
                "raw_event_id": result.raw_event_id,
                "output_hash": result.output_hash,
                "artifact_count": result.artifact_count,
            }
            source_run["results"].append(result_payload)
            for artifact_index, artifact in enumerate(result.shadow_artifacts or []):
                if len(projections) >= policy["maximum_artifacts"]:
                    break
                projection = _project_artifact(artifact)
                projection.update(
                    {
                        "source_execution_run_db_id": run.id,
                        "source_execution_run_id": run.run_id,
                        "source_result_db_id": result.id,
                        "source_result_id": result.result_id,
                        "raw_event_id": result.raw_event_id,
                        "artifact_index": artifact_index,
                    }
                )
                projections.append(projection)
            if len(projections) >= policy["maximum_artifacts"]:
                break
        sources.append(source_run)
        if len(projections) >= policy["maximum_artifacts"]:
            break
    return sources, projections


def preview_paper_projection(
    db: Session,
    *,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _policy_snapshot(settings_object)
    policy_hash = calculate_payload_hash(policy)
    certification = resolve_shadow_reliability_certification(
        db, settings_object=settings_object, evaluated_at=now
    )
    blockers: set[str] = set()
    if certification.get("resolved_status") != "CERTIFIED":
        blockers.add("PAPER_PROJECTION_RELIABILITY_NOT_CERTIFIED")
    cert_id = certification.get("certification_id")
    cert_model = None
    if cert_id:
        cert_model = db.scalar(
            select(CanonicalParserShadowReliabilityCertification).where(
                CanonicalParserShadowReliabilityCertification.certification_id == cert_id
            )
        )
    if cert_model is None:
        blockers.add("PAPER_PROJECTION_CERTIFICATION_MISSING")

    sources, projections = _collect_sources(
        db, settings_object=settings_object, evaluated_at=now
    )
    projectable = sum(item["status"] == "PROJECTABLE" for item in projections)
    review = sum(item["status"] == "REVIEW" for item in projections)
    rejected = sum(item["status"] == "REJECTED" for item in projections)
    reasons: set[str] = set(blockers)
    if not projections:
        reasons.add("PAPER_PROJECTION_NO_SOURCE_ARTIFACTS")
    if projectable < policy["minimum_projectable_results"]:
        reasons.add("PAPER_PROJECTION_PROJECTABLE_RESULTS_INSUFFICIENT")
    if blockers:
        status = "BLOCKED"
    elif not projections:
        status = "INSUFFICIENT_DATA"
    elif projectable == 0 or rejected == len(projections):
        status = "BLOCKED"
    elif review or rejected:
        status = "PARTIAL"
    else:
        status = "PASSED"
    source_snapshot = {
        "certification_id": cert_id,
        "certification_event_hash": certification.get("latest_event_hash"),
        "assessment_id": certification.get("assessment_id"),
        "source_runs": sources,
        "projection_manifest": [
            {
                "source_execution_run_id": item["source_execution_run_id"],
                "source_result_id": item["source_result_id"],
                "artifact_index": item["artifact_index"],
                "artifact_hash": item["artifact_hash"],
                "projection_hash": item["projection_hash"],
                "status": item["status"],
            }
            for item in projections
        ],
    }
    source_evidence_hash = calculate_payload_hash(source_snapshot)
    manifest = {
        "certification_id": cert_id,
        "certification_event_hash": certification.get("latest_event_hash"),
        "policy_hash": policy_hash,
        "source_evidence_hash": source_evidence_hash,
        "status": status,
    }
    projection_key = calculate_payload_hash(manifest)
    metrics = {
        "source_run_count": len(sources),
        "source_result_count": len(projections),
        "projectable_count": projectable,
        "review_count": review,
        "rejected_count": rejected,
    }
    return {
        "eligible": not blockers,
        "status": status,
        "reason_codes": sorted(reasons),
        "projection_key": projection_key,
        "confirmation": f"{PAPER_PROJECTION_PREFIX}:{projection_key[:16]}",
        "certification_db_id": cert_model.id if cert_model else None,
        "certification": sanitize_technical_metadata(certification),
        "policy": policy,
        "policy_hash": policy_hash,
        "source_evidence_hash": source_evidence_hash,
        "source_snapshot": sanitize_technical_metadata(source_snapshot),
        "metrics": metrics,
        "projections": projections,
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
    }


def _serialize_run(db: Session, run: CanonicalParserPaperProjectionRun) -> dict[str, Any]:
    results = list(
        db.scalars(
            select(CanonicalParserPaperProjectionResult)
            .where(CanonicalParserPaperProjectionResult.projection_run_db_id == run.id)
            .order_by(CanonicalParserPaperProjectionResult.sequence.asc())
        )
    )
    return {
        "projection_id": run.projection_id,
        "projection_key": run.projection_key,
        "certification_id": run.certification_id,
        "certification_event_hash": run.certification_event_hash,
        "assessment_id": run.assessment_id,
        "status": run.status,
        "source_run_count": run.source_run_count,
        "source_result_count": run.source_result_count,
        "projectable_count": run.projectable_count,
        "review_count": run.review_count,
        "rejected_count": run.rejected_count,
        "policy_version": run.policy_version,
        "policy_hash": run.policy_hash,
        "policy_snapshot": run.policy_snapshot,
        "source_evidence_hash": run.source_evidence_hash,
        "source_snapshot": run.source_snapshot,
        "metrics_snapshot": run.metrics_snapshot,
        "reason_codes": run.reason_codes,
        "actor_label": run.actor_label,
        "note": run.note,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "results": [
            {
                "result_id": item.result_id,
                "sequence": item.sequence,
                "source_execution_run_id": item.source_execution_run_id,
                "source_result_id": item.source_result_id,
                "raw_event_id": item.raw_event_id,
                "artifact_index": item.artifact_index,
                "status": item.status,
                "action": item.action,
                "wallet_address": item.wallet_address,
                "token_mint": item.token_mint,
                "token_amount": item.token_amount,
                "sol_amount": item.sol_amount,
                "artifact_hash": item.artifact_hash,
                "projection_hash": item.projection_hash,
                "projection_payload": item.projection_payload,
                "reason_codes": item.reason_codes,
            }
            for item in results
        ],
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
    }


def run_paper_projection(
    db: Session,
    *,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    started_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_PAPER_PROJECTION_ENABLED", False)):
        raise CanonicalParserPaperProjectionError(
            "Paper projection dry-run disabilitata.",
            code="CANONICAL_PARSER_PAPER_PROJECTION_DISABLED",
            status_code=409,
        )
    now = _aware(started_at)
    preview = preview_paper_projection(
        db, settings_object=settings_object, evaluated_at=now
    )
    existing = db.scalar(
        select(CanonicalParserPaperProjectionRun).where(
            CanonicalParserPaperProjectionRun.projection_key == preview["projection_key"]
        )
    )
    if existing is not None:
        return _serialize_run(db, existing)
    if confirmation != preview["confirmation"]:
        raise CanonicalParserPaperProjectionError(
            "Conferma paper projection non valida.",
            code="PAPER_PROJECTION_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if not preview["eligible"]:
        raise CanonicalParserPaperProjectionError(
            "Paper projection bloccata dalla reliability certification.",
            code="PAPER_PROJECTION_CERTIFICATION_BLOCKED",
            status_code=409,
        )
    certification = preview["certification"]
    metrics = preview["metrics"]
    run = CanonicalParserPaperProjectionRun(
        projection_id=str(uuid4()),
        projection_key=preview["projection_key"],
        certification_db_id=preview["certification_db_id"],
        certification_id=certification["certification_id"],
        certification_event_hash=certification["latest_event_hash"],
        assessment_id=certification["assessment_id"],
        source_run_count=metrics["source_run_count"],
        source_result_count=metrics["source_result_count"],
        projectable_count=metrics["projectable_count"],
        review_count=metrics["review_count"],
        rejected_count=metrics["rejected_count"],
        status=preview["status"],
        policy_version=PAPER_PROJECTION_POLICY_VERSION,
        policy_hash=preview["policy_hash"],
        policy_snapshot=preview["policy"],
        source_evidence_hash=preview["source_evidence_hash"],
        source_snapshot=preview["source_snapshot"],
        metrics_snapshot=metrics,
        reason_codes=preview["reason_codes"],
        actor_label=_actor(actor_label),
        note=_note(note),
        started_at=now,
        completed_at=now,
    )
    db.add(run)
    try:
        db.flush()
        for sequence, item in enumerate(preview["projections"], start=1):
            db.add(
                CanonicalParserPaperProjectionResult(
                    result_id=str(uuid4()),
                    projection_run_db_id=run.id,
                    sequence=sequence,
                    source_execution_run_db_id=item["source_execution_run_db_id"],
                    source_execution_run_id=item["source_execution_run_id"],
                    source_result_db_id=item["source_result_db_id"],
                    source_result_id=item["source_result_id"],
                    raw_event_id=item["raw_event_id"],
                    artifact_index=item["artifact_index"],
                    status=item["status"],
                    action=item["action"],
                    wallet_address=item["wallet_address"],
                    token_mint=item["token_mint"],
                    token_amount=item["token_amount"],
                    sol_amount=item["sol_amount"],
                    artifact_hash=item["artifact_hash"],
                    projection_hash=item["projection_hash"],
                    projection_payload=item["projection_payload"],
                    reason_codes=item["reason_codes"],
                )
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(
            select(CanonicalParserPaperProjectionRun).where(
                CanonicalParserPaperProjectionRun.projection_key == preview["projection_key"]
            )
        )
        if existing is not None:
            return _serialize_run(db, existing)
        raise CanonicalParserPaperProjectionError(
            "Conflitto durante la paper projection.",
            code="PAPER_PROJECTION_CONFLICT",
            status_code=409,
        ) from exc
    db.refresh(run)
    return _serialize_run(db, run)


def get_paper_projection_run(db: Session, projection_id: str) -> dict[str, Any]:
    run = db.scalar(
        select(CanonicalParserPaperProjectionRun).where(
            CanonicalParserPaperProjectionRun.projection_id == projection_id
        )
    )
    if run is None:
        raise CanonicalParserPaperProjectionError(
            "Paper projection non trovata.",
            code="PAPER_PROJECTION_NOT_FOUND",
            status_code=404,
        )
    return _serialize_run(db, run)


def resolve_paper_projection(
    db: Session,
    *,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    run = db.scalar(
        select(CanonicalParserPaperProjectionRun)
        .order_by(CanonicalParserPaperProjectionRun.completed_at.desc())
        .limit(1)
    )
    if run is None:
        return {
            "resolved_status": "UNPROJECTED",
            "projection_id": None,
            "paper_execution_authorized": False,
            "live_execution_authorized": False,
        }
    payload = _serialize_run(db, run)
    if run.status != "PASSED":
        payload["resolved_status"] = run.status
        return payload
    preview = preview_paper_projection(
        db, settings_object=settings_object, evaluated_at=evaluated_at
    )
    if (
        preview["source_evidence_hash"] != run.source_evidence_hash
        or preview["policy_hash"] != run.policy_hash
        or preview["certification"].get("latest_event_hash") != run.certification_event_hash
    ):
        payload["resolved_status"] = "DRIFTED"
        return payload
    payload["resolved_status"] = "PASSED"
    return payload


def get_paper_projection_status(
    db: Session,
    *,
    settings_object: Any = settings,
) -> dict[str, Any]:
    return {
        "enabled": bool(getattr(settings_object, "CANONICAL_PARSER_PAPER_PROJECTION_ENABLED", False)),
        "policy": _policy_snapshot(settings_object),
        "projection_run_count": int(
            db.scalar(select(func.count(CanonicalParserPaperProjectionRun.id))) or 0
        ),
        "projection_result_count": int(
            db.scalar(select(func.count(CanonicalParserPaperProjectionResult.id))) or 0
        ),
        "operational_guards": {
            "manual_projection_only": True,
            "writes_projection_tables_only": True,
            "paper_account_reads": False,
            "paper_account_writes": False,
            "paper_order_writes": False,
            "paper_position_writes": False,
            "trade_writes": False,
            "external_requests_allowed": False,
            "paper_execution_authorized": False,
            "live_execution_authorized": False,
        },
    }
