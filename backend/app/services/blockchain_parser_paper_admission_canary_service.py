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
    CanonicalParserPaperAdmissionCanaryResult,
    CanonicalParserPaperAdmissionCanaryRun,
    CanonicalParserPaperAdmissionCertification,
    CanonicalParserPaperProjectionReadinessEvidenceRun,
    CanonicalParserPaperProjectionResult,
    CanonicalParserPaperProjectionRun,
    CanonicalParserPaperRuntimeBinding,
)
from backend.app.models.paper_account import PaperAccount
from backend.app.models.paper_position import PaperPosition
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    sanitize_error_message,
    sanitize_technical_metadata,
)
from backend.app.services.blockchain_parser_paper_runtime_binding_service import (
    resolve_paper_runtime_binding,
)

PAPER_ADMISSION_CANARY_POLICY_VERSION = "canonical-parser-paper-admission-canary/1"
PAPER_ADMISSION_CANARY_PREFIX = "RUN_PAPER_ADMISSION_CANARY"
_MAX_ACTOR_LENGTH = 80
_MAX_NOTE_LENGTH = 500


class CanonicalParserPaperAdmissionCanaryError(ValueError):
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
    return sanitize_error_message(value or "LOCAL_PAPER_CANARY", max_length=_MAX_ACTOR_LENGTH) or "LOCAL_PAPER_CANARY"


def _note(value: str | None) -> str | None:
    if not str(value or "").strip():
        return None
    return sanitize_error_message(value, max_length=_MAX_NOTE_LENGTH)


def _decimal(value: Any) -> Decimal | None:
    try:
        resolved = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not resolved.is_finite():
        return None
    return resolved


def _decimal_text(value: Decimal) -> str:
    return format(value.normalize(), "f") if value != 0 else "0"


def _policy_snapshot(settings_object: Any) -> dict[str, Any]:
    return {
        "policy_version": PAPER_ADMISSION_CANARY_POLICY_VERSION,
        "validity_minutes": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_ADMISSION_CANARY_VALIDITY_MINUTES", 15)),
        "max_source_runs": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_ADMISSION_CANARY_MAX_SOURCE_RUNS", 3)),
        "max_results": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_ADMISSION_CANARY_MAX_RESULTS", 25)),
        "min_admissible_results": int(getattr(settings_object, "CANONICAL_PARSER_PAPER_ADMISSION_CANARY_MIN_ADMISSIBLE_RESULTS", 1)),
        "max_cumulative_buy_fraction": float(getattr(settings_object, "CANONICAL_PARSER_PAPER_ADMISSION_CANARY_MAX_CUMULATIVE_BUY_FRACTION", 0.5)),
        "manual_canary_only": True,
        "paper_account_reads": True,
        "paper_position_reads": True,
        "paper_account_writes": False,
        "paper_order_writes": False,
        "paper_position_writes": False,
        "trade_writes": False,
        "price_requests_allowed": False,
        "external_requests_allowed": False,
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
    }


def _account_state(db: Session, account: PaperAccount) -> dict[str, Any]:
    positions = list(
        db.scalars(
            select(PaperPosition)
            .where(PaperPosition.account_id == account.id, PaperPosition.status == "OPEN")
            .order_by(PaperPosition.token_mint.asc(), PaperPosition.id.asc())
        )
    )
    return {
        "paper_account_id": int(account.id),
        "paper_account_name": account.name,
        "status": account.status,
        "cash_balance_sol": str(account.cash_balance_sol),
        "realized_pnl_sol": str(account.realized_pnl_sol),
        "max_position_size_sol": str(account.max_position_size_sol),
        "max_open_positions": int(account.max_open_positions),
        "daily_loss_limit_sol": str(account.daily_loss_limit_sol),
        "open_positions": [
            {
                "position_id": int(position.id),
                "token_mint": position.token_mint,
                "quantity": str(position.quantity),
                "cost_basis_sol": str(position.cost_basis_sol),
            }
            for position in positions
        ],
    }


def _source_rows(
    db: Session, certification: CanonicalParserPaperAdmissionCertification,
    *, policy: dict[str, Any],
) -> tuple[list[CanonicalParserPaperProjectionResult], dict[str, Any], str]:
    evidence = list(
        db.scalars(
            select(CanonicalParserPaperProjectionReadinessEvidenceRun)
            .where(CanonicalParserPaperProjectionReadinessEvidenceRun.assessment_db_id == certification.assessment_db_id)
            .order_by(CanonicalParserPaperProjectionReadinessEvidenceRun.completed_at.desc())
            .limit(int(policy["max_source_runs"]))
        )
    )
    evidence.reverse()
    run_ids = [item.projection_run_db_id for item in evidence]
    runs = []
    if run_ids:
        run_map = {
            item.id: item
            for item in db.scalars(
                select(CanonicalParserPaperProjectionRun).where(CanonicalParserPaperProjectionRun.id.in_(run_ids))
            )
        }
        runs = [run_map[item] for item in run_ids if item in run_map]
    results: list[CanonicalParserPaperProjectionResult] = []
    remaining = int(policy["max_results"])
    for run in runs:
        if remaining <= 0:
            break
        current = list(
            db.scalars(
                select(CanonicalParserPaperProjectionResult)
                .where(CanonicalParserPaperProjectionResult.projection_run_db_id == run.id)
                .order_by(CanonicalParserPaperProjectionResult.sequence.asc())
                .limit(remaining)
            )
        )
        results.extend(current)
        remaining -= len(current)
    snapshot = {
        "assessment_id": certification.assessment_id,
        "projection_runs": [
            {
                "projection_id": run.projection_id,
                "projection_key": run.projection_key,
                "status": run.status,
                "source_result_count": run.source_result_count,
                "completed_at": _aware(run.completed_at).isoformat(),
            }
            for run in runs
        ],
        "results": [
            {
                "result_id": result.result_id,
                "projection_hash": result.projection_hash,
                "status": result.status,
                "action": result.action,
                "token_mint": result.token_mint,
                "token_amount": result.token_amount,
                "sol_amount": result.sol_amount,
            }
            for result in results
        ],
    }
    return results, snapshot, calculate_payload_hash(snapshot)


def _evaluate(
    results: list[CanonicalParserPaperProjectionResult],
    account_state: dict[str, Any], policy: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], str, list[str]]:
    reasons: set[str] = set()
    cash = _decimal(account_state["cash_balance_sol"]) or Decimal("0")
    initial_cash = cash
    max_position = _decimal(account_state["max_position_size_sol"]) or Decimal("0")
    daily_limit = _decimal(account_state["daily_loss_limit_sol"]) or Decimal("0")
    realized = _decimal(account_state["realized_pnl_sol"]) or Decimal("0")
    max_open = int(account_state["max_open_positions"])
    positions: dict[str, dict[str, Decimal]] = {
        item["token_mint"]: {
            "quantity": _decimal(item["quantity"]) or Decimal("0"),
            "cost_basis": _decimal(item["cost_basis_sol"]) or Decimal("0"),
        }
        for item in account_state["open_positions"]
    }
    cumulative_buy = Decimal("0")
    evaluated: list[dict[str, Any]] = []
    global_blockers: set[str] = set()
    if account_state["status"] != "ACTIVE":
        global_blockers.add("PAPER_ACCOUNT_NOT_ACTIVE")
    if daily_limit > 0 and realized <= -daily_limit:
        global_blockers.add("PAPER_DAILY_LOSS_LIMIT_REACHED")

    for sequence, source in enumerate(results, start=1):
        item_reasons: set[str] = set(global_blockers)
        status = "ADMISSIBLE"
        action = source.action if source.action in {"BUY", "SELL"} else "UNKNOWN"
        token = str(source.token_mint or "").strip()
        projected_positions = len([value for value in positions.values() if value["quantity"] > 0])
        if source.status != "PROJECTABLE":
            item_reasons.add("SOURCE_RESULT_NOT_PROJECTABLE")
        if not token:
            item_reasons.add("TOKEN_MINT_MISSING")

        if action == "BUY":
            amount = _decimal(source.sol_amount)
            if amount is None or amount <= 0:
                item_reasons.add("BUY_SOL_AMOUNT_INVALID")
            else:
                existing = positions.get(token)
                current_cost = existing["cost_basis"] if existing else Decimal("0")
                if amount > max_position or current_cost + amount > max_position:
                    item_reasons.add("MAX_POSITION_SIZE_EXCEEDED")
                if amount > cash:
                    item_reasons.add("INSUFFICIENT_PAPER_CASH")
                if existing is None and projected_positions >= max_open:
                    item_reasons.add("MAX_OPEN_POSITIONS_EXCEEDED")
                fraction_limit = initial_cash * Decimal(str(policy["max_cumulative_buy_fraction"]))
                if cumulative_buy + amount > fraction_limit:
                    if not item_reasons:
                        status = "REVIEW"
                    item_reasons.add("CUMULATIVE_BUY_FRACTION_REVIEW")
                if not (item_reasons - {"CUMULATIVE_BUY_FRACTION_REVIEW"}):
                    cash -= amount
                    cumulative_buy += amount
                    if existing is None:
                        positions[token] = {"quantity": Decimal("0"), "cost_basis": amount}
                    else:
                        existing["cost_basis"] += amount
        elif action == "SELL":
            amount = _decimal(source.token_amount)
            existing = positions.get(token)
            if amount is None or amount <= 0:
                item_reasons.add("SELL_TOKEN_AMOUNT_INVALID")
            elif existing is None or existing["quantity"] <= 0:
                item_reasons.add("SELL_POSITION_MISSING")
            elif amount > existing["quantity"]:
                item_reasons.add("SELL_QUANTITY_EXCEEDS_POSITION")
            else:
                existing["quantity"] -= amount
        else:
            item_reasons.add("ACTION_UNSUPPORTED")

        hard_reasons = item_reasons - {"CUMULATIVE_BUY_FRACTION_REVIEW"}
        if hard_reasons:
            status = "BLOCKED"
        elif item_reasons:
            status = "REVIEW"
        reasons.update(item_reasons)
        projected_positions = len([value for value in positions.values() if value["quantity"] > 0 or value["cost_basis"] > 0])
        payload = {
            "sequence": sequence,
            "source_result_id": source.result_id,
            "source_projection_hash": source.projection_hash,
            "status": status,
            "action": action,
            "token_mint": source.token_mint,
            "token_amount": source.token_amount,
            "sol_amount": source.sol_amount,
            "projected_cash_after_sol": _decimal_text(cash),
            "projected_open_positions": projected_positions,
            "reason_codes": sorted(item_reasons),
            "paper_execution": False,
        }
        evaluated.append({**payload, "canary_hash": calculate_payload_hash(payload), "source_db_id": source.id})

    admissible = sum(item["status"] == "ADMISSIBLE" for item in evaluated)
    review = sum(item["status"] == "REVIEW" for item in evaluated)
    blocked = sum(item["status"] == "BLOCKED" for item in evaluated)
    if not evaluated:
        run_status = "INSUFFICIENT_DATA"
        reasons.add("PAPER_CANARY_RESULTS_MISSING")
    elif blocked:
        run_status = "BLOCKED"
    elif review:
        run_status = "REVIEW"
    elif admissible < int(policy["min_admissible_results"]):
        run_status = "INSUFFICIENT_DATA"
        reasons.add("PAPER_CANARY_MIN_ADMISSIBLE_NOT_MET")
    else:
        run_status = "PASSED"
    metrics = {
        "source_result_count": len(evaluated),
        "admissible_count": admissible,
        "review_count": review,
        "blocked_count": blocked,
        "initial_cash_sol": _decimal_text(initial_cash),
        "projected_cash_sol": _decimal_text(cash),
        "cumulative_buy_sol": _decimal_text(cumulative_buy),
        "projected_open_positions": len([value for value in positions.values() if value["quantity"] > 0 or value["cost_basis"] > 0]),
    }
    return evaluated, metrics, run_status, sorted(reasons)


def preview_paper_admission_canary(
    db: Session, *, settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _policy_snapshot(settings_object)
    policy_hash = calculate_payload_hash(policy)
    binding = resolve_paper_runtime_binding(db, settings_object=settings_object, evaluated_at=now)
    blockers: set[str] = set()
    if binding.get("resolved_status") != "BOUND":
        blockers.add("PAPER_RUNTIME_BINDING_NOT_BOUND")
    binding_record = None
    certification = None
    account = None
    if binding.get("binding_id"):
        binding_record = db.scalar(
            select(CanonicalParserPaperRuntimeBinding).where(
                CanonicalParserPaperRuntimeBinding.binding_id == binding["binding_id"]
            )
        )
    if binding_record is not None:
        certification = db.get(CanonicalParserPaperAdmissionCertification, binding_record.certification_db_id)
        account = db.get(PaperAccount, binding_record.paper_account_id)
    if certification is None:
        blockers.add("PAPER_ADMISSION_CERTIFICATION_MISSING")
    if account is None:
        blockers.add("PAPER_ACCOUNT_NOT_FOUND")
    if account is None or certification is None:
        account_state = None
        account_state_hash = None
        source_snapshot: dict[str, Any] = {"projection_runs": [], "results": []}
        source_evidence_hash = calculate_payload_hash(source_snapshot)
        evaluated: list[dict[str, Any]] = []
        metrics = {"source_result_count": 0, "admissible_count": 0, "review_count": 0, "blocked_count": 0}
        run_status = "INSUFFICIENT_DATA"
        reasons = sorted(blockers)
    else:
        account_state = _account_state(db, account)
        account_state_hash = calculate_payload_hash(account_state)
        sources, source_snapshot, source_evidence_hash = _source_rows(db, certification, policy=policy)
        evaluated, metrics, run_status, reasons = _evaluate(sources, account_state, policy)
        blockers.update(reasons if run_status == "BLOCKED" else [])
    manifest = {
        "binding_id": binding.get("binding_id"),
        "binding_event_hash": binding.get("latest_event_hash"),
        "certification_id": certification.certification_id if certification else None,
        "assessment_id": certification.assessment_id if certification else None,
        "paper_account_id": account.id if account else None,
        "source_evidence_hash": source_evidence_hash,
        "account_state_hash": account_state_hash,
        "policy_hash": policy_hash,
    }
    canary_key = calculate_payload_hash(manifest)
    return {
        "eligible": not blockers and run_status in {"PASSED", "REVIEW", "BLOCKED", "INSUFFICIENT_DATA"},
        "status": run_status,
        "reason_codes": sorted(set(reasons) | blockers),
        "canary_key": canary_key,
        "confirmation": f"{PAPER_ADMISSION_CANARY_PREFIX}:{canary_key[:16]}",
        "binding_db_id": binding_record.id if binding_record else None,
        "binding": sanitize_technical_metadata(binding),
        "certification_id": certification.certification_id if certification else None,
        "assessment_id": certification.assessment_id if certification else None,
        "paper_account_id": account.id if account else None,
        "source_evidence_hash": source_evidence_hash,
        "source_snapshot": sanitize_technical_metadata(source_snapshot),
        "account_state_hash": account_state_hash,
        "account_state": sanitize_technical_metadata(account_state),
        "policy": policy,
        "policy_hash": policy_hash,
        "metrics": metrics,
        "results": evaluated,
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
    }


def _serialize_run(run: CanonicalParserPaperAdmissionCanaryRun) -> dict[str, Any]:
    return {
        "canary_id": run.canary_id,
        "canary_key": run.canary_key,
        "binding_id": run.binding_id,
        "binding_event_hash": run.binding_event_hash,
        "certification_id": run.certification_id,
        "assessment_id": run.assessment_id,
        "paper_account_id": run.paper_account_id,
        "source_result_count": run.source_result_count,
        "admissible_count": run.admissible_count,
        "review_count": run.review_count,
        "blocked_count": run.blocked_count,
        "status": run.status,
        "source_evidence_hash": run.source_evidence_hash,
        "account_state_hash": run.account_state_hash,
        "account_state_snapshot": run.account_state_snapshot,
        "policy_version": run.policy_version,
        "policy_hash": run.policy_hash,
        "policy_snapshot": run.policy_snapshot,
        "metrics_snapshot": run.metrics_snapshot,
        "reason_codes": run.reason_codes,
        "actor_label": run.actor_label,
        "note": run.note,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "valid_until": run.valid_until,
        "paper_execution_authorized": False,
        "live_execution_authorized": False,
    }


def run_paper_admission_canary(
    db: Session, *, confirmation: str, actor_label: str | None = None,
    note: str | None = None, settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_PAPER_ADMISSION_CANARY_ENABLED", False)):
        raise CanonicalParserPaperAdmissionCanaryError(
            "PAPER admission canary disabilitato.",
            code="CANONICAL_PARSER_PAPER_ADMISSION_CANARY_DISABLED",
            status_code=409,
        )
    now = _aware(evaluated_at)
    preview = preview_paper_admission_canary(db, settings_object=settings_object, evaluated_at=now)
    existing = db.scalar(
        select(CanonicalParserPaperAdmissionCanaryRun).where(
            CanonicalParserPaperAdmissionCanaryRun.canary_key == preview["canary_key"]
        )
    )
    if existing is not None:
        return get_paper_admission_canary_run(db, existing.canary_id)
    if confirmation != preview["confirmation"]:
        raise CanonicalParserPaperAdmissionCanaryError(
            "Conferma PAPER admission canary non valida.",
            code="PAPER_ADMISSION_CANARY_CONFIRMATION_REQUIRED",
            status_code=409,
        )
    if not preview["eligible"]:
        raise CanonicalParserPaperAdmissionCanaryError(
            "PAPER admission canary non idoneo.",
            code=preview["reason_codes"][0],
            status_code=409,
        )
    run = CanonicalParserPaperAdmissionCanaryRun(
        canary_id=str(uuid4()),
        canary_key=preview["canary_key"],
        binding_db_id=preview["binding_db_id"],
        binding_id=preview["binding"]["binding_id"],
        binding_event_hash=preview["binding"]["latest_event_hash"],
        certification_id=preview["certification_id"],
        assessment_id=preview["assessment_id"],
        paper_account_id=preview["paper_account_id"],
        source_result_count=preview["metrics"]["source_result_count"],
        admissible_count=preview["metrics"]["admissible_count"],
        review_count=preview["metrics"]["review_count"],
        blocked_count=preview["metrics"]["blocked_count"],
        status=preview["status"],
        source_evidence_hash=preview["source_evidence_hash"],
        account_state_hash=preview["account_state_hash"],
        account_state_snapshot=preview["account_state"],
        policy_version=PAPER_ADMISSION_CANARY_POLICY_VERSION,
        policy_hash=preview["policy_hash"],
        policy_snapshot=preview["policy"],
        metrics_snapshot=preview["metrics"],
        reason_codes=preview["reason_codes"],
        actor_label=_actor(actor_label),
        note=_note(note),
        started_at=now,
        completed_at=now,
        valid_until=now + timedelta(minutes=int(preview["policy"]["validity_minutes"])),
    )
    db.add(run)
    try:
        db.flush()
        for item in preview["results"]:
            db.add(CanonicalParserPaperAdmissionCanaryResult(
                result_id=str(uuid4()),
                canary_run_db_id=run.id,
                sequence=item["sequence"],
                source_projection_result_db_id=item["source_db_id"],
                source_projection_result_id=item["source_result_id"],
                source_projection_hash=item["source_projection_hash"],
                status=item["status"],
                action=item["action"],
                token_mint=item["token_mint"],
                token_amount=item["token_amount"],
                sol_amount=item["sol_amount"],
                projected_cash_after_sol=item["projected_cash_after_sol"],
                projected_open_positions=item["projected_open_positions"],
                canary_payload={key: value for key, value in item.items() if key not in {"source_db_id", "canary_hash"}},
                reason_codes=item["reason_codes"],
                canary_hash=item["canary_hash"],
            ))
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(
            select(CanonicalParserPaperAdmissionCanaryRun).where(
                CanonicalParserPaperAdmissionCanaryRun.canary_key == preview["canary_key"]
            )
        )
        if existing is not None:
            return get_paper_admission_canary_run(db, existing.canary_id)
        raise CanonicalParserPaperAdmissionCanaryError(
            "Conflitto durante il PAPER admission canary.",
            code="PAPER_ADMISSION_CANARY_CONFLICT",
            status_code=409,
        ) from exc
    db.refresh(run)
    return get_paper_admission_canary_run(db, run.canary_id)


def get_paper_admission_canary_run(db: Session, canary_id: str) -> dict[str, Any]:
    run = db.scalar(
        select(CanonicalParserPaperAdmissionCanaryRun).where(
            CanonicalParserPaperAdmissionCanaryRun.canary_id == canary_id
        )
    )
    if run is None:
        raise CanonicalParserPaperAdmissionCanaryError(
            "PAPER admission canary non trovato.",
            code="PAPER_ADMISSION_CANARY_NOT_FOUND",
            status_code=404,
        )
    payload = _serialize_run(run)
    results = list(
        db.scalars(
            select(CanonicalParserPaperAdmissionCanaryResult)
            .where(CanonicalParserPaperAdmissionCanaryResult.canary_run_db_id == run.id)
            .order_by(CanonicalParserPaperAdmissionCanaryResult.sequence.asc())
        )
    )
    payload["results"] = [
        {
            "result_id": item.result_id,
            "sequence": item.sequence,
            "source_projection_result_id": item.source_projection_result_id,
            "status": item.status,
            "action": item.action,
            "token_mint": item.token_mint,
            "token_amount": item.token_amount,
            "sol_amount": item.sol_amount,
            "projected_cash_after_sol": item.projected_cash_after_sol,
            "projected_open_positions": item.projected_open_positions,
            "reason_codes": item.reason_codes,
            "canary_hash": item.canary_hash,
        }
        for item in results
    ]
    return payload


def resolve_paper_admission_canary(
    db: Session, *, settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    run = db.scalar(
        select(CanonicalParserPaperAdmissionCanaryRun)
        .order_by(CanonicalParserPaperAdmissionCanaryRun.completed_at.desc())
        .limit(1)
    )
    if run is None:
        return {
            "resolved_status": "UNTESTED",
            "canary_id": None,
            "paper_execution_authorized": False,
            "live_execution_authorized": False,
        }
    payload = _serialize_run(run)
    if _aware(run.valid_until) <= now:
        payload["resolved_status"] = "EXPIRED"
        return payload
    preview = preview_paper_admission_canary(db, settings_object=settings_object, evaluated_at=now)
    if (
        preview.get("binding", {}).get("binding_id") != run.binding_id
        or preview.get("binding", {}).get("latest_event_hash") != run.binding_event_hash
        or preview.get("source_evidence_hash") != run.source_evidence_hash
        or preview.get("account_state_hash") != run.account_state_hash
        or preview.get("policy_hash") != run.policy_hash
    ):
        payload["resolved_status"] = "DRIFTED"
        return payload
    payload["resolved_status"] = run.status
    return payload


def get_paper_admission_canary_status(db: Session, *, settings_object: Any = settings) -> dict[str, Any]:
    return {
        "enabled": bool(getattr(settings_object, "CANONICAL_PARSER_PAPER_ADMISSION_CANARY_ENABLED", False)),
        "policy": _policy_snapshot(settings_object),
        "run_count": int(db.scalar(select(func.count(CanonicalParserPaperAdmissionCanaryRun.id))) or 0),
        "result_count": int(db.scalar(select(func.count(CanonicalParserPaperAdmissionCanaryResult.id))) or 0),
        "operational_guards": {
            "manual_canary_only": True,
            "paper_account_reads": True,
            "paper_position_reads": True,
            "paper_account_writes": False,
            "paper_order_writes": False,
            "paper_position_writes": False,
            "trade_writes": False,
            "price_requests_allowed": False,
            "external_requests_allowed": False,
            "paper_execution_authorized": False,
            "live_execution_authorized": False,
        },
    }
