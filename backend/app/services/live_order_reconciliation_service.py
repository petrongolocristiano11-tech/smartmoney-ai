from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from backend.app.models.live_copy_order import LiveCopyOrder
from backend.app.services.live_trading_policy_service import record_live_event
from backend.app.services.solana_rpc import SolanaRpcClient


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def reconcile_live_orders(
    db: Session,
    *,
    rpc_client: SolanaRpcClient | None = None,
    limit: int = 50,
) -> dict:
    rpc_client = rpc_client or SolanaRpcClient()
    orders = (
        db.query(LiveCopyOrder)
        .filter(
            LiveCopyOrder.mode == "LIVE",
            LiveCopyOrder.transaction_signature.is_not(None),
            LiveCopyOrder.reconciliation_status.in_(("PENDING", "UNKNOWN")),
        )
        .order_by(LiveCopyOrder.id.asc())
        .limit(max(1, min(int(limit), 500)))
        .all()
    )

    summary = {
        "scanned": len(orders),
        "confirmed": 0,
        "failed": 0,
        "unknown": 0,
        "errors": [],
    }
    now = utc_now()
    for order in orders:
        try:
            status = rpc_client.get_signature_status(order.transaction_signature)
            order.reconciliation_attempts = int(order.reconciliation_attempts or 0) + 1
            order.last_reconciled_at = now
            order.confirmation_status = status.get("confirmation_status")
            order.on_chain_error = status.get("error")

            if status.get("error") is not None:
                order.reconciliation_status = "FAILED"
                summary["failed"] += 1
                record_live_event(
                    db,
                    order_id=order.id,
                    generation=order.generation,
                    event_type="ORDER_RECONCILIATION_FAILED",
                    severity="ERROR",
                    message="La transazione LIVE risulta fallita on-chain.",
                    payload={
                        "signature": order.transaction_signature,
                        "error": status.get("error"),
                    },
                )
            elif status.get("found") and status.get("confirmation_status") in {
                "confirmed",
                "finalized",
            }:
                order.reconciliation_status = "CONFIRMED"
                order.confirmed_at = now
                summary["confirmed"] += 1
                record_live_event(
                    db,
                    order_id=order.id,
                    generation=order.generation,
                    event_type="ORDER_RECONCILED",
                    message="Ordine LIVE confermato on-chain.",
                    payload={
                        "signature": order.transaction_signature,
                        "confirmation_status": status.get("confirmation_status"),
                        "slot": status.get("slot"),
                    },
                )
            else:
                order.reconciliation_status = "UNKNOWN"
                summary["unknown"] += 1
        except Exception as exception:
            db.rollback()
            order = db.query(LiveCopyOrder).filter(LiveCopyOrder.id == order.id).one()
            order.reconciliation_attempts = int(order.reconciliation_attempts or 0) + 1
            order.last_reconciled_at = utc_now()
            order.reconciliation_status = "UNKNOWN"
            summary["unknown"] += 1
            summary["errors"].append(
                {"order_id": order.id, "error_type": type(exception).__name__}
            )
        db.commit()

    return summary
