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
    CanonicalParserControlledLiveSubmission,
    CanonicalParserGovernedLivePosition,
    CanonicalParserGovernedLivePositionAssessment,
    CanonicalParserLiveIncident,
    CanonicalParserLivePortfolioRiskAssessment,
    CanonicalParserLivePortfolioRiskPermit,
    CanonicalParserLivePortfolioRiskPermitEvent,
)
from backend.app.services.blockchain_integrity_service import calculate_payload_hash

POLICY_VERSION = "canonical-parser-live-portfolio-risk/1"
ASSESS_PREFIX = "ASSESS_M42_LIVE_PORTFOLIO_RISK"
PERMIT_PREFIX = "ISSUE_M42_LIVE_PORTFOLIO_RISK_PERMIT"
REVOKE_PREFIX = "REVOKE_M42_LIVE_PORTFOLIO_RISK_PERMIT"
_MONEY = Decimal("0.000000001")
_ACTIVE_SUBMISSION_STATUSES = {"RESERVED", "SUBMITTED", "PROCESSED", "CONFIRMED", "FINALIZED", "RECONCILIATION_REQUIRED"}
_ACTIVE_INCIDENT_STATUSES = {"OPEN", "ACKNOWLEDGED", "RECOVERY_AUTHORIZED"}


class CanonicalParserLivePortfolioRiskError(ValueError):
    def __init__(self, message: str, *, code: str, status_code: int = 422):
        super().__init__(message); self.code = code; self.status_code = status_code


def _now(value: datetime | None = None) -> datetime:
    resolved = value or datetime.now(timezone.utc)
    if resolved.tzinfo is None: return resolved.replace(tzinfo=timezone.utc)
    return resolved.astimezone(timezone.utc)


def _decimal(value: Any) -> Decimal:
    try: result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CanonicalParserLivePortfolioRiskError("Valore monetario M42 non valido.", code="M42_VALUE_INVALID") from exc
    if not result.is_finite(): raise CanonicalParserLivePortfolioRiskError("Valore monetario M42 non finito.", code="M42_VALUE_INVALID")
    return result.quantize(_MONEY)


def _actor(value: str | None) -> str:
    return str(value or "MANUAL_OPERATOR").strip()[:80] or "MANUAL_OPERATOR"


def _note(value: str | None) -> str | None:
    normalized = str(value or "").strip(); return normalized[:500] if normalized else None


def _policy(settings_object: Any = settings) -> dict[str, Any]:
    return {
        "version": POLICY_VERSION,
        "enabled": bool(getattr(settings_object, "CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_ENABLED", False)),
        "enforcement_enabled": bool(getattr(settings_object, "CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_ENFORCEMENT_ENABLED", False)),
        "assessment_ttl_seconds": int(getattr(settings_object, "CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_ASSESSMENT_TTL_SECONDS", 60)),
        "maximum_permit_validity_minutes": int(getattr(settings_object, "CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_MAX_PERMIT_VALIDITY_MINUTES", 10)),
        "maximum_total_exposure_sol": _decimal(getattr(settings_object, "CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_MAX_TOTAL_EXPOSURE_SOL", 0.05)),
        "maximum_pending_buy_sol": _decimal(getattr(settings_object, "CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_MAX_PENDING_BUY_SOL", 0.02)),
        "maximum_open_positions": int(getattr(settings_object, "CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_MAX_OPEN_POSITIONS", 3)),
        "maximum_token_concentration_percent": Decimal(str(getattr(settings_object, "CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_MAX_TOKEN_CONCENTRATION_PERCENT", 50.0))),
        "require_fresh_position_assessment": bool(getattr(settings_object, "CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_REQUIRE_FRESH_POSITION_ASSESSMENT", True)),
        "fail_on_high_incident": bool(getattr(settings_object, "CANONICAL_PARSER_LIVE_PORTFOLIO_RISK_FAIL_ON_HIGH_INCIDENT", True)),
        "manual_only": True,
    }


def _serialize_assessment(row: CanonicalParserLivePortfolioRiskAssessment) -> dict[str, Any]:
    return {"assessment_id": row.assessment_id, "wallet_address": row.wallet_address, "side": row.side,
            "requested_token_mint": row.requested_token_mint, "requested_budget_sol": format(_decimal(row.requested_budget_sol), "f"),
            "status": row.status, "open_position_count": row.open_position_count, "stale_position_count": row.stale_position_count,
            "active_incident_count": row.active_incident_count, "total_cost_basis_sol": format(_decimal(row.total_cost_basis_sol), "f"),
            "current_value_sol": format(_decimal(row.current_value_sol), "f"), "unrealized_pnl_sol": format(_decimal(row.unrealized_pnl_sol), "f"),
            "pending_buy_sol": format(_decimal(row.pending_buy_sol), "f"), "gross_exposure_sol": format(_decimal(row.gross_exposure_sol), "f"),
            "max_token_concentration_percent": str(row.max_token_concentration_percent), "largest_token_mint": row.largest_token_mint,
            "reason_codes": row.reason_codes, "position_breakdown": row.position_breakdown, "policy_snapshot": row.policy_snapshot,
            "evidence_hash": row.evidence_hash, "as_of": row.as_of, "assessed_at": row.assessed_at, "expires_at": row.expires_at}


def _resolved_permit_status(row: CanonicalParserLivePortfolioRiskPermit, now: datetime) -> str:
    if row.status == "ACTIVE" and _now(row.expires_at) <= now: return "EXPIRED"
    return row.status


def _serialize_permit(row: CanonicalParserLivePortfolioRiskPermit, *, now: datetime | None = None) -> dict[str, Any]:
    return {"permit_id": row.permit_id, "assessment_id": row.assessment_id, "wallet_address": row.wallet_address,
            "side": row.side, "token_mint": row.token_mint, "status": row.status, "resolved_status": _resolved_permit_status(row, _now(now)),
            "requested_budget_sol": format(_decimal(row.requested_budget_sol), "f"), "max_additional_exposure_sol": format(_decimal(row.max_additional_exposure_sol), "f"),
            "permit_snapshot": row.permit_snapshot, "evidence_hash": row.evidence_hash, "issued_at": row.issued_at, "expires_at": row.expires_at,
            "revoked_at": row.revoked_at, "consumed_at": row.consumed_at, "consumed_submission_id": row.consumed_submission_id,
            "latest_event_sequence": row.latest_event_sequence, "latest_event_hash": row.latest_event_hash}


def _append_permit_event(db: Session, row: CanonicalParserLivePortfolioRiskPermit, *, event_type: str, payload: dict[str, Any], at: datetime) -> None:
    sequence = int(row.latest_event_sequence or 0) + 1; previous = row.latest_event_hash if row.latest_event_sequence else None
    body = {"permit_id": row.permit_id, "sequence": sequence, "event_type": event_type, "occurred_at": at.isoformat(), "payload": payload, "previous_event_hash": previous}
    event_hash = calculate_payload_hash(body)
    db.add(CanonicalParserLivePortfolioRiskPermitEvent(event_id=str(uuid4()), permit_db_id=row.id, sequence=sequence, event_type=event_type,
                                                       event_payload=body, previous_event_hash=previous, event_hash=event_hash, occurred_at=at))
    row.latest_event_sequence = sequence; row.latest_event_hash = event_hash


def _latest_position_assessment(db: Session, position_id: str) -> CanonicalParserGovernedLivePositionAssessment | None:
    return db.scalar(select(CanonicalParserGovernedLivePositionAssessment).where(CanonicalParserGovernedLivePositionAssessment.position_id == position_id).order_by(CanonicalParserGovernedLivePositionAssessment.assessed_at.desc()).limit(1))


def preview_live_portfolio_risk_assessment(
    db: Session, *, wallet_address: str, side: str, requested_token_mint: str, requested_budget_sol: Any,
    as_of: datetime, idempotency_token: str, settings_object: Any = settings, evaluated_at: datetime | None = None,
) -> dict[str, Any]:
    now = _now(evaluated_at); observed = _now(as_of); policy = _policy(settings_object)
    wallet = str(wallet_address).strip(); side = str(side).strip().upper(); mint = str(requested_token_mint).strip(); token = str(idempotency_token or "").strip()
    if side not in {"BUY", "SELL"}: raise CanonicalParserLivePortfolioRiskError("Side M42 non valido.", code="M42_SIDE_INVALID")
    if len(wallet) < 32 or len(mint) < 32: raise CanonicalParserLivePortfolioRiskError("Wallet o mint M42 non valido.", code="M42_ADDRESS_INVALID")
    if len(token) < 8: raise CanonicalParserLivePortfolioRiskError("Idempotency token M42 non valido.", code="M42_IDEMPOTENCY_INVALID")
    requested = _decimal(requested_budget_sol)
    if side == "SELL": requested = Decimal("0").quantize(_MONEY)
    positions = list(db.scalars(select(CanonicalParserGovernedLivePosition).where(CanonicalParserGovernedLivePosition.wallet_address == wallet, CanonicalParserGovernedLivePosition.status == "OPEN").order_by(CanonicalParserGovernedLivePosition.opened_at.asc())))
    breakdown: list[dict[str, Any]] = []; token_values: dict[str, Decimal] = defaultdict(lambda: Decimal("0")); current_total = Decimal("0"); cost_total = Decimal("0"); stale = 0
    for position in positions:
        latest = _latest_position_assessment(db, position.position_id)
        fresh = latest is not None and _now(latest.expires_at) > observed
        if not fresh: stale += 1
        current = _decimal(latest.current_value_sol if fresh else position.cost_basis_sol)
        cost = _decimal(position.cost_basis_sol); current_total += current; cost_total += cost; token_values[position.token_mint] += current
        breakdown.append({"position_id": position.position_id, "token_mint": position.token_mint, "quantity_raw": str(position.quantity_raw),
                          "cost_basis_sol": format(cost, "f"), "current_value_sol": format(current, "f"), "fresh_assessment": fresh,
                          "assessment_id": None if latest is None else latest.assessment_id})
    pending_rows = list(db.scalars(select(CanonicalParserControlledLiveSubmission).where(CanonicalParserControlledLiveSubmission.side == "BUY", CanonicalParserControlledLiveSubmission.status.in_(sorted(_ACTIVE_SUBMISSION_STATUSES)))))
    pending = sum((_decimal(row.reserved_budget_sol) for row in pending_rows), Decimal("0")).quantize(_MONEY)
    prospective_values = dict(token_values)
    if side == "BUY": prospective_values[mint] = prospective_values.get(mint, Decimal("0")) + requested
    gross = (current_total + pending + (requested if side == "BUY" else Decimal("0"))).quantize(_MONEY)
    largest_mint = None; largest_value = Decimal("0")
    for token_mint, value in prospective_values.items():
        if value > largest_value: largest_mint, largest_value = token_mint, value
    concentration = (largest_value * Decimal("100") / gross) if gross > 0 else Decimal("0")
    incidents = list(db.scalars(select(CanonicalParserLiveIncident).where(CanonicalParserLiveIncident.status.in_(sorted(_ACTIVE_INCIDENT_STATUSES)), CanonicalParserLiveIncident.severity.in_(["HIGH", "CRITICAL"]))))
    reasons: list[str] = []
    prospective_count = len(positions) + (1 if side == "BUY" and not any(p.token_mint == mint for p in positions) else 0)
    if gross > policy["maximum_total_exposure_sol"]: reasons.append("TOTAL_EXPOSURE_LIMIT_EXCEEDED")
    if pending + (requested if side == "BUY" else Decimal("0")) > policy["maximum_pending_buy_sol"]: reasons.append("PENDING_BUY_LIMIT_EXCEEDED")
    if prospective_count > policy["maximum_open_positions"]: reasons.append("OPEN_POSITION_LIMIT_EXCEEDED")
    if side == "BUY" and concentration > policy["maximum_token_concentration_percent"]: reasons.append("TOKEN_CONCENTRATION_LIMIT_EXCEEDED")
    if policy["require_fresh_position_assessment"] and stale > 0: reasons.append("STALE_POSITION_ASSESSMENT")
    if policy["fail_on_high_incident"] and incidents and side == "BUY": reasons.append("ACTIVE_HIGH_SEVERITY_INCIDENT")
    blocking = {"TOTAL_EXPOSURE_LIMIT_EXCEEDED", "PENDING_BUY_LIMIT_EXCEEDED", "OPEN_POSITION_LIMIT_EXCEEDED", "TOKEN_CONCENTRATION_LIMIT_EXCEEDED", "ACTIVE_HIGH_SEVERITY_INCIDENT"}
    if any(r in blocking for r in reasons): status = "BLOCKED"
    elif "STALE_POSITION_ASSESSMENT" in reasons: status = "INSUFFICIENT_DATA"
    else: status = "READY"
    key = calculate_payload_hash({"wallet": wallet, "side": side, "mint": mint, "requested": format(requested, "f"), "as_of": observed.isoformat(), "token": token, "policy_version": POLICY_VERSION})
    existing = db.scalar(select(CanonicalParserLivePortfolioRiskAssessment).where(CanonicalParserLivePortfolioRiskAssessment.assessment_key == key))
    policy_json = {**policy, "maximum_total_exposure_sol": format(policy["maximum_total_exposure_sol"], "f"), "maximum_pending_buy_sol": format(policy["maximum_pending_buy_sol"], "f"), "maximum_token_concentration_percent": str(policy["maximum_token_concentration_percent"])}
    evidence = {"wallet_address": wallet, "side": side, "requested_token_mint": mint, "requested_budget_sol": format(requested, "f"),
                "open_position_count": len(positions), "prospective_position_count": prospective_count, "stale_position_count": stale,
                "active_incident_ids": [i.incident_id for i in incidents], "total_cost_basis_sol": format(cost_total.quantize(_MONEY), "f"),
                "current_value_sol": format(current_total.quantize(_MONEY), "f"), "pending_buy_sol": format(pending, "f"),
                "gross_exposure_sol": format(gross, "f"), "max_token_concentration_percent": str(concentration.quantize(Decimal("0.000001"))),
                "largest_token_mint": largest_mint, "position_breakdown": breakdown, "reason_codes": sorted(set(reasons)), "policy": policy_json}
    return {"status": status, "ready": status == "READY", "assessment_key": key, "existing_assessment": None if existing is None else _serialize_assessment(existing),
            "wallet_address": wallet, "side": side, "requested_token_mint": mint, "requested_budget_sol": format(requested, "f"),
            "open_position_count": len(positions), "stale_position_count": stale, "active_incident_count": len(incidents),
            "total_cost_basis_sol": format(cost_total.quantize(_MONEY), "f"), "current_value_sol": format(current_total.quantize(_MONEY), "f"),
            "unrealized_pnl_sol": format((current_total-cost_total).quantize(_MONEY), "f"), "pending_buy_sol": format(pending, "f"),
            "gross_exposure_sol": format(gross, "f"), "max_token_concentration_percent": str(concentration.quantize(Decimal("0.000001"))),
            "largest_token_mint": largest_mint, "reason_codes": sorted(set(reasons)), "position_breakdown": breakdown, "policy": policy_json,
            "evidence": evidence, "evidence_hash": calculate_payload_hash(evidence), "confirmation": f"{ASSESS_PREFIX}:{wallet}:{key}"}


def assess_live_portfolio_risk(db: Session, *, confirmation: str, actor_label: str | None = None, note: str | None = None,
                               assessed_at: datetime | None = None, settings_object: Any = settings, **kwargs: Any) -> dict[str, Any]:
    policy = _policy(settings_object)
    if not policy["enabled"]: raise CanonicalParserLivePortfolioRiskError("M42 è disabilitata.", code="M42_DISABLED", status_code=409)
    now = _now(assessed_at); preview = preview_live_portfolio_risk_assessment(db, settings_object=settings_object, evaluated_at=now, **kwargs)
    if preview["existing_assessment"] is not None: return preview["existing_assessment"]
    if confirmation != preview["confirmation"]: raise CanonicalParserLivePortfolioRiskError("Conferma assessment M42 non valida.", code="M42_ASSESSMENT_CONFIRMATION_REQUIRED", status_code=409)
    row = CanonicalParserLivePortfolioRiskAssessment(
        assessment_id=str(uuid4()), assessment_key=preview["assessment_key"], scope="M42_AGGREGATED_LIVE_PORTFOLIO_RISK",
        wallet_address=preview["wallet_address"], side=preview["side"], requested_token_mint=preview["requested_token_mint"], requested_budget_sol=_decimal(preview["requested_budget_sol"]),
        status=preview["status"], open_position_count=preview["open_position_count"], stale_position_count=preview["stale_position_count"], active_incident_count=preview["active_incident_count"],
        total_cost_basis_sol=_decimal(preview["total_cost_basis_sol"]), current_value_sol=_decimal(preview["current_value_sol"]), unrealized_pnl_sol=_decimal(preview["unrealized_pnl_sol"]),
        pending_buy_sol=_decimal(preview["pending_buy_sol"]), gross_exposure_sol=_decimal(preview["gross_exposure_sol"]),
        max_token_concentration_percent=Decimal(preview["max_token_concentration_percent"]), largest_token_mint=preview["largest_token_mint"],
        reason_codes=preview["reason_codes"], position_breakdown=preview["position_breakdown"], policy_snapshot=preview["policy"], evidence_hash=preview["evidence_hash"],
        actor_label=_actor(actor_label), note=_note(note), as_of=_now(kwargs["as_of"]), assessed_at=now, expires_at=now+timedelta(seconds=policy["assessment_ttl_seconds"]),
    )
    db.add(row)
    try: db.commit()
    except IntegrityError as exc:
        db.rollback(); existing = db.scalar(select(CanonicalParserLivePortfolioRiskAssessment).where(CanonicalParserLivePortfolioRiskAssessment.assessment_key == preview["assessment_key"]))
        if existing is not None: return _serialize_assessment(existing)
        raise CanonicalParserLivePortfolioRiskError("Conflitto assessment M42.", code="M42_ASSESSMENT_CONFLICT", status_code=409) from exc
    db.refresh(row); return _serialize_assessment(row)


def preview_live_portfolio_risk_permit(db: Session, *, assessment_id: str, validity_minutes: int, idempotency_token: str,
                                       settings_object: Any = settings, evaluated_at: datetime | None = None) -> dict[str, Any]:
    now = _now(evaluated_at); policy = _policy(settings_object); token = str(idempotency_token or "").strip()
    if len(token) < 8: raise CanonicalParserLivePortfolioRiskError("Idempotency token permit M42 non valido.", code="M42_IDEMPOTENCY_INVALID")
    assessment = db.scalar(select(CanonicalParserLivePortfolioRiskAssessment).where(CanonicalParserLivePortfolioRiskAssessment.assessment_id == assessment_id))
    if assessment is None: raise CanonicalParserLivePortfolioRiskError("Assessment M42 non trovato.", code="M42_ASSESSMENT_NOT_FOUND", status_code=404)
    minutes = int(validity_minutes); reasons: list[str] = []
    if _now(assessment.expires_at) <= now: reasons.append("ASSESSMENT_EXPIRED")
    if minutes < 1 or minutes > policy["maximum_permit_validity_minutes"]: reasons.append("PERMIT_VALIDITY_OUT_OF_RANGE")
    if assessment.side == "BUY" and assessment.status != "READY": reasons.append("BUY_ASSESSMENT_NOT_READY")
    if assessment.side == "SELL" and assessment.status == "INSUFFICIENT_DATA": reasons.append("SELL_ASSESSMENT_INSUFFICIENT_DATA")
    active = db.scalar(select(CanonicalParserLivePortfolioRiskPermit).where(CanonicalParserLivePortfolioRiskPermit.wallet_address == assessment.wallet_address,
        CanonicalParserLivePortfolioRiskPermit.side == assessment.side, CanonicalParserLivePortfolioRiskPermit.status == "ACTIVE", CanonicalParserLivePortfolioRiskPermit.expires_at > now))
    if active is not None: reasons.append("ACTIVE_PORTFOLIO_RISK_PERMIT_EXISTS")
    key = calculate_payload_hash({"assessment_id": assessment_id, "assessment_evidence_hash": assessment.evidence_hash, "token": token, "policy_version": POLICY_VERSION})
    existing = db.scalar(select(CanonicalParserLivePortfolioRiskPermit).where(CanonicalParserLivePortfolioRiskPermit.permit_key == key))
    max_additional = Decimal("0") if assessment.side == "SELL" else max(Decimal("0"), policy["maximum_total_exposure_sol"] - _decimal(assessment.gross_exposure_sol) + _decimal(assessment.requested_budget_sol))
    snapshot = {"assessment_id": assessment_id, "wallet_address": assessment.wallet_address, "side": assessment.side, "token_mint": assessment.requested_token_mint,
                "requested_budget_sol": format(_decimal(assessment.requested_budget_sol), "f"), "max_additional_exposure_sol": format(max_additional.quantize(_MONEY), "f"),
                "assessment_status": assessment.status, "assessment_evidence_hash": assessment.evidence_hash, "policy": {**policy, "maximum_total_exposure_sol": format(policy["maximum_total_exposure_sol"], "f"), "maximum_pending_buy_sol": format(policy["maximum_pending_buy_sol"], "f"), "maximum_token_concentration_percent": str(policy["maximum_token_concentration_percent"])}}
    return {"status": "READY" if not reasons else "BLOCKED", "ready": not reasons, "permit_key": key, "existing_permit": None if existing is None else _serialize_permit(existing, now=now),
            "assessment_id": assessment_id, "wallet_address": assessment.wallet_address, "side": assessment.side, "token_mint": assessment.requested_token_mint,
            "requested_budget_sol": format(_decimal(assessment.requested_budget_sol), "f"), "max_additional_exposure_sol": format(max_additional.quantize(_MONEY), "f"),
            "expires_at": now+timedelta(minutes=minutes), "reason_codes": sorted(set(reasons)), "evidence": snapshot, "evidence_hash": calculate_payload_hash(snapshot),
            "confirmation": f"{PERMIT_PREFIX}:{assessment_id}:{key}", "policy": policy}


def issue_live_portfolio_risk_permit(db: Session, *, assessment_id: str, validity_minutes: int, idempotency_token: str, confirmation: str,
                                     actor_label: str | None = None, note: str | None = None, issued_at: datetime | None = None,
                                     settings_object: Any = settings) -> dict[str, Any]:
    policy = _policy(settings_object)
    if not policy["enabled"]: raise CanonicalParserLivePortfolioRiskError("M42 è disabilitata.", code="M42_DISABLED", status_code=409)
    now = _now(issued_at); preview = preview_live_portfolio_risk_permit(db, assessment_id=assessment_id, validity_minutes=validity_minutes,
                                                                        idempotency_token=idempotency_token, settings_object=settings_object, evaluated_at=now)
    if preview["existing_permit"] is not None: return preview["existing_permit"]
    if not preview["ready"]: raise CanonicalParserLivePortfolioRiskError("Permit M42 bloccato.", code="M42_PERMIT_BLOCKED", status_code=409)
    if confirmation != preview["confirmation"]: raise CanonicalParserLivePortfolioRiskError("Conferma permit M42 non valida.", code="M42_PERMIT_CONFIRMATION_REQUIRED", status_code=409)
    assessment = db.scalar(select(CanonicalParserLivePortfolioRiskAssessment).where(CanonicalParserLivePortfolioRiskAssessment.assessment_id == assessment_id).with_for_update())
    permit_id = str(uuid4())
    initial_payload = {"assessment_id": assessment_id, "side": preview["side"]}
    initial_event_body = {
        "permit_id": permit_id,
        "sequence": 1,
        "event_type": "ISSUED",
        "occurred_at": now.isoformat(),
        "payload": initial_payload,
        "previous_event_hash": None,
    }
    initial_event_hash = calculate_payload_hash(initial_event_body)
    row = CanonicalParserLivePortfolioRiskPermit(
        permit_id=permit_id, permit_key=preview["permit_key"], scope="M42_MANUAL_PORTFOLIO_RISK_PERMIT", assessment_db_id=assessment.id, assessment_id=assessment.assessment_id,
        wallet_address=preview["wallet_address"], side=preview["side"], token_mint=preview["token_mint"], status="ACTIVE",
        requested_budget_sol=_decimal(preview["requested_budget_sol"]), max_additional_exposure_sol=_decimal(preview["max_additional_exposure_sol"]),
        permit_snapshot=preview["evidence"], evidence_hash=preview["evidence_hash"], actor_label=_actor(actor_label), note=_note(note),
        issued_at=now, expires_at=preview["expires_at"], revoked_at=None, consumed_at=None, consumed_submission_id=None,
        latest_event_sequence=1, latest_event_hash=initial_event_hash,
    )
    db.add(row); db.flush()
    db.add(CanonicalParserLivePortfolioRiskPermitEvent(
        event_id=str(uuid4()), permit_db_id=row.id, sequence=1, event_type="ISSUED",
        event_payload=initial_event_body, previous_event_hash=None, event_hash=initial_event_hash, occurred_at=now,
    ))
    db.commit(); db.refresh(row); return _serialize_permit(row, now=now)


def validate_portfolio_risk_permit_for_submission(db: Session, *, permit_id: str | None, side: str, token_mint: str,
                                                  requested_budget_sol: Any, wallet_address: str | None = None, settings_object: Any = settings,
                                                  evaluated_at: datetime | None = None, lock: bool = False) -> dict[str, Any]:
    policy = _policy(settings_object); now = _now(evaluated_at)
    if not policy["enforcement_enabled"]:
        return {"required": False, "ready": True, "reason_codes": [], "permit": None, "snapshot": {"enforcement_enabled": False}}
    reasons: list[str] = []
    if not permit_id:
        return {"required": True, "ready": False, "reason_codes": ["M42_PORTFOLIO_RISK_PERMIT_REQUIRED"], "permit": None, "snapshot": {"enforcement_enabled": True}}
    stmt = select(CanonicalParserLivePortfolioRiskPermit).where(CanonicalParserLivePortfolioRiskPermit.permit_id == permit_id)
    if lock: stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if row is None:
        return {"required": True, "ready": False, "reason_codes": ["M42_PORTFOLIO_RISK_PERMIT_NOT_FOUND"], "permit": None, "snapshot": {"permit_id": permit_id}}
    if row.status != "ACTIVE": reasons.append("M42_PORTFOLIO_RISK_PERMIT_NOT_ACTIVE")
    if _now(row.expires_at) <= now: reasons.append("M42_PORTFOLIO_RISK_PERMIT_EXPIRED")
    if row.side != str(side).upper(): reasons.append("M42_PORTFOLIO_RISK_PERMIT_SIDE_MISMATCH")
    if row.token_mint != token_mint: reasons.append("M42_PORTFOLIO_RISK_PERMIT_TOKEN_MISMATCH")
    if wallet_address is not None and row.wallet_address != str(wallet_address).strip():
        reasons.append("M42_PORTFOLIO_RISK_PERMIT_WALLET_MISMATCH")
    requested = _decimal(requested_budget_sol)
    if str(side).upper() == "BUY" and requested > _decimal(row.requested_budget_sol): reasons.append("M42_PORTFOLIO_RISK_PERMIT_BUDGET_EXCEEDED")
    snapshot = {"permit_id": row.permit_id, "assessment_id": row.assessment_id, "wallet_address": row.wallet_address, "side": row.side,
                "token_mint": row.token_mint, "requested_budget_sol": format(_decimal(row.requested_budget_sol), "f"), "expires_at": _now(row.expires_at).isoformat(),
                "evidence_hash": row.evidence_hash, "enforcement_enabled": True}
    return {"required": True, "ready": not reasons, "reason_codes": sorted(set(reasons)), "permit": row, "snapshot": snapshot}


def consume_portfolio_risk_permit(db: Session, *, permit_id: str, submission_id: str, side: str, token_mint: str,
                                  requested_budget_sol: Any, wallet_address: str | None = None,
                                  settings_object: Any = settings, consumed_at: datetime | None = None) -> dict[str, Any]:
    now = _now(consumed_at); validation = validate_portfolio_risk_permit_for_submission(db, permit_id=permit_id, side=side, token_mint=token_mint,
                                                                                         requested_budget_sol=requested_budget_sol, wallet_address=wallet_address,
                                                                                         settings_object=settings_object, evaluated_at=now, lock=True)
    if not validation["ready"]: raise CanonicalParserLivePortfolioRiskError("Permit M42 non utilizzabile.", code="M42_PERMIT_CONSUME_BLOCKED", status_code=409)
    row = validation["permit"]
    if row is None: return {"consumed": False, "enforcement_enabled": False}
    row.status = "CONSUMED"; row.consumed_at = now; row.consumed_submission_id = submission_id
    _append_permit_event(db, row, event_type="CONSUMED", payload={"submission_id": submission_id}, at=now)
    return {"consumed": True, "permit_id": row.permit_id, "submission_id": submission_id}


def revoke_live_portfolio_risk_permit(db: Session, *, permit_id: str, confirmation: str, reason: str, actor_label: str | None = None,
                                      revoked_at: datetime | None = None, settings_object: Any = settings) -> dict[str, Any]:
    if not _policy(settings_object)["enabled"]: raise CanonicalParserLivePortfolioRiskError("M42 è disabilitata.", code="M42_DISABLED", status_code=409)
    now = _now(revoked_at); row = db.scalar(select(CanonicalParserLivePortfolioRiskPermit).where(CanonicalParserLivePortfolioRiskPermit.permit_id == permit_id).with_for_update())
    if row is None: raise CanonicalParserLivePortfolioRiskError("Permit M42 non trovato.", code="M42_PERMIT_NOT_FOUND", status_code=404)
    if row.status != "ACTIVE": return _serialize_permit(row, now=now)
    expected = f"{REVOKE_PREFIX}:{row.permit_id}:{row.evidence_hash}"
    if confirmation != expected: raise CanonicalParserLivePortfolioRiskError("Conferma revoca M42 non valida.", code="M42_REVOKE_CONFIRMATION_REQUIRED", status_code=409)
    row.status = "REVOKED"; row.revoked_at = now; _append_permit_event(db, row, event_type="REVOKED", payload={"reason": str(reason)[:500], "actor_label": _actor(actor_label)}, at=now)
    db.commit(); db.refresh(row); return _serialize_permit(row, now=now)


def get_live_portfolio_risk_assessment(db: Session, assessment_id: str) -> dict[str, Any]:
    row = db.scalar(select(CanonicalParserLivePortfolioRiskAssessment).where(CanonicalParserLivePortfolioRiskAssessment.assessment_id == assessment_id))
    if row is None: raise CanonicalParserLivePortfolioRiskError("Assessment M42 non trovato.", code="M42_ASSESSMENT_NOT_FOUND", status_code=404)
    return _serialize_assessment(row)


def get_live_portfolio_risk_permit(db: Session, permit_id: str) -> dict[str, Any]:
    row = db.scalar(select(CanonicalParserLivePortfolioRiskPermit).where(CanonicalParserLivePortfolioRiskPermit.permit_id == permit_id))
    if row is None: raise CanonicalParserLivePortfolioRiskError("Permit M42 non trovato.", code="M42_PERMIT_NOT_FOUND", status_code=404)
    result = _serialize_permit(row)
    result["events"] = [{"sequence": e.sequence, "event_type": e.event_type, "event_hash": e.event_hash, "previous_event_hash": e.previous_event_hash, "event_payload": e.event_payload, "occurred_at": e.occurred_at}
                        for e in db.scalars(select(CanonicalParserLivePortfolioRiskPermitEvent).where(CanonicalParserLivePortfolioRiskPermitEvent.permit_db_id == row.id).order_by(CanonicalParserLivePortfolioRiskPermitEvent.sequence.asc()))]
    return result


def resolve_live_portfolio_risk(db: Session) -> dict[str, Any]:
    row = db.scalar(select(CanonicalParserLivePortfolioRiskAssessment).order_by(CanonicalParserLivePortfolioRiskAssessment.assessed_at.desc()).limit(1))
    permit = db.scalar(select(CanonicalParserLivePortfolioRiskPermit).order_by(CanonicalParserLivePortfolioRiskPermit.issued_at.desc()).limit(1))
    return {"latest_assessment": None if row is None else _serialize_assessment(row), "latest_permit": None if permit is None else _serialize_permit(permit),
            "resolved_status": "EMPTY" if row is None else row.status}


def get_live_portfolio_risk_status(db: Session, *, settings_object: Any = settings) -> dict[str, Any]:
    policy = _policy(settings_object)
    return {"enabled": policy["enabled"], "assessment_count": int(db.scalar(select(func.count(CanonicalParserLivePortfolioRiskAssessment.id))) or 0),
            "active_permit_count": int(db.scalar(select(func.count(CanonicalParserLivePortfolioRiskPermit.id)).where(CanonicalParserLivePortfolioRiskPermit.status == "ACTIVE")) or 0),
            "policy": {**policy, "maximum_total_exposure_sol": format(policy["maximum_total_exposure_sol"], "f"), "maximum_pending_buy_sol": format(policy["maximum_pending_buy_sol"], "f"), "maximum_token_concentration_percent": str(policy["maximum_token_concentration_percent"])},
            "safety": {"manual_only": True, "permit_single_use": True, "automatic_submission": False, "worker_connected": False, "scheduler_connected": False, "stream_connected": False}}
