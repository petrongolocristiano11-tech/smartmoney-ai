from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class LiveOperationsRunRequest(BaseModel):
    position_limit: int = Field(default=100, ge=1, le=500)
    reconcile_limit: int = Field(default=50, ge=1, le=500)


class LiveOperationsReconcileRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=500)


class LiveRiskCooldownResetRequest(BaseModel):
    confirmation: str

    @field_validator("confirmation")
    @classmethod
    def validate_confirmation(cls, value: str) -> str:
        normalized = str(value).strip()
        if normalized != "RESET RISK COOLDOWN":
            raise ValueError("Usa esattamente: RESET RISK COOLDOWN")
        return normalized


class LiveRiskStateResponse(BaseModel):
    id: int
    mode: Literal["DRY_RUN", "LIVE"]
    generation: int
    starting_equity_sol: float
    current_equity_sol: float
    peak_equity_sol: float
    realized_pnl_sol: float
    drawdown_percent: float
    loss_streak: int
    cooldown_until: datetime | None
    blocked_reason: str | None
    last_loss_at: datetime | None
    last_fill_at: datetime | None
    updated_at: datetime


class LivePositionMonitorResponse(BaseModel):
    status: Literal["STOPPED", "IDLE", "RUNNING", "DEGRADED", "ERROR"]
    online: bool
    lease_active: bool
    worker_id: str | None
    lease_owner: str | None
    lease_expires_at: datetime | None
    heartbeat_at: datetime | None
    last_run_started_at: datetime | None
    last_run_completed_at: datetime | None
    total_runs: int
    positions_scanned: int
    quotes_succeeded: int
    quotes_failed: int
    exits_triggered: int
    exits_completed: int
    exits_failed: int
    orders_reconciled: int
    reconciliation_failed: int
    last_error_code: str | None
    last_error_message: str | None
    updated_at: datetime


class LiveOperationsOverviewResponse(BaseModel):
    mode: str
    generation: int | None
    automatic_exits_enabled: bool
    monitor_runtime_enabled: bool
    risk: LiveRiskStateResponse | None
    monitor: LivePositionMonitorResponse
    open_positions: int
    exit_pending_positions: int
    reconciliation_pending_orders: int
    last_auto_exit_at: datetime | None


class LivePositionMonitorCycleResponse(BaseModel):
    started_at: datetime
    completed_at: datetime
    mode: str
    generation: int | None
    automatic_exits_enabled: bool
    positions_scanned: int
    quotes_succeeded: int
    quotes_failed: int
    exits_triggered: int
    exits_completed: int
    exits_failed: int
    items: list[dict]
    reconciliation: dict
