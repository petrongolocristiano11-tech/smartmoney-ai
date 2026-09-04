from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.constants import SOL_MINT
from backend.app.models.gen4_copyability import (
    CanonicalParserGen4PromotedSelectiveActivation,
    CanonicalParserGen4PromotedSelectivePosition,
)
from backend.app.services.blockchain_parser_gen4_copyability_service import (
    _allocate_integer,
    _conservative_out_amount,
    _quote,
)
from backend.app.services.gen4_promoted_selective_lifecycle_service import (
    ACTIVATION_ACTIVE,
    ACTIVATION_DRAINING,
    PROMOTED_POSITION_CLOSED,
    PROMOTED_POSITION_OPEN,
    PROMOTED_POSITION_OPEN_PARTIAL,
)
from backend.app.services.gen4_selective_challenger_lifecycle_bridge_design_service import (
    PROMOTED_SELECTIVE_SCOPE,
)
from backend.app.services.jupiter_swap_client import JupiterSwapClient
from backend.app.services.live_trading_errors import JupiterSwapError


PROMOTED_EXIT_RECOVERY_VERSION = "gen4-promoted-exit-autonomous-recovery-shadow/1"
PROMOTED_EXIT_RECOVERY_MAX_ATTEMPTS = 2
PROMOTED_EXIT_RECOVERY_MAX_AGE_SECONDS = 20
PROMOTED_EXIT_RECOVERY_BACKOFF_SECONDS = (2.0, 5.0)
PROMOTED_EXIT_RECOVERY_TICK_SECONDS = 1.0
PROMOTED_EXIT_RECOVERY_BATCH_LIMIT = 100

_RECOVERABLE_CODES = frozenset(
    {
        "JUPITER_HTTP_ERROR",
        "JUPITER_NETWORK_ERROR",
        "JUPITER_TIMEOUT",
        "JUPITER_REQUEST_EXHAUSTED",
    }
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif value not in (None, ""):
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _safe_error_payload(value: Any, *, depth: int = 0) -> Any:
    if depth > 4:
        return "<depth-limited>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return value[:800]
    if isinstance(value, dict):
        return {
            str(key)[:120]: _safe_error_payload(item, depth=depth + 1)
            for key, item in list(value.items())[:40]
        }
    if isinstance(value, (list, tuple)):
        return [_safe_error_payload(item, depth=depth + 1) for item in list(value)[:40]]
    return str(value)[:800]


def promoted_exit_error_snapshot(exc: JupiterSwapError) -> dict[str, Any]:
    return {
        "code": str(exc.code),
        "message": str(getattr(exc, "message", str(exc)))[:800],
        "status_code": int(getattr(exc, "status_code", 0) or 0),
        "payload": _safe_error_payload(dict(getattr(exc, "payload", {}) or {})),
    }


def is_recoverable_promoted_exit_error(exc: JupiterSwapError) -> bool:
    return str(exc.code or "").strip().upper() in _RECOVERABLE_CODES


def _history_append(evidence: dict[str, Any], item: dict[str, Any]) -> None:
    history = list(evidence.get("exit_recovery_history") or [])
    history.append(item)
    evidence["exit_recovery_history"] = history[-100:]


def _terminal_failure_append(
    position: CanonicalParserGen4PromotedSelectivePosition,
    *,
    signature: str,
    code: str,
    observed_at: datetime,
    details: dict[str, Any] | None,
    recovery_id: str | None,
) -> None:
    evidence = dict(position.evidence or {})
    failures = list(evidence.get("exit_failures") or [])
    record: dict[str, Any] = {
        "signature": str(signature),
        "code": str(code),
        "observed_at": observed_at.isoformat(),
    }
    if details:
        record["details"] = _safe_error_payload(details)
    if recovery_id:
        record["recovery_id"] = str(recovery_id)
        record["terminal_after_autonomous_recovery"] = True
    failures.append(record)
    evidence["exit_failures"] = failures[-100:]
    position.evidence = evidence


def schedule_promoted_exit_recovery(
    positions: list[CanonicalParserGen4PromotedSelectivePosition],
    *,
    signature: str,
    sell_fraction: float,
    sold_allocations: list[int],
    observed_at: datetime,
    error: JupiterSwapError,
) -> dict[str, Any]:
    if len(positions) != len(sold_allocations):
        raise ValueError("PROMOTED_EXIT_RECOVERY_ALLOCATION_LENGTH_MISMATCH")
    recovery_id = str(uuid4())
    now = _aware(observed_at) or _utc_now()
    next_retry = now + timedelta(seconds=PROMOTED_EXIT_RECOVERY_BACKOFF_SECONDS[0])
    error_snapshot = promoted_exit_error_snapshot(error)
    scheduled = 0
    total_requested_raw = 0

    for position, sold_raw in zip(positions, sold_allocations):
        requested_raw = max(0, min(int(position.remaining_token_raw), int(sold_raw)))
        if requested_raw <= 0:
            continue
        scheduled += 1
        total_requested_raw += requested_raw
        target_remaining = max(0, int(position.remaining_token_raw) - requested_raw)
        evidence = dict(position.evidence or {})
        pending = {
            "version": PROMOTED_EXIT_RECOVERY_VERSION,
            "state": "PENDING",
            "recovery_id": recovery_id,
            "source_signature": str(signature),
            "source_sell_fraction": float(sell_fraction),
            "requested_sell_token_raw": requested_raw,
            "target_remaining_token_raw": target_remaining,
            "scheduled_at_utc": now.isoformat(),
            "next_retry_at_utc": next_retry.isoformat(),
            "recovery_attempts": 0,
            "max_recovery_attempts": PROMOTED_EXIT_RECOVERY_MAX_ATTEMPTS,
            "max_recovery_age_seconds": PROMOTED_EXIT_RECOVERY_MAX_AGE_SECONDS,
            "initial_error": error_snapshot,
            "last_error": error_snapshot,
            "live_execution": False,
            "paper_execution": False,
            "signer_access": False,
            "transaction_submission": False,
        }
        evidence["pending_exit_recovery"] = pending
        _history_append(
            evidence,
            {
                "recovery_id": recovery_id,
                "state": "SCHEDULED",
                "observed_at_utc": now.isoformat(),
                "source_signature": str(signature),
                "requested_sell_token_raw": requested_raw,
                "target_remaining_token_raw": target_remaining,
                "error": error_snapshot,
            },
        )
        position.evidence = evidence

    return {
        "scheduled": scheduled > 0,
        "recovery_id": recovery_id,
        "positions_scheduled": scheduled,
        "requested_sell_token_raw": total_requested_raw,
        "next_retry_at_utc": next_retry.isoformat(),
        "max_recovery_attempts": PROMOTED_EXIT_RECOVERY_MAX_ATTEMPTS,
        "max_recovery_age_seconds": PROMOTED_EXIT_RECOVERY_MAX_AGE_SECONDS,
        "initial_error": error_snapshot,
        "live_execution": False,
        "signer_access": False,
        "transaction_submission": False,
    }


def _exit_rejection(
    policy: dict[str, Any],
    *,
    quote_latency_ms: int,
    out_amount: int,
    transaction_built: bool,
    price_impact_bps: float,
) -> str | None:
    if quote_latency_ms > int(policy.get("max_quote_latency_ms") or 5_000):
        return "EXIT_QUOTE_TOO_SLOW"
    if out_amount <= 0:
        return "EXIT_NO_EXECUTABLE_OUTPUT"
    if price_impact_bps > float(policy.get("max_price_impact_bps") or 500):
        return "EXIT_PRICE_IMPACT_TOO_HIGH"
    if not transaction_built:
        return "EXIT_UNSIGNED_TRANSACTION_NOT_BUILT"
    return None


def _mark_recovery_state(
    position: CanonicalParserGen4PromotedSelectivePosition,
    *,
    state: str,
    observed_at: datetime,
    extra: dict[str, Any] | None = None,
) -> None:
    evidence = dict(position.evidence or {})
    pending = dict(evidence.get("pending_exit_recovery") or {})
    if not pending:
        return
    pending["state"] = str(state)
    pending["resolved_at_utc"] = observed_at.isoformat()
    if extra:
        pending.update(_safe_error_payload(extra))
    evidence["pending_exit_recovery"] = pending
    _history_append(
        evidence,
        {
            "recovery_id": pending.get("recovery_id"),
            "state": str(state),
            "observed_at_utc": observed_at.isoformat(),
            **(_safe_error_payload(extra) if extra else {}),
        },
    )
    position.evidence = evidence


def _pending(position: CanonicalParserGen4PromotedSelectivePosition) -> dict[str, Any] | None:
    raw = dict(position.evidence or {}).get("pending_exit_recovery")
    if not isinstance(raw, dict):
        return None
    if str(raw.get("state") or "").upper() != "PENDING":
        return None
    if not str(raw.get("recovery_id") or "").strip():
        return None
    return dict(raw)


def _next_backoff(attempt_number: int) -> float:
    index = max(0, min(attempt_number, len(PROMOTED_EXIT_RECOVERY_BACKOFF_SECONDS) - 1))
    return float(PROMOTED_EXIT_RECOVERY_BACKOFF_SECONDS[index])


def _terminalize_group(
    positions: list[CanonicalParserGen4PromotedSelectivePosition],
    *,
    pending_by_position: dict[int, dict[str, Any]],
    observed_at: datetime,
    code: str,
    details: dict[str, Any] | None,
    terminal_state: str,
) -> None:
    for position in positions:
        pending = pending_by_position[int(position.id)]
        _terminal_failure_append(
            position,
            signature=str(pending.get("source_signature") or ""),
            code=str(code),
            observed_at=observed_at,
            details=details,
            recovery_id=str(pending.get("recovery_id") or ""),
        )
        _mark_recovery_state(
            position,
            state=terminal_state,
            observed_at=observed_at,
            extra={"terminal_code": str(code), "terminal_details": details or {}},
        )


def recover_promoted_selective_exits(
    db: Session,
    *,
    jupiter_client: JupiterSwapClient,
    now: datetime | None = None,
    limit: int = PROMOTED_EXIT_RECOVERY_BATCH_LIMIT,
) -> dict[str, Any]:
    observed = _aware(now) or _utc_now()
    rows = list(
        db.scalars(
            select(CanonicalParserGen4PromotedSelectivePosition)
            .where(
                CanonicalParserGen4PromotedSelectivePosition.scope == PROMOTED_SELECTIVE_SCOPE,
                CanonicalParserGen4PromotedSelectivePosition.status.in_(
                    [PROMOTED_POSITION_OPEN, PROMOTED_POSITION_OPEN_PARTIAL]
                ),
                CanonicalParserGen4PromotedSelectivePosition.remaining_token_raw > 0,
            )
            .order_by(
                CanonicalParserGen4PromotedSelectivePosition.updated_at.asc(),
                CanonicalParserGen4PromotedSelectivePosition.id.asc(),
            )
            .limit(max(1, min(int(limit), 100)))
            .with_for_update()
        )
    )

    due: dict[str, list[CanonicalParserGen4PromotedSelectivePosition]] = {}
    pending_map: dict[int, dict[str, Any]] = {}
    for position in rows:
        pending = _pending(position)
        if pending is None:
            continue
        next_retry = _aware(pending.get("next_retry_at_utc"))
        if next_retry is not None and observed < next_retry:
            continue
        recovery_id = str(pending["recovery_id"])
        due.setdefault(recovery_id, []).append(position)
        pending_map[int(position.id)] = pending

    summary = {
        "version": PROMOTED_EXIT_RECOVERY_VERSION,
        "checked_open_positions": len(rows),
        "due_recovery_groups": len(due),
        "attempted_groups": 0,
        "recovered_groups": 0,
        "superseded_groups": 0,
        "rescheduled_groups": 0,
        "terminal_groups": 0,
        "positions_closed": 0,
        "positions_partially_reduced": 0,
        "jupiter_quote_attempted": 0,
        "live_execution": False,
        "paper_execution": False,
        "signer_access": False,
        "transaction_submission": False,
    }

    for recovery_id, positions in due.items():
        summary["attempted_groups"] += 1
        first_pending = pending_map[int(positions[0].id)]
        activation_id = int(positions[0].activation_db_id)
        activation = db.scalar(
            select(CanonicalParserGen4PromotedSelectiveActivation).where(
                CanonicalParserGen4PromotedSelectiveActivation.id == activation_id
            )
        )
        if activation is None or str(activation.status) not in {
            ACTIVATION_ACTIVE,
            ACTIVATION_DRAINING,
        }:
            _terminalize_group(
                positions,
                pending_by_position=pending_map,
                observed_at=observed,
                code="EXIT_RECOVERY_LIFECYCLE_NOT_ELIGIBLE",
                details={"activation_status": getattr(activation, "status", None)},
                terminal_state="TERMINAL_LIFECYCLE_BLOCKED",
            )
            summary["terminal_groups"] += 1
            continue

        desired_raw: list[int] = []
        all_satisfied = True
        for position in positions:
            pending = pending_map[int(position.id)]
            target = max(0, int(pending.get("target_remaining_token_raw") or 0))
            desired = max(0, int(position.remaining_token_raw) - target)
            desired_raw.append(desired)
            if desired > 0:
                all_satisfied = False
        if all_satisfied:
            for position in positions:
                _mark_recovery_state(
                    position,
                    state="SUPERSEDED_BY_LATER_EXIT",
                    observed_at=observed,
                )
            summary["superseded_groups"] += 1
            continue

        scheduled_at = _aware(first_pending.get("scheduled_at_utc")) or observed
        age_seconds = max(0.0, (observed - scheduled_at).total_seconds())
        previous_attempts = max(0, int(first_pending.get("recovery_attempts") or 0))
        if (
            previous_attempts >= PROMOTED_EXIT_RECOVERY_MAX_ATTEMPTS
            or age_seconds > PROMOTED_EXIT_RECOVERY_MAX_AGE_SECONDS
        ):
            _terminalize_group(
                positions,
                pending_by_position=pending_map,
                observed_at=observed,
                code="EXIT_RECOVERY_EXHAUSTED",
                details={
                    "recovery_attempts": previous_attempts,
                    "age_seconds": age_seconds,
                    "last_error": first_pending.get("last_error"),
                },
                terminal_state="TERMINAL_EXHAUSTED",
            )
            summary["terminal_groups"] += 1
            continue

        amount_to_sell = sum(desired_raw)
        if amount_to_sell <= 0:
            continue
        summary["jupiter_quote_attempted"] += 1
        try:
            quote = _quote(
                input_mint=str(positions[0].token_mint),
                output_mint=SOL_MINT,
                amount_raw=int(amount_to_sell),
                slippage_bps=int(dict(activation.policy_snapshot or {})["slippage_bps"]),
                client=jupiter_client,
            )
        except JupiterSwapError as exc:
            error = promoted_exit_error_snapshot(exc)
            attempts = previous_attempts + 1
            recoverable = is_recoverable_promoted_exit_error(exc)
            terminal = (
                not recoverable
                or attempts >= PROMOTED_EXIT_RECOVERY_MAX_ATTEMPTS
                or age_seconds >= PROMOTED_EXIT_RECOVERY_MAX_AGE_SECONDS
            )
            if terminal:
                _terminalize_group(
                    positions,
                    pending_by_position=pending_map,
                    observed_at=observed,
                    code=str(exc.code),
                    details={
                        "recovery_attempts": attempts,
                        "age_seconds": age_seconds,
                        "jupiter_error": error,
                    },
                    terminal_state="TERMINAL_JUPITER_FAILURE",
                )
                summary["terminal_groups"] += 1
            else:
                next_retry = observed + timedelta(seconds=_next_backoff(attempts))
                for position in positions:
                    evidence = dict(position.evidence or {})
                    pending = dict(evidence.get("pending_exit_recovery") or {})
                    pending["recovery_attempts"] = attempts
                    pending["last_attempt_at_utc"] = observed.isoformat()
                    pending["next_retry_at_utc"] = next_retry.isoformat()
                    pending["last_error"] = error
                    evidence["pending_exit_recovery"] = pending
                    _history_append(
                        evidence,
                        {
                            "recovery_id": recovery_id,
                            "state": "RETRY_FAILED_RESCHEDULED",
                            "observed_at_utc": observed.isoformat(),
                            "attempt": attempts,
                            "next_retry_at_utc": next_retry.isoformat(),
                            "error": error,
                        },
                    )
                    position.evidence = evidence
                summary["rescheduled_groups"] += 1
            continue

        conservative_out = _conservative_out_amount(
            quote.result, int(dict(activation.policy_snapshot or {})["slippage_bps"])
        )
        impact_bps = max(0.0, float(quote.result.price_impact_percent) * 100.0)
        policy = dict(activation.policy_snapshot or {})
        rejection = _exit_rejection(
            policy,
            quote_latency_ms=int(quote.latency_ms),
            out_amount=int(quote.result.out_amount),
            transaction_built=bool(quote.result.transaction),
            price_impact_bps=impact_bps,
        )
        if rejection is not None:
            _terminalize_group(
                positions,
                pending_by_position=pending_map,
                observed_at=_aware(quote.received_at) or observed,
                code=rejection,
                details={
                    "quote_latency_ms": int(quote.latency_ms),
                    "price_impact_bps": impact_bps,
                    "transaction_built": bool(quote.result.transaction),
                },
                terminal_state="TERMINAL_POLICY_REJECTION",
            )
            summary["terminal_groups"] += 1
            continue

        out_allocations = _allocate_integer(int(conservative_out), desired_raw)
        fee_allocations = _allocate_integer(
            int(policy.get("estimated_network_fee_lamports") or 0), desired_raw
        )
        recovered_at = _aware(quote.received_at) or observed
        for position, sold_raw, out_lamports, fee_lamports in zip(
            positions, desired_raw, out_allocations, fee_allocations
        ):
            if sold_raw <= 0:
                _mark_recovery_state(
                    position,
                    state="SUPERSEDED_BY_LATER_EXIT",
                    observed_at=recovered_at,
                )
                continue
            pending = pending_map[int(position.id)]
            position.remaining_token_raw = max(
                0, int(position.remaining_token_raw) - int(sold_raw)
            )
            position.realized_output_lamports += int(out_lamports)
            position.allocated_exit_fee_lamports += int(fee_lamports)
            position.last_exit_signature = str(pending.get("source_signature") or "")
            position.exit_quote_latency_ms = int(quote.latency_ms)
            position.exit_price_impact_bps = float(impact_bps)
            position.exit_transaction_built = bool(quote.result.transaction)
            position.exit_copyable = True
            exit_quotes = list(position.exit_quotes or [])
            exit_quotes.append(
                {
                    "signature": str(pending.get("source_signature") or ""),
                    "sell_fraction": float(pending.get("source_sell_fraction") or 0.0),
                    "sold_token_raw": int(sold_raw),
                    "out_lamports": int(out_lamports),
                    "allocated_fee_lamports": int(fee_lamports),
                    "autonomous_exit_recovery": True,
                    "recovery_id": recovery_id,
                    "quote": {
                        **dict(quote.sanitized or {}),
                        "expected_out_amount": int(quote.result.out_amount),
                        "conservative_out_amount": int(conservative_out),
                        "slippage_haircut_applied": True,
                    },
                    "quote_requested_at": quote.requested_at.isoformat(),
                    "quote_received_at": quote.received_at.isoformat(),
                }
            )
            position.exit_quotes = exit_quotes[-100:]
            dust_limit = max(1, int(position.entry_output_token_raw * 0.001))
            target = max(0, int(pending.get("target_remaining_token_raw") or 0))
            if position.remaining_token_raw <= dust_limit or target == 0:
                position.remaining_token_raw = 0
                position.status = PROMOTED_POSITION_CLOSED
                position.closed_at = recovered_at
                position.close_reason = "MIRRORED_WALLET_EXIT_RECOVERED"
                cost = int(position.entry_input_lamports) + int(
                    position.allocated_entry_fee_lamports
                )
                proceeds = int(position.realized_output_lamports) - int(
                    position.allocated_exit_fee_lamports
                )
                position.pnl_lamports = proceeds - cost
                position.return_percent = (
                    position.pnl_lamports / cost * 100.0 if cost > 0 else None
                )
                summary["positions_closed"] += 1
            else:
                position.status = PROMOTED_POSITION_OPEN_PARTIAL
                summary["positions_partially_reduced"] += 1
            _mark_recovery_state(
                position,
                state="RECOVERED",
                observed_at=recovered_at,
                extra={
                    "sold_token_raw": int(sold_raw),
                    "out_lamports": int(out_lamports),
                    "quote_latency_ms": int(quote.latency_ms),
                    "price_impact_bps": impact_bps,
                },
            )
        summary["recovered_groups"] += 1

    return summary
