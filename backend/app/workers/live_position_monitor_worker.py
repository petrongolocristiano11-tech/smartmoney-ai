from __future__ import annotations

import asyncio
import logging
import socket
from contextlib import suppress
from uuid import uuid4

from backend.app.core.config import settings
from backend.app.database.session import SessionLocal
from backend.app.services.live_position_automation_service import run_position_monitor_cycle
from backend.app.services.live_position_monitor_state_service import (
    acquire_monitor_lease,
    heartbeat_monitor,
    release_monitor_lease,
    update_monitor_run,
    utc_now,
)


logger = logging.getLogger("smartmoney.position_monitor")


class LivePositionMonitorWorker:
    def __init__(self) -> None:
        self.worker_id = f"{socket.gethostname()}:{uuid4().hex[:12]}"
        self._stop_event = asyncio.Event()

    def request_stop(self) -> None:
        self._stop_event.set()

    async def run(self) -> None:
        logger.info("position_monitor_starting worker_id=%s", self.worker_id)
        while not self._stop_event.is_set():
            with SessionLocal() as db:
                acquired = acquire_monitor_lease(
                    db,
                    worker_id=self.worker_id,
                    lease_seconds=settings.LIVE_POSITION_MONITOR_LEASE_SECONDS,
                )
            if not acquired:
                await self._wait(settings.LIVE_POSITION_MONITOR_INTERVAL_SECONDS)
                continue

            started_at = utc_now()
            summary: dict = {}
            error: Exception | None = None
            try:
                with SessionLocal() as db:
                    heartbeat_monitor(
                        db,
                        worker_id=self.worker_id,
                        lease_seconds=settings.LIVE_POSITION_MONITOR_LEASE_SECONDS,
                        status="RUNNING",
                    )
                summary = await asyncio.to_thread(self._run_cycle)
            except asyncio.CancelledError:
                raise
            except Exception as exception:
                error = exception
                logger.exception("position_monitor_cycle_failed worker_id=%s", self.worker_id)
            finally:
                completed_at = utc_now()
                with SessionLocal() as db:
                    update_monitor_run(
                        db,
                        summary=summary,
                        started_at=started_at,
                        completed_at=completed_at,
                        error=error,
                    )
                    heartbeat_monitor(
                        db,
                        worker_id=self.worker_id,
                        lease_seconds=settings.LIVE_POSITION_MONITOR_LEASE_SECONDS,
                        status="ERROR" if error else "IDLE",
                    )

            await self._wait(settings.LIVE_POSITION_MONITOR_INTERVAL_SECONDS)

        with SessionLocal() as db:
            with suppress(Exception):
                release_monitor_lease(db, worker_id=self.worker_id)
        logger.info("position_monitor_stopped worker_id=%s", self.worker_id)

    def _run_cycle(self) -> dict:
        with SessionLocal() as db:
            return run_position_monitor_cycle(
                db,
                position_limit=settings.LIVE_POSITION_MONITOR_BATCH_SIZE,
                reconcile_limit=settings.LIVE_ORDER_RECONCILE_BATCH_SIZE,
            )

    async def _wait(self, seconds: float) -> None:
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=max(1.0, float(seconds)))
        except TimeoutError:
            return
