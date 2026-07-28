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
    CanonicalParserPaperCalibrationCampaign,
    CanonicalParserPaperCampaignItem,
    CanonicalParserPaperCampaignRun,
    CanonicalParserPaperExecutionPermit,
    CanonicalParserPaperOperationalAssessment,
    CanonicalParserPermitBoundPaperExecution,
)
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    sanitize_error_message,
)
from backend.app.services.blockchain_parser_permit_bound_paper_execution_service import (
    CanonicalParserPermitBoundPaperExecutionError,
    PERMIT_BOUND_RECONCILE_PREFIX,
    execute_permit_bound_paper,
    preview_permit_bound_paper_execution,
    reconcile_permit_bound_paper_execution,
)

PAPER_CAMPAIGN_POLICY_VERSION = "canonical-parser-paper-campaign-orchestration/1"
PAPER_CAMPAIGN_PREFIX = "RUN_M34_PAPER_CAMPAIGN"
PAPER_CAMPAIGN_RECOVERY_PREFIX = "RECOVER_M34_PAPER_CAMPAIGN"
PAPER_OPERATIONAL_POLICY_VERSION = "canonical-parser-paper-operational-readiness/1"
PAPER_OPERATIONAL_PREFIX = "ASSESS_M34_PAPER_OPERATIONS"
_MONEY_QUANTUM = Decimal("0.000000001")
_SCORE_QUANTUM = Decimal("0.0001")


class CanonicalParserPaperCampaignError(ValueError):
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


def _decimal(value: Any, *, quantum: Decimal = _MONEY_QUANTUM) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CanonicalParserPaperCampaignError(
            "Valore numerico M34 non valido.", code="PAPER_CAMPAIGN_INVALID_NUMBER"
        ) from exc
    if not result.is_finite():
        raise CanonicalParserPaperCampaignError(
            "Valore numerico M34 non finito.", code="PAPER_CAMPAIGN_INVALID_NUMBER"
        )
    return result.quantize(quantum)


def _money(value: Any) -> str:
    return format(_decimal(value), "f")


def _score(value: Any | None) -> str | None:
    return None if value is None else format(_decimal(value, quantum=_SCORE_QUANTUM), "f")


def _actor(value: str | None) -> str:
    return sanitize_error_message(value or "LOCAL_PAPER_CAMPAIGN", max_length=80) or "LOCAL_PAPER_CAMPAIGN"


def _note(value: str | None) -> str | None:
    return None if not str(value or "").strip() else sanitize_error_message(value, max_length=500)


def _policy(settings_object: Any) -> dict[str, Any]:
    return {
        "policy_version": PAPER_CAMPAIGN_POLICY_VERSION,
        "maximum_items": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_CAMPAIGN_MAX_ITEMS", 10)),
        "recovery_limit": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_CAMPAIGN_RECOVERY_LIMIT", 25)),
        "manual_only": True,
        "worker_connected": False,
        "scheduler_connected": False,
        "stream_connected": False,
        "external_requests_allowed": False,
        "live_execution_authorized": False,
    }


def _operational_policy(settings_object: Any) -> dict[str, Any]:
    return {
        "policy_version": PAPER_OPERATIONAL_POLICY_VERSION,
        "lookback_hours": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_OPERATIONAL_LOOKBACK_HOURS", 24)),
        "minimum_settled": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_OPERATIONAL_MIN_SETTLED", 20)),
        "maximum_reconciliation_required": int(
            getattr(settings_object, "CANONICAL_PARSER_PAPER_OPERATIONAL_MAX_RECONCILIATION_REQUIRED", 0)
        ),
        "minimum_reliability_score": str(
            getattr(settings_object, "CANONICAL_PARSER_PAPER_OPERATIONAL_MIN_RELIABILITY_SCORE", 98.0)
        ),
        "maximum_calibration_gap_percent": str(
            getattr(settings_object, "CANONICAL_PARSER_PAPER_OPERATIONAL_MAX_CALIBRATION_GAP_PERCENT", 20.0)
        ),
        "maximum_calibration_age_minutes": int(
            getattr(settings_object, "CANONICAL_PARSER_PAPER_OPERATIONAL_MAX_CALIBRATION_AGE_MINUTES", 120)
        ),
        "validity_minutes": int(
            getattr(settings_object, "CANONICAL_PARSER_PAPER_OPERATIONAL_VALIDITY_MINUTES", 30)
        ),
        "reservation_timeout_minutes": int(
            getattr(settings_object, "CANONICAL_PARSER_PERMIT_BOUND_PAPER_EXECUTION_RESERVATION_TIMEOUT_MINUTES", 10)
        ),
        "live_execution_authorized": False,
    }


def _serialize_campaign(row: CanonicalParserPaperCampaignRun) -> dict[str, Any]:
    return {
        "campaign_id": row.campaign_id,
        "campaign_key": row.campaign_key,
        "scope": row.scope,
        "status": row.status,
        "paper_account_id": row.paper_account_id,
        "permit_id": row.permit_id,
        "requested_count": row.requested_count,
        "selected_count": row.selected_count,
        "settled_count": row.settled_count,
        "released_count": row.released_count,
        "failed_count": row.failed_count,
        "reconciliation_required_count": row.reconciliation_required_count,
        "skipped_count": row.skipped_count,
        "requested_budget_sol": _money(row.requested_budget_sol),
        "settled_budget_sol": _money(row.settled_budget_sol),
        "policy_version": row.policy_version,
        "policy_hash": row.policy_hash,
        "policy_snapshot": row.policy_snapshot,
        "parameters": row.parameters,
        "summary": row.summary,
        "reason_codes": row.reason_codes,
        "safety": row.safety,
        "evidence_hash": row.evidence_hash,
        "actor_label": row.actor_label,
        "note": row.note,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
    }


def _serialize_item(row: CanonicalParserPaperCampaignItem) -> dict[str, Any]:
    return {
        "sequence": row.sequence,
        "decision_result_id": row.decision_result_id,
        "execution_id": row.execution_id,
        "side": row.side,
        "token_mint": row.token_mint,
        "status": row.status,
        "market_price_sol": format(row.market_price_sol, "f"),
        "requested_budget_sol": _money(row.requested_budget_sol),
        "settled_budget_sol": _money(row.settled_budget_sol),
        "idempotency_key": row.idempotency_key,
        "reason_code": row.reason_code,
        "item_snapshot": row.item_snapshot,
        "item_hash": row.item_hash,
    }


def _serialize_assessment(row: CanonicalParserPaperOperationalAssessment) -> dict[str, Any]:
    return {
        "assessment_id": row.assessment_id,
        "assessment_key": row.assessment_key,
        "scope": row.scope,
        "status": row.status,
        "paper_account_id": row.paper_account_id,
        "calibration_campaign_id": row.calibration_campaign_id,
        "settled_count": row.settled_count,
        "reconciliation_required_count": row.reconciliation_required_count,
        "stale_reservation_count": row.stale_reservation_count,
        "budget_drift_count": row.budget_drift_count,
        "reliability_score": _score(row.reliability_score),
        "calibration_gap_percent": _score(row.calibration_gap_percent),
        "policy_version": row.policy_version,
        "policy_hash": row.policy_hash,
        "policy_snapshot": row.policy_snapshot,
        "summary": row.summary,
        "reason_codes": row.reason_codes,
        "evidence_hash": row.evidence_hash,
        "actor_label": row.actor_label,
        "note": row.note,
        "window_started_at": row.window_started_at,
        "window_ended_at": row.window_ended_at,
        "completed_at": row.completed_at,
        "valid_until": row.valid_until,
    }


def _normalize_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in items:
        decision_result_id = str(raw.get("decision_result_id") or "").strip()
        side = str(raw.get("side") or "BUY").strip().upper()
        if len(decision_result_id) != 36 or side not in {"BUY", "SELL"}:
            raise CanonicalParserPaperCampaignError(
                "Elemento campagna M34 non valido.", code="PAPER_CAMPAIGN_INVALID_ITEM"
            )
        identity = (decision_result_id, side)
        if identity in seen:
            raise CanonicalParserPaperCampaignError(
                "Decisione duplicata nella stessa campagna M34.", code="PAPER_CAMPAIGN_DUPLICATE_ITEM", status_code=409
            )
        seen.add(identity)
        normalized.append(
            {
                "decision_result_id": decision_result_id,
                "side": side,
                "market_price_sol": str(raw.get("market_price_sol")),
                "quantity": raw.get("quantity"),
                "slippage_percent": str(raw.get("slippage_percent", 0.5)),
                "fee_percent": str(raw.get("fee_percent", 0.25)),
                "idempotency_token": str(raw.get("idempotency_token") or "").strip(),
            }
        )
    return normalized


def preview_paper_campaign(
    db: Session,
    *,
    permit_id: str,
    items: list[dict[str, Any]],
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _policy(settings_object)
    normalized = _normalize_items(items)
    if not normalized or len(normalized) > policy["maximum_items"]:
        raise CanonicalParserPaperCampaignError(
            "Numero elementi M34 fuori limite.", code="PAPER_CAMPAIGN_ITEM_LIMIT", status_code=409
        )
    previews: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    account_id: int | None = None
    for sequence, item in enumerate(normalized, start=1):
        try:
            payload = preview_permit_bound_paper_execution(
                db,
                permit_id=permit_id,
                decision_result_id=item["decision_result_id"],
                side=item["side"],
                market_price_sol=item["market_price_sol"],
                quantity=item["quantity"],
                slippage_percent=item["slippage_percent"],
                fee_percent=item["fee_percent"],
                idempotency_token=item["idempotency_token"],
                settings_object=settings_object,
                evaluated_at=now,
            )
            if payload.get("existing_execution") is not None:
                payload = dict(payload)
                payload["ready"] = True
                payload["paper_account_id"] = payload["existing_execution"]["paper_account_id"]
                payload["decision_result_id"] = item["decision_result_id"]
                payload["side"] = item["side"]
                payload["token_mint"] = payload["existing_execution"]["token_mint"]
                payload["requested_budget_sol"] = payload["existing_execution"]["requested_budget_sol"]
            if account_id is None:
                account_id = int(payload["paper_account_id"])
            elif account_id != int(payload["paper_account_id"]):
                raise CanonicalParserPaperCampaignError(
                    "Gli elementi M34 non appartengono allo stesso account PAPER.",
                    code="PAPER_CAMPAIGN_ACCOUNT_MISMATCH",
                    status_code=409,
                )
            previews.append({"sequence": sequence, "input": item, "preview": payload})
        except (CanonicalParserPermitBoundPaperExecutionError, CanonicalParserPaperCampaignError) as exc:
            errors.append(
                {
                    "sequence": sequence,
                    "decision_result_id": item["decision_result_id"],
                    "code": getattr(exc, "code", "PAPER_CAMPAIGN_ITEM_BLOCKED"),
                    "message": sanitize_error_message(exc, max_length=500),
                }
            )
    identity = {
        "permit_id": permit_id,
        "items": [
            {
                "decision_result_id": row["input"]["decision_result_id"],
                "side": row["input"]["side"],
                "market_price_sol": row["input"]["market_price_sol"],
                "idempotency_key": row["preview"].get("idempotency_key")
                or row["preview"].get("existing_execution", {}).get("idempotency_key"),
            }
            for row in previews
        ],
        "policy": policy,
    }
    campaign_key = calculate_payload_hash(identity)
    existing = db.scalar(
        select(CanonicalParserPaperCampaignRun).where(CanonicalParserPaperCampaignRun.campaign_key == campaign_key)
    )
    requested_budget = sum(
        (_decimal(row["preview"].get("requested_budget_sol", 0)) for row in previews), Decimal("0")
    )
    return {
        "ready": not errors and len(previews) == len(normalized),
        "existing_campaign": None if existing is None else _serialize_campaign(existing),
        "campaign_key": campaign_key,
        "permit_id": permit_id,
        "paper_account_id": account_id,
        "requested_count": len(normalized),
        "selected_count": len(previews),
        "requested_budget_sol": _money(requested_budget),
        "items": previews,
        "errors": errors,
        "confirmation": f"{PAPER_CAMPAIGN_PREFIX}:{permit_id}:{campaign_key}",
        "policy": policy,
        "safety": {
            "manual_only": True,
            "m32_required": True,
            "worker_connected": False,
            "scheduler_connected": False,
            "stream_connected": False,
            "external_requests_allowed": False,
            "live_execution_authorized": False,
        },
    }


def run_paper_campaign(
    db: Session,
    *,
    permit_id: str,
    items: list[dict[str, Any]],
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    executed_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_PAPER_CAMPAIGN_ORCHESTRATION_ENABLED", False)):
        raise CanonicalParserPaperCampaignError(
            "M34 è disabilitata. Il flag resta false di default.",
            code="PAPER_CAMPAIGN_DISABLED",
            status_code=409,
        )
    now = _aware(executed_at)
    preview = preview_paper_campaign(
        db, permit_id=permit_id, items=items, settings_object=settings_object, evaluated_at=now
    )
    if preview["existing_campaign"] is not None:
        return preview["existing_campaign"]
    if not preview["ready"]:
        raise CanonicalParserPaperCampaignError(
            "Campagna M34 non pronta.", code="PAPER_CAMPAIGN_NOT_READY", status_code=409
        )
    if confirmation != preview["confirmation"]:
        raise CanonicalParserPaperCampaignError(
            "Conferma M34 non valida.", code="PAPER_CAMPAIGN_CONFIRMATION_REQUIRED", status_code=409
        )

    results: list[dict[str, Any]] = []
    for row in preview["items"]:
        item = row["input"]
        item_preview = row["preview"]
        if item_preview.get("existing_execution") is not None:
            execution = item_preview["existing_execution"]
        else:
            try:
                execution = execute_permit_bound_paper(
                    db,
                    permit_id=permit_id,
                    decision_result_id=item["decision_result_id"],
                    side=item["side"],
                    market_price_sol=item["market_price_sol"],
                    idempotency_token=item["idempotency_token"],
                    confirmation=item_preview["confirmation"],
                    quantity=item["quantity"],
                    slippage_percent=item["slippage_percent"],
                    fee_percent=item["fee_percent"],
                    actor_label=actor_label,
                    note=note,
                    settings_object=settings_object,
                    executed_at=now,
                )
            except CanonicalParserPermitBoundPaperExecutionError as exc:
                execution = {
                    "execution_id": None,
                    "status": "FAILED",
                    "decision_result_id": item["decision_result_id"],
                    "side": item["side"],
                    "token_mint": item_preview.get("token_mint", "UNKNOWN"),
                    "requested_budget_sol": item_preview.get("requested_budget_sol", "0"),
                    "settled_budget_sol": "0",
                    "idempotency_key": item_preview.get("idempotency_key", "0" * 64),
                    "failure_code": exc.code,
                    "failure_message": sanitize_error_message(exc, max_length=500),
                }
        results.append(execution)

    counts = {name: 0 for name in ("SETTLED", "RELEASED", "FAILED", "RECONCILIATION_REQUIRED", "SKIPPED")}
    requested_budget = Decimal("0")
    settled_budget = Decimal("0")
    snapshots: list[dict[str, Any]] = []
    for execution in results:
        status = str(execution.get("status") or "FAILED")
        if status not in counts:
            status = "FAILED"
        counts[status] += 1
        requested_budget += _decimal(execution.get("requested_budget_sol", 0))
        settled_budget += _decimal(execution.get("settled_budget_sol", 0))
        snapshots.append(
            {
                "execution_id": execution.get("execution_id"),
                "decision_result_id": execution.get("decision_result_id"),
                "side": execution.get("side"),
                "status": status,
                "token_mint": execution.get("token_mint"),
                "requested_budget_sol": _money(execution.get("requested_budget_sol", 0)),
                "settled_budget_sol": _money(execution.get("settled_budget_sol", 0)),
                "idempotency_key": execution.get("idempotency_key") or "0" * 64,
                "failure_code": execution.get("failure_code"),
            }
        )
    if counts["RECONCILIATION_REQUIRED"]:
        campaign_status = "RECONCILIATION_REQUIRED"
    elif counts["SETTLED"] == len(results):
        campaign_status = "COMPLETED"
    elif counts["SETTLED"]:
        campaign_status = "PARTIAL"
    elif not results:
        campaign_status = "NOOP"
    else:
        campaign_status = "FAILED"
    policy = preview["policy"]
    policy_hash = calculate_payload_hash(policy)
    evidence_hash = calculate_payload_hash({"campaign_key": preview["campaign_key"], "items": snapshots})
    campaign = CanonicalParserPaperCampaignRun(
        campaign_id=str(uuid4()),
        campaign_key=preview["campaign_key"],
        scope="PAPER_MANUAL_ORCHESTRATION",
        status=campaign_status,
        paper_account_id=int(preview["paper_account_id"]),
        permit_id=permit_id,
        requested_count=preview["requested_count"],
        selected_count=len(results),
        settled_count=counts["SETTLED"],
        released_count=counts["RELEASED"],
        failed_count=counts["FAILED"],
        reconciliation_required_count=counts["RECONCILIATION_REQUIRED"],
        skipped_count=counts["SKIPPED"],
        requested_budget_sol=requested_budget,
        settled_budget_sol=settled_budget,
        policy_version=PAPER_CAMPAIGN_POLICY_VERSION,
        policy_hash=policy_hash,
        policy_snapshot=policy,
        parameters={"permit_id": permit_id, "requested_count": preview["requested_count"]},
        summary={"status_counts": counts},
        reason_codes=["RECONCILIATION_REQUIRED"] if counts["RECONCILIATION_REQUIRED"] else [],
        safety=preview["safety"],
        evidence_hash=evidence_hash,
        actor_label=_actor(actor_label),
        note=_note(note),
        started_at=now,
        completed_at=_utc_now(),
    )
    db.add(campaign)
    try:
        db.flush()
        for sequence, snapshot in enumerate(snapshots, start=1):
            item_hash = calculate_payload_hash(snapshot)
            db.add(
                CanonicalParserPaperCampaignItem(
                    campaign_db_id=campaign.id,
                    sequence=sequence,
                    decision_result_id=str(snapshot["decision_result_id"]),
                    execution_id=snapshot["execution_id"],
                    side=str(snapshot["side"]),
                    token_mint=str(snapshot["token_mint"]),
                    status=str(snapshot["status"]),
                    market_price_sol=_decimal(preview["items"][sequence - 1]["input"]["market_price_sol"], quantum=Decimal("0.000000000000000001")),
                    requested_budget_sol=_decimal(snapshot["requested_budget_sol"]),
                    settled_budget_sol=_decimal(snapshot["settled_budget_sol"]),
                    idempotency_key=str(snapshot["idempotency_key"]),
                    reason_code=snapshot["failure_code"],
                    item_snapshot=snapshot,
                    item_hash=item_hash,
                )
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.scalar(
            select(CanonicalParserPaperCampaignRun).where(
                CanonicalParserPaperCampaignRun.campaign_key == preview["campaign_key"]
            )
        )
        if duplicate is not None:
            return _serialize_campaign(duplicate)
        raise CanonicalParserPaperCampaignError(
            "Conflitto durante la campagna M34.", code="PAPER_CAMPAIGN_CONFLICT", status_code=409
        ) from exc
    db.refresh(campaign)
    return _serialize_campaign(campaign)


def get_paper_campaign(db: Session, campaign_id: str) -> dict[str, Any]:
    campaign = db.scalar(
        select(CanonicalParserPaperCampaignRun).where(CanonicalParserPaperCampaignRun.campaign_id == campaign_id)
    )
    if campaign is None:
        raise CanonicalParserPaperCampaignError(
            "Campagna M34 non trovata.", code="PAPER_CAMPAIGN_NOT_FOUND", status_code=404
        )
    payload = _serialize_campaign(campaign)
    payload["items"] = [
        _serialize_item(row)
        for row in db.scalars(
            select(CanonicalParserPaperCampaignItem)
            .where(CanonicalParserPaperCampaignItem.campaign_db_id == campaign.id)
            .order_by(CanonicalParserPaperCampaignItem.sequence.asc())
        )
    ]
    return payload


def recover_paper_campaign(
    db: Session,
    *,
    campaign_id: str,
    confirmation: str,
    actor_label: str | None = None,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_PAPER_CAMPAIGN_ORCHESTRATION_ENABLED", False)):
        raise CanonicalParserPaperCampaignError(
            "M34 è disabilitata.", code="PAPER_CAMPAIGN_DISABLED", status_code=409
        )
    campaign = db.scalar(
        select(CanonicalParserPaperCampaignRun).where(CanonicalParserPaperCampaignRun.campaign_id == campaign_id)
    )
    if campaign is None:
        raise CanonicalParserPaperCampaignError(
            "Campagna M34 non trovata.", code="PAPER_CAMPAIGN_NOT_FOUND", status_code=404
        )
    expected = f"{PAPER_CAMPAIGN_RECOVERY_PREFIX}:{campaign_id}:{campaign.evidence_hash}"
    if confirmation != expected:
        raise CanonicalParserPaperCampaignError(
            "Conferma recovery M34 non valida.", code="PAPER_CAMPAIGN_RECOVERY_CONFIRMATION_REQUIRED", status_code=409
        )
    rows = list(
        db.scalars(
            select(CanonicalParserPaperCampaignItem)
            .where(
                CanonicalParserPaperCampaignItem.campaign_db_id == campaign.id,
                CanonicalParserPaperCampaignItem.status == "RECONCILIATION_REQUIRED",
            )
            .order_by(CanonicalParserPaperCampaignItem.sequence.asc())
            .limit(_policy(settings_object)["recovery_limit"])
        )
    )
    recovered: list[dict[str, Any]] = []
    for item in rows:
        if not item.execution_id:
            continue
        execution = db.scalar(
            select(CanonicalParserPermitBoundPaperExecution).where(
                CanonicalParserPermitBoundPaperExecution.execution_id == item.execution_id
            )
        )
        if execution is None:
            item.status = "FAILED"
            item.reason_code = "M32_EXECUTION_MISSING"
            continue
        payload = reconcile_permit_bound_paper_execution(
            db,
            execution_id=execution.execution_id,
            confirmation=f"{PERMIT_BOUND_RECONCILE_PREFIX}:{execution.execution_id}:{execution.reservation_hash}",
            actor_label=actor_label,
            settings_object=settings_object,
            evaluated_at=evaluated_at,
        )
        item.status = payload["status"]
        item.settled_budget_sol = _decimal(payload.get("settled_budget_sol", 0))
        item.reason_code = payload.get("failure_code")
        item.item_snapshot = {**item.item_snapshot, "recovery_status": payload["status"]}
        item.item_hash = calculate_payload_hash(item.item_snapshot)
        recovered.append(payload)
    db.commit()
    current_items = list(
        db.scalars(select(CanonicalParserPaperCampaignItem).where(CanonicalParserPaperCampaignItem.campaign_db_id == campaign.id))
    )
    campaign.settled_count = sum(row.status == "SETTLED" for row in current_items)
    campaign.released_count = sum(row.status == "RELEASED" for row in current_items)
    campaign.failed_count = sum(row.status == "FAILED" for row in current_items)
    campaign.reconciliation_required_count = sum(row.status == "RECONCILIATION_REQUIRED" for row in current_items)
    campaign.settled_budget_sol = sum((_decimal(row.settled_budget_sol) for row in current_items), Decimal("0"))
    campaign.status = (
        "RECONCILIATION_REQUIRED"
        if campaign.reconciliation_required_count
        else "COMPLETED"
        if campaign.settled_count == campaign.selected_count
        else "PARTIAL"
        if campaign.settled_count
        else "FAILED"
    )
    campaign.completed_at = _utc_now()
    campaign.summary = {**campaign.summary, "last_recovery_count": len(recovered)}
    db.commit()
    db.refresh(campaign)
    return {"campaign": _serialize_campaign(campaign), "recovered": recovered}


def preview_paper_operational_assessment(
    db: Session,
    *,
    paper_account_id: int,
    calibration_campaign_id: str | None = None,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _operational_policy(settings_object)
    window_start = now - timedelta(hours=policy["lookback_hours"])
    calibration_query = select(CanonicalParserPaperCalibrationCampaign).where(
        CanonicalParserPaperCalibrationCampaign.paper_account_id == paper_account_id
    )
    if calibration_campaign_id:
        calibration_query = calibration_query.where(
            CanonicalParserPaperCalibrationCampaign.campaign_id == calibration_campaign_id
        )
    calibration = db.scalar(calibration_query.order_by(CanonicalParserPaperCalibrationCampaign.completed_at.desc()).limit(1))
    executions = list(
        db.scalars(
            select(CanonicalParserPermitBoundPaperExecution).where(
                CanonicalParserPermitBoundPaperExecution.paper_account_id == paper_account_id,
                CanonicalParserPermitBoundPaperExecution.reserved_at >= window_start,
                CanonicalParserPermitBoundPaperExecution.reserved_at <= now,
            )
        )
    )
    settled = sum(row.status == "SETTLED" for row in executions)
    reconciliation = sum(row.status == "RECONCILIATION_REQUIRED" for row in executions)
    timeout = timedelta(minutes=policy["reservation_timeout_minutes"])
    stale = sum(
        row.status in {"RESERVED", "RECONCILIATION_REQUIRED"} and now - _aware(row.reserved_at) >= timeout
        for row in executions
    )
    permit_ids = {row.permit_db_id for row in executions}
    drifts: list[dict[str, Any]] = []
    for permit_db_id in permit_ids:
        permit = db.get(CanonicalParserPaperExecutionPermit, permit_db_id)
        if permit is None:
            drifts.append({"permit_db_id": permit_db_id, "reason": "PERMIT_MISSING"})
            continue
        active_rows = [
            row
            for row in db.scalars(
                select(CanonicalParserPermitBoundPaperExecution).where(
                    CanonicalParserPermitBoundPaperExecution.permit_db_id == permit_db_id,
                    CanonicalParserPermitBoundPaperExecution.status.in_(("RESERVED", "RECONCILIATION_REQUIRED", "SETTLED")),
                )
            )
        ]
        expected_budget = sum((_decimal(row.reserved_budget_sol) for row in active_rows), Decimal("0"))
        expected_orders = len(active_rows)
        if _decimal(permit.consumed_budget_sol) != expected_budget or int(permit.consumed_order_count) != expected_orders:
            drifts.append(
                {
                    "permit_id": permit.permit_id,
                    "expected_budget_sol": _money(expected_budget),
                    "actual_budget_sol": _money(permit.consumed_budget_sol),
                    "expected_order_count": expected_orders,
                    "actual_order_count": int(permit.consumed_order_count),
                }
            )
    reasons: list[str] = []
    if calibration is None or settled < policy["minimum_settled"]:
        status = "INSUFFICIENT_DATA"
        reasons.append("MINIMUM_SETTLED_NOT_REACHED" if calibration else "CALIBRATION_CAMPAIGN_MISSING")
    else:
        calibration_age = now - _aware(calibration.completed_at)
        if calibration_age > timedelta(minutes=policy["maximum_calibration_age_minutes"]):
            reasons.append("CALIBRATION_STALE")
        if calibration.status == "BLOCKED":
            reasons.append("CALIBRATION_BLOCKED")
        if reconciliation > policy["maximum_reconciliation_required"]:
            reasons.append("RECONCILIATION_REQUIRED_PRESENT")
        if stale:
            reasons.append("STALE_RESERVATIONS_PRESENT")
        if drifts:
            reasons.append("PERMIT_BUDGET_DRIFT")
        if reasons:
            status = "BLOCKED"
        elif calibration.status != "READY":
            status = "REVIEW"
            reasons.append("CALIBRATION_NOT_READY")
        elif _decimal(calibration.reliability_score, quantum=_SCORE_QUANTUM) < _decimal(
            policy["minimum_reliability_score"], quantum=_SCORE_QUANTUM
        ):
            status = "REVIEW"
            reasons.append("RELIABILITY_BELOW_TARGET")
        elif calibration.calibration_gap_percent is not None and _decimal(
            calibration.calibration_gap_percent, quantum=_SCORE_QUANTUM
        ) > _decimal(policy["maximum_calibration_gap_percent"], quantum=_SCORE_QUANTUM):
            status = "REVIEW"
            reasons.append("CALIBRATION_GAP_ABOVE_TARGET")
        else:
            status = "READY"
    evidence = {
        "paper_account_id": paper_account_id,
        "calibration_campaign_id": None if calibration is None else calibration.campaign_id,
        "calibration_status": None if calibration is None else calibration.status,
        "settled_count": settled,
        "reconciliation_required_count": reconciliation,
        "stale_reservation_count": stale,
        "budget_drifts": drifts,
        "window_started_at": window_start.isoformat(),
        "window_ended_at": now.isoformat(),
        "policy": policy,
    }
    evidence_hash = calculate_payload_hash(evidence)
    assessment_key = calculate_payload_hash({"evidence_hash": evidence_hash, "status": status})
    existing = db.scalar(
        select(CanonicalParserPaperOperationalAssessment).where(
            CanonicalParserPaperOperationalAssessment.assessment_key == assessment_key
        )
    )
    return {
        "status": status,
        "reason_codes": reasons,
        "paper_account_id": paper_account_id,
        "calibration_campaign_id": None if calibration is None else calibration.campaign_id,
        "settled_count": settled,
        "reconciliation_required_count": reconciliation,
        "stale_reservation_count": stale,
        "budget_drift_count": len(drifts),
        "reliability_score": None if calibration is None else _score(calibration.reliability_score),
        "calibration_gap_percent": None if calibration is None else _score(calibration.calibration_gap_percent),
        "assessment_key": assessment_key,
        "evidence_hash": evidence_hash,
        "evidence": evidence,
        "existing_assessment": None if existing is None else _serialize_assessment(existing),
        "confirmation": f"{PAPER_OPERATIONAL_PREFIX}:{paper_account_id}:{assessment_key}",
        "policy": policy,
        "window_started_at": window_start,
        "window_ended_at": now,
        "valid_until": now + timedelta(minutes=policy["validity_minutes"]),
    }


def assess_paper_operations(
    db: Session,
    *,
    paper_account_id: int,
    calibration_campaign_id: str | None,
    confirmation: str,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_PAPER_CAMPAIGN_ORCHESTRATION_ENABLED", False)):
        raise CanonicalParserPaperCampaignError(
            "M34 è disabilitata.", code="PAPER_CAMPAIGN_DISABLED", status_code=409
        )
    preview = preview_paper_operational_assessment(
        db,
        paper_account_id=paper_account_id,
        calibration_campaign_id=calibration_campaign_id,
        settings_object=settings_object,
        evaluated_at=evaluated_at,
    )
    if preview["existing_assessment"] is not None:
        return preview["existing_assessment"]
    if confirmation != preview["confirmation"]:
        raise CanonicalParserPaperCampaignError(
            "Conferma assessment M34 non valida.", code="PAPER_OPERATIONAL_CONFIRMATION_REQUIRED", status_code=409
        )
    calibration = None
    if preview["calibration_campaign_id"]:
        calibration = db.scalar(
            select(CanonicalParserPaperCalibrationCampaign).where(
                CanonicalParserPaperCalibrationCampaign.campaign_id == preview["calibration_campaign_id"]
            )
        )
    policy_hash = calculate_payload_hash(preview["policy"])
    row = CanonicalParserPaperOperationalAssessment(
        assessment_id=str(uuid4()),
        assessment_key=preview["assessment_key"],
        scope="PAPER_OPERATIONAL_READINESS",
        status=preview["status"],
        paper_account_id=paper_account_id,
        calibration_campaign_db_id=None if calibration is None else calibration.id,
        calibration_campaign_id=preview["calibration_campaign_id"],
        settled_count=preview["settled_count"],
        reconciliation_required_count=preview["reconciliation_required_count"],
        stale_reservation_count=preview["stale_reservation_count"],
        budget_drift_count=preview["budget_drift_count"],
        reliability_score=None if preview["reliability_score"] is None else _decimal(preview["reliability_score"], quantum=_SCORE_QUANTUM),
        calibration_gap_percent=None if preview["calibration_gap_percent"] is None else _decimal(preview["calibration_gap_percent"], quantum=_SCORE_QUANTUM),
        policy_version=PAPER_OPERATIONAL_POLICY_VERSION,
        policy_hash=policy_hash,
        policy_snapshot=preview["policy"],
        summary=preview["evidence"],
        reason_codes=preview["reason_codes"],
        evidence_hash=preview["evidence_hash"],
        actor_label=_actor(actor_label),
        note=_note(note),
        window_started_at=preview["window_started_at"],
        window_ended_at=preview["window_ended_at"],
        completed_at=preview["window_ended_at"],
        valid_until=preview["valid_until"],
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.scalar(
            select(CanonicalParserPaperOperationalAssessment).where(
                CanonicalParserPaperOperationalAssessment.assessment_key == preview["assessment_key"]
            )
        )
        if duplicate is not None:
            return _serialize_assessment(duplicate)
        raise CanonicalParserPaperCampaignError(
            "Conflitto assessment M34.", code="PAPER_OPERATIONAL_CONFLICT", status_code=409
        ) from exc
    db.refresh(row)
    return _serialize_assessment(row)


def get_paper_operational_assessment(db: Session, assessment_id: str) -> dict[str, Any]:
    row = db.scalar(
        select(CanonicalParserPaperOperationalAssessment).where(
            CanonicalParserPaperOperationalAssessment.assessment_id == assessment_id
        )
    )
    if row is None:
        raise CanonicalParserPaperCampaignError(
            "Assessment M34 non trovato.", code="PAPER_OPERATIONAL_NOT_FOUND", status_code=404
        )
    return _serialize_assessment(row)


def resolve_paper_campaign(db: Session, *, paper_account_id: int | None = None) -> dict[str, Any]:
    campaign_query = select(CanonicalParserPaperCampaignRun)
    assessment_query = select(CanonicalParserPaperOperationalAssessment)
    if paper_account_id is not None:
        campaign_query = campaign_query.where(CanonicalParserPaperCampaignRun.paper_account_id == paper_account_id)
        assessment_query = assessment_query.where(
            CanonicalParserPaperOperationalAssessment.paper_account_id == paper_account_id
        )
    latest_campaign = db.scalar(campaign_query.order_by(CanonicalParserPaperCampaignRun.created_at.desc()).limit(1))
    latest_assessment = db.scalar(
        assessment_query.order_by(CanonicalParserPaperOperationalAssessment.completed_at.desc()).limit(1)
    )
    return {
        "latest_campaign": None if latest_campaign is None else _serialize_campaign(latest_campaign),
        "latest_operational_assessment": None if latest_assessment is None else _serialize_assessment(latest_assessment),
    }


def get_paper_campaign_status(db: Session, *, settings_object: Any = settings) -> dict[str, Any]:
    return {
        "enabled": bool(getattr(settings_object, "CANONICAL_PARSER_PAPER_CAMPAIGN_ORCHESTRATION_ENABLED", False)),
        "campaign_count": int(db.scalar(select(func.count(CanonicalParserPaperCampaignRun.id))) or 0),
        "assessment_count": int(db.scalar(select(func.count(CanonicalParserPaperOperationalAssessment.id))) or 0),
        "policy": _policy(settings_object),
        "operational_policy": _operational_policy(settings_object),
        "safety": {
            "manual_only": True,
            "paper_execution_via_m32_only": True,
            "live_execution_authorized": False,
            "worker_connected": False,
            "scheduler_connected": False,
            "stream_connected": False,
        },
    }
