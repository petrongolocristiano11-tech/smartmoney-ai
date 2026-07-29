from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.models.blockchain_integrity import (
    CanonicalParserControlledLiveSubmission,
    CanonicalParserGovernedLivePosition,
    CanonicalParserIsolatedSignerProfile,
    CanonicalParserLiveOnchainSettlement,
    CanonicalParserLiveOnchainSettlementEvent,
    CanonicalParserLiveTransactionDryRun,
    CanonicalParserMicroLiveCanarySimulation,
    CanonicalParserUnifiedDecisionResult,
)
from backend.app.services.blockchain_integrity_service import (
    calculate_payload_hash,
    sanitize_error_message,
)
from backend.app.services.solana_rpc import SolanaRpcClient

POLICY_VERSION = "canonical-parser-live-onchain-settlement/1"
SETTLE_PREFIX = "SETTLE_M39_AUTHORITATIVE_ONCHAIN"
_MONEY = Decimal("0.000000001")
_ZERO = Decimal("0")


class CanonicalParserLiveOnchainSettlementError(ValueError):
    def __init__(self, message: str, *, code: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime | None) -> datetime:
    value = value or _now()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _decimal(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CanonicalParserLiveOnchainSettlementError(
            "Valore numerico M39 non valido.", code="M39_INVALID_NUMBER"
        ) from exc
    if not result.is_finite():
        raise CanonicalParserLiveOnchainSettlementError(
            "Valore numerico M39 non finito.", code="M39_INVALID_NUMBER"
        )
    return result


def _money(value: Any) -> Decimal:
    return _decimal(value).quantize(_MONEY)


def _actor(value: str | None) -> str:
    return str(value or "MANUAL_OPERATOR").strip()[:80] or "MANUAL_OPERATOR"


def _note(value: str | None) -> str | None:
    value = str(value or "").strip()
    return value[:500] if value else None


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return _aware(value).isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _policy(settings_object: Any = settings) -> dict[str, Any]:
    return {
        "version": POLICY_VERSION,
        "enabled": bool(getattr(settings_object, "CANONICAL_PARSER_LIVE_ONCHAIN_SETTLEMENT_ENABLED", False)),
        "rpc_enabled": bool(getattr(settings_object, "CANONICAL_PARSER_LIVE_ONCHAIN_SETTLEMENT_RPC_ENABLED", False)),
        "require_finalized": bool(getattr(settings_object, "CANONICAL_PARSER_LIVE_ONCHAIN_SETTLEMENT_REQUIRE_FINALIZED", True)),
        "maximum_transaction_age_seconds": int(getattr(settings_object, "CANONICAL_PARSER_LIVE_ONCHAIN_SETTLEMENT_MAX_TRANSACTION_AGE_SECONDS", 900)),
        "maximum_buy_input_deviation_bps": int(getattr(settings_object, "CANONICAL_PARSER_LIVE_ONCHAIN_SETTLEMENT_MAX_BUY_INPUT_DEVIATION_BPS", 3000)),
        "manual_only": True,
        "legacy_position_write": False,
        "trade_write": False,
    }


def _account_key(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict):
        return str(item.get("pubkey") or item.get("address") or "")
    return str(item or "")


def _token_amount(item: dict[str, Any]) -> Decimal:
    ui = item.get("uiTokenAmount") if isinstance(item, dict) else None
    raw = ui.get("amount") if isinstance(ui, dict) else None
    return _decimal(raw or 0)


def _sum_token_balances(items: Any, *, wallet: str, mint: str) -> tuple[Decimal, bool]:
    matching: list[dict[str, Any]] = []
    for item in items or []:
        if not isinstance(item, dict) or str(item.get("mint") or "") != mint:
            continue
        owner = str(item.get("owner") or "")
        if owner == wallet:
            matching.append(item)
    if matching:
        return sum((_token_amount(item) for item in matching), _ZERO), True
    mint_only = [item for item in (items or []) if isinstance(item, dict) and str(item.get("mint") or "") == mint]
    if len(mint_only) == 1:
        return _token_amount(mint_only[0]), False
    return _ZERO, False


def inspect_settlement_transaction(
    transaction: dict[str, Any], *, wallet_address: str, token_mint: str, side: str
) -> dict[str, Any]:
    if not isinstance(transaction, dict):
        raise CanonicalParserLiveOnchainSettlementError(
            "Transazione M39 non disponibile.", code="M39_TRANSACTION_NOT_FOUND", status_code=404
        )
    meta = transaction.get("meta")
    tx = transaction.get("transaction")
    message = tx.get("message") if isinstance(tx, dict) else None
    keys = message.get("accountKeys") if isinstance(message, dict) else None
    if not isinstance(meta, dict) or not isinstance(keys, list):
        raise CanonicalParserLiveOnchainSettlementError(
            "Struttura transazione M39 incompleta.", code="M39_TRANSACTION_STRUCTURE_INVALID", status_code=502
        )
    account_keys = [_account_key(item) for item in keys]
    try:
        wallet_index = account_keys.index(wallet_address)
    except ValueError as exc:
        raise CanonicalParserLiveOnchainSettlementError(
            "Wallet signer non presente nella transazione.", code="M39_WALLET_NOT_IN_TRANSACTION", status_code=409
        ) from exc
    pre_balances = meta.get("preBalances") or []
    post_balances = meta.get("postBalances") or []
    if wallet_index >= len(pre_balances) or wallet_index >= len(post_balances):
        raise CanonicalParserLiveOnchainSettlementError(
            "Bilanci SOL M39 incompleti.", code="M39_SOL_BALANCES_MISSING", status_code=502
        )
    pre_token, pre_owner = _sum_token_balances(meta.get("preTokenBalances"), wallet=wallet_address, mint=token_mint)
    post_token, post_owner = _sum_token_balances(meta.get("postTokenBalances"), wallet=wallet_address, mint=token_mint)
    token_delta = post_token - pre_token
    sol_delta = _decimal(post_balances[wallet_index]) - _decimal(pre_balances[wallet_index])
    fee = _decimal(meta.get("fee") or 0)
    reasons: list[str] = []
    if meta.get("err") is not None:
        reasons.append("CHAIN_TRANSACTION_FAILED")
    if not (pre_owner or post_owner):
        reasons.append("TOKEN_OWNER_INFERRED")
    if side == "BUY" and token_delta <= 0:
        reasons.append("BUY_TOKEN_DELTA_NOT_POSITIVE")
    if side == "SELL" and token_delta >= 0:
        reasons.append("SELL_TOKEN_DELTA_NOT_NEGATIVE")
    input_lamports = max(_ZERO, -sol_delta - fee) if side == "BUY" else _ZERO
    output_lamports = max(_ZERO, sol_delta + fee) if side == "SELL" else _ZERO
    actual_input_raw = input_lamports if side == "BUY" else abs(token_delta)
    actual_output_raw = token_delta if side == "BUY" else output_lamports
    return {
        "slot": transaction.get("slot"),
        "block_time_epoch": transaction.get("blockTime"),
        "fee_lamports": fee,
        "wallet_sol_delta_lamports": sol_delta,
        "token_delta_raw": token_delta,
        "actual_input_amount_raw": actual_input_raw,
        "actual_output_amount_raw": actual_output_raw,
        "actual_input_sol": _money(input_lamports / Decimal(1_000_000_000)),
        "actual_output_sol": _money(output_lamports / Decimal(1_000_000_000)),
        "reason_codes": reasons,
        "wallet_index": wallet_index,
        "account_count": len(account_keys),
        "token_owner_evidence": bool(pre_owner or post_owner),
        "chain_error": meta.get("err"),
    }


def _serialize_position(row: CanonicalParserGovernedLivePosition) -> dict[str, Any]:
    return {
        "position_id": row.position_id,
        "status": row.status,
        "wallet_address": row.wallet_address,
        "token_mint": row.token_mint,
        "quantity_raw": str(row.quantity_raw),
        "cost_basis_sol": format(_money(row.cost_basis_sol), "f"),
        "realized_proceeds_sol": format(_money(row.realized_proceeds_sol), "f"),
        "realized_pnl_sol": format(_money(row.realized_pnl_sol), "f"),
        "high_watermark_value_sol": None if row.high_watermark_value_sol is None else format(_money(row.high_watermark_value_sol), "f"),
        "high_watermark_roi_percent": None if row.high_watermark_roi_percent is None else str(row.high_watermark_roi_percent),
        "exit_plan": row.exit_plan,
        "position_version": row.position_version,
        "opened_at": row.opened_at,
        "closed_at": row.closed_at,
    }


def _serialize(row: CanonicalParserLiveOnchainSettlement) -> dict[str, Any]:
    return {
        "settlement_id": row.settlement_id,
        "submission_id": row.submission_id,
        "position_id": row.position_id,
        "status": row.status,
        "side": row.side,
        "token_mint": row.token_mint,
        "wallet_address": row.wallet_address,
        "rpc_signature": row.rpc_signature,
        "confirmation_status": row.confirmation_status,
        "slot": row.slot,
        "block_time": row.block_time,
        "fee_lamports": str(row.fee_lamports),
        "wallet_sol_delta_lamports": str(row.wallet_sol_delta_lamports),
        "token_delta_raw": str(row.token_delta_raw),
        "actual_input_amount_raw": str(row.actual_input_amount_raw),
        "actual_output_amount_raw": str(row.actual_output_amount_raw),
        "actual_input_sol": format(_money(row.actual_input_sol), "f"),
        "actual_output_sol": format(_money(row.actual_output_sol), "f"),
        "reason_codes": row.reason_codes,
        "transaction_snapshot": row.transaction_snapshot,
        "attribution_snapshot": row.attribution_snapshot,
        "evidence_hash": row.evidence_hash,
        "settled_at": row.settled_at,
    }


def _event(db: Session, row: CanonicalParserLiveOnchainSettlement, *, event_type: str, payload: dict[str, Any], at: datetime) -> None:
    previous = db.scalar(
        select(CanonicalParserLiveOnchainSettlementEvent)
        .where(CanonicalParserLiveOnchainSettlementEvent.settlement_db_id == row.id)
        .order_by(CanonicalParserLiveOnchainSettlementEvent.sequence.desc())
        .limit(1)
    )
    sequence = 1 if previous is None else previous.sequence + 1
    previous_hash = None if previous is None else previous.event_hash
    event_payload = {
        "settlement_id": row.settlement_id,
        "sequence": sequence,
        "event_type": event_type,
        "occurred_at": at.isoformat(),
        "payload": payload,
        "previous_event_hash": previous_hash,
    }
    db.add(CanonicalParserLiveOnchainSettlementEvent(
        event_id=str(uuid4()), settlement_db_id=row.id, sequence=sequence,
        event_type=event_type, event_payload=event_payload,
        previous_event_hash=previous_hash, event_hash=calculate_payload_hash(event_payload), occurred_at=at,
    ))


def _context(db: Session, submission_id: str) -> tuple[Any, ...]:
    submission = db.scalar(select(CanonicalParserControlledLiveSubmission).where(CanonicalParserControlledLiveSubmission.submission_id == submission_id))
    if submission is None:
        raise CanonicalParserLiveOnchainSettlementError("Submission M38 non trovata.", code="M39_SUBMISSION_NOT_FOUND", status_code=404)
    dry_run = db.scalar(select(CanonicalParserLiveTransactionDryRun).where(CanonicalParserLiveTransactionDryRun.dry_run_id == submission.dry_run_id))
    if dry_run is None:
        raise CanonicalParserLiveOnchainSettlementError("Dry-run M36 non trovato.", code="M39_DRY_RUN_NOT_FOUND", status_code=404)
    profile = db.get(CanonicalParserIsolatedSignerProfile, dry_run.signer_profile_db_id)
    simulation = db.get(CanonicalParserMicroLiveCanarySimulation, dry_run.micro_live_simulation_db_id)
    decision = None if simulation is None else db.get(CanonicalParserUnifiedDecisionResult, simulation.decision_result_db_id)
    if profile is None or simulation is None or decision is None:
        raise CanonicalParserLiveOnchainSettlementError("Catena evidenze M35-M36 incompleta.", code="M39_EVIDENCE_CHAIN_INCOMPLETE", status_code=409)
    return submission, dry_run, profile, simulation, decision


def preview_live_onchain_settlement(
    db: Session, *, submission_id: str, settings_object: Any = settings,
    evaluated_at: datetime | None = None, rpc_client: SolanaRpcClient | None = None,
) -> dict[str, Any]:
    now = _aware(evaluated_at)
    policy = _policy(settings_object)
    submission, dry_run, profile, simulation, decision = _context(db, submission_id)
    existing = db.scalar(select(CanonicalParserLiveOnchainSettlement).where(CanonicalParserLiveOnchainSettlement.submission_db_id == submission.id))
    reasons: list[str] = []
    required = "FINALIZED" if policy["require_finalized"] else "CONFIRMED"
    acceptable = {"FINALIZED"} if required == "FINALIZED" else {"CONFIRMED", "FINALIZED"}
    if submission.status not in acceptable:
        reasons.append("SUBMISSION_NOT_FINALIZED" if required == "FINALIZED" else "SUBMISSION_NOT_CONFIRMED")
    signature = submission.rpc_signature or submission.expected_signature
    transaction = None
    inspection = None
    if not policy["rpc_enabled"]:
        reasons.append("M39_RPC_DISABLED")
    else:
        try:
            transaction = (rpc_client or SolanaRpcClient()).get_transaction_details(signature)
            if transaction is None:
                reasons.append("TRANSACTION_NOT_FOUND")
            else:
                inspection = inspect_settlement_transaction(transaction, wallet_address=profile.wallet_address, token_mint=submission.token_mint, side=submission.side)
                reasons.extend(inspection["reason_codes"])
                block_epoch = inspection.get("block_time_epoch")
                if block_epoch is not None:
                    block_time = datetime.fromtimestamp(int(block_epoch), tz=timezone.utc)
                    if now - block_time > timedelta(seconds=policy["maximum_transaction_age_seconds"]):
                        reasons.append("TRANSACTION_TOO_OLD")
                if submission.side == "BUY":
                    expected = _decimal(dry_run.amount_raw)
                    actual = _decimal(inspection["actual_input_amount_raw"])
                    deviation = abs(actual - expected) * Decimal(10_000) / expected if expected > 0 else Decimal(10_000)
                    if deviation > policy["maximum_buy_input_deviation_bps"]:
                        reasons.append("BUY_INPUT_DEVIATION_HIGH")
                elif _decimal(inspection["actual_input_amount_raw"]) != _decimal(dry_run.amount_raw):
                    reasons.append("SELL_INPUT_AMOUNT_MISMATCH")
        except CanonicalParserLiveOnchainSettlementError:
            raise
        except Exception as exc:
            reasons.append("RPC_TRANSACTION_UNAVAILABLE")
            inspection = {"error": sanitize_error_message(exc, max_length=500)}
    blocking = {"CHAIN_TRANSACTION_FAILED", "BUY_TOKEN_DELTA_NOT_POSITIVE", "SELL_TOKEN_DELTA_NOT_NEGATIVE", "SELL_INPUT_AMOUNT_MISMATCH"}
    insufficient = {"M39_RPC_DISABLED", "TRANSACTION_NOT_FOUND", "RPC_TRANSACTION_UNAVAILABLE", "SUBMISSION_NOT_FINALIZED", "SUBMISSION_NOT_CONFIRMED"}
    if any(r in blocking for r in reasons):
        status = "BLOCKED"
    elif any(r in insufficient for r in reasons):
        status = "INSUFFICIENT_DATA"
    elif reasons:
        status = "REVIEW"
    else:
        status = "SETTLED"
    settlement_key = calculate_payload_hash({"submission_id": submission_id, "signature": signature, "policy_version": POLICY_VERSION})
    evidence = {
        "submission_id": submission_id, "submission_status": submission.status,
        "dry_run_id": dry_run.dry_run_id, "permit_id": simulation.permit_id,
        "decision_result_id": decision.result_id, "wallet_address": profile.wallet_address,
        "side": submission.side, "token_mint": submission.token_mint,
        "signature": signature, "inspection": _jsonable(inspection), "reason_codes": sorted(set(reasons)), "policy": policy,
    }
    return {
        "status": status, "ready": status == "SETTLED", "existing_settlement": None if existing is None else _serialize(existing),
        "settlement_key": settlement_key, "reason_codes": sorted(set(reasons)), "inspection": inspection,
        "evidence_hash": calculate_payload_hash(evidence), "evidence": evidence,
        "confirmation": f"{SETTLE_PREFIX}:{submission_id}:{settlement_key}", "policy": policy,
    }


def settle_live_onchain_submission(
    db: Session, *, submission_id: str, confirmation: str, actor_label: str | None = None,
    note: str | None = None, settings_object: Any = settings, settled_at: datetime | None = None,
    rpc_client: SolanaRpcClient | None = None,
) -> dict[str, Any]:
    policy = _policy(settings_object)
    if not policy["enabled"]:
        raise CanonicalParserLiveOnchainSettlementError("M39 è disabilitata.", code="M39_DISABLED", status_code=409)
    now = _aware(settled_at)
    preview = preview_live_onchain_settlement(db, submission_id=submission_id, settings_object=settings_object, evaluated_at=now, rpc_client=rpc_client)
    if preview["existing_settlement"] is not None:
        return preview["existing_settlement"]
    if preview["status"] not in {"SETTLED", "REVIEW"}:
        raise CanonicalParserLiveOnchainSettlementError("Settlement M39 bloccato.", code="M39_SETTLEMENT_BLOCKED", status_code=409)
    if confirmation != preview["confirmation"]:
        raise CanonicalParserLiveOnchainSettlementError("Conferma M39 non valida.", code="M39_CONFIRMATION_REQUIRED", status_code=409)
    submission, dry_run, profile, simulation, decision = _context(db, submission_id)
    inspection = preview["inspection"]
    block_epoch = inspection.get("block_time_epoch")
    block_time = None if block_epoch is None else datetime.fromtimestamp(int(block_epoch), tz=timezone.utc)
    row = CanonicalParserLiveOnchainSettlement(
        settlement_id=str(uuid4()), settlement_key=preview["settlement_key"], scope="M39_AUTHORITATIVE_ONCHAIN_SETTLEMENT",
        submission_db_id=submission.id, submission_id=submission.submission_id, dry_run_id=dry_run.dry_run_id,
        micro_live_permit_id=simulation.permit_id, decision_result_id=decision.result_id, position_id=None,
        status=preview["status"], side=submission.side, token_mint=submission.token_mint, wallet_address=profile.wallet_address,
        rpc_signature=submission.rpc_signature or submission.expected_signature, confirmation_status=submission.confirmation_status,
        slot=inspection.get("slot"), block_time=block_time, fee_lamports=_decimal(inspection["fee_lamports"]),
        wallet_sol_delta_lamports=_decimal(inspection["wallet_sol_delta_lamports"]), token_delta_raw=_decimal(inspection["token_delta_raw"]),
        actual_input_amount_raw=_decimal(inspection["actual_input_amount_raw"]), actual_output_amount_raw=_decimal(inspection["actual_output_amount_raw"]),
        actual_input_sol=_money(inspection["actual_input_sol"]), actual_output_sol=_money(inspection["actual_output_sol"]),
        reason_codes=preview["reason_codes"], transaction_snapshot={
            "slot": inspection.get("slot"), "block_time": block_time.isoformat() if block_time else None,
            "fee_lamports": str(inspection["fee_lamports"]), "wallet_index": inspection.get("wallet_index"),
            "account_count": inspection.get("account_count"), "token_owner_evidence": inspection.get("token_owner_evidence"),
            "raw_transaction_persisted": False,
        }, attribution_snapshot={}, evidence_hash=preview["evidence_hash"], actor_label=_actor(actor_label), note=_note(note), settled_at=now,
    )
    db.add(row)
    db.flush()
    _event(db, row, event_type=row.status, payload={"reason_codes": row.reason_codes}, at=now)
    attribution: dict[str, Any] = {"position_action": "NONE"}
    if row.status == "SETTLED" and row.side == "BUY":
        quantity = _decimal(row.token_delta_raw)
        cost_basis = _money(row.actual_input_sol + (_decimal(row.fee_lamports) / Decimal(1_000_000_000)))
        position_key = calculate_payload_hash({"entry_settlement_id": row.settlement_id, "wallet": row.wallet_address, "token": row.token_mint})
        position = CanonicalParserGovernedLivePosition(
            position_id=str(uuid4()), position_key=position_key, scope="M39_GOVERNED_LIVE_POSITION_LEDGER",
            entry_settlement_db_id=row.id, entry_settlement_id=row.settlement_id, last_settlement_id=row.settlement_id,
            micro_live_permit_id=row.micro_live_permit_id, decision_result_id=row.decision_result_id,
            wallet_address=row.wallet_address, token_mint=row.token_mint, status="OPEN", quantity_raw=quantity,
            cost_basis_sol=cost_basis, realized_proceeds_sol=_MONEY, realized_pnl_sol=_MONEY,
            high_watermark_value_sol=cost_basis, high_watermark_roi_percent=Decimal("0"),
            exit_plan=decision.exit_plan or {"status": "MISSING"},
            position_snapshot={"entry_signature": row.rpc_signature, "entry_fee_lamports": str(row.fee_lamports), "source": "M39"},
            evidence_hash=calculate_payload_hash({"position_key": position_key, "quantity_raw": str(quantity), "cost_basis_sol": format(cost_basis, 'f'), "exit_plan": decision.exit_plan}),
            position_version=1, opened_at=block_time or now, last_assessed_at=None, closed_at=None,
        )
        db.add(position)
        db.flush()
        row.position_id = position.position_id
        attribution = {"position_action": "OPENED", "position_id": position.position_id, "quantity_raw": str(quantity), "cost_basis_sol": format(cost_basis, "f")}
        _event(db, row, event_type="POSITION_OPENED", payload=attribution, at=now)
    elif row.status == "SETTLED" and row.side == "SELL":
        positions = db.scalars(select(CanonicalParserGovernedLivePosition).where(
            CanonicalParserGovernedLivePosition.wallet_address == row.wallet_address,
            CanonicalParserGovernedLivePosition.token_mint == row.token_mint,
            CanonicalParserGovernedLivePosition.status == "OPEN",
        ).with_for_update()).all()
        if len(positions) != 1:
            row.status = "REVIEW"
            row.reason_codes = sorted(set(list(row.reason_codes or []) + ["OPEN_POSITION_ATTRIBUTION_AMBIGUOUS"]))
            attribution = {"position_action": "REVIEW", "candidate_position_count": len(positions)}
            _event(db, row, event_type="REVIEW", payload=attribution, at=now)
        else:
            position = positions[0]
            sold = min(_decimal(position.quantity_raw), abs(_decimal(row.token_delta_raw)))
            before_qty = _decimal(position.quantity_raw)
            cost_portion = _money(_decimal(position.cost_basis_sol) * sold / before_qty) if before_qty > 0 else _MONEY
            proceeds = _money(row.actual_output_sol)
            position.quantity_raw = before_qty - sold
            position.cost_basis_sol = _money(_decimal(position.cost_basis_sol) - cost_portion)
            position.realized_proceeds_sol = _money(_decimal(position.realized_proceeds_sol) + proceeds)
            position.realized_pnl_sol = _money(_decimal(position.realized_pnl_sol) + proceeds - cost_portion)
            position.last_settlement_id = row.settlement_id
            position.position_version += 1
            action = "CLOSED" if position.quantity_raw == 0 else "REDUCED"
            if action == "CLOSED":
                position.status = "CLOSED"
                position.closed_at = block_time or now
            row.position_id = position.position_id
            attribution = {"position_action": action, "position_id": position.position_id, "sold_quantity_raw": str(sold), "remaining_quantity_raw": str(position.quantity_raw), "realized_pnl_sol": format(_money(position.realized_pnl_sol), "f")}
            _event(db, row, event_type=f"POSITION_{action}", payload=attribution, at=now)
    row.attribution_snapshot = attribution
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        duplicate = db.scalar(select(CanonicalParserLiveOnchainSettlement).where(CanonicalParserLiveOnchainSettlement.submission_db_id == submission.id))
        if duplicate is not None:
            return _serialize(duplicate)
        raise CanonicalParserLiveOnchainSettlementError("Conflitto settlement M39.", code="M39_SETTLEMENT_CONFLICT", status_code=409) from exc
    db.refresh(row)
    result = _serialize(row)
    if row.position_id:
        position = db.scalar(select(CanonicalParserGovernedLivePosition).where(CanonicalParserGovernedLivePosition.position_id == row.position_id))
        result["position"] = None if position is None else _serialize_position(position)
    return result


def get_live_onchain_settlement(db: Session, settlement_id: str) -> dict[str, Any]:
    row = db.scalar(select(CanonicalParserLiveOnchainSettlement).where(CanonicalParserLiveOnchainSettlement.settlement_id == settlement_id))
    if row is None:
        raise CanonicalParserLiveOnchainSettlementError("Settlement M39 non trovato.", code="M39_SETTLEMENT_NOT_FOUND", status_code=404)
    return _serialize(row)


def get_governed_live_position(db: Session, position_id: str) -> dict[str, Any]:
    row = db.scalar(select(CanonicalParserGovernedLivePosition).where(CanonicalParserGovernedLivePosition.position_id == position_id))
    if row is None:
        raise CanonicalParserLiveOnchainSettlementError("Posizione M39 non trovata.", code="M39_POSITION_NOT_FOUND", status_code=404)
    return _serialize_position(row)


def resolve_live_onchain_settlement(db: Session) -> dict[str, Any]:
    latest = db.scalar(select(CanonicalParserLiveOnchainSettlement).order_by(CanonicalParserLiveOnchainSettlement.settled_at.desc()).limit(1))
    open_positions = db.scalars(select(CanonicalParserGovernedLivePosition).where(CanonicalParserGovernedLivePosition.status == "OPEN")).all()
    return {"latest_settlement": None if latest is None else _serialize(latest), "open_position_count": len(open_positions), "open_positions": [_serialize_position(row) for row in open_positions[:20]]}


def get_live_onchain_settlement_status(db: Session, *, settings_object: Any = settings) -> dict[str, Any]:
    return {"milestone": "M39", "policy": _policy(settings_object), "settlement_count": len(db.scalars(select(CanonicalParserLiveOnchainSettlement)).all()), "open_position_count": len(db.scalars(select(CanonicalParserGovernedLivePosition).where(CanonicalParserGovernedLivePosition.status == "OPEN")).all()), "safety": {"manual_only": True, "raw_transaction_persisted": False, "legacy_position_write": False, "trade_write": False}}
