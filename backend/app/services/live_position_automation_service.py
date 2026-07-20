from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from backend.app.core.constants import SOL_MINT
from backend.app.models.live_position import LivePosition
from backend.app.services.jupiter_swap_client import JupiterSwapClient
from backend.app.services.live_copy_trading_engine import close_live_position
from backend.app.services.live_order_reconciliation_service import reconcile_live_orders
from backend.app.services.live_risk_state_service import refresh_risk_state
from backend.app.services.live_trading_policy_service import get_or_create_live_policy, record_live_event
from backend.app.services.solana_rpc import SolanaRpcClient
from backend.app.services.solana_transaction_signer import SolanaTransactionSigner


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def evaluate_exit_reason(position: LivePosition, policy, *, now: datetime | None = None) -> str | None:
    now = now or utc_now()
    roi = float(position.unrealized_roi_percent or 0.0)

    if policy.stop_loss_enabled and roi <= -abs(float(policy.stop_loss_percent)):
        return "STOP_LOSS"

    if policy.trailing_stop_enabled:
        current = float(position.current_value_sol or 0.0)
        stop_value = float(position.trailing_stop_value_sol or 0.0)
        high_roi = float(position.high_watermark_roi_percent or 0.0)
        if high_roi > 0 and stop_value > 0 and current <= stop_value:
            return "TRAILING_STOP"

    if policy.take_profit_enabled and roi >= abs(float(policy.take_profit_percent)):
        return "TAKE_PROFIT"

    opened = _as_utc(position.opened_at)
    if policy.time_exit_enabled and opened is not None:
        age_minutes = (now - opened).total_seconds() / 60.0
        if age_minutes >= int(policy.max_position_age_minutes):
            return "TIME_EXIT"

    return None


def quote_and_update_position(
    db: Session,
    *,
    position: LivePosition,
    policy,
    jupiter_client: JupiterSwapClient,
    now: datetime | None = None,
) -> dict:
    now = now or utc_now()
    quantity = int(Decimal(position.quantity_raw or 0))
    quote = jupiter_client.get_order(
        input_mint=position.token_mint,
        output_mint=SOL_MINT,
        amount_raw=quantity,
        taker=None,
        slippage_bps=policy.max_slippage_bps,
    )
    value_sol = float(quote.out_amount) / 1_000_000_000
    cost = float(position.cost_basis_sol or 0.0)
    pnl = value_sol - cost
    roi = pnl / cost * 100.0 if cost > 0 else 0.0

    position.current_value_sol = value_sol
    position.unrealized_pnl_sol = pnl
    position.unrealized_roi_percent = roi
    position.last_quote_at = now
    position.last_exit_evaluation_at = now

    high_value = max(float(position.high_watermark_value_sol or 0.0), value_sol)
    high_roi = max(float(position.high_watermark_roi_percent or -100.0), roi)
    position.high_watermark_value_sol = high_value
    position.high_watermark_roi_percent = high_roi
    if policy.trailing_stop_enabled and high_value > 0:
        position.trailing_stop_value_sol = high_value * (
            1.0 - float(policy.trailing_stop_percent) / 100.0
        )

    db.commit()
    db.refresh(position)
    return {
        "quote": quote,
        "current_value_sol": value_sol,
        "unrealized_pnl_sol": pnl,
        "unrealized_roi_percent": roi,
        "exit_reason": evaluate_exit_reason(position, policy, now=now),
    }


def run_position_monitor_cycle(
    db: Session,
    *,
    jupiter_client: JupiterSwapClient | None = None,
    rpc_client: SolanaRpcClient | None = None,
    signer: SolanaTransactionSigner | None = None,
    position_limit: int = 100,
    reconcile_limit: int = 50,
) -> dict:
    started_at = utc_now()
    policy = get_or_create_live_policy(db)
    summary = {
        "started_at": started_at,
        "completed_at": None,
        "mode": policy.mode,
        "generation": None,
        "automatic_exits_enabled": bool(policy.automatic_exits_enabled),
        "positions_scanned": 0,
        "quotes_succeeded": 0,
        "quotes_failed": 0,
        "exits_triggered": 0,
        "exits_completed": 0,
        "exits_failed": 0,
        "items": [],
        "reconciliation": {"scanned": 0, "confirmed": 0, "failed": 0, "unknown": 0, "errors": []},
    }

    if policy.mode not in {"DRY_RUN", "LIVE"}:
        summary["completed_at"] = utc_now()
        return summary

    generation = max(1, int(policy.dry_run_generation or 1)) if policy.mode == "DRY_RUN" else 1
    summary["generation"] = generation
    jupiter_client = jupiter_client or JupiterSwapClient()

    positions = (
        db.query(LivePosition)
        .filter(
            LivePosition.mode == policy.mode,
            LivePosition.generation == generation,
            LivePosition.status == "OPEN",
            LivePosition.quantity_raw > 0,
        )
        .order_by(LivePosition.id.asc())
        .limit(max(1, min(int(position_limit), 500)))
        .all()
    )

    for position in positions:
        summary["positions_scanned"] += 1
        item = {"position_id": position.id, "token_mint": position.token_mint, "status": "QUOTED"}
        try:
            result = quote_and_update_position(
                db,
                position=position,
                policy=policy,
                jupiter_client=jupiter_client,
            )
            summary["quotes_succeeded"] += 1
            item.update(
                {
                    "current_value_sol": result["current_value_sol"],
                    "unrealized_roi_percent": result["unrealized_roi_percent"],
                    "exit_reason": result["exit_reason"],
                }
            )
            if policy.automatic_exits_enabled and result["exit_reason"]:
                summary["exits_triggered"] += 1
                order = close_live_position(
                    db,
                    position_id=position.id,
                    reason=result["exit_reason"],
                    percentage=policy.auto_exit_position_percentage,
                    execution_origin="AUTO_EXIT",
                    jupiter_client=jupiter_client,
                    rpc_client=rpc_client,
                    signer=signer,
                )
                item["order_id"] = order.id
                item["order_status"] = order.status
                if order.status in {"DRY_RUN", "FILLED"}:
                    summary["exits_completed"] += 1
                    item["status"] = "EXIT_COMPLETED"
                else:
                    summary["exits_failed"] += 1
                    item["status"] = "EXIT_FAILED"
        except Exception as exception:
            db.rollback()
            summary["quotes_failed"] += 1
            item["status"] = "ERROR"
            item["error_type"] = type(exception).__name__
            record_live_event(
                db,
                generation=generation,
                event_type="POSITION_MONITOR_ERROR",
                severity="WARNING",
                message="Monitor posizione: quotazione o valutazione non completata.",
                payload={
                    "position_id": position.id,
                    "token_mint": position.token_mint,
                    "error_type": type(exception).__name__,
                },
            )
            db.commit()
        summary["items"].append(item)

    if policy.mode == "LIVE":
        summary["reconciliation"] = reconcile_live_orders(
            db,
            rpc_client=rpc_client,
            limit=reconcile_limit,
        )

    refresh_risk_state(
        db,
        mode=policy.mode,
        generation=generation,
        commit=True,
    )
    summary["completed_at"] = utc_now()
    return summary
