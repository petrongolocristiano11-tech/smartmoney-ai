from __future__ import annotations

from collections import defaultdict
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
    CanonicalParserPaperCalibrationEvidence,
    CanonicalParserPaperExecutionPermit,
    CanonicalParserPermitBoundPaperExecution,
)
from backend.app.models.paper_account import PaperAccount
from backend.app.models.paper_order import PaperOrder
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    sanitize_error_message,
)

PAPER_CALIBRATION_POLICY_VERSION = "canonical-parser-paper-calibration/1"
PAPER_CALIBRATION_SCOPE = "PAPER_ANALYTICS_ONLY"
PAPER_CALIBRATION_PREFIX = "RUN_PAPER_CALIBRATION"
_MONEY_QUANTUM = Decimal("0.000000001")
_SCORE_QUANTUM = Decimal("0.0001")
_MAX_NOTE_LENGTH = 500


class CanonicalParserPaperCalibrationError(ValueError):
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
        result = Decimal(str(value or 0))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CanonicalParserPaperCalibrationError(
            "Valore numerico non valido.", code="PAPER_CALIBRATION_INVALID_NUMBER"
        ) from exc
    if not result.is_finite():
        raise CanonicalParserPaperCalibrationError(
            "Valore numerico non finito.", code="PAPER_CALIBRATION_INVALID_NUMBER"
        )
    return result.quantize(quantum)


def _money_text(value: Any) -> str:
    return format(_decimal(value), "f")


def _score_text(value: Any) -> str:
    return format(_decimal(value, quantum=_SCORE_QUANTUM), "f")


def _actor(value: str | None) -> str:
    return sanitize_error_message(value or "LOCAL_PAPER_CALIBRATION", max_length=80) or "LOCAL_PAPER_CALIBRATION"


def _note(value: str | None) -> str | None:
    if not str(value or "").strip():
        return None
    return sanitize_error_message(value, max_length=_MAX_NOTE_LENGTH)


def _policy(settings_object: Any) -> dict[str, Any]:
    return {
        "policy_version": PAPER_CALIBRATION_POLICY_VERSION,
        "default_lookback_days": int(
            getattr(settings_object, "CANONICAL_PARSER_PAPER_CALIBRATION_DEFAULT_LOOKBACK_DAYS", 30)
        ),
        "minimum_settled_attempts": int(
            getattr(settings_object, "CANONICAL_PARSER_PAPER_CALIBRATION_MIN_SETTLED_ATTEMPTS", 20)
        ),
        "minimum_closed_outcomes": int(
            getattr(settings_object, "CANONICAL_PARSER_PAPER_CALIBRATION_MIN_CLOSED_OUTCOMES", 10)
        ),
        "maximum_calibration_gap_percent": str(
            getattr(settings_object, "CANONICAL_PARSER_PAPER_CALIBRATION_MAX_CALIBRATION_GAP_PERCENT", 20.0)
        ),
        "minimum_reliability_score": str(
            getattr(settings_object, "CANONICAL_PARSER_PAPER_CALIBRATION_MIN_RELIABILITY_SCORE", 98.0)
        ),
        "reservation_timeout_minutes": int(
            getattr(
                settings_object,
                "CANONICAL_PARSER_PERMIT_BOUND_PAPER_EXECUTION_RESERVATION_TIMEOUT_MINUTES",
                10,
            )
        ),
        "automatic_policy_changes": False,
        "paper_only": True,
        "live_execution_authorized": False,
    }


def _serialize(row: CanonicalParserPaperCalibrationCampaign) -> dict[str, Any]:
    return {
        "campaign_id": row.campaign_id,
        "campaign_key": row.campaign_key,
        "scope": row.scope,
        "status": row.status,
        "paper_account_id": row.paper_account_id,
        "permit_id": row.permit_id,
        "attempt_count": row.attempt_count,
        "settled_count": row.settled_count,
        "released_count": row.released_count,
        "failed_count": row.failed_count,
        "reconciliation_required_count": row.reconciliation_required_count,
        "buy_count": row.buy_count,
        "sell_count": row.sell_count,
        "closed_outcome_count": row.closed_outcome_count,
        "winning_outcome_count": row.winning_outcome_count,
        "realized_pnl_sol": _money_text(row.realized_pnl_sol),
        "total_fee_sol": _money_text(row.total_fee_sol),
        "estimated_slippage_cost_sol": _money_text(row.estimated_slippage_cost_sol),
        "win_rate_percent": _score_text(row.win_rate_percent),
        "profit_factor": None if row.profit_factor is None else _money_text(row.profit_factor),
        "brier_score": None if row.brier_score is None else format(row.brier_score, "f"),
        "calibration_gap_percent": None if row.calibration_gap_percent is None else _score_text(row.calibration_gap_percent),
        "reliability_score": _score_text(row.reliability_score),
        "policy_version": row.policy_version,
        "policy_hash": row.policy_hash,
        "policy_snapshot": row.policy_snapshot,
        "summary": row.summary,
        "segments": row.segments,
        "recommendations": row.recommendations,
        "reason_codes": row.reason_codes,
        "evidence_hash": row.evidence_hash,
        "actor_label": row.actor_label,
        "note": row.note,
        "window_started_at": row.window_started_at,
        "window_ended_at": row.window_ended_at,
        "completed_at": row.completed_at,
    }


def _confidence_bucket(value: Decimal) -> str:
    score = float(value)
    if score < 50:
        return "0-49"
    if score < 60:
        return "50-59"
    if score < 70:
        return "60-69"
    if score < 80:
        return "70-79"
    if score < 90:
        return "80-89"
    return "90-100"


def _score_bucket(value: Decimal) -> str:
    score = float(value)
    if score < 60:
        return "0-59"
    if score < 70:
        return "60-69"
    if score < 80:
        return "70-79"
    if score < 90:
        return "80-89"
    return "90-100"


def _segment_summary(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row[key])].append(row)
    payload: dict[str, Any] = {}
    for segment, items in sorted(grouped.items()):
        sells = [item for item in items if item["side"] == "SELL" and item["status"] == "SETTLED"]
        pnl = sum((_decimal(item["realized_pnl_sol"]) for item in sells), Decimal("0"))
        wins = sum(1 for item in sells if _decimal(item["realized_pnl_sol"]) > 0)
        payload[segment] = {
            "attempt_count": len(items),
            "settled_count": sum(1 for item in items if item["status"] == "SETTLED"),
            "closed_outcome_count": len(sells),
            "winning_outcome_count": wins,
            "win_rate_percent": round(wins / len(sells) * 100, 4) if sells else 0.0,
            "realized_pnl_sol": _money_text(pnl),
        }
    return payload


def _collect_attempts(
    db: Session,
    *,
    paper_account_id: int,
    permit_id: str | None,
    window_started_at: datetime,
    window_ended_at: datetime,
) -> list[CanonicalParserPermitBoundPaperExecution]:
    query = select(CanonicalParserPermitBoundPaperExecution).where(
        CanonicalParserPermitBoundPaperExecution.paper_account_id == paper_account_id,
        CanonicalParserPermitBoundPaperExecution.created_at >= window_started_at,
        CanonicalParserPermitBoundPaperExecution.created_at <= window_ended_at,
    )
    if permit_id:
        query = query.where(CanonicalParserPermitBoundPaperExecution.permit_id == permit_id)
    return list(db.scalars(query.order_by(CanonicalParserPermitBoundPaperExecution.created_at.asc())))


def _budget_drift(db: Session, attempts: list[CanonicalParserPermitBoundPaperExecution]) -> list[dict[str, Any]]:
    permit_ids = sorted({row.permit_id for row in attempts})
    drifts: list[dict[str, Any]] = []
    for permit_id in permit_ids:
        permit = db.scalar(
            select(CanonicalParserPaperExecutionPermit).where(
                CanonicalParserPaperExecutionPermit.permit_id == permit_id
            )
        )
        if permit is None:
            drifts.append({"permit_id": permit_id, "reason": "PERMIT_MISSING"})
            continue
        all_attempts = list(
            db.scalars(
                select(CanonicalParserPermitBoundPaperExecution).where(
                    CanonicalParserPermitBoundPaperExecution.permit_id == permit_id
                )
            )
        )
        active = [row for row in all_attempts if row.status in {"RESERVED", "RECONCILIATION_REQUIRED", "SETTLED"}]
        expected_budget = sum((_decimal(row.reserved_budget_sol) for row in active), Decimal("0"))
        expected_orders = len(active)
        if expected_budget != _decimal(permit.consumed_budget_sol) or expected_orders != int(permit.consumed_order_count):
            drifts.append(
                {
                    "permit_id": permit_id,
                    "expected_budget_sol": _money_text(expected_budget),
                    "actual_budget_sol": _money_text(permit.consumed_budget_sol),
                    "expected_order_count": expected_orders,
                    "actual_order_count": int(permit.consumed_order_count),
                }
            )
    return drifts


def _build_analysis(
    db: Session,
    attempts: list[CanonicalParserPermitBoundPaperExecution],
    *,
    policy: dict[str, Any],
    window_ended_at: datetime,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for attempt in attempts:
        order = db.get(PaperOrder, attempt.paper_order_id) if attempt.paper_order_id else None
        realized_pnl = _decimal(order.realized_pnl_sol if order is not None else 0)
        fee = _decimal(order.fee_sol if order is not None else 0)
        slippage_cost = Decimal("0")
        if order is not None:
            market = _decimal(attempt.market_price_sol, quantum=Decimal("0.000000000000000001"))
            execution = _decimal(order.execution_price_sol, quantum=Decimal("0.000000000000000001"))
            quantity = _decimal(order.quantity, quantum=Decimal("0.000000000000000001"))
            if attempt.side == "BUY":
                slippage_cost = max(Decimal("0"), (execution - market) * quantity).quantize(_MONEY_QUANTUM)
            else:
                slippage_cost = max(Decimal("0"), (market - execution) * quantity).quantize(_MONEY_QUANTUM)
        rows.append(
            {
                "execution_id": attempt.execution_id,
                "status": attempt.status,
                "side": attempt.side,
                "token_mint": attempt.token_mint,
                "permit_id": attempt.permit_id,
                "paper_order_id": attempt.paper_order_id,
                "signal_score": _decimal(attempt.signal_score, quantum=_SCORE_QUANTUM),
                "confidence_score": _decimal(attempt.confidence_score, quantum=_SCORE_QUANTUM),
                "confidence_bucket": _confidence_bucket(_decimal(attempt.confidence_score, quantum=_SCORE_QUANTUM)),
                "signal_score_bucket": _score_bucket(_decimal(attempt.signal_score, quantum=_SCORE_QUANTUM)),
                "realized_pnl_sol": realized_pnl,
                "fee_sol": fee,
                "slippage_cost_sol": slippage_cost,
                "reserved_at": attempt.reserved_at,
            }
        )

    settled = [row for row in rows if row["status"] == "SETTLED"]
    sells = [row for row in settled if row["side"] == "SELL"]
    wins = [row for row in sells if row["realized_pnl_sol"] > 0]
    losses = [row for row in sells if row["realized_pnl_sol"] < 0]
    realized_pnl = sum((row["realized_pnl_sol"] for row in sells), Decimal("0"))
    total_fee = sum((row["fee_sol"] for row in settled), Decimal("0"))
    slippage_cost = sum((row["slippage_cost_sol"] for row in settled), Decimal("0"))
    gross_profit = sum((row["realized_pnl_sol"] for row in wins), Decimal("0"))
    gross_loss = abs(sum((row["realized_pnl_sol"] for row in losses), Decimal("0")))
    profit_factor = None if gross_loss == 0 else (gross_profit / gross_loss).quantize(_MONEY_QUANTUM)
    win_rate = Decimal("0") if not sells else (Decimal(len(wins)) / Decimal(len(sells)) * Decimal("100")).quantize(_SCORE_QUANTUM)

    brier_values: list[Decimal] = []
    if sells:
        for row in sells:
            probability = row["confidence_score"] / Decimal("100")
            outcome = Decimal("1") if row["realized_pnl_sol"] > 0 else Decimal("0")
            brier_values.append((probability - outcome) ** 2)
    brier_score = None if not brier_values else (sum(brier_values) / Decimal(len(brier_values))).quantize(Decimal("0.000000001"))
    avg_confidence = None if not sells else (sum((row["confidence_score"] for row in sells), Decimal("0")) / Decimal(len(sells))).quantize(_SCORE_QUANTUM)
    calibration_gap = None if avg_confidence is None else abs(avg_confidence - win_rate).quantize(_SCORE_QUANTUM)

    timeout_minutes = int(policy["reservation_timeout_minutes"])
    orphan_cutoff = window_ended_at - timedelta(minutes=timeout_minutes)
    orphans = [
        row
        for row in attempts
        if row.status in {"RESERVED", "RECONCILIATION_REQUIRED"} and _aware(row.reserved_at) <= orphan_cutoff
    ]
    budget_drifts = _budget_drift(db, attempts)
    duplicate_count = len(attempts) - len({row.idempotency_key for row in attempts})
    reliability_deductions = duplicate_count * 25 + len(orphans) * 20 + len(budget_drifts) * 25
    reliability_score = max(Decimal("0"), Decimal("100") - Decimal(reliability_deductions)).quantize(_SCORE_QUANTUM)

    reasons: set[str] = set()
    recommendations: list[str] = []
    if duplicate_count:
        reasons.add("IDEMPOTENCY_DUPLICATES_DETECTED")
        recommendations.append("Correggere le collisioni idempotenti prima di nuovi batch PAPER.")
    if orphans:
        reasons.add("ORPHAN_RESERVATIONS_DETECTED")
        recommendations.append("Riconciliare o rilasciare tutte le reservation M32 scadute.")
    if budget_drifts:
        reasons.add("PERMIT_BUDGET_DRIFT_DETECTED")
        recommendations.append("Riconciliare i contatori M30 con il ledger M32.")
    reconciliation_required_count = sum(1 for row in attempts if row.status == "RECONCILIATION_REQUIRED")
    if reconciliation_required_count:
        reasons.add("RECONCILIATION_REQUIRED_PRESENT")
    if len(settled) < int(policy["minimum_settled_attempts"]):
        reasons.add("SETTLED_SAMPLE_INSUFFICIENT")
        recommendations.append("Raccogliere più esecuzioni PAPER M32 prima di calibrare le soglie.")
    if len(sells) < int(policy["minimum_closed_outcomes"]):
        reasons.add("CLOSED_OUTCOME_SAMPLE_INSUFFICIENT")
        recommendations.append("Chiudere più posizioni PAPER per misurare PnL e calibrazione.")
    if calibration_gap is not None and calibration_gap > _decimal(policy["maximum_calibration_gap_percent"], quantum=_SCORE_QUANTUM):
        reasons.add("CONFIDENCE_CALIBRATION_GAP_HIGH")
        recommendations.append("Ricalibrare la confidence M31 usando dati fuori campione; nessun cambio automatico applicato.")
    if realized_pnl < 0:
        reasons.add("REALIZED_PNL_NEGATIVE")
        recommendations.append("Analizzare separatamente alpha, fee, slippage e timing prima di ampliare il PAPER.")
    if reliability_score < _decimal(policy["minimum_reliability_score"], quantum=_SCORE_QUANTUM):
        reasons.add("RELIABILITY_SCORE_BELOW_MINIMUM")

    blocked = bool(duplicate_count or orphans or budget_drifts or reconciliation_required_count)
    insufficient = len(settled) < int(policy["minimum_settled_attempts"]) or len(sells) < int(policy["minimum_closed_outcomes"])
    review = (
        realized_pnl < 0
        or (calibration_gap is not None and calibration_gap > _decimal(policy["maximum_calibration_gap_percent"], quantum=_SCORE_QUANTUM))
        or reliability_score < _decimal(policy["minimum_reliability_score"], quantum=_SCORE_QUANTUM)
    )
    if blocked:
        status = "BLOCKED"
    elif insufficient:
        status = "INSUFFICIENT_DATA"
    elif review:
        status = "REVIEW"
    else:
        status = "READY"

    summary = {
        "attempt_count": len(attempts),
        "settled_count": len(settled),
        "released_count": sum(1 for row in attempts if row.status == "RELEASED"),
        "failed_count": sum(1 for row in attempts if row.status == "FAILED"),
        "reconciliation_required_count": reconciliation_required_count,
        "buy_count": sum(1 for row in settled if row["side"] == "BUY"),
        "sell_count": len(sells),
        "closed_outcome_count": len(sells),
        "winning_outcome_count": len(wins),
        "realized_pnl_sol": _money_text(realized_pnl),
        "total_fee_sol": _money_text(total_fee),
        "estimated_slippage_cost_sol": _money_text(slippage_cost),
        "strategy_gross_before_execution_costs_sol": _money_text(realized_pnl + total_fee + slippage_cost),
        "win_rate_percent": _score_text(win_rate),
        "profit_factor": None if profit_factor is None else _money_text(profit_factor),
        "average_confidence_percent": None if avg_confidence is None else _score_text(avg_confidence),
        "brier_score": None if brier_score is None else format(brier_score, "f"),
        "calibration_gap_percent": None if calibration_gap is None else _score_text(calibration_gap),
        "reliability_score": _score_text(reliability_score),
        "idempotency_duplicate_count": duplicate_count,
        "orphan_reservation_count": len(orphans),
        "permit_budget_drift_count": len(budget_drifts),
        "budget_drifts": budget_drifts,
        "automatic_policy_changes": False,
    }
    segments = {
        "by_confidence_bucket": _segment_summary(rows, "confidence_bucket"),
        "by_signal_score_bucket": _segment_summary(rows, "signal_score_bucket"),
        "by_token": _segment_summary(rows, "token_mint"),
        "by_permit": _segment_summary(rows, "permit_id"),
    }
    return {
        "status": status,
        "rows": rows,
        "summary": summary,
        "segments": segments,
        "recommendations": recommendations,
        "reason_codes": sorted(reasons),
        "metrics": {
            "realized_pnl": realized_pnl,
            "total_fee": total_fee,
            "slippage_cost": slippage_cost,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
            "brier_score": brier_score,
            "calibration_gap": calibration_gap,
            "reliability_score": reliability_score,
        },
    }


def preview_paper_calibration_campaign(
    db: Session,
    *,
    paper_account_id: int,
    permit_id: str | None = None,
    lookback_days: int | None = None,
    window_started_at: datetime | None = None,
    window_ended_at: datetime | None = None,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    account = db.get(PaperAccount, paper_account_id)
    if account is None:
        raise CanonicalParserPaperCalibrationError(
            "Account PAPER non trovato.", code="PAPER_CALIBRATION_ACCOUNT_NOT_FOUND", status_code=404
        )
    now = _aware(evaluated_at)
    policy = _policy(settings_object)
    ended = _aware(window_ended_at) if window_ended_at else now
    if window_started_at:
        started = _aware(window_started_at)
    else:
        days = int(lookback_days or policy["default_lookback_days"])
        if days < 1 or days > 3650:
            raise CanonicalParserPaperCalibrationError(
                "lookback_days non valido.", code="PAPER_CALIBRATION_INVALID_WINDOW"
            )
        started = ended - timedelta(days=days)
    if started >= ended:
        raise CanonicalParserPaperCalibrationError(
            "La finestra M33 non è valida.", code="PAPER_CALIBRATION_INVALID_WINDOW"
        )
    attempts = _collect_attempts(
        db,
        paper_account_id=paper_account_id,
        permit_id=permit_id,
        window_started_at=started,
        window_ended_at=ended,
    )
    analysis = _build_analysis(db, attempts, policy=policy, window_ended_at=ended)
    policy_hash = calculate_payload_hash(policy)
    evidence_descriptor = [
        {
            "execution_id": row.execution_id,
            "status": row.status,
            "settlement_hash": row.settlement_hash,
            "reservation_hash": row.reservation_hash,
            "paper_order_id": row.paper_order_id,
        }
        for row in attempts
    ]
    evidence_hash = calculate_payload_hash(evidence_descriptor)
    campaign_key = calculate_payload_hash(
        {
            "paper_account_id": paper_account_id,
            "permit_id": permit_id,
            "window_started_at": started.isoformat(),
            "window_ended_at": ended.isoformat(),
            "policy_hash": policy_hash,
            "evidence_hash": evidence_hash,
        }
    )
    return {
        "status": analysis["status"],
        "paper_account_id": paper_account_id,
        "permit_id": permit_id,
        "window_started_at": started,
        "window_ended_at": ended,
        "policy": policy,
        "policy_hash": policy_hash,
        "campaign_key": campaign_key,
        "evidence_hash": evidence_hash,
        "summary": analysis["summary"],
        "segments": analysis["segments"],
        "recommendations": analysis["recommendations"],
        "reason_codes": analysis["reason_codes"],
        "confirmation": f"{PAPER_CALIBRATION_PREFIX}:{paper_account_id}:{campaign_key}",
        "safety": {
            "analytics_only": True,
            "automatic_policy_changes": False,
            "paper_order_writes": False,
            "paper_position_writes": False,
            "trade_writes": False,
            "external_requests_allowed": False,
            "live_execution_authorized": False,
        },
    }


def run_paper_calibration_campaign(
    db: Session,
    *,
    paper_account_id: int,
    confirmation: str,
    permit_id: str | None = None,
    lookback_days: int | None = None,
    window_started_at: datetime | None = None,
    window_ended_at: datetime | None = None,
    actor_label: str | None = None,
    note: str | None = None,
    settings_object: Any = settings,
    evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    if not bool(getattr(settings_object, "CANONICAL_PARSER_PAPER_CALIBRATION_ENABLED", False)):
        raise CanonicalParserPaperCalibrationError(
            "M33 è disabilitata. Il flag resta false di default.",
            code="PAPER_CALIBRATION_DISABLED",
            status_code=409,
        )
    preview = preview_paper_calibration_campaign(
        db,
        paper_account_id=paper_account_id,
        permit_id=permit_id,
        lookback_days=lookback_days,
        window_started_at=window_started_at,
        window_ended_at=window_ended_at,
        settings_object=settings_object,
        evaluated_at=evaluated_at,
    )
    if confirmation != preview["confirmation"]:
        raise CanonicalParserPaperCalibrationError(
            "Conferma M33 non valida.", code="PAPER_CALIBRATION_CONFIRMATION_REQUIRED", status_code=409
        )
    existing = db.scalar(
        select(CanonicalParserPaperCalibrationCampaign).where(
            CanonicalParserPaperCalibrationCampaign.campaign_key == preview["campaign_key"]
        )
    )
    if existing is not None:
        return _serialize(existing)
    attempts = _collect_attempts(
        db,
        paper_account_id=paper_account_id,
        permit_id=permit_id,
        window_started_at=_aware(preview["window_started_at"]),
        window_ended_at=_aware(preview["window_ended_at"]),
    )
    analysis = _build_analysis(
        db,
        attempts,
        policy=preview["policy"],
        window_ended_at=_aware(preview["window_ended_at"]),
    )
    metrics = analysis["metrics"]
    now = _aware(evaluated_at)
    campaign = CanonicalParserPaperCalibrationCampaign(
        campaign_id=str(uuid4()),
        campaign_key=preview["campaign_key"],
        scope=PAPER_CALIBRATION_SCOPE,
        status=analysis["status"],
        paper_account_id=paper_account_id,
        permit_id=permit_id,
        attempt_count=len(attempts),
        settled_count=sum(1 for row in attempts if row.status == "SETTLED"),
        released_count=sum(1 for row in attempts if row.status == "RELEASED"),
        failed_count=sum(1 for row in attempts if row.status == "FAILED"),
        reconciliation_required_count=sum(1 for row in attempts if row.status == "RECONCILIATION_REQUIRED"),
        buy_count=sum(1 for row in attempts if row.status == "SETTLED" and row.side == "BUY"),
        sell_count=sum(1 for row in attempts if row.status == "SETTLED" and row.side == "SELL"),
        closed_outcome_count=sum(1 for row in attempts if row.status == "SETTLED" and row.side == "SELL"),
        winning_outcome_count=sum(
            1
            for row in analysis["rows"]
            if row["status"] == "SETTLED" and row["side"] == "SELL" and row["realized_pnl_sol"] > 0
        ),
        realized_pnl_sol=metrics["realized_pnl"],
        total_fee_sol=metrics["total_fee"],
        estimated_slippage_cost_sol=metrics["slippage_cost"],
        win_rate_percent=metrics["win_rate"],
        profit_factor=metrics["profit_factor"],
        brier_score=metrics["brier_score"],
        calibration_gap_percent=metrics["calibration_gap"],
        reliability_score=metrics["reliability_score"],
        policy_version=PAPER_CALIBRATION_POLICY_VERSION,
        policy_hash=preview["policy_hash"],
        policy_snapshot=preview["policy"],
        summary=analysis["summary"],
        segments=analysis["segments"],
        recommendations=analysis["recommendations"],
        reason_codes=analysis["reason_codes"],
        evidence_hash=preview["evidence_hash"],
        actor_label=_actor(actor_label),
        note=_note(note),
        window_started_at=_aware(preview["window_started_at"]),
        window_ended_at=_aware(preview["window_ended_at"]),
        completed_at=now,
    )
    db.add(campaign)
    try:
        db.flush()
        row_by_id = {row.execution_id: row for row in attempts}
        for sequence, evidence in enumerate(analysis["rows"], start=1):
            attempt = row_by_id[evidence["execution_id"]]
            snapshot = {
                "execution_id": attempt.execution_id,
                "status": attempt.status,
                "side": attempt.side,
                "token_mint": attempt.token_mint,
                "permit_id": attempt.permit_id,
                "decision_result_id": attempt.decision_result_id,
                "decision_hash": attempt.decision_hash,
                "reservation_hash": attempt.reservation_hash,
                "settlement_hash": attempt.settlement_hash,
                "paper_order_id": attempt.paper_order_id,
                "paper_position_id": attempt.paper_position_id,
                "signal_score": _score_text(attempt.signal_score),
                "confidence_score": _score_text(attempt.confidence_score),
                "realized_pnl_sol": _money_text(evidence["realized_pnl_sol"]),
                "fee_sol": _money_text(evidence["fee_sol"]),
                "slippage_cost_sol": _money_text(evidence["slippage_cost_sol"]),
            }
            snapshot_hash = calculate_payload_hash(snapshot)
            db.add(
                CanonicalParserPaperCalibrationEvidence(
                    campaign_db_id=campaign.id,
                    sequence=sequence,
                    execution_db_id=attempt.id,
                    execution_id=attempt.execution_id,
                    execution_status=attempt.status,
                    side=attempt.side,
                    token_mint=attempt.token_mint,
                    signal_score=attempt.signal_score,
                    confidence_score=attempt.confidence_score,
                    realized_pnl_sol=evidence["realized_pnl_sol"],
                    evidence_snapshot=snapshot,
                    evidence_hash=snapshot_hash,
                )
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.scalar(
            select(CanonicalParserPaperCalibrationCampaign).where(
                CanonicalParserPaperCalibrationCampaign.campaign_key == preview["campaign_key"]
            )
        )
        if duplicate is not None:
            return _serialize(duplicate)
        raise CanonicalParserPaperCalibrationError(
            "Conflitto durante la campagna M33.", code="PAPER_CALIBRATION_CONFLICT", status_code=409
        ) from exc
    db.refresh(campaign)
    return _serialize(campaign)


def get_paper_calibration_campaign(db: Session, campaign_id: str) -> dict[str, Any]:
    campaign = db.scalar(
        select(CanonicalParserPaperCalibrationCampaign).where(
            CanonicalParserPaperCalibrationCampaign.campaign_id == campaign_id
        )
    )
    if campaign is None:
        raise CanonicalParserPaperCalibrationError(
            "Campagna M33 non trovata.", code="PAPER_CALIBRATION_NOT_FOUND", status_code=404
        )
    payload = _serialize(campaign)
    payload["evidence"] = [
        {
            "sequence": row.sequence,
            "execution_id": row.execution_id,
            "execution_status": row.execution_status,
            "side": row.side,
            "token_mint": row.token_mint,
            "signal_score": _score_text(row.signal_score),
            "confidence_score": _score_text(row.confidence_score),
            "realized_pnl_sol": _money_text(row.realized_pnl_sol),
            "evidence_hash": row.evidence_hash,
        }
        for row in db.scalars(
            select(CanonicalParserPaperCalibrationEvidence)
            .where(CanonicalParserPaperCalibrationEvidence.campaign_db_id == campaign.id)
            .order_by(CanonicalParserPaperCalibrationEvidence.sequence.asc())
        )
    ]
    return payload


def resolve_paper_calibration_campaign(db: Session, *, paper_account_id: int | None = None) -> dict[str, Any]:
    query = select(CanonicalParserPaperCalibrationCampaign)
    if paper_account_id is not None:
        query = query.where(CanonicalParserPaperCalibrationCampaign.paper_account_id == paper_account_id)
    latest = db.scalar(query.order_by(CanonicalParserPaperCalibrationCampaign.completed_at.desc()).limit(1))
    return {
        "resolved_status": "EMPTY" if latest is None else latest.status,
        "latest_campaign": None if latest is None else _serialize(latest),
    }


def get_paper_calibration_status(db: Session, *, settings_object: Any = settings) -> dict[str, Any]:
    return {
        "enabled": bool(getattr(settings_object, "CANONICAL_PARSER_PAPER_CALIBRATION_ENABLED", False)),
        "policy": _policy(settings_object),
        "campaign_count": int(db.scalar(select(func.count(CanonicalParserPaperCalibrationCampaign.id))) or 0),
        "evidence_count": int(db.scalar(select(func.count(CanonicalParserPaperCalibrationEvidence.id))) or 0),
        "operational_guards": {
            "analytics_only": True,
            "automatic_policy_changes": False,
            "paper_order_writes": False,
            "paper_position_writes": False,
            "trade_writes": False,
            "external_requests_allowed": False,
            "workers_started": False,
            "schedulers_started": False,
            "streams_started": False,
            "live_execution_authorized": False,
        },
    }
