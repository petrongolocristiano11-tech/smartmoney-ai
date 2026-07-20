from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.live_trading_security import require_live_trading_key
from backend.app.database.session import get_db
from backend.app.models.live_copy_order import LiveCopyOrder
from backend.app.models.live_position import LivePosition
from backend.app.schemas.live_operations import (
    LiveOperationsOverviewResponse,
    LiveOperationsReconcileRequest,
    LiveOperationsRunRequest,
    LivePositionMonitorCycleResponse,
    LiveRiskCooldownResetRequest,
    LiveRiskStateResponse,
)
from backend.app.services.jupiter_swap_client import JupiterSwapClient
from backend.app.services.live_order_reconciliation_service import reconcile_live_orders
from backend.app.services.live_position_automation_service import run_position_monitor_cycle
from backend.app.services.live_position_monitor_state_service import (
    get_or_create_monitor_state,
    serialize_monitor_state,
    update_monitor_run,
)
from backend.app.services.live_risk_state_service import (
    refresh_risk_state,
    reset_risk_cooldown,
    serialize_risk_state,
)
from backend.app.services.live_trading_policy_service import get_or_create_live_policy, record_live_event
from backend.app.services.solana_rpc import SolanaRpcClient
from backend.app.services.solana_transaction_signer import SolanaTransactionSigner


router = APIRouter(
    prefix="/live-trading/operations",
    tags=["Live Trading Operations"],
    dependencies=[Depends(require_live_trading_key)],
)


def get_jupiter_client() -> JupiterSwapClient:
    return JupiterSwapClient()


def get_rpc_client() -> SolanaRpcClient:
    return SolanaRpcClient()


def get_signer() -> SolanaTransactionSigner:
    return SolanaTransactionSigner()


def _mode_generation(policy) -> tuple[str | None, int | None]:
    if policy.mode == "DRY_RUN":
        return "DRY_RUN", max(1, int(policy.dry_run_generation or 1))
    if policy.mode == "LIVE":
        return "LIVE", 1
    return None, None


@router.get("/overview", response_model=LiveOperationsOverviewResponse)
def get_operations_overview(db: Session = Depends(get_db)):
    policy = get_or_create_live_policy(db)
    mode, generation = _mode_generation(policy)
    monitor = get_or_create_monitor_state(db)
    risk_payload = None
    open_positions = 0
    exit_pending = 0
    reconciliation_pending = 0
    last_auto_exit_at = None

    if mode is not None and generation is not None:
        risk = refresh_risk_state(
            db,
            mode=mode,
            generation=generation,
            commit=True,
        )
        risk_payload = serialize_risk_state(risk)
        open_positions = int(
            db.query(func.count(LivePosition.id))
            .filter(
                LivePosition.mode == mode,
                LivePosition.generation == generation,
                LivePosition.status == "OPEN",
            )
            .scalar()
            or 0
        )
        exit_pending = int(
            db.query(func.count(LivePosition.id))
            .filter(
                LivePosition.mode == mode,
                LivePosition.generation == generation,
                LivePosition.status == "OPEN",
                LivePosition.exit_pending.is_(True),
            )
            .scalar()
            or 0
        )
        reconciliation_pending = int(
            db.query(func.count(LiveCopyOrder.id))
            .filter(
                LiveCopyOrder.mode == "LIVE",
                LiveCopyOrder.reconciliation_status.in_(("PENDING", "UNKNOWN")),
            )
            .scalar()
            or 0
        )
        last_auto_exit_at = (
            db.query(func.max(LiveCopyOrder.executed_at))
            .filter(
                LiveCopyOrder.mode == mode,
                LiveCopyOrder.generation == generation,
                LiveCopyOrder.execution_origin == "AUTO_EXIT",
                LiveCopyOrder.status.in_(("DRY_RUN", "FILLED")),
            )
            .scalar()
        )

    return {
        "mode": policy.mode,
        "generation": generation,
        "automatic_exits_enabled": policy.automatic_exits_enabled,
        "monitor_runtime_enabled": settings.RUN_LIVE_POSITION_MONITOR,
        "risk": risk_payload,
        "monitor": serialize_monitor_state(monitor),
        "open_positions": open_positions,
        "exit_pending_positions": exit_pending,
        "reconciliation_pending_orders": reconciliation_pending,
        "last_auto_exit_at": last_auto_exit_at,
    }


@router.post("/run-once", response_model=LivePositionMonitorCycleResponse)
def run_operations_once(
    payload: LiveOperationsRunRequest,
    db: Session = Depends(get_db),
    jupiter_client: JupiterSwapClient = Depends(get_jupiter_client),
    rpc_client: SolanaRpcClient = Depends(get_rpc_client),
    signer: SolanaTransactionSigner = Depends(get_signer),
):
    from backend.app.services.live_position_monitor_state_service import utc_now

    started_at = utc_now()
    error = None
    summary: dict = {}
    try:
        summary = run_position_monitor_cycle(
            db,
            jupiter_client=jupiter_client,
            rpc_client=rpc_client,
            signer=signer,
            position_limit=payload.position_limit,
            reconcile_limit=payload.reconcile_limit,
        )
        return summary
    except Exception as exception:
        error = exception
        raise
    finally:
        update_monitor_run(
            db,
            summary=summary,
            started_at=started_at,
            completed_at=utc_now(),
            error=error,
        )


@router.post("/reconcile")
def reconcile_operations(
    payload: LiveOperationsReconcileRequest,
    db: Session = Depends(get_db),
    rpc_client: SolanaRpcClient = Depends(get_rpc_client),
):
    return reconcile_live_orders(db, rpc_client=rpc_client, limit=payload.limit)


@router.post("/risk/cooldown/reset", response_model=LiveRiskStateResponse)
def reset_operations_cooldown(
    payload: LiveRiskCooldownResetRequest,
    db: Session = Depends(get_db),
):
    policy = get_or_create_live_policy(db)
    mode, generation = _mode_generation(policy)
    if mode is None or generation is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=409, detail={"code": "LIVE_TRADING_DISABLED", "message": "Policy disabilitata."})
    state = reset_risk_cooldown(db, mode=mode, generation=generation)
    record_live_event(
        db,
        generation=generation,
        event_type="RISK_COOLDOWN_RESET",
        severity="WARNING",
        message="Cooldown rischio azzerato manualmente.",
        commit=True,
    )
    return serialize_risk_state(state)
